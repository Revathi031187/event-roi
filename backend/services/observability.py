"""
Langfuse observability wiring for the Event ROI pipeline.

Scope: this module covers LLM/agent-layer tracing and evals only. It does
NOT and cannot cover infrastructure metrics (CPU, memory, non-LLM request
latency) — Langfuse doesn't ingest those. See LANGFUSE_OBSERVABILITY_REFERENCE.md.

Design rules this module enforces everywhere:
  - Fail open. Nothing in here may raise into a caller's request path. If
    Langfuse is unreachable, misconfigured, or simply not set up
    (LANGFUSE_PUBLIC_KEY/SECRET_KEY absent), every helper below degrades to a
    safe no-op and the pipeline behaves exactly as it did before this file
    existed.
  - Mask before anything leaves the process. `mask_sensitive_data` is wired
    into the client at construction time (Langfuse SDK requirement — masking
    must be configured before any span carries content).
  - Every trace gets session_id + environment. There is no user auth in this
    app (no login), so user_id is intentionally left unset rather than
    fabricated — see the reference doc's "what's intentionally not built".

API surface used here was verified against the *installed* langfuse==4.15.4
package (not memorized/generic docs) — see the repo's
LANGFUSE_OBSERVABILITY_REFERENCE.md "SDK verification" note for how. Re-verify
with the snippet below before bumping the pin:

    python -c "from langfuse import Langfuse; import inspect; \
        print(inspect.signature(Langfuse.__init__))"
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from config import settings

logger = logging.getLogger("event_roi.observability")

try:
    from langfuse import Langfuse, propagate_attributes
    _LANGFUSE_IMPORT_ERROR: Optional[Exception] = None
except Exception as _exc:  # pragma: no cover - defensive, see fail-open rule
    Langfuse = None  # type: ignore[assignment,misc]
    propagate_attributes = None  # type: ignore[assignment]
    _LANGFUSE_IMPORT_ERROR = _exc

_MAX_TRACED_STRING = 8000  # cap payload size landing in any single field

# ── Masking ────────────────────────────────────────────────────────────────
# Domain-specific, not a generic placeholder: this app (a) can receive raw
# Databricks credentials in a request body (GenerateRequest.databricks_token),
# (b) reads a Gemini API key from settings, and (c) pipes freeform user text
# (additional_context) and Databricks Genie query results (which may contain
# account/contact-level rows) into LLM prompts. All of that can end up in
# traced input/output unless masked here first.

_SECRET_KEY_NAME_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|access[_-]?key"
    r"|client[_-]?secret|\bpat\b|credential)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_DATABRICKS_PAT_RE = re.compile(r"\bdapi[0-9a-f]{20,}\b", re.IGNORECASE)
_GOOGLE_API_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)


def _mask_string(value: str) -> str:
    value = _DATABRICKS_PAT_RE.sub("[REDACTED_DATABRICKS_TOKEN]", value)
    value = _GOOGLE_API_KEY_RE.sub("[REDACTED_API_KEY]", value)
    value = _BEARER_RE.sub("Bearer [REDACTED_TOKEN]", value)
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _PHONE_RE.sub("[REDACTED_PHONE]", value)
    return value


def _mask_value(key: Optional[str], value: Any) -> Any:
    if isinstance(value, str):
        if key and _SECRET_KEY_NAME_RE.search(str(key)) and value:
            return "[REDACTED]"
        return _mask_string(value)
    if isinstance(value, dict):
        return {k: _mask_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_value(key, v) for v in value]
    return value


def mask_sensitive_data(*, data: Any, **_kwargs: Any) -> Any:
    """Langfuse `mask` hook — see MaskFunction protocol in langfuse.types.

    Fails CLOSED (withholds content) on an internal masking error, unlike the
    rest of this module which fails open on availability — a masking bug
    should never result in unredacted content reaching Langfuse.
    """
    try:
        return _mask_value(None, data)
    except Exception:
        logger.exception("[Observability] Masking function raised — withholding content")
        return "[MASKING_ERROR — CONTENT_WITHHELD]"


def _truncate(value: Any, limit: int = _MAX_TRACED_STRING) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"...[truncated, {len(value)} chars total]"
    return value


# ── Client lifecycle ─────────────────────────────────────────────────────────

_client: Optional["Langfuse"] = None
_enabled: bool = False


def init_langfuse() -> None:
    """Call once at app startup (FastAPI lifespan). Idempotent."""
    global _client, _enabled

    if _client is not None:
        return

    if _LANGFUSE_IMPORT_ERROR is not None:
        logger.warning(
            "[Observability] langfuse package failed to import (%s) — "
            "tracing disabled, app continues normally.",
            _LANGFUSE_IMPORT_ERROR,
        )
        return

    if not settings.langfuse_enabled:
        logger.info(
            "[Observability] LANGFUSE_PUBLIC_KEY/SECRET_KEY not set — "
            "tracing disabled. Add both to backend/.env to enable."
        )
        return

    try:
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            environment=settings.langfuse_environment,
            mask=mask_sensitive_data,
        )
        _enabled = True
        logger.info(
            "[Observability] Langfuse client initialized (host=%s, environment=%s)",
            settings.langfuse_host,
            settings.langfuse_environment,
        )
    except Exception:
        logger.exception(
            "[Observability] Langfuse client init failed — tracing disabled, "
            "app continues normally (fail-open)."
        )
        _client = None
        _enabled = False


def shutdown_langfuse() -> None:
    """Call once at app shutdown (FastAPI lifespan) to flush queued events."""
    if _client is None:
        return
    try:
        _client.flush()
    except Exception:
        logger.exception("[Observability] Langfuse flush on shutdown failed")


def is_enabled() -> bool:
    return _enabled and _client is not None


def get_client() -> Optional["Langfuse"]:
    """Return the process-wide Langfuse client, or None if tracing is
    disabled. Reused by offline eval scripts (backend/evals/) so they trace
    against the exact same, already-authenticated client the app itself
    uses — no key is ever read/printed/exported by anything that imports
    this module."""
    return _client


# ── Tracing helpers ──────────────────────────────────────────────────────────
# Every helper below is a no-op (never raises) when tracing is disabled.


@contextmanager
def traced_pipeline_run(
    job_id: str,
    event_name: str,
    additional_context: str = "",
) -> Iterator[Optional[Any]]:
    """Root span for one end-to-end plan -> query -> synthesize run.

    session_id = job_id (one job is one user-facing "session" in this app —
    there's no multi-turn conversation). user_id intentionally omitted: this
    app has no auth layer, so there is no real per-user identity to attach —
    see LANGFUSE_OBSERVABILITY_REFERENCE.md.
    """
    if not is_enabled():
        yield None
        return

    try:
        with propagate_attributes(
            session_id=job_id,
            environment=settings.langfuse_environment,
            tags=["event-roi-pipeline"],
            metadata={"event_name": _truncate(event_name)},
        ):
            with _client.start_as_current_observation(
                as_type="span",
                name="event_roi_pipeline",
                input=_truncate(
                    {
                        "event_name": event_name,
                        "additional_context": additional_context,
                    }
                ),
            ) as root_span:
                yield root_span
    except Exception:
        logger.exception("[Observability] traced_pipeline_run failed — continuing untraced")
        yield None


@contextmanager
def traced_generation(
    name: str,
    model: str,
    input_data: Any,
    metadata: Optional[dict] = None,
) -> Iterator[Optional[Any]]:
    """Wrap one Gemini call site. Usage:

        with traced_generation("gemini-plan-questions", model, prompt) as gen:
            response = await client.generate_content(...)
            if gen: gen.update(output=..., usage_details={...})
    """
    if not is_enabled():
        yield None
        return
    try:
        with _client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=_truncate(input_data),
            metadata=metadata,
        ) as gen:
            yield gen
    except Exception:
        logger.exception("[Observability] traced_generation(%s) failed — continuing untraced", name)
        yield None


@contextmanager
def traced_tool(name: str, input_data: Any, metadata: Optional[dict] = None) -> Iterator[Optional[Any]]:
    """Wrap one tool-call site (Databricks Genie NL->SQL ask)."""
    if not is_enabled():
        yield None
        return
    try:
        with _client.start_as_current_observation(
            as_type="tool",
            name=name,
            input=_truncate(input_data),
            metadata=metadata,
        ) as span:
            yield span
    except Exception:
        logger.exception("[Observability] traced_tool(%s) failed — continuing untraced", name)
        yield None


def usage_details_from_gemini(response: Any) -> Optional[dict]:
    """Map google-genai's usage_metadata onto Langfuse's usage_details shape.
    Returns None (rather than a partial/guessed dict) if the response doesn't
    carry usage metadata, so callers can skip attaching it rather than
    reporting fabricated zeros."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    try:
        return {
            "input": getattr(usage, "prompt_token_count", None) or 0,
            "output": getattr(usage, "candidates_token_count", None) or 0,
            "total": getattr(usage, "total_token_count", None) or 0,
        }
    except Exception:
        return None


# ── Score push (Phase E) ─────────────────────────────────────────────────────


def push_score(
    *,
    name: str,
    value: Any,
    trace_id: Optional[str] = None,
    observation_id: Optional[str] = None,
    data_type: Optional[str] = None,
    comment: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """Push one custom score via the Scores API (create_score). Returns
    whether the push was attempted successfully (queued for export) — NOT
    proof of delivery; see Phase F validation notes in the reference doc for
    why those are two different claims. Never raises.

    Every call site using this MUST log on every outcome (success, exception,
    AND "skipped because tracing disabled / no active trace") — a silent skip
    here is exactly the failure mode Phase D3 warns about: indistinguishable
    from "nothing to report" if it isn't logged.
    """
    if not is_enabled():
        logger.info(
            "[Observability] push_score(%s) skipped — tracing disabled", name
        )
        return False
    if not trace_id:
        logger.warning(
            "[Observability] push_score(%s) skipped — no trace_id in context "
            "(precondition not met, not a silent success)",
            name,
        )
        return False
    try:
        _client.create_score(
            name=name,
            value=value,
            trace_id=trace_id,
            observation_id=observation_id,
            data_type=data_type,
            comment=comment,
            metadata=metadata,
            environment=settings.langfuse_environment,
        )
        logger.info("[Observability] push_score(%s=%s) queued for trace=%s", name, value, trace_id)
        return True
    except Exception:
        logger.exception("[Observability] push_score(%s) raised — score NOT sent", name)
        return False


def current_trace_id() -> Optional[str]:
    if not is_enabled():
        return None
    try:
        return _client.get_current_trace_id()
    except Exception:
        logger.exception("[Observability] get_current_trace_id() failed")
        return None

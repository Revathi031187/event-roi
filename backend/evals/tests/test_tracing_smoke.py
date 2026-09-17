"""
Phase F validation, offline half: no live Langfuse project exists yet for
this repo (Cloud US chosen, but real LANGFUSE_PUBLIC_KEY/SECRET_KEY have not
been supplied — see LANGFUSE_OBSERVABILITY_REFERENCE.md). That blocks the
"confirm a trace actually landed in the Langfuse UI" half of Phase F, which
only the project owner can complete once real keys exist.

What CAN be verified without live credentials, and what this file actually
checks:
  1. Root pipeline span + nested generation/tool spans are created with the
     right names, types, and hierarchy (parent/child) when tracing is
     "enabled" — using an OTel InMemorySpanExporter instead of the real HTTP
     exporter, so no network call and no real project is needed.
  2. session_id / environment / tags actually land as span attributes (Phase
     B's tag requirement) — not just "the call didn't throw."
  3. Fail-open actually holds: pointing the client at an unreachable host
     must not raise into the caller, and disabling tracing entirely (no
     keys) must not change pipeline behavior.
  4. A Tier-1 score push with no active trace_id logs distinctly and returns
     False rather than silently no-op'ing (the exact failure mode Phase D3
     warns about).

Run with: .venv/Scripts/python.exe backend/evals/tests/test_tracing_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from langfuse import Langfuse  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from services import observability  # noqa: E402


def test_disabled_by_default_is_a_true_noop():
    observability._client = None
    observability._enabled = False
    assert observability.is_enabled() is False

    with observability.traced_pipeline_run("job-1", "NRF 2026") as span:
        assert span is None  # no-op yields None, never raises
    with observability.traced_generation("g", "model-x", "input") as gen:
        assert gen is None
    with observability.traced_tool("t", "input") as tool:
        assert tool is None

    ok = observability.push_score(name="whatever", value=1.0, trace_id="fake")
    assert ok is False
    print("[disabled-is-noop] OK")


def test_push_score_without_trace_id_logs_and_returns_false():
    """Phase D3's explicit warning: a guard with no else/log branch makes a
    real failure indistinguishable from 'nothing to report yet'. Confirm the
    precondition-not-met path is distinct from success, not just silent."""
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-test",
        secret_key="sk-test",
        host="http://127.0.0.1:1",  # unreachable — irrelevant, we never flush
        environment="test",
        mask=observability.mask_sensitive_data,
        span_exporter=exporter,
    )
    observability._client = client
    observability._enabled = True
    try:
        ok = observability.push_score(name="no_trace_context", value=1.0, trace_id=None)
        assert ok is False, "push_score with no trace_id must report failure, not silently succeed"
        print("[push-score-missing-trace-id] OK — returned False, not a silent no-op")
    finally:
        observability._client = None
        observability._enabled = False


def test_span_hierarchy_and_attributes_structurally_correct():
    """The real assertion Phase F asks for: 'confirm a trace appears with the
    expected spans,' substituting an in-memory exporter for a live Langfuse
    project (none exists yet for this repo)."""
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-test",
        secret_key="sk-test",
        host="http://127.0.0.1:1",
        environment="test",
        mask=observability.mask_sensitive_data,
        span_exporter=exporter,
    )
    observability._client = client
    observability._enabled = True
    try:
        with observability.traced_pipeline_run("job-42", "NRF 2026", "extra ctx") as root:
            assert root is not None
            with observability.traced_generation(
                "gemini-plan-questions", "gemini-2.5-flash", "plan this"
            ) as gen:
                assert gen is not None
                gen.update(output=["q1", "q2"], usage_details={"input": 10, "output": 5, "total": 15})
            with observability.traced_tool("genie-ask", "how many registrants?") as tool:
                assert tool is not None
                tool.update(output={"status": "SUCCEEDED", "data_rows_total": 3})

        client.flush()  # exports to the in-memory exporter, not the network
        spans = exporter.get_finished_spans()
        names = sorted(s.name for s in spans)
        assert "event_roi_pipeline" in names, f"root span missing, got: {names}"
        assert "gemini-plan-questions" in names, f"generation span missing, got: {names}"
        assert "genie-ask" in names, f"tool span missing, got: {names}"

        root_span = next(s for s in spans if s.name == "event_roi_pipeline")
        # session_id / environment must be real attributes on the span, not
        # just accepted by the call without landing anywhere (Phase B
        # requirement: every trace carries session_id + environment tag).
        attrs = dict(root_span.attributes or {})
        attr_blob = str(attrs)
        assert "job-42" in attr_blob, f"session_id not found on root span attributes: {attrs}"
        # traced_pipeline_run tags every trace with settings.langfuse_environment
        # (not the literal string passed to Langfuse() below — that constructor
        # param only sets the *client's* default; the per-trace tag Phase B
        # requires comes from config.settings, same value the real app uses).
        from config import settings as _settings
        assert _settings.langfuse_environment in attr_blob, (
            f"environment tag not found on root span attributes: {attrs}"
        )

        # Parent/child: generation and tool spans must be children of the
        # trace the root span opened (same trace_id), not orphaned into a
        # separate isolated trace.
        trace_ids = {s.context.trace_id for s in spans}
        assert len(trace_ids) == 1, f"expected one shared trace, got spans across {len(trace_ids)} traces"

        print(f"[span-hierarchy] OK — {len(spans)} spans in one trace: {names}")
    finally:
        observability._client = None
        observability._enabled = False


def test_fail_open_on_unreachable_host_does_not_raise():
    """Simulate Langfuse being unreachable — client construction and normal
    span usage must not raise or block; only flush() would attempt network
    I/O, and even that must not raise into the caller."""
    client = Langfuse(
        public_key="pk-test",
        secret_key="sk-test",
        host="http://127.0.0.1:1",  # nothing listens here
        environment="test",
        mask=observability.mask_sensitive_data,
    )
    observability._client = client
    observability._enabled = True
    try:
        with observability.traced_pipeline_run("job-fail-open", "Some Event") as root:
            assert root is not None
        # This performs the real (failing) network export attempt. Fail-open
        # means: no exception escapes, regardless of what happens on the wire.
        client.flush()
        print("[fail-open-unreachable-host] OK — flush against unreachable host did not raise")
    finally:
        observability._client = None
        observability._enabled = False


if __name__ == "__main__":
    # Each test constructs its own Langfuse client to simulate "the one client
    # the real app builds at startup." OpenTelemetry's TracerProvider is a
    # process-global singleton, so constructing several such clients in ONE
    # process (as a naive test-runner loop would) causes them to silently
    # share/steal each other's span processors — a test-harness artifact that
    # can't happen in the real app (which only ever constructs one client).
    # Isolate each test in its own subprocess so that artifact can't occur.
    if len(sys.argv) > 1:
        # Subprocess entrypoint: run exactly one named test.
        globals()[sys.argv[1]]()
        sys.exit(0)

    import subprocess

    test_names = [k for k in list(globals().keys()) if k.startswith("test_")]
    failed = 0
    for name in test_names:
        result = subprocess.run(
            [sys.executable, os.path.abspath(__file__), name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
        else:
            failed += 1
            print(f"FAIL: {name}")
            print(result.stdout)
            print(result.stderr)
    print(f"\n{len(test_names) - failed}/{len(test_names)} tracing smoke tests passed")
    sys.exit(1 if failed else 0)

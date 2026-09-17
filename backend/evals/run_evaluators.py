"""
Offline Tier-2 (LLM-as-judge) evaluator runner for the Event ROI pipeline.

Why this is a standalone script and not wired into the live request path:
judge-model calls cost real money and add latency (see cost-governance note
in references/security-production.md), and this app has no background
worker/queue to hide that behind — the pipeline itself runs inline in a
FastAPI BackgroundTask driven by an SSE stream the user is actively watching.
Run this on a schedule (cron / CI job) instead — see LANGFUSE_OBSERVABILITY_
REFERENCE.md's lifecycle section for the recommended cadence.

Usage:
    backend/.venv/Scripts/python.exe -m evals.run_evaluators [--limit 50] [--dry-run]

Requires LANGFUSE_PUBLIC_KEY/SECRET_KEY and GEMINI_API_KEY to already be set
in the environment (same convention as the app itself — backend/.env). This
script never reads a .env file itself or prints any key; it reuses the exact
same config.settings + services.observability.init_langfuse() path the app
uses, so a key is only ever read once, through the app's own config loader.
"""
from __future__ import annotations

import argparse
import hashlib
import sys

from config import settings
from services import observability
from evals import judges

SCORE_GROUNDEDNESS = "report_numeric_groundedness"
SCORE_INSIGHT_SPECIFICITY = "slide_insight_specificity"
PIPELINE_TAG = "event-roi-pipeline"


def _sample_in(trace_id: str, rate: float) -> bool:
    """Deterministic by trace ID hash (security-production.md: 'sample by
    trace ID hash, not independently per service') so re-running this script
    against the same trace always makes the same in/out decision."""
    digest = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
    bucket = int(digest, 16) / float(1 << 256)
    return bucket < rate


def _already_scored(trace_obj, score_name: str) -> bool:
    for s in getattr(trace_obj, "scores", None) or []:
        name = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None)
        if name == score_name:
            return True
    return False


def _find_observation(observations, name: str):
    for obs in observations or []:
        if getattr(obs, "name", None) == name:
            return obs
    return None


def _find_observations(observations, name: str):
    return [obs for obs in (observations or []) if getattr(obs, "name", None) == name]


def run_groundedness(client, trace_id: str, observations, root_input) -> None:
    synth_obs = _find_observation(observations, "gemini-synthesize-report")
    if synth_obs is None:
        print(f"[Evaluator] trace={trace_id} skipped (groundedness): no synthesis generation found")
        return

    genie_tool_obs = _find_observations(observations, "genie-ask")
    context = "\n\n".join(str(getattr(o, "output", "") or "") for o in genie_tool_obs)
    user_request = str(root_input) if root_input else ""
    report_text = str(getattr(synth_obs, "output", "") or "")

    verdict = judges.judge_report_numeric_groundedness(
        user_request=user_request, data_packet=context, report_text=report_text
    )
    if verdict is None:
        print(f"[Evaluator] trace={trace_id} groundedness UNSCORED (judge call failed/unparseable — retry next run)")
        return

    ok = observability.push_score(
        name=SCORE_GROUNDEDNESS,
        value=float(verdict.get("score", 0)),
        trace_id=trace_id,
        observation_id=getattr(synth_obs, "id", None),
        data_type="NUMERIC",
        comment=str(verdict.get("rationale", ""))[:500],
        metadata={"evaluator_prompt": "report_numeric_groundedness.prompt.md", "judge_model": judges.JUDGE_MODEL},
    )
    print(f"[Evaluator] trace={trace_id} groundedness={verdict.get('score')} pushed={ok}")


def run_insight_specificity(client, trace_id: str, observations) -> None:
    insights_obs = _find_observation(observations, "gemini-slide-insights")
    if insights_obs is None:
        print(f"[Evaluator] trace={trace_id} skipped (insight-specificity): no slide-insights generation found")
        return

    import json as _json

    try:
        input_payload = getattr(insights_obs, "input", None)
        if isinstance(input_payload, str):
            input_payload = _json.loads(input_payload)
        slides = (input_payload or {}).get("user_message")
        if isinstance(slides, str):
            slides = _json.loads(slides).get("slides", [])
        else:
            slides = (input_payload or {}).get("slides", [])

        output_payload = getattr(insights_obs, "output", None)
        if isinstance(output_payload, str):
            output_payload = _json.loads(output_payload)
    except Exception as exc:
        print(f"[Evaluator] trace={trace_id} skipped (insight-specificity): couldn't parse observation I/O ({exc})")
        return

    if not slides or not output_payload or len(slides) != len(output_payload):
        print(
            f"[Evaluator] trace={trace_id} skipped (insight-specificity): "
            f"slide/insight count mismatch ({len(slides or [])} vs {len(output_payload or [])})"
        )
        return

    for idx, (slide, insight_text) in enumerate(zip(slides, output_payload)):
        verdict = judges.judge_slide_insight_specificity(
            slide_title=slide.get("title", ""),
            slide_points=slide.get("points", []),
            insight_text=str(insight_text),
        )
        if verdict is None:
            print(f"[Evaluator] trace={trace_id} slide[{idx}] insight-specificity UNSCORED (judge call failed)")
            continue
        ok = observability.push_score(
            name=SCORE_INSIGHT_SPECIFICITY,
            value=str(verdict.get("score", "")),
            trace_id=trace_id,
            observation_id=getattr(insights_obs, "id", None),
            data_type="CATEGORICAL",
            comment=str(verdict.get("rationale", ""))[:500],
            metadata={
                "evaluator_prompt": "slide_insight_specificity.prompt.md",
                "judge_model": judges.JUDGE_MODEL,
                "slide_index": idx,
                "slide_title": slide.get("title", ""),
            },
        )
        print(f"[Evaluator] trace={trace_id} slide[{idx}] insight_specificity={verdict.get('score')} pushed={ok}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="Max recent traces to consider")
    parser.add_argument("--dry-run", action="store_true", help="Sample and log, but push no scores")
    args = parser.parse_args()

    observability.init_langfuse()
    client = observability.get_client()
    if client is None:
        print(
            "[Evaluator] Langfuse tracing is disabled (no LANGFUSE_PUBLIC_KEY/SECRET_KEY "
            "configured) — nothing to evaluate. Add real keys to backend/.env first."
        )
        return 1

    traces_page = client.api.trace.list(
        tags=[PIPELINE_TAG],
        environment=settings.langfuse_environment,
        limit=args.limit,
    )
    trace_summaries = getattr(traces_page, "data", None) or []
    print(f"[Evaluator] Found {len(trace_summaries)} traces tagged '{PIPELINE_TAG}' in environment={settings.langfuse_environment}")

    considered = sampled_in = skipped_sampling = skipped_already_scored = 0

    for summary in trace_summaries:
        trace_id = getattr(summary, "id", None)
        if not trace_id:
            continue
        considered += 1

        if not _sample_in(trace_id, settings.langfuse_judge_sample_rate):
            skipped_sampling += 1
            continue
        sampled_in += 1

        full_trace = client.api.trace.get(trace_id)
        if _already_scored(full_trace, SCORE_GROUNDEDNESS) and _already_scored(full_trace, SCORE_INSIGHT_SPECIFICITY):
            skipped_already_scored += 1
            print(f"[Evaluator] trace={trace_id} skipped: already scored on both metrics")
            continue

        if args.dry_run:
            print(f"[Evaluator] trace={trace_id} sampled in (dry-run, no scores pushed)")
            continue

        observations = getattr(full_trace, "observations", None) or []
        run_groundedness(client, trace_id, observations, getattr(full_trace, "input", None))
        run_insight_specificity(client, trace_id, observations)

    client.flush()
    print(
        f"[Evaluator] Done. considered={considered} sampled_in={sampled_in} "
        f"skipped_sampling={skipped_sampling} skipped_already_scored={skipped_already_scored}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

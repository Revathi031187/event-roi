"""
One-time setup script (Phase E + Phase D2 step 5): builds the custom
dashboard and, where the platform's data model actually supports it,
activates native Langfuse online evaluators.

This talks to the real Langfuse REST API and therefore needs REAL project
keys — it does nothing useful against the placeholders in .env.example.
Run it once, after you've added real LANGFUSE_PUBLIC_KEY/SECRET_KEY to
backend/.env:

    backend/.venv/Scripts/python.exe -m evals.setup_langfuse_dashboard

It authenticates through this app's own already-initialized Langfuse client
(services.observability.init_langfuse(), same config.settings path the app
itself uses) — no key is read, printed, or handled directly by this script.

Why groundedness isn't activated as a native online evaluator here (a real,
verified platform constraint, not an oversight): Langfuse's evaluator
variable-mapping model (langfuse.api.evaluators / evaluation_rules, checked
against the installed langfuse==4.15.4 SDK types) maps a judge prompt's
variables to fields of a SINGLE observation/trace being evaluated
(input/output/metadata/tool_calls/expected_output). `report_numeric_
groundedness` needs THREE separate observations at once — the root trace's
input, the `genie-ask` tool outputs, and the `gemini-synthesize-report`
generation's output — which doesn't fit that single-observation model. It
keeps running via `evals/run_evaluators.py` (an explicit code-side join)
instead. `slide_insight_specificity` DOES fit — it only needs one
observation's own input+output (`gemini-slide-insights`) — so it's wired up
here as a real native evaluator + evaluation rule.
"""
from __future__ import annotations

import sys

from config import settings
from services import observability

DASHBOARD_NAME = "Event ROI Pipeline — Custom Observability"
PIPELINE_TAG = "event-roi-pipeline"

# (score name, human label, chart type) — one native-metric-adjacent tile per
# custom score this skill actually pushes (services/pipeline_service.py +
# evals/run_evaluators.py). Keep this list in sync with what's really pushed;
# see phase-e-push-surface.md: "derive the widget list from what Phase D/E
# actually produced, not a fixed template."
CUSTOM_SCORE_WIDGETS = [
    ("question_plan_signal_score", "Planner question signal (avg)", "NUMBER"),
    ("genie_query_success_rate", "Genie query success rate", "NUMBER"),
    ("genie_query_retry_rate", "Genie query retry rate", "NUMBER"),
    ("synthesis_structural_completeness", "Synthesis structural completeness", "NUMBER"),
    ("report_numeric_groundedness", "Report numeric groundedness (judge, sampled)", "NUMBER"),
    ("prompt_injection_marker_detected", "Prompt-injection marker hits", "NUMBER"),
]


def _get_or_create_dashboard(client):
    existing = client.api.unstable.dashboards.list(limit=100)
    for d in getattr(existing, "data", None) or []:
        if getattr(d, "name", None) == DASHBOARD_NAME:
            print(f"[Dashboard] Reusing existing dashboard: {d.id}")
            return d
    dashboard = client.api.unstable.dashboards.create(
        name=DASHBOARD_NAME,
        description="Native + custom metrics for the Event ROI plan->query->synthesize pipeline. "
                     "See LANGFUSE_OBSERVABILITY_REFERENCE.md for what each tile means and how it's computed.",
    )
    print(f"[Dashboard] Created dashboard: {dashboard.id}")
    return dashboard


def _widget_exists(client, name: str):
    existing = client.api.unstable.dashboard_widgets.list(limit=100)
    for w in getattr(existing, "data", None) or []:
        if getattr(w, "name", None) == name:
            return w
    return None


def _create_number_widget(client, score_name: str, label: str):
    from langfuse.api.unstable.dashboard_widgets.types.dashboard_widget_view import DashboardWidgetView
    from langfuse.api.unstable.dashboard_widgets.types.dashboard_widget_chart_type import DashboardWidgetChartType
    from langfuse.api.unstable.dashboard_widgets.types.dashboard_widget_metric_aggregation import (
        DashboardWidgetMetricAggregation,
    )

    existing = _widget_exists(client, label)
    if existing:
        print(f"[Widget] Reusing existing widget: {label} ({existing.id})")
        return existing

    widget = client.api.unstable.dashboard_widgets.create(
        name=label,
        description=f"Average of score `{score_name}` (see LANGFUSE_OBSERVABILITY_REFERENCE.md).",
        view=DashboardWidgetView.SCORES_NUMERIC,
        dimensions=[],
        metrics=[{"measure": score_name, "agg": DashboardWidgetMetricAggregation.AVG}],
        filters=[
            {"column": "name", "operator": "=", "value": score_name, "type": "string"},
            {"column": "environment", "operator": "=", "value": settings.langfuse_environment, "type": "string"},
        ],
        chart_type=DashboardWidgetChartType.NUMBER,
    )
    print(f"[Widget] Created widget: {label} ({widget.id})")
    return widget


def build_dashboard(client) -> str:
    dashboard = _get_or_create_dashboard(client)
    placed = 0
    for score_name, label, _chart in CUSTOM_SCORE_WIDGETS:
        widget = _create_number_widget(client, score_name, label)
        try:
            client.api.unstable.dashboards.add_placement(
                dashboard.id,
                request={
                    "type": "widget",
                    "widgetId": widget.id,
                    "x": (placed % 3) * 4,
                    "y": (placed // 3) * 3,
                    "width": 4,
                    "height": 3,
                },
            )
            placed += 1
        except Exception as exc:
            # Likely already placed on a prior run — non-fatal, keep going.
            print(f"[Dashboard] Could not place widget '{label}' (may already be placed): {exc}")

    url = f"{settings.langfuse_host.rstrip('/')}/project/_/dashboards/{dashboard.id}"
    print(f"[Dashboard] {placed} widgets placed. URL (project id substituted by Langfuse UI): {url}")
    return dashboard.id


def try_activate_native_insight_specificity_evaluator(client) -> None:
    connections = client.api.llm_connections.list(limit=100)
    usable = list(getattr(connections, "data", None) or [])
    if not usable:
        print(
            "[Evaluator] No LLM Connection configured in this Langfuse project — "
            "skipping native evaluator activation for slide_insight_specificity. "
            "This is the one step this script won't do for you: adding an LLM "
            "Connection means giving Langfuse its own copy of a model provider "
            "credential, which belongs in Langfuse's UI (Settings > LLM Connections), "
            "not in a script run from this repo. Once one exists, re-run this script. "
            "Until then, evals/run_evaluators.py covers both custom metrics via "
            "this app's own Gemini key, no LLM Connection required."
        )
        return

    provider_name = getattr(usable[0], "provider", None) or getattr(usable[0], "id", None)
    print(f"[Evaluator] Using existing LLM Connection: {provider_name}")
    print(
        "[Evaluator] NOTE: this native evaluator judges the WHOLE "
        "gemini-slide-insights generation at once (all 7 slides' points + all "
        "7 insights together), because Langfuse's variable mapping binds to "
        "one observation's input/output as a whole — it can't loop per-slide "
        "the way evals/run_evaluators.py's judges.judge_slide_insight_specificity "
        "does. The two will not always agree exactly; treat run_evaluators.py's "
        "per-slide score as the more precise of the two and this one as a "
        "cheaper, always-on native signal."
    )

    from langfuse.api.evaluators.types.create_evaluator_request import CreateEvaluatorRequest_LlmAsJudge
    from langfuse.api.evaluators.types.evaluator_model_config import EvaluatorModelConfig
    from langfuse.api.evaluators.types.evaluator_chat_message import EvaluatorChatMessage
    from langfuse.api.evaluation_commons.types.evaluator_output_definition import EvaluatorOutputDefinition_Categorical
    from langfuse.api.evaluation_commons.types.prompt_variable_mapping_input import PromptVariableMappingInput
    from langfuse.api.evaluation_commons.types.prompt_variable_mapping_source import PromptVariableMappingSource

    prompt_path = "prompts/slide_insight_specificity.prompt.md"
    with open(__file__.rsplit("/", 1)[0] + "/" + prompt_path, "r", encoding="utf-8") as f:
        rubric_text = f.read()

    existing = client.api.evaluators.list(limit=100)
    for e in getattr(existing, "data", None) or []:
        if getattr(e, "name", None) == "slide_insight_specificity":
            print(f"[Evaluator] 'slide_insight_specificity' evaluator already exists: {e.id}")
            return

    evaluator = client.api.evaluators.create(
        request=CreateEvaluatorRequest_LlmAsJudge(
            name="slide_insight_specificity",
            description="Zero-shot rubric — see evals/prompts/slide_insight_specificity.prompt.md for the source of truth.",
            prompt=[EvaluatorChatMessage(role="system", content=rubric_text)],
            model_config=EvaluatorModelConfig(provider=str(provider_name), model="gemini-2.5-flash"),
            variable_mapping=[
                PromptVariableMappingInput(variable="input", source=PromptVariableMappingSource.INPUT),
                PromptVariableMappingInput(variable="context", source=PromptVariableMappingSource.INPUT),
                PromptVariableMappingInput(variable="output", source=PromptVariableMappingSource.OUTPUT),
            ],
            output_definition=EvaluatorOutputDefinition_Categorical(
                categories=["specific", "generic", "unsupported"],
                should_allow_multiple_matches=False,
                score_value_instructions="Return exactly one of: specific, generic, unsupported.",
            ),
        )
    )
    print(f"[Evaluator] Created evaluator: {evaluator.id}")

    rule = client.api.evaluation_rules.create(
        name="slide_insight_specificity_on_slide_insights_generation",
        enabled=True,
        evaluator_assignments=[{"evaluatorId": evaluator.id}],
        sampling=settings.langfuse_judge_sample_rate,
        filter=[
            {"column": "name", "operator": "=", "value": "gemini-slide-insights", "type": "string"},
            {"column": "environment", "operator": "=", "value": settings.langfuse_environment, "type": "string"},
        ],
    )
    print(
        f"[Evaluator] Activated evaluation rule: {rule.id} "
        f"(sampling={settings.langfuse_judge_sample_rate}, environment={settings.langfuse_environment})"
    )


def main() -> int:
    observability.init_langfuse()
    client = observability.get_client()
    if client is None:
        print(
            "[Setup] Langfuse tracing is disabled (no real LANGFUSE_PUBLIC_KEY/SECRET_KEY "
            "in backend/.env) — nothing to set up against a placeholder project."
        )
        return 1

    dashboard_id = build_dashboard(client)
    try_activate_native_insight_specificity_evaluator(client)

    print(
        f"\n[Setup] Done. Record this dashboard id in LANGFUSE_OBSERVABILITY_REFERENCE.md: {dashboard_id}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

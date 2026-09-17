# Langfuse Observability Reference — Event ROI Dashboard

Last generated: 2026-09-17 · Owner: *(unassigned — set this to whoever merges this PR)* · Review cadence: revisit on major drift re-scan (see "Lifecycle" below), or quarterly at minimum.

## Scope

This document covers LLM/agent-layer observability and evaluation via Langfuse for the **Event ROI Dashboard** — a FastAPI + React app that plans analytics questions with Gemini, executes them against Databricks Genie (NL→SQL), and synthesizes a 7-slide marketing ROI report with Gemini.

**Langfuse does not cover infrastructure metrics** (CPU, memory, non-LLM request latency, FastAPI/uvicorn health, SQLite I/O, PPTX-generation latency). None of that exists in this repo today as a separate OTel/Prometheus/Grafana path — if you need it, it has to be built separately; don't assume Langfuse's dashboards show it.

Deployment: **Langfuse Cloud, US region** (`https://us.cloud.langfuse.com`). Chosen because: no existing self-hosted observability infra was found in this repo, and the user confirmed Cloud US directly rather than defaulting silently (this app's data — Databricks marketing/event data, and a request path that can carry a live Databricks token — has enough sensitivity that the deployment target was treated as a decision, not a default).

## SDK verification note (why you can trust the call sites below)

`langfuse==4.15.4`'s actual installed API surface was verified against the real package before any integration code was written (per this skill's Phase B rule — never rely on memorized/generic docs). Notably: this version has **no** `update_current_trace()` (that's `propagate_attributes(...)` as a context manager), scores are pushed via `create_score()` (not `score()`), and generation/tool spans come from `start_as_current_observation(as_type=...)`. Re-verify before bumping the pin:
```
python -c "from langfuse import Langfuse; import inspect; print(inspect.signature(Langfuse.__init__))"
```

## Where things live

- **Instrumentation code**: `backend/services/observability.py` (client init, masking, tracing helpers, score push — all fail-open, all no-op when `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` aren't set).
- **Instrumented call sites**: `backend/services/gemini_service.py` (3 generation spans: `gemini-plan-questions`, `gemini-synthesize-report`, `gemini-slide-insights`), `backend/services/genie_service.py` (1 tool span: `genie-ask`), `backend/services/pipeline_service.py` (root span `event_roi_pipeline`, Tier-1 score pushes).
- **Dashboard**: *"Event ROI Pipeline — Custom Observability"* — **not yet created**. `backend/evals/setup_langfuse_dashboard.py` builds it via the Dashboards API, but needs real project keys to run (see "What still needs you" below). Re-run it and paste the resulting dashboard ID/URL here once it exists.
- **Dataset (golden/calibration set)**: none exists yet. Per this skill's design, that's expected at cold start, not a blocker — see "Eval strategy" below for how it grows from production.
- **Evaluator prompts**: `backend/evals/prompts/report_numeric_groundedness.prompt.md` and `backend/evals/prompts/slide_insight_specificity.prompt.md` — both zero-shot (no annotated examples exist yet), both hardened against prompt injection (rubric structurally separated from judged content, explicit "data not instructions" framing).
- **CI/CD Experiments**: not wired in — no dataset exists yet to gate against (see Lifecycle: don't gate CI on a 0-example dataset).
- **Masking rules applied**: emails, phone numbers, Databricks PAT shapes (`dapi...`), Google/Gemini API key shapes (`AIza...`), Bearer tokens, and any field whose *name* looks secret-shaped (`token`, `secret`, `password`, `api_key`, `authorization`, etc., recursively through nested dicts/lists — this specifically covers `GenerateRequest.databricks_token`, which this app's own API can receive directly in a request body, not just from server config). Masking fails **closed** (withholds content) on its own internal errors, unlike the rest of the observability code, which fails open on availability. See `backend/services/observability.py`'s masking section and `backend/evals/tests/test_masking.py` for verified test cases.

## What was already there vs. what this PR adds

**Already there (found in Phase A, unchanged by this PR):** no Langfuse/OTel instrumentation, no eval framework, no golden dataset, no committed secrets. The pipeline already had its own reference-free quality gates baked directly into `pipeline_service.py`: a retry-if-synthesis-looks-incomplete check (`explicit_slides < 7`), a retry-if-outline-is-sparse check (`non_empty_slides < 5`), and a groundedness-enforcement post-process (`_enrich_outline_with_query_answers`). Separately, `_score_question` / `_filter_high_signal_questions` / `_enforce_question_coverage` existed in the same file but were **dead code** — written but never called from `run_pipeline`. This PR does not change that dead-code status (no pipeline *behavior* changes), but it does reuse `_score_question` as a pure measurement input for `question_plan_signal_score` below.

**Added by this PR:** the entire Langfuse wiring described in this document — SDK, masking, tracing, Tier-1 code-evaluator scores, Tier-2 judge prompts + offline runner, and this reference doc.

## Metrics

| Metric | Native or custom | Computed by | Langfuse score name | Where to find it in Langfuse | Maps to goal | Evaluator/prompt version | Calibration status |
|---|---|---|---|---|---|---|---|
| Cost per generation / per trace | Native | — (automatic once `usage_details` is attached; see `usage_details_from_gemini`) | — | Traces view → per-trace cost; Sessions view (session = one `job_id`) | Cost visibility for an "ROI" tool — trivially on-theme | — | — |
| Token usage (input/output/total) | Native | — (from `google-genai`'s `usage_metadata`, mapped in `observability.usage_details_from_gemini`) | — | Traces/Generations view, per-observation usage | Cost/efficiency observability | — | — |
| Latency (per-span, per-trace) | Native | — (automatic from tracing) | — | Traces view, per-trace and per-observation latency | Pipeline reliability | — | — |
| Planner question signal quality | Custom, Tier 1 (code) | Reuses pre-existing `_score_question` heuristic in `pipeline_service.py`, read-only (no pipeline behavior change) | `question_plan_signal_score` | Dashboard → "Planner question signal (avg)" tile; Traces → filter by score name | A bad planner question cascades into a hollow report — first-stage quality gate | — (deterministic code, not a judge) | N/A — deterministic, not judge-calibrated |
| Genie tool-call success rate | Custom, Tier 1 (code) | `stats['succeeded']/stats['total_queries']` from `build_data_packet`, pushed in `pipeline_service.py` | `genie_query_success_rate` | Dashboard → "Genie query success rate" tile | Tool-use reliability | — | N/A — deterministic |
| Genie tool-call retry rate | Custom, Tier 1 (code) | Attempt count added to each Genie result in `genie_service.GenieService.ask`, aggregated in `pipeline_service.py` | `genie_query_retry_rate` | Dashboard → "Genie query retry rate" tile | Tool-use reliability / early warning of Genie space issues | — | N/A — deterministic |
| Synthesis structural completeness | Custom, Tier 1 (code) | Formalizes this app's own pre-existing `explicit_slides<7` / `non_empty_slides<5` retry gates as a trended score | `synthesis_structural_completeness` | Dashboard → "Synthesis structural completeness" tile | Report format/schema compliance | — | N/A — deterministic |
| Prompt-injection marker detected | Custom, Tier 1 (code) | Keyword tripwire on `additional_context` free text (`pipeline_service._detect_injection_markers`) | `prompt_injection_marker_detected` | Dashboard → "Prompt-injection marker hits" tile | Lightweight defensive signal (see "What's intentionally not built" — this is *not* a full safety judge) | — | N/A — deterministic |
| Report numeric groundedness | Custom, Tier 2 (LLM-as-judge, sampled) | `evals/judges.py:judge_report_numeric_groundedness`, run by `evals/run_evaluators.py` (offline, sampled by trace-ID hash at `LANGFUSE_JUDGE_SAMPLE_RATE`, default 0.2) | `report_numeric_groundedness` | Dashboard → "Report numeric groundedness" tile; Traces → filter by score name, attached to the `gemini-synthesize-report` observation | **This is the single highest-stakes metric for this app's stated goal** — an ROI dashboard that fabricates a dollar figure is the worst-case failure this tool could produce; the app's own synthesizer prompt already begs the model not to do this | `evals/prompts/report_numeric_groundedness.prompt.md`, v1 (zero-shot) | **Provisional — 0 annotated cases so far.** Not yet checked against any human-labeled examples. Do not treat scores from this evaluator as ground truth yet — see "Eval strategy" below |
| Slide key-insight specificity | Custom, Tier 2 (LLM-as-judge, sampled) | `evals/judges.py:judge_slide_insight_specificity`, per-slide, run by `evals/run_evaluators.py` | `slide_insight_specificity` | Dashboard (once built) via `evals/setup_langfuse_dashboard.py`; Traces → filter by score name, attached to the `gemini-slide-insights` observation, one score per slide index (see `metadata.slide_index`) | Directly enforces this app's own `SLIDE_INSIGHTS_SYSTEM_PROMPT` rule against generic "management advice" filler | `evals/prompts/slide_insight_specificity.prompt.md`, v1 (zero-shot) | **Provisional — 0 annotated cases so far.** |
| Pipeline fatal error | Custom, Tier 1 (code) | Pushed from `run_pipeline`'s exception handler | `pipeline_fatal_error` | Traces → filter by score name = `pipeline_fatal_error` | Operational reliability | — | N/A — deterministic |

## What's intentionally not built

- **RAG / retrieval-quality metrics (context precision/recall, chunk utilization, citation accuracy)** — this app doesn't do retrieval-augmented generation. Databricks Genie is NL→SQL against structured warehouse tables, not embedding-based retrieval, so the whole RAG metrics family in the Phase D taxonomy doesn't apply here.
- **Answer-correctness-vs-reference** — needs a golden/reference answer, and none exists. Not fabricated. `report_numeric_groundedness` (checks numbers against the actual Genie data, not a golden report) covers the same underlying risk without needing one.
- **Full safety/toxicity judge** — this is an internal B2B marketing analytics tool with no adversarial public chat surface (the only freeform user input, `additional_context`, feeds a planner prompt, not a user-facing chat). A full moderation-model judge was judged disproportionate to the actual risk surface; `prompt_injection_marker_detected` is the proportionate, cheap tripwire instead. Revisit if this app ever exposes a public-facing chat entry point.
- **User-level metrics / per-user_id breakdown** — this app has no authentication layer, so there is no real per-user identity to attach to traces. `user_id` is intentionally left unset rather than fabricated (e.g. faked from an IP or session cookie). `session_id` (= `job_id`) is set on every trace instead.
- **CI/CD Experiment gating** — no dataset exists yet to gate against; see Lifecycle.

## Eval strategy (why "no golden dataset" isn't a blocker)

Per this skill's design: you don't need a labeled dataset to start.
- **Tier 1 (code evaluators, always on, zero cost)**: `question_plan_signal_score`, `genie_query_success_rate`, `genie_query_retry_rate`, `synthesis_structural_completeness`, `prompt_injection_marker_detected`, `pipeline_fatal_error` — all run on every single pipeline execution, wired directly into `pipeline_service.py`.
- **Tier 2 (LLM-as-judge, sampled, still reference-free)**: `report_numeric_groundedness` and `slide_insight_specificity` — judged against the actual Genie data / actual slide bullet points, never against a "correct" reference report, because no such reference exists or is needed.
- **Tier 3/4/5 (human review, production-signal, dataset growth)**: not yet active — there's no annotation queue wired up and no traces have flowed yet (this repo has no real Langfuse keys configured). Once real traffic flows, route Tier 2 disagreements/low-confidence cases to a Langfuse annotation queue and let a real Dataset grow from curated production cases. This is the same store a "we already have a golden dataset" project would read from — it just starts empty here instead of pre-populated.

**Calibration status, stated plainly**: both Tier-2 evaluators are **provisional** — zero annotated human-reviewed cases exist yet. Do not present either score with the same confidence as a fully calibrated evaluator in any downstream reporting until Tier 3 has produced real annotated agreement data.

## What still needs you (can't be completed without a live Langfuse project)

This PR ships fully working code, verified against the real installed SDK and offline-tested (see "Validation performed" below) — but two things need real Langfuse Cloud project keys, which don't exist yet (only placeholders were added, per your instruction):

1. **Add real `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` to `backend/.env`** (never committed — already covered by `.gitignore`). Use a project-scoped key, and use separate keys per environment (dev/staging/prod) rather than one shared key.
2. **Run `backend/evals/setup_langfuse_dashboard.py` once**, after step 1. It builds the custom dashboard via the API and, if an LLM Connection already exists in your Langfuse project, also activates `slide_insight_specificity` as a native online evaluator. It will **not** activate `report_numeric_groundedness` as a native evaluator — a real, verified platform constraint (Langfuse's evaluator variable-mapping binds to one observation's input/output; this metric needs three separate observations joined together), documented in the script's own header. That one keeps running via `evals/run_evaluators.py` instead.
3. **Run `backend/evals/run_evaluators.py` on a schedule** (cron / CI, e.g. every hour) to keep both Tier-2 judges scoring recent traces — see Lifecycle below. It samples 20% of traces by default (`LANGFUSE_JUDGE_SAMPLE_RATE`), deterministically by trace-ID hash.
4. **Configure Langfuse's own data-retention/deletion settings** in the project UI to match whatever policy applies to this app's data — not accepted defaults. Also route the "we're now sending production marketing/event data to a third-party SaaS" decision through whatever compliance/security review your organization normally requires for that; this skill doesn't substitute for that sign-off.

## Validation performed (Phase F) — and its honest limits

No live Langfuse project exists yet, so "confirm a trace appears in the Langfuse UI" (the strongest form of Phase F validation) **could not be performed** and is not claimed here. What *was* verified, concretely, without live credentials:

- ✅ **Masking genuinely redacts**, not just "looks configured" — `backend/evals/tests/test_masking.py`, 5/5 passing, covering a flat string (email+phone), a nested tool-call-result dict (Databricks token + email — the exact shape `GenieService` returns), a Google API key/Bearer token, secret-shaped field names, and a forced internal masking failure (confirmed to fail **closed**, withholding content, with a real traceback logged — not silently swallowed).
- ✅ **Span structure is correct** — `backend/evals/tests/test_tracing_smoke.py`, 4/4 passing, using an OpenTelemetry in-memory exporter in place of the real Langfuse HTTP exporter (no live project needed for this check). Confirms: root span (`event_roi_pipeline`) + nested generation (`gemini-plan-questions`) + tool (`genie-ask`) spans all land in one shared trace; `session_id` and the environment tag are real span attributes, not just accepted parameters; a Tier-1 score push with no active trace_id logs distinctly and returns `False` rather than silently no-op'ing (the exact failure mode Phase D3 warns about); tracing being fully disabled is a true no-op everywhere.
- ✅ **Fail-open holds** — pointing a real `Langfuse` client at an unreachable host and driving a full traced pipeline run + `flush()` against it does not raise.
- ✅ **The app itself still imports and runs cleanly** with the new instrumentation wired in, using the exact pinned `langfuse==4.15.4` (verified against the real installed package, not memorized docs — see the SDK verification note above). No pre-existing test suite existed in this repo to regress.
- ❌ **Not yet verified** (blocked on real keys, see "What still needs you"): a trace actually landing in Langfuse Cloud's UI; a pushed score actually being delivered and visible (vs. just "the SDK call didn't raise" — these are explicitly different claims); the native `slide_insight_specificity` evaluator/rule actually running against live traffic; the dashboard actually existing.

## Lifecycle

- **Keep `evals/run_evaluators.py` running on a schedule** (cron/CI) — this is the ongoing Tier-2 mechanism until/unless the native evaluator route (`setup_langfuse_dashboard.py`) is fully activated for both metrics.
- **Don't gate CI/CD on the dataset yet** — it doesn't exist. Once Tier 3 (human review of Tier-2 disagreements) has produced a real, curated Dataset with enough examples to be statistically meaningful, add an Experiment-based CI gate and treat it as a candidate for ensemble-judging (multiple judge calls, not one) given it would be a high-stakes CI-blocking decision.
- **Re-run `scripts/scan_codebase.py`** (from the scan-codebase-observability skill) when a significant PR touches `backend/services/pipeline_service.py`, `gemini_service.py`, or `genie_service.py`, to catch new uninstrumented call sites early.
- **Regenerate the two evaluator prompts** if this app's domain moves materially (new slide template, new metric definitions in `METRIC_DEFINITIONS`, a new Genie table) — treat prompt staleness as a code-drift problem, not a one-time artifact.
- **Assign a real owner** to this document (currently unassigned above) before calling this "done" — an observability setup with no named owner tends to be accurate on day one and wrong by month three.

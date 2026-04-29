import asyncio
import uuid
from typing import Dict, Optional
from .gemini_service import GeminiService
from .genie_service import GenieService, build_data_packet
from .outline_parser import parse_report_to_outline
from . import db_service

# ── In-memory job store ───────────────────────────────────────────────────────
_job_queues: Dict[str, asyncio.Queue] = {}
_job_results: Dict[str, dict] = {}

MAX_QUESTION_RETRIES = 2
MIN_ACCEPTED_QUESTIONS = 6
MAX_QUESTIONS = 8

_GENERIC_PREFIXES = (
    "show ",
    "summarize ",
    "list ",
    "provide ",
    "identify ",
    "explain ",
    "calculate ",
)
_SQL_PATTERNS = (
    "select ",
    " from ",
    " where ",
    " group by ",
    " order by ",
    " join ",
    "sum(",
    "count(",
)
_SIGNAL_KEYWORDS = (
    "conversion", "rate", "delta", "trend", "driver", "impact", "contribution",
    "top", "bottom", "segment", "roi", "efficiency", "pipeline", "cost",
    "registration", "attendance", "qualified", "qualified leads", "per ",
)
_COMPARISON_KEYWORDS = ("vs", "versus", "compared", "relative", "change", "delta", "trend")


def _normalize_question(question: str) -> str:
    return " ".join((question or "").split()).strip()


def _score_question(question: str) -> int:
    q = _normalize_question(question)
    ql = q.lower()
    score = 0

    if 35 <= len(q) <= 220:
        score += 2
    else:
        score -= 2

    if any(ql.startswith(p) for p in _GENERIC_PREFIXES):
        score -= 3
    if any(tok in ql for tok in _SQL_PATTERNS):
        score -= 5

    if any(k in ql for k in _SIGNAL_KEYWORDS):
        score += 3
    if any(k in ql for k in _COMPARISON_KEYWORDS):
        score += 2
    if " by " in ql:
        score += 1

    return score


def _filter_high_signal_questions(questions: list[str]) -> tuple[list[str], list[dict]]:
    accepted: list[str] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for raw in questions:
        q = _normalize_question(raw)
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)

        score = _score_question(q)
        # Strict gate: reject generic instruction-style or low-signal prompts.
        if score >= 2 and not any(q.lower().startswith(p) for p in _GENERIC_PREFIXES):
            accepted.append(q)
        else:
            rejected.append({"question": q, "score": score})

    return accepted[:MAX_QUESTIONS], rejected


def _high_signal_fallback_questions(event_name: str) -> list[str]:
    name = event_name or "this event"
    return [
        f"For {name} or closest matching available event, return exact totals for registrations, attendees, and attendance rate with supporting breakdown by primary program or region.",
        f"For {name} or closest matching available event, return exact funnel stage counts and conversion rates from early engagement through qualified outcomes.",
        f"For {name} or closest matching available event, return exact pipeline generated, qualified pipeline, and opportunity metrics by the strongest available segment dimension.",
        f"For {name} or closest matching available event, return exact lead quality metrics such as NNN/MQL/qualified indicators and their conversion progression.",
        f"For {name} or closest matching available event, return exact top and bottom segment performance with contribution share and variance.",
        f"For {name} or closest matching available event, return exact spend, cost efficiency, and ROI/fPOI style indicators using available financial fields.",
        f"For {name} or closest matching available event, return exact trend comparison versus prior comparable period if available, otherwise provide latest-period trend by available time grain.",
        f"For {name} or closest matching available event, return exact data quality or coverage diagnostics including unknown/missing categories and inconsistencies.",
    ]


def _classify_question_theme(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ("registration", "attend", "participation", "reach")):
        return "attendance"
    if any(k in q for k in ("funnel", "stage", "drop-off", "conversion")):
        return "funnel"
    if any(k in q for k in ("mql", "nnn", "lead quality", "lead", "qualification")):
        return "lead_quality"
    if any(k in q for k in ("pipeline", "revenue", "qualified")):
        return "pipeline"
    if any(k in q for k in ("segment", "region", "program group", "audience", "top", "bottom")):
        return "segment"
    if any(k in q for k in ("cost", "roi", "efficiency", "spend", "return")):
        return "financial"
    if any(k in q for k in ("prior", "trend", "yoy", "versus", "compared", "change", "delta")):
        return "trend"
    if any(k in q for k in ("data quality", "unknown", "missing", "consistency", "coverage")):
        return "data_quality"
    return "other"


def _canonical_theme_question(theme: str, event_name: str) -> str:
    name = event_name or "this event"
    prompts = {
        "attendance": f"For {name} or closest matching available event, return exact registrations, attendees, and attendance rate with primary dimension breakdown.",
        "funnel": f"For {name} or closest matching available event, return exact stage counts and conversion rates across the full available funnel.",
        "lead_quality": f"For {name} or closest matching available event, return exact NNN, MQL, and qualified lead indicators with progression/conversion.",
        "pipeline": f"For {name} or closest matching available event, return exact pipeline generated and qualified pipeline values by top segment drivers.",
        "segment": f"For {name} or closest matching available event, return exact top and bottom segment performance with contribution shares.",
        "financial": f"For {name} or closest matching available event, return exact spend, cost efficiency, and ROI/fPOI indicators from available financial fields.",
        "trend": f"For {name} or closest matching available event, return exact comparison vs prior period (or nearest available trend dimension) for key metrics.",
        "data_quality": f"For {name} or closest matching available event, return exact data quality signals: unknown buckets, missingness, and metric inconsistencies.",
    }
    return prompts.get(theme, f"For {name}, return exact measurable business outcomes using available data.")


def _enforce_question_coverage(questions: list[str], event_name: str) -> list[str]:
    """
    Ensure diversified, wide question set similar to notebook pipeline intent:
    one question per key analytic theme, then fill remaining slots.
    """
    desired_order = ["attendance", "funnel", "lead_quality", "pipeline", "segment", "financial", "trend", "data_quality"]
    by_theme: dict[str, list[str]] = {}
    for q in questions:
        by_theme.setdefault(_classify_question_theme(q), []).append(q)

    selected: list[str] = []
    for theme in desired_order:
        if by_theme.get(theme):
            selected.append(by_theme[theme][0])
        else:
            selected.append(_canonical_theme_question(theme, event_name))

    # Fill up with remaining accepted questions without duplicates.
    for q in questions:
        if q not in selected:
            selected.append(q)
        if len(selected) >= MAX_QUESTIONS:
            break

    if len(selected) < MIN_ACCEPTED_QUESTIONS:
        fallback = _high_signal_fallback_questions(event_name)
        for q in fallback:
            if q not in selected:
                selected.append(q)
            if len(selected) >= MAX_QUESTIONS:
                break

    return _dedupe_preserve_order(selected)[:MAX_QUESTIONS]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        key = _normalize_question(it).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(_normalize_question(it))
    return out


def create_job() -> str:
    job_id = uuid.uuid4().hex
    _job_queues[job_id] = asyncio.Queue()
    return job_id


def get_queue(job_id: str) -> Optional[asyncio.Queue]:
    return _job_queues.get(job_id)


def get_result(job_id: str) -> Optional[dict]:
    return _job_results.get(job_id)


async def _emit(job_id: str, event: dict) -> None:
    q = _job_queues.get(job_id)
    if q:
        await q.put(event)


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_pipeline(
    job_id: str,
    event_name: str,
    additional_context: str = "",
    databricks_host: str = None,
    databricks_token: str = None,
    genie_space_id: str = None,
) -> None:
    try:
        gemini = GeminiService()
        genie = GenieService(
            host=databricks_host,
            token=databricks_token,
            space_id=genie_space_id,
        )

        # ── Phase 1: PLAN (includes schema discovery) ─────────────────────────
        await _emit(job_id, {
            "type": "phase_start", "phase": 1,
            "message": "Discovering data schema and planning queries...",
        })

        # Step 1a: Ask Genie what data is available so the planner can tailor questions
        schema_info = ""
        try:
            schema_info = await genie.discover_schema()
            if schema_info:
                print(f"[Pipeline] Schema discovered ({len(schema_info)} chars)")
            else:
                print("[Pipeline] No schema returned — planner will use generic questions")
        except Exception as e:
            print(f"[Pipeline] Schema discovery failed (non-fatal): {e}")

        # Step 1b: Gemini generates questions tailored to the discovered schema
        planned_questions = await gemini.plan_questions(
            event_name,
            additional_context,
            schema_info=schema_info,
        )
        accepted_questions, rejected_questions = _filter_high_signal_questions(planned_questions)

        retry = 0
        while len(accepted_questions) < MIN_ACCEPTED_QUESTIONS and retry < MAX_QUESTION_RETRIES:
            retry += 1
            print(
                f"[Pipeline] Question quality low ({len(accepted_questions)}/{len(planned_questions)} accepted). "
                f"Retrying planner ({retry}/{MAX_QUESTION_RETRIES})..."
            )
            refinement_context = (
                (additional_context or "")
                + "\n\nPlanner quality constraints: produce high-signal analytical questions only. "
                  "Avoid generic instruction phrasing (show/list/summarize/provide/explain/calculate). "
                  "Prefer comparative, driver-based, contribution, conversion, efficiency, and action-oriented questions."
            )
            planned_questions = await gemini.plan_questions(
                event_name,
                refinement_context,
                schema_info=schema_info,
            )
            accepted_questions, rejected_questions = _filter_high_signal_questions(planned_questions)

        if len(accepted_questions) < MIN_ACCEPTED_QUESTIONS:
            print(
                f"[Pipeline] Using deterministic high-signal fallback questions "
                f"({len(accepted_questions)} accepted after retries)."
            )
            accepted_questions = _high_signal_fallback_questions(event_name)
            rejected_questions = []

        questions = _enforce_question_coverage(accepted_questions, event_name)

        await _emit(job_id, {
            "type": "phase_done", "phase": 1,
            "message": f"Generated {len(questions)} questions",
            "data": {
                "questions": questions,
                "quality": {
                    "accepted": len(questions),
                    "rejected": len(rejected_questions),
                    "retries_used": retry,
                },
            },
        })

        # ── Phase 2: BATCH QUERY ──────────────────────────────────────────────
        await _emit(job_id, {
            "type": "phase_start", "phase": 2,
            "message": f"Querying {'demo data' if genie.is_demo else 'Databricks Genie'} in parallel...",
            "data": {"total": len(questions), "demo_mode": genie.is_demo},
        })

        async def on_progress(idx: int, question: str, result: dict):
            status = result.get("status", "UNKNOWN")
            error_snippet = ""
            if status == "FAILED" and result.get("error"):
                error_snippet = result["error"][:120]

            await _emit(job_id, {
                "type": "phase_progress", "phase": 2,
                "data": {
                    "index": idx,
                    "completed": idx + 1,
                    "total": len(questions),
                    "question": question,
                    "status": status,
                    "rows": len(result.get("data_rows", [])),
                    "columns": len(result.get("data_columns", [])),
                    "error": error_snippet,
                },
            })

        query_results = await genie.batch_ask(questions, progress_callback=on_progress)
        data_packet, stats = build_data_packet(query_results)

        await _emit(job_id, {
            "type": "phase_done", "phase": 2,
            "message": f"{stats['succeeded']}/{stats['total_queries']} queries succeeded",
            "data": {"stats": stats},
        })

        # ── Phase 3: SYNTHESIZE with streaming ────────────────────────────────
        await _emit(job_id, {
            "type": "phase_start", "phase": 3,
            "message": "Synthesizing report with Gemini...",
            "data": {"tokens_estimate": stats["data_packet_tokens_est"]},
        })

        print(f"[Pipeline] Phase 3 start — data_packet: {len(data_packet)} chars, "
              f"{stats['succeeded']}/{stats['total_queries']} queries succeeded")

        report_tokens: list[str] = []
        async for token in gemini.synthesize_report_streaming(
            data_packet,
            event_name,
            stats,
            planned_questions=questions,
        ):
            report_tokens.append(token)
            await _emit(job_id, {
                "type": "phase_token",
                "phase": 3,
                "data": {"token": token},
            })

        full_report = "".join(report_tokens)
        print(f"[Pipeline] Phase 3 complete — {len(full_report)} chars synthesized")

        outline = parse_report_to_outline(full_report, event_name)
        outline_dict = outline.model_dump()
        print(f"[Pipeline] Outline parsed — {len(outline.slides)} slides")

        await db_service.save_report(
            job_id=job_id,
            event_name=event_name,
            report_text=full_report,
            outline=outline_dict,
            stats=stats,
        )

        _job_results[job_id] = {
            "report": full_report,
            "outline": outline_dict,
            "questions": questions,
            "stats": stats,
        }

        await _emit(job_id, {
            "type": "phase_done", "phase": 3,
            "message": "Report synthesized successfully",
            "data": {"report": full_report, "outline": outline_dict},
        })

        await _emit(job_id, {"type": "complete"})

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(f"[Pipeline] FATAL ERROR:\n{tb}")
        await _emit(job_id, {
            "type": "error",
            "message": str(exc),
            "detail": tb,
        })
    finally:
        await asyncio.sleep(300)
        _job_queues.pop(job_id, None)

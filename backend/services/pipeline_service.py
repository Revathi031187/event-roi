import asyncio
import re
import uuid
from typing import Dict, Optional, Any
from .gemini_service import GeminiService
from .genie_service import GenieService, build_data_packet
from .outline_parser import parse_report_to_outline
from . import db_service
from models.schemas import ReportOutline

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


def _count_explicit_slides(report_text: str) -> int:
    return len(re.findall(r"#{2,6}\s+Slide\s+\d+\s*[:\-–]", report_text or "", flags=re.IGNORECASE))


def _looks_numeric(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).replace(",", "").strip()
    if not s:
        return False
    try:
        float(s.replace("%", "").replace("$", ""))
        return True
    except Exception:
        return False


def _fmt_value(value: Any) -> str:
    if value is None:
        return "NULL"
    s = str(value).strip()
    return s if len(s) <= 60 else f"{s[:57]}..."


def _classify_question_to_slide_idx(question: str) -> int:
    q = (question or "").lower()
    if any(k in q for k in ("registration", "attend", "check-in", "show-up")):
        return 1  # Registration & Attendance
    if any(k in q for k in ("funnel", "nnn", "mql", "u2", "u3", "conversion", "stage")):
        return 2  # Pipeline Funnel
    if any(k in q for k in ("segment", "account", "customer", "prospect", "region", "tier", "business unit", "audience")):
        return 3  # Account Segment Analysis
    if any(k in q for k in ("cost", "spend", "roi", "fpoi", "efficiency", "cpl")):
        return 4  # Cost & ROI Analysis
    if any(k in q for k in ("yoy", "year over year", "prior year", "previous year", "trend")):
        return 5  # YoY Comparison
    if any(k in q for k in ("cross-event", "across events", "benchmark", "compare events", "vs other events")):
        return 6  # Cross-Event Comparison
    return 0  # Executive Summary / generic KPI


def _points_from_query_result(result: dict, max_points: int = 3) -> list[str]:
    points: list[str] = []
    cols = result.get("data_columns") or []
    rows = result.get("data_rows") or []

    if cols and rows:
        for row in rows[:max_points]:
            if not isinstance(row, (list, tuple)):
                continue
            dim_parts: list[str] = []
            met_parts: list[str] = []
            for i, col in enumerate(cols):
                if i >= len(row):
                    continue
                val = row[i]
                if _looks_numeric(val):
                    met_parts.append(f"{col}={_fmt_value(val)}")
                elif val not in (None, "") and len(dim_parts) < 2:
                    dim_parts.append(f"{col}: {_fmt_value(val)}")
                if len(met_parts) >= 3:
                    break

            if met_parts:
                prefix = ""
                if dim_parts:
                    prefix = f"{'; '.join(dim_parts)} -> "
                points.append(f"{prefix}{', '.join(met_parts)}.")
            if len(points) >= max_points:
                break

    if points:
        return points[:max_points]

    text = (result.get("text_response") or "").strip()
    if text:
        first = re.split(r"(?<=[.!?])\s+", text)[0].strip()
        if first and any(ch.isdigit() for ch in first):
            return [first[:220]]
    return []


def _dedupe_points_for_slide(points: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in points:
        key = re.sub(r"\s+", " ", (p or "").lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p.strip())
    return out


def _enrich_outline_with_query_answers(outline, query_results: list[dict]) -> None:
    """
    Replace generic explanatory bullets with concrete query-answer bullets
    derived from Genie outputs where possible.
    """
    bucketed: dict[int, list[str]] = {i: [] for i in range(7)}
    fallback_pool: list[str] = []

    for r in query_results:
        pts = _points_from_query_result(r, max_points=3)
        if not pts:
            continue
        idx = _classify_question_to_slide_idx(r.get("question", ""))
        bucketed[idx].extend(pts)
        fallback_pool.extend(pts)

    fallback_pool = _dedupe_points_for_slide(fallback_pool)

    for i, slide in enumerate(outline.slides):
        existing = list(slide.points or [])
        # Keep points that already look like concrete answers (contain numbers/currency/percent).
        concrete_existing = [p for p in existing if any(c.isdigit() for c in p) or "$" in p or "%" in p]
        merged = list(concrete_existing)
        merged.extend(bucketed.get(i, []))
        if len(merged) < 3:
            merged.extend(fallback_pool)
        merged = _dedupe_points_for_slide(merged)[:6]
        if merged:
            slide.points = merged


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

        # ── Phase 1: PLAN ─────────────────────────────────────────────────────
        await _emit(job_id, {
            "type": "phase_start", "phase": 1,
            "message": "Planning analytics queries...",
        })

        user_request = (
            f"Generate report for {event_name}"
            + (f"\n\nAdditional context: {additional_context}" if additional_context else "")
        )
        planned_questions = await gemini.plan_questions(user_request=user_request)
        questions = _dedupe_preserve_order(planned_questions)[:MAX_QUESTIONS]

        await _emit(job_id, {
            "type": "phase_done", "phase": 1,
            "message": f"Generated {len(questions)} questions",
            "data": {"questions": questions},
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
            user_request,
            stats,
        ):
            report_tokens.append(token)
            await _emit(job_id, {
                "type": "phase_token",
                "phase": 3,
                "data": {"token": token},
            })

        full_report = "".join(report_tokens)
        print(f"[Pipeline] Phase 3 complete — {len(full_report)} chars synthesized")

        # Guard against partial first-slide responses: retry once with explicit 7-slide shape.
        explicit_slides = _count_explicit_slides(full_report)
        if explicit_slides < 7:
            print(f"[Pipeline] Incomplete synthesis ({explicit_slides}/7 slides). Retrying once...")
            retry_request = (
                user_request
                + "\n\nReturn the report in exactly 7 sections:"
                  "\n### Slide 1: ... through ### Slide 7: ..."
                  "\nEach slide must include at least 3 bullet points and a Key Insight."
            )
            retry_report = await gemini.synthesize_report(data_packet, retry_request, stats)
            retry_slides = _count_explicit_slides(retry_report)
            if retry_slides >= explicit_slides:
                full_report = retry_report
                print(f"[Pipeline] Retry synthesis accepted ({retry_slides}/7 slides, {len(full_report)} chars)")

        outline = parse_report_to_outline(full_report, event_name)
        non_empty_slides = sum(1 for s in outline.slides if (s.points or []))
        if non_empty_slides < 5:
            print(f"[Pipeline] Parsed outline sparse ({non_empty_slides}/7 slides with points). Retrying synthesis once...")
            retry_request = (
                user_request
                + "\n\nEnsure each slide (Slide 1..Slide 7) has 3-6 concrete bullet points "
                  "with numbers from the provided data where available."
            )
            retry_report = await gemini.synthesize_report(data_packet, retry_request, stats)
            retry_outline = parse_report_to_outline(retry_report, event_name)
            retry_non_empty = sum(1 for s in retry_outline.slides if (s.points or []))
            if retry_non_empty >= non_empty_slides:
                full_report = retry_report
                outline = retry_outline
                print(f"[Pipeline] Retry outline accepted ({retry_non_empty}/7 slides with points)")

        # Final grounding pass: make slide bullets answer-oriented from Genie query outputs.
        _enrich_outline_with_query_answers(outline, query_results)

        # Gemini key insights grounded strictly in each slide's bullet text (no extra-stage hallucinations).
        try:
            slide_payload = [(s.title or "", list(s.points or [])) for s in outline.slides]
            gi = await gemini.generate_key_insights_for_slides(slide_payload)
            if gi and len(gi) == len(outline.slides):
                outline = ReportOutline(
                    event_name=outline.event_name,
                    slides=[
                        s.model_copy(update={"insight": gi[i].strip()})
                        for i, s in enumerate(outline.slides)
                    ],
                )
                print("[Pipeline] Gemini slide key insights applied")
        except Exception as ex:
            print(f"[Pipeline] Gemini slide insights skipped: {ex}")

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

import json
import re
from typing import AsyncGenerator, Optional
from google import genai
from google.genai import types
from config import settings
from services import observability


# ── JSON extraction helper ────────────────────────────────────────────────────

def _extract_json_array(raw: str, event_name: str = "") -> list[str]:
    """
    Robustly extract a JSON string array from Gemini output.
    Tries multiple strategies; final fallback generates schema-agnostic questions.
    """
    # Strategy 1: strip markdown fences, then parse
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rstrip("`").strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list) and result:
            return [str(q) for q in result]
    except json.JSONDecodeError:
        pass

    # Strategy 2: first [...] block via regex
    match = re.search(r'\[[\s\S]*?\]', raw)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and result:
                return [str(q) for q in result]
        except json.JSONDecodeError:
            pass

    # Strategy 3: greedy — everything from first [ to last ]
    start, end = raw.find('['), raw.rfind(']')
    if start != -1 and end > start:
        try:
            result = json.loads(raw[start:end + 1])
            if isinstance(result, list) and result:
                return [str(q) for q in result]
        except json.JSONDecodeError:
            pass

    # Fallback: fully domain-agnostic questions — no hardcoded column or table names
    print(f"[Gemini] JSON parse failed — using generic fallback. Raw ({len(raw)}): {raw[:150]}")
    name = event_name or "this event"
    return [
        f"Show me a complete summary of all available data for {name} — every key metric and dimension.",
        f"What are the volume and reach numbers for {name}? Show totals and a breakdown by the primary grouping dimension.",
        f"Show the stage-by-stage progression or funnel for {name} — how many moved through each step and at what conversion rate?",
        f"What were the financial metrics for {name}? Show total spend, cost efficiency, and any ROI measures.",
        f"Which segments, regions, or groups performed best for {name}? Show the top and bottom performers.",
        f"Are there any time-based or comparative metrics for {name} compared to previous periods or similar events?",
        f"Show the account and audience breakdown for {name} — by customer type, tier, geography, or any other available segment.",
    ]


def _extract_json_string_list(raw: str, expected_len: int) -> Optional[list[str]]:
    """Parse a JSON array of strings; pad/truncate to expected_len."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rstrip("`").strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            out = [str(x).strip() for x in result if str(x).strip()]
            if len(out) >= expected_len:
                return out[:expected_len]
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                out = [str(x).strip() for x in result if str(x).strip()]
                if len(out) >= expected_len:
                    return out[:expected_len]
        except json.JSONDecodeError:
            pass
    return None


# ── System prompts ────────────────────────────────────────────────────────────

METRIC_DEFINITIONS = """
## Metric Definitions
- **fPOI (Forecasted Pipeline on Investment)** = SUM(u2_ARR) / SUM(allocated_spend)
  Formula: IF(SUM(allocated_spend) = 0, 0, SUM(u2_ARR) / SUM(allocated_spend))
- **Attendance Rate** = Attended / Registered × 100
- **U2** = Pipeline Created stage
- **U3 / QRR** = Qualified Pipeline stage

## Attribution Rules
- Use existing MTA from gold tables — do NOT re-derive attribution
- Pipeline numbers mature over 30–60 days post-event
- Always use pre-computed registered/attended from rpt_event_performance
- Roll up at parent_program_name level for multi-program events
- Join logic: parent_program_name ↔ program for spend linkage
"""

REPORT_TEMPLATE = """
## Report Structure (7 Slides)

### Slide 1: Executive Summary
KPI headlines: Total Pipeline, Attendance Rate

### Slide 2: Registration & Attendance
Registered count, Attended count, Attendance rate, In-person vs virtual breakdown

### Slide 3: Pipeline Funnel
NNN → MQL → U2 → U3 progression with conversion rates at each stage

### Slide 4: Account Segment Analysis
Business unit breakdown, spend tier, DBX customer vs prospect

### Slide 5: Cost & ROI Analysis
Blank for now

### Slide 6: YoY Comparison
Blank for now

### Slide 7: Cross-Event Comparison
Blank for now
"""

PLANNER_SYSTEM_PROMPT = """
You are an event analytics planner for Databricks marketing. Your job is to
take a user request about an event report and produce 5–8 wide, data-rich
questions for a Genie analytics agent (MARDI) that has access to these tables:

- rpt_event_performance: registration, attendance, NNN, MQL counts by event/child program, pipeline attribution — U2 (created), U3/QRR (qualified), amounts

Rules:
1. Each question should request MULTIPLE metrics in one query (wide, not narrow).
2. Group by child_program or relevant dimension where useful.
3. Always include one question for registration + attendance totals.
4. Always include one question for pipeline funnel (NNN → MQL → U2 → U3).
5. Always include one question for spend / cost data.
6. Include a YoY comparison question if a prior-year event likely exists.
7. Include a question about account segmentation if relevant.
8. Return ONLY a JSON array of question strings. No commentary.

Example output:
[
  "Show me total registered, attended, NNN, and MQL for NRF 2026 grouped by child program",
  "What is the U2 pipeline amount, U2 ARR, U3 pipeline amount, and deal count for NRF 2026",
  "Show the total allocated spend and spend breakdown by category for NRF 2026",
  "What were the registration, attendance, and pipeline numbers for NRF 2025 for YoY comparison",
  "Show unique accounts, DBX customer vs prospect breakdown for NRF 2026 attendees"
]
"""

SYNTHESIZER_SYSTEM_PROMPT = f"""
You are an expert marketing analytics report writer at Databricks.
You receive a data packet containing raw results from multiple queries about
a marketing event. Your job is to synthesize this into a structured report
following the exact slide template below.

{METRIC_DEFINITIONS}

{REPORT_TEMPLATE}

## Instructions
1. Cross-reference data across all query results to build a complete picture.
2. Calculate derived metrics where raw components are available:
   - Attendance Rate = Attended / Registered × 100
   - Cost per Lead = Total Spend / NNN
   - fPOI = U2 ARR / Allocated Spend
   - Conversion rates between funnel stages
3. For each slide, provide:
   - Headline metric(s) with actual numbers
   - Supporting data points and breakdowns
   - **Key insight (1-2 sentences): a concrete finding from the numbers on that slide** — e.g. which segment or program is highest/lowest, the size of the gap, or the direction of change. **Do not** write generic “how to think about this” or management-advice text; the reader must learn something specific from the data.
4. If data for a slide is unavailable, note "[Data Not Available]" and explain what's missing.
5. If YoY data exists, compute percentage changes.
6. Use clean formatting with headers, bullet points, and bold for key numbers.
7. End with a brief "Data Gaps & Caveats" section noting any failed queries or missing data.
8. Be precise with numbers — do not round excessively or fabricate data.
"""

SLIDE_INSIGHTS_SYSTEM_PROMPT = """
You are a marketing analytics editor. You receive JSON with a "slides" array. Each item has:
- "title": slide title
- "points": bullet strings that are the ONLY source of truth for that slide

For each slide, in order, write ONE key insight: 1–2 sentences that interpret the numbers on that slide.

Hard rules (must follow):
- Cite only metrics, stage names (U2, U3, NNN, MQL, etc.), and dollar or percent values that **appear in that slide's points** text. If a stage or amount is not written in the points, do not mention it.
- Do not compare U3 to U2 unless **both** "U3" and "U2" (or the same numbers with those labels) appear in that slide's points.
- You may compute simple derived facts that use only numbers on the slide (e.g. attendance rate from registered and attended if both are in the points).
- No generic management advice. Be specific to the figures given.
- Return ONLY a JSON array of strings, one insight per slide, same order as "slides". Length must equal the number of slides. No markdown, no keys, no commentary.
"""


# ── Service class ─────────────────────────────────────────────────────────────

class GeminiService:
    def __init__(self, api_key: str = None):
        key = api_key or settings.gemini_api_key
        if not key:
            raise ValueError(
                "GEMINI_API_KEY is not configured. "
                "Add GEMINI_API_KEY=your_key to backend/.env and restart."
            )
        self.client = genai.Client(api_key=key)

    async def plan_questions(self, user_request: str) -> list[str]:
        user_msg = user_request

        with observability.traced_generation(
            "gemini-plan-questions",
            settings.gemini_plan_model,
            {"system_instruction": PLANNER_SYSTEM_PROMPT, "user_message": user_msg},
            metadata={"temperature": 0.2, "max_output_tokens": 1500},
        ) as gen:
            response = await self.client.aio.models.generate_content(
                model=settings.gemini_plan_model,
                contents=user_msg,
                config=types.GenerateContentConfig(
                    system_instruction=PLANNER_SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=1500,
                ),
            )

            raw = (response.text or "").strip()
            print(f"[Gemini] Planner response ({len(raw)} chars): {raw[:300]}")
            questions = _extract_json_array(raw, user_request)

            if gen:
                gen.update(
                    output=questions,
                    usage_details=observability.usage_details_from_gemini(response),
                )
            return questions

    async def synthesize_report_streaming(
        self,
        data_packet: str,
        user_request: str,
        stats: dict,
    ) -> AsyncGenerator[str, None]:
        user_msg = (
            f"## Original Request\n"
            f"{user_request}\n\n"
            f"## Query Statistics\n"
            f"- Queries sent: {stats.get('total_queries', 0)}\n"
            f"- Succeeded: {stats.get('succeeded', 0)}\n"
            f"- Failed: {stats.get('failed', 0)} (indices: {stats.get('failed_indices', [])})\n\n"
            f"## Raw Data from Genie\n"
            f"{data_packet}\n\n"
            f"Please synthesize this data into the 7-slide report format."
        )

        with observability.traced_generation(
            "gemini-synthesize-report",
            settings.gemini_synth_model,
            {"system_instruction": SYNTHESIZER_SYSTEM_PROMPT, "user_message": user_msg},
            metadata={"temperature": 0.3, "max_output_tokens": 4000, "query_stats": stats},
        ) as gen:
            stream = await self.client.aio.models.generate_content_stream(
                model=settings.gemini_synth_model,
                contents=user_msg,
                config=types.GenerateContentConfig(
                    system_instruction=SYNTHESIZER_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=4000,
                ),
            )
            collected: list[str] = []
            last_chunk = None
            async for chunk in stream:
                last_chunk = chunk
                if chunk.text:
                    collected.append(chunk.text)
                    yield chunk.text

            if gen:
                gen.update(
                    output="".join(collected),
                    usage_details=(
                        observability.usage_details_from_gemini(last_chunk)
                        if last_chunk is not None
                        else None
                    ),
                )

    async def synthesize_report(self, data_packet: str, user_request: str, stats: dict) -> str:
        parts = []
        async for token in self.synthesize_report_streaming(
            data_packet,
            user_request,
            stats,
        ):
            parts.append(token)
        return "".join(parts)

    async def generate_key_insights_for_slides(
        self,
        slides: list[tuple[str, list[str]]],
    ) -> Optional[list[str]]:
        """
        One grounded insight per slide from bullet text only (no hallucinated metrics).
        slides: list of (title, points) in deck order.
        """
        if not slides:
            return None
        payload = {
            "slides": [
                {"title": t or "", "points": list(p or [])}
                for t, p in slides
            ],
        }
        user_msg = json.dumps(payload, ensure_ascii=False)
        with observability.traced_generation(
            "gemini-slide-insights",
            settings.gemini_synth_model,
            {"system_instruction": SLIDE_INSIGHTS_SYSTEM_PROMPT, "user_message": user_msg},
            metadata={"temperature": 0.25, "max_output_tokens": 2500, "slide_count": len(slides)},
        ) as gen:
            response = await self.client.aio.models.generate_content(
                model=settings.gemini_synth_model,
                contents=user_msg,
                config=types.GenerateContentConfig(
                    system_instruction=SLIDE_INSIGHTS_SYSTEM_PROMPT,
                    temperature=0.25,
                    max_output_tokens=2500,
                ),
            )
            raw = (response.text or "").strip()
            print(f"[Gemini] Slide insights response ({len(raw)} chars): {raw[:400]}")
            parsed = _extract_json_string_list(raw, len(slides))

            if gen:
                gen.update(
                    output=parsed,
                    usage_details=observability.usage_details_from_gemini(response),
                )

            if not parsed or len(parsed) != len(slides):
                return None
            return parsed

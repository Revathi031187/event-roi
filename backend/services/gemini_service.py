import json
import re
from typing import AsyncGenerator
from google import genai
from google.genai import types
from config import settings


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


# ── System prompts ────────────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """
You are a data analytics question architect. You design natural-language questions for a
conversational BI agent called Genie that automatically translates English to SQL.

## THE GOLDEN RULE — Write Plain Business English
Genie maps business language to actual database columns automatically.
You MUST NOT use SQL, column names, or table names in your questions.

Examples of CORRECT questions:
  ✓ "How many people registered vs actually attended, broken down by city or program?"
  ✓ "What is the total revenue pipeline created, by deal stage and region?"
  ✓ "Show total spend by category and calculate cost per attendee and cost per lead"
  ✓ "Which geographic regions generated the most pipeline value?"

Examples of WRONG questions:
  ✗ "SELECT registered_count FROM rpt_event_performance GROUP BY child_program"
  ✗ "Show u2_amount and u3_amount by child_program"
  ✗ "What is SUM(allocated_spend) from gold_roi_attribution_spend?"

## How to Use Schema Information
When a data schema is provided:
  1. Identify KEY DIMENSIONS — categorical columns used for grouping (program, city, region, segment, date, tier, etc.)
  2. Identify KEY MEASURES — numeric columns (counts, amounts, rates, booleans)
  3. Translate any technical labels from the discovered schema into business-friendly wording
  4. ONLY ask about topics that exist in the schema
  5. Write broad questions so Genie can handle slight column-name variations
  6. If header + first-row previews are available, prioritize columns and dimensions that clearly appear in those previews
  7. Avoid asking for metrics that are not visible in schema or sample previews

## Question Coverage (include each domain if schema supports it)
  1. Overview/Summary: total KPIs, counts, top-level performance
  2. Volume & Engagement: registrations, attendance, reach, participation
  3. Lead Generation: leads, MQLs, pipeline qualification, conversion rates
  4. Revenue Pipeline: deal values, ARR, opportunity amounts, stages
  5. Cost & ROI: spend totals, cost per lead/attendee, efficiency ratios, ROI
  6. Segmentation: by region, account type, customer vs. prospect, tier
  7. Trends & Comparison: year-over-year, prior period, multi-event patterns

## Output
Return ONLY a valid JSON array of 5-8 question strings. No markdown, no commentary.
["question one", "question two", ...]
"""

SYNTHESIZER_SYSTEM_PROMPT = """
You are an expert analytics report writer. You receive structured data from multiple
Genie queries and synthesize it into a professional, evidence-based slide report.

## Step 1 — Inventory What Data Actually Arrived
Before writing a single word:
- List every query that SUCCEEDED and what columns/rows came back
- Identify the KEY DIMENSIONS in the data (what categories/groups exist)
- Identify the KEY MEASURES (what numbers are in the data)
- Note every FAILED or DEMO query — those topics will have no data

## Step 2 — Calculate Derived Metrics
From available raw data, compute everything derivable:
- Rates: attendance_rate = attended / registered × 100
- Efficiency: cost per lead = total_spend / total_leads
- Totals: SUM all numeric columns across rows
- Conversion: each stage ÷ prior stage × 100
- YoY delta: (current − prior) / prior × 100
- ROI/multiplier: pipeline_value / spend

## Step 3 — Build a fixed 7-slide executive event report
Use this exact template in this exact order (do not skip slides):
1) Executive Summary
2) Pipeline and Revenue Performance
3) Funnel and Conversion Health
4) Audience and Segment Performance
5) Platform and Data Quality
6) Financial Efficiency and ROI
7) Risks, Actions, and Next Steps

For each slide, provide:
- one headline metric line
- at least 3 and at most 6 bullet points
- one Key Insight paragraph
- add a markdown table whenever numeric breakdowns are available
- every bullet must be an ANSWER/observation from data, not a question/instruction
- if an intended metric is unavailable, substitute with the best available metric from returned data
- avoid repeating the same primary metric across multiple slides; each slide should emphasize a distinct analytic angle
- for Slide 7, include a mix of risks and actions (at least 2 risk bullets and at least 2 action bullets)
- ensure all major user-relevant metric areas are covered across the 7 slides: attendance, funnel, lead quality, pipeline, segment variance, financial efficiency, trend/data quality

Standard slide structure:
## Slide N: [Clear Business Title]
**Headline Metric:** [exact number from data]
- [Supporting data point with number]
- [Breakdown or segment insight]
- [Comparison or rate if available]
### Key Insight
[Analytic conclusion — see rules below]

### Key Insight — mandatory writing rules
- State what the data implies: trends, concentration, segment gaps, funnel choke points, efficiency, or risk — not a meta-description of the slide.
- Do NOT copy, paraphrase, concatenate, or summarize the slide bullets in the Key Insight. The Key Insight must add net-new interpretation: tradeoffs, sequencing priorities, cross-bullet implications, or where decisions should diverge from averages — wording must be clearly distinct from every bullet line.
- Start directly with substance (a metric, segment, stage, region, rate, or contrast). Do NOT use filler openers such as: "The strongest signal...", "The strongest indication...", "This slide shows...", "The key takeaway is...", "It is important to note...", or "Overall," as the opening.
- Prefer interpretations over repetition: if the headline already states a number, explain divergence across segments, direction vs benchmark, tradeoff, or what decision is pressured — do not restate the same figure alone.
- Use 1-3 sentences; include at least one contrast, comparison, or concentration pattern when the bullets support it (e.g. top vs bottom, early vs late funnel, region vs region).
- Slide-specific angles: Executive Summary = cross-slide tradeoffs; Pipeline = value concentration and qualification; Funnel = where conversion breaks; Audience = who over- or under-performs; Platform/Data = confidence and gaps; Financial = spend vs yield; Risks/Actions = prioritized exposure and next moves.

## End with:
## Data Gaps & Caveats
List any queries that failed, data topics with no results, and limitations.

## Absolute Rules
- NEVER invent a number. Every figure must come from the provided data.
- NEVER invent event, campaign, or program names. If a name is not explicitly present in returned data, refer to it as "the event" or "the program".
- Do NOT use placeholder text such as "[Data Not Available]" in slide bullets.
- Do NOT mention missing data in slide bullets; reframe the slide around available evidence only.
- When both narrative text and tabular values are present, prioritize tabular values as source-of-truth.
- Never claim a metric is zero if any returned tabular values for that metric are non-zero.
- Do NOT use markdown emphasis in output (no **bold**, no *italics*, no backticks).
- Preserve exact numeric values from Genie output (no alteration of value digits/sign/scale).
- Every headline metric must be traceable to at least one returned Genie query block.
- Do NOT round aggressively — preserve meaningful precision from the data.
- Do NOT write bullets like "Show...", "Compare...", "Summarize...", "List..." or other instruction phrasing.
- Do NOT write questions in bullets.
- Keep the 7 slides differentiated: attendance/engagement, funnel behavior, pipeline outcomes, segment variance, data/platform reliability, financial efficiency, and prioritized actions.
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

    async def plan_questions(
        self,
        event_name: str,
        context: str = "",
        schema_info: str = "",
    ) -> list[str]:
        if schema_info:
            schema_section = (
                f"\n\n## Live Data Schema from Genie\n"
                f"The following schema was discovered directly from the Genie space. "
                f"It includes inventory plus header/row previews. "
                f"Use ONLY the concepts, dimensions, and measures described here.\n\n"
                f"{schema_info}"
            )
        else:
            schema_section = (
                "\n\n## Data Schema\n"
                "Schema could not be discovered. Generate broad, concept-level questions "
                "covering all typical analytics domains (volume, pipeline, cost, segmentation, trends). "
                "Do NOT reference specific column or table names."
            )

        user_msg = (
            f"Generate analytical questions for: {event_name}"
            + (f"\n\nAdditional context: {context}" if context else "")
            + schema_section
        )

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
        return _extract_json_array(raw, event_name)

    async def synthesize_report_streaming(
        self,
        data_packet: str,
        event_name: str,
        stats: dict,
        planned_questions: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        planned_section = ""
        if planned_questions:
            planned_lines = "\n".join(f"- Q{i+1}: {q}" for i, q in enumerate(planned_questions))
            planned_section = (
                "## Planned User-Relevant Questions (must be covered in report)\n"
                f"{planned_lines}\n\n"
            )
        user_msg = (
            f"## Report Request\n"
            f"Event/Campaign: {event_name}\n\n"
            f"## Query Statistics\n"
            f"- Total queries: {stats.get('total_queries', 0)}\n"
            f"- Succeeded: {stats.get('succeeded', 0)}\n"
            f"- Failed/No data: {stats.get('failed', 0)}\n\n"
            f"{planned_section}"
            f"## Data from Genie (use ONLY this data)\n"
            f"{data_packet}\n\n"
            f"Synthesize the above into a fixed 7-slide executive event report for both technical and non-technical stakeholders. "
            f"Complete ALL seven slides in full — do not stop early; keep bullets concise if needed so Slide 7 and Data Gaps fit. "
            f"Each slide must include a headline metric, 3-6 bullets, and a key insight that analyzes trends and contrasts — "
            f"not slide-meta phrases (avoid openings like 'the strongest indication for this slide'). "
            f"Each Key Insight must NOT repeat or stitch together that slide's bullet lines; add distinct analytic judgment. "
            f"Ensure important user-relevant metrics are covered across slides and preserve exact Genie values. "
            f"Every number must come from the data above."
        )

        stream = await self.client.aio.models.generate_content_stream(
            model=settings.gemini_synth_model,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYNTHESIZER_SYSTEM_PROMPT,
                temperature=0.3,
                max_output_tokens=16384,
            ),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    async def synthesize_report(
        self, data_packet: str, event_name: str, stats: dict, planned_questions: list[str] | None = None
    ) -> str:
        parts = []
        async for token in self.synthesize_report_streaming(
            data_packet,
            event_name,
            stats,
            planned_questions=planned_questions,
        ):
            parts.append(token)
        return "".join(parts)

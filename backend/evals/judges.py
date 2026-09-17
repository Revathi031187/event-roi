"""
Tier 2 (LLM-as-judge) evaluators — reference-free, sampled, run OUT-OF-BAND
by backend/evals/run_evaluators.py, never inline in the live request path
(see pipeline_service.run_pipeline's comment on why: judge calls cost real
money/latency and this app has no worker/queue to hide that behind).

Reads the two prompt files in evals/prompts/ as the actual rubric — this
module renders + calls the judge model; it does not embed its own copy of
the criteria (keeps prompt and code from silently drifting apart, per
phase-d2's "treat evaluator prompts as something that goes stale" note).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from google import genai
from google.genai import types as genai_types

from config import settings

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# Deliberately a small/cheap model for the judge — this is a cost surface
# (see references/security-production.md, cost governance), not the same
# model tier as the app's own synthesis call.
JUDGE_MODEL = "gemini-2.5-flash"


def _load_prompt(filename: str) -> str:
    path = os.path.join(_PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _render(template: str, **kwargs: Any) -> str:
    rendered = template
    for key, value in kwargs.items():
        placeholder = "{{" + key + "}}"
        value_str = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        rendered = rendered.replace(placeholder, value_str)
    return rendered


def _extract_json_object(raw: str) -> Optional[dict]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rstrip("`").strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    return None


def _call_judge(rendered_prompt: str) -> Optional[dict]:
    """Returns the parsed {"score": ..., "rationale": ...} dict, or None on
    any failure (timeout, non-JSON response, empty response) — callers MUST
    treat None as "unscored, retry later," never as a crashed pipeline or as
    a silent pass/fail (see security-production.md, graceful judge-failure
    handling)."""
    if not settings.gemini_api_key:
        return None
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=JUDGE_MODEL,
            contents=rendered_prompt,
            config=genai_types.GenerateContentConfig(temperature=0.0, max_output_tokens=500),
        )
        raw = (response.text or "").strip()
        parsed = _extract_json_object(raw)
        if parsed is None or "score" not in parsed:
            print(f"[Judge] Unparseable judge response, discarding (not scored): {raw[:200]}")
            return None
        return parsed
    except Exception as exc:
        print(f"[Judge] Judge call failed (unscored, will retry next run): {type(exc).__name__}: {exc}")
        return None


def judge_report_numeric_groundedness(
    *, user_request: str, data_packet: str, report_text: str
) -> Optional[dict]:
    template = _load_prompt("report_numeric_groundedness.prompt.md")
    prompt = _render(template, input=user_request, context=data_packet, output=report_text)
    return _call_judge(prompt)


def judge_slide_insight_specificity(
    *, slide_title: str, slide_points: list[str], insight_text: str
) -> Optional[dict]:
    template = _load_prompt("slide_insight_specificity.prompt.md")
    prompt = _render(template, input=slide_title, context=slide_points, output=insight_text)
    return _call_judge(prompt)

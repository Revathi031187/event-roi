import re
from typing import Optional
from models.schemas import SlideOutline, ReportOutline

TEMPLATE_TITLES = [
    "Executive Summary",
    "Registration & Attendance",
    "Pipeline Funnel",
    "Account Segment Analysis",
    "Cost & ROI Analysis",
    "YoY Comparison",
    "Cross-Event Comparison",
]

# Analytic one-liners for when parsed/derived insights merely echo bullets (must not repeat bullet wording).
BRIDGE_INSIGHTS_BY_TITLE = {
    "Executive Summary": (
        "Tradeoffs across engagement, funnel, and efficiency show where leadership attention "
        "will move outcomes fastest versus where the program already clears the bar."
    ),
    "Registration & Attendance": (
        "Attendance performance should be judged by where conversion from registered to attended diverges "
        "across programs or regions, not by a single blended event average."
    ),
    "Pipeline Funnel": (
        "The useful signal is where drop-offs cluster between stages, not a single headline "
        "conversion rate; interventions should target the widest stage-to-stage gap first."
    ),
    "Account Segment Analysis": (
        "When segments diverge, replication budgets should follow the pockets that already "
        "convert while diagnosing structural gaps in laggards."
    ),
    "Cost & ROI Analysis": (
        "Efficiency is meaningful only against pipeline yield: compare spend to qualified outcomes "
        "before reallocating budget across motions."
    ),
    "YoY Comparison": (
        "Year-over-year movement should be interpreted by separating scale effects from conversion "
        "quality shifts, so growth is tied to durable funnel performance."
    ),
    "Cross-Event Comparison": (
        "Cross-event variance is most useful when it identifies repeatable drivers and outliers "
        "that should inform future event design."
    ),
}


TEMPLATE_DEFAULT_POINTS = {
    "Executive Summary": [
        "Current evidence indicates this event generated measurable engagement and business impact.",
        "Performance concentration is visible across a subset of observed dimensions.",
        "Available metrics suggest clear opportunities to improve conversion and efficiency.",
    ],
    "Registration & Attendance": [
        "Registration and attendance volumes should be compared together to diagnose conversion from sign-up to participation.",
        "Participation efficiency varies across available segments or programs in the returned data.",
        "Improvement opportunity is concentrated in under-converting cohorts rather than in top performers.",
    ],
    "Pipeline Funnel": [
        "Funnel progression can be partially inferred from returned stage-level metrics.",
        "Early-stage engagement appears stronger than later-stage conversion in available data.",
        "Conversion lift is most likely to come from improving mid-to-late funnel transitions.",
    ],
    "Account Segment Analysis": [
        "Segment-level performance varies across available categories in the response.",
        "Audience mix suggests targeted follow-up can improve outcome concentration.",
        "Top-performing segments provide a replicable pattern for upcoming events.",
    ],
    "Cost & ROI Analysis": [
        "Available financial indicators suggest positive outcome potential where pipeline is concentrated.",
        "Efficiency appears strongest in segments with higher conversion quality.",
        "ROI trends indicate budget should be prioritized toward high-yield motions.",
    ],
    "YoY Comparison": [
        "Comparative movement versus prior period should prioritize both scale and conversion quality deltas.",
        "Any growth pattern should be validated against underlying funnel consistency.",
        "Direction-of-change signals can guide planning assumptions for the next cycle.",
    ],
    "Cross-Event Comparison": [
        "Cross-event performance variance reveals which playbooks are repeatable across event formats.",
        "Top and bottom events can be contrasted to isolate the strongest operational drivers.",
        "Future event planning should replicate high-yield patterns while correcting recurrent weak spots.",
    ],
}


def parse_report_to_outline(report_text: str, event_name: str) -> ReportOutline:
    """Parse markdown report into a robust 7-slide business outline."""
    slides: list[SlideOutline] = []

    slide_pattern = re.compile(
        r"#{2,6}\s+Slide\s+(\d+)\s*[:\-–]\s*(.+?)(?=#{2,6}\s+Slide\s+\d+|#{2,6}\s+Data\s+Gaps|$)",
        re.DOTALL | re.IGNORECASE,
    )
    matches = list(slide_pattern.finditer(report_text))

    for match in matches:
        slide_num = int(match.group(1))
        title = _clean_text(match.group(2).split("\n")[0].strip())
        content = match.group(0)

        insight = ""
        insight_match = re.search(
            r"#{2,6}\s+Key\s+Insight\s*\n(.*?)(?=#{2,6}\s+|$)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if not insight_match:
            insight_match = re.search(
                r"\*\*Key\s+Insights?:\*\*\s*\n(.*?)(?=\n#{2,6}\s+|\n---\n|$)",
                content,
                re.DOTALL | re.IGNORECASE,
            )
        if insight_match:
            insight = _sanitize_key_insight(_clean_text(insight_match.group(1).strip()))

        sub_headers = re.findall(r"#{3,6}\s+(.+?)(?=\n|$)", content, re.MULTILINE)
        sub_headers = [h for h in sub_headers if not re.search(r"key\s*insight", h, re.IGNORECASE)]

        points = _extract_points_from_content(content, max_points=10)
        table_data = _extract_table(content)

        slides.append(
            SlideOutline(
                id=f"slide-{slide_num}",
                number=slide_num,
                title=title,
                subtitle=_clean_text(sub_headers[0]) if sub_headers else "",
                points=points,
                insight=insight,
                table_data=table_data,
            )
        )

    if not slides:
        slides = _create_fallback_outline(report_text)

    slides = _ensure_seven_slides(slides, report_text)
    return ReportOutline(event_name=event_name, slides=slides)


def _clean_text(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text or "")
    text = text.replace("*", "")
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


def _extract_points_from_content(content: str, max_points: int = 10) -> list[str]:
    points: list[str] = []

    for line in content.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if re.match(r"^[-*]\s+", s):
            candidate = _clean_text(re.sub(r"^[-*]\s+", "", s))
            if _is_valid_point(candidate):
                points.append(candidate)
            continue
        if re.match(r"^\d+\.\s+", s):
            candidate = _clean_text(re.sub(r"^\d+\.\s+", "", s))
            if _is_valid_point(candidate):
                points.append(candidate)
            continue
        if re.match(r"^\*\*Headline Metric:\*\*", s, re.IGNORECASE):
            candidate = _clean_text(re.sub(r"^\*\*Headline Metric:\*\*\s*", "", s, flags=re.IGNORECASE))
            if _is_valid_point(candidate):
                points.append(candidate)

    if len(points) >= 3:
        return _dedupe_points(points)[:max_points]

    # Fallback to sentence extraction when bullets are sparse.
    prose = re.sub(r"\|.*\|", " ", content)  # strip table rows
    prose = re.sub(r"#+\s*", "", prose)
    prose = _clean_text(prose)
    sentences = re.split(r"(?<=[.!?])\s+", prose)
    for sent in sentences:
        s = sent.strip(" -")
        if len(s) < 35 or len(s) > 220:
            continue
        if s.lower().startswith(("slide ", "key insight", "data gaps")):
            continue
        candidate = _clean_text(s)
        if _is_valid_point(candidate):
            points.append(candidate)
        if len(points) >= max_points:
            break

    sanitized = [p for p in _dedupe_points(points) if _is_valid_point(p)]
    return sanitized[:max_points]


def _seed_points_from_report(report_text: str, max_points: int = 42) -> list[str]:
    candidates: list[str] = []
    for line in report_text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if re.match(r"^[-*]\s+", s) or re.match(r"^\d+\.\s+", s):
            candidate = _clean_text(re.sub(r"^([-*]|\d+\.)\s+", "", s))
            if _is_valid_point(candidate):
                candidates.append(candidate)
        elif re.search(r"\d", s) and 30 <= len(s) <= 170 and not s.startswith("#"):
            candidate = _clean_text(s)
            if _is_valid_point(candidate):
                candidates.append(candidate)
    return _dedupe_points(candidates)[:max_points]


def _dedupe_points(points: list[str]) -> list[str]:
    seen = set()
    seen_metric_signatures = set()
    out: list[str] = []
    for p in points:
        key = re.sub(r"\s+", " ", p.lower()).strip()
        if not key or key in seen:
            continue
        metric_sig = _metric_signature(key)
        if metric_sig and metric_sig in seen_metric_signatures:
            continue
        seen.add(key)
        if metric_sig:
            seen_metric_signatures.add(metric_sig)
        out.append(p)
    return out


def _metric_signature(text: str) -> str:
    """Semantic dedupe key for repeated headline-style metrics."""
    metric_labels = [
        "total registrations",
        "registrations",
        "total attended",
        "attendance rate",
        "pipeline value",
        "qualified pipeline",
        "mql",
        "leads",
        "cost per lead",
        "roi",
    ]
    metric = next((m for m in metric_labels if m in text), "")
    if not metric:
        return ""
    num_match = re.search(r"\$?\d[\d,]*(?:\.\d+)?%?", text)
    if not num_match:
        return metric
    num = num_match.group(0).replace(",", "")
    return f"{metric}:{num}"


_INSIGHT_BOILERPLATE = re.compile(
    r"^(?:(?:the\s+)?(?:strongest|strong)\s+(?:signal|indication|finding|takeaway)\s+"
    r"(?:on\s+this\s+slide\s+)?(?:is\s+that\s*)"
    r"|(?:the\s+)?key\s+(?:takeaway|insight|finding)\s+"
    r"(?:from\s+this\s+(?:slide|section|chart)\s+)?(?:is\s+that\s*)"
    r"|this\s+slide\s+(?:shows|demonstrates|highlights|indicates)\s+(?:that\s*)?"
    r"|(?:the\s+)?(?:primary|main)\s+(?:finding|takeaway)\s+(?:here\s+)?(?:is\s+that\s*)"
    r"|overall,?\s+(?:the\s+)?(?:main\s+)?(?:point|finding)\s+is\s+that\s*)",
    re.IGNORECASE,
)


def _sanitize_key_insight(text: str) -> str:
    """Strip generic AI openers so insights lead with analytic substance."""
    t = (text or "").strip()
    if not t:
        return ""
    original = t
    for _ in range(4):
        t2 = _INSIGHT_BOILERPLATE.sub("", t).strip()
        if t2 == t:
            break
        t = t2
    if t and original != t:
        t = t[0].upper() + t[1:] if len(t) > 1 else t.upper()
    return t


def _clip_first_clause(text: str, max_len: int = 280) -> str:
    """First sentence or clause for merging bullet evidence into one insight."""
    t = (text or "").strip()
    if not t:
        return ""
    for sep in (". ", "; ", " — ", "\n"):
        if sep in t:
            t = t.split(sep)[0]
            break
    t = t.strip()
    if len(t) > max_len:
        t = t[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return t


def _join_analytic_clauses(a: str, b: str) -> str:
    """Join two bullet-derived clauses with a semicolon (keeps codes like U2, ARR intact)."""
    a = _clip_first_clause(a).rstrip(".")
    b = _clip_first_clause(b).rstrip(".")
    if not a:
        return (b + ".") if b else ""
    if not b or a.lower() == b.lower():
        return a + "."
    return f"{a}; {b}."


def _strip_risk_action_label(text: str) -> str:
    """Normalize 'Risk: ...' / 'Action: ...' bullets for comparison."""
    t = (text or "").strip()
    t = re.sub(r"^(risk|action)\s*:\s*", "", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip().lower()


def _insight_is_trivial_fragment(insight: str) -> bool:
    """Single-cell style lines (e.g. 'Prospect: $0.00') are not insights."""
    t = re.sub(r"\s+", " ", (insight or "").strip())
    if not t:
        return True
    tl = t.lower()
    if re.search(r":\s*\$0\.00", tl):
        return True
    # One short "Label: $amount" with no analysis (and not a long sentence)
    if len(t) < 55 and re.match(
        r"^[\w\s,'/-]{1,40}:\s*\$[\d,]+\.\d{2}\.?\s*$", t, re.I
    ):
        return True
    return False


def _insight_is_metric_echo(insight: str, points: list[str]) -> bool:
    """
    True when the 'insight' is only restating one KPI from the bullets (same text or label:$ pattern),
    not synthesizing across metrics.
    """
    if not (insight or "").strip() or not points:
        return False
    ins = re.sub(r"\s+", " ", insight.strip().lower())
    ins_loose = re.sub(r"[^a-z0-9$%.]+", "", ins)
    blob = " ".join(points).lower()
    blob_loose = re.sub(r"[^a-z0-9$%.]+", "", blob)

    if len(ins) >= 12 and len(ins_loose) >= 10 and ins_loose in blob_loose:
        return True
    for p in points:
        pl = re.sub(r"\s+", " ", p.strip().lower())
        if len(ins) >= 14 and ins in pl:
            return True

    comparative = (
        "versus", " vs ", " than ", "exceed", "compared", " while ", " between ",
        "ratio", "range", "span ", "stronger", "weaker", "higher ", "lower ",
        "×", " outpaces ", " lags ", " diverg ", "mix ",
    )
    if len(ins) <= 110 and re.search(r":\s*\$[\d,]+\.\d{2}", ins):
        if not any(c in ins for c in comparative):
            return True
    return False


def _insight_redundant_with_points(insight: str, points: list[str]) -> bool:
    """
    True if the insight restates bullets (including semicolon-joined copies of two bullets)
    or largely reuses the same words without adding analytic distance.
    """
    if not (insight or "").strip():
        return True
    if not points:
        return False
    if _insight_is_trivial_fragment(insight):
        return True
    if _insight_is_metric_echo(insight, points):
        return True

    inorm = re.sub(r"\s+", " ", insight.strip().lower())
    p_norms = [re.sub(r"\s+", " ", p.strip().lower()) for p in points]
    p_body = [_strip_risk_action_label(p) for p in points]

    if inorm in p_norms:
        return True

    parts = [p.strip() for p in re.split(r"\s*;\s*", insight) if p.strip()]
    if len(parts) >= 2:
        part_bodies = [_strip_risk_action_label(x) for x in parts]
        hits = 0
        for pb in part_bodies:
            if any(pb == bb or (len(pb) >= 24 and (pb in bb or bb in pb)) for bb in p_body if bb):
                hits += 1
        if hits >= 2:
            return True

    # High word overlap with bullet vocabulary (insight is mostly a rearrangement)
    insight_words = set(re.findall(r"[a-z]{3,}", inorm))
    if len(insight_words) < 6:
        return False
    bullet_words: set[str] = set()
    for p in points:
        bullet_words.update(re.findall(r"[a-z]{3,}", p.lower()))
    overlap = len(insight_words & bullet_words)
    if overlap / max(len(insight_words), 1) >= 0.75:
        return True

    return False


def _bridge_insight_for_title(title: str) -> str:
    return BRIDGE_INSIGHTS_BY_TITLE.get(
        title,
        "Use the metrics above to prioritize where gaps are widest; avoid averaging away segment or stage differences.",
    )


_GENERIC_INSIGHT_MARKERS = (
    "efficiency is meaningful only",
    "tradeoffs across engagement",
    "use the metrics above",
    "the useful signal is where drop-offs",
    "when segments diverge, replication",
    "year-over-year movement should",
    "cross-event variance is most useful",
    "should be judged by",
    "interventions should target",
    "before reallocating budget",
    "the gap between them is the main story",
    "the data contrasts",
    "dominant quantitative signal",
    "headline figure on this slide",
    "segment mix drives portfolio",
    "relative scale matters more than",
    "interpretation for ",
    "follows from how segments",
)


def is_generic_playbook_insight(text: str) -> bool:
    """True if insight reads like generic advice rather than a finding from this slide."""
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(m in low for m in _GENERIC_INSIGHT_MARKERS)


def _fmt_currency_us(n: float) -> str:
    return f"${n:,.2f}"


def _short_segment_label(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "This segment"
    parts = re.split(r"[-_/]", s)
    for p in reversed(parts):
        p = p.strip()
        if len(p) >= 3 and p.upper() not in ("EV", "FY27Q1", "FY27", "Q1", "Q2", "Q3", "Q4", "AIDAYS"):
            return p
    return s[:48] if len(s) > 48 else s


def _money_amounts_in_text(s: str) -> list[float]:
    out: list[float] = []
    for m in re.finditer(r"\$([\d,]+(?:\.\d+)?)", s or ""):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except Exception:
            continue
    return out


def _qualified_pipeline_from_line(line: str) -> Optional[float]:
    m = re.search(r"total_qualified_pipeline\s*=\s*\$([\d,]+\.\d{2})", line, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except Exception:
            pass
    # Field present but corrupted — take largest dollar amount on the line as pipeline proxy
    if re.search(r"total_qualified_pipeline", line, re.I):
        amounts = _money_amounts_in_text(line)
        return max(amounts) if amounts else None
    amounts = _money_amounts_in_text(line)
    if not amounts:
        return None
    return max(amounts)


def _segment_label_from_line(line: str) -> str:
    m = re.search(r"parent_program_name:\s*([^->\n]+?)(?:\s*->|\Z)", line, re.I)
    if m:
        return _short_segment_label(m.group(1).strip())
    m2 = re.search(r"([A-Za-z][A-Za-z0-9_\-]{2,})\s*->", line)
    if m2:
        return _short_segment_label(m2.group(1).strip())
    return ""


def _metric_led_sentence(line: str, max_len: int = 210) -> str:
    """Turn the strongest numeric clause in a bullet into one standalone sentence."""
    t = _clean_text(line).strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t)
    # Prefer clause containing first currency or percentage or large count
    m = re.search(r"(\$[\d,]+\.\d{2}|[\d.]+\s*%|\b\d[\d,]{2,}\b)", t)
    if m:
        i = max(0, m.start() - 55)
        chunk = t[i : m.end() + 95].strip()
        if i > 0 and not chunk.startswith("…"):
            chunk = "…" + chunk.lstrip()
    else:
        chunk = _clip_first_clause(t, max_len=max_len)
        return chunk if chunk.endswith(".") else chunk + "."

    if len(chunk) > max_len:
        chunk = chunk[: max_len - 1].rsplit(" ", 1)[0] + "…"
    if chunk and not chunk.endswith((".", "…")):
        chunk += "."
    # Do not return a lone zero-dollar cell as an "insight"
    if re.search(r":\s*\$0\.00", chunk, re.I) and len(chunk) < 70:
        return ""
    return chunk


def _compose_insight_from_bullets(title: str, pts: list[str]) -> str:
    """
    Derive an insight only from extracted metrics — no fixed 'contrast / gap / main story' wrapper.
    """
    tl = (title or "").lower()
    blob = " ".join(pts)

    # Per-line: label + max dollar (same basis as segment/cost parsing)
    dollar_rows: list[tuple[str, float]] = []
    for p in pts:
        lab = _segment_label_from_line(p)
        mx = max(_money_amounts_in_text(p), default=None)
        if lab and mx is not None:
            dollar_rows.append((lab, mx))
    if len(dollar_rows) >= 2:
        dollar_rows.sort(key=lambda x: x[1], reverse=True)
        top_l, top_v = dollar_rows[0]
        bot_l, bot_v = dollar_rows[-1]
        if top_v > bot_v:
            # Wording variants — same facts, different surface form
            if hash(tl + top_l) % 2 == 0:
                return (
                    f"{top_l} reaches {_fmt_currency_us(top_v)} in this slice; "
                    f"{bot_l} measures {_fmt_currency_us(bot_v)} under the same fields."
                )
            return (
                f"Largest dollar reading is {_fmt_currency_us(top_v)} ({top_l}); "
                f"smallest among rows shown is {_fmt_currency_us(bot_v)} ({bot_l})."
            )

    # Percent ranges across bullets
    all_pcts: list[tuple[str, float]] = []
    for p in pts:
        for x in re.findall(r"([\d.]+)\s*%", p):
            try:
                all_pcts.append(("", float(x)))
            except Exception:
                continue
    p_vals = [v for _, v in all_pcts]
    if len(p_vals) >= 2:
        lo, hi = min(p_vals), max(p_vals)
        if hash(tl) % 2 == 0:
            return f"Percentages on this slide run from {lo:.2f}% up to {hi:.2f}%."
        return f"Measured rates span {lo:.2f}%–{hi:.2f}% across the lines above."

    # Single richest bullet → lead with its strongest metric clause
    best = max(pts, key=lambda p: len(re.findall(r"\d", p)) + 4 * len(_money_amounts_in_text(p)))
    one = _metric_led_sentence(best)
    if one:
        return one

    return _clip_first_clause(pts[0], max_len=200) + ("." if pts[0] and not pts[0].strip().endswith(".") else "")


def _executive_summary_insight(points: list[str]) -> str:
    """Cross-metric takeaway for slide 1 — never a single KPI restatement."""
    blob = " ".join(points)
    u2 = u3 = None
    m = re.search(r"\$([\d,]+\.\d{2})\s+in\s+U2", blob, re.I)
    if m:
        u2 = float(m.group(1).replace(",", ""))
    m = re.search(r"\$([\d,]+\.\d{2})\s+in\s+U3", blob, re.I)
    if m:
        u3 = float(m.group(1).replace(",", ""))
    if u2 is None:
        m = re.search(
            r"U2\s+(?:Pipeline|pipeline|ARR)[^\d$]{0,55}\$([\d,]+\.\d{2})",
            blob,
            re.I,
        )
        if m:
            u2 = float(m.group(1).replace(",", ""))
    if u3 is None:
        m = re.search(
            r"U3\s+(?:Qualified\s+)?(?:Pipeline|pipeline|ARR)[^\d$]{0,55}\$([\d,]+\.\d{2})",
            blob,
            re.I,
        )
        if m:
            u3 = float(m.group(1).replace(",", ""))
    rates = [float(x) for x in re.findall(r"([\d.]+)\s*%", blob)]
    rate = rates[0] if rates else None

    has_u2 = bool(re.search(r"\bU2\b", blob, re.I))
    has_u3 = bool(re.search(r"\bU3\b", blob, re.I))

    parts: list[str] = []
    # Compare stages only when BOTH labels appear in the bullet text (avoid phantom U3).
    if u2 is not None and u3 is not None and u2 > 0 and has_u2 and has_u3:
        mult = u3 / u2
        parts.append(
            f"Qualified pipeline (U3, {_fmt_currency_us(u3)}) runs about {mult:.2f}x "
            f"created pipeline (U2, {_fmt_currency_us(u2)}) here — downstream qualification outpaces new pipe creation."
        )
    elif u3 is not None and u2 is not None and has_u2 and has_u3:
        parts.append(
            f"Pipeline totals land at {_fmt_currency_us(u2)} (U2) and {_fmt_currency_us(u3)} (U3) on this slide."
        )
    elif u2 is not None and has_u2 and not has_u3:
        parts.append(
            f"Created pipeline (U2) totals {_fmt_currency_us(u2)} on this executive snapshot."
        )

    if rate is not None:
        parts.append(
            f"Attendance is near {rate:.2f}% of registrations, so most registrants never attended live."
        )

    out = " ".join(parts).strip()
    return out[:480] if out else ""


def insight_requires_rewrite(insight: str, points: list[str]) -> bool:
    """True if stored insight should be replaced with a synthesized analytic line."""
    if not (insight or "").strip():
        return True
    if _insight_is_trivial_fragment(insight):
        return True
    if is_generic_playbook_insight(insight):
        return True
    if _insight_is_metric_echo(insight, points):
        return True
    return False


def _kv_program_comparison_insight(points: list[str]) -> str:
    """
    YoY / cross-program rows often arrive as parent_program_name ... volume=/reach=/registered=.
    Summarize TOTAL plus spread across programs — never a lone 'Prospect: $0.00' cell.
    """
    blob = " ".join(points)
    if not re.search(r"(volume|reach|registered)\s*=", blob, re.I):
        return ""

    total_vol: Optional[int] = None
    total_reach: Optional[int] = None
    for p in points:
        if not re.search(r"parent_program_name:\s*TOTAL", p, re.I):
            continue
        vm = re.search(r"volume=(\d+)", p, re.I)
        rm = re.search(r"reach=(\d+)", p, re.I)
        if vm:
            total_vol = int(vm.group(1))
        if rm:
            total_reach = int(rm.group(1))

    reg_rows: list[tuple[str, int]] = []
    for p in points:
        if re.search(r"parent_program_name:\s*TOTAL\b", p, re.I):
            continue
        pm = re.search(r"parent_program_name:\s*([^;,\n]+?)(?:;|\s*->)", p, re.I)
        if not pm:
            continue
        raw_lab = pm.group(1).strip()
        if raw_lab.upper() == "TOTAL":
            continue
        cm = re.search(r"child_program_name:\s*([^;,\n]+?)(?:;|\s*->)", p, re.I)
        lab_src = cm.group(1).strip() if cm else raw_lab
        lab = _short_segment_label(lab_src)
        rm = re.search(r"registered=(\d+)", p, re.I)
        if rm:
            reg_rows.append((lab, int(rm.group(1))))

    parts: list[str] = []
    if total_vol is not None and total_reach is not None:
        parts.append(
            f"In the TOTAL row, volume is {total_vol:,} and reach is {total_reach:,} - "
            f"that is the portfolio-level footprint for this pull."
        )
    elif total_vol is not None:
        parts.append(f"TOTAL volume in this extract is {total_vol:,}.")
    if len(reg_rows) >= 2:
        reg_rows.sort(key=lambda x: x[1], reverse=True)
        hi_l, hi_n = reg_rows[0]
        lo_l, lo_n = reg_rows[-1]
        if hi_n != lo_n:
            parts.append(
                f"Registered counts range from {lo_n:,} ({lo_l}) up to {hi_n:,} ({hi_l}) across child programs."
            )
    return " ".join(parts).strip()[:480]


def synthesize_data_driven_insight(title: str, points: list[str]) -> str:
    """
    Build a 1-2 sentence insight that states what the data implies (contrast, concentration,
    magnitude). Uses numbers from bullets — no generic consulting framing.
    """
    pts = [_clean_text(p).strip() for p in (points or []) if _clean_text(p).strip()]
    if not pts:
        return ""

    tl = (title or "").lower()
    blob = " ".join(pts).lower()

    if any(k in tl for k in ("executive", "summary")):
        ex = _executive_summary_insight(pts)
        if ex:
            return ex

    # Program / YoY / comparison slides with Genie key=value rows (not dollar-first scoring)
    if any(re.search(r"(volume|reach|registered)\s*=", p, re.I) for p in pts) and (
        "yoy" in tl or "cross-event" in tl or "cross event" in tl
        or ("comparison" in tl and "segment" not in tl)
    ):
        kv = _kv_program_comparison_insight(pts)
        if kv:
            return kv

    # Financial / ROI — program rows with pipeline fields (Genie key=value style)
    if any(k in tl for k in ("cost", "roi", "financial")):
        rows: list[tuple[str, float]] = []
        for p in pts:
            lab = _segment_label_from_line(p)
            qpl = _qualified_pipeline_from_line(p)
            if lab and qpl is not None:
                rows.append((lab, qpl))
        if len(rows) >= 2:
            rows.sort(key=lambda x: x[1], reverse=True)
            hi_l, hi_v = rows[0]
            lo_l, lo_v = rows[-1]
            if hi_v > 0 and hi_v > lo_v * 1.05:
                ratio = (hi_v / lo_v) if lo_v and lo_v > 0.01 else None
                spread = f" ({ratio:.1f}× higher than the lowest)" if ratio and ratio < 1e6 else ""
                return (
                    f"Qualified pipeline peaks at {hi_l} ({_fmt_currency_us(hi_v)}) and falls to {lo_l} "
                    f"({_fmt_currency_us(lo_v)}){spread} — most closed-won potential in this view sits with the top program, not evenly across geographies."
                )
            mid = rows[len(rows) // 2]
            return (
                f"Mid-ranked row is {mid[0]} at {_fmt_currency_us(mid[1])} qualified pipeline — "
                f"spread between programs stays within a narrow band on this extract."
            )

    # Registration / attendance — headline rate + scale
    if "registration" in tl or "attendance" in tl:
        reg_m = re.search(r"registered[^0-9]{0,24}([\d,]+)", blob)
        att_m = re.search(r"attend(?:ed|ees)?[^0-9]{0,24}([\d,]+)", blob)
        pct_vals = [float(x) for x in re.findall(r"([\d.]+)\s*%", " ".join(pts))]
        try:
            reg = float(reg_m.group(1).replace(",", "")) if reg_m else None
            att = float(att_m.group(1).replace(",", "")) if att_m else None
        except Exception:
            reg = att = None
        rate = pct_vals[0] if pct_vals else ((att / reg * 100) if reg and att and reg > 0 else None)
        if reg and att and rate is not None:
            return (
                f"Show-up is {rate:.2f}% ({int(att):,} attended of {int(reg):,} registered) — "
                f"the majority of sign-ups did not convert to live participation."
            )

    # Funnel — spread of stage conversion percentages
    if "funnel" in tl or "pipeline funnel" in tl:
        pcts = []
        for p in pts:
            pcts.extend([float(x) for x in re.findall(r"([\d.]+)\s*%", p)])
        if len(pcts) >= 2:
            hi, lo = max(pcts), min(pcts)
            if hash(tl) % 2 == 0:
                return f"Listed conversions bottom near {lo:.2f}% and top out near {hi:.2f}%."
            return f"Stage metrics on this slide range from {lo:.2f}% to {hi:.2f}%."

    # Segment / account — first split by dimension if present
    if "segment" in tl or "account" in tl:
        rows = []
        for p in pts:
            lab = _segment_label_from_line(p) or ""
            nums = _money_amounts_in_text(p)
            if lab and nums:
                rows.append((lab, max(nums)))
        if len(rows) >= 2:
            rows.sort(key=lambda x: x[1], reverse=True)
            return (
                f"{rows[0][0]} shows {_fmt_currency_us(rows[0][1])} vs {_fmt_currency_us(rows[-1][1])} for {rows[-1][0]} "
                f"on the reported segment basis."
            )

    # YoY / comparison — dollar span only when meaningful (skip all-zero noise)
    if "yoy" in tl or "comparison" in tl or "cross-event" in tl:
        nums = [n for n in _money_amounts_in_text(blob) if n > 0]
        if len(nums) >= 2:
            a, b = max(nums), min(nums)
            return (
                f"Non-zero dollar amounts in this comparison run from {_fmt_currency_us(b)} to {_fmt_currency_us(a)}."
            )

    # Executive — largest numeric signals in first bullets (ignore $0-only rows)
    scored: list[tuple[float, str]] = []
    for p in pts[:6]:
        nums = _money_amounts_in_text(p)
        if nums and max(nums) > 0:
            scored.append((max(nums), p))
    if not scored:
        for p in pts:
            vm = re.search(r"volume=(\d+)", p, re.I)
            if vm:
                scored.append((float(vm.group(1)), p))
                break
    if len(scored) >= 1:
        scored.sort(key=lambda x: x[0], reverse=True)
        led = _metric_led_sentence(scored[0][1])
        if led and not re.search(r":\s*\$0\.00", led, re.I):
            return led

    return _compose_insight_from_bullets(title, pts)


def _is_instructional(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return True
    bad_prefixes = (
        "show ", "compare ", "summarize ", "list ", "identify ", "provide ",
        "recommend ", "break down ", "explain ", "calculate ", "define ",
    )
    if t.endswith("?"):
        return True
    return any(t.startswith(p) for p in bad_prefixes)


def _is_valid_point(text: str) -> bool:
    if not text or len(text.strip()) < 12:
        return False
    if len(text) > 260:
        return False
    tl = text.lower()
    if (
        "[data not available]" in tl
        or "data not available" in tl
        or "cannot be calculated" in tl
        or "cannot be determined" in tl
        or "not available" in tl
        or ("missing" in tl and "data" in tl)
    ):
        return False
    if _is_instructional(text):
        return False
    return True


def _rebalance_risks_actions(points: list[str]) -> list[str]:
    """Ensure final slide contains both risk and action statements."""
    if not points:
        return points

    risk_kw = (
        "risk", "gap", "issue", "inconsisten", "mismatch", "drop",
        "decline", "missing", "unknown", "error", "underperform",
    )
    action_kw = (
        "action", "recommend", "next step", "implement", "investigate",
        "standardize", "develop", "analyze", "improve", "fix", "prioritize",
    )

    clean = [_clean_text(p) for p in points if _clean_text(p)]
    risks = [p for p in clean if any(k in p.lower() for k in risk_kw)]
    actions = [p for p in clean if any(k in p.lower() for k in action_kw)]
    neutral = [p for p in clean if p not in risks and p not in actions]

    # If risks are missing, derive up to two from non-risk statements.
    if not risks:
        for src in (neutral + actions)[:2]:
            s = src.strip()
            if s.lower().startswith("action:"):
                s = s.split(":", 1)[1].strip()
            risks.append(f"Risk: {s}")

    # If actions are missing, derive up to three from available statements.
    if not actions:
        for src in (neutral + risks)[:3]:
            s = src.strip()
            if s.lower().startswith("risk:"):
                s = s.split(":", 1)[1].strip()
            actions.append(f"Action: {s}")

    ordered = []
    for p in risks[:2]:
        ordered.append(p if p.lower().startswith("risk:") else f"Risk: {p}")
    for p in actions[:4]:
        ordered.append(p if p.lower().startswith("action:") else f"Action: {p}")

    return _dedupe_points(ordered)[:6]


def _derive_insight(title: str, points: list[str]) -> str:
    """Build a fallback insight from bullet evidence: trends and contrasts, no template openers."""
    clean_points = []
    for p in points:
        if not p:
            continue
        pl = p.lower()
        if (
            "[data not available]" in pl
            or "data not available" in pl
            or "cannot be calculated" in pl
            or "cannot be determined" in pl
            or "not available" in pl
            or ("missing" in pl and "data" in pl)
        ):
            continue
        clean_points.append(p.strip())
    if not clean_points:
        return ""

    dd = synthesize_data_driven_insight(title, clean_points)
    if dd and len(dd.strip()) >= 40:
        return _sanitize_key_insight(dd.strip())

    def _score(p: str) -> tuple:
        pl = p.lower()
        s = 0
        if re.search(r"[%$]", p):
            s += 4
        if re.search(r"\d", p):
            s += 2
        for w in (
            "versus",
            " vs ",
            "compared",
            "higher",
            "lower",
            "top ",
            "bottom",
            "growth",
            "decline",
            "concentrat",
            "spread",
            "gap ",
            "risk ",
            "roi",
            "conversion",
            "funnel",
            "stage",
        ):
            if w in pl:
                s += 1
        return (-s, -len(p))

    ordered = sorted(clean_points, key=_score)
    first = ordered[0]
    second = None
    f_clip = _clip_first_clause(first)
    for p in ordered[1:]:
        if _clip_first_clause(p).lower() != f_clip.lower():
            second = p
            break
    if second is None and len(ordered) > 1:
        second = ordered[1]

    if second:
        insight = _join_analytic_clauses(first, second)
    else:
        insight = _clip_first_clause(first)
        if insight and not insight.endswith("."):
            insight += "."

    insight = _sanitize_key_insight(insight)

    norm_insight = re.sub(r"\s+", " ", insight.lower()).strip()
    norm_points = {re.sub(r"\s+", " ", p.lower()).strip() for p in clean_points}
    if norm_insight in norm_points:
        if len(ordered) >= 3:
            insight = _sanitize_key_insight(_join_analytic_clauses(ordered[1], ordered[2]))
        elif len(ordered) >= 2:
            insight = _sanitize_key_insight(_join_analytic_clauses(ordered[0], ordered[-1]))
        else:
            insight = _compose_insight_from_bullets(title, clean_points)
            insight = _sanitize_key_insight(insight)

    if _insight_redundant_with_points(insight, clean_points):
        dd2 = synthesize_data_driven_insight(title, clean_points)
        if dd2 and len(dd2.strip()) >= 36:
            insight = _sanitize_key_insight(dd2.strip())
        else:
            insight = _sanitize_key_insight(_bridge_insight_for_title(title))

    return insight


def _extract_table(content: str) -> Optional[list]:
    lines = content.split("\n")
    table_lines = []
    in_table = False

    for line in lines:
        if "|" in line:
            in_table = True
            table_lines.append(line.strip())
        elif in_table and line.strip() == "":
            break

    if len(table_lines) < 3:
        return None

    headers_raw = [h.strip() for h in table_lines[0].split("|") if h.strip()]
    rows = []
    for row_line in table_lines[2:7]:
        cells = [c.strip() for c in row_line.split("|") if c.strip()]
        if len(cells) == len(headers_raw):
            rows.append(dict(zip(headers_raw, cells)))

    return rows if rows else None


def _create_fallback_outline(report_text: str) -> list[SlideOutline]:
    lines = [l for l in report_text.split("\n") if l.strip()]
    chunk_size = max(1, len(lines) // 7)

    slides = []
    for i, title in enumerate(TEMPLATE_TITLES):
        start = i * chunk_size
        chunk = lines[start : start + chunk_size]
        bullets = _extract_points_from_content("\n".join(chunk), max_points=8)
        if not bullets:
            bullets = TEMPLATE_DEFAULT_POINTS[title][:3]
        slides.append(
            SlideOutline(
                id=f"slide-{i + 1}",
                number=i + 1,
                title=title,
                points=bullets[:8],
                insight="",
            )
        )
    return slides


def _ensure_seven_slides(slides: list[SlideOutline], report_text: str) -> list[SlideOutline]:
    """Normalize to exactly seven slides with minimum content guarantees."""
    pooled_points = _seed_points_from_report(report_text)
    out = list(slides[:7])

    while len(out) < 7:
        idx = len(out)
        out.append(
            SlideOutline(
                id=f"slide-{idx + 1}",
                number=idx + 1,
                title=TEMPLATE_TITLES[idx],
                subtitle="",
                points=[],
                insight="",
                table_data=None,
            )
        )

    normalized: list[SlideOutline] = []
    for i, s in enumerate(out):
        title = TEMPLATE_TITLES[i]
        base_points = _dedupe_points((s.points or []))[:6]

        # 1) Use pooled evidence from full report text.
        if len(base_points) < 3:
            start = i * 6
            extra = pooled_points[start : start + 6]
            base_points.extend(extra)
            base_points = _dedupe_points([p for p in base_points if _is_valid_point(p)])

        # 2) Hard guarantee: if still sparse, backfill with title-aware defaults.
        if len(base_points) < 3:
            for p in TEMPLATE_DEFAULT_POINTS.get(title, []):
                if _is_valid_point(p):
                    base_points.append(p)
                if len(_dedupe_points(base_points)) >= 3:
                    break
            base_points = _dedupe_points(base_points)

        # 3) Final guarantee: always output at least 3 points, max 6.
        if len(base_points) < 3:
            base_points = _dedupe_points(
                base_points + TEMPLATE_DEFAULT_POINTS.get(title, [])[:3]
            )
        base_points = base_points[:6]

        if title == "Cross-Event Comparison":
            # Keep old balancing logic out of notebook-aligned slide set.
            pass

        insight = _sanitize_key_insight((s.insight or "").strip())
        norm_insight = re.sub(r"\s+", " ", insight.lower()).strip() if insight else ""
        point_norms = {re.sub(r"\s+", " ", p.lower()).strip() for p in base_points}
        needs_data_insight = (
            (not insight)
            or _is_instructional(insight)
            or (norm_insight in point_norms)
            or is_generic_playbook_insight(insight)
            or _insight_is_metric_echo(insight, base_points)
            or _insight_is_trivial_fragment(insight)
        )
        if needs_data_insight:
            insight = _derive_insight(title, base_points)
            if (not insight) or is_generic_playbook_insight(insight):
                dd = synthesize_data_driven_insight(title, base_points)
                if dd:
                    insight = _sanitize_key_insight(dd.strip())
        elif _insight_redundant_with_points(insight, base_points):
            dd = synthesize_data_driven_insight(title, base_points)
            if dd and len(dd.strip()) >= 36:
                insight = _sanitize_key_insight(dd.strip())
            else:
                insight = _sanitize_key_insight(_bridge_insight_for_title(title))

        normalized.append(
            SlideOutline(
                id=f"slide-{i + 1}",
                number=i + 1,
                title=title,
                subtitle=s.subtitle or "",
                points=base_points,
                insight=insight,
                table_data=s.table_data,
            )
        )
    return normalized

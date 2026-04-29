import re
from typing import Optional
from models.schemas import SlideOutline, ReportOutline

TEMPLATE_TITLES = [
    "Executive Summary",
    "Pipeline and Revenue Performance",
    "Funnel and Conversion Health",
    "Audience and Segment Performance",
    "Platform and Data Quality",
    "Financial Efficiency and ROI",
    "Risks, Actions, and Next Steps",
]

# Analytic one-liners for when parsed/derived insights merely echo bullets (must not repeat bullet wording).
BRIDGE_INSIGHTS_BY_TITLE = {
    "Executive Summary": (
        "Tradeoffs across engagement, funnel, and efficiency show where leadership attention "
        "will move outcomes fastest versus where the program already clears the bar."
    ),
    "Pipeline and Revenue Performance": (
        "Value and qualification levels are unlikely to be uniform; focus account planning "
        "on the concentration pattern rather than average pipeline figures alone."
    ),
    "Funnel and Conversion Health": (
        "The useful signal is where drop-offs cluster between stages, not a single headline "
        "conversion rate; interventions should target the widest stage-to-stage gap first."
    ),
    "Audience and Segment Performance": (
        "When segments diverge, replication budgets should follow the pockets that already "
        "convert while diagnosing structural gaps in laggards."
    ),
    "Platform and Data Quality": (
        "Reporting confidence depends on consistent definitions and joins; treat anomalies as "
        "process signals to fix upstream before scaling decisions on marginal metrics."
    ),
    "Financial Efficiency and ROI": (
        "Efficiency is meaningful only against yield: compare spend to pipeline quality and "
        "conversion depth, not volume-for-volume, before reallocating budget."
    ),
    "Risks, Actions, and Next Steps": (
        "The tactical sequence matters: strengthen follow-up and low-converting paths first, "
        "then scale investment only where pipeline impact is already measurable."
    ),
}


TEMPLATE_DEFAULT_POINTS = {
    "Executive Summary": [
        "Current evidence indicates this event generated measurable engagement and business impact.",
        "Performance concentration is visible across a subset of observed dimensions.",
        "Available metrics suggest clear opportunities to improve conversion and efficiency.",
    ],
    "Pipeline and Revenue Performance": [
        "Available records indicate pipeline outcomes are concentrated in a subset of segments.",
        "Observed revenue signals show uneven contribution across available groups.",
        "Highest-impact contributors account for a large share of visible pipeline value.",
    ],
    "Funnel and Conversion Health": [
        "Funnel progression can be partially inferred from returned stage-level metrics.",
        "Early-stage engagement appears stronger than later-stage conversion in available data.",
        "Conversion lift is most likely to come from improving mid-to-late funnel transitions.",
    ],
    "Audience and Segment Performance": [
        "Segment-level performance varies across available categories in the response.",
        "Audience mix suggests targeted follow-up can improve outcome concentration.",
        "Top-performing segments provide a replicable pattern for upcoming events.",
    ],
    "Platform and Data Quality": [
        "Source outputs are consistent enough to support directional decision-making in this report.",
        "Data structure supports trend and segmentation analysis for key business outcomes.",
        "Further normalization can improve confidence and reporting speed in future runs.",
    ],
    "Financial Efficiency and ROI": [
        "Available financial indicators suggest positive outcome potential where pipeline is concentrated.",
        "Efficiency appears strongest in segments with higher conversion quality.",
        "ROI trends indicate budget should be prioritized toward high-yield motions.",
    ],
    "Risks, Actions, and Next Steps": [
        "Current risk areas are concentrated in lower-converting segments and weaker follow-up paths.",
        "Immediate next step is to prioritize actions with clear measurable impact on conversion and pipeline.",
        "Define measurable targets and track movement against the strongest current baseline metrics.",
    ],
}


def parse_report_to_outline(report_text: str, event_name: str) -> ReportOutline:
    """Parse markdown report into a robust 7-slide business outline."""
    slides: list[SlideOutline] = []

    slide_pattern = re.compile(
        r"##\s+Slide\s+(\d+)\s*[:\-–]\s*(.+?)(?=##\s+Slide\s+\d+|##\s+Data\s+Gaps|$)",
        re.DOTALL | re.IGNORECASE,
    )
    matches = list(slide_pattern.finditer(report_text))

    for match in matches:
        slide_num = int(match.group(1))
        title = _clean_text(match.group(2).split("\n")[0].strip())
        content = match.group(0)

        insight = ""
        insight_match = re.search(
            r"###\s+Key\s+Insight\s*\n(.*?)(?=###|##|$)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if insight_match:
            insight = _sanitize_key_insight(_clean_text(insight_match.group(1).strip()))

        sub_headers = re.findall(r"###\s+(.+?)(?=\n|$)", content, re.MULTILINE)
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
        if s.startswith("##") or s.startswith("###"):
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


def _insight_redundant_with_points(insight: str, points: list[str]) -> bool:
    """
    True if the insight restates bullets (including semicolon-joined copies of two bullets)
    or largely reuses the same words without adding analytic distance.
    """
    if not (insight or "").strip():
        return True
    if not points:
        return False

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
    if overlap / max(len(insight_words), 1) >= 0.82:
        return True

    return False


def _bridge_insight_for_title(title: str) -> str:
    return BRIDGE_INSIGHTS_BY_TITLE.get(
        title,
        "Use the metrics above to prioritize where gaps are widest; avoid averaging away segment or stage differences.",
    )


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
    if "[data not available]" in text.lower():
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
    clean_points = [p.strip() for p in points if p and "[data not available]" not in p.lower()]
    if not clean_points:
        return (
            f"Use the metrics above to anchor decisions for {title}; add evidence if concentration "
            f"or segment gaps need confirmation."
        )

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
            insight = (
                f"{_clip_first_clause(ordered[0])} "
                f"Interpretation for {title.lower()} follows from how segments or stages diverge in the bullets."
            )
            insight = _sanitize_key_insight(insight)

    if _insight_redundant_with_points(insight, clean_points):
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

        if len(base_points) < 3:
            start = i * 6
            extra = pooled_points[start : start + 6]
            base_points.extend(extra)
            base_points = _dedupe_points(base_points)

        if len(base_points) < 3:
            base_points.extend(TEMPLATE_DEFAULT_POINTS[title])
            base_points = _dedupe_points(base_points)

        if title == "Risks, Actions, and Next Steps":
            base_points = _rebalance_risks_actions(base_points)

        insight = _sanitize_key_insight((s.insight or "").strip())
        norm_insight = re.sub(r"\s+", " ", insight.lower()).strip() if insight else ""
        point_norms = {re.sub(r"\s+", " ", p.lower()).strip() for p in base_points}
        if (not insight) or _is_instructional(insight) or (norm_insight in point_norms):
            insight = _derive_insight(title, base_points)
        elif _insight_redundant_with_points(insight, base_points):
            insight = _derive_insight(title, base_points)

        normalized.append(
            SlideOutline(
                id=f"slide-{i + 1}",
                number=i + 1,
                title=title,
                subtitle=s.subtitle or "",
                points=base_points[:6],
                insight=insight,
                table_data=s.table_data,
            )
        )
    return normalized

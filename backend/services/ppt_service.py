"""
Databricks Brand PowerPoint Generator
Light theme · two-column layouts · auto-charts · per-slide progress callback
"""
import io
import os
import re
import uuid
from typing import Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from models.schemas import ReportOutline, SlideOutline
from config import settings

# ── Palette ───────────────────────────────────────────────────────────────────
C_BG      = RGBColor(0xFF, 0xFF, 0xFF)
C_HEADER  = RGBColor(0xF8, 0xFA, 0xFC)
C_SURFACE = RGBColor(0xF1, 0xF5, 0xF9)
C_CARD    = RGBColor(0xFF, 0xFF, 0xFF)
C_RED     = RGBColor(0xFF, 0x36, 0x21)
C_ORANGE  = RGBColor(0xFF, 0x7D, 0x00)
C_TEAL    = RGBColor(0x00, 0x99, 0xC4)
C_GREEN   = RGBColor(0x00, 0xC4, 0x72)
C_WHITE   = RGBColor(0x11, 0x18, 0x27)
C_LGRAY   = RGBColor(0x33, 0x40, 0x52)
C_DGRAY   = RGBColor(0xD6, 0xDE, 0xE8)
C_YELL_BG = RGBColor(0xFF, 0xF7, 0xCC)
C_YELL_BR = RGBColor(0xF5, 0xC5, 0x42)
C_YELL_TX = RGBColor(0x7A, 0x4B, 0x00)

SLIDE_W  = Inches(13.33)
SLIDE_H  = Inches(7.50)
ACCENT_H = Inches(0.06)
HEADER_H = Inches(0.80)
HDR_BOT  = ACCENT_H + HEADER_H
FOOTER_H = Inches(0.40)
FOOTER_Y = SLIDE_H - FOOTER_H
CTOP     = HDR_BOT + Inches(0.14)
CBOT     = FOOTER_Y - Inches(0.08)
CAVAIL   = CBOT - CTOP
MG       = Inches(0.35)

# Two-column split
LEFT_W  = Inches(3.60)
COL_GAP = Inches(0.22)
RIGHT_X = MG + LEFT_W + COL_GAP
RIGHT_W = SLIDE_W - RIGHT_X - MG

_CHART_COLORS = ["#FF3621", "#0099C4", "#00C472", "#FF7D00", "#8B5CF6", "#F59E0B"]

# Databricks mark (transparent PNG) — same path as packaged assets for add_picture
_DATABRICKS_LOGO_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "databricks-logo.png")
)
_DATABRICKS_LOGO_BYTES: Optional[bytes] = None  # lazy cache — read once per process


def _get_databricks_logo_bytes() -> Optional[bytes]:
    """Load logo once; avoids reopening the PNG on every slide."""
    global _DATABRICKS_LOGO_BYTES
    if _DATABRICKS_LOGO_BYTES is None:
        if not os.path.isfile(_DATABRICKS_LOGO_PATH):
            _DATABRICKS_LOGO_BYTES = b""
        else:
            with open(_DATABRICKS_LOGO_PATH, "rb") as f:
                _DATABRICKS_LOGO_BYTES = f.read()
    return _DATABRICKS_LOGO_BYTES or None

# Typography: larger for readability; keep table/insight in sync
FS_SLIDE_TITLE = 28.0
FS_BULLET = 18.0
FS_BULLET_STEP = Inches(0.90)
FS_TABLE_HDR = 14.0
FS_TABLE_CELL = 13.0
FS_TABLE_CELL_NARROW = 10.5  # many columns
FS_INSIGHT_LABEL = 12.0
FS_INSIGHT_BODY = 16.0


# ── Primitives ────────────────────────────────────────────────────────────────

def _bg(slide, color: RGBColor):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _rect(slide, l, t, w, h, fill: RGBColor, border: RGBColor = None):
    shp = slide.shapes.add_shape(1, l, t, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if border:
        shp.line.color.rgb = border
        shp.line.width = Pt(0.75)
    else:
        shp.line.fill.background()
    return shp


def _txt(slide, text: str, l, t, w, h,
         size=13, bold=False, color=C_WHITE,
         align=PP_ALIGN.LEFT, wrap=True, font="Calibri", line_spacing=1.15):
    txb = slide.shapes.add_textbox(l, t, w, h)
    tf = txb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Pt(2)
    tf.margin_right = Pt(2)
    tf.margin_top = Pt(1)
    tf.margin_bottom = Pt(1)
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    p.space_after = Pt(2)
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    return txb


def _txt_emphasis(slide, text: str, l, t, w, h,
                  size=12, color=C_LGRAY, align=PP_ALIGN.LEFT,
                  wrap=True, font="Calibri", line_spacing=1.12):
    """Render text with lightweight emphasis: bold numeric tokens, italic data-gap notes."""
    txb = slide.shapes.add_textbox(l, t, w, h)
    tf = txb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Pt(2)
    tf.margin_right = Pt(2)
    tf.margin_top = Pt(1)
    tf.margin_bottom = Pt(1)
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    p.space_after = Pt(2)

    # Keep long analytical statements intact whenever possible.
    clean_text = _fit_text(text, 520)
    low = clean_text.lower().strip()
    if low.startswith("[data not available]") or "not available" in low:
        r = p.add_run()
        r.text = clean_text
        r.font.size = Pt(size)
        r.font.bold = False
        r.font.italic = True
        r.font.color.rgb = color
        r.font.name = font
        return txb

    # Bold metric-like tokens.
    token_re = re.compile(r"(\$?\d[\d,]*(?:\.\d+)?%?|[+-]?\d+(?:\.\d+)?x)")
    parts = token_re.split(clean_text)
    for part in parts:
        if not part:
            continue
        run = p.add_run()
        run.text = part
        run.font.size = Pt(size)
        run.font.bold = bool(token_re.fullmatch(part))
        run.font.italic = False
        run.font.color.rgb = color
        run.font.name = font
    return txb


def _pic(slide, img_bytes: bytes, l, t, w, h):
    slide.shapes.add_picture(io.BytesIO(img_bytes), l, t, w, h)


def _clean(s: str) -> str:
    if s is None:
        return ""
    text = str(s)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = text.replace("*", "")
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


def _is_money_label(label: str) -> bool:
    l = (label or "").lower()
    money_kw = ("pipeline", "revenue", "arr", "spend", "cost", "amount", "opportunity", "roi", "value")
    return any(k in l for k in money_kw)


def _parse_float(value) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except Exception:
        return None


def _fmt_num(v: float, decimals: int = 2) -> str:
    if v is None:
        return ""
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.{decimals}f}".rstrip("0").rstrip(".")


def _fmt_money(v: float, decimals: int = 2) -> str:
    if v is None:
        return ""
    # Always show cents for currency (avoids $127,371.5 after repairs).
    return f"${v:,.{decimals}f}"


# Whole USD amounts — must not be split by the numeric pass (which would match "534"
# inside "$45,534.08" and corrupt it to "$45,$534.00.08").
_WELLFORMED_USD = re.compile(
    r"\$(?:(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?)|(?:\d{4,}(?:\.\d+)?)|(?:\d{1,3}(?:\.\d+)?))"
)


def _repair_fragmented_currency(s: str) -> str:
    """
    Merge broken currency fragments from incremental formatting, e.g.
    '$98,$639.$73' -> '$98,639.73', '$73,325.$13' -> '$73,325.13'.
    """

    def repl_split_thousands(m: re.Match) -> str:
        whole = m.group(1).replace(",", "")
        frac = m.group(2)
        n = _parse_float(f"{whole}.{frac}")
        if n is None:
            return m.group(0)
        return _fmt_money(n, 2)

    def repl_pair(m: re.Match) -> str:
        whole = m.group(1) + m.group(2)
        frac = m.group(4)
        n = _parse_float(f"{whole}.{frac}")
        if n is None:
            return m.group(0)
        return _fmt_money(n, 2)

    out = re.sub(
        r"\$(\d{1,3}(?:,\d{3})+)\.\$(\d{2})\b",
        repl_split_thousands,
        s,
    )
    return re.sub(r"\$(\d{1,3}),\$(\d{1,3})\.(\$)?(\d{1,4})\b", repl_pair, out)


def _repair_inner_currency_corruption(s: str) -> str:
    """
    Undo mistaken chunking where a whole $45,534.08 became $45,$534.00.$8.00
    (inner thousands matched and reformatted). Pattern: $XX,$YYY.mm.$Z.nn
    """

    pat = re.compile(
        r"\$(\d{1,3}),\$(\d{1,3})\.(\d{2})\.\$(\d{1,2})\.(\d{2})\b"
    )

    def fix(m: re.Match) -> str:
        g1, g2, _spurious, g4, g5 = m.groups()
        if g5 != "00":
            return m.group(0)
        try:
            whole = int(g1 + g2)
        except ValueError:
            return m.group(0)
        n = whole + int(g4) / 100.0
        return _fmt_money(n, 2)

    return pat.sub(fix, s)


def _png_pixel_size(data: bytes) -> Optional[tuple[int, int]]:
    """Read width/height from PNG IHDR so logo scaling preserves aspect ratio."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    w = int.from_bytes(data[16:20], "big")
    h = int.from_bytes(data[20:24], "big")
    if w <= 0 or h <= 0:
        return None
    return (w, h)


def _format_value_for_column(col: str, raw_val) -> str:
    text = _clean(str(raw_val))
    n = _parse_float(text)
    if n is None:
        return text

    cl = (col or "").lower()
    if "rate" in cl or "percent" in cl or cl.endswith("%"):
        # If values are 0-1 style rates, convert to percentage.
        if 0 <= n <= 1:
            return f"{n * 100:,.2f}%".rstrip("0").rstrip(".")
        return f"{n:,.2f}%".rstrip("0").rstrip(".")
    if _is_money_label(cl):
        return _fmt_money(n, 2)
    return _fmt_num(n, 2)


def _format_text_numbers(text: str, title: str = "") -> str:
    """Round long decimals and add currency where context clearly indicates monetary values."""
    s = _repair_fragmented_currency(_clean(text))
    s = _repair_inner_currency_corruption(s)
    monetary_context = _is_money_label(title)

    shields: list[str] = []

    def shield_usd(m: re.Match) -> str:
        shields.append(m.group(0))
        return f"USDNUM{len(shields) - 1}Z"

    s = _WELLFORMED_USD.sub(shield_usd, s)

    num_re = re.compile(r"(?<![\w$])(-?\d[\d,]*\.\d{3,}|-?\d[\d,]*)(?![\w%])")
    out = []
    last = 0
    for m in num_re.finditer(s):
        out.append(s[last:m.start()])
        token = m.group(0)
        n = _parse_float(token)
        if n is None:
            out.append(token)
            last = m.end()
            continue
        prev = s[max(0, m.start() - 28):m.start()].lower()
        prev_has_money = any(k in prev for k in ("$", "pipeline", "revenue", "arr", "spend", "cost", "roi", "value", "opportun"))
        next_chunk = s[m.end():m.end() + 18].lower()
        next_has_percent = "%" in next_chunk
        if next_has_percent:
            out.append(_fmt_num(n, 2))
        elif prev_has_money or monetary_context:
            out.append(_fmt_money(n, 2))
        else:
            out.append(_fmt_num(n, 2))
        last = m.end()
    out.append(s[last:])
    result = "".join(out)
    for i, tok in enumerate(shields):
        result = result.replace(f"USDNUM{i}Z", tok)
    return result


def _derive_funnel_insight_points(points: list[str], title: str) -> list[str]:
    """
    Convert raw row-like bullet lines into funnel-style insights so this slide
    is not a duplicate of the pipeline table slide.
    """
    parsed = []
    for p in points:
        t = _clean(p)
        if "|" not in t:
            continue
        parts = [x.strip() for x in t.split("|") if x.strip()]
        if len(parts) < 3:
            continue
        label = parts[0]
        nums = []
        for v in parts[1:]:
            n = _parse_float(v)
            if n is not None:
                nums.append(n)
        if len(nums) >= 2:
            parsed.append((label, nums))

    if len(parsed) < 2:
        return [_format_text_numbers(p, title) for p in points[:6]]

    stage1_total = sum(row[1][0] for row in parsed if len(row[1]) > 0)
    stage2_total = sum(row[1][1] for row in parsed if len(row[1]) > 1)
    conv = (stage2_total / stage1_total * 100) if stage1_total else 0

    best = None
    worst = None
    for label, nums in parsed:
        if nums[0] <= 0:
            continue
        c = nums[1] / nums[0] * 100
        item = (label, c, nums[0], nums[1])
        if best is None or c > best[1]:
            best = item
        if worst is None or c < worst[1]:
            worst = item

    bullets = [
        f"Overall funnel progression converts {_fmt_money(stage1_total)} to {_fmt_money(stage2_total)}, at {conv:.2f}% conversion.",
    ]
    if best:
        bullets.append(
            f"Strongest conversion segment is {best[0]}: {_fmt_money(best[2])} to {_fmt_money(best[3])} ({best[1]:.2f}%)."
        )
    if worst:
        bullets.append(
            f"Weakest conversion segment is {worst[0]}: {_fmt_money(worst[2])} to {_fmt_money(worst[3])} ({worst[1]:.2f}%)."
        )
    if len(parsed) >= 3:
        sorted_rows = sorted(parsed, key=lambda x: x[1][1], reverse=True)
        top = sorted_rows[0]
        bullets.append(
            f"Top qualified contributor is {top[0]} with approximately {_fmt_money(top[1][1])} at the second funnel stage."
        )

    return [_format_text_numbers(b, title) for b in bullets[:6]]


def _fit_text(text: str, max_chars: int) -> str:
    t = _clean(text)
    if len(t) <= max_chars:
        return t
    return t[: max(0, max_chars - 1)].rstrip() + "…"


def _is_pipe_data_row(s: str) -> bool:
    t = _clean(s or "").strip()
    if t.count("|") < 2:
        return False
    if not t.lstrip().startswith("|"):
        t = "|" + t
    parts = [c.strip() for c in t.split("|") if c != ""]
    return len(parts) >= 2


def _row_cells_from_pipe_line(s: str) -> list[str]:
    t = _clean(s or "").strip()
    if not t.startswith("|"):
        t = "|" + t
    parts = [c.strip() for c in t.split("|") if c != ""]
    return parts if len(parts) >= 2 else []


def _unique_headers(cells: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i, c in enumerate(cells):
        base = (c or "").replace("_", " ")[:32].strip() or f"col_{i+1}"
        k = base
        n = 1
        while k in seen:
            n += 1
            k = f"{base[:28]}_{n}" if n > 1 else f"{base}_{n}"
        seen.add(k)
        out.append(k)
    return out


def _rows_from_points(points: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for p in points or []:
        if not _is_pipe_data_row(p):
            continue
        cells = _row_cells_from_pipe_line(p)
        if len(cells) < 2:
            continue
        rows.append(cells)
    if not rows:
        return []
    w = max(len(r) for r in rows)
    for r in rows:
        while len(r) < w:
            r.append("")
    return rows


def _first_row_looks_like_header(r0: list[str], r1: list[str]) -> bool:
    """Heuristic: first row is a header if it reads more like labels than data."""
    n0 = sum(1 for c in r0[1:] if _parse_float(c) is not None)
    n1 = sum(1 for c in r1[1:] if _parse_float(c) is not None)
    s0 = sum(len(c) for c in r0) / max(len(r0), 1)
    s1 = sum(len(c) for c in r1) / max(len(r1), 1)
    if n1 > n0 and n0 < max(1, (len(r0) - 1) // 2):
        return True
    if s0 < 18 and s1 > 24:
        return True
    return n0 < max(1, (len(r0) - 1) // 2)


def _promote_pipe_bullets_to_table(
    points: list[str],
) -> tuple[Optional[list[dict]], list[str]]:
    """
    If bullets look like pipe-separated table rows, convert to table_data and
    return remaining narrative bullets.
    """
    rows = _rows_from_points(points)
    if len(rows) < 2:
        return None, list(points)
    w = max(len(r) for r in rows)
    for r in rows:
        while len(r) < w:
            r.append("")

    r0, r1 = rows[0], rows[1]
    if _first_row_looks_like_header(r0, r1):
        headers = _unique_headers(r0)
        data = rows[1:]
    else:
        headers = _unique_headers(
            (["Segment"] if w else []) + [f"M{i}" for i in range(1, w)]
        )[:w]
        data = rows
    if not data:
        return None, list(points)
    out = [dict(zip(headers, row)) for row in data]
    remaining = [p for p in (points or []) if not _is_pipe_data_row(p)]
    return out, remaining


def _decorate_canvas(slide):
    """No background ornaments in clean template."""
    return


# ── Header / footer ───────────────────────────────────────────────────────────

def _header(slide, title: str, num: int, total: int):
    _rect(slide, 0, 0, SLIDE_W, ACCENT_H, C_RED)
    _rect(slide, 0, ACCENT_H, SLIDE_W, HEADER_H, C_HEADER)
    _rect(slide, 0, HDR_BOT - Inches(0.012), SLIDE_W, Inches(0.012), C_DGRAY)
    logo_slot = Inches(1.08)
    _txt(slide, title,
         MG, ACCENT_H + Inches(0.1),
         SLIDE_W - MG - logo_slot - Inches(0.14), HEADER_H - Inches(0.12),
         size=FS_SLIDE_TITLE, bold=True, color=C_WHITE)
    logo_bytes = _get_databricks_logo_bytes()
    if logo_bytes:
        dims = _png_pixel_size(logo_bytes)
        max_w = logo_slot - Inches(0.06)
        max_h = HEADER_H - Inches(0.14)
        max_w_in = Emu(max_w).inches
        max_h_in = Emu(max_h).inches
        if dims:
            w_px, h_px = dims
            aspect = w_px / float(h_px)
            # Fit inside max box; preserve aspect ratio (no horizontal stretch).
            lh_f = max_h_in
            lw_f = lh_f * aspect
            if lw_f > max_w_in:
                lw_f = max_w_in
                lh_f = lw_f / aspect
            lw, lh = Inches(lw_f), Inches(lh_f)
        else:
            lw, lh = Inches(0.75), Inches(0.62)
        lx = SLIDE_W - MG - lw
        ly = ACCENT_H + (HEADER_H - lh) / 2
        slide.shapes.add_picture(io.BytesIO(logo_bytes), lx, ly, lw, lh)


def _footer(slide, event_name: str):
    # Keep footer minimal and uncluttered.
    _rect(slide, 0, FOOTER_Y, SLIDE_W, Inches(0.010), C_DGRAY)


# ── Content helpers ───────────────────────────────────────────────────────────

def _bullets(slide, points, l, t, w, max_h, fs: float = FS_BULLET):
    y = t
    step = FS_BULLET_STEP
    for pt in points:
        if y + step > t + max_h + Inches(0.02):
            break
        text = _fit_text(pt, 520)
        if not text:
            continue
        _rect(slide, l, y + Inches(0.16), Inches(0.07), Inches(0.07), C_RED)
        _txt_emphasis(
            slide, text, l + Inches(0.20), y, w - Inches(0.24), step,
            size=max(FS_BULLET, float(fs)), color=C_LGRAY, wrap=True, line_spacing=1.22
        )
        y += step
    return y


def _insight_wrapped_line_count(text: str, inner_width_in: float, pt_size: float = FS_INSIGHT_BODY) -> int:
    """Approximate wrapped line count for KEY INSIGHT body (word wrap; long tokens split)."""
    t = (text or "").replace("\n", " ").strip()
    if not t:
        return 1
    char_w = (pt_size / 72.0) * 0.52
    cpl = max(16, int(inner_width_in / max(char_w, 0.01)))
    words: list[str] = []
    for word in t.split():
        if len(word) <= cpl:
            words.append(word)
        else:
            for i in range(0, len(word), cpl):
                words.append(word[i : i + cpl])
    lines = 1
    line_len = 0
    for word in words:
        wlen = len(word)
        add = wlen + (1 if line_len > 0 else 0)
        if line_len + add <= cpl:
            line_len += add
        else:
            lines += 1
            line_len = wlen
    return max(1, lines)


def _insight_pick_body_font(st: str, inner_w_in: float, max_body_in: float) -> tuple[float, int, float]:
    """
    Choose body pt size so full text fits vertically (layout only — never truncate).
    Returns (font_pt, line_count, line_height_inches).
    """
    fs = FS_INSIGHT_BODY
    min_fs = 3.5
    while fs >= min_fs:
        line_h_in = (fs / 72.0) * 1.28
        nlines = _insight_wrapped_line_count(st, inner_w_in, fs)
        need = nlines * line_h_in
        if need <= max_body_in + 0.03:
            return fs, nlines, line_h_in
        fs -= 0.5
    line_h_in = (min_fs / 72.0) * 1.28
    nlines = _insight_wrapped_line_count(st, inner_w_in, min_fs)
    return min_fs, nlines, line_h_in


def _insight(
    slide,
    text: str,
    l, t, w,
    title: str = "",
    bottom_limit=None,
) -> None:
    """Key insight: box sized to full text; shrink body font if needed so nothing is clipped."""
    st = _format_text_numbers(_clean(text), title)
    if not st:
        return
    bl = bottom_limit if bottom_limit is not None else (FOOTER_Y - Inches(0.1))
    max_h = bl - t - Inches(0.06)
    if max_h < Inches(0.45):
        return

    fix_top = Inches(0.55)
    pad_bottom = Inches(0.08)
    inner_w_in = max(2.0, Emu(w).inches - 0.48)

    max_total_in = Emu(max_h).inches
    max_body_in = max(0.18, max_total_in - Emu(fix_top + pad_bottom).inches)

    body_fs, nlines, line_h_in = _insight_pick_body_font(st, inner_w_in, max_body_in)
    body_content_in = nlines * line_h_in
    h = fix_top + Inches(body_content_in + 0.06) + pad_bottom
    h = min(max(h, Inches(1.05)), max_h)

    _rect(slide, l, t, w, h, C_YELL_BG, border=C_YELL_BR)
    _rect(slide, l, t, Inches(0.08), h, C_YELL_BR)
    _txt(
        slide, "KEY INSIGHT",
        l + Inches(0.18), t + Inches(0.10), w - Inches(0.28), Inches(0.32),
        size=FS_INSIGHT_LABEL, bold=True, color=C_YELL_TX
    )
    _txt_emphasis(
        slide, st,
        l + Inches(0.20), t + Inches(0.44), w - Inches(0.32), h - Inches(0.55),
        size=body_fs, color=C_WHITE, wrap=True, line_spacing=1.22
    )


def _left_panel(slide, big_val: str, label: str, sub: str = "",
                accent: RGBColor = C_RED):
    _rect(slide, MG, CTOP, LEFT_W, CAVAIL, C_CARD, border=C_DGRAY)
    _rect(slide, MG, CTOP, Inches(0.10), CAVAIL, accent)
    _txt(slide, big_val,
         MG + Inches(0.22), CTOP + Inches(0.28), LEFT_W - Inches(0.32), Inches(1.6),
         size=34, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER, wrap=False)
    _txt(slide, label.upper(),
         MG + Inches(0.18), CTOP + Inches(1.88), LEFT_W - Inches(0.28), Inches(0.38),
         size=10.5, bold=True, color=accent, align=PP_ALIGN.CENTER)
    if sub:
        _txt(slide, _fit_text(sub, 120),
             MG + Inches(0.18), CTOP + Inches(2.3), LEFT_W - Inches(0.28), Inches(1.5),
             size=11, color=C_LGRAY, align=PP_ALIGN.CENTER, wrap=True, line_spacing=1.1)
    # Decorative mini bars to avoid empty-feel left panel
    bar_base_y = CTOP + CAVAIL - Inches(0.95)
    widths = [0.72, 0.52, 0.84, 0.63]
    for i, w_frac in enumerate(widths):
        _rect(
            slide,
            MG + Inches(0.32),
            bar_base_y + Inches(0.16) * i,
            (LEFT_W - Inches(0.64)) * w_frac,
            Inches(0.08),
            RGBColor(0xD6, 0xE6, 0xFA) if i % 2 == 0 else RGBColor(0xF7, 0xDD, 0xD7),
        )


def _chart_panel(slide, img_bytes: bytes, accent: RGBColor = C_TEAL):
    _rect(slide, MG, CTOP, LEFT_W, CAVAIL, C_CARD, border=C_DGRAY)
    _rect(slide, MG, CTOP, Inches(0.10), CAVAIL, accent)
    if img_bytes:
        _pic(slide, img_bytes,
             MG + Inches(0.16), CTOP + Inches(0.18),
             LEFT_W - Inches(0.26), CAVAIL - Inches(0.36))


# ── Chart generators ──────────────────────────────────────────────────────────

def _make_bar(labels, values) -> bytes:
    n = len(labels)
    fig_h = max(2.2, min(5.0, n * 0.55))
    fig, ax = plt.subplots(figsize=(LEFT_W.inches - 0.3, fig_h))
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    colors = [_CHART_COLORS[i % len(_CHART_COLORS)] for i in range(n)]
    ax.barh(range(n), values, color=colors, height=0.6, edgecolor="none")
    mv = max(values) if values else 1
    for i, (v, lbl) in enumerate(zip(values, labels)):
        ax.text(-mv * 0.03, i, lbl, va="center", ha="right", color="#4B5563", fontsize=8.5)
        fmt = f"{int(v):,}" if v == int(v) else f"{v:.1f}"
        ax.text(v + mv * 0.03, i, fmt, va="center", ha="left",
                color="#111827", fontsize=8.5, fontweight="bold")
    ax.set_xlim(-mv * 0.42, mv * 1.35)
    ax.set_ylim(-0.5, n - 0.5)
    ax.invert_yaxis()
    ax.axis("off")
    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _make_funnel(stages, values) -> bytes:
    n = len(stages)
    fig, ax = plt.subplots(figsize=(5.5, 3.8))
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    max_v = values[0] if values else 1
    h = 1.0 / n
    colors = _CHART_COLORS[:n]
    for i in range(n):
        w_top = values[i - 1] / max_v if i > 0 else 1.0
        w_bot = values[i] / max_v
        y = 1.0 - (i + 1) * h
        xs = [(1 - w_top) / 2, (1 + w_top) / 2, (1 + w_bot) / 2, (1 - w_bot) / 2]
        ys = [y + h, y + h, y, y]
        ax.fill(xs, ys, color=colors[i], alpha=0.9)
        pct = f"({values[i] / max_v * 100:.0f}%)" if i > 0 else "(100%)"
        ax.text(0.5, y + h / 2, f"{stages[i]}  {int(values[i]):,}  {pct}",
                ha="center", va="center", color="#111827", fontsize=9, fontweight="bold")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    plt.tight_layout(pad=0.2)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _extract_pairs(points):
    out = []
    for pt in points:
        m = re.search(r"(.+?)[:\–\—]\s*\*{0,2}([0-9][0-9,]*(?:\.[0-9]+)?)", pt)
        if m:
            lbl = _clean(m.group(1))[:30].strip()
            try:
                val = float(m.group(2).replace(",", ""))
                if val > 0:
                    out.append((lbl, val))
            except ValueError:
                pass
    return out[:8]


# ── Slide type detection ──────────────────────────────────────────────────────

def _stype(title: str, has_table: bool) -> str:
    t = title.lower()
    if any(w in t for w in ("exec", "summary", "overview", "snapshot", "highlight")):
        return "exec"
    if has_table:
        return "table"
    if any(w in t for w in ("funnel", "stage", "progression", "conversion")):
        return "funnel"
    if any(w in t for w in ("cost", "roi", "spend", "financial", "budget", "efficien")):
        return "financial"
    if any(w in t for w in ("segment", "region", "geographic", "audience", "breakdown",
                             "account", "tier", "top performer", "bottom")):
        return "segment"
    if any(w in t for w in ("trend", "yoy", "year", "compar", "period", "quarter")):
        return "trend"
    return "standard"


# ── Slide builders ────────────────────────────────────────────────────────────

def _exec_slide(slide, data: SlideOutline, total: int, event_name: str):
    _header(slide, data.title, data.number, total)
    _footer(slide, event_name)

    points = [_format_text_numbers(_clean(p), data.title) for p in data.points[:6]]
    bullet_y = CTOP + Inches(0.18)
    ins_reserve = Inches(1.5) if data.insight else 0
    ins_top = CBOT - ins_reserve
    avail = max(0, ins_top - bullet_y - Inches(0.12))
    if points:
        # Same single-column bullet rhythm as other slides — avoids two-column overlap.
        _bullets(slide, points, MG, bullet_y, SLIDE_W - 2 * MG, avail)
    if data.insight:
        _insight(
            slide, data.insight, MG, ins_top, SLIDE_W - 2 * MG,
            title=data.title, bottom_limit=CBOT,
        )


def _two_col_slide(slide, data: SlideOutline, total: int, event_name: str,
                   accent=None, chart_img: bytes = None):
    if accent is None:
        accent = C_RED
    _header(slide, data.title, data.number, total)
    _footer(slide, event_name)

    ins_reserve = Inches(1.5) if data.insight else 0
    ins_top = CBOT - ins_reserve
    clean_points = [_format_text_numbers(_clean(p), data.title) for p in data.points[:6]]
    avail = max(0, ins_top - CTOP - Inches(0.08))
    # Render full-width text layout (no left-side chart/panel formatting).
    _bullets(slide, clean_points, MG, CTOP, SLIDE_W - 2 * MG, avail)
    if data.insight:
        _insight(
            slide, data.insight, MG, ins_top, SLIDE_W - 2 * MG,
            title=data.title, bottom_limit=CBOT,
        )


def _funnel_slide(slide, data: SlideOutline, total: int, event_name: str):
    # Show conversion-oriented insights so this slide is not a duplicate of raw pipeline rows.
    transformed = SlideOutline(
        id=data.id,
        number=data.number,
        title=data.title,
        subtitle=data.subtitle,
        points=_derive_funnel_insight_points(data.points or [], data.title),
        insight=data.insight,
        table_data=None,
    )
    _two_col_slide(slide, transformed, total, event_name, C_TEAL, chart_img=None)


def _table_slide(slide, data: SlideOutline, total: int, event_name: str):
    _header(slide, data.title, data.number, total)
    _footer(slide, event_name)
    if not data.table_data:
        _two_col_slide(slide, data, total, event_name)
        return

    rows_all = list(data.table_data)
    cols = list(rows_all[0].keys())
    nc = len(cols)
    has_ins = bool((data.insight or "").strip())
    narrative = [
        _format_text_numbers(_clean(p), data.title)
        for p in (data.points or []) if _clean(p)
    ][:3]

    def _em(x):
        return float(x) if not hasattr(x, "inches") else x.inches

    # Wide tables: one row of 20+ columns makes each cell too narrow; text stacks
    # vertically and overflows onto bullets below. Split into stacked horizontal bands
    # (same data, wider cells). Content (values) unchanged.
    usable_w_in = _em(SLIDE_W - 2 * MG)
    min_cell_in = 0.85
    cols_per_band = max(4, min(8, int(usable_w_in / min_cell_in)))
    if cols_per_band < 1:
        cols_per_band = 4
    col_groups = [cols[i : i + cols_per_band] for i in range(0, nc, cols_per_band)]
    num_bands = len(col_groups)

    fs_h = FS_TABLE_HDR
    fs_c = FS_TABLE_CELL_NARROW if nc > 5 else FS_TABLE_CELL
    if num_bands >= 3:
        fs_h = max(9.0, fs_h - 1.5)
        fs_c = max(7.5, fs_c - 1.5)
    if num_bands >= 5:
        fs_h = max(9.0, fs_h - 1.0)
        fs_c = max(7.0, fs_c - 1.0)

    rh = Inches(0.52) + Inches(0.012) * (fs_c - 10)
    band_gap = Inches(0.14)

    ins_max = Inches(1.55) if has_ins else Inches(0.1)
    bullet_h = (Inches(0.32) * len(narrative)) if narrative else 0
    y0 = CTOP + Inches(0.10)
    y_max = CBOT - ins_max - bullet_h - (Inches(0.12) if narrative else 0) - Inches(0.06)
    if y_max < y0 + rh * 2:
        y_max = CBOT - ins_max - Inches(0.06)

    budget_in = max(0.0, _em(y_max) - _em(y0))
    gap_in = _em(band_gap)

    def _stack_height(rows_n: int, row_h_in: float, nb: int) -> float:
        """Vertical inches for stacked bands: each band = header + data rows + gap."""
        per_band = row_h_in * (1 + rows_n)
        return nb * per_band + max(0, nb - 1) * gap_in

    max_data_rows = min(7, len(rows_all))
    rhi = max(0.01, _em(rh))
    while True:
        if _stack_height(max_data_rows, rhi, num_bands) <= budget_in + 0.08:
            break
        if max_data_rows > 1:
            max_data_rows -= 1
            continue
        if fs_c > 7.0 or fs_h > 9.5:
            fs_c = max(7.0, fs_c - 0.5)
            fs_h = max(9.0, fs_h - 0.5)
            rh = Inches(0.52) + Inches(0.012) * (fs_c - 10)
            rhi = max(0.01, _em(rh))
            continue
        break

    data_rows = rows_all[:max_data_rows] if max_data_rows > 0 else []

    y = y0
    for bi, band_cols in enumerate(col_groups):
        band_nc = len(band_cols)
        cw = (SLIDE_W - 2 * MG) / band_nc
        for j, col in enumerate(band_cols):
            x = MG + j * cw
            _rect(slide, x, y, cw - Inches(0.04), rh, C_SURFACE, border=C_DGRAY)
            _txt(
                slide, _clean(str(col)).replace("_", " ").upper(),
                x + Inches(0.06), y + Inches(0.06), cw - Inches(0.12), rh - Inches(0.12),
                size=fs_h, bold=True, color=C_TEAL, wrap=True,
            )
        y += rh
        for i, row in enumerate(data_rows):
            if y + rh > y_max + Inches(0.02):
                break
            bg = C_CARD if i % 2 == 0 else C_SURFACE
            for j, col in enumerate(band_cols):
                x = MG + j * cw
                _rect(slide, x, y, cw - Inches(0.04), rh, bg, border=C_DGRAY)
                _txt(
                    slide, _format_value_for_column(str(col), row.get(col, "")),
                    x + Inches(0.06), y + Inches(0.05), cw - Inches(0.12), rh - Inches(0.10),
                    size=fs_c, color=C_LGRAY, wrap=True,
                )
            y += rh
        if bi < len(col_groups) - 1:
            y += band_gap

    y_end = y
    y_cur = y_end + Inches(0.10)
    if narrative and y_cur < CBOT - ins_max - Inches(0.1):
        _bullets(
            slide, narrative, MG, y_cur, SLIDE_W - 2 * MG,
            max(0, CBOT - ins_max - y_cur - Inches(0.08)),
        )
    if has_ins:
        _insight(
            slide, data.insight, MG, CBOT - ins_max, SLIDE_W - 2 * MG,
            title=data.title, bottom_limit=CBOT,
        )


def _build_slide(slide, data: SlideOutline, total: int, event_name: str):
    _decorate_canvas(slide)
    d = data
    promo, rem = _promote_pipe_bullets_to_table(list(data.points or []))
    if promo is not None and not data.table_data:
        d = data.model_copy(
            update={
                "table_data": promo,
                "points": rem if rem else [],
            }
        )
    st = _stype(d.title, bool(d.table_data))
    if st == "exec":
        _exec_slide(slide, d, total, event_name)
        return
    if st == "table" or d.table_data:
        _table_slide(slide, d, total, event_name)
        return
    if st == "funnel":
        _funnel_slide(slide, d, total, event_name)
        return
    accent = {"financial": C_RED, "segment": C_TEAL, "trend": C_ORANGE}.get(st, C_RED)
    _two_col_slide(slide, d, total, event_name, accent, chart_img=None)


def _fmt_insight_for_export(data: SlideOutline) -> str:
    if not (data.insight or "").strip():
        return ""
    return _format_text_numbers(_clean(data.insight), data.title)


def slide_outline_as_in_ppt(data: SlideOutline) -> SlideOutline:
    """
    Apply the same point/table/insight transforms as _build_slide (without drawing).
    Use this so web slideshow preview matches the downloaded PPTX.
    """
    d = data
    promo, rem = _promote_pipe_bullets_to_table(list(data.points or []))
    if promo is not None and not data.table_data:
        d = data.model_copy(
            update={
                "table_data": promo,
                "points": rem if rem else [],
            }
        )
    st = _stype(d.title, bool(d.table_data))
    insight_out = _fmt_insight_for_export(d)

    if st == "exec":
        pts = [_format_text_numbers(_clean(p), d.title) for p in (d.points or [])[:6]]
        return d.model_copy(update={"points": pts, "insight": insight_out})

    if st == "table" or d.table_data:
        narrative = [
            _format_text_numbers(_clean(p), d.title)
            for p in (d.points or [])
            if _clean(p)
        ][:3]
        return d.model_copy(update={"points": narrative, "insight": insight_out})

    if st == "funnel":
        pts = _derive_funnel_insight_points(d.points or [], d.title)
        return d.model_copy(
            update={
                "points": pts,
                "table_data": None,
                "insight": insight_out,
            }
        )

    pts = [_format_text_numbers(_clean(p), d.title) for p in (d.points or [])[:6]]
    return d.model_copy(update={"points": pts, "insight": insight_out})


def outline_as_in_ppt(outline: ReportOutline) -> ReportOutline:
    """Full deck: same effective content the PowerPoint generator uses per slide."""
    slides = [slide_outline_as_in_ppt(s) for s in outline.slides]
    return ReportOutline(event_name=outline.event_name, slides=slides)


# ── Cover slide ───────────────────────────────────────────────────────────────

def _cover(prs: Presentation, event_name: str):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(slide, C_BG)
    _rect(slide, 0, Inches(0.20), SLIDE_W, Inches(0.05), C_RED)

    _txt(slide, "POST-EVENT ROI REPORT",
         Inches(0.65), Inches(1.10), Inches(8.6), Inches(0.5),
         size=15, color=C_LGRAY, font="Calibri Light")
    _txt(slide, event_name,
         Inches(0.65), Inches(1.95), Inches(12.0), Inches(1.9),
         size=52, bold=True, color=C_WHITE)
    _txt(slide, "Executive summary of event performance, conversion, pipeline, segmentation, and ROI outcomes.",
         Inches(0.65), Inches(4.15), Inches(11.9), Inches(0.8),
         size=18, color=C_LGRAY)
    _rect(slide, Inches(0.65), Inches(5.15), Inches(11.9), Inches(0.02), C_DGRAY)


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_pptx(outline: ReportOutline, on_progress=None) -> str:
    """
    Generate a branded PPTX from outline.
    on_progress(slide_num, total_slides, title) is called after each slide.
    Returns the saved filename.
    """
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    total = len(outline.slides)  # content slides (excl. cover)

    _cover(prs, outline.event_name)
    if on_progress:
        on_progress(0, total + 1, "Cover")

    for sdata in outline.slides:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _bg(slide, C_BG)
        _build_slide(slide, sdata, total, outline.event_name)
        if on_progress:
            on_progress(sdata.number, total + 1, sdata.title)

    safe = re.sub(r"[^\w\s\-]", "", outline.event_name).replace(" ", "_")[:40]
    filename = f"roi_{safe}_{uuid.uuid4().hex[:6]}.pptx"
    prs.save(os.path.join(settings.temp_dir, filename))
    return filename

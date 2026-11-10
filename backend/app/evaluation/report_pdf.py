"""把会话报告 JSON 排版为 A4 PDF。

版式与网页报告一致：封面与摘要、事件、情绪趋势与公告总分、公告评分与解析、
讨论词云、关键评论、结论与建议。使用 ReportLab 的分页控制（CondPageBreak、
KeepTogether）避免标题孤行、卡片断裂和大面积空白。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    HRFlowable,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#D6D3CD")
ACCENT = colors.HexColor("#2F6F6A")
ACCENT_SOFT = colors.HexColor("#E8F0EE")
TABLE_HEAD = colors.HexColor("#F3F2EE")
CARD_BG = colors.HexColor("#FAF9F6")
NEGATIVE = colors.HexColor("#B4543F")
NEUTRAL = colors.HexColor("#9A8B72")
POSITIVE = colors.HexColor("#177F6F")

INK_HEX = "#1F2933"
MUTED_HEX = "#6B7280"
ACCENT_HEX = "#2F6F6A"

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

SERIES = (
    ("negative", "负面", NEGATIVE),
    ("neutral", "中性", NEUTRAL),
    ("positive", "正面", POSITIVE),
)
EMOTION_LABELS = {"negative": "负面", "neutral": "中性", "positive": "正面"}
TONE_COLORS = {
    "negative": NEGATIVE,
    "neutral": NEUTRAL,
    "positive": POSITIVE,
}

_FONT_REGISTERED = False
_STYLES: dict[str, ParagraphStyle] | None = None


def _register_font(name: str, path: Path, index: int | None) -> bool:
    if not path.is_file():
        return False
    try:
        font = TTFont(name, str(path), subfontIndex=index) if index is not None else TTFont(name, str(path))
        pdfmetrics.registerFont(font)
        return True
    except Exception:  # noqa: BLE001 - 字体不可用时回退
        return False


def _register_fonts() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    regular_candidates = (
        (Path(r"C:\Windows\Fonts\msyh.ttc"), 0),
        (Path(r"C:\Windows\Fonts\simhei.ttf"), None),
        (Path(r"C:\Windows\Fonts\simsun.ttc"), 0),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
        (Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"), 0),
        (Path("/System/Library/Fonts/PingFang.ttc"), 0),
    )
    bold_candidates = (
        (Path(r"C:\Windows\Fonts\msyhbd.ttc"), 0),
        (Path(r"C:\Windows\Fonts\simhei.ttf"), None),
        (Path(r"C:\Windows\Fonts\simsun.ttc"), 0),
        (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 0),
        (Path("/System/Library/Fonts/PingFang.ttc"), 0),
    )
    regular = next(
        (path for path, index in regular_candidates if _register_font("CN", path, index)),
        None,
    )
    bold = next(
        (path for path, index in bold_candidates if _register_font("CN-Bold", path, index)),
        None,
    )
    if regular is None:
        pdfmetrics.registerFont(TTFont("CN", "Helvetica"))
    if bold is None:
        pdfmetrics.registerFont(TTFont("CN-Bold", "Helvetica-Bold"))
    pdfmetrics.registerFontFamily(
        "CN", normal="CN", bold="CN-Bold", italic="CN", boldItalic="CN-Bold"
    )
    _FONT_REGISTERED = True


def _styles() -> dict[str, ParagraphStyle]:
    global _STYLES
    if _STYLES is not None:
        return _STYLES
    _register_fonts()
    _STYLES = {
        "kicker": ParagraphStyle(
            "kicker", fontName="CN", fontSize=8, leading=11,
            textColor=ACCENT, spaceAfter=6,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", fontName="CN-Bold", fontSize=21, leading=29,
            textColor=INK, spaceAfter=4,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontName="CN", fontSize=10, leading=16,
            textColor=MUTED, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2", fontName="CN-Bold", fontSize=13, leading=18,
            textColor=INK, spaceBefore=2, spaceAfter=2, keepWithNext=1,
        ),
        "h3": ParagraphStyle(
            "h3", fontName="CN-Bold", fontSize=10, leading=15,
            textColor=INK, spaceBefore=4, spaceAfter=3, keepWithNext=1,
        ),
        "body": ParagraphStyle(
            "body", fontName="CN", fontSize=9, leading=15,
            textColor=INK, spaceAfter=4, wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "small", fontName="CN", fontSize=7.6, leading=12,
            textColor=MUTED, wordWrap="CJK",
        ),
        "note": ParagraphStyle(
            "note", fontName="CN", fontSize=7.6, leading=11.5,
            textColor=MUTED, spaceAfter=6, wordWrap="CJK",
        ),
        "meta_label": ParagraphStyle(
            "meta_label", fontName="CN", fontSize=7.6, leading=12,
            textColor=MUTED, wordWrap="CJK",
        ),
        "meta_value": ParagraphStyle(
            "meta_value", fontName="CN", fontSize=8.6, leading=13,
            textColor=INK, wordWrap="CJK",
        ),
        "card": ParagraphStyle(
            "card", fontName="CN", fontSize=8.6, leading=13,
            textColor=INK, wordWrap="CJK", alignment=0,
        ),
        "quote": ParagraphStyle(
            "quote", fontName="CN", fontSize=8.6, leading=14,
            textColor=colors.HexColor("#3F3A33"), wordWrap="CJK",
        ),
        "cell": ParagraphStyle(
            "cell", fontName="CN", fontSize=8.2, leading=13,
            textColor=INK, wordWrap="CJK",
        ),
        "cell_head": ParagraphStyle(
            "cell_head", fontName="CN-Bold", fontSize=7.6, leading=11.5,
            textColor=MUTED, wordWrap="CJK",
        ),
        "cell_num": ParagraphStyle(
            "cell_num", fontName="CN", fontSize=8.2, leading=13,
            textColor=INK, alignment=2,
        ),
        "cloud": ParagraphStyle(
            "cloud", fontName="CN", fontSize=12, leading=30,
            textColor=INK, wordWrap="CJK", alignment=1,
        ),
        "cloud_cell": ParagraphStyle(
            "cloud_cell", fontName="CN", fontSize=12, leading=18,
            textColor=INK, wordWrap="CJK", alignment=1,
        ),
    }
    return _STYLES


def _hex(color) -> str:
    return "#" + color.hexval()[2:]


def _num(value, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "—"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _pct(value) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _text(value, style: ParagraphStyle) -> Paragraph:
    payload = "" if value is None else str(value)
    return Paragraph(escape(payload).replace("\n", "<br/>"), style)


def _meta_table(rows, styles) -> Table:
    data = [
        [_text(label, styles["meta_label"]), _text(value if value not in (None, "") else "—", styles["meta_value"])]
        for label, value in rows
    ]
    table = Table(data, colWidths=[30 * mm, CONTENT_W - 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _quote_table(text_value, styles, width: float = CONTENT_W) -> Table:
    cell = _text(text_value, styles["quote"])
    table = Table([[cell]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, -1), 2.2, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _bar(score: float, width: float, tone) -> Drawing:
    height = 5.5
    drawing = Drawing(width, height)
    ratio = max(0.0, min(1.0, float(score or 0) / 100))
    drawing.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#EFEDE8"), strokeColor=None))
    if ratio:
        drawing.add(Rect(0, 0, width * ratio, height, fillColor=tone, strokeColor=None))
    return drawing


def _score_tone(score: float):
    if score >= 86:
        return POSITIVE
    if score >= 80:
        return colors.HexColor("#B98A4B")
    return NEGATIVE


def _section(number: str, title: str, note: str | None, styles) -> list:
    key = f"sec-{number}"
    heading = _SectionTitle(
        f"{number} · {title}",
        styles["h2"],
        key=key,
        level=0,
    )
    flows = [
        Spacer(1, 2),
        heading,
        HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=2, spaceAfter=4),
    ]
    if note:
        flows.append(_text(note, styles["note"]))
    return flows


class _SectionTitle(Paragraph):
    """带 PDF 书签的章节标题。"""

    def __init__(self, text, style, key, level=0):
        super().__init__(text, style)
        self.key = key
        self.level = level

    def draw(self):
        super().draw()
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.getPlainText(), self.key, self.level, 0)


class _NumberedCanvas(pdf_canvas.Canvas):
    """延迟输出，以便页脚写“第 x 页 / 共 y 页”。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        if self._pageNumber == 1:
            return
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.4)
        self.line(MARGIN_X, 13 * mm, PAGE_W - MARGIN_X, 13 * mm)
        self.setFont("CN", 7.5)
        self.setFillColor(MUTED)
        self.drawString(MARGIN_X, 9 * mm, "Simulation2 · 舆情推演报告")
        self.drawRightString(
            PAGE_W - MARGIN_X,
            9 * mm,
            f"第 {self._pageNumber} 页 / 共 {total} 页",
        )
        self.restoreState()


def _short(value, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _draw_header(canvas, doc, title: str, report_id: str) -> None:
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFont("CN", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN_X, PAGE_H - 11 * mm, _short(title, 34))
    canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 11 * mm, _short(report_id, 42))
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN_X, PAGE_H - 13.5 * mm, PAGE_W - MARGIN_X, PAGE_H - 13.5 * mm)
    canvas.restoreState()


def _summary_cards(report: dict, styles) -> Table:
    summary = report.get("summary") or {}
    simulation = report.get("simulation") or {}
    announcements = report.get("announcements") or []
    best = next(
        (
            item
            for item in announcements
            if item.get("id") == summary.get("best_announcement_id")
        ),
        None,
    )
    entry_step = ((best or {}).get("score") or {}).get("response_step")
    peak = summary.get("peak_negative_rate")
    final = summary.get("final_negative_rate")
    drop = None
    try:
        drop = float(peak) - float(final)
    except (TypeError, ValueError):
        drop = None

    items = [
        ("综合风险", summary.get("risk_level") or "—", f"负面峰值 {_pct(peak)}"),
        ("最终负面率", _pct(final), f"较峰值下降 {_pct(drop) if drop is not None else '—'}"),
        ("最佳公告", (best or {}).get("name") or "—", f"总分 {_num(summary.get('best_score'))}"),
        (
            "官方进场",
            f"第 {entry_step} 轮" if entry_step else "未进场",
            f"{simulation.get('rounds', '—')} 轮推演 · {len(announcements)} 个公告方案",
        ),
    ]
    cells = [
        Paragraph(
            f'<font size="8" color="{MUTED_HEX}">{escape(label)}</font><br/>'
            f'<font size="14" color="{INK_HEX}"><b>{escape(str(value))}</b></font><br/>'
            f'<font size="8" color="{MUTED_HEX}">{escape(sub)}</font>',
            styles["card"],
        )
        for label, value, sub in items
    ]
    table = Table(
        [[cells[0], cells[1]], [cells[2], cells[3]]],
        colWidths=[CONTENT_W / 2, CONTENT_W / 2],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
                ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _trend_chart(trend: list[dict], width: float) -> Drawing:
    height = 62 * mm
    drawing = Drawing(width, height)
    left, right = 24, width - 6
    top, bottom = height - 16, 15
    plot_w = max(right - left, 10)
    plot_h = max(top - bottom, 10)

    for tick in (0, 0.25, 0.5, 0.75, 1):
        y = bottom + plot_h * tick
        drawing.add(
            Line(left, y, right, y, strokeColor=colors.HexColor("#E7E4DE"), strokeWidth=0.4)
        )
        drawing.add(
            String(
                left - 4,
                y - 2.5,
                f"{int(tick * 100)}%",
                fontName="CN",
                fontSize=6,
                fillColor=MUTED,
                textAnchor="end",
            )
        )

    steps = len(trend)
    step_w = plot_w / max(steps - 1, 1)
    for key, _label, color in SERIES:
        points = []
        for index, item in enumerate(trend):
            x = left + index * step_w
            try:
                value = max(0.0, min(1.0, float(item.get(key, 0))))
            except (TypeError, ValueError):
                value = 0.0
            y = bottom + plot_h * value
            points.extend([x, y])
        if len(points) >= 4:
            drawing.add(
                PolyLine(points, strokeColor=color, strokeWidth=1.6, strokeLineJoin=1)
            )
        for index in range(0, len(points), 2):
            drawing.add(
                Circle(
                    points[index],
                    points[index + 1],
                    2.2,
                    fillColor=colors.white,
                    strokeColor=color,
                    strokeWidth=1.1,
                )
            )

    label_step = 1 if steps <= 8 else 2
    for index, item in enumerate(trend):
        if index % label_step:
            continue
        x = left + index * step_w
        drawing.add(
            String(
                x,
                bottom - 9,
                f"第{int(item.get('round', index + 1))}轮",
                fontName="CN",
                fontSize=6,
                fillColor=MUTED,
                textAnchor="middle",
            )
        )

    legend_x = left
    for _key, label, color in SERIES:
        drawing.add(
            Line(legend_x, height - 6, legend_x + 12, height - 6, strokeColor=color, strokeWidth=1.6)
        )
        drawing.add(
            String(legend_x + 15, height - 8.5, label, fontName="CN", fontSize=7, fillColor=MUTED)
        )
        legend_x += 48
    return drawing


def _ranking_table(announcements: list[dict], styles, width: float) -> Table:
    rows = [[
        _text("公告方案", styles["cell_head"]),
        _text("总分", styles["cell_head"]),
        _text("", styles["cell_head"]),
    ]]
    for item in announcements:
        score = item.get("score") or {}
        total = float(score.get("total") or 0)
        rows.append(
            [
                _text(item.get("name") or "—", styles["cell"]),
                _text(_num(total), styles["cell_num"]),
                _bar(total, width * 0.42, _score_tone(total)),
            ]
        )
    table = Table(rows, colWidths=[width * 0.46, width * 0.16, width * 0.38], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _score_rows(item: dict) -> list[tuple[str, float, float]]:
    score = item.get("score") or {}
    dimensions = score.get("dimensions")
    if isinstance(dimensions, list) and dimensions:
        rows = []
        for dimension in dimensions:
            value = float(dimension.get("score") or 0)
            rows.append((str(dimension.get("name") or "维度"), min(100.0, max(0.0, value / 20 * 100)), value))
        return rows
    rounds = score.get("rounds") or []
    if not rounds:
        return []

    def average(field: str) -> float:
        total = sum(float(row.get(field) or 0) for row in rounds)
        return total / len(rounds)

    comment = average("comment_score")
    attitude = average("attitude_score")
    return [
        ("评论情绪分", comment, comment),
        ("官方态度分", attitude, attitude),
    ]


def _dimension_table(item: dict, styles, width: float) -> Table | None:
    rows = _score_rows(item)
    if not rows:
        return None
    data = []
    for name, percent, score in rows:
        data.append(
            [
                _text(name, styles["cell"]),
                _bar(percent, width * 0.55, ACCENT),
                _text(_num(score, 1), styles["cell_num"]),
            ]
        )
    table = Table(data, colWidths=[width * 0.28, width * 0.56, width * 0.16])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _bullets(items, styles) -> Paragraph:
    lines = [f"· {escape(str(item))}" for item in (items or []) if str(item).strip()]
    return Paragraph("<br/>".join(lines) or "—", styles["small"])


def _strengths_risks(analysis: dict, styles) -> Table:
    left = Table(
        [[_text("优势", styles["cell_head"])], [_bullets(analysis.get("strengths"), styles)]],
        colWidths=[(CONTENT_W - 8) / 2],
    )
    right = Table(
        [[_text("风险", styles["cell_head"])], [_bullets(analysis.get("risks"), styles)]],
        colWidths=[(CONTENT_W - 8) / 2],
    )
    for table in (left, right):
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
    container = Table([[left, right]], colWidths=[(CONTENT_W - 8) / 2, (CONTENT_W - 8) / 2])
    container.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.3, RULE),
                ("LINEBELOW", (0, 0), (-1, 0), 0.3, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return container


def _announcement_flows(item: dict, index: int, styles) -> list:
    score = item.get("score") or {}
    total = float(score.get("total") or 0)
    level = score.get("level") or score.get("judgement") or ""
    published = item.get("published_at") or (
        f"第 {score.get('response_step')} 轮" if score.get("response_step") else "—"
    )
    name = item.get("name") or f"公告方案 {index}"
    header = Table(
        [
            [
                Paragraph(
                    f'<font size="8" color="{MUTED_HEX}">{escape(str(published))}</font><br/>'
                    f'<font size="12">{escape(str(name))}</font>',
                    styles["card"],
                ),
                Paragraph(
                    f'<font size="16" color="{_hex(_score_tone(total))}"><b>{escape(_num(total))}</b></font>'
                    f'<font size="8" color="{MUTED_HEX}"> / 100</font><br/>'
                    f'<font size="8" color="{MUTED_HEX}">{escape(str(level))}</font>',
                    styles["card"],
                ),
            ]
        ],
        colWidths=[CONTENT_W - 38 * mm, 38 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    flows = [
        header,
        Spacer(1, 3),
        _quote_table(item.get("official_statement") or item.get("text") or "", styles),
        Spacer(1, 4),
    ]
    dimensions = _dimension_table(item, styles, CONTENT_W - 10 * mm)
    if dimensions is not None:
        flows.append(dimensions)
    analysis = item.get("analysis") or {}
    if analysis.get("summary"):
        flows.append(Spacer(1, 3))
        flows.append(_text(analysis.get("summary"), styles["body"]))
    if analysis.get("strengths") or analysis.get("risks"):
        flows.append(Spacer(1, 2))
        flows.append(_strengths_risks(analysis, styles))
    return flows


def _word_cloud_table(words: list[dict], styles) -> Table:
    weights = []
    for word in words:
        try:
            weights.append(float(word.get("weight") or 0))
        except (TypeError, ValueError):
            weights.append(0.0)
    low = min(weights) if weights else 0
    high = max(weights) if weights else 1
    span = max(high - low, 1)
    columns = 4 if len(words) >= 8 else 3
    rows = []
    for index in range(0, len(words), columns):
        cells = []
        for word, weight in zip(words[index : index + columns], weights[index : index + columns]):
            ratio = (weight - low) / span
            size = 11 + ratio * 12
            color = _hex(TONE_COLORS.get(str(word.get("tone") or "neutral"), NEUTRAL))
            cells.append(
                Paragraph(
                    f'<font size="{size:.1f}" color="{color}">{escape(str(word.get("text") or ""))}</font>',
                    styles["cloud_cell"],
                )
            )
        while len(cells) < columns:
            cells.append(Paragraph("", styles["cloud_cell"]))
        rows.append(cells)
    table = Table(
        rows,
        colWidths=[CONTENT_W / columns] * columns,
    )
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _comment_flow(comment: dict, styles):
    emotion = EMOTION_LABELS.get(str(comment.get("emotion") or ""), str(comment.get("emotion") or "—"))
    color = _hex(TONE_COLORS.get(str(comment.get("emotion") or "neutral"), NEUTRAL))
    header = Paragraph(
        f'<font color="{color}">{escape(emotion)}</font>'
        f'　·　{escape(str(comment.get("faction") or "—"))}'
        f'　·　第 {escape(str(comment.get("round") or "—"))} 轮',
        styles["small"],
    )
    return KeepTogether(
        [
            header,
            Spacer(1, 2),
            _quote_table(comment.get("text") or "", styles),
            Spacer(1, 2),
            _text(f"解读：{comment.get('insight') or ''}", styles["small"]),
            Spacer(1, 4),
        ]
    )


def _build_story(report: dict, styles) -> list:
    simulation = report.get("simulation") or {}
    summary = report.get("summary") or {}
    event = report.get("event") or {}
    trend = report.get("sentiment_trend") or []
    announcements = [item for item in (report.get("announcements") or []) if isinstance(item, dict)]
    words = [item for item in (report.get("word_cloud") or []) if isinstance(item, dict)]
    comments = [item for item in (report.get("key_comments") or []) if isinstance(item, dict)]
    conclusion = report.get("conclusion") or {}

    story = [
        Spacer(1, 9 * mm),
        Paragraph("PUBLIC OPINION SIMULATION REPORT", styles["kicker"]),
        _text(report.get("title") or "舆情推演报告", styles["cover_title"]),
        _text(report.get("subtitle") or "", styles["cover_sub"]),
        HRFlowable(width="100%", thickness=0.8, color=RULE, spaceBefore=0, spaceAfter=10),
        _meta_table(
            [
                ("报告编号", report.get("report_id")),
                ("生成时间", report.get("generated_at")),
                (
                    "推演规模",
                    f"{simulation.get('agent_count', '—')} Agent · {simulation.get('rounds', '—')} 轮",
                ),
                ("使用模型", simulation.get("model")),
            ],
            styles,
        ),
        Spacer(1, 5 * mm),
        Paragraph("摘要", styles["h3"]),
        _text(summary.get("overall") or "", styles["body"]),
        Spacer(1, 4 * mm),
        _summary_cards(report, styles),
        Spacer(1, 4 * mm),
    ]

    # 01 事件本身
    story.append(CondPageBreak(45 * mm))
    story += _section("01", "事件本身", None, styles)
    when_where = " · ".join(
        part for part in (event.get("time"), event.get("location")) if part
    )
    if when_where:
        story.append(_text(when_where, styles["small"]))
        story.append(Spacer(1, 2))
    story.append(_text(event.get("title") or "事件", styles["h3"]))
    story.append(_text(event.get("content") or "", styles["body"]))
    labels = " / ".join(event.get("labels") or [])
    foot_notes = []
    if labels:
        foot_notes.append(f"标签：{labels}")
    if event.get("event_id"):
        foot_notes.append(f"事件编号：{event.get('event_id')}")
    if foot_notes:
        story.append(_text("　·　".join(foot_notes), styles["small"]))
    story.append(Spacer(1, 2))

    # 02 情绪趋势 + 公告总分
    story.append(CondPageBreak(52 * mm))
    story += _section(
        "02",
        "情绪趋势与公告总分",
        "按轮次的负面、中性、正面情绪占比；公告总分为评论情绪 40% + 官方态度 60%",
        styles,
    )
    chart_width = CONTENT_W * 0.60 - 3 * mm
    ranking_width = CONTENT_W * 0.40 - 3 * mm
    if trend:
        chart = _trend_chart(trend, chart_width)
    else:
        chart = _text("本报告没有可用的情绪趋势数据。", styles["small"])
    ranking = (
        _ranking_table(announcements, styles, ranking_width)
        if announcements
        else _text("本报告没有公告方案评分。", styles["small"])
    )
    grid = Table([[chart, ranking]], colWidths=[CONTENT_W * 0.60, CONTENT_W * 0.40])
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(KeepTogether([grid]))

    # 03 公告评分与解析
    if announcements:
        story.append(CondPageBreak(60 * mm))
        story += _section(
            "03",
            "公告评分与解析",
            "五个维度各 20 分" if any((item.get("score") or {}).get("dimensions") for item in announcements)
            else "评论情绪 40% · 官方态度 60%",
            styles,
        )
        for index, item in enumerate(announcements, start=1):
            story.append(CondPageBreak(65 * mm))
            if index > 1:
                story.append(
                    HRFlowable(
                        width="100%",
                        thickness=0.4,
                        color=RULE,
                        spaceBefore=2,
                        spaceAfter=8,
                    )
                )
            story.extend(_announcement_flows(item, index, styles))
            story.append(Spacer(1, 6))

    # 04 讨论词云
    if words:
        story.append(CondPageBreak(50 * mm))
        story += _section("04", "讨论词云", "按讨论权重排序", styles)
        story.append(_word_cloud_table(words, styles))
        story.append(Spacer(1, 4))

    # 05 关键评论
    if comments:
        story.append(CondPageBreak(45 * mm))
        story += _section("05", "关键评论示例", f"精选 {len(comments)} 条", styles)
        for comment in comments:
            story.append(_comment_flow(comment, styles))

    # 06 结论与建议
    story.append(CondPageBreak(55 * mm))
    story += _section("06", "结论与建议", None, styles)
    if summary.get("overall"):
        story.append(_quote_table(summary.get("overall"), styles))
        story.append(Spacer(1, 5))
    for index, item in enumerate(conclusion.get("recommendations") or [], start=1):
        story.append(_text(f"{index}. {item}", styles["body"]))
    if conclusion.get("limitations"):
        story.append(Spacer(1, 5))
        story.append(HRFlowable(width="100%", thickness=0.4, color=RULE, spaceBefore=2, spaceAfter=5))
        story.append(_text("使用边界", styles["cell_head"]))
        story.append(_text(conclusion.get("limitations"), styles["small"]))

    return story


def build_report_pdf(report: dict) -> bytes:
    """把报告字典渲染为 PDF 字节。"""

    if not isinstance(report, dict):
        raise ValueError("报告数据必须是 JSON 对象。")
    styles = _styles()
    title = str(report.get("title") or "舆情推演报告")
    report_id = str(report.get("report_id") or "")
    buffer = BytesIO()
    document = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title,
        author="Simulation2",
        subject=str(report.get("subtitle") or ""),
    )
    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    document.addPageTemplates(
        [
            PageTemplate(
                id="main",
                frames=[frame],
                onPage=lambda canvas, doc: _draw_header(canvas, doc, title, report_id),
            )
        ]
    )
    document.build(_build_story(report, styles), canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


__all__ = ["build_report_pdf"]

"""Build an editable slide deck from extracted lesson material."""

from io import BytesIO
import re
from unicodedata import east_asian_width

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

PAGE_WIDTH = 13.333
PAGE_HEIGHT = 7.5
ROWS_PER_PAGE = 7
MAX_MATERIAL_PAGES = 18

NAVY = RGBColor.from_string("152A47")
BLUE = RGBColor.from_string("285EBA")
PAPER = RGBColor.from_string("F3F6FA")
WHITE = RGBColor.from_string("FFFFFF")
SLATE = RGBColor.from_string("445775")
PALE = RGBColor.from_string("E4EDFC")

OBJECTIVE = re.compile(
    r"^(?:#{1,6}\s*)?(?:教学目标|学习目标|课时目标|(?:Learning\s+)?Objectives?|Learning\s+Goals?)"
    r"(?:\s*[：:]\s*(.*))?\s*$",
    re.IGNORECASE,
)
LIST_ITEM = re.compile(r"^(?:[-*•]|\d{1,2}[.)、])\s*")
NON_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _wrap(text: str, limit: int) -> list[str]:
    """Wrap against a conservative character width, including wide CJK text."""
    lines = []
    current = ""
    width = 0
    for word in re.findall(r"\S+\s*", text):
        units = [2 if east_asian_width(ch) in {"W", "F", "A"} or ch in "mwMW@%&" or ch.isupper() else 1
                 for ch in word]
        if current and width + sum(units) > limit:
            lines.append(current.rstrip())
            current, width = "", 0
        for ch, unit in zip(word, units):
            if width + unit > limit:
                lines.append(current.rstrip())
                current, width = "", 0
            if current or not ch.isspace():
                current += ch
                width += unit
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _short(text: str, limit: int, lines: int) -> list[str]:
    rows = _wrap(text, limit)
    if len(rows) > lines:
        rows = rows[:lines]
        rows[-1] = rows[-1].rstrip("。.,，;； ") + "…"
    return rows


def _box(slide, x, y, width, height, color):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _text(slide, text, x, y, width, height, size, color=NAVY, *, bold=False):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(height))
    frame = shape.text_frame
    frame.word_wrap = False
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    paragraph = frame.paragraphs[0]
    paragraph.space_before = paragraph.space_after = Pt(0)
    run = paragraph.add_run()
    run.text = text
    run.font.name = "Arial Unicode MS"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    east_asian = OxmlElement("a:ea")
    east_asian.set("typeface", "Arial Unicode MS")
    properties = run._r.get_or_add_rPr()
    properties.set("lang", "zh-CN" if any("\u4e00" <= ch <= "\u9fff" for ch in text) else "en-US")
    properties.append(east_asian)


def _objectives(blocks: list[str]) -> list[str]:
    for position, block in enumerate(blocks):
        match = OBJECTIVE.fullmatch(block)
        if not match:
            continue
        inline = match.group(1)
        if inline:
            return [inline]
        items = []
        for item in blocks[position + 1 : position + 4]:
            if not LIST_ITEM.match(item):
                break
            items.append(LIST_ITEM.sub("", item))
        if items:
            return items
    return [
        "阅读本节材料，说出这节课的主题。",
        "从材料中找出两个关键词，并联系原句解释。",
        "用材料中的一个例子说明你理解的要点。",
    ]


def _material_pages(blocks: list[str]) -> list[list[str]]:
    rows = [row for block in blocks for row in _wrap(block, 57)]
    return [rows[index : index + ROWS_PER_PAGE] for index in range(0, len(rows), ROWS_PER_PAGE)]


def _page(deck, category, title, subtitle):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = PAPER
    _box(slide, 0, 0, PAGE_WIDTH, 0.10, BLUE)
    _text(slide, category, 0.75, 0.42, 11.8, 0.32, 12, BLUE, bold=True)
    _text(slide, title, 0.75, 0.89, 11.8, 0.76, 34, NAVY, bold=True)
    _text(slide, subtitle, 0.77, 1.67, 11.8, 0.38, 14, SLATE)
    _box(slide, 0.72, 2.23, 11.90, 4.43, WHITE)
    _text(slide, "BIBOO  /  课堂课件", 0.76, 7.04, 8.6, 0.28, 10, SLATE)
    _text(slide, f"{len(deck.slides):02d}", 12.03, 7.00, 0.53, 0.35, 12, BLUE, bold=True)
    return slide


def _write_rows(slide, rows, *, markers=False):
    for index, row in enumerate(rows):
        y = 2.48 + 0.55 * index
        if markers:
            _text(slide, f"{index + 1:02d}", 1.07, y + 0.04, 0.55, 0.33, 11, BLUE, bold=True)
        _text(slide, row, 1.72 if markers else 1.07, y, 10.60 if markers else 11.18, 0.44, 21)


def _cover(deck, title, material_count, excerpted, lesson):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = NAVY
    _box(slide, 0.74, 1.32, 0.10, 3.15, RGBColor.from_string("77B2FA"))
    _text(slide, "BIBOO  /  课堂课件", 1.02, 0.57, 11.3, 0.38, 15, PALE, bold=True)
    for index, row in enumerate(_short(title, 42, 3)):
        _text(slide, row, 1.00, 1.38 + 0.88 * index, 11.38, 0.80, 40, WHITE, bold=True)
    note = (
        f"根据本课目标和课堂活动整理 · {material_count} 页内容"
        if lesson else f"根据上传的教学材料整理 · {material_count} 页材料"
    )
    if excerpted:
        note += "（节选）"
    _text(slide, note, 1.03, 4.55, 11.3, 0.44, 17, PALE)
    for index, label in enumerate(("01  学习目标", "02  材料讲解", "03  课堂练习")):
        x = 1.03 + index * 3.70
        _box(slide, x, 5.77, 3.39, 0.65, BLUE)
        _text(slide, label, x + 0.23, 5.93, 2.98, 0.36, 15, WHITE, bold=True)


def build_courseware(title: str, source: str, *, lesson: bool = False) -> tuple[bytes, int]:
    """Return the PPTX bytes and slide count without persisting the source."""
    title = " ".join(NON_XML.sub("", title).split()) or "课堂课件"
    blocks = [" ".join(line.split()) for line in NON_XML.sub("", source).splitlines()]
    blocks = [line for line in blocks if line]
    if not blocks:
        raise ValueError("Courseware requires extracted text.")

    material = _material_pages(blocks)
    total = len(material)
    excerpted = total > MAX_MATERIAL_PAGES
    if excerpted:
        last = MAX_MATERIAL_PAGES - 1
        selected = [round(step * (total - 1) / last) for step in range(MAX_MATERIAL_PAGES)]
    else:
        selected = range(total)

    deck = Presentation()
    deck.slide_width = Inches(PAGE_WIDTH)
    deck.slide_height = Inches(PAGE_HEIGHT)
    deck.core_properties.title = title[:255]
    deck.core_properties.author = "Biboo"

    _cover(deck, title, len(selected), excerpted, lesson)
    slide = _page(deck, "01  学习目标", "这节课要完成什么", "读一读，想一想，用材料里的例子说一说。")
    for position, objective in enumerate(_objectives(blocks)[:3]):
        y = 2.54 + 1.23 * position
        _text(slide, f"{position + 1:02d}", 1.07, y + 0.06, 0.62, 0.36, 14, BLUE, bold=True)
        for index, row in enumerate(_short(objective, 52, 2)):
            _text(slide, row, 1.84, y + 0.46 * index, 10.35, 0.43, 21)

    for index in selected:
        title_suffix = f" · {index + 1:02d}/{total:02d}"
        subtitle = "按原顺序展示材料节选。" if excerpted else "一起阅读这一页，用原文找依据。"
        if lesson:
            subtitle = "按顺序练习本课词汇、句型和课堂活动。"
        slide = _page(deck, "02  材料讲解", ("本课内容" if lesson else "教学材料") + title_suffix, subtitle)
        _write_rows(slide, material[index])

    slide = _page(deck, "03  课堂练习", "读、找、说", "先独立完成，再和同桌交换想法。")
    _write_rows(slide, [
        "听老师读一个本课单词，跟读两次。",
        "用本课句型说一句话，再和同桌轮换。",
        "找出今天的发音重点，慢速读一遍。",
    ] if lesson else [
        "读一段材料，圈出两个关键词。",
        "从材料中选一个例子，用自己的话说一遍。",
        "和同桌对照原文，各提出一个问题。",
    ], markers=True)

    slide = _page(deck, "04  课末回顾", "带着三个问题离开", "给自己一分钟，写下今天学到的内容。")
    _write_rows(slide, [
        "我今天能读出哪些单词？",
        "我能用哪个句型说一句话？",
        "哪个音还想再练一遍？",
    ] if lesson else [
        "这节课的主题是什么？",
        "我能从材料中举出哪个例子？",
        "我还想再弄懂哪一点？",
    ], markers=True)

    output = BytesIO()
    deck.save(output)
    return output.getvalue(), len(deck.slides)

"""Editable, illustrated classroom activities for learners aged six to ten.

The illustrations are bundled assets. This export does not call an image or
language model, and never labels its deterministic lesson design as AI output.
"""

from io import BytesIO
from pathlib import Path
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from app.core.errors import AppError
from app.services.courseware_plan import plan_courseware
from app.services.courseware_pptx import NON_XML

ASSETS = Path(__file__).resolve().parents[1] / "assets/courseware/children"
WIDTH, HEIGHT = 13.333, 7.5
INK = "183B4B"
MUTED = "45636A"
CREAM = "FFF9EB"
AQUA = "E7F6F2"
PEACH = "FFF0E6"
LAVENDER = "F0EAFF"
YELLOW = "FFF3C8"
TEAL = "176B68"
FONT = "Arial Rounded MT Bold"
CJK_FONT = "Arial Unicode MS"


def _color(value):
    return RGBColor.from_string(value)


def _text(slide, text, x, y, w, h, size=30, color=INK, *, bold=False,
          align=PP_ALIGN.LEFT, name=""):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        box.name = name
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    for index, line in enumerate(str(text).split("\n")):
        p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        p.alignment = align
        p.space_after = Pt(3)
        p.space_before = Pt(0)
        run = p.add_run()
        run.text = line
        run.font.name = CJK_FONT if re.search(r"[\u3400-\u9fff]", line) else FONT
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = _color(color)
        props = run._r.get_or_add_rPr()
        ea = OxmlElement("a:ea")
        ea.set("typeface", CJK_FONT)
        props.append(ea)
    return box


def _phrase(slide, text, x, y, w, h, size=34, **kwargs):
    """Keep short spoken prompts readable when a teacher enters a longer line."""
    units = sum(1.0 if ord(c) > 255 else .62 for c in text)
    while size > 24:
        rows = max(1, int(units * size / (w * 72)) + 1)
        if rows * size * 1.25 <= h * 72:
            break
        size -= 1
    return _text(slide, text, x, y, w, h, size, **kwargs)


def _picture(slide, key, x, y, w, h, *, description=""):
    # Asset names are chosen by the planner, never by a client-supplied path.
    allowed = {"ocean", "owl", "octopus", "crab", "jellyfish", "turtle", "sea-star"}
    if key not in allowed:
        key = "owl"
    path = ASSETS / f"{key}.png"
    if not path.is_file():
        raise AppError(503, "COURSEWARE_ART_UNAVAILABLE", "儿童课件插画尚未准备好，请稍后重试。")
    from PIL import Image
    with Image.open(path) as image:
        ratio = image.width / image.height
    fitted_w, fitted_h = min(w, h * ratio), min(h, w / ratio)
    image = slide.shapes.add_picture(
        str(path), Inches(x + (w - fitted_w) / 2), Inches(y + (h - fitted_h) / 2),
        width=Inches(fitted_w), height=Inches(fitted_h),
    )
    image.name = f"illustration-{key}"
    image._pic.nvPicPr.cNvPr.set("descr", description or key)
    return image


def _notes(slide, text):
    slide.notes_slide.notes_text_frame.text = (
        text + "\n\n教学对象：6–10 岁。6–7 岁可先指图或说单词，8–10 岁鼓励说完整句。"
        "\n插画：Biboo 原创儿童插画库，使用图像生成工具制作。"
    )


def _slide(deck, *, bg=CREAM, label="", title="", hint="", note="", hidden=False):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _color(bg)
    if hidden:
        slide._element.set("show", "0")
    if label:
        _text(slide, label, .65, .32, 11.8, .35, 15, TEAL)
    if title:
        _text(slide, title, .65, .92, 12.0, .95, 40, name="slide-title")
    if hint:
        _text(slide, hint, .68, 1.86, 11.7, .65, 22, MUTED)
    _text(slide, "Biboo", .66, 7.04, 2.0, .25, 12, MUTED)
    _text(slide, f"{len(deck.slides):02d}", 12.13, 7.02, .5, .3, 13, MUTED,
          align=PP_ALIGN.RIGHT)
    if note:
        _notes(slide, note)
    return slide


def _link(slide, label, target, x, y, w=2.5, *, fill=TEAL):
    button = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(.60),
    )
    button.fill.solid()
    button.fill.fore_color.rgb = _color(fill)
    button.line.fill.background()
    button.adjustments[0] = .2
    button.name = "classroom-navigation"
    button.text_frame.clear()
    button.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = button.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = label
    run.font.name = CJK_FONT
    run.font.size = Pt(20)
    run.font.color.rgb = _color("FFFFFF")
    button.click_action.target_slide = target
    return button


def _activity(plan, kind):
    return next((a for a in plan.activities if a.kind == kind), None)


def _cover(deck, plan):
    slide = _slide(deck, bg=AQUA if plan.theme == "ocean" else CREAM)
    if plan.theme == "ocean":
        _picture(slide, "ocean", 0, 0, WIDTH, HEIGHT)
    else:
        _picture(slide, "owl", 7.2, 1.25, 5.5, 5.4)
    # The scene intentionally leaves the left half clear for editable text.
    _text(slide, "LET'S PLAY & LEARN", .75, .7, 6.3, .45, 17, TEAL)
    title = plan.title.strip()
    # Display the uploaded title, not a title invented from the picture theme.
    title = re.sub(r"\s*[·|｜]\s*", "\n", title, count=1)
    size = 50 if len(title) < 36 else 38 if len(title) < 62 else 30
    _text(slide, title, .75, 1.65, 6.25, 3.15, size, bold=True, name="lesson-title")
    _text(slide, "一起创造一个海洋新朋友" if plan.theme == "ocean" else "和 Biboo 一起发现新单词",
          .8, 5.15, 6.2, .75, 24, TEAL)
    _text(slide, "6–10 岁  /  看一看 · 猜一猜 · 说一说", .8, 6.25, 6.8, .45, 18, MUTED)
    _notes(slide, plan.teacher_notes +
           "\n使用方法：在幻灯片放映模式中授课。猜谜页可点击图片或单词选答案；"
           "也可以按下一页揭晓。错误反馈页隐藏在正常播放顺序之外。"
           "\n课堂重点来自上传材料。海洋背景中的动物用于情境导入，不要求额外记忆全部名称。")


def build_children_courseware(title: str, source: str, *, lesson: bool = False) -> tuple[bytes, int]:
    """Build a classroom sequence; the old text-layout exporter remains separate."""
    plan = plan_courseware(NON_XML.sub("", title), NON_XML.sub("", source))
    words = list(plan.vocabulary)
    if not words:
        raise AppError(422, "COURSEWARE_WORDS_MISSING", "没有识别到英文目标词，请在材料中补充“词汇”一栏后重试，或选择文字整理模式。")
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(WIDTH), Inches(HEIGHT)
    deck.core_properties.title = plan.title[:255]
    deck.core_properties.author = "Biboo"
    deck.core_properties.subject = "6–10 岁儿童互动课堂"
    _cover(deck, plan)

    warmup = _activity(plan, "warmup")
    slide = _slide(deck, label="HELLO, EXPLORERS!", title="What can you see?",
                   hint="你发现了什么？指一指，和同桌说一说。", bg=CREAM,
                   note=warmup.teacher_note if warmup else "给孩子20秒观察，再请他们指图说出已知词汇。")
    keys = list(dict.fromkeys(word.asset for word in words if word.asset != "owl"))[:4]
    if plan.theme == "ocean" and keys:
        for index, key in enumerate(keys):
            span = 11.7 / max(len(keys), 1)
            _picture(slide, key, .8 + span * index, 2.55, span - .18, 3.65)
            _text(slide, str(index + 1), .8 + span * index, 6.25, span - .18, .45, 25,
                  align=PP_ALIGN.CENTER)
    else:
        _picture(slide, "owl", .8, 2.6, 3.8, 3.8)
        preview = "\n".join(w.word for w in words[:4]) or "Look at your lesson material."
        _text(slide, preview, 5.2, 2.65, 7.1, 3.9, 34)

    for index, word in enumerate(words):
        slide = _slide(deck, bg=(AQUA, PEACH, LAVENDER, YELLOW)[index % 4],
                       label=f"OUR NEW WORD {index + 1}",
                       note=f"目标词：{word.word}。先看图，用动作帮助理解，然后全班跟读两遍。"
                       f"\n教师动作：{word.gesture}\n示范句：{word.model_sentence}"
                       "\n先留5秒给孩子尝试，不急着纠正每一个发音。"
                       + ("\n图片是 Biboo 引导角色，并非该词的释义图。请结合上传材料解释词义。"
                          if word.asset == "owl" else ""))
        size = 66 if len(word.word) <= 10 else 49 if len(word.word) <= 18 else 34
        _text(slide, word.word, .78, 1.5, 6.2, 1.55, size, bold=True)
        if word.label_zh:
            _text(slide, word.label_zh, .84, 3.0, 5.7, .55, 26, TEAL)
        _phrase(slide, word.model_sentence, .84, 4.1, 6.0, 1.5, 32)
        _text(slide, word.gesture, .84, 6.10, 11.4, .62, 21, MUTED)
        _picture(slide, word.asset, 7.0, 1.15, 5.55, 4.85,
                 description=f"Cartoon teaching illustration for {word.word}")
        if word.asset == "owl":
            _text(slide, "跟着老师，看实物或材料中的图片", 7.0, 5.93, 5.55, .42,
                  17, MUTED, align=PP_ALIGN.CENTER)

    question = answer_slide = retry_slide = None
    choices = []
    if plan.mystery and len(plan.mystery.options) >= 2:
        mystery = plan.mystery
        question = _slide(deck, label="GUESSING GAME", title="Can you solve it?", bg=CREAM,
                          note=mystery.teacher_note +
                          "\n先读线索，孩子用手指或举手选择。放映时点击选项图片/单词会打开反馈。"
                          "\n按下一页可直接揭晓。答案不显示在本页。")
        _text(question, mystery.question, .8, 1.95, 11.8, 1.0, 31)
        lookup = {w.word: w for w in words}
        for index, option in enumerate(mystery.options):
            word = lookup.get(option)
            span = 11.7 / len(mystery.options)
            x = .8 + span * index
            picture = _picture(question, word.asset if word else "owl", x, 3.12, span - .3, 2.5)
            label = _text(question, option, x, 5.8, span - .3, .6,
                          29 if len(option) < 16 else 22, align=PP_ALIGN.CENTER)
            choices.append((picture, label, index))
        _text(question, "想好了，再点选一个答案", .8, 6.5, 11.5, .35, 18, MUTED,
              align=PP_ALIGN.CENTER)
        correct_word = lookup.get(mystery.options[mystery.correct])
        answer_slide = _slide(deck, label="YOU FOUND IT!", title="Yes! You got it!", bg=AQUA,
                              hint="给自己一个小小的鼓励，再用一句话说出来。",
                              note=f"正确选项：{mystery.options[mystery.correct]}。{mystery.teacher_note}"
                              "\n请全班一起说，再请一位孩子独立说。接受先说词、后补完整句。")
        _picture(answer_slide, correct_word.asset if correct_word else "owl", 7.65, 2.6, 4.6, 3.9)
        _text(answer_slide, mystery.options[mystery.correct], .8, 3.0, 6.6, 1.15, 52)
        _phrase(answer_slide, correct_word.model_sentence if correct_word else mystery.answer,
                .84, 4.45, 6.45, 1.25, 30)

    movement = _activity(plan, "movement")
    move_slide = _slide(deck, label="MOVE & SAY", title="Show me!", bg=YELLOW,
                        hint="听到一个词，就用动作表现出来。", note=(movement.teacher_note if movement else
                        "教师打乱顺序说词，孩子做动作。第二轮请一个孩子做小老师发指令。"))
    _picture(move_slide, "owl", .65, 2.6, 4.4, 3.95)
    for index, word in enumerate(words[:3]):
        y = 2.67 + index * 1.18
        _text(move_slide, word.word, 5.5, y, 6.8, .55, 31)
        _text(move_slide, word.gesture, 5.5, y + .58, 6.8, .5, 20, MUTED)
    if answer_slide is not None:
        _link(answer_slide, "继续挑战", move_slide, .84, 6.15)

    first = words[0] if words else None
    sentence = _activity(plan, "sentence")
    slide = _slide(deck, label="LET'S SAY A SENTENCE", title="Your turn to talk", bg=LAVENDER,
                   hint="看图，试着说完整的一句。",
                   note=sentence.teacher_note if sentence else "先示范一句，让孩子替换一个词。指图或只说词也可参与。")
    pattern = plan.patterns[0] if plan.patterns else "I can say ___."
    model = first.model_sentence if first else "I can say it."
    if pattern and "___" not in pattern:
        model = pattern
    elif "___" in pattern and not re.match(r"It(?:'s| is) got", pattern):
        # Leave unfamiliar source frames intact instead of inserting a noun
        # without knowing its article, plural, or verb agreement.
        model = "选一个本课词，请老师帮你补完整。"
    _phrase(slide, pattern, .8, 2.7, 7.1, 1.45, 37)
    _phrase(slide, model, .84, 4.5, 6.6, 1.4, 30, color=TEAL)
    _text(slide, "先听一句，再换一个词。", .84, 6.2, 8.0, .45, 22, MUTED)
    _picture(slide, first.asset if first else "owl", 8.1, 2.8, 4.4, 3.7)

    body_words = {"arms", "claws", "tentacles", "shell", "tail", "fin", "blowhole"}
    body_focus = plan.theme == "ocean" and any(word.word in body_words for word in words)
    slide = _slide(deck, label="TALK WITH A FRIEND", title="My turn. Your turn.", bg=PEACH,
                   hint="两人一组。一人指图，一人说；说完交换。",
                   note="给同桌各30秒。A指向已学图片，B说词或完整句，然后交换。"
                   "\n教师巡视只记录共性问题，不打断每一句表达。")
    _text(slide, "A", .9, 2.75, .7, .7, 36, TEAL)
    _text(slide, "What's it got?" if body_focus else "Your turn!",
          1.85, 2.8, 7.2, .95, 35)
    _text(slide, "B", .9, 4.15, .7, .7, 36, TEAL)
    _phrase(slide, pattern, 1.85, 4.2, 7.2, 1.5, 34)
    _picture(slide, words[-1].asset if words else "owl", 9.0, 2.75, 3.5, 3.4)
    _text(slide, "现在交换角色！", .9, 6.2, 8, .5, 24, TEAL)

    create = _activity(plan, "create")
    slide = _slide(deck, label="IMAGINE & CREATE", title="My new sea creature" if plan.theme == "ocean" else "My word picture",
                   bg=CREAM, hint="拿出纸和笔，把你的想法画出来。",
                   note=create.teacher_note if create else "留3–5分钟创作。让孩子画图并标出学过的词，先独立完成，再分享。")
    number = "两个" if len(words) > 1 else "一个"
    if body_focus:
        tasks = [f"选{number}身体部位", "画一个海洋新朋友", "给它起一个名字"]
    elif plan.theme == "ocean":
        tasks = [f"选{number}今天学过的词", "画出你想象的海洋朋友", "给它起一个名字"]
    else:
        tasks = [f"选{number}今天学过的词", "把它们画进同一幅图", "给同桌讲讲你的画"]
    for index, task in enumerate(tasks):
        _text(slide, f"{index + 1}", .9, 2.9 + index * 1.1, .7, .6, 31, TEAL)
        _text(slide, task, 1.9, 2.9 + index * 1.1, 6.2, .7, 29)
    _picture(slide, "owl", 8.5, 2.6, 4.0, 3.8)
    _text(slide, "可以画得很奇妙！", .9, 6.4, 7.6, .4, 21, MUTED)

    slide = _slide(deck, label="SHOW & TELL", title="Meet my new friend!" if plan.theme == "ocean" else "Look at my picture!",
                   bg=AQUA, hint="举起你的画，让同桌认识它。",
                   note="先让孩子两人互讲，再邀请愿意分享的孩子展示。听的孩子指出一个学过的词。"
                   "\n低龄孩子可用单词加手势；高龄孩子鼓励使用两种不同句型。")
    frames = ["This is ___…", pattern]
    if len(plan.patterns) > 1:
        frames.append(plan.patterns[1])
    for index, frame in enumerate(frames[:3]):
        _phrase(slide, frame, .9, 2.65 + index * 1.2, 8.1, 1.08, 33)
    _picture(slide, "owl", 9.2, 3.0, 3.1, 3.0)
    _text(slide, "听完，告诉伙伴：我喜欢你画的……", .9, 6.35, 11.5, .5, 22, MUTED)

    exit_activity = _activity(plan, "exit")
    slide = _slide(deck, label="ONE LAST CHALLENGE", title="Can you remember?", bg=LAVENDER,
                   hint="不看前面的单词，你还能说出来吗？",
                   note=exit_activity.teacher_note if exit_activity else "逐一指图，孩子回忆词汇。再请孩子说一句今天学会的句子。")
    for index, word in enumerate(words[:4]):
        span = 11.7 / max(min(len(words), 4), 1)
        _picture(slide, word.asset, .8 + index * span, 2.7, span - .15, 2.7)
        # For unillustrated vocabulary, a first-letter cue is meaningful; the owl is just a guide.
        label = "?" if word.asset != "owl" else word.word[0] + "…"
        _text(slide, label, .8 + index * span, 5.6, span - .15, .8, 42, TEAL, align=PP_ALIGN.CENTER)

    finish = _slide(deck, label="WELL DONE, EXPLORER!", title="I can do it!", bg=YELLOW,
                    hint="选一件你今天学会的事，说给老师听。",
                    note=plan.teacher_notes + "\n\n上传材料原文（供教师核对，不在课堂投影展示）：\n" + plan.source_notes)
    _text(finish, "我能说出新单词。\n我能说一句完整的话。\n我能介绍自己的作品。", .9, 3.0, 7.0, 2.6, 29)
    _picture(finish, "owl", 8.3, 2.65, 4.1, 3.8)
    _text(finish, "See you next time!", .9, 6.25, 8.0, .6, 29, TEAL)

    if question is not None:
        retry_slide = _slide(deck, label="LET'S THINK AGAIN", title="One more try!", bg=PEACH,
                             hint="听听线索，再找一找。", hidden=True,
                             note="本页仅在孩子选择其他答案时出现，不在正常播放顺序中。点击返回猜谜继续。")
        _text(retry_slide, plan.mystery.question, .9, 3.0, 7.0, 1.6, 31)
        _picture(retry_slide, "owl", 8.6, 2.6, 3.6, 3.6)
        _link(retry_slide, "返回猜谜", question, .9, 5.75)
        _link(answer_slide, "再看一次题目", question, 3.65, 6.15, 3.05, fill="45636A")
        for picture, label, index in choices:
            target = answer_slide if index == plan.mystery.correct else retry_slide
            picture.click_action.target_slide = target
            label.click_action.target_slide = target
    output = BytesIO()
    deck.save(output)
    return output.getvalue(), len(deck.slides)

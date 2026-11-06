from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from pptx import Presentation

from app.core.errors import AppError
from app.services.courseware_children_pptx import build_children_courseware


def visible_text(slide):
    return "\n".join(shape.text for shape in slide.shapes if shape.has_text_frame)


def test_children_deck_has_illustrations_editable_prompts_and_working_quiz_targets():
    source = "Sea creatures\nVocabulary: arms, claws, tentacles, shell\nSentence patterns: It's got ___."
    binary, count = build_children_courseware("My sea creature", source)
    deck = Presentation(BytesIO(binary))
    assert count == len(deck.slides)
    assert 12 <= count <= 20
    assert "My sea creature" in visible_text(deck.slides[0])
    assert source in deck.slides[-2].notes_slide.notes_text_frame.text
    assert sum(shape.shape_type == 13 for slide in deck.slides for shape in slide.shapes) >= 10
    question = next(s for s in deck.slides if "Can you solve it?" in visible_text(s))
    answer = next(s for s in deck.slides if "Yes! You got it!" in visible_text(s))
    retry = next(s for s in deck.slides if "One more try!" in visible_text(s))
    assert retry._element.get("show") == "0"
    assert "It's got claws." in visible_text(answer)
    assert "It's got claws." not in visible_text(question)
    targets = [shape.click_action.target_slide for shape in question.shapes]
    assert sum(target == answer for target in targets) == 2  # image and editable word
    assert sum(target == retry for target in targets) == 4
    assert any(shape.click_action.target_slide == question for shape in retry.shapes)
    # No embedded executable action or external link is used for the game.
    with ZipFile(BytesIO(binary)) as archive:
        for name in archive.namelist():
            if name.endswith(".rels"):
                root = ET.fromstring(archive.read(name))
                assert all(rel.get("TargetMode") != "External" for rel in root)
    original = next(shape for shape in deck.slides[2].shapes if shape.has_text_frame and shape.text == "arms")
    original.text = "arms – edited by teacher"
    edited = BytesIO()
    deck.save(edited)
    assert "arms – edited by teacher" in visible_text(Presentation(BytesIO(edited.getvalue())).slides[2])


def test_non_ocean_lesson_does_not_gain_ocean_vocabulary_or_picture_facts():
    binary, _ = build_children_courseware("My family", "Vocabulary: mother, father, sister\nI love my family.")
    deck = Presentation(BytesIO(binary))
    text = "\n".join(visible_text(s) for s in deck.slides)
    assert "mother" in text and "father" in text
    assert "It's got" not in text and "sea creature" not in text
    assert all(shape.name != "illustration-ocean" for slide in deck.slides for shape in slide.shapes)
    assert "跟着老师，看实物或材料中的图片" in text


def test_children_mode_without_reliable_english_words_explains_how_to_recover():
    with pytest.raises(AppError) as error:
        build_children_courseware("测试材料", "今天学习怎样分享自己的想法。")
    assert error.value.detail.error.code == "COURSEWARE_WORDS_MISSING"


def test_ocean_words_without_subject_art_still_have_a_usable_warmup():
    binary, _ = build_children_courseware("Sea animals", "Vocabulary: dolphin, whale, shark\nSea animals")
    warmup = Presentation(BytesIO(binary)).slides[1]
    assert all(word in visible_text(warmup) for word in ("dolphin", "whale", "shark"))
    assert any(shape.name == "illustration-owl" for shape in warmup.shapes)

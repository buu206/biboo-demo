from io import BytesIO
from zipfile import ZipFile
import wave

from lxml import etree
from pptx import Presentation

from app.services.courseware_children_pptx import build_children_courseware

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def wav():
    out = BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 2400)
    return out.getvalue()


def test_word_builds_hide_answers_until_later_clicks_and_keep_native_audio():
    voice = wav()
    binary, _ = build_children_courseware("Sea friends", "Vocabulary: crab, turtle",
                                          audio_by_text={"crab": (voice, "audio/wav")})
    deck = Presentation(BytesIO(binary))
    word_slide = deck.slides[2]
    root = word_slide._element
    steps = root.xpath('.//p:cTn[@nodeType="mainSeq"]/p:childTnLst/p:par')
    assert len(steps) == 4
    shapes = {str(s.shape_id): s for s in word_slide.shapes}
    first = steps[0].xpath('.//p:spTgt/@spid', namespaces=NS)
    assert all(shapes[i].name == "illustration-crab" for i in first)
    second = {shapes[i].text for i in steps[1].xpath('.//p:spTgt/@spid', namespaces=NS)}
    assert second == {"crab", "螃蟹"}
    assert not any("crab" == getattr(shapes[i], "text", "") for i in first)
    assert root.xpath('.//p:audio/p:cMediaNode/p:cTn/p:stCondLst/p:cond/@delay') == ['indefinite']
    assert root.xpath('.//a:audioFile') and not root.xpath('.//a:videoFile')
    assert not root.xpath('.//a:hlinkClick/a:snd')
    assert root.xpath('.//p:cmd/@cmd') == ['playFrom(0.0)']
    assert root.xpath('.//p:cTn[@nodeType="interactiveSeq"]/p:stCondLst/p:cond/@evt') == ['onClick']
    assert len(root.xpath('p:timing')) == 1
    assert not root.xpath('p:transition/@advTm')  # teacher owns the pace
    with ZipFile(BytesIO(binary)) as package:
        assert any(name.endswith(".wav") and package.read(name) == voice for name in package.namelist())
        for name in package.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                xml = etree.fromstring(package.read(name))
                ids = xml.xpath('.//p:cTn/@id', namespaces=NS)
                assert len(ids) == len(set(ids))
                targets = set(xml.xpath('.//p:spTgt/@spid', namespaces=NS))
                actual = set(xml.xpath('.//p:cNvPr/@id', namespaces=NS))
                assert targets <= actual
    # Teacher editing and saving must preserve the timeline and the media.
    next(s for s in word_slide.shapes if s.has_text_frame and s.text == "crab").text = "CRAB"
    saved = BytesIO()
    deck.save(saved)
    assert Presentation(BytesIO(saved.getvalue())).slides[2]._element.xpath('.//a:audioFile')


def test_partner_swap_exits_old_prompts_without_hiding_navigation():
    binary, _ = build_children_courseware("Sea friends", "Vocabulary: crab, turtle")
    deck = Presentation(BytesIO(binary))
    slide = next(s for s in deck.slides if any(getattr(sh, "text", "") == "My turn. Your turn." for sh in s.shapes))
    exits = slide._element.xpath('.//p:animEffect[@transition="out"]')
    assert len(exits) == 4
    assert slide._element.xpath('.//p:set/p:to/p:strVal[@val="hidden"]')
    assert not slide._element.xpath('.//p:audio')

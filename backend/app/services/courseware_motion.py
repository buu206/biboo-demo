"""Native PresentationML teaching builds and embedded, click-to-play audio.

No macros, remote media, autoplay, or timed slide advance. Each build is one
teacher click; several shapes can share a build (e.g. a word and its meaning).
"""

from io import BytesIO

from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Inches


def node(tag, parent=None, **attrs):
    element = OxmlElement(tag)
    for key, value in attrs.items():
        element.set(key, str(value))
    if parent is not None:
        parent.append(element)
    return element


def reveal(slide, *shapes, hide=()):
    """Queue one teacher-controlled build. Shapes remain fully editable."""
    if not hasattr(slide, "_biboo_builds"):
        slide._biboo_builds = []
    slide._biboo_builds.append((tuple(s.shape_id for s in shapes), tuple(s.shape_id for s in hide)))


def _condition(parent, delay, event=None, target=False):
    condition = node("p:cond", parent, delay=delay)
    if event:
        condition.set("evt", event)
    if target:
        node("p:sldTgt", node("p:tgtEl", condition))


def _behavior(parent, shape_id, duration):
    behavior = node("p:cBhvr", parent)
    node("p:cTn", behavior, dur=duration, fill="hold")
    node("p:spTgt", node("p:tgtEl", behavior), spid=shape_id)
    return behavior


def _effect(parent, shape_id, entering):
    effect = node("p:cTn", node("p:par", parent), presetID=10,
                  presetClass="entr" if entering else "exit", presetSubtype=0,
                  fill="hold", nodeType="clickEffect")
    _condition(node("p:stCondLst", effect), 0)
    children = node("p:childTnLst", effect)
    # PowerPoint uses a visibility set alongside the fade. An entrance preset
    # hides its target before the build; exit visibility changes after the fade.
    setting = node("p:set", children)
    behavior = _behavior(setting, shape_id, 1)
    ct = behavior.find(qn("p:cTn"))
    _condition(node("p:stCondLst", ct), 0 if entering else 350)
    node("p:attrName", node("p:attrNameLst", behavior)).text = "style.visibility"
    node("p:strVal", node("p:to", setting), val="visible" if entering else "hidden")
    fade = node("p:animEffect", children, transition="in" if entering else "out", filter="fade")
    _behavior(fade, shape_id, 350)


def finish_motion(slide):
    """Merge builds with media timing; keep a single root and unique node IDs."""
    transition = node("p:transition", spd="fast", advClick=1)
    node("p:fade", transition)
    slide._element.insert_element_before(transition, "p:timing", "p:extLst")
    timing = slide._element.find(qn("p:timing"))
    builds = getattr(slide, "_biboo_builds", [])
    if not builds and timing is None:
        return
    if timing is None:
        timing = node("p:timing")
        slide._element.insert_element_before(timing, "p:extLst")
        root = node("p:cTn", node("p:par", node("p:tnLst", timing)),
                    dur="indefinite", restart="never", nodeType="tmRoot")
        children = node("p:childTnLst", root)
    else:
        root = timing.find(".//" + qn("p:cTn"))
        children = root.find(qn("p:childTnLst"))
        if children is None:
            children = node("p:childTnLst", root)
    if builds:
        sequence = node("p:seq", concurrent=1, nextAc="seek")
        children.insert(0, sequence)
        main = node("p:cTn", sequence, dur="indefinite", nodeType="mainSeq")
        steps = node("p:childTnLst", main)
        for enter, leave in builds:
            outer = node("p:cTn", node("p:par", steps), fill="hold")
            _condition(node("p:stCondLst", outer), "indefinite")
            inner = node("p:cTn", node("p:par", node("p:childTnLst", outer)), fill="hold")
            _condition(node("p:stCondLst", inner), 0)
            effects = node("p:childTnLst", inner)
            for shape_id in enter:
                _effect(effects, shape_id, True)
            for shape_id in leave:
                _effect(effects, shape_id, False)
        for tag, event in (("p:prevCondLst", "onPrev"), ("p:nextCondLst", "onNext")):
            _condition(node(tag, sequence), 0, event, True)
    for index, ct in enumerate(timing.iter(qn("p:cTn")), 1):
        ct.set("id", str(index))


def embed_audio(slide, content, mime, *, x=11.55, y=6.12):
    """Add an offline native audio object with a speaker poster, no autoplay."""
    from PIL import Image, ImageDraw

    if mime not in {"audio/wav", "audio/mpeg"} or not 0 < len(content) <= 2_000_000:
        raise ValueError("Unsupported classroom audio")
    poster = Image.new("RGB", (180, 180), "#176B68")
    draw = ImageDraw.Draw(poster)
    draw.polygon([(39, 72), (65, 72), (99, 43), (99, 137), (65, 108), (39, 108)], fill="white")
    draw.arc((81, 48, 141, 132), -65, 65, fill="white", width=8)
    image = BytesIO()
    poster.save(image, format="PNG")
    image.seek(0)
    # A standard sound action on a visible picture is supported by PowerPoint
    # without autoplay or a hidden video control. Short TTS clips need replay,
    # not a transport bar. The relationship points inside the PPTX package.
    from pptx.media import Video

    extension = "wav" if mime == "audio/wav" else "mp3"
    media = Video.from_blob(content, mime, f"teacher.{extension}")
    part = slide.part.package.get_or_add_media_part(media)
    audio_id = slide.part.relate_to(part, RT.AUDIO)
    audio = slide.shapes.add_picture(image, Inches(x), Inches(y), Inches(.62), Inches(.62))
    audio.name = "classroom-audio"
    audio._element.nvPicPr.cNvPr.set("descr", "点击播放示范声音；再次点击从头播放")
    click = node("a:hlinkClick", audio._element.nvPicPr.cNvPr, endSnd=1)
    click.set(qn("r:id"), "")
    sound = node("a:snd", click, name=f"teacher.{extension}")
    sound.set(qn("r:embed"), audio_id)
    return audio

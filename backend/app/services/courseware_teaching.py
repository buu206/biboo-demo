"""Bounded AI teaching copy and reusable voice for the children's exporter."""

from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.services import ai
from app.services.courseware_plan import plan_courseware, _mystery

PROMPT = (Path(__file__).parent / "prompts/courseware_v1.md").read_text()


class TeachingWord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str = Field(min_length=1, max_length=24)
    meaning: str = Field(min_length=1, max_length=12)
    sentence: str = Field(min_length=3, max_length=70)
    gesture: str = Field(min_length=3, max_length=36)


class TeachingCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    words: list[TeachingWord] = Field(min_length=1, max_length=4)


def apply_copy(plan, raw):
    output = TeachingCopy.model_validate_json(raw)
    expected = [word.word for word in plan.vocabulary]
    if [word.word for word in output.words] != expected:
        raise ValueError("Focus vocabulary changed")
    result = []
    for old, new in zip(plan.vocabulary, output.words):
        if (len(ai.WORDS.findall(new.sentence)) > 10
                or not re.search(r"(?<![A-Za-z])" + re.escape(old.word) + r"(?![A-Za-z])", new.sentence, re.I)
                or not re.fullmatch(r"[A-Za-z ,.!?'’\-]+", new.sentence)
                or re.search(r"https?://|<|>|[\x00-\x1f]", new.meaning + new.gesture)):
            raise ValueError("Invalid teaching copy")
        result.append(replace(old, label_zh=new.meaning, model_sentence=new.sentence,
                              gesture=new.gesture, clue=f"{new.meaning}，用英语怎么说？"))
    words = tuple(result)
    return replace(plan, vocabulary=words, mystery=_mystery(words))


def enrich_plan(settings, plan, record):
    if settings.fake_models:
        return plan, "template"
    call = ai.Call(settings.deepseek_model)
    started = time.monotonic()
    try:
        with OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url,
                    timeout=settings.model_timeout_seconds, max_retries=0) as client:
            response = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps({
                    "title": plan.title, "focus_words": [w.word for w in plan.vocabulary],
                    "patterns": plan.patterns, "material": plan.source_notes[:6000],
                }, ensure_ascii=False)}],
                response_format={"type": "json_object"}, max_tokens=900,
                extra_body={"thinking": {"type": "disabled"}},
            )
        call.request_id = response._request_id or response.id
        if response.usage:
            call.input_tokens, call.output_tokens = response.usage.prompt_tokens, response.usage.completion_tokens
        result = apply_copy(plan, response.choices[0].message.content or "")
        call.structure, call.result = "合规", "通过"
        return result, "ai"
    except Exception:
        call.error = "COURSEWARE_COPY_FALLBACK"
        return plan, "fallback"
    finally:
        call.seconds = round(time.monotonic() - started, 3)
        record("courseware_copy", call)


def classroom_audio(settings, plan, existing, owner_id, record):
    """Only target vocabulary is synthesized; no student recordings are read."""
    result = dict(existing or {})
    if settings.fake_models:
        return result
    deadline = time.monotonic() + min(settings.publish_timeout_seconds, 45)
    folder = settings.data_dir / "courseware-audio" / str(owner_id)
    folder.mkdir(parents=True, exist_ok=True)
    for word in plan.vocabulary:
        key = word.word.casefold().strip(" .!?")
        if key in result:
            continue
        identity = json.dumps([word.word, settings.tts_provider, settings.tts_model_label,
            settings.aihubmix_tts_voice, settings.aihubmix_tts_instructions, settings.aihubmix_tts_speed,
            settings.tts_region, settings.tts_voice_type, settings.tts_speed])
        digest = sha256(identity.encode()).hexdigest()
        for ext, mime in (("wav", "audio/wav"), ("mp3", "audio/mpeg")):
            cached = folder / f"{digest}.{ext}"
            if cached.is_file() and 0 < cached.stat().st_size <= ai.MAX_AUDIO_BYTES:
                result[key] = (cached.read_bytes(), mime)
                break
        if key in result:
            continue
        try:
            audio, mime = ai.synthesize(settings, word.word, deadline, record)
            suffix = "wav" if mime == "audio/wav" else "mp3"
            destination = folder / f"{digest}.{suffix}"
            temporary = folder / f".{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(audio)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            result[key] = (audio, mime)
        except AppError:
            # A voice outage does not destroy a usable editable deck. Missing
            # audio is explicitly disclosed in the slide notes and response.
            break
    return result


def prepare_teaching(settings, title, source, existing, owner_id, record):
    plan = plan_courseware(title, source)
    if not plan.vocabulary:
        raise AppError(422, "COURSEWARE_WORDS_MISSING", "请在材料中补充英文词汇后重试。")
    plan, mode = enrich_plan(settings, plan, record)
    audios = classroom_audio(settings, plan, existing, owner_id, record)
    count = sum(w.word.casefold().strip(" .!?") in audios for w in plan.vocabulary)
    note = {"ai": "例句、词义和动作由 AI 辅助生成，请老师课前核对。",
            "template": "本次使用本机教学模板。", "fallback": "AI 生成暂不可用，本次使用教学模板。"}[mode]
    plan = replace(plan, teacher_notes=plan.teacher_notes + "\n" + note +
                   f"\n已附 {count}/{len(plan.vocabulary)} 个词汇示范声音。")
    return plan, audios, mode, count

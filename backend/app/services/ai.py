import base64
import io
import json
import math
import re
import struct
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import ValidationError
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.tts.v20190823 import models, tts_client

from app.core.errors import AppError
from app.schemas import GeneratedContent, LessonInput

PROMPT = (Path(__file__).parent / "prompts" / "homework_v1.md").read_text()
WORDS = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
MAX_AUDIO_BYTES = 2_000_000


@dataclass
class Call:
    model: str
    seconds: float = 0
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    structure: str = "不适用"
    retry: int = 0
    result: str = "失败"
    error: str | None = None

    def detail(self):
        return asdict(self)


def parse_content(raw: str):
    decoder = json.JSONDecoder()
    position = 0
    while (start := raw.find("{", position)) >= 0:
        try:
            value, end = decoder.raw_decode(raw, start)
        except ValueError:
            position = start + 1
            continue
        try:
            return GeneratedContent.model_validate(value)
        except ValidationError:
            position = end
    raise ValueError("Invalid lesson structure")


def tokens(text: str):
    return " ".join(WORDS.findall(text.casefold()))


def quality_notes(target, outline, sentences, dialogue):
    notes = []
    if not 3 <= len(outline) <= 6:
        notes.append("课堂大纲建议有 3–6 个环节。")
    total = sum(section.minutes for section in outline)
    if abs(total - target.duration_minutes) > max(2, target.duration_minutes * 0.1):
        notes.append(f"大纲合计 {total} 分钟，与课时 {target.duration_minutes} 分钟有偏差。")
    if len(sentences) != 3:
        notes.append("建议安排 3 句跟读句。")
    if not 2 <= len(dialogue) <= 4:
        notes.append("对话建议为 2–4 行。")
    vocabulary = [tokens(word) for word in target.vocabulary]
    patterns = [
        re.compile(r"^" + r".*".join(re.escape(tokens(part)) for part in re.split(r"_{2,}", pattern)))
        for pattern in target.patterns if tokens(pattern)
    ]
    for number, sentence in enumerate(sentences, 1):
        normalized = tokens(sentence)
        if len(normalized.split()) > 6:
            notes.append(f"第 {number} 句跟读句超过 6 个词。")
        if not (
            any(word and f" {word} " in f" {normalized} " for word in vocabulary)
            or any(pattern.search(normalized) for pattern in patterns)
        ):
            notes.append(f"第 {number} 句跟读句可能未覆盖本课词汇或句型。")
    return notes


def mock_content(target: LessonInput):
    word = target.vocabulary[0]
    vocabulary = "、".join(target.vocabulary[:4])
    pattern = target.patterns[0] if target.patterns else f"I can say {word}."
    sound = "、".join(target.sound_focus) if target.sound_focus else "本课单词的读音"
    sentences = list(dict.fromkeys(
        re.sub(r"_{2,}", word, line)
        for line in target.patterns
    ))[:3]
    for entry in target.vocabulary[:3]:
        if len(sentences) == 3:
            break
        sentences.append(f"I can say {entry}.")
    sentences.extend([f"Please say {word}.", f"Can you say {word}?"][:3 - len(sentences)])
    minutes = [target.duration_minutes // 3] * 2
    minutes.append(target.duration_minutes - sum(minutes))
    activities = [
        ("词汇热身", f"出示词卡并轮流朗读：{vocabulary}。"),
        ("示范跟读", f"先听再跟读，留意{sound[:280]}。"),
        ("结对练习", f"两人轮流读或用这个句型造句：{pattern}"),
    ]
    return GeneratedContent.model_validate({
        "outline": [
            {"title": title, "minutes": length, "activity": activity}
            for (title, activity), length in zip(activities, minutes)
        ],
        "sentences": [
            {"text": sentence[:140], "translation": ""}
            for sentence in sentences
        ],
        "dialogue": [
            {"speaker": "A", "text": f"Can you say {word}?", "translation": "你会说这个词吗？"},
            {"speaker": "B", "text": f"Yes, {word}.", "translation": "是的。"},
        ],
    })


def request_content(settings, target, call):
    with OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
    ) as client:
        response = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": target.model_dump_json(exclude={"class_id"})},
            ],
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=1600,
        )
    call.request_id = response._request_id or response.id
    if response.usage:
        call.input_tokens = response.usage.prompt_tokens
        call.output_tokens = response.usage.completion_tokens
    return (response.choices[0].message.content or "") if response.choices else ""


def generate(settings, target, record):
    if settings.fake_models:
        return mock_content(target)
    if not settings.deepseek_api_key:
        raise AppError(503, "MODEL_UNAVAILABLE", "请先配置 DeepSeek 凭证。")

    for retry in range(settings.model_max_retries + 1):
        call = Call(settings.deepseek_model, retry=retry)
        started = time.monotonic()
        try:
            raw = request_content(settings, target, call)
            try:
                result = parse_content(raw)
            except ValueError:
                call.structure = "不合规"
                call.error = "MODEL_OUTPUT_INVALID"
                continue
            call.structure = "重试后合规" if retry else "首测合规"
            call.result = (
                "瑕疵待打分"
                if quality_notes(target, result.outline, [line.text for line in result.sentences], result.dialogue)
                else "通过"
            )
            return result
        except APIStatusError as error:
            call.request_id = error.request_id
            call.error = f"HTTP_{error.status_code}"
            if error.status_code not in (408, 429) and error.status_code < 500:
                break
        except APIConnectionError:
            call.error = "MODEL_CONNECTION_ERROR"
        except Exception:
            call.error = "MODEL_UNAVAILABLE"
            break
        finally:
            call.seconds = round(time.monotonic() - started, 3)
            record("generate", call)
    if call.error == "MODEL_OUTPUT_INVALID":
        raise AppError(502, call.error, "生成结果格式不完整，请重新生成。")
    raise AppError(503, "MODEL_UNAVAILABLE", "暂时无法连接备课模型，请检查配置或稍后重试。")


def mock_audio():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"".join(
            struct.pack("<h", int(3500 * math.sin(2 * math.pi * 440 * sample / 8000)))
            for sample in range(2000)
        ))
    return buffer.getvalue(), "audio/wav"


def request_audio(settings, text, timeout, call):
    profile = HttpProfile(endpoint="tts.tencentcloudapi.com", reqTimeout=timeout)
    client = tts_client.TtsClient(
        credential.Credential(settings.tencentcloud_secret_id, settings.tencentcloud_secret_key),
        settings.tts_region,
        ClientProfile(httpProfile=profile),
    )
    request = models.TextToVoiceRequest()
    request.Text = text
    request.SessionId = uuid4().hex
    request.PrimaryLanguage = 2
    request.VoiceType = settings.tts_voice_type
    request.Speed = settings.tts_speed
    request.SampleRate = 16000
    request.Codec = "mp3"
    response = client.TextToVoice(request)
    call.request_id = response.RequestId
    return checked_mp3(base64.b64decode(response.Audio, validate=True))


def checked_mp3(audio):
    is_mp3 = audio.startswith(b"ID3") or (len(audio) > 2 and audio[0] == 255 and audio[1] & 224 == 224)
    if not is_mp3 or not 32 <= len(audio) <= MAX_AUDIO_BYTES:
        raise ValueError("Unexpected audio")
    return audio, "audio/mpeg"


def request_aihubmix_audio(settings, text, timeout, call):
    deadline = time.monotonic() + timeout
    with OpenAI(
        api_key=settings.aihubmix_api_key,
        base_url=settings.aihubmix_base_url,
        timeout=timeout,
        max_retries=0,
    ) as client, client.audio.speech.with_streaming_response.create(
        model=settings.aihubmix_tts_model,
        voice=settings.aihubmix_tts_voice,
        input=text,
        response_format="mp3",
        speed=settings.aihubmix_tts_speed,
    ) as response:
        call.request_id = response.headers.get("x-request-id")
        audio = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() >= deadline:
                raise TimeoutError
            if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                raise ValueError("Unexpected audio size")
            audio.extend(chunk)
    return checked_mp3(bytes(audio))


def synthesize(settings, text, deadline, record):
    if settings.fake_models:
        return mock_audio()
    if not settings.tts_credentials_ready:
        provider = "AIHubMix" if settings.tts_provider == "aihubmix" else "腾讯云"
        raise AppError(503, "TTS_UNAVAILABLE", f"请先配置{provider}语音合成凭证。")

    request = request_aihubmix_audio if settings.tts_provider == "aihubmix" else request_audio
    for retry in range(settings.tts_max_retries + 1):
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            break
        call = Call(settings.tts_model_label, retry=retry)
        started = time.monotonic()
        try:
            result = request(settings, text, min(settings.tts_timeout_seconds, remaining), call)
            call.structure = "MP3 合规"
            call.result = "通过"
            return result
        except TencentCloudSDKException as error:
            call.request_id = error.get_request_id()
            call.error = error.get_code() or "TTS_UNAVAILABLE"
            if not call.error.startswith(("InternalError", "RequestLimitExceeded", "ClientNetworkError")):
                break
        except APIStatusError as error:
            call.request_id = error.request_id
            call.error = f"HTTP_{error.status_code}"
            if error.status_code not in (408, 429) and error.status_code < 500:
                break
        except (APIConnectionError, TimeoutError):
            call.error = "TTS_CONNECTION_ERROR"
        except ValueError:
            call.error = "TTS_AUDIO_INVALID"
        except Exception:
            call.error = "TTS_UNAVAILABLE"
        finally:
            call.seconds = round(time.monotonic() - started, 3)
            record("tts", call)
    raise AppError(503, "TTS_UNAVAILABLE", "示范音频生成失败，作业仍保留为待发布，可稍后重试。")

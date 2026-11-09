import io
import json
import wave

import httpx
import pytest

from app.core.config import Settings
from app.services import ai


def pcm_wav(*, rate=24000, frames=2400, width=2):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setparams((1, width, rate, 0, "NONE", "not compressed"))
        output.writeframes(b"\x01" * frames * width)
    return buffer.getvalue()


def test_checked_wav_preserves_complete_native_24khz_audio():
    audio = pcm_wav()
    assert ai.checked_wav(audio) == (audio, "audio/wav")


@pytest.mark.parametrize("audio", [
    b"",
    b"RIFF\x00\x00\x00\x00WAVEinvalid",
    pcm_wav()[:-2],
    pcm_wav(frames=0),
    pcm_wav(rate=96000),
    pcm_wav(width=1),
    pcm_wav(rate=8000, frames=8000 * 31),
    b"x" * (ai.MAX_AUDIO_BYTES + 1),
])
def test_checked_wav_rejects_invalid_or_unreasonable_audio(audio):
    with pytest.raises(ValueError):
        ai.checked_wav(audio)


def test_checked_wav_rejects_truncated_pcm_even_with_matching_riff_size():
    audio = bytearray(pcm_wav()[:-2])
    audio[4:8] = (len(audio) - 8).to_bytes(4, "little")
    with pytest.raises(ValueError, match="Incomplete WAV"):
        ai.checked_wav(bytes(audio))


@pytest.mark.parametrize("model", ["gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"])
def test_gemini_tts_uses_wav_and_instructions_without_speed(monkeypatch, model):
    settings = Settings(
        tts_provider="aihubmix", aihubmix_api_key="test-only", aihubmix_tts_model=model,
        aihubmix_tts_voice="Kore", aihubmix_tts_instructions="Read exactly, gently and slowly.",
    )
    audio = pcm_wav()

    def respond(request):
        body = json.loads(request.content)
        assert body == {
            "model": model, "voice": "Kore", "input": "Hello, turtle!",
            "response_format": "wav", "instructions": settings.aihubmix_tts_instructions,
        }
        return httpx.Response(200, content=audio)

    openai = ai.OpenAI
    monkeypatch.setattr(ai, "OpenAI", lambda **kwargs: openai(
        http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs,
    ))
    assert ai.request_aihubmix_audio(settings, "Hello, turtle!", 10, ai.Call(model)) == (audio, "audio/wav")


def test_gemini_tts_rejects_oversized_stream(monkeypatch):
    settings = Settings(tts_provider="aihubmix", aihubmix_api_key="test-only")
    openai = ai.OpenAI
    transport = httpx.MockTransport(lambda _: httpx.Response(
        200, content=b"x" * (ai.MAX_AUDIO_BYTES + 1),
    ))
    monkeypatch.setattr(ai, "OpenAI", lambda **kwargs: openai(
        http_client=httpx.Client(transport=transport), **kwargs,
    ))
    with pytest.raises(ValueError, match="Unexpected audio size"):
        ai.request_aihubmix_audio(settings, "Hello!", 10, ai.Call(settings.aihubmix_tts_model))

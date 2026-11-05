import io
import wave
from array import array
from math import sqrt
from sys import byteorder

from app.core.errors import AppError

MAX_UPLOAD_BYTES = 2_000_000
SAMPLE_RATE = 16_000


def normalize_wav(upload: bytes) -> tuple[bytes, float, bool]:
    """Accept only PCM WAV and discard everything except the audio samples."""
    try:
        with wave.open(io.BytesIO(upload), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ValueError
            frame_count = source.getnframes()
            if not SAMPLE_RATE // 5 <= frame_count <= SAMPLE_RATE * 30:
                raise ValueError
            pcm = source.readframes(frame_count)
            if len(pcm) != frame_count * 2:
                raise ValueError
    except (ValueError, EOFError, wave.Error):
        raise AppError(422, "INVALID_AUDIO", "请提交 0.2–30 秒的 16 kHz 单声道 PCM WAV 录音。") from None

    samples = array("h", pcm)
    if byteorder != "little":
        samples.byteswap()
    rms = sqrt(sum(sample * sample for sample in samples) / frame_count)
    clipped = sum(abs(sample) >= 32760 for sample in samples) > frame_count * 0.01

    normalized = io.BytesIO()
    with wave.open(normalized, "wb") as target:
        target.setparams((1, 2, SAMPLE_RATE, frame_count, "NONE", "not compressed"))
        target.writeframes(pcm)
    return normalized.getvalue(), rms, clipped

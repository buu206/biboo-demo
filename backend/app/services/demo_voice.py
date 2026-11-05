"""Use a consistent macOS English voice for the local demo."""

from hashlib import sha256
from pathlib import Path
from subprocess import DEVNULL, SubprocessError, run
from tempfile import TemporaryDirectory
import wave

from app.core.errors import AppError


def speak(directory: Path, text: str) -> Path:
    # Brackets can mark embedded speech commands in macOS voices.
    spoken = " ".join(text.translate(str.maketrans("[]_", "   ")).split())
    key = sha256(f"samantha-150:{spoken}".encode()).hexdigest()
    path = directory / f"{key}.wav"
    if path.is_file():
        return path
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=directory) as temporary:
            output = Path(temporary) / "example.wav"
            run(
                [
                    "/usr/bin/say", "-v", "Samantha", "-r", "150",
                    "--file-format=WAVE", "--data-format=LEI16@22050",
                    "-o", str(output), "-f", "-",
                ],
                input=spoken, encoding="utf-8", stdout=DEVNULL, stderr=DEVNULL,
                check=True, timeout=8,
            )
            with wave.open(str(output)) as clip:
                if not clip.getnframes():
                    raise ValueError("Empty speech clip")
            output.replace(path)
        return path
    except (OSError, SubprocessError, EOFError, ValueError, wave.Error) as error:
        raise AppError(503, "DEMO_VOICE_UNAVAILABLE", "暂时无法播放英文示范。") from error

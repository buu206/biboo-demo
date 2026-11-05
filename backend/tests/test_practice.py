import io
import math
import re
import struct
import wave
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import create_teacher
from app.core.config import Settings
from app.main import create_app
from app.models import PracticeAttempt
from app.services import practice
from app.services.oral_provider import OralPhone, OralResult, OralWord

PREFIX = "/api/v1"


def wav_audio(rate=16_000, seconds=0.5, amplitude=9_000):
    frame_count = int(rate * seconds)
    cycle = rate // 200
    waveform = b"".join(
        struct.pack("<h", round(amplitude * math.sin(2 * math.pi * sample / cycle)))
        for sample in range(cycle)
    )
    payload = (waveform * math.ceil(frame_count / cycle))[:frame_count * 2]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(payload)
    return buffer.getvalue()


def log_in(client, teacher_name):
    with Session(client.app.state.engine) as db:
        _, code = create_teacher(db, teacher_name)
    response = client.post(f"{PREFIX}/auth/login", json={"invite_code": code})
    assert response.status_code == 200, response.text


def create_item(client, *, published=True):
    classroom = client.post(f"{PREFIX}/classes", json={"name": "评测测试班"})
    assert classroom.status_code == 201, classroom.text
    lesson = client.post(
        f"{PREFIX}/lessons",
        json={
            "class_id": classroom.json()["id"],
            "topic": "Think and thank",
            "age_band": "7–9 岁",
            "duration_minutes": 25,
            "vocabulary": ["think", "thank", "three"],
            "sound_focus": ["th"],
        },
    )
    assert lesson.status_code == 201, lesson.text
    url = f"{PREFIX}/lessons/{lesson.json()['id']}"
    generated = client.post(f"{url}/generate")
    assert generated.status_code == 200, generated.text
    result = generated.json()
    if published:
        response = client.post(
            f"{url}/publish", json={"confirm": True, "revision": result["revision"]},
        )
        assert response.status_code == 200, response.text
        result = response.json()
    return next(item["id"] for item in result["items"] if item["text"] == "think")


def attempts_url(item_id):
    return f"{PREFIX}/practice/items/{item_id}/attempts"


def submit(
    client, item_id, learner_id, *, drill=False, key=None,
    recording=None, content_type="audio/wav",
):
    return client.post(
        attempts_url(item_id),
        params={"learner_id": str(learner_id), "drill": str(drill).lower()},
        headers={"Content-Type": content_type, "Idempotency-Key": str(key or uuid4())},
        content=wav_audio() if recording is None else recording,
    )


def history(client, item_id, learner_id):
    return client.get(attempts_url(item_id), params={"learner_id": str(learner_id)})


def matched(reference, *, practice_needed=False):
    phone_accuracy = 40 if practice_needed else 96
    words = tuple(
        OralWord(word, True, (OralPhone("θ", phone_accuracy), OralPhone("ɪ", 96)))
        for word in re.findall(r"[A-Za-z]+", reference.lower())
    )
    return OralResult(75 if practice_needed else 96, 1.0, words)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, fake_models=True)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url="http://localhost") as test_client:
        log_in(test_client, "评测测试老师")
        yield test_client


def test_good_attempt_is_replayed_and_remains_available_after_restart(settings, monkeypatch):
    calls = []

    def evaluate(_settings, _audio, reference):
        calls.append(reference)
        return matched(reference)

    monkeypatch.setattr(practice, "evaluate", evaluate)
    learner_id, key = uuid4(), uuid4()
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        log_in(client, "评测测试老师")
        item_id = create_item(client)
        response = submit(client, item_id, learner_id, key=key)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["decision"] == "good"
        assert result["round"] == 0
        assert result["reference"] == "think"
        assert result["feedback"]
        assert result["drill"] is None
        assert "accuracy" not in result and "score" not in result
        assert submit(client, item_id, learner_id, key=key).json() == result
        collision = submit(
            client, item_id, learner_id, key=key, recording=wav_audio(amplitude=8_000),
        )
        assert collision.status_code == 409, collision.text
        cookies = dict(client.cookies)
    with TestClient(create_app(settings), base_url="http://localhost", cookies=cookies) as restarted:
        assert history(restarted, item_id, learner_id).json() == [result]
        assert submit(restarted, item_id, learner_id, key=key).json() == result
        with Session(restarted.app.state.engine) as db:
            recording = settings.data_dir / db.get(PracticeAttempt, result["id"]).audio_path
            assert recording.read_bytes() == wav_audio()
    assert calls == ["think"]


def test_concurrent_retries_do_not_duplicate_the_provider_call(client, monkeypatch):
    started, release = Event(), Event()
    calls = []

    def evaluate(_settings, _audio, reference):
        calls.append(reference)
        started.set()
        assert release.wait(timeout=5)
        return matched(reference)

    monkeypatch.setattr(practice, "evaluate", evaluate)
    item_id, learner_id, key = create_item(client), uuid4(), uuid4()
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(submit, client, item_id, learner_id, key=key)
        try:
            assert started.wait(timeout=5)
            duplicate = submit(client, item_id, learner_id, key=key)
            assert duplicate.status_code == 409, duplicate.text
        finally:
            release.set()
        response = pending.result(timeout=5)
    assert response.status_code == 200, response.text
    assert submit(client, item_id, learner_id, key=key).json() == response.json()
    assert calls == ["think"]


def test_unresolved_issue_offers_at_most_two_drill_rounds(client, monkeypatch):
    references = []

    def evaluate(_settings, _audio, reference):
        references.append(reference)
        return matched(reference, practice_needed=True)

    monkeypatch.setattr(practice, "evaluate", evaluate)
    item_id, learner_id = create_item(client), uuid4()
    results = []
    for round_number in range(3):
        response = submit(client, item_id, learner_id, drill=round_number > 0)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["round"] == round_number
        assert result["feedback"]
        results.append(result)
    assert [result["decision"] for result in results] == ["practice", "practice", "teacher_review"]
    assert results[2]["drill"] is None
    assert references == ["think", results[0]["drill"]["text"], results[1]["drill"]["text"]]
    assert history(client, item_id, learner_id).json() == results
    rejected = submit(client, item_id, learner_id, drill=True)
    assert rejected.status_code == 409, rejected.text
    assert len(references) == 3


def test_third_unsuccessful_original_attempt_goes_to_teacher(client, monkeypatch):
    def evaluate(_settings, _audio, reference):
        return matched(reference, practice_needed=True)

    monkeypatch.setattr(practice, "evaluate", evaluate)
    item_id, learner_id = create_item(client), uuid4()
    for expected in ("practice", "practice", "teacher_review"):
        response = submit(client, item_id, learner_id)
        assert response.status_code == 200, response.text
        assert response.json()["decision"] == expected
        assert response.json()["round"] == 0
    assert response.json()["drill"] is None


def test_uncertain_evaluation_routes_to_teacher_without_exercise(client, monkeypatch):
    def evaluate(_settings, _audio, _reference):
        return OralResult(None, None, ())

    monkeypatch.setattr(practice, "evaluate", evaluate)
    item_id, learner_id = create_item(client), uuid4()
    response = submit(client, item_id, learner_id)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["decision"] == "teacher_review"
    assert result["feedback"]
    assert result["drill"] is None
    assert history(client, item_id, learner_id).json() == [result]


def test_silent_recording_routes_to_teacher_without_calling_provider(client, monkeypatch):
    def unexpected_evaluation(*_args):
        pytest.fail("A silent recording does not need provider evaluation")

    monkeypatch.setattr(practice, "evaluate", unexpected_evaluation)
    item_id, learner_id = create_item(client), uuid4()
    response = submit(client, item_id, learner_id, recording=wav_audio(amplitude=0))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["decision"] == "teacher_review"
    assert result["drill"] is None
    assert history(client, item_id, learner_id).json() == [result]


def test_attempts_are_scoped_to_published_items_and_their_teachers(client, monkeypatch):
    monkeypatch.setattr(practice, "evaluate", lambda _settings, _audio, text: matched(text))
    learner_id = uuid4()
    draft_item = create_item(client, published=False)
    assert submit(client, draft_item, learner_id).status_code == 404
    published_item = create_item(client)
    assert submit(client, published_item, learner_id).status_code == 200
    assert history(client, published_item, uuid4()).json() == []

    logout = client.post(f"{PREFIX}/auth/logout")
    assert logout.status_code == 204
    assert submit(client, published_item, learner_id).status_code == 401
    assert history(client, published_item, learner_id).status_code == 401

    log_in(client, "另一个评测测试老师")
    assert submit(client, published_item, learner_id).status_code == 404
    assert history(client, published_item, learner_id).status_code == 404


@pytest.mark.parametrize(
    ("recording", "content_type", "status"),
    [
        (b"", "audio/wav", 422),
        (b"RIFF\x00\x00\x00\x00WAVEinvalid", "audio/wav", 422),
        (wav_audio(rate=8_000), "audio/wav", 422),
        (wav_audio(seconds=31), "audio/wav", 422),
        (b"x" * 2_000_001, "audio/wav", 413),
        (wav_audio(), "application/json", 415),
    ],
    ids=["empty", "forged", "wrong-sample-rate", "too-long", "too-large", "wrong-content-type"],
)
def test_rejects_invalid_wav_before_any_assessment(client, monkeypatch, recording, content_type, status):
    def unexpected_evaluation(*_args):
        pytest.fail("Invalid audio must not be sent to the provider")

    monkeypatch.setattr(practice, "evaluate", unexpected_evaluation)
    item_id, learner_id = create_item(client), uuid4()
    response = submit(
        client, item_id, learner_id, recording=recording, content_type=content_type,
    )
    assert response.status_code == status, response.text
    assert history(client, item_id, learner_id).json() == []

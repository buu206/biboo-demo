import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import create_teacher
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import Asset, AuditLog
from app.schemas import LessonInput
from app.services import ai

PREFIX = "/api/v1"


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, fake_models=True)
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost") as client:
        with Session(app.state.engine) as db:
            _, code = create_teacher(db, "老师 A")
            _, other = create_teacher(db, "老师 B")
        login = client.post(f"{PREFIX}/auth/login", json={"invite_code": code})
        assert login.status_code == 200 and "HttpOnly" in login.headers["set-cookie"]
        classroom = client.post(f"{PREFIX}/classes", json={"name": "周六班"}).json()
        assert "id" in classroom
        target = {
            "class_id": classroom["id"], "topic": "家庭成员", "age_band": "7–9 岁",
            "duration_minutes": 25, "vocabulary": ["mother", "father", "sister"],
            "patterns": ["This is my ___."], "sound_focus": ["th"],
        }
        yield app, client, target, other


def create(client, target):
    response = client.post(f"{PREFIX}/lessons", json=target)
    assert response.status_code == 201, response.text
    return f"{PREFIX}/lessons/{response.json()['id']}"


def generate(client, url):
    response = client.post(f"{url}/generate")
    assert response.status_code == 200, response.text
    return response.json()


def publish(client, url, lesson):
    return client.post(f"{url}/publish", json={"confirm": True, "revision": lesson["revision"]})


def edit_request(lesson):
    return {
        "revision": lesson["revision"], "outline": lesson["outline"]["sections"],
        "items": [{key: row[key] for key in ("id", "text", "translation")} for row in lesson["items"]],
    }


def test_parser_accepts_fences_and_surrounding_text(setup):
    _, _, target, _ = setup
    content = ai.mock_content(LessonInput.model_validate(target))
    assert ai.parse_content(f"提要 {{ignored}}\n```json\n{content.model_dump_json()}\n```\n完成") == content


def test_invalid_structure_retries_then_reports_uniform_error(setup, monkeypatch):
    app, client, target, _ = setup
    app.state.settings.fake_models = False
    app.state.settings.deepseek_api_key = "test-only"
    attempts = []

    def bad_output(*_args):
        attempts.append(1)
        return '{"outline":[]}'

    monkeypatch.setattr(ai, "request_content", bad_output)
    url = create(client, target)
    response = client.post(f"{url}/generate")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"
    assert len(attempts) == 2
    assert client.get(url).json()["status"] == "draft"
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 2


def test_first_invalid_output_can_recover(setup, monkeypatch):
    app, client, target, _ = setup
    app.state.settings.fake_models = False
    app.state.settings.deepseek_api_key = "test-only"
    content = ai.mock_content(LessonInput.model_validate(target)).model_dump_json()
    output = iter(["{}", content])
    monkeypatch.setattr(ai, "request_content", lambda *_args: next(output))
    lesson = generate(client, create(client, target))
    assert lesson["status"] == "generated"


def test_missing_key_and_sdk_init_failure_are_safe(setup, monkeypatch):
    app, client, target, _ = setup
    app.state.settings.fake_models = False
    app.state.settings.deepseek_api_key = ""
    url = create(client, target)
    assert client.post(f"{url}/generate").json()["error"]["code"] == "MODEL_UNAVAILABLE"
    app.state.settings.deepseek_api_key = "test-only"

    def fail(**_kwargs):
        raise RuntimeError("private details")

    monkeypatch.setattr(ai, "OpenAI", fail)
    response = client.post(f"{url}/generate")
    assert response.status_code == 503
    assert "private details" not in response.text


def test_exact_vocabulary_and_soft_quality_warning(setup, monkeypatch):
    _, client, target, _ = setup
    content = ai.mock_content(LessonInput.model_validate(target))
    content.sentences[0].text = "My mother is reading a very long book today."
    monkeypatch.setattr(ai, "mock_content", lambda _target: content)
    url = create(client, target)
    lesson = generate(client, url)
    assert [item["text"] for item in lesson["items"] if item["kind"] == "word"] == target["vocabulary"]
    assert any("超过 6 个词" in note for note in lesson["quality_notes"])
    assert len(generate(client, url)["items"]) == len(lesson["items"])


def test_requires_login(setup):
    _, client, _, _ = setup
    response = client.post(f"{PREFIX}/auth/logout")
    assert response.status_code == 204
    assert client.get(f"{PREFIX}/classes").json()["error"]["code"] == "UNAUTHORIZED"


def test_owner_isolation_including_audio(setup):
    _, client, target, other = setup
    url = create(client, target)
    published = publish(client, url, generate(client, url)).json()
    asset = published["items"][0]["audio_asset_id"]
    assert client.post(f"{PREFIX}/auth/login", json={"invite_code": other}).status_code == 200
    assert client.get(f"{PREFIX}/classes").json() == []
    assert client.get(f"{PREFIX}/lessons").json() == []
    assert client.get(url).status_code == 404
    assert client.post(f"{url}/generate").status_code == 404
    assert client.post(f"{PREFIX}/lessons", json=target).status_code == 404
    assert client.get(f"{PREFIX}/assets/{asset}").status_code == 404


def test_edit_publish_audio_and_idempotent_retry(setup):
    _, client, target, _ = setup
    url = create(client, target)
    assert client.post(f"{url}/publish", json={"confirm": True, "revision": 0}).status_code == 409
    lesson = generate(client, url)
    changes = edit_request(lesson)
    changes["items"][3]["text"] = "This is my mother."
    changes["outline"][0]["title"] = "复习家庭成员"
    updated = client.put(f"{url}/content", json=changes)
    assert updated.status_code == 200, updated.text
    saved = client.get(url).json()
    assert saved["items"][3]["text"] == "This is my mother."
    assert saved["outline"]["sections"][0]["title"] == "复习家庭成员"
    assert publish(client, url, lesson).status_code == 409
    assert client.post(f"{url}/publish", json={"confirm": False, "revision": saved["revision"]}).status_code == 422
    response = publish(client, url, saved)
    assert response.status_code == 200, response.text
    published = response.json()
    assert published["status"] == "published"
    assert publish(client, url, saved).json() == published
    assert client.put(f"{url}/content", json=edit_request(published)).status_code == 409
    for item in published["items"]:
        audio = client.get(f"{PREFIX}/assets/{item['audio_asset_id']}")
        assert audio.status_code == 200 and audio.content.startswith(b"RIFF")
        assert audio.headers["content-type"] == "audio/wav"


def test_tts_failure_rolls_back_files_and_database(setup, monkeypatch):
    app, client, target, _ = setup
    url = create(client, target)
    lesson = generate(client, url)
    audio = ai.mock_audio()

    def fails_on_second(_settings, text, *_args):
        if text == target["vocabulary"][0]:
            return audio
        raise AppError(503, "TTS_UNAVAILABLE", "测试语音合成失败")

    monkeypatch.setattr(ai, "synthesize", fails_on_second)
    assert publish(client, url, lesson).json()["error"]["code"] == "TTS_UNAVAILABLE"
    assert client.get(url).json() == lesson
    assert not list(app.state.settings.data_dir.rglob("*.wav"))
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Asset)) == 0


MP3_FRAME = b"\xff\xfb\x90\x64" + bytes(413)


def mock_aihubmix(monkeypatch, respond):
    openai = ai.OpenAI

    def client(**kwargs):
        return openai(http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs)

    monkeypatch.setattr(ai, "OpenAI", client)


def test_aihubmix_publishes_mp3_without_tencent_credentials(setup, monkeypatch):
    app, client, target, _ = setup
    url = create(client, target)
    lesson = generate(client, url)
    settings = app.state.settings
    settings.fake_models = False
    settings.deepseek_api_key = "test-only"
    settings.tts_provider = "aihubmix"
    settings.aihubmix_api_key = "hub-test"
    settings.aihubmix_tts_model = "gpt-4o-mini-tts"
    settings.aihubmix_tts_voice = "coral"
    assert settings.credentials_ready
    spoken = []

    def respond(request):
        assert request.method == "POST"
        assert request.url == httpx.URL("https://aihubmix.com/v1/audio/speech")
        assert request.headers["Authorization"] == "Bearer hub-test"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o-mini-tts"
        assert body["voice"] == "coral"
        assert body["response_format"] == "mp3"
        assert body["speed"] == settings.aihubmix_tts_speed
        spoken.append(body["input"])
        if len(spoken) == 1:
            return httpx.Response(429, json={"error": {"message": "test rate limit"}})
        return httpx.Response(200, content=MP3_FRAME, headers={"x-request-id": "hub-request"})

    mock_aihubmix(monkeypatch, respond)
    response = publish(client, url, lesson)
    assert response.status_code == 200, response.text
    published = response.json()
    assert published["status"] == "published"
    expected_texts = list(dict.fromkeys(item["text"] for item in published["items"]))
    assert spoken == expected_texts[:1] + expected_texts
    audio = client.get(f"{PREFIX}/assets/{published['items'][0]['audio_asset_id']}")
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content == MP3_FRAME
    with Session(app.state.engine) as db:
        events = list(db.scalars(select(AuditLog).where(AuditLog.event == "tts").order_by(AuditLog.id)))
        assert events[0].detail["error"] == "HTTP_429"
        assert events[1].detail["retry"] == 1
        assert events[1].detail["model"] == "AIHubMix gpt-4o-mini-tts"
        assert events[1].detail["request_id"] == "hub-request"
        assert events[1].detail["structure"] == "MP3 合规"


def test_aihubmix_gemini_publishes_wav_with_delivery_instructions(setup, monkeypatch):
    app, client, target, _ = setup
    url = create(client, target)
    lesson = generate(client, url)
    settings = app.state.settings
    settings.fake_models = False
    settings.tts_provider = "aihubmix"
    settings.aihubmix_api_key = "hub-test"
    settings.aihubmix_tts_instructions = "Read exactly. Speak warmly and slightly slowly."
    wav, _ = ai.mock_audio()
    spoken = []

    def respond(request):
        assert request.url == httpx.URL("https://aihubmix.com/v1/audio/speech")
        body = json.loads(request.content)
        assert body["model"] == "gemini-3.8-flash-tts"
        assert body["voice"] == "Sulafat"
        assert body["response_format"] == "wav"
        assert body["instructions"] == settings.aihubmix_tts_instructions
        assert "speed" not in body
        spoken.append(body["input"])
        return httpx.Response(200, content=wav, headers={"x-request-id": "gemini-request"})

    mock_aihubmix(monkeypatch, respond)
    response = publish(client, url, lesson)
    assert response.status_code == 200, response.text
    published = response.json()
    assert spoken == list(dict.fromkeys(item["text"] for item in published["items"]))
    audio = client.get(f"{PREFIX}/assets/{published['items'][0]['audio_asset_id']}")
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content == wav
    with Session(app.state.engine) as db:
        assets = list(db.scalars(select(Asset)))
        assert assets and all(asset.path.endswith(".wav") for asset in assets)
        events = list(db.scalars(select(AuditLog).where(AuditLog.event == "tts")))
        assert events and all(event.detail["structure"] == "WAV 合规" for event in events)
        assert events[0].detail["request_id"] == "gemini-request"


@pytest.mark.parametrize("tts_model, extension", [
    ("gpt-4o-mini-tts", "mp3"), ("gemini-3.8-flash-tts", "wav"),
])
def test_aihubmix_invalid_audio_rolls_back_publication(setup, monkeypatch, tts_model, extension):
    app, client, target, _ = setup
    url = create(client, target)
    lesson = generate(client, url)
    settings = app.state.settings
    settings.fake_models = False
    settings.tts_provider = "aihubmix"
    settings.aihubmix_api_key = "hub-test"
    settings.aihubmix_tts_model = tts_model
    settings.aihubmix_tts_voice = "coral" if extension == "mp3" else "Sulafat"
    valid_audio = MP3_FRAME if extension == "mp3" else ai.mock_audio()[0]

    def respond(request):
        if json.loads(request.content)["input"] == target["vocabulary"][0]:
            return httpx.Response(200, content=valid_audio)
        return httpx.Response(200, json={"error": "no audio returned"})

    mock_aihubmix(monkeypatch, respond)
    response = publish(client, url, lesson)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TTS_UNAVAILABLE"
    assert client.get(url).json() == lesson
    assert not list(settings.data_dir.rglob(f"*.{extension}"))
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Asset)) == 0


def test_aihubmix_requires_selected_provider_key(setup):
    app, client, target, _ = setup
    url = create(client, target)
    lesson = generate(client, url)
    settings = app.state.settings
    settings.fake_models = False
    settings.tts_provider = "aihubmix"
    settings.deepseek_api_key = "test-only"
    settings.tencentcloud_secret_id = "tencent-id"
    settings.tencentcloud_secret_key = "tencent-key"
    assert not settings.credentials_ready
    response = publish(client, url, lesson)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TTS_UNAVAILABLE"
    assert "AIHubMix" in response.json()["error"]["message"]
    assert client.get(url).json() == lesson


@pytest.mark.parametrize("words", [[], ["cat"] * 13])
def test_invalid_vocabulary(setup, words):
    _, client, target, _ = setup
    response = client.post(f"{PREFIX}/lessons", json={**target, "vocabulary": words})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_concurrent_publish_cannot_change_reviewed_content(setup, monkeypatch):
    _, client, target, _ = setup
    url = create(client, target)
    lesson = generate(client, url)
    started, resume = Event(), Event()
    audio = ai.mock_audio()

    def slow(*_args):
        started.set()
        assert resume.wait(5)
        return audio

    monkeypatch.setattr(ai, "synthesize", slow)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(publish, client, url, lesson)
        try:
            assert started.wait(5)
            assert client.put(f"{url}/content", json=edit_request(lesson)).status_code == 409
            assert publish(client, url, lesson).status_code == 409
        finally:
            resume.set()
        assert pending.result().status_code == 200


@pytest.mark.parametrize("use_alias", [False, True], ids=["real-path", "aliased-path"])
def test_published_content_and_audio_survive_app_restart(tmp_path, use_alias):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    if use_alias:
        alias = tmp_path / "data-alias"
        alias.symlink_to(data_dir, target_is_directory=True)
        data_dir = alias
    settings = Settings(data_dir=data_dir, fake_models=True)
    with TestClient(create_app(settings)) as client:
        with Session(client.app.state.engine) as db:
            _, code = create_teacher(db, "重启验收")
        assert client.post(f"{PREFIX}/auth/login", json={"invite_code": code}).is_success
        classroom = client.post(f"{PREFIX}/classes", json={"name": "重启验收班"}).json()
        url = create(client, {
            "class_id": classroom["id"], "topic": "Pets", "age_band": "7–9 岁",
            "duration_minutes": 25, "vocabulary": ["cat"],
        })
        published = publish(client, url, generate(client, url)).json()
        audio_url = f"{PREFIX}/assets/{published['items'][0]['audio_asset_id']}"
        audio = client.get(audio_url)
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        before = audio.content
        cookies = dict(client.cookies)
    with TestClient(create_app(settings), cookies=cookies) as restarted:
        assert restarted.get(url).json() == published
        assert restarted.get(audio_url).content == before

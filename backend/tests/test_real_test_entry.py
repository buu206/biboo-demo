import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import database
from app.models import Asset, AuditLog, Classroom, Lesson, PracticeAttempt, Teacher


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "real_test.py"
spec = importlib.util.spec_from_file_location("biboo_real_test_entry", SCRIPT)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def settings_for(tmp_path):
    return Settings(
        data_dir=tmp_path / "manual-demo",
        fake_models=True,
        deepseek_api_key="test-text",
        tts_provider="aihubmix",
        aihubmix_api_key="test-voice",
        tencentcloud_secret_id="test-account",
        tencentcloud_secret_key="test-secret",
        tencent_soe_app_id="123456789",
    )


def test_check_is_real_isolated_and_does_not_leak_or_write(tmp_path, monkeypatch, capsys):
    configured = settings_for(tmp_path)
    monkeypatch.setattr(entry, "PRODUCT", tmp_path)
    monkeypatch.setattr(entry.Settings, "load", classmethod(lambda cls: configured))
    monkeypatch.setattr(entry, "prepare_workspace", lambda _: (_ for _ in ()).throw(AssertionError("check wrote data")))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("check started server")))

    settings = entry.load_real_settings()
    assert settings.fake_models is False
    assert settings.data_dir == tmp_path / "data" / "real-test"
    assert configured.fake_models is True
    assert entry.main(["--check"]) == 0
    output = capsys.readouterr()
    for secret in (configured.deepseek_api_key, configured.aihubmix_api_key,
                   configured.tencentcloud_secret_id, configured.tencentcloud_secret_key,
                   configured.tencent_soe_app_id, entry.LOCAL_INVITE):
        assert secret not in output.out + output.err
    assert not (tmp_path / "data").exists()


def test_missing_required_key_stops_before_startup(tmp_path, monkeypatch, capsys):
    settings = settings_for(tmp_path).model_copy(update={"aihubmix_api_key": " "})
    monkeypatch.setattr(entry, "load_real_settings", lambda: settings)
    monkeypatch.setattr(entry, "prepare_workspace", lambda _: (_ for _ in ()).throw(AssertionError("missing key wrote data")))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("missing key started server")))
    assert entry.main([]) == 2
    assert "AIHUBMIX_API_KEY" in capsys.readouterr().err


def test_startup_seeds_no_lessons_or_model_calls_and_reuses_class(tmp_path, monkeypatch):
    from app.services import ai, oral_provider, practice_feedback

    def forbidden(*args, **kwargs):
        raise AssertionError("startup attempted an external model call")

    monkeypatch.setattr(ai, "generate", forbidden)
    monkeypatch.setattr(ai, "synthesize", forbidden)
    monkeypatch.setattr(practice_feedback, "OpenAI", forbidden)
    # The startup path must never reach the oral provider or any network endpoint.
    monkeypatch.setattr(oral_provider, "create_connection", forbidden)
    settings = settings_for(tmp_path).model_copy(update={"fake_models": False, "data_dir": tmp_path / "real-test"})
    monkeypatch.setattr(entry, "load_real_settings", lambda: settings)
    calls = []

    def capture_run(app, **kwargs):
        calls.append(kwargs)
        with TestClient(app) as client:
            assert app.state.settings.fake_models is False
            response = client.post("/api/v1/auth/login", json={"invite_code": entry.LOCAL_INVITE})
            assert response.status_code == 200
            classes = client.get("/api/v1/classes").json()
            assert [row["name"] for row in classes] == [entry.CLASS_NAME]

    monkeypatch.setattr(entry.uvicorn, "run", capture_run)
    assert entry.main([]) == 0
    assert entry.main([]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 18768}] * 2
    engine = database(settings.data_dir)
    try:
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Teacher)) == 1
            assert db.scalar(select(func.count()).select_from(Classroom)) == 1
            for model in (Lesson, PracticeAttempt, Asset, AuditLog):
                assert db.scalar(select(func.count()).select_from(model)) == 0
    finally:
        engine.dispose()

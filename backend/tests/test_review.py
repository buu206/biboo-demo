from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import AuditLog
from test_practice import create_item, log_in, submit, wav_audio

PREFIX = "/api/v1/review"


def test_review_audio_feedback_and_progress_survive_restart(tmp_path):
    settings = Settings(data_dir=tmp_path, fake_models=True)
    learner_id = uuid4()
    original = wav_audio(amplitude=0)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        log_in(client, "Review teacher")
        item_id = create_item(client)
        attempt = submit(client, item_id, learner_id, recording=original).json()
        classroom = client.get("/api/v1/classes").json()[0]
        dashboard = f"{PREFIX}/classes/{classroom['id']}/dashboard"
        result = client.get(dashboard).json()
        assert result["counts"]["pending_review"] == 1
        pending = result["queue"][0]
        assert pending["id"] == attempt["id"]
        assert pending["review"] is None
        assert client.get(pending["audio_url"]).content == original
        assert result["students"][0]["status"] == "pending_review"

        path = f"{PREFIX}/attempts/{attempt['id']}"
        payload = {"verdict": "practice", "note": "先慢读 think", "focus": "th"}
        saved = client.put(path, json=payload)
        assert saved.status_code == 200, saved.text
        assert client.put(path, json=payload).json() == saved.json()
        assert saved.json()["review"]["note"] == payload["note"]
        voice = wav_audio(amplitude=2000)
        feedback = client.put(f"{path}/feedback-audio", headers={"Content-Type": "audio/wav"}, content=voice)
        assert feedback.status_code == 200, feedback.text
        cookies = dict(client.cookies)

    with TestClient(create_app(settings), base_url="http://localhost", cookies=cookies) as restarted:
        result = restarted.get(dashboard).json()
        assert result["counts"]["pending_review"] == 0 and result["counts"]["reviewed"] == 1
        assert result["students"][0]["status"] == "in_progress"
        assert result["suggestion"]["vocabulary"] == ["think"]
        assert result["suggestion"]["sound_focus"] == ["th"]
        assert result["reminder"]
        review = result["recent_reviews"][0]["review"]
        assert review["verdict"] == "practice"
        assert restarted.get(review["audio_url"]).content == voice
        with Session(restarted.app.state.engine) as db:
            assert db.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.event == "practice_reviewed",
            )) == 1
        assert restarted.put(path, json={"verdict": "good"}).status_code == 200
        refreshed = restarted.get(dashboard).json()
        assert refreshed["students"][0]["completed_items"] == 1
        assert refreshed["suggestion"] is None


def test_review_is_scoped_to_own_teacher(tmp_path):
    settings = Settings(data_dir=tmp_path, fake_models=True)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        log_in(client, "Teacher A")
        item_id = create_item(client)
        attempt = submit(client, item_id, uuid4(), recording=wav_audio(amplitude=0)).json()
        class_id = client.get("/api/v1/classes").json()[0]["id"]
        path = f"{PREFIX}/attempts/{attempt['id']}"
        assert client.put(path, json={"verdict": "good"}).status_code == 200
        log_in(client, "Teacher B")
        assert client.get(f"{PREFIX}/classes/{class_id}/dashboard").status_code == 404
        assert client.get(f"{path}/audio").status_code == 404
        assert client.get(f"{path}/feedback-audio").status_code == 404
        assert client.put(path, json={"verdict": "practice"}).status_code == 404

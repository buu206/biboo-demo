"""Run Biboo's local, simulated demo with a prepublished exercise."""

import argparse
from io import BytesIO
from pathlib import Path
import sys
import wave

PRODUCT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT / "backend"))

import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import digest
from app.core.config import Settings
from app.main import create_app
from app.models import Teacher

DEMO_CODE = "biboo-demo"
CLASS_NAME = "Biboo 体验班"
TOPIC = "练习 th"
SAMPLE_LEARNER = "00000000-0000-4000-8000-000000000001"
SAMPLE_ATTEMPT = "00000000-0000-4000-8000-000000000002"


def quiet_sample():
    output = BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
        recording.writeframes(bytes(16_000 * 2))
    return output.getvalue()


def seed(app):
    with TestClient(app) as client:
        def api(method, path, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            response.raise_for_status()
            return response.json()

        with Session(app.state.engine) as db:
            invite_hash = digest(DEMO_CODE)
            if db.scalar(select(Teacher.id).where(Teacher.invite_code_hash == invite_hash)) is None:
                db.add(Teacher(name="体验老师", invite_code_hash=invite_hash))
                db.commit()
        api("POST", "/auth/login", json={"invite_code": DEMO_CODE})

        classroom = next((row for row in api("GET", "/classes") if row["name"] == CLASS_NAME), None)
        if classroom is None:
            classroom = api("POST", "/classes", json={"name": CLASS_NAME})
        lessons = api("GET", "/lessons", params={"class_id": classroom["id"]})
        lesson = next((row for row in lessons if row["topic"] == TOPIC), None)
        if lesson is None:
            lesson = api("POST", "/lessons", json={
                "class_id": classroom["id"], "topic": TOPIC, "age_band": "7–9 岁",
                "duration_minutes": 20, "vocabulary": ["think", "three", "thank"],
                "patterns": ["I think ___."], "sound_focus": ["th"],
            })
        else:
            lesson = api("GET", f"/lessons/{lesson['id']}")
        if lesson["status"] == "draft":
            lesson = api("POST", f"/lessons/{lesson['id']}/generate")
        if lesson["status"] == "generated":
            lesson = api("POST", f"/lessons/{lesson['id']}/publish",
                         json={"confirm": True, "revision": lesson["revision"]})
        item = lesson["items"][0]
        path = f"/practice/items/{item['id']}/attempts"
        params = {"learner_id": SAMPLE_LEARNER}
        if not api("GET", path, params=params):
            api("POST", path, params=params, content=quiet_sample(), headers={
                "Content-Type": "audio/wav", "Idempotency-Key": SAMPLE_ATTEMPT,
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    settings = Settings(data_dir=PRODUCT / "data" / "manual-demo", fake_models=True)
    app = create_app(settings)
    seed(app)
    print(f"Biboo Demo http://127.0.0.1:{args.port}/ · 邀请码 {DEMO_CODE}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

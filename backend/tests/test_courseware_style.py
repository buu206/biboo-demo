from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import courseware
from app.core.auth import create_teacher
from app.core.config import Settings
from app.main import create_app
from app.services.courseware_plan import plan_courseware


def test_upload_style_is_validated_and_forwarded_after_authentication(tmp_path, monkeypatch):
    calls = []

    def render(title, source, style, *, lesson=False):
        calls.append((title, source, style, lesson))
        return b"test-deck", 15

    monkeypatch.setattr(courseware, "render_courseware", render)
    with TestClient(create_app(Settings(data_dir=tmp_path, fake_models=True))) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "课件风格测试")
        path = "/api/v1/courseware/pptx"
        params = {"filename": "教学材料.txt", "title": "Sea animals", "style": "children"}
        assert client.post(path, params=params, content=b"octopus, crab").status_code == 401
        assert not calls
        client.post("/api/v1/auth/login", json={"invite_code": invite}).raise_for_status()
        response = client.post(path, params=params, content=b"octopus, crab").raise_for_status()
        assert calls == [("Sea animals", "octopus, crab", "children", False)]
        assert response.headers["x-slide-count"] == "15"
        assert response.headers["x-courseware-style"] == "children"
        assert "%E5%84%BF%E7%AB%A5%E4%BA%92%E5%8A%A8.pptx" in response.headers["content-disposition"]

        invalid = client.post(path, params={**params, "style": "unsupported"}, content=b"octopus")
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
        assert len(calls) == 1

        client.post(path, params={"filename": "words.txt"}, content=b"octopus").raise_for_status()
        assert calls[-1][2] == "standard"


def test_lesson_download_uses_selected_style_and_keeps_ownership(tmp_path, monkeypatch):
    calls = []

    def render(title, source, style, *, lesson=False):
        calls.append((title, source, style, lesson))
        return b"test-deck", 15

    monkeypatch.setattr(courseware, "render_courseware", render)
    with TestClient(create_app(Settings(data_dir=tmp_path, fake_models=True))) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "本课课件测试")
            _, other_invite = create_teacher(db, "另一位老师")
        client.post("/api/v1/auth/login", json={"invite_code": invite}).raise_for_status()
        classroom = client.post("/api/v1/classes", json={"name": "海洋班"}).raise_for_status().json()
        lesson = client.post("/api/v1/lessons", json={
            "class_id": classroom["id"], "topic": "Sea animals", "age_band": "6–10 岁",
            "duration_minutes": 25, "vocabulary": ["octopus", "crab"],
            "patterns": ["It has got eight arms."], "sound_focus": [],
        }).raise_for_status().json()
        lesson = client.post(f"/api/v1/lessons/{lesson['id']}/generate").raise_for_status().json()
        sections = lesson["outline"]["sections"]
        sections[0]["activity"] = "老师补充活动：拿出标着 shell 和 tentacles 的图片，请两人描述。"
        client.put(f"/api/v1/lessons/{lesson['id']}/content", json={
            "revision": lesson["revision"], "outline": sections,
            "items": [{key: item[key] for key in ("id", "text", "translation")} for item in lesson["items"]],
        }).raise_for_status()
        url = f"/api/v1/courseware/pptx/{lesson['id']}"
        response = client.get(url, params={"style": "children"}).raise_for_status()
        assert response.headers["x-courseware-style"] == "children"
        assert calls[-1][0] == "Sea animals"
        assert "octopus" in calls[-1][1] and "It has got eight arms." in calls[-1][1]
        assert calls[-1][2:] == ("children", True)
        child_source = calls[-1][1]
        assert child_source.startswith("Vocabulary\noctopus\ncrab\nSentence patterns\nIt has got eight arms.\n课堂活动\n")
        assert sections[0]["activity"] in child_source
        plan = plan_courseware("Sea animals", child_source)
        assert [item.word for item in plan.vocabulary] == ["octopus", "crab"]
        assert tuple(pattern.rstrip(".") for pattern in plan.patterns) == ("It has got eight arms",)
        assert sections[0]["activity"] in plan.source_notes

        client.get(url).raise_for_status()
        assert calls[-1][2] == "standard"
        assert calls[-1][1].startswith("教学目标\n")
        assert sections[0]["activity"] in calls[-1][1]

        client.post("/api/v1/auth/logout").raise_for_status()
        client.post("/api/v1/auth/login", json={"invite_code": other_invite}).raise_for_status()
        assert client.get(url, params={"style": "children"}).status_code == 404
        assert len(calls) == 2

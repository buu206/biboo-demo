from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pptx import Presentation
from sqlalchemy.orm import Session

from app.core.auth import create_teacher
from app.core.config import Settings
from app.main import create_app


def test_upload_generates_editable_pptx_from_material(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, fake_models=True))) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "课件测试")
        path = "/api/v1/courseware/pptx"
        params = {"filename": "英语材料.txt", "title": "动物英语课"}
        raw = "今天学习三种动物。\n\nKey words: penguin, turtle, dolphin.\n\nI can see a penguin.".encode()
        assert client.post(path, params=params, content=raw).status_code == 401
        assert client.post("/api/v1/auth/login", json={"invite_code": invite}).is_success
        response = client.post(path, params=params, content=raw)

    assert response.status_code == 200
    assert response.headers["content-type"].endswith("presentationml.presentation")
    assert response.headers["content-disposition"].startswith("attachment;")
    presentation = Presentation(BytesIO(response.content))
    assert len(presentation.slides) == int(response.headers["x-slide-count"])
    content = "\n".join(
        shape.text for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame
    )
    assert "动物英语课" in content
    assert "penguin" in content and "dolphin" in content


def test_invalid_document_returns_explanation(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, fake_models=True))) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "课件错误测试")
        assert client.post("/api/v1/auth/login", json={"invite_code": invite}).is_success
        response = client.post(
            "/api/v1/courseware/pptx", params={"filename": "broken.docx"}, content=b"invalid docx",
        )

    assert response.status_code == 422
    assert response.json()["error"]["message"]


def test_word_document_text_is_used(tmp_path):
    document = BytesIO()
    with ZipFile(document, "w") as archive:
        archive.writestr("[Content_Types].xml", """
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
""")
        archive.writestr("word/document.xml", """
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Three little turtles cross the road.</w:t></w:r></w:p></w:body>
</w:document>
""")

    with TestClient(create_app(Settings(data_dir=tmp_path, fake_models=True))) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "Word 测试")
        assert client.post("/api/v1/auth/login", json={"invite_code": invite}).is_success
        response = client.post(
            "/api/v1/courseware/pptx", params={"filename": "turtles.docx"}, content=document.getvalue(),
        )

    assert response.status_code == 200, response.text[:250]
    presentation = Presentation(BytesIO(response.content))
    assert any(
        "Three little turtles" in shape.text
        for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame
    )


def test_imported_goals_feed_assignment_and_edited_lesson_pptx(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, fake_models=True))) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "同源备课测试")
        client.post("/api/v1/auth/login", json={"invite_code": invite}).raise_for_status()
        classroom = client.post("/api/v1/classes", json={"name": "体验班"}).raise_for_status().json()
        goals = client.post(
            "/api/v1/courseware/goals", params={"filename": "认识海洋动物.md"},
            content="Vocabulary\n- dolphin\n- turtle\nSentence patterns: I see a turtle.\n发音：/t/".encode(),
        ).raise_for_status().json()
        assert goals == {
            "topic": "认识海洋动物", "vocabulary": ["dolphin", "turtle"],
            "patterns": ["I see a turtle."], "sound_focus": ["/t/"],
        }
        lesson = client.post("/api/v1/lessons", json={
            **goals, "class_id": classroom["id"], "age_band": "7–9 岁", "duration_minutes": 20,
        }).raise_for_status().json()
        path = f"/api/v1/lessons/{lesson['id']}"
        pptx_path = f"/api/v1/courseware/pptx/{lesson['id']}"
        assert client.get(pptx_path).status_code == 409
        lesson = client.post(path + "/generate").raise_for_status().json()
        assert any(item["text"] == "I see a turtle." for item in lesson["items"])
        sections = lesson["outline"]["sections"]
        sections[1]["activity"] = "老师补充活动：把海龟图片分给两组。"
        lesson = client.put(path + "/content", json={
            "revision": lesson["revision"], "outline": sections,
            "items": [{key: item[key] for key in ("id", "text", "translation")} for item in lesson["items"]],
        }).raise_for_status().json()
        response = client.get(pptx_path).raise_for_status()
        published = client.post(path + "/publish", json={
            "confirm": True, "revision": lesson["revision"],
        }).raise_for_status().json()
        assert published["status"] == "published"
        assert published["items"][0]["text"] == "dolphin"

    presentation = Presentation(BytesIO(response.content))
    pptx_text = "\n".join(
        shape.text for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame
    )
    assert "认识海洋动物" in pptx_text
    assert "把海龟图片分给两组" in pptx_text
    assert "I see a turtle." in pptx_text

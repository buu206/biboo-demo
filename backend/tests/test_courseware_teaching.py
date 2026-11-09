import json

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services import courseware_teaching as teaching
from app.services.courseware_plan import plan_courseware
from test_courseware_motion import wav


def copy(words=None):
    return json.dumps({"words": words or [{"word": "football", "meaning": "足球", "sentence": "I like football.",
                                          "gesture": "坐在座位上，用双手比一个圆。"}]})


def test_model_copy_is_bounded_and_does_not_change_teacher_targets_or_art():
    plan = plan_courseware("Sports", "Vocabulary: football\nSentence patterns: I like ___.")
    improved = teaching.apply_copy(plan, copy())
    assert improved.vocabulary[0].model_sentence == "I like football."
    assert improved.vocabulary[0].asset == plan.vocabulary[0].asset
    assert improved.patterns == plan.patterns
    for raw in [copy().replace('"football"', '"basketball"'), copy().replace('I like football.', 'I like bananas.'),
                copy().replace('I like football.', '<script>football</script>'), '{"words":[]}']:
        with pytest.raises(ValueError):
            teaching.apply_copy(plan, raw)


def test_model_outage_is_disclosed_and_voice_is_cached_per_teacher(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, fake_models=False)
    plan = plan_courseware("Sports", "Vocabulary: football")
    records = []
    monkeypatch.setattr(teaching, "OpenAI", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")))
    result, mode = teaching.enrich_plan(settings, plan, lambda event, call: records.append(call))
    assert result == plan and mode == "fallback"
    assert records[0].error == "COURSEWARE_COPY_FALLBACK"
    calls = []
    monkeypatch.setattr(teaching.ai, "synthesize", lambda *args: (calls.append(args[1]) or wav(), "audio/wav"))
    a = teaching.classroom_audio(settings, plan, {}, 1, lambda *args: None)
    b = teaching.classroom_audio(settings, plan, {}, 1, lambda *args: None)
    assert a == b and calls == ["football"]
    teaching.classroom_audio(settings, plan, {}, 2, lambda *args: None)
    assert calls == ["football", "football"]
    teaching.classroom_audio(settings, plan, a, 3, lambda *args: None)
    assert len(calls) == 2  # published voice reused without another paid call


def test_audio_failure_retains_usable_deck_and_explicit_missing_voice_note(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(teaching, "enrich_plan", lambda settings, plan, record: (plan, "fallback"))
    def fail(*args):
        raise AppError(503, "TTS_UNAVAILABLE", "暂不可用")
    monkeypatch.setattr(teaching.ai, "synthesize", fail)
    plan, audio, mode, count = teaching.prepare_teaching(settings, "Sports", "Vocabulary: football", {}, 1, lambda *a: None)
    assert not audio and count == 0 and mode == "fallback"
    assert "0/1" in plan.teacher_notes and "AI 生成暂不可用" in plan.teacher_notes


def test_export_never_embeds_other_owners_or_outside_audio(tmp_path):
    from types import SimpleNamespace as Obj
    from app.api.courseware import lesson_audio

    path = tmp_path / "valid.wav"
    path.write_bytes(wav())
    def item(owner=1, name="valid.wav", kind="tts"):
        return Obj(text="football", audio=Obj(owner_id=owner, kind=kind, path=name, mime="audio/wav"))
    settings = Settings(data_dir=tmp_path)
    assert "football" in lesson_audio(settings, Obj(items=[item()]), 1)
    assert not lesson_audio(settings, Obj(items=[item(owner=2), item(name="../outside.wav"), item(kind="recording")]), 1)


def test_real_post_exports_use_teaching_pipeline_after_owner_check(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from app.api import courseware
    from app.core.auth import create_teacher
    from app.main import create_app

    settings = Settings(data_dir=tmp_path, fake_models=True)
    calls = []
    with TestClient(create_app(settings)) as client:
        with Session(client.app.state.engine) as db:
            _, invite = create_teacher(db, "课堂测试")
            _, other = create_teacher(db, "另一位老师")
        client.post('/api/v1/auth/login', json={'invite_code': invite}).raise_for_status()
        classroom = client.post('/api/v1/classes', json={'name': '测试班'}).json()
        lesson = client.post('/api/v1/lessons', json={'class_id': classroom['id'], 'topic': 'Sports',
            'age_band': '6–8 岁', 'duration_minutes': 25, 'vocabulary': ['football'],
            'patterns': [], 'sound_focus': []}).json()
        client.post(f"/api/v1/lessons/{lesson['id']}/generate").raise_for_status()
        settings.fake_models = False
        def prepare(settings, title, source, existing, owner, record):
            calls.append(owner)
            return plan_courseware(title, source), {'football': (wav(), 'audio/wav')}, 'ai', 1
        monkeypatch.setattr(teaching, 'prepare_teaching', prepare)
        url = f"/api/v1/courseware/pptx/{lesson['id']}?style=children"
        response = client.post(url).raise_for_status()
        assert response.headers['x-courseware-audio-count'] == '1'
        assert response.headers['x-courseware-planner'] == 'ai'
        client.get(url).raise_for_status()
        assert len(calls) == 1  # GET remains a free, deterministic download
        client.post('/api/v1/auth/login', json={'invite_code': other}).raise_for_status()
        assert client.post(url).status_code == 404 and len(calls) == 1

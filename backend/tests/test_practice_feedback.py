import json

import httpx
import pytest

from app.core.config import Settings
from app.services import practice, practice_feedback as feedback
from app.services.oral_provider import OralPhone, OralResult, OralWord


def result(scores, overall, symbols=("f", "uh", "t", "b", "ao", "l")):
    return OralResult(overall, 1.0, (OralWord("football", True, tuple(
        OralPhone(symbol, score) for symbol, score in zip(symbols, scores)
    )),))


@pytest.mark.parametrize("scores,overall,decision", [
    ([98.20, 97.70, 98.51, 99.07, 99.34, 98.78], 98.60, "good"),
    ([2.29, .32, 95.67, 99.45, 99.10, 98.97], 65.97, "teacher_review"),
    ([56.96, 32.02, 5.67, 50.77, 90.23, 78.46], 52.35, "teacher_review"),
])
def test_replay_observed_scores_preserves_good_and_review_decisions(scores, overall, decision):
    # Rounded, anonymized scores from the three adult tests. No audio is replayed.
    assert practice.assess(result(scores, overall), "football")[0] == decision


def test_single_supported_issue_is_actionable_but_other_uncertainty_is_not():
    assert practice.assess(result([45, 90, 90, 90, 90, 90], 78), "football") == (
        "practice", ("football", "f"), "localized_phone",
    )
    assert practice.assess(result([45, 60, 90, 90, 90, 90], 78), "football")[0] == "teacher_review"
    assert practice.assess(result([45, 90, 90, 90, 90, 90], 54), "football")[0] == "teacher_review"
    unknown = result([45, 90], 78, symbols=("unmapped", "l"))
    assert practice.assess(unknown, "football")[2] == "unsupported_phone"
    unmatched = OralResult(90, 1, (OralWord("banana", True, (OralPhone("f", 40),)),))
    assert practice.assess(unmatched, "football")[2] == "uncertain_alignment"


def mock_llm(monkeypatch, content=None, unavailable=False):
    def respond(request):
        if unavailable:
            raise httpx.ConnectError("test unavailable", request=request)
        body = json.loads(request.content)
        prompt = json.loads(body["messages"][1]["content"])
        assert prompt["cue"] == feedback.CUES["f"]
        assert "fish" in prompt["candidates"]
        return httpx.Response(200, json={
            "id": "test-response", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(content, ensure_ascii=False),
            }}], "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        })
    original = feedback.OpenAI
    monkeypatch.setattr(feedback, "OpenAI", lambda **kw: original(
        http_client=httpx.Client(transport=httpx.MockTransport(respond)), **kw,
    ))


def call_coach():
    events = []
    response = feedback.coach(Settings(deepseek_api_key="test-key"), "football", "f", lambda e,c: events.append(c))
    return response, events


def test_live_contract_composes_trusted_action_and_selected_drill(monkeypatch):
    mock_llm(monkeypatch, {"encouragement": feedback.ENCOURAGEMENTS[1], "drill": "fish"})
    (text, drill), calls = call_coach()
    assert "上齿轻碰下唇，轻轻吹气" in text
    assert "football" in text and "先听示范读 fish" in text
    assert drill == "fish" and calls[0].result == "通过" and calls[0].error is None


@pytest.mark.parametrize("content", [
    {"encouragement": "你太笨了", "drill": "fish"},
    {"encouragement": feedback.ENCOURAGEMENTS[0], "drill": "unapproved"},
    {"encouragement": feedback.ENCOURAGEMENTS[0], "drill": "fish", "cue": "咬住舌头"},
    {"feedback": "慢慢练一次", "drill": "football"},
])
def test_invalid_coaching_cannot_remove_action_or_introduce_instructions(monkeypatch, content):
    mock_llm(monkeypatch, content)
    (text, drill), calls = call_coach()
    assert "上齿轻碰下唇，轻轻吹气" in text and drill == "fish"
    assert "笨" not in text and "咬住舌头" not in text
    assert calls[0].error == "COACH_FALLBACK"


def test_network_failure_keeps_specific_instruction(monkeypatch):
    mock_llm(monkeypatch, unavailable=True)
    (text, drill), calls = call_coach()
    assert "上齿轻碰下唇" in text and drill == "fish"
    assert calls[0].error == "COACH_FALLBACK"


def test_alias_and_unknown_vocabulary_do_not_invent_target_position():
    text, drill = feedback.coach(Settings(fake_models=True), "leaf", "F", lambda *a: None)
    assert drill == "leaf" and "开头" not in text and "/f/" in text
    text, drill = feedback.coach(Settings(fake_models=True), "think", "th", lambda *a: None)
    assert "/θ/" in text and "舌尖" in text
    with pytest.raises(ValueError):
        feedback.coach(Settings(fake_models=True), "word", "unknown", lambda *a: None)

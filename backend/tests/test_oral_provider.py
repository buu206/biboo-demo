import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services import oral_provider


@pytest.fixture
def settings():
    return Settings(tencent_soe_app_id="123456", tencentcloud_secret_id="unit-id",
                    tencentcloud_secret_key="unit-key")


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    def settimeout(self, timeout):
        assert 0 < timeout <= 10

    def recv(self):
        return json.dumps(next(self.messages))

    def send_binary(self, value):
        self.sent.append(value)

    def send(self, value):
        self.sent.append(json.loads(value))

    def close(self, timeout):
        self.closed = True


def test_signature_uses_raw_text_and_request_percent_encodes_it(settings, monkeypatch):
    monkeypatch.setattr(oral_provider, "time", lambda: 1722321759)
    monkeypatch.setattr(oral_provider, "randbelow", lambda maximum: 11)
    url = urlsplit(oral_provider.signed_url(settings, "I think it's sunny.", "unit-voice"))
    assert (url.scheme, url.hostname, url.path) == ("wss", "soe.cloud.tencent.com", "/soe/api/123456")
    assert "ref_text=I%20think%20it%27s%20sunny." in url.query
    assert parse_qs(url.query)["signature"] == ["ir/glQ8AzfsCXuRMu6WLCs5vyUk="]


def test_recording_mode_waits_for_handshake_and_returns_soe_evidence(settings, monkeypatch):
    socket = Socket([
        {"code": 0, "message": "success"},
        {"code": 0, "message_id": "req-1", "final": 1, "result": {
            "PronAccuracy": 81.0,
            "PronCompletion": 1,
            "Words": [
                {"Word": "think", "ReferenceWord": "think_0", "MatchTag": 0, "PhoneInfos": [
                    {"Phone": "s", "ReferencePhone": "th", "PronAccuracy": 30},
                ]},
                {"Word": "*", "MatchTag": 2},
            ],
        }},
    ])

    def connect(url, **options):
        params = parse_qs(urlsplit(url).query)
        assert (params["rec_mode"], params["voice_format"], params["eval_mode"]) == (["1"], ["1"], ["0"])
        assert options["redirect_limit"] == 0
        return socket

    monkeypatch.setattr(oral_provider, "create_connection", connect)
    result = oral_provider.evaluate(settings, b"test-wav", "think")

    assert socket.sent == [b"test-wav", {"type": "end"}]
    assert socket.closed
    assert result == oral_provider.OralResult(81.0, 1.0, (
        oral_provider.OralWord("think", True, (oral_provider.OralPhone("th", 30.0),)),
        oral_provider.OralWord("*", False, ()),
    ), "req-1")


def test_partial_phone_evidence_cannot_become_a_matched_word():
    result = oral_provider.parse_result({
        "PronAccuracy": 95,
        "PronCompletion": 1,
        "Words": [{"Word": "think", "MatchTag": 0, "PhoneInfos": [
            {"Phone": "th", "PronAccuracy": 98},
            {"Phone": "ih", "PronAccuracy": -1},
        ]}],
    }, "req-3")
    assert result.words == (oral_provider.OralWord("think", False, ()),)


def test_unrecognized_speech_keeps_evidence_empty(settings, monkeypatch):
    socket = Socket([{"code": 0}, {"code": 4105, "message_id": "req-2"}])
    monkeypatch.setattr(oral_provider, "create_connection", lambda *args, **kwargs: socket)
    assert oral_provider.evaluate(settings, b"test-wav", "think") == (
        oral_provider.OralResult(None, None, (), "req-2")
    )


@pytest.mark.parametrize(
    ("vendor_code", "app_code"),
    [
        (4002, "ORAL_UNAVAILABLE"),
        (4003, "ORAL_SERVICE_NOT_ENABLED"),
        (4004, "ORAL_QUOTA_UNAVAILABLE"),
    ],
)
def test_vendor_error_never_exposes_response_message(settings, monkeypatch, vendor_code, app_code):
    socket = Socket([{"code": vendor_code, "message": "private request text"}])
    monkeypatch.setattr(oral_provider, "create_connection", lambda *args, **kwargs: socket)
    with pytest.raises(AppError) as caught:
        oral_provider.evaluate(settings, b"test-wav", "think")
    assert caught.value.detail.error.code == app_code
    assert "private request text" not in caught.value.detail.error.message
    assert socket.sent == []
    assert socket.closed

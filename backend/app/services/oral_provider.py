import base64
import hmac
import json
import re
from dataclasses import dataclass
from secrets import randbelow
from time import monotonic, time
from urllib.parse import quote, urlencode
from uuid import uuid4

from websocket import WebSocket, WebSocketException, create_connection

from app.core.config import Settings
from app.core.errors import AppError

SOE_HOST = "soe.cloud.tencent.com"
ORAL_MODEL = "腾讯云智聆口语评测（新版）16k_en"
NO_USABLE_SPEECH = {4105, 4108}
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class OralPhone:
    symbol: str
    accuracy: float


@dataclass(frozen=True)
class OralWord:
    text: str
    matched: bool
    phones: tuple[OralPhone, ...]


@dataclass(frozen=True)
class OralResult:
    accuracy: float | None
    completion: float | None
    words: tuple[OralWord, ...]
    request_id: str | None = None


def signed_url(settings: Settings, reference: str, voice_id: str) -> str:
    path = f"{SOE_HOST}/soe/api/{settings.tencent_soe_app_id.strip()}"
    timestamp = int(time())
    params = sorted({
        "eval_mode": "0" if len(reference.split()) == 1 else "1",
        "expired": str(timestamp + 60),
        "nonce": str(randbelow(999999999) + 1),
        "rec_mode": "1",
        "ref_text": reference,
        "score_coeff": "1.0",
        "secretid": settings.tencentcloud_secret_id.strip(),
        "sentence_info_enabled": "0",
        "server_engine_type": "16k_en",
        "text_mode": "0",
        "timestamp": str(timestamp),
        "voice_format": "1",
        "voice_id": voice_id,
    }.items())
    original = path + "?" + "&".join(f"{key}={value}" for key, value in params)
    signature = base64.b64encode(
        hmac.digest(settings.tencentcloud_secret_key.strip().encode(), original.encode(), "sha1")
    ).decode("ascii")
    return f"wss://{path}?{urlencode([*params, ('signature', signature)], quote_via=quote)}"


def score(value: object, maximum: float) -> float | None:
    if type(value) in (int, float) and 0 <= value <= maximum:
        return float(value)
    return None


def parse_result(result: dict, request_id: str) -> OralResult:
    words = []
    rows = result.get("Words")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("Word"), str) or not row["Word"].strip():
                words.clear()
                break
            phones = []
            phone_rows = row.get("PhoneInfos")
            if isinstance(phone_rows, list):
                for phone in phone_rows:
                    if not isinstance(phone, dict):
                        phones.clear()
                        break
                    symbol = phone.get("ReferencePhone") or phone.get("Phone")
                    accuracy = score(phone.get("PronAccuracy"), 100)
                    if not isinstance(symbol, str) or not 0 < len(symbol.strip()) <= 20 or accuracy is None:
                        phones.clear()
                        break
                    phones.append(OralPhone(symbol.strip(), accuracy))
            matched = bool(phones) and type(row.get("MatchTag")) is int and row["MatchTag"] == 0
            words.append(OralWord(row["Word"], matched, tuple(phones)))
    return OralResult(
        score(result.get("PronAccuracy"), 100),
        score(result.get("PronCompletion"), 1),
        tuple(words),
        request_id,
    )


def _time_left(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _receive(connection: WebSocket, deadline: float) -> dict:
    connection.settimeout(_time_left(deadline))
    payload = connection.recv()
    if not isinstance(payload, str) or len(payload) > 512_000:
        raise ValueError("SOE response must be a bounded text message")
    message = json.loads(payload)
    if not isinstance(message, dict) or type(message.get("code")) is not int:
        raise ValueError("SOE response is missing a status")
    return message


def _request_id(message: dict, voice_id: str) -> str:
    for name in ("message_id", "voice_id"):
        value = message.get(name)
        if isinstance(value, str) and REQUEST_ID.fullmatch(value):
            return value
    return voice_id


def evaluate(settings: Settings, pcm_wav: bytes, reference: str) -> OralResult:
    if not settings.oral_credentials_ready:
        raise AppError(503, "ORAL_NOT_CONFIGURED", "请先配置腾讯云口语评测。")
    reference = " ".join(reference.split())
    if not reference or len(reference.split()) > 30:
        raise AppError(422, "ORAL_REFERENCE_INVALID", "这道跟读题的文本超出评测范围。")

    voice_id = uuid4().hex
    deadline = monotonic() + settings.tencent_soe_timeout_seconds
    connection = None
    try:
        connection = create_connection(
            signed_url(settings, reference, voice_id),
            timeout=_time_left(deadline),
            suppress_origin=True,
            redirect_limit=0,
        )
        handshake_code = _receive(connection, deadline)["code"]
        if handshake_code == 4003:
            raise AppError(503, "ORAL_SERVICE_NOT_ENABLED", "请在腾讯云控制台开通智聆口语评测（新版）。")
        if handshake_code == 4004:
            raise AppError(503, "ORAL_QUOTA_UNAVAILABLE", "腾讯云口语评测当前没有可用额度。请在腾讯云开通后付费或购买资源包。")
        if handshake_code != 0:
            raise ValueError("SOE handshake failed")
        connection.settimeout(_time_left(deadline))
        connection.send_binary(pcm_wav)
        connection.settimeout(_time_left(deadline))
        connection.send('{"type":"end"}')

        last_result = None
        while True:
            message = _receive(connection, deadline)
            request_id = _request_id(message, voice_id)
            if message["code"] in NO_USABLE_SPEECH:
                return OralResult(None, None, (), request_id)
            if message["code"] != 0:
                raise ValueError("SOE assessment failed")
            result = message.get("result")
            if isinstance(result, dict) and result:
                last_result = parse_result(result, request_id)
            if message.get("final") == 1:
                if last_result is None:
                    raise ValueError("SOE final message is missing an assessment")
                return last_result
    except (OSError, WebSocketException, ValueError):
        raise AppError(503, "ORAL_UNAVAILABLE", "口语评测暂时不可用，请稍后重试。") from None
    finally:
        if connection is not None:
            connection.close(timeout=0.1)

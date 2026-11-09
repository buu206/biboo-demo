import json
import time

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.services.ai import Call

# Reviewed, bounded articulation cues. Unknown sounds go to teacher review.
CUES = {
    "f": "上齿轻碰下唇，轻轻吹气",
    "v": "上齿轻碰下唇，边送气边让喉咙轻轻振动",
    "p": "先轻轻闭唇，再张开，让气流短短地出来",
    "b": "先轻轻闭唇，再张开，同时让喉咙轻轻振动",
    "s": "牙齿靠近但不咬紧，让气流从中间轻轻出来",
    "ʃ": "嘴唇稍微向前，像轻轻提醒大家安静一样送气",
    "θ": "舌尖轻放在上下齿之间，轻轻送气，不要咬住舌头",
    "ð": "舌尖轻放在上下齿之间，送气时让喉咙轻轻振动",
}
ALIASES = {"th": "θ", "dh": "ð", "sh": "ʃ"}
DRILL_WORDS = {
    "f": ("football", "fish", "four", "fun"),
    "v": ("van", "very", "five"),
    "p": ("pen", "pig", "pink"),
    "b": ("ball", "bag", "book", "basketball"),
    "s": ("sun", "six", "see"),
    "ʃ": ("ship", "shop", "fish"),
    "θ": ("think", "three", "thank"),
    "ð": ("this", "that", "mother"),
}
ENCOURAGEMENTS = ("谢谢你认真跟读！", "你完成了一次练习！", "我们一起试试这个小动作。")
PROMPT = """Select coaching options for an English learner aged 6 to 10.
The JSON input contains a single supported pronunciation issue, a trusted articulation cue,
allowed encouragements and approved drill texts. Do not diagnose, invent a cue or introduce vocabulary.
Choose one encouragement and one drill verbatim from the supplied lists.
Prefer a short alternative drill when one is available. The server will add the articulation cue.
Return only JSON with keys encouragement and drill. No Markdown or additional keys."""


def normalized_phone(symbol):
    value = symbol.strip().casefold()
    return ALIASES.get(value, value)


def supports_phone(symbol):
    return normalized_phone(symbol) in CUES


class CoachOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    encouragement: str = Field(min_length=1, max_length=40)
    drill: str = Field(min_length=1, max_length=100)


def compose_feedback(word, phone, encouragement, drill):
    return f"{encouragement}练 /{phone}/：{CUES[phone]}。先听示范读 {drill}，再把这个音放回 {word}。"


def coach(settings, word, symbol, record):
    phone = normalized_phone(symbol)
    if phone not in CUES:
        raise ValueError("Unsupported pronunciation cue")
    related = DRILL_WORDS.get(phone, ())
    candidates = (word,)
    # Expand only known target words; unknown vocabulary repeats the original word.
    if word.casefold() in related:
        candidates += tuple(candidate for candidate in related if candidate != word.casefold())
    default_drill = candidates[1] if len(candidates) > 1 else word
    fallback = (compose_feedback(word, phone, ENCOURAGEMENTS[0], default_drill), default_drill)
    if settings.fake_models or not settings.deepseek_api_key:
        return fallback

    call = Call(settings.deepseek_model)
    started = time.monotonic()
    try:
        with OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=min(settings.model_timeout_seconds, 4),
            max_retries=0,
        ) as client:
            response = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": json.dumps(
                        {"word": word, "phoneme": phone, "cue": CUES[phone],
                         "encouragements": ENCOURAGEMENTS, "candidates": candidates}, ensure_ascii=False,
                    )},
                ],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
                max_tokens=200,
            )
        call.request_id = response._request_id or response.id
        if response.usage:
            call.input_tokens = response.usage.prompt_tokens
            call.output_tokens = response.usage.completion_tokens
        output = CoachOutput.model_validate_json(response.choices[0].message.content or "")
        if output.drill not in candidates or output.encouragement not in ENCOURAGEMENTS:
            raise ValueError("Unapproved coaching option")
        call.structure = "鼓励语与练习词白名单合规"
        call.result = "通过"
        return compose_feedback(word, phone, output.encouragement, output.drill), output.drill
    except Exception:
        call.error = "COACH_FALLBACK"
        return fallback
    finally:
        call.seconds = round(time.monotonic() - started, 3)
        record("practice_feedback", call)

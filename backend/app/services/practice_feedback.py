import json
import time

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.services.ai import Call

# These short words reinforce the same English /θ/ or /ð/ sound.
TH_WORDS = {
    "θ": ("think", "three", "thank"),
    "ð": ("this", "that", "mother"),
    "th": ("think", "three", "thank"),
    "dh": ("this", "that", "mother"),
}
PROMPT = """You write short, kind Mandarin feedback for young English learners.
The JSON user message contains one supported pronunciation issue and approved drill texts.
Encourage first, then name one practice point. Mention the given English word.
Do not add any other diagnosis or grades. Choose one drill verbatim from candidates.
Return only JSON with keys feedback and drill. Example:
{"feedback":"你已经读出了 think，我们把开头的音慢慢练一次。","drill":"three"}
Do not output Markdown, shame, grades, or new vocabulary."""


class CoachOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    feedback: str = Field(min_length=1, max_length=80)
    drill: str = Field(min_length=1, max_length=100)


def coach(settings, word, symbol, record):
    candidates = (word,)
    related_words = TH_WORDS.get(symbol.casefold(), ())
    if word.casefold() in related_words:
        candidates += tuple(candidate for candidate in related_words if candidate != word.casefold())
    fallback = (f"你已经完成了一次跟读。我们把 {word} 里的这个音慢慢练一次。", candidates[0])
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
                        {"word": word, "phoneme": symbol, "candidates": candidates}, ensure_ascii=False,
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
        if (
            output.drill not in candidates
            or word.casefold() not in output.feedback.casefold()
            or any(character.isdigit() for character in output.feedback)
            or any(term in output.feedback for term in ("分数", "笨", "糟糕", "太差"))
        ):
            raise ValueError
        call.structure = "首测合规"
        call.result = "通过"
        return output.feedback, output.drill
    except Exception:
        call.error = "COACH_FALLBACK"
        return fallback
    finally:
        call.seconds = round(time.monotonic() - started, 3)
        record("practice_feedback", call)

"""Run the real Biboo API workflow against isolated data and record provider calls."""

import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from zoneinfo import ZoneInfo

PRODUCT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT / "backend"))

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import create_teacher
from app.core.config import Settings
from app.main import create_app

EVIDENCE = PRODUCT / "docs" / "evidence" / "阶段2-1"
LOG = EVIDENCE / "冒烟记录.md"
SAMPLES = EVIDENCE / "真实样例评分.md"
PREVIEW = EVIDENCE / "示范音频-家庭成员.mp3"
API = "/api/v1"
TARGETS = (
    ("家庭成员", ["mother", "father", "sister"], ["This is my ___."], ["th"]),
    ("教室用品", ["book", "pen", "bag"], ["I have a ___."], ["b"]),
    ("宠物", ["cat", "dog", "fish"], ["Do you have a ___?"], ["sh"]),
    ("早餐", ["egg", "milk", "bread"], ["I like ___."], ["br"]),
    ("天气", ["sunny", "rainy", "windy"], ["It is ___ today."], ["w"]),
)


def timestamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def markdown(value):
    return str(value if value is not None else "-").replace("|", "¦").replace("\n", " ")


def row(values):
    return "| " + " | ".join(map(markdown, values)) + " |\n"


def setup_log(settings):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if not LOG.exists():
        LOG.write_text(
            "# 冒烟记录（冒烟脚本自动写入，不得手填）\n"
            "- 产品：Biboo\n- 阶段：阶段2-1\n"
            f"- 模型：{settings.deepseek_model} / {settings.tts_model_label}\n"
            f"- 写入时间：{timestamp()}\n\n"
            "| 时间 | 链路 | 请求 ID | 输入 token | 输出 token | 首字耗时 | 总耗时 | 结构校验 | 重试次数 | 结果 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )


def record(event, call):
    label = "生成" if event == "generate" else "语音合成"
    with LOG.open("a", encoding="utf-8") as file:
        file.write(row((
            timestamp(), f"{label} · {call.model}", call.request_id, call.input_tokens, call.output_tokens,
            "-", f"{call.seconds:.3f}s", call.structure, call.retry, call.result,
        )))


def api(client, method, path, **kwargs):
    response = client.request(method, API + path, **kwargs)
    if not response.is_success:
        code = response.json().get("error", {}).get("code", "HTTP_ERROR")
        raise RuntimeError(f"{method} {path} 返回 {response.status_code} {code}")
    return response


def write_sample(file, target, lesson, elapsed):
    file.write(f"\n## {markdown(target['topic'])}\n\n")
    file.write(f"{target['age_band']}，{target['duration_minutes']} 分钟，生成耗时 {elapsed:.2f} 秒。\n\n")
    file.write(f"词汇：{markdown('、'.join(target['vocabulary']))}。"
               f"句型：{markdown('、'.join(target['patterns']))}。"
               f"发音重点：{markdown('、'.join(target['sound_focus']))}。\n\n")
    for section in lesson["outline"]["sections"]:
        file.write(f"- {markdown(section['title'])}（{section['minutes']} 分钟） · {markdown(section['activity'])}\n")
    file.write("\n")
    file.write(row(("类型", "文本", "译文")) + row(("---", "---", "---")))
    for item in lesson["items"]:
        file.write(row((item["speaker"] or item["kind"], item["text"], item["translation"])))
    if lesson["quality_notes"]:
        file.write("\n" + "\n".join(f"- {markdown(note)}" for note in lesson["quality_notes"]) + "\n")
    file.write("\n覆盖要求 __ / 结构 __ / 语言 __ / 年龄适配 __ / 长度 __ / 不能接受项 __\n")


def main():
    settings = Settings.load()
    if settings.fake_models or not settings.credentials_ready:
        print(f"待验：请配置 DeepSeek 和 {settings.tts_model_label} 的凭证，并将 BIBOO_FAKE_MODELS 设为 0。")
        return 2

    setup_log(settings)
    with TemporaryDirectory(prefix="biboo-smoke-") as directory:
        local = settings.model_copy(update={"data_dir": Path(directory), "secure_cookie": False})
        app = create_app(local, observer=record)
        with TestClient(app) as client, SAMPLES.open("w", encoding="utf-8") as file:
            file.write("# Biboo 阶段 2-1 真实样例评分\n\n每项 1–3 分，请标出不能接受的内容。\n")
            with Session(app.state.engine) as db:
                _, code = create_teacher(db, "冒烟验收老师")
            api(client, "POST", "/auth/login", json={"invite_code": code})
            classroom = api(client, "POST", "/classes", json={"name": "验收班"}).json()
            first = None
            for topic, vocabulary, patterns, sounds in TARGETS:
                target = dict(class_id=classroom["id"], topic=topic, age_band="7–9 岁",
                              duration_minutes=25, vocabulary=vocabulary, patterns=patterns, sound_focus=sounds)
                lesson = api(client, "POST", "/lessons", json=target).json()
                url = f"/lessons/{lesson['id']}"
                started = monotonic()
                generated = api(client, "POST", f"{url}/generate").json()
                elapsed = monotonic() - started
                assert generated == api(client, "GET", url).json()
                assert [item["text"] for item in generated["items"] if item["kind"] == "word"] == vocabulary
                write_sample(file, target, generated, elapsed)
                if elapsed >= 30:
                    raise RuntimeError(f"备课生成超过 30 秒：{elapsed:.2f}s")
                if first is None:
                    first = (url, generated)

            url, lesson = first
            published = api(client, "POST", f"{url}/publish",
                            json={"confirm": True, "revision": lesson["revision"]}).json()
            assert published["status"] == "published" and published == api(client, "GET", url).json()
            preview = None
            for item in published["items"]:
                audio = api(client, "GET", f"/assets/{item['audio_asset_id']}")
                assert audio.headers["content-type"] in {"audio/mpeg", "audio/wav"} and audio.content
                if preview is None and item["kind"] == "sentence":
                    preview = (audio.content, ".wav" if audio.headers["content-type"] == "audio/wav" else ".mp3")
            if preview is not None:
                PREVIEW.with_suffix(preview[1]).write_bytes(preview[0])

    print(f"真实链路通过，已写入 {LOG.name} 和 {SAMPLES.name}。请按样例评分。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        message = str(error) if type(error) is RuntimeError else type(error).__name__
        print(f"真实链路未通过：{message}。")
        raise SystemExit(1) from None

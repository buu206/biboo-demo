"""Exercise the real pronunciation flow with explicitly supplied adult recordings."""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

PRODUCT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT / "backend"))

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import smoke
from app.core.auth import create_teacher
from app.core.config import Settings
from app.main import create_app
from app.models import Classroom, HomeworkItem, Lesson
from app.services.recordings import MAX_UPLOAD_BYTES, normalize_wav

EVIDENCE = PRODUCT / "docs" / "evidence" / "阶段2-2"
API = "/api/v1"


def recording(value):
    label, separator, filename = value.partition("=")
    if label not in {"clean", "wrong", "noisy"} or not separator:
        raise argparse.ArgumentTypeError("使用 clean=文件.wav、wrong=文件.wav 或 noisy=文件.wav")
    path = Path(filename).expanduser()
    if not path.is_file() or path.stat().st_size > MAX_UPLOAD_BYTES:
        raise argparse.ArgumentTypeError("文件须存在且不超过 2 MB")
    audio = path.read_bytes()
    try:
        normalize_wav(audio)
    except Exception:
        raise argparse.ArgumentTypeError("请提交 16 kHz 单声道 PCM WAV，0.2–30 秒") from None
    return label, audio


def seed(app):
    with Session(app.state.engine) as db:
        teacher, invite = create_teacher(db, "合成验收账号")
        group = Classroom(owner_id=teacher.id, name="跟读验收")
        db.add(group)
        db.flush()
        lesson = Lesson(
            owner_id=teacher.id, class_id=group.id, topic="练习 th", age_band="7–9 岁",
            duration_minutes=10, vocabulary=["think"], patterns=[], sound_focus=["th"], status="published",
        )
        db.add(lesson)
        db.flush()
        item = HomeworkItem(owner_id=teacher.id, lesson_id=lesson.id, kind="word",
                            position=0, text="think", translation="想")
        db.add(item)
        db.flush()
        item_id = item.id
        db.commit()
        return invite, item_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", type=recording, required=True)
    parser.add_argument("--adult-consent", action="store_true", required=True,
                        help="确认使用已同意用于本次验收的成人录音")
    args = parser.parse_args()
    counts = Counter(label for label, _ in args.case)
    if len(args.case) not in range(5, 11) or len(counts) != 3:
        parser.error("需提供 5–10 份成人录音，覆盖 clean、wrong、noisy 三类。")

    settings = Settings.load()
    if settings.fake_models or not (settings.oral_credentials_ready and settings.deepseek_api_key):
        print("待验：请配置腾讯云口语评测（新版）和 DeepSeek 凭证，并关闭模拟模式。")
        return 2

    # Keep only complete evidence at the path checked by verify.sh.
    with TemporaryDirectory(prefix="biboo-oral-smoke-") as work, TemporaryDirectory(dir=EVIDENCE) as pending:
        log_path = Path(pending) / "冒烟记录.md"
        samples_path = Path(pending) / "真实样例评分.md"
        model_line = f"腾讯云 SOE-N / {settings.deepseek_model}"
        log_path.write_text(
            "# 真实冒烟记录\n\n"
            "- 产品：Biboo\n- 阶段：阶段2-2\n"
            f"- 模型：{model_line}\n\n"
            "| 时间 | 链路 | 请求 ID | 输入 token | 输出 token | 首字耗时 | 耗时 | 结构校验 | 重试次数 | 结果 |\n"
            "| --- | --- | --- | ---: | ---: | --- | --- | --- | ---: | --- |\n",
            encoding="utf-8",
        )
        def record(event, call):
            label = "口语评测" if event == "oral_assessment" else "跟读反馈"
            with log_path.open("a", encoding="utf-8") as file:
                file.write(smoke.row((
                    smoke.timestamp(), f"{label} · {call.model}", call.request_id,
                    call.input_tokens, call.output_tokens, "-", f"{call.seconds:.3f}s",
                    call.structure, call.retry, call.result,
                )))

        local = settings.model_copy(update={"data_dir": Path(work), "secure_cookie": False})
        app = create_app(local, observer=record)
        rows = [
            "# Biboo 阶段 2-2 真实样例评分", "",
            "成人模仿跟读 think。请判断分流是否合适，给儿童反馈和加练各打 1–3 分，并标出误纠。",
            "", "| 样例 | 输入标签 | 分流 | 儿童反馈 | 加练 |",
            "| --- | --- | --- | --- | --- |",
        ]
        with TestClient(app) as client:
            invite, item_id = seed(app)
            smoke.api(client, "POST", "/auth/login", json={"invite_code": invite})
            for index, (label, audio) in enumerate(args.case, 1):
                url = f"/practice/items/{item_id}/attempts?learner_id={uuid4()}"
                outcome = smoke.api(
                    client, "POST", url, content=audio,
                    headers={"Content-Type": "audio/wav", "Idempotency-Key": str(uuid4())},
                ).json()
                assert smoke.api(client, "GET", url).json() == [outcome]
                drill = outcome["drill"]["text"] if outcome["drill"] else "-"
                feedback = outcome["feedback"].replace("|", "\\|").replace("\n", " ")
                rows.append(f"| {index} | {label} | {outcome['decision']} | {feedback} | {drill} |")

        calls = log_path.read_text(encoding="utf-8").splitlines()
        if not any("口语评测" in row and row.endswith("| 通过 |") for row in calls):
            raise RuntimeError("没有成功的真实口语评测调用。")
        if not any("跟读反馈" in row and row.endswith("| 通过 |") for row in calls):
            raise RuntimeError("尚无真实跟读反馈样例，请补充可定位 th 错误的成人录音。")
        samples_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        for artifact in (samples_path, log_path):
            os.replace(artifact, EVIDENCE / artifact.name)
    print("真实评测与反馈调用通过，请到证据目录查看样例并评分。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"真实冒烟待验：{error}")
        raise SystemExit(1) from None

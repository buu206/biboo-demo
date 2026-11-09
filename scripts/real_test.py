"""Start Biboo's loopback-only real-model test workspace without making model calls."""

import argparse
from pathlib import Path
import sys

PRODUCT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT / "backend"))

import uvicorn
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import digest
from app.core.config import Settings
from app.core.db import database, migrate
from app.main import create_app
from app.models import Classroom, Teacher

# This public local-demo login is valid only in this isolated localhost workspace.
LOCAL_INVITE = "biboo-demo"
CLASS_NAME = "Biboo 真实测试班"


def load_real_settings():
    settings = Settings.load()
    return settings.model_copy(update={
        "fake_models": False,
        "data_dir": (PRODUCT / "data" / "real-test").resolve(),
    })


def missing_credentials(settings):
    required = [("DEEPSEEK_API_KEY", settings.deepseek_api_key)]
    if settings.tts_provider == "aihubmix":
        required.append(("AIHUBMIX_API_KEY", settings.aihubmix_api_key))
    else:
        required.extend([
            ("TENCENTCLOUD_SECRET_ID", settings.tencentcloud_secret_id),
            ("TENCENTCLOUD_SECRET_KEY", settings.tencentcloud_secret_key),
        ])
    return [name for name, value in required if not value.strip()]


def show_configuration(settings):
    """Print presence only; never print keys, account IDs, or the local invite."""
    def configured(value):
        return "已配置" if value else "缺配置"

    tts_ready = (
        bool(settings.aihubmix_api_key.strip())
        if settings.tts_provider == "aihubmix"
        else bool(settings.tencentcloud_secret_id.strip() and settings.tencentcloud_secret_key.strip())
    )
    print("运行模式：真实模型（非模拟）；这里只检查配置，不发起模型请求。")
    print(f"文字模型：{settings.deepseek_model} · {configured(settings.deepseek_api_key.strip())}")
    print(f"示范语音：{settings.tts_model_label} · {configured(tts_ready)}")
    print(f"口语评测：腾讯云 SOE-N · {configured(settings.oral_credentials_ready)}")
    print(f"独立测试数据：{settings.data_dir}")
    print("已配置只表示凭证存在；服务权限、额度和真实效果仍需单独验证。")


def prepare_workspace(settings):
    """Create only an empty teacher/classroom, without lessons or paid requests."""
    engine = database(settings.data_dir)
    try:
        migrate(engine)
        with Session(engine) as db:
            teacher = db.scalar(select(Teacher).where(
                Teacher.invite_code_hash == digest(LOCAL_INVITE),
            ))
            if teacher is None:
                teacher = Teacher(name="真实测试老师", invite_code_hash=digest(LOCAL_INVITE))
                db.add(teacher)
                db.flush()
            classroom = db.scalar(select(Classroom.id).where(
                Classroom.owner_id == teacher.id, Classroom.name == CLASS_NAME,
            ))
            if classroom is None:
                db.add(Classroom(owner_id=teacher.id, name=CLASS_NAME))
            db.commit()
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18768)
    parser.add_argument("--check", action="store_true", help="只检查配置；不创建数据、不启动服务、不调用模型")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间。")
    try:
        settings = load_real_settings()
    except ValidationError as error:
        fields = sorted({str(issue["loc"][0]) for issue in error.errors() if issue["loc"]})
        print("配置格式不正确，请检查这些字段：" + "、".join(fields), file=sys.stderr)
        return 2

    show_configuration(settings)
    missing = missing_credentials(settings)
    if missing:
        print("请在 backend/.env 补齐：" + "、".join(missing), file=sys.stderr)
        return 2
    if args.check:
        return 0

    prepare_workspace(settings)
    app = create_app(settings)
    print(f"Biboo 真实测试入口：http://localhost:{args.port}/", flush=True)
    print("启动只准备空白老师和班级；生成、发布、跟读操作才会发起真实请求。", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

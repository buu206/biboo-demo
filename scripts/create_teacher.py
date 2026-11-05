"""Create a local teacher and display the invite code once."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy.orm import Session

from app.core.auth import create_teacher
from app.core.config import Settings
from app.core.db import database, migrate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="老师显示名称")
    name = parser.parse_args().name.strip()
    if not 1 <= len(name) <= 140:
        parser.error("老师显示名称须为 1–140 个字符")
    engine = database(Settings.load().data_dir)
    try:
        migrate(engine)
        with Session(engine) as db:
            _, code = create_teacher(db, name)
            print(code)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

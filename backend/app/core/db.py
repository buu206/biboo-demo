from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, event

from app.core.config import BACKEND


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def database(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(data_dir / "biboo.db")))

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

    return engine


def migrate(engine):
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode = WAL")
        connection.commit()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.db import now


class Base(DeclarativeBase):
    pass


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    invite_code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    expires_at: Mapped[datetime]


class Classroom(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=now)


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (CheckConstraint("status IN ('draft', 'generated', 'published')"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    topic: Mapped[str]
    age_band: Mapped[str]
    duration_minutes: Mapped[int]
    vocabulary: Mapped[list[str]] = mapped_column(JSON)
    patterns: Mapped[list[str]] = mapped_column(JSON)
    sound_focus: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(default="draft")
    outline: Mapped[dict | None] = mapped_column(JSON, default=None)
    quality_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    items: Mapped[list["HomeworkItem"]] = relationship(
        order_by="HomeworkItem.position", cascade="all, delete-orphan",
    )


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    kind: Mapped[str] = mapped_column(default="tts")
    path: Mapped[str] = mapped_column(unique=True)
    mime: Mapped[str]
    size: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=now)


class HomeworkItem(Base):
    __tablename__ = "homework_items"
    __table_args__ = (
        UniqueConstraint("lesson_id", "position"),
        CheckConstraint("kind IN ('word', 'sentence', 'dialogue')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    kind: Mapped[str]
    position: Mapped[int]
    speaker: Mapped[str | None]
    text: Mapped[str]
    translation: Mapped[str]
    audio_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    audio: Mapped[Asset | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    event: Mapped[str]
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"
    __table_args__ = (
        UniqueConstraint("owner_id", "item_id", "learner_id", "request_key"),
        CheckConstraint("decision IN ('good', 'practice', 'teacher_review')"),
        CheckConstraint("round BETWEEN 0 AND 2"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("homework_items.id"))
    learner_id: Mapped[str] = mapped_column(String(36))
    request_key: Mapped[str] = mapped_column(String(36))
    audio_digest: Mapped[str] = mapped_column(String(64))
    audio_path: Mapped[str] = mapped_column(unique=True)
    reference: Mapped[str]
    round: Mapped[int]
    decision: Mapped[str]
    feedback: Mapped[str]
    drill_text: Mapped[str | None]
    assessment: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)


class PracticeReview(Base):
    __tablename__ = "practice_reviews"
    __table_args__ = (CheckConstraint("verdict IN ('good', 'practice')"),)

    attempt_id: Mapped[int] = mapped_column(ForeignKey("practice_attempts.id"), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    verdict: Mapped[str]
    note: Mapped[str]
    focus: Mapped[str]
    reviewed_at: Mapped[datetime] = mapped_column(default=now)
    voice_audio: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    voice_recorded_at: Mapped[datetime | None]

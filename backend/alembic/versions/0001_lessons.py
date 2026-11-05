"""Create teacher accounts, lessons, homework, audio and audits."""

from alembic import op
import sqlalchemy as sa

revision = "0001_lessons"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("invite_code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("teacher_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("topic", sa.String, nullable=False),
        sa.Column("age_band", sa.String, nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("vocabulary", sa.JSON, nullable=False),
        sa.Column("patterns", sa.JSON, nullable=False),
        sa.Column("sound_focus", sa.JSON, nullable=False),
        sa.Column("status", sa.String, sa.CheckConstraint("status IN ('draft', 'generated', 'published')"), nullable=False),
        sa.Column("outline", sa.JSON, nullable=True),
        sa.Column("quality_notes", sa.JSON, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("path", sa.String, nullable=False, unique=True),
        sa.Column("mime", sa.String, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "homework_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("kind", sa.String, sa.CheckConstraint("kind IN ('word', 'sentence', 'dialogue')"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("speaker", sa.String),
        sa.Column("text", sa.String, nullable=False),
        sa.Column("translation", sa.String, nullable=False),
        sa.Column("audio_asset_id", sa.Integer, sa.ForeignKey("assets.id")),
        sa.UniqueConstraint("lesson_id", "position"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    for table in ("classes", "lessons", "assets", "homework_items", "audit_log"):
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
    op.create_index("ix_sessions_teacher_id", "sessions", ["teacher_id"])
    op.create_index("ix_lessons_class_id", "lessons", ["class_id"])
    op.create_index("ix_homework_items_lesson_id", "homework_items", ["lesson_id"])


def downgrade():
    for table in ("audit_log", "homework_items", "assets", "lessons", "classes", "sessions", "teachers"):
        op.drop_table(table)

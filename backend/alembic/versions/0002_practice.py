"""Store assessment attempts with their recording ownership."""

from alembic import op
import sqlalchemy as sa

revision = "0002_practice"
down_revision = "0001_lessons"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("homework_items.id"), nullable=False),
        sa.Column("learner_id", sa.String(36), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("audio_digest", sa.String(64), nullable=False),
        sa.Column("audio_path", sa.String, nullable=False, unique=True),
        sa.Column("reference", sa.String, nullable=False),
        sa.Column("round", sa.Integer, nullable=False),
        sa.Column("decision", sa.String, nullable=False),
        sa.Column("feedback", sa.String, nullable=False),
        sa.Column("drill_text", sa.String, nullable=True),
        sa.Column("assessment", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("owner_id", "item_id", "learner_id", "request_key"),
        sa.CheckConstraint("decision IN ('good', 'practice', 'teacher_review')"),
        sa.CheckConstraint("round BETWEEN 0 AND 2"),
    )


def downgrade():
    op.drop_table("practice_attempts")

"""Store teachers' reviews and optional voice feedback."""

from alembic import op
import sqlalchemy as sa

revision = "0003_reviews"
down_revision = "0002_practice"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "practice_reviews",
        sa.Column("attempt_id", sa.Integer, sa.ForeignKey("practice_attempts.id"), primary_key=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("verdict", sa.String, nullable=False),
        sa.Column("note", sa.String, nullable=False),
        sa.Column("focus", sa.String, nullable=False),
        sa.Column("reviewed_at", sa.DateTime, nullable=False),
        sa.Column("voice_audio", sa.LargeBinary),
        sa.Column("voice_recorded_at", sa.DateTime),
        sa.CheckConstraint("verdict IN ('good', 'practice')"),
    )
    op.create_index("ix_practice_reviews_owner_id", "practice_reviews", ["owner_id"])


def downgrade():
    op.drop_table("practice_reviews")

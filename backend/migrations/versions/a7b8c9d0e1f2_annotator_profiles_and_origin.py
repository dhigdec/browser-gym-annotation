"""annotator profiles + per-annotator gym-correction origin link

annotator: display_name, avatar_hue, last_login_at, is_active — profile fields for
the multi-annotator login/profile UI.
review_session.origin_session_id: for a SYSTEM gym run produced by an annotator's
correction, the human session that triggered it — so a corrected re-benchmark
scores from that annotator's own correction, not another's (verdict isolation).

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-22 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("annotator", sa.Column("display_name", sa.String(length=80), nullable=True))
    op.add_column("annotator", sa.Column("avatar_hue", sa.Integer(), nullable=False, server_default="210"))
    op.add_column("annotator", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("annotator", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("review_session", sa.Column("origin_session_id", sa.Uuid(), nullable=True))
    op.create_index("ix_review_session_origin_session_id", "review_session", ["origin_session_id"])
    op.create_foreign_key(
        "fk_review_session_origin", "review_session", "review_session",
        ["origin_session_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_session_origin", "review_session", type_="foreignkey")
    op.drop_index("ix_review_session_origin_session_id", table_name="review_session")
    op.drop_column("review_session", "origin_session_id")
    op.drop_column("annotator", "is_active")
    op.drop_column("annotator", "last_login_at")
    op.drop_column("annotator", "avatar_hue")
    op.drop_column("annotator", "display_name")

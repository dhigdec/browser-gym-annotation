"""persist review progress (review_session.reviewed_through) + annotator.password_hash

reviewed_through: the granular per-step review progress, so every verify/approve
click persists and survives a refresh.
password_hash: the (nullable) column the minimal-auth login writes to.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-21 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("review_session", sa.Column("reviewed_through", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("annotator", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("annotator", "password_hash")
    op.drop_column("review_session", "reviewed_through")

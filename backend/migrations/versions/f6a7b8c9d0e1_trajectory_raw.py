"""persist the full review payload per run (trajectory.raw)

raw: the exact review payload a run produced (task + steps + verifiers + tabs +
backendState + gymResume world). Persisted for gym runs so reopening a gym task
replays the SAME run instead of re-driving a fresh, stochastic agent each time —
which would leave a saved correction fork restoring onto a different trajectory.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trajectory", sa.Column("raw", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("trajectory", "raw")

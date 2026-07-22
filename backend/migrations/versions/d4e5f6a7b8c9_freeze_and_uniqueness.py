"""freeze submitted samples + uniqueness backstops

Cluster A: add submission.snapshot (the deliverable frozen at submit time).
Cluster B: one submission per session, one (session_id, version) per suite —
enforced with unique constraints so concurrent writes can't double-insert.

Existing rows are de-duplicated first (idempotent no-op on a clean DB):
  * duplicate (session_id, version) verifier_suites are renumbered sequentially
    (data preserved — nothing is deleted),
  * duplicate submissions per session are collapsed to one (the adjudicated
    golden if any, else the earliest), deleting the extras.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-21 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cluster A — freeze column
    op.add_column("submission", sa.Column("snapshot", sa.JSON(), nullable=True))

    # Cluster B — clean up existing violations before constraining.
    # Renumber duplicate suite versions (preserves every row + its verifiers/runs).
    op.execute(
        """
        UPDATE verifier_suite vs
        SET version = d.rn
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY session_id ORDER BY version ASC, created_at ASC, id ASC
            ) AS rn
            FROM verifier_suite
        ) d
        WHERE vs.id = d.id AND vs.version <> d.rn
        """
    )
    # Collapse duplicate submissions per session — keep the accepted one, else the
    # earliest; delete the rest (submissions have no children).
    op.execute(
        """
        DELETE FROM submission s
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY session_id ORDER BY accepted DESC, created_at ASC, id ASC
            ) AS rn
            FROM submission
        ) d
        WHERE s.id = d.id AND d.rn > 1
        """
    )

    op.create_unique_constraint(
        "uq_verifier_suite_session_version", "verifier_suite", ["session_id", "version"]
    )
    op.create_unique_constraint("uq_submission_session", "submission", ["session_id"])


def downgrade() -> None:
    op.drop_constraint("uq_submission_session", "submission", type_="unique")
    op.drop_constraint("uq_verifier_suite_session_version", "verifier_suite", type_="unique")
    op.drop_column("submission", "snapshot")

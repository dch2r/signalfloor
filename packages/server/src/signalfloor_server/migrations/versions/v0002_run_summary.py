"""Store the case count and mean score on each run, and index runs for listing.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the columns as nullable, fill them from existing cases, then make them required.
    # Adding them as NOT NULL straight away fails on a database that already has runs.
    op.add_column("runs", sa.Column("n_cases", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("mean_score", sa.Double(), nullable=True))
    op.execute(
        """
        update runs set n_cases = s.n, mean_score = s.mean
        from (
            select run_id, count(*) as n, avg(score) as mean from case_results group by run_id
        ) as s
        where runs.id = s.run_id
        """
    )
    # A run with no cases can only come from a manual insert. Give it zeros rather than fail.
    op.execute("update runs set n_cases = 0, mean_score = 0 where n_cases is null")
    op.alter_column("runs", "n_cases", nullable=False)
    op.alter_column("runs", "mean_score", nullable=False)

    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_index("ix_runs_labels", "runs", ["labels"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_runs_labels", table_name="runs")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_column("runs", "mean_score")
    op.drop_column("runs", "n_cases")

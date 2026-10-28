"""Store OpenTelemetry spans and link cases to their traces.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("case_results", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.create_table(
        "spans",
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("parent_span_id", sa.String(length=16), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ns", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=5), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id", "span_id"),
    )
    op.create_index("ix_spans_start_time", "spans", ["start_time"])


def downgrade() -> None:
    op.drop_index("ix_spans_start_time", table_name="spans")
    op.drop_table("spans")
    op.drop_column("case_results", "trace_id")

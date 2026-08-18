"""Add authentication verification state and visits.

Revision ID: 0002_location_slice
Revises: 0001_foundation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_location_slice"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_places_boundary_geography_gist",
        "places",
        [sa.text("(boundary::geography)")],
        postgresql_using="gist",
    )

    op.create_table(
        "visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "place_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("places.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "entered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "exited_at IS NULL OR exited_at >= entered_at",
            name="ck_visits_exit_after_entry",
        ),
    )
    op.create_index(
        "uq_visits_one_active_per_user",
        "visits",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("exited_at IS NULL"),
    )
    op.create_index(
        "ix_visits_user_entered",
        "visits",
        ["user_id", sa.text("entered_at DESC")],
    )
    op.create_index(
        "ix_visits_place_entered",
        "visits",
        ["place_id", sa.text("entered_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_visits_place_entered", table_name="visits")
    op.drop_index("ix_visits_user_entered", table_name="visits")
    op.drop_index("uq_visits_one_active_per_user", table_name="visits")
    op.drop_table("visits")
    op.drop_index("ix_places_boundary_geography_gist", table_name="places")
    op.drop_column("users", "email_verified_at")

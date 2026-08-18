"""Create the Milestones 1-2 foundation schema.

Revision ID: 0001_foundation
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handle", sa.String(32), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("char_length(handle) BETWEEN 3 AND 32", name="ck_users_handle_length"),
        sa.CheckConstraint("char_length(email) BETWEEN 3 AND 254", name="ck_users_email_length"),
        sa.CheckConstraint(
            "char_length(password_hash) BETWEEN 20 AND 255", name="ck_users_password_hash_length"
        ),
    )
    op.create_index("uq_users_handle_ci", "users", [sa.text("lower(handle)")], unique=True)
    op.create_index("uq_users_email_ci", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "places",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("osm_type", sa.String(16), nullable=False),
        sa.Column("osm_id", sa.BigInteger(), nullable=False),
        sa.Column("osm_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "parent_place_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("places.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "boundary",
            geoalchemy2.Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("osm_type IN ('node', 'way', 'relation')", name="ck_places_osm_type"),
        sa.CheckConstraint("osm_id > 0", name="ck_places_osm_id_positive"),
        sa.CheckConstraint("osm_version > 0", name="ck_places_osm_version_positive"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="ck_places_name_length"),
        sa.UniqueConstraint("osm_type", "osm_id", name="uq_places_osm_identity"),
    )
    op.create_index("ix_places_boundary_gist", "places", ["boundary"], postgresql_using="gist")

    op.create_table(
        "forum_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "place_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("places.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 2000", name="ck_forum_posts_body_length"
        ),
    )
    op.create_index(
        "ix_forum_posts_place_created", "forum_posts", ["place_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "forum_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("forum_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 1000", name="ck_forum_comments_body_length"
        ),
    )
    op.create_index(
        "ix_forum_comments_post_created", "forum_comments", ["post_id", sa.text("created_at ASC")]
    )

    op.create_table(
        "seed_registry",
        sa.Column("seed_version", sa.String(64), primary_key=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "char_length(seed_version) BETWEEN 1 AND 64", name="ck_seed_registry_version_length"
        ),
    )


def downgrade() -> None:
    op.drop_table("seed_registry")
    op.drop_index("ix_forum_comments_post_created", table_name="forum_comments")
    op.drop_table("forum_comments")
    op.drop_index("ix_forum_posts_place_created", table_name="forum_posts")
    op.drop_table("forum_posts")
    op.drop_index("ix_places_boundary_gist", table_name="places", postgresql_using="gist")
    op.drop_table("places")
    op.drop_index("uq_users_email_ci", table_name="users")
    op.drop_index("uq_users_handle_ci", table_name="users")
    op.drop_table("users")

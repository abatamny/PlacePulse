from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("char_length(handle) BETWEEN 3 AND 32", name="ck_users_handle_length"),
        CheckConstraint("char_length(email) BETWEEN 3 AND 254", name="ck_users_email_length"),
        CheckConstraint(
            "char_length(password_hash) BETWEEN 20 AND 255", name="ck_users_password_hash_length"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    handle: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (
        CheckConstraint("osm_type IN ('node', 'way', 'relation')", name="ck_places_osm_type"),
        CheckConstraint("osm_id > 0", name="ck_places_osm_id_positive"),
        CheckConstraint("osm_version > 0", name="ck_places_osm_version_positive"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="ck_places_name_length"),
        UniqueConstraint("osm_type", "osm_id", name="uq_places_osm_identity"),
        Index("ix_places_boundary_gist", "boundary", postgresql_using="gist"),
        Index(
            "ix_places_boundary_geography_gist",
            text("(boundary::geography)"),
            postgresql_using="gist",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    osm_type: Mapped[str] = mapped_column(String(16), nullable=False)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    osm_version: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_place_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="SET NULL"), nullable=True
    )
    boundary: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForumPost(Base):
    __tablename__ = "forum_posts"
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="ck_forum_posts_body_length"),
        Index("ix_forum_posts_place_created", "place_id", desc("created_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForumComment(Base):
    __tablename__ = "forum_comments"
    __table_args__ = (
        CheckConstraint(
            "char_length(body) BETWEEN 1 AND 1000", name="ck_forum_comments_body_length"
        ),
        Index("ix_forum_comments_post_created", "post_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forum_posts.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SeedRegistry(Base):
    __tablename__ = "seed_registry"
    __table_args__ = (
        CheckConstraint(
            "char_length(seed_version) BETWEEN 1 AND 64", name="ck_seed_registry_version_length"
        ),
    )

    seed_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        CheckConstraint(
            "exited_at IS NULL OR exited_at >= entered_at",
            name="ck_visits_exit_after_entry",
        ),
        Index(
            "uq_visits_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("exited_at IS NULL"),
        ),
        Index("ix_visits_user_entered", "user_id", desc("entered_at")),
        Index("ix_visits_place_entered", "place_id", desc("entered_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("places.id", ondelete="RESTRICT"), nullable=False
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("uq_users_handle_ci", func.lower(User.handle), unique=True)
Index("uq_users_email_ci", func.lower(User.email), unique=True)

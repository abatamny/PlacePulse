from __future__ import annotations

from geoalchemy2 import Geometry

from placepulse.models import Base


def test_foundation_metadata_declares_expected_tables_and_spatial_type() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "places",
        "forum_posts",
        "forum_comments",
        "seed_registry",
    }
    boundary = Base.metadata.tables["places"].c.boundary
    assert isinstance(boundary.type, Geometry)
    assert boundary.type.geometry_type == "MULTIPOLYGON"
    assert boundary.type.srid == 4326

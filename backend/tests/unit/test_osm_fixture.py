from __future__ import annotations

from pathlib import Path

import pytest

from placepulse.bootstrap import FIXTURE_PATH, load_and_validate_fixture


def _ring_covers_point(ring: list[list[float]], longitude: float, latitude: float) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > latitude) != (y2 > latitude):
            crossing = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing:
                inside = not inside
        previous = current
    return inside


def test_fixture_is_exact_campus_revision_and_covers_supplied_point() -> None:
    feature = load_and_validate_fixture()
    assert feature["properties"]["osm_id"] == 66_098_525
    assert feature["properties"]["osm_version"] == 35
    assert feature["properties"]["attribution"] == "© OpenStreetMap contributors"
    ring = feature["geometry"]["coordinates"][0]
    assert _ring_covers_point(ring, 35.021595, 32.777691)


def test_fixture_validation_rejects_a_non_closed_ring(tmp_path: Path) -> None:
    broken = tmp_path / "broken.geojson"
    source = FIXTURE_PATH.read_text(encoding="utf-8")
    broken.write_text(
        source.replace("[35.0152537,32.7784636]]]", "[35.1,32.8]]]"), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="not closed"):
        load_and_validate_fixture(broken)

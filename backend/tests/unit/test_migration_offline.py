from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from placepulse.config import get_settings


def test_foundation_migration_renders_from_an_empty_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    postgres_secret = tmp_path / "postgres_password"
    postgres_secret.write_text("offline/%-render-password\n", encoding="utf-8")
    monkeypatch.setenv("PLACEPULSE_POSTGRES_PASSWORD_FILE", str(postgres_secret))
    get_settings.cache_clear()
    try:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        command.upgrade(config, "head", sql=True)
        rendered = capsys.readouterr().out
    finally:
        get_settings.cache_clear()
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in rendered
    assert "geometry(MULTIPOLYGON,4326)" in rendered
    assert "CREATE INDEX ix_places_boundary_gist" in rendered
    assert "offline" not in rendered
    assert "render-password" not in rendered

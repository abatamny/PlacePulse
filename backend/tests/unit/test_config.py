from __future__ import annotations

from pathlib import Path

import pytest

from placepulse.config import Settings, read_secret


def test_database_url_escapes_password_without_mutating_it(settings: Settings) -> None:
    settings.postgres_password_file.write_text("spaces + / ? #\n", encoding="utf-8")
    url = settings.database_url
    assert url.password == "spaces + / ? #"
    assert "spaces + / ? #" not in url.render_as_string(hide_password=True)


def test_missing_secret_has_sanitized_error(tmp_path: Path) -> None:
    missing = tmp_path / "not-present"
    with pytest.raises(
        RuntimeError, match="Required secret file for postgres_password is unavailable"
    ) as exc_info:
        read_secret(missing, "postgres_password")
    assert str(missing) not in str(exc_info.value)

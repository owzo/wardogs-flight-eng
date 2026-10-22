"""Config directory and logging setup."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from wardogs_flight_eng.runtime import paths


@pytest.fixture
def local_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point LOCALAPPDATA at ``tmp_path``; remove any handlers the test adds."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    yield tmp_path
    for handler in [h for h in root.handlers if h not in before]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)


def test_config_dir_is_created_under_local_appdata(local_appdata: Path) -> None:
    path = paths.config_dir()
    assert path == local_appdata / "WardogsFlightEng" and path.is_dir()


def test_config_dir_falls_back_to_home_without_local_appdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    expected = tmp_path / "AppData" / "Local" / "WardogsFlightEng"
    assert paths.config_dir() == expected and expected.is_dir()


def test_setup_logging_is_idempotent(local_appdata: Path) -> None:
    root = logging.getLogger()
    before = len(root.handlers)
    paths.setup_logging(verbose=False)
    assert root.level == logging.INFO
    paths.setup_logging(verbose=True)
    assert len(root.handlers) == before + 2 and root.level == logging.DEBUG
    logging.getLogger("wardogs_flight_eng.test").info("hello log file")
    for handler in root.handlers:
        handler.flush()
    log_file = local_appdata / "WardogsFlightEng" / "logs" / "wardogs-flight-eng.log"
    assert "hello log file" in log_file.read_text(encoding="utf-8")

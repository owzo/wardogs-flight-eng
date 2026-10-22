"""Per-user configuration directory and the application's logging setup."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_DIR_NAME = "WardogsFlightEng"
LOG_FILE_NAME = "wardogs-flight-eng.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_FILE_HANDLER = "wardogs-flight-eng-file"
_STDERR_HANDLER = "wardogs-flight-eng-stderr"


def config_dir() -> Path:
    """``%LOCALAPPDATA%\\WardogsFlightEng``, created on first use."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _named(handler: logging.Handler, name: str) -> logging.Handler:
    handler.set_name(name)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def setup_logging(verbose: bool) -> None:
    """Log to a rotating file in ``config_dir()/logs`` and to stderr.

    Level is DEBUG when ``verbose`` else INFO. Calling again only updates the
    level; the handlers are installed once.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    installed = {handler.get_name() for handler in root.handlers}
    if _FILE_HANDLER not in installed:
        logs = config_dir() / "logs"
        logs.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            logs / LOG_FILE_NAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        root.addHandler(_named(file_handler, _FILE_HANDLER))
    if _STDERR_HANDLER not in installed:
        root.addHandler(_named(logging.StreamHandler(sys.stderr), _STDERR_HANDLER))

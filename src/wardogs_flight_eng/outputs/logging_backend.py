"""JSONL force logger: the no-hardware acceptance path.

One JSON object per command, one per line::

    {"t": 0.01, "kind": "spring", "axis": "pitch", "center": 0.0, ...}
    {"t": 0.01, "kind": "all_off"}
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)

logger = logging.getLogger(__name__)

_KINDS: dict[type, str] = {
    SpringCommand: "spring",
    SineCommand: "sine",
    PulseCommand: "pulse",
    TransientCommand: "transient",
    AllOffCommand: "all_off",
}


def _record(t: float, command: Command) -> dict[str, Any]:
    fields = asdict(command)
    if "axis" in fields:
        fields["axis"] = str(fields["axis"])
    return {"t": t, "kind": _KINDS[type(command)], **fields}


class LoggingBackend:
    """Writes every applied command to ``path`` as JSON lines.

    The file (and its parent directory) is created on construction and closed
    by ``close``; calls after ``close`` are ignored.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", encoding="utf-8", newline="\n")
        self._last_t = 0.0
        logger.debug("force log opened at %s", self._path)

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        if self._file.closed:
            logger.debug("apply ignored: force log already closed")
            return
        self._last_t = t
        for command in commands:
            self._write(_record(t, command))

    def all_off(self) -> None:
        if self._file.closed:
            logger.debug("all_off ignored: force log already closed")
            return
        self._write({"t": self._last_t, "kind": "all_off"})

    def close(self) -> None:
        if self._file.closed:
            return
        self._file.flush()
        self._file.close()
        logger.debug("force log closed at %s", self._path)

    def _write(self, record: dict[str, Any]) -> None:
        self._file.write(json.dumps(record, sort_keys=False) + "\n")

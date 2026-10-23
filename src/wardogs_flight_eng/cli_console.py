"""The CLI's output, input and failure contract, shared by every subcommand.

All user-facing text goes through ``Console`` (no ``print`` anywhere in the
package); diagnostics go through ``logging``. A subcommand fails by raising
``CliError`` with one of the exit codes below.
"""

import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, TextIO

from wardogs_flight_eng.inputs.sdl_api import SdlApi

EXIT_OK: Final = 0
EXIT_CONFIG: Final = 1
"""Usage, profile, scenario or configuration error; the message names the field."""
EXIT_DEVICE: Final = 2
"""A device is missing, was lost, or SDL failed."""


class CliError(Exception):
    """A subcommand failure carrying its user message and exit code."""

    def __init__(self, message: str, code: int = EXIT_CONFIG) -> None:
        super().__init__(message)
        self.code = code


class LineReader(Protocol):
    """Where interactive answers come from (``sys.stdin`` in production)."""

    def readline(self) -> str: ...


class Console:
    """Writes user-facing lines and tables to one stream."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = sys.stdout if stream is None else stream

    def line(self, text: str = "") -> None:
        self._stream.write(f"{text}\n")
        self._stream.flush()

    def error(self, text: str) -> None:
        self.line(f"error: {text}")

    def table(self, headers: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
        """Left-aligned columns, each as wide as its widest cell."""
        body = [list(row) for row in rows]
        widths = [
            max([len(header), *(len(row[column]) for row in body)])
            for column, header in enumerate(headers)
        ]
        for cells in [list(headers), ["-" * width for width in widths], *body]:
            padded = (
                cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
            )
            self.line("  ".join(padded).rstrip())


@dataclass(frozen=True, slots=True)
class CliContext:
    """What a subcommand may touch: console, SDL (``None`` = real) and stdin."""

    console: Console
    api: SdlApi | None
    stdin: LineReader

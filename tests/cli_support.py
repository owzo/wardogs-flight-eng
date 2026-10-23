"""Helpers for the CLI tests: bound profiles, scripted stdin and a ticking SDL."""

import copy
import io
import json
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdl_support import GUID_PEDALS, GUID_STICK, FakeJoystick, FakeSdl

from wardogs_flight_eng.cli import main
from wardogs_flight_eng.engine.profile import PROFILES_DIR
from wardogs_flight_eng.inputs.sdl_api import SdlApi

PACKAGED = PROFILES_DIR / "littlebird-miniguns.json"

BOUND_MAP: dict[str, Any] = {
    "devices": {
        "base": {"guid": GUID_STICK, "product": None},
        "pedals": {"guid": GUID_PEDALS, "product": None},
    },
    "axes": {
        "pitch": {"device": "base", "axis": 1},
        "roll": {"device": "base", "axis": 0},
        "collective": {"device": "base", "axis": 2},
        "pedals": {"device": "pedals", "axis": 0},
    },
    "buttons": {"trim_lock": {"device": "base", "button": 0}},
    "calibration": {
        "collective_bottom_raw": -1.0,
        "collective_top_raw": 1.0,
        "pedals_center_raw": 0.0,
    },
}


def packaged_document() -> dict[str, Any]:
    """The shipped littlebird-miniguns profile (empty device map) as a dict."""
    document: dict[str, Any] = json.loads(PACKAGED.read_text(encoding="utf-8"))
    return document


def bound_document() -> dict[str, Any]:
    """The shipped profile with ``BOUND_MAP`` as its device map."""
    document = packaged_document()
    document["device_map"] = copy.deepcopy(BOUND_MAP)
    return document


def write_profile(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


@dataclass(frozen=True)
class CliRun:
    code: int
    output: str


def invoke(
    argv: list[str],
    api: SdlApi | None = None,
    stdin: "ScriptedStdin | None" = None,
) -> CliRun:
    """Run ``main`` with a captured console; ``api`` defaults to an empty fake."""
    out = io.StringIO()
    code = main(
        argv,
        console=out,
        api=FakeSdl() if api is None else api,
        stdin=ScriptedStdin() if stdin is None else stdin,
    )
    return CliRun(code, out.getvalue())


class ScriptedStdin:
    """Each ``readline`` runs the next action (e.g. moving an axis), then is Enter.

    With no actions left it returns ``""``: the stream is closed.
    """

    def __init__(self, *actions: Callable[[], None]) -> None:
        self._actions = list(actions)
        self.reads = 0

    def readline(self) -> str:
        self.reads += 1
        if not self._actions:
            return ""
        self._actions.pop(0)()
        return "\n"


class TickingSdl(FakeSdl):
    """A fake SDL that calls ``then(self)`` on the ``after``-th joystick update."""

    def __init__(
        self,
        *joysticks: FakeJoystick,
        after: int,
        then: Callable[["TickingSdl"], None],
    ) -> None:
        super().__init__(*joysticks)
        self._after = after
        self._then = then
        self.updates = 0

    def SDL_JoystickUpdate(self) -> None:
        super().SDL_JoystickUpdate()
        self.updates += 1
        if self.updates == self._after:
            self._then(self)


def joysticks_released(fake: FakeSdl) -> bool:
    """The last two joystick closes are the stick and the pedals."""
    closes = fake.args("SDL_JoystickClose")[-2:]
    return sorted(closes) == sorted([(GUID_STICK,), (GUID_PEDALS,)])


def detach_all(fake: FakeSdl) -> None:
    for joystick in fake.joysticks:
        joystick.attached = False


def press_ctrl_c(_fake: FakeSdl) -> None:
    signal.raise_signal(signal.SIGINT)

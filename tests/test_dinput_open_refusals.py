"""Opening the base: the two set-up properties a driver may refuse as unsupported."""

import logging

import pytest
from dinput_haptic_support import sdl_guid
from dinput_support import FakeDirectInput, ab9

from wardogs_flight_eng.inputs import dinput_api as di
from wardogs_flight_eng.inputs.dinput_api import DInputError
from wardogs_flight_eng.inputs.dinput_device import open_dinput_joystick
from wardogs_flight_eng.inputs.protocol import DeviceLostError

E_NOTIMPL = -2147467263  # 0x80004001, DIERR_UNSUPPORTED
E_INVALIDARG = -2147024809  # 0x80070057
REFUSALS = [
    (
        "set_autocenter_off",
        "the base refused DIPROP_AUTOCENTER (unsupported); "
        "its own centring spring may add to Flight Eng's",
    ),
    (
        "set_ff_gain",
        "the base refused DIPROP_FFGAIN (unsupported); "
        "forces may be weaker than commanded",
    ),
]


def test_unsupported_is_stored_signed() -> None:
    assert di.DIERR_UNSUPPORTED == E_NOTIMPL


@pytest.mark.parametrize(("call", "warning"), REFUSALS, ids=["autocenter", "gain"])
def test_an_unsupported_property_warns_once_and_the_open_goes_on(
    call: str, warning: str, caplog: pytest.LogCaptureFixture
) -> None:
    base = ab9()
    fake = FakeDirectInput(base)
    fake.fail[call] = E_NOTIMPL
    with caplog.at_level(logging.WARNING):
        joystick = open_dinput_joystick(fake, sdl_guid(base))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == [warning]
    assert joystick.alive and base.acquired and base.actuators_on
    assert "release_device" not in fake.names()


@pytest.mark.parametrize("call", [call for call, _ in REFUSALS])
@pytest.mark.parametrize(
    ("code", "error"),
    [(E_INVALIDARG, DInputError), (di.DIERR_INPUTLOST, DeviceLostError)],
)
def test_any_other_refusal_still_aborts_and_releases(
    call: str, code: int, error: type[Exception]
) -> None:
    base = ab9()
    fake = FakeDirectInput(base)
    fake.fail[call] = code
    with pytest.raises(error, match=call):
        open_dinput_joystick(fake, sdl_guid(base))
    assert fake.names()[-2:] == [call, "release_device"]
    assert not base.acquired

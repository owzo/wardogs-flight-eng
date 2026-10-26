"""The two open-sequence refusals a base may make without aborting the open.

SDL's haptic layer goes on when a driver refuses ``DIPROP_AUTOCENTER`` or
``DIPROP_FFGAIN``. Flight Eng goes on only when the refusal is
``DIERR_UNSUPPORTED``, logging one warning for it; any other failure of those
two calls stays fatal, judged by ``dinput_device.checked``.
"""

import logging

from wardogs_flight_eng.inputs.dinput_api import DI_OK, DIERR_UNSUPPORTED

__all__ = ["UNSUPPORTED_WARNINGS", "tolerate_unsupported"]

log = logging.getLogger(__name__)

UNSUPPORTED_WARNINGS = {
    "set_autocenter_off": (
        "the base refused DIPROP_AUTOCENTER (unsupported); its own centring "
        "spring may add to Flight Eng's"
    ),
    "set_ff_gain": (
        "the base refused DIPROP_FFGAIN (unsupported); forces may be weaker "
        "than commanded"
    ),
}


def tolerate_unsupported(status: int, call: str) -> int:
    """``DI_OK`` after one warning when ``call`` is a tolerated property that
    the driver refused as unsupported; otherwise ``status`` unchanged."""
    if status != DIERR_UNSUPPORTED or call not in UNSUPPORTED_WARNINGS:
        return status
    log.warning(UNSUPPORTED_WARNINGS[call])
    return DI_OK

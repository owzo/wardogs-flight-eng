"""Windows plumbing under the DirectInput adapter: DLLs, COM calls, the window.

A COM call reads the function pointer from the interface's vtable and calls
it through a ``WINFUNCTYPE`` prototype whose result is the raw ``HRESULT``
(a signed ``LONG``, never ctypes' raising ``HRESULT`` type). The hidden
window exists only because ``SetCooperativeLevel`` needs an ``HWND``: like
SDL's helper window it is a message-only window (parent ``HWND_MESSAGE``),
so it receives no broadcast ``SendMessage`` traffic that an unpumped thread
would block; its class is registered once per process with
``DefWindowProcW`` as the window procedure, and it is never shown. Off Windows the
module imports (so the pure layers and tests can name it) but loading a DLL
raises ``DInputError``.
"""

import ctypes
import logging
import sys
from ctypes import (
    POINTER,
    Structure,
    c_int,
    c_int32,
    c_uint16,
    c_uint32,
    c_ulong,
    c_void_p,
    c_wchar_p,
)
from typing import Any

from wardogs_flight_eng.inputs.dinput_api import DInputError
from wardogs_flight_eng.inputs.dinput_guids import RELEASE_SLOT

log = logging.getLogger(__name__)

HRESULT = c_int32  # signed, so failures come back as negative ints
WINDOW_CLASS = "WardogsFlightEngDirectInput"
WINDOW_TITLE = "WardogsFlightEng"
WS_OVERLAPPED = 0x00000000
HWND_MESSAGE = c_void_p(-3)  # ((HWND)-3): the message-only parent
ERROR_CLASS_ALREADY_EXISTS = 1410

if sys.platform == "win32":
    FUNCTYPE = ctypes.WINFUNCTYPE

    def load_library(name: str) -> ctypes.CDLL:
        try:
            return ctypes.WinDLL(name, use_last_error=True)
        except OSError as err:
            raise DInputError(f"cannot load {name}.dll: {err}") from err

    def last_error() -> int:
        return ctypes.get_last_error()

else:
    FUNCTYPE = ctypes.CFUNCTYPE

    def load_library(name: str) -> ctypes.CDLL:
        raise DInputError(f"DirectInput 8 needs Windows, not {sys.platform}")

    def last_error() -> int:
        return 0


def method(slot: int, *argtypes: Any, restype: Any = HRESULT) -> tuple[int, Any]:
    """A vtable ``slot`` and its prototype (``this`` is the first argument)."""
    return slot, FUNCTYPE(restype, c_void_p, *argtypes)


RELEASE = method(RELEASE_SLOT, restype=c_ulong)


def com_call(iface: int, entry: tuple[int, Any], *args: Any) -> int:
    """Call ``entry`` (from ``method``) on the interface pointer ``iface``."""
    slot, prototype = entry
    vtable = ctypes.cast(iface, POINTER(c_void_p))[0]
    function = prototype(ctypes.cast(vtable, POINTER(c_void_p))[slot])
    return int(function(iface, *args))


def release(iface: int, what: str) -> None:
    """``IUnknown::Release``; a fault is logged, never raised."""
    try:
        com_call(iface, RELEASE)
    except OSError as err:
        log.warning("DirectInput %s release failed: %s", what, err)


class WNDCLASSEXW(Structure):
    _fields_ = [
        ("cbSize", c_uint32),
        ("style", c_uint32),
        ("lpfnWndProc", c_void_p),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", c_void_p),
        ("hIcon", c_void_p),
        ("hCursor", c_void_p),
        ("hbrBackground", c_void_p),
        ("lpszMenuName", c_wchar_p),
        ("lpszClassName", c_wchar_p),
        ("hIconSm", c_void_p),
    ]


_WINDOW_ARGS = (c_uint32, c_wchar_p, c_wchar_p, c_uint32, *(c_int,) * 4)
_SIGNATURES: dict[tuple[str, str], tuple[Any, tuple[Any, ...]]] = {
    ("kernel32", "GetModuleHandleW"): (c_void_p, (c_wchar_p,)),
    ("user32", "RegisterClassExW"): (c_uint16, (c_void_p,)),
    ("user32", "CreateWindowExW"): (c_void_p, (*_WINDOW_ARGS, *(c_void_p,) * 4)),
    ("user32", "DestroyWindow"): (c_int, (c_void_p,)),
    ("dinput8", "DirectInput8Create"): (
        HRESULT,
        (c_void_p, c_uint32, *(c_void_p,) * 3),
    ),
}


class Win32:
    """``kernel32``, ``user32`` and ``dinput8`` with the prototypes used here."""

    def __init__(self) -> None:
        names = ("kernel32", "user32", "dinput8")
        self.dlls = {name: load_library(name) for name in names}
        self.functions: dict[str, Any] = {}
        for (dll, name), (restype, argtypes) in _SIGNATURES.items():
            function = getattr(self.dlls[dll], name)
            function.restype, function.argtypes = restype, argtypes
            self.functions[name] = function
        self.class_registered = False

    def call(self, name: str, *args: Any) -> Any:
        return self.functions[name](*args)


_win32: Win32 | None = None


def win32() -> Win32:
    """The DLLs, loaded on the first call."""
    global _win32
    if _win32 is None:
        _win32 = Win32()
    return _win32


def _register_class(api: Win32, hinstance: int) -> None:
    if api.class_registered:
        return
    wndclass = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW))
    wndclass.lpfnWndProc = ctypes.cast(api.dlls["user32"].DefWindowProcW, c_void_p)
    wndclass.hInstance, wndclass.lpszClassName = hinstance, WINDOW_CLASS
    atom = api.call("RegisterClassExW", ctypes.byref(wndclass))
    if not atom and last_error() != ERROR_CLASS_ALREADY_EXISTS:
        raise DInputError(f"RegisterClassExW failed: error {last_error()}")
    api.class_registered = True


def create_window(api: Win32) -> tuple[int, int]:
    """``(hinstance, hwnd)`` of a new message-only window (never shown)."""
    hinstance = int(api.call("GetModuleHandleW", None) or 0)
    _register_class(api, hinstance)
    position = (0, 0, 0, 0)
    hwnd = api.call(
        "CreateWindowExW",
        0,
        WINDOW_CLASS,
        WINDOW_TITLE,
        WS_OVERLAPPED,
        *position,
        HWND_MESSAGE,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        raise DInputError(f"CreateWindowExW failed: error {last_error()}")
    return hinstance, int(hwnd)


def destroy_window(api: Win32, hwnd: int) -> None:
    """``DestroyWindow``; a failure is logged, never raised."""
    if not api.call("DestroyWindow", hwnd):
        log.warning("DestroyWindow failed: error %d", last_error())

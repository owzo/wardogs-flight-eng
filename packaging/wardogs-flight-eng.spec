# PyInstaller spec: one-file console build of Wardogs Flight Eng.
#
#     uv run pyinstaller packaging/wardogs-flight-eng.spec
#
# Produces dist/wardogs-flight-eng.exe. The two package data directories are
# bundled at the same package-relative paths the code resolves at run time
# (``importlib.resources`` for the constants, ``PROFILES_DIR`` for profiles).
# ``sdl2`` is imported by name at run time (inputs/sdl_real.py), so
# PyInstaller's static analysis cannot see it: it and ``sdl2dll`` are listed as
# hidden imports. pyinstaller-hooks-contrib ships no hook for ``sdl2dll``, so
# its SDL2.dll is added as a binary under ``sdl2dll/dll``, where
# ``sdl2dll.get_dllpath()`` looks for it inside the unpacked bundle.
import importlib.util
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller
SRC = ROOT / "src"

datas = [
    (str(SRC / "wardogs_flight_eng/data"), "wardogs_flight_eng/data"),
    (str(SRC / "wardogs_flight_eng/profiles"), "wardogs_flight_eng/profiles"),
]

sdl2dll_spec = importlib.util.find_spec("sdl2dll")
if sdl2dll_spec is None or sdl2dll_spec.origin is None:
    raise SystemExit("pysdl2-dll (package sdl2dll) is not installed; run `uv sync`")
sdl_dll = Path(sdl2dll_spec.origin).parent / "dll" / "SDL2.dll"
if not sdl_dll.is_file():
    raise SystemExit(f"{sdl_dll} not found: pysdl2-dll is installed without binaries")
binaries = [(str(sdl_dll), "sdl2dll/dll")]

a = Analysis(  # noqa: F821
    [str(SRC / "wardogs_flight_eng/__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["sdl2", "sdl2dll"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="wardogs-flight-eng",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    runtime_tmpdir=None,
)

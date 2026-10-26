"""Guard the pure packages and confine ``ctypes`` to the native adapters.

``engine`` and ``constants`` must not import impure code; ``ctypes`` is
imported only by the SDL adapter and the DirectInput adapter modules.
"""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "wardogs_flight_eng"

CLI_MODULES = {
    f"wardogs_flight_eng.{name}"
    for name in (
        "cli",
        "cli_calibrate",
        "cli_console",
        "cli_device_open",
        "cli_devices",
        "cli_dinput_devices",
        "cli_interrupt",
        "cli_offline",
        "cli_preset",
        "cli_profiles",
        "cli_record",
        "cli_run",
        "cli_run_checks",
    )
}

DINPUT_NATIVE = {
    "wardogs_flight_eng.inputs.dinput_real",
    "wardogs_flight_eng.inputs.dinput_structs",
}

FORBIDDEN = {
    "engine": {
        "wardogs_flight_eng.inputs",
        "wardogs_flight_eng.outputs",
        "wardogs_flight_eng.runtime",
        *CLI_MODULES,
        *DINPUT_NATIVE,
        "sdl2",
    },
    "constants": {
        "wardogs_flight_eng.engine",
        "wardogs_flight_eng.inputs",
        "wardogs_flight_eng.outputs",
        "wardogs_flight_eng.runtime",
        *CLI_MODULES,
        *DINPUT_NATIVE,
        "sdl2",
    },
}

# The modules allowed to import ctypes: the SDL adapter, and the DirectInput
# adapter (``dinput_real`` and ``dinput_structs``, split under the 200-line
# limit into the COM plumbing, the built structs and one module per COM
# interface). Every other module, ``dinput_guids`` included, stays ctypes-free.
CTYPES_MODULES = {
    f"inputs/{name}.py"
    for name in (
        "sdl_real",
        "dinput_real",
        "dinput_real_root",
        "dinput_real_device",
        "dinput_real_effects",
        "dinput_com",
        "dinput_structs",
        "dinput_format",
    )
}


def _absolute_imports(source: str, package: str = "") -> set[str]:
    """Return every dotted module name imported by ``source``.

    Relative imports are resolved against ``package`` (the dotted name of the
    package containing the module) so they cannot dodge the check.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, package)
            if base:
                modules.add(base)
                modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


def _resolve_from(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    parts = package.split(".")
    anchor = parts[: len(parts) - (node.level - 1)]
    return ".".join([*anchor, *([node.module] if node.module else [])])


def _violates(module: str, prefixes: set[str]) -> bool:
    return any(module == p or module.startswith(f"{p}.") for p in prefixes)


def test_pure_packages_import_nothing_impure() -> None:
    violations: list[str] = []
    for package, prefixes in FORBIDDEN.items():
        assert (PACKAGE_ROOT / package).is_dir(), f"missing package {package}"
        for path in sorted((PACKAGE_ROOT / package).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            rel = path.relative_to(PACKAGE_ROOT).parent.as_posix().replace("/", ".")
            imports = _absolute_imports(source, f"wardogs_flight_eng.{rel}")
            violations.extend(
                f"{path.relative_to(PACKAGE_ROOT)} imports {module}"
                for module in sorted(imports)
                if _violates(module, prefixes)
            )
    assert not violations, "\n".join(violations)


def test_detector_flags_forbidden_imports() -> None:
    source = "import sdl2\nfrom wardogs_flight_eng.inputs import x\nimport os\n"
    found = {m for m in _absolute_imports(source) if _violates(m, FORBIDDEN["engine"])}
    assert found == {"sdl2", "wardogs_flight_eng.inputs", "wardogs_flight_eng.inputs.x"}


def test_detector_resolves_relative_imports() -> None:
    source = "from ..inputs import x\nfrom . import sibling\n"
    found = _absolute_imports(source, "wardogs_flight_eng.engine")
    assert "wardogs_flight_eng.inputs" in found
    assert "wardogs_flight_eng.engine.sibling" in found


def test_constants_forbids_runtime_and_cli() -> None:
    source = "import wardogs_flight_eng.runtime\nfrom wardogs_flight_eng import cli\n"
    found = {
        m for m in _absolute_imports(source) if _violates(m, FORBIDDEN["constants"])
    }
    assert found == {"wardogs_flight_eng.runtime", "wardogs_flight_eng.cli"}


def test_ctypes_is_confined_to_the_native_adapters() -> None:
    importers = {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if _violates_any(_absolute_imports(path.read_text(encoding="utf-8")))
    }
    assert importers <= CTYPES_MODULES, sorted(importers - CTYPES_MODULES)
    assert {"inputs/sdl_real.py", "inputs/dinput_structs.py"} <= importers


def _violates_any(imports: set[str]) -> bool:
    return any(_violates(module, {"ctypes"}) for module in imports)


def test_ctypes_detector_sees_every_import_form() -> None:
    sources = ("import ctypes", "from ctypes import c_int", "import ctypes.util")
    for source in sources:
        assert _violates_any(_absolute_imports(source))
    assert not _violates_any(_absolute_imports("import ctypeslib"))

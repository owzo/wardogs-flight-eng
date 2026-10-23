"""Subcommands that need no hardware: ``dry-run`` and ``show-constants``."""

import argparse
from datetime import datetime
from pathlib import Path

from wardogs_flight_eng.cli_console import EXIT_OK, CliContext, CliError
from wardogs_flight_eng.cli_profiles import load_checked_profile
from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.constants.model import GameConstants, describe
from wardogs_flight_eng.inputs.simulated import Scenario
from wardogs_flight_eng.runtime.dry_run import dry_run
from wardogs_flight_eng.runtime.paths import config_dir

DRY_RUNS_DIR = "dry-runs"
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"


def _scenario(path: Path) -> Scenario:
    try:
        return Scenario.load(path)
    except (OSError, KeyError, TypeError, ValueError) as err:
        detail = err.strerror if isinstance(err, OSError) else err
        raise CliError(f"invalid scenario {path}: {detail}") from err


def dry_run_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Run a scenario through the profile; print where the log and plot went."""
    constants = load_constants()
    profile = load_checked_profile(args.profile, constants)
    scenario = _scenario(args.scenario)
    out: Path | None = args.out
    if out is None:
        stamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        out = config_dir() / DRY_RUNS_DIR / stamp
    try:
        log_path, plot_path = dry_run(profile, constants, scenario, out)
    except RuntimeError as err:
        raise CliError(f"dry run of {args.scenario} failed: {err}") from err
    ctx.console.line(f"force log: {log_path}")
    ctx.console.line(f"plot:      {plot_path}")
    return EXIT_OK


def _airframe_rows(constants: GameConstants) -> list[tuple[str, ...]]:
    return [
        (
            a.key,
            a.plugin,
            describe(a.mass_kg),
            describe(a.main_rotor_rpm),
            describe(a.spool_down_rpm_per_s),
        )
        for a in constants.airframes.values()
    ]


def _weapon_rows(constants: GameConstants) -> list[tuple[str, ...]]:
    return [
        (
            w.key,
            describe(w.rounds_per_minute),
            describe(w.windup_s),
            describe(w.reload_s),
            describe(w.shake_multiplier),
            w.shake or "none",
            describe(w.rounds_per_reload),
        )
        for w in constants.weapons.values()
    ]


def show_constants_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Print the airframe and weapon constants; unknowns as the sentinel."""
    constants = load_constants()
    prov = constants.provenance
    ctx.console.line(
        f"Wardogs game constants: build {prov.build_id}, extracted "
        f"{prov.extracted_at}, mappings {prov.mappings}"
    )
    ctx.console.line()
    ctx.console.line("Airframes")
    ctx.console.table(
        ("key", "plugin", "mass_kg", "main_rotor_rpm", "spool_down_rpm_per_s"),
        _airframe_rows(constants),
    )
    ctx.console.line()
    ctx.console.line("Weapons")
    ctx.console.table(
        (
            "key",
            "rounds_per_minute",
            "windup_s",
            "reload_s",
            "shake_multiplier",
            "shake",
            "rounds_per_reload",
        ),
        _weapon_rows(constants),
    )
    return EXIT_OK

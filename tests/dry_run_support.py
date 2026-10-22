"""Shared helpers for the dry-run and plot tests."""

from pathlib import Path

from wardogs_flight_eng.engine.profile import PROFILES_DIR, Profile, load_profile

SCENARIOS = Path(__file__).parent / "scenarios"


def profile(name: str) -> Profile:
    return load_profile(PROFILES_DIR / f"{name}.json")

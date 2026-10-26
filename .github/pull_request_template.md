<!-- One topic per pull request. Keep the sections; delete the comments. -->

## What changed and why

<!-- Two or three sentences. Link the issue or the spec in docs/superpowers/specs/ if there is one. -->

## How it keeps the ground rules

- [ ] Nothing reads the game (no process, memory, screen, file, network or telemetry access to Wardogs).
- [ ] No game asset contents, keys or mappings are added anywhere.
- [ ] Every force still goes through the clamp, the finite persistent effects, the watchdogs and the release on every exit path.
- [ ] No shipped profile's `feel`, `rotor` or `safety` values change without a hardware report behind the change, and `safety.force_ceiling` is not raised.
- [ ] Procedure numbers live in named constants with a cited source, not in profile JSON.

## Tests

<!-- Name the tests that cover the change. For a bug fix, name the test that fails without the fix. -->

## Gates

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check src tests`
- [ ] `uv run ruff format --check src tests`
- [ ] `uv run mypy` (plain, covers src and tests)
- [ ] Every file under 200 lines, every function under 50

## Hardware

<!-- Was this run on a real base? Which backend? If not, say "not run on hardware" and what the fake layer covered. -->

# Pre-hardware backlog: six small features

Status: owner-directed, 2026-10-25 ("finish anything you can finish before
the hardware gets here, no backlog"). No question round; the calls below
are the author's and are marked so. Builds on the 0.2.0 feel-conditions
design (`2026-10-24-feel-conditions-design.md`). The dinput8 fallback
backend has its own spec (`2026-10-25-dinput8-backend-design.md`).

## Intent

Everything that can be finished and verified without a force base in hand,
so that the first hardware session is a tuning session: the leftovers the
0.2.0 reviews deferred, the two owner decisions left open since 0.1.0,
continuous integration on the public repo, the hold-to-release trim style
real force-trim buttons use, a Moza Cockpit preset emitter so the two
programs never both apply a spring, and a scenario recorder so a real flight
can be replayed through the dry run.

## Goals

1. Deferred-minor wave: every `minor (deferred)` item from the 0.2.0 task
   reviews that is a code or test change, in one pass.
2. Open decisions settled: a rotor buzz floor (`rotor.min_amplitude`) and a
   `--refresh-every-tick` flag on `run`.
3. CI: gates on every push and pull request; an exe artifact on every tag.
4. `feel.trim_style`: `tap` (today) or `hold` (held = slack, released =
   re-anchor), in both feel modes.
5. `make-preset`: write a Moza Cockpit `.preset` from the user's own
   exported preset plus a profile, for division A or B.
6. `record`: capture the real stick, collective and pedals into a scenario
   file with no force output, replayable by `dry-run`.

## Non-goals

- Any feel value change. Placeholders stay placeholders.
- Shipping a `.preset` file (the samples' authors and licences are unknown).
- Auto-publishing GitHub releases from CI (the owner publishes).
- Telemetry, yaw/collective forces, Linux or macOS.
- The dinput8 backend (own spec).

## Anti-goals

- A `hold` trim that moves the anchor anywhere but where the stick is when
  the button is released.
- `record` ever opening the haptic side of the base or commanding a force.
- A preset emitter that invents values the user did not export or set.
- Breaking 0.2.0 profiles again: every new profile field defaults to
  today's behaviour.

## Constraints

- Project rules as before: pure `engine/`, files under 200 lines, functions
  under 50, `logging` not `print`, no bare `except`, no TODOs; gates are
  `uv run pytest -q`, `uv run ruff check src tests`,
  `uv run ruff format --check src tests`, plain `uv run mypy`.
- Every new profile field has a default equal to current behaviour.
- The fail-closed force path is unchanged in shape.

## 1. Deferred-minor wave (decided)

Code and test items only; wording nits ride along where the file is open.

- `cli_profiles.write_calibration` validates through `Profile.from_document`
  so the migration hint reaches that path.
- `engine/profile.py`: the migration hint is appended only when a missing
  field is one of `feel.mode`, `feel.friction`, `feel.damper`,
  `feel.inertia`, `rotor.airspeed_factor`, `estimator`; `MIGRATION_HINT`
  joins `__all__`.
- `outputs/sdl_capabilities.py` and `outputs/sdl_conditions.py`: SDL
  constants read as attributes (`api.SDL_HAPTIC_FRICTION`), never
  `getattr`; a test walks `get_args(ConditionCommand)` and asserts every
  member has a type mapping.
- `ConditionSupport` logs its WARNINGs once at construction (per missing
  kind, or the single "did not report" line); `allows()` is silent.
- `engine/feel.py`: the `clamp_friction is not None` guard becomes an
  `assert` for type narrowing; the spring fade depends on the mode alone.
- `engine/synth.py`: the `all_off` setter and `prime_buttons` are removed
  (`take_over` is the only handoff); `engine/flight_state.py:37` restart
  docstring names `take_over`.
- `outputs/clamp.py`: a `ClampableCommand` alias replaces the repeated
  union; the NaN and over-ceiling clamp tests are parametrised over the
  three condition kinds.
- `README.md:284-287`: the division A/B sentences match
  `docs/reference/community-ffb-references.md` (A: Cockpit conditions low
  or 0; B: Flight Eng supplies damper, inertia, buzz and recoil).
- Tests: `check-device` WARN text pinned verbatim; the mask-0 `run` test
  asserts one haptic open and close, no effect created, devices released;
  a probe open failure exits 2 and releases the joysticks; an
  inverted-binding `condition_effect` test (coefficient unsigned); the
  empty-log plot test asserts the two gain rows; stale test names fixed
  (`test_plot_has_four_rows`, the tau-0 "snap" test); pitch exactly at the
  estimator threshold; `InputEstimator` rejects NaN `tau_s`
  (`not tau_s >= 0`); `take_over` lower clamp; friction boundary
  `== spring / 4`; value tests for littlebird-rockets and lakota.
- `tests/test_dry_run.py` friction filter gains an axis predicate.

## 2. Open decisions (author's calls)

- **Rotor buzz floor.** `rotor.min_amplitude: Unit = 0.0`. A computed buzz
  magnitude below it is emitted as 0 (the sine command keeps its frequency).
  Removes a faint idle hum and the effect restarts a slowly varying tiny
  magnitude would cause. Shipped profiles: 0.0 (no feel change).
- **Refresh flag.** `run --refresh-every-tick` passes
  `refresh_every_tick=True` to `SdlHapticBackend`; default off. The
  environment variable stays for the hardware test. README "Hardware tuning
  pass" step 3 names the flag.

## 3. Continuous integration (decided)

- `.github/workflows/ci.yml`: on `push` and `pull_request` to `main`, a
  matrix of `ubuntu-latest` and `windows-latest`, Python 3.12,
  `astral-sh/setup-uv`, `uv sync --all-groups`, then the four gates. The
  fake SDL makes the suite platform-neutral; the Windows leg proves the
  SDL DLL import and the PyInstaller spec load.
- `.github/workflows/build-exe.yml`: on tags `v*`, `windows-latest`,
  `uv run pyinstaller packaging/wardogs-flight-eng.spec`, then upload
  `dist/wardogs-flight-eng.exe` and a `SHA256SUMS` file as a workflow
  artifact named after the tag. No release is created.
- README Status gains a CI badge line; the release procedure in the README
  says to download the artifact and attach it to the GitHub release.

## 4. Hold-to-release trim (decided)

`feel.trim_style: Literal["tap", "hold"] = "tap"`.

**`tap`** is 0.2.0 behaviour, unchanged.

**`hold`, force_trim mode** (real force-trim release): while `TRIM_LOCK` is
held the spring coefficient slews to 0 over `trim_slew_s` (the stick goes
slack); the anchor does not move. On release, the anchor is set to the
stick position at that instant and the spring slews back to its full
coefficient over `trim_slew_s` about the new anchor. `TRIM_RESET` tap
recentres as today. Friction, damper and inertia are unaffected.

**`hold`, unboosted mode** (momentary clamp): the clamp is engaged while
`TRIM_LOCK` is held and released when it is let go, each through the
existing blend; `TRIM_RESET` is a no-op in this style (there is nothing
latched to reset).

Engine: `FeelModel` gains `hold(pressed: bool, pitch: float, roll: float)`
called every tick with the held state; `FlightEngine._dispatch` routes
`TRIM_LOCK` to `lock()` (tap style, rising edge) or `hold()` (hold style,
level) per the profile. `restart()` also clears any held state. Shipped
profiles stay `tap`. README "Feel modes" documents both styles.

## 5. Moza Cockpit preset emitter (decided)

```
wardogs-flight-eng make-preset --profile <profile.json> --template <your-export.preset>
                               --division A|B --out <new.preset> [--name <text>]
```

- The template is the user's own Cockpit export (JSON, `version` 1.0.3 or
  1.0.4, `device_params` holding the `bacic_*` and `hardware_balancing_*`
  keys). It is read, every key preserved in order, and only the keys below
  rewritten. The output is written with 4-space indent and a trailing
  newline. Missing required keys, a non-object `device_params`, or a
  template that is not JSON are configuration errors naming the key.
- **Division A** (Flight Eng owns spring, friction, damper, inertia, trim):
  `bacic_spring` 0, `bacic_damper` 0, `bacic_friction` 0, `bacic_inertia` 0,
  `bacic_start_force_enble` 0, `hardware_balancing_enable` 0,
  `bacic_gameForceFeedback` 100. Any profile mode.
- **Division B** (Cockpit owns spring and hardware trim): requires a
  `force_trim` profile with `feel.spring_coefficient == 0` (else a
  configuration error naming the rule); `bacic_damper`, `bacic_friction`,
  `bacic_inertia` 0, `hardware_balancing_enable` 1,
  `bacic_gameForceFeedback` 100; `bacic_spring` and the trim button ids are
  left as the template has them (the user's taste).
- Metadata: `name` = `--name` or `"<template name> + Flight Eng <division>"`;
  `uuid` = a new `{uuid4}` in braces; `date` = current Unix seconds as a
  string, matching the template's type. Nothing else changes.
- The command prints a table of every key it changed with old and new
  values and the output path. Tests use a small synthetic template fixture
  with the required keys and a few extra ones; no real preset enters the
  repo.
- README "Moza Cockpit companion settings" gains the command.

## 6. Scenario recorder (decided)

```
wardogs-flight-eng record --profile <profile.json> --out <scenario.json>
                          [--rate 100] [--duration <s>]
```

- Opens the devices named by the profile's `device_map` exactly as `run`
  does (same errors for missing devices) and reads raw axes and buttons at
  `--rate` Hz with a `NullBackend`; it never opens the haptic side and
  never commands a force. Ends on Ctrl+C or after `--duration` seconds.
- Writes a scenario in the existing format: `rate_hz`, the profile's
  `device_map` verbatim, `devices` from the opened devices (alias, axis
  and button counts), and `steps`: at `t 0.0` every axis and button's
  initial value, then a step whenever a raw axis (rounded to 3 decimals) or
  button changes, grouping all changes of one tick under one `t`, and a
  final `{"t": <end>, "set": {}}`. `Scenario.load` must read it back.
- Prints the tick count, duration and step count on exit. README "Try it
  without hardware" gains a paragraph on recording a real flight and
  replaying it with `dry-run`.

## Safety

- `record` constructs no haptic objects; a test asserts no
  `SDL_HapticOpenFromJoystick` call and no force command during a recording.
- `hold` trim is pure engine state; its forces go through the same clamp
  and persistent-effect path. A held `TRIM_LOCK` across a profile switch
  is cleared by `take_over` (restart), so the incoming engine never starts
  slack or clamped.
- `min_amplitude` only ever lowers a magnitude.

## Left to the builder

- The CI matrix cache settings and action versions.
- `record` tick clock (reuse the loop's slot scheduling or a simpler sleep).
- Preset key table formatting and the exact error wording.
- Whether `make-preset` and `record` live in `cli_offline.py`,
  `cli_devices.py` or new `cli_preset.py` / `cli_record.py` modules (file
  size decides).

## Acceptance

1. Gates green on both CI legs; the tag workflow produces an artifact.
2. Every item in section 1 has a commit, and the deferred list in the
   0.2.0 ledger copy is empty of code items.
3. Engine tests: buzz floor; `hold` style in both modes including release
   re-anchoring at the stick position, slack and re-stiffen timing, reset
   behaviour, and restart clearing a held state.
4. `make-preset` tests: A and B rewrites, preserved unknown keys and order,
   B refusal on a non-zero spring or an unboosted profile, metadata, table
   output, error cases.
5. `record` tests against simulated devices: file shape, change-only
   steps, round trip through `Scenario.load`, no haptic open, Ctrl+C and
   duration stop.
6. README updated for every feature; nothing claims a hardware result.

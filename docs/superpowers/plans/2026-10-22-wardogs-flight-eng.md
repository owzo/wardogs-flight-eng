# Wardogs Flight Eng Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Python program that synthesises helicopter force feedback for Wardogs from the pilot's own stick, collective and pedals, testable end-to-end with no hardware attached.

**Architecture:** A pure-logic `engine` package turns one `ControlFrame` per tick into a list of effect `Command` value objects; a `inputs` composite maps any number of HID devices onto the engine's logical channels; an `outputs` backend applies commands to a device (SDL2 haptics) or a log. A fixed-rate runtime loop with a watchdog joins them. The game is never touched.

**Tech Stack:** Python 3.12, uv, pydantic v2 (profile validation), pysdl2 + pysdl2-dll (joystick input and haptic output), pytest, ruff, mypy, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-22-wardogs-flight-eng-design.md`

## Global Constraints

- Windows only; Python `>=3.12`; `uv` project; `ruff` and `mypy --strict` clean on `src` and `tests`.
- `engine/` and `constants/` import nothing from `inputs/`, `outputs/`, `runtime/`, `sdl2`, or `cli`; `tests/test_layering.py` enforces it.
- Never `print()` in `src/`; `logging` only. Never bare `except:`.
- No vJoy, ViGEm, virtual HID, hooks, injected DLLs, or any read of the game process. No pak contents, AES key, or mappings in the repo.
- Every game-derived number lives in `data/wardogs_heli_constants.json` with provenance `build_id "25937608"`, `extracted_at "2026-10-22"`, and its asset / property; an unknown value is JSON `null` and is rendered as `UNKNOWN - WARDOGS GAME VALUE REQUIRED`.
- Every effect other than the trim buttons is additive and transient; nothing else writes the trim centre.
- Force magnitudes leaving a backend are clamped to the profile's `safety.force_ceiling` (default `0.6` of device maximum).
- MIT licence. Files under 200 lines, functions under 50, no `utils.py` / `helpers.py`.

## Review Focus

1. A profile that names a button index beyond the device's button count must fail at start-up with the channel name in the error, never raise inside the loop (Task 8).
2. A collective calibrated with `bottom_raw > top_raw` (inverted axis) must still normalise to `0.0` at the physical bottom and `1.0` at the top (Task 8).
3. Trim lock tapped with the stick at full deflection must leave the spring centre at `±1.0`, slewed, and the spring symmetric about it (Task 4).
4. Fire held continuously through a Reload tap must go silent for the whole reload window and then re-run the wind-up before pulsing again (Task 6).
5. A loop stall (`dt` larger than `safety.watchdog_s`) must produce an `AllOffCommand`, not a burst of catch-up pulses (Task 7) — and the runtime must zero the device when the input source stalls (Task 10).

---

## File structure

```
pyproject.toml  LICENSE  README.md  .gitignore
packaging/wardogs-flight-eng.spec
src/wardogs_flight_eng/
  __init__.py  __main__.py  cli.py
  data/wardogs_heli_constants.json      (package data, shipped inside the .exe)
  profiles/{littlebird-miniguns,littlebird-rockets,lakota,havoc}.json
  engine/
    frame.py       ControlFrame, Button (logical input per tick)
    commands.py    Axis, SpringCommand, SineCommand, PulseCommand, AllOffCommand
    profile.py     Profile model (pydantic) + load_profile()
    trim.py        TrimState
    rotor.py       RotorModel
    weapon.py      WeaponModel
    synth.py       FlightEngine
  constants/
    model.py       GameConstants, Airframe, Weapon dataclasses, UNKNOWN sentinel
    loader.py      load_constants()
  inputs/
    protocol.py    InputDevice protocol, DeviceMap/ChannelBinding (from profile)
    composite.py   CompositeInput
    simulated.py   SimulatedDevice, Scenario
    sdl_device.py  SdlDevice, enumerate_devices()
  outputs/
    protocol.py    ForceBackend protocol
    clamp.py       ClampedBackend
    logging_backend.py  LoggingBackend (JSONL)
    null_backend.py
    sdl_haptic.py  SdlHapticBackend, probe_primitives()
    sdl_persistent.py  PersistentEffects, SineClock (upload on change, half-length re-run)
  runtime/
    loop.py        run_loop()
    plot.py        write_plot_html()
    paths.py       config_dir(), log setup
tests/            one test module per source module, plus test_layering.py,
                  test_cli.py, scenarios/*.json
```

---

### Task 1: Project scaffold and layering test

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `README.md`, `.gitignore`, `src/wardogs_flight_eng/__init__.py`, `src/wardogs_flight_eng/__main__.py`, empty `__init__.py` in `engine/`, `constants/`, `inputs/`, `outputs/`, `runtime/`
- Test: `tests/test_layering.py`

**Interfaces:**
- Produces: package name `wardogs_flight_eng`, version `0.1.0`, console script `wardogs-flight-eng = wardogs_flight_eng.cli:main`.

- [ ] **Step 1: The repo already exists (docs committed on `main`, work on branch `build/v1`); do not `git init`. Run `uv init --package --python 3.12` in it (if `uv init` refuses because files exist, write `pyproject.toml` by hand to the same effect); set `pyproject.toml` dependencies `pydantic>=2.7`, `pysdl2>=0.9.16`, `pysdl2-dll>=2.30`; dev group `pytest`, `ruff`, `mypy`; `[tool.ruff] line-length = 88`, `[tool.mypy] strict = true`; the console script above.**

- [ ] **Step 2: Write `LICENSE` (MIT, copyright 2026 Skye Stubbins) and a `README.md` whose first section is titled "What this does and does not touch" stating: reads your own HID devices, writes forces to your own base, never reads the game process, screen, memory or network, installs no drivers or virtual devices.**

- [ ] **Step 3: Write the failing layering test**

```python
FORBIDDEN = {"engine": {"wardogs_flight_eng.inputs", "wardogs_flight_eng.outputs",
                        "wardogs_flight_eng.runtime", "wardogs_flight_eng.cli", "sdl2"},
             "constants": {"wardogs_flight_eng.engine", "wardogs_flight_eng.inputs",
                           "wardogs_flight_eng.outputs", "sdl2"}}

def test_pure_packages_import_nothing_impure():
    # walk src/wardogs_flight_eng/<pkg>/*.py, parse with ast, collect
    # absolute import roots; assert none start with a forbidden prefix
```

- [ ] **Step 4: Run `uv run pytest tests/test_layering.py -v` — expected PASS (packages are empty) and `uv run ruff check src tests` clean.**

- [ ] **Step 5: Commit** — `git add -A && git commit -m "chore: scaffold wardogs-flight-eng package and layering test"`

---

### Task 2: Game constants with provenance

**Files:**
- Create: `data/wardogs_heli_constants.json`, `src/wardogs_flight_eng/constants/model.py`, `src/wardogs_flight_eng/constants/loader.py`
- Test: `tests/test_constants.py`

**Interfaces:**
- Produces: `UNKNOWN: Final = "UNKNOWN - WARDOGS GAME VALUE REQUIRED"`; frozen dataclasses `Provenance(build_id: str, extracted_at: str, mappings: str)`, `Airframe(key, plugin, mass_kg, main_rotor_rpm, rpm_source, spool_down_rpm_per_s: float | None)`, `Weapon(key, asset, rounds_per_minute, windup_s, reload_s, reload_breakdown: tuple[float, ...], shake_multiplier: float | None, shake: str | None, recoil_pattern: tuple[tuple[float, float], ...], rounds_per_reload: int | None)`, `Shake(key, asset, frequency_hz: float, duration_s: float, blend_in_s: float, blend_out_s: float)`, `InputFacts(pedal_heading_hold_threshold: float, hotas_deadzone_default: float)`, `GameConstants(provenance, airframes: dict[str, Airframe], weapons: dict[str, Weapon], shakes: dict[str, Shake], input: InputFacts)`; `Airframe.one_per_rev_hz -> float` (= rpm / 60); `load_constants(path: Path | None = None) -> GameConstants` (default: the packaged data file); `describe(value: float | int | None) -> str` returning `UNKNOWN` for `None`.

- [ ] **Step 1: Write `data/wardogs_heli_constants.json` from the spec's tables: provenance `{"build_id": "25937608", "extracted_at": "2026-10-22", "mappings": "Wardogs20261015-new.usmap"}`; airframes `littlebird` (ROT_03, 722, 330.4, `FC_ROT_03_MainRotorRPM_MaterialValue`, 850), `lakota` (ROT_02, 7500, 250, `FC_ROT_02_MainRotorRPM_MaterialValue`, null), `havoc` (ROT_04, 9500, 270, `DA_ROT_04_Engine.MainRotorOperatingRPM`, null); weapons `littlebird_miniguns` (`WE_ROT_03_AttachedMachineGuns`, 1500, 0.25, 6.25, [1, 4.25, 1], 0.15, the seven-step pattern, null), `littlebird_rockets` (`WE_ROT_03_Weapon_122mm`, 350, 0, 7, [1, 6], null, [], null), `lakota_cannon` (`WE_ROT_02_Weapon_30mmCannon`, 250, 0, 8, [8], null, [], null), `lakota_rockets` (`WE_ROT_02_Weapon_122mm`, 500, 0, 7, [1, 6], null, [], null), `havoc_mg` (`WE_ROT_04_MountedMachineGun`, 1500, 1.0, 7, [1, 5, 1], 0.15, same pattern, null); weapon `shake` keys: MGs `null`, `littlebird_rockets` → `littlebird_heli_firing`, both Lakota weapons → `heli_firing`; shakes (`frequency_hz` = the envelope's rotation frequency multiplier, or its highest named frequency when there is no multiplier): `heli_firing` (`B_CameraShake_HeliFiring`, 8, 0.4, 0, 0.25), `littlebird_heli_firing` (`B_CameraShake_Littlebird_HeliFiring`, 6, 0.4, 0, 0.25), `havoc_mg_firing` (`BP_ROT_04_Camera_MachineGun_FiringShake`, 12, 0.4, 0, 0.6), `crash_first_person` (`BP_CameraShake_Crash_FirstPerson`, 50, 0.25, 0, 0), `landed_first_person` (`BP_CameraShake_Landed_FirstPerson`, 2, 0.3, 0.1, 0); input facts `0.05`, `0.05`. Crash and Landed are data only in this release (no trigger source exists).**

- [ ] **Step 2: Write the failing tests**

```python
def test_littlebird_one_per_rev():
    c = load_constants()
    assert c.airframes["littlebird"].one_per_rev_hz == pytest.approx(5.5067, abs=1e-3)
    assert c.airframes["lakota"].one_per_rev_hz == pytest.approx(4.1667, abs=1e-3)
    assert c.airframes["havoc"].one_per_rev_hz == pytest.approx(4.5)

def test_minigun_reload_is_summed_breakdown():
    w = load_constants().weapons["littlebird_miniguns"]
    assert w.reload_s == 6.25 and sum(w.reload_breakdown) == 6.25
    assert len(w.recoil_pattern) == 7 and w.recoil_pattern[0] == (1.107, 2.406)

def test_unknown_values_render_sentinel():
    w = load_constants().weapons["littlebird_rockets"]
    assert w.rounds_per_reload is None
    assert describe(w.rounds_per_reload) == "UNKNOWN - WARDOGS GAME VALUE REQUIRED"

def test_provenance_build_id():
    assert load_constants().provenance.build_id == "25937608"

def test_rocket_shake_envelope():
    c = load_constants()
    s = c.shakes[c.weapons["littlebird_rockets"].shake]
    assert (s.frequency_hz, s.duration_s, s.blend_out_s) == (6, 0.4, 0.25)
    assert c.weapons["littlebird_miniguns"].shake is None
```

- [ ] **Step 3: Run `uv run pytest tests/test_constants.py -v` — expected FAIL (module missing).**

- [ ] **Step 4: Implement `model.py` and `loader.py` as in Interfaces; the loader reads JSON with `json`, builds dataclasses, and raises `ConstantsError(ValueError)` naming the missing key on malformed input. Locate the packaged file with `importlib.resources` after adding `data/` to `[tool.hatch.build]` / `[tool.setuptools]` include (whichever uv generated).**

- [ ] **Step 5: Run `uv run pytest tests/test_constants.py -v` — expected PASS. Commit** — `git commit -m "feat: game constants with provenance"`

---

### Task 3: Engine frame and command value objects

**Files:**
- Create: `src/wardogs_flight_eng/engine/frame.py`, `src/wardogs_flight_eng/engine/commands.py`
- Test: `tests/test_frame_commands.py`

**Interfaces:**
- Produces: `class Button(StrEnum)` with members `TRIM_LOCK, TRIM_RESET, FIRE, RELOAD, ROTOR_TOGGLE, PROFILE_CYCLE, ALL_OFF`; frozen dataclass `ControlFrame(pitch: float, roll: float, collective: float, pedals: float, held: frozenset[Button])` whose `__post_init__` raises `ValueError` unless `-1 <= pitch, roll, pedals <= 1` and `0 <= collective <= 1`; `class Axis(StrEnum)`: `PITCH, ROLL`; frozen dataclasses `SpringCommand(axis: Axis, center: float, coefficient: float, deadband: float)`, `SineCommand(axis: Axis, frequency_hz: float, magnitude: float)`, `PulseCommand(axis: Axis, magnitude: float, duration_s: float)` (signed magnitude), `TransientCommand(axis: Axis, frequency_hz: float, magnitude: float, duration_s: float, blend_out_s: float)` (a one-shot decaying vibration), `AllOffCommand()`; `Command = SpringCommand | SineCommand | PulseCommand | TransientCommand | AllOffCommand`. Magnitudes and coefficients are normalised `0..1` (pulse `-1..1`).

- [ ] **Step 1: Write the failing tests**

```python
def test_frame_rejects_out_of_range_collective():
    with pytest.raises(ValueError):
        ControlFrame(0, 0, 1.2, 0, frozenset())

def test_commands_are_hashable_value_objects():
    a = SpringCommand(Axis.PITCH, 0.0, 0.5, 0.02)
    assert a == SpringCommand(Axis.PITCH, 0.0, 0.5, 0.02) and hash(a)
```

- [ ] **Step 2: Run — expected FAIL. Step 3: implement. Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: engine frame and command value objects"`

---

### Task 4: Trim state

**Files:**
- Create: `src/wardogs_flight_eng/engine/trim.py`
- Test: `tests/test_trim.py`

**Interfaces:**
- Produces: `class TrimState` with `__init__(self, slew_s: float)`, properties `center_pitch: float`, `center_roll: float`, methods `lock(pitch: float, roll: float) -> None` (sets the target to the clamped `±1.0` values), `reset() -> None` (target origin), `step(dt: float) -> None` (moves the current centre toward the target linearly so that a full `0 → 1` move takes `slew_s`; `slew_s == 0` snaps).

- [ ] **Step 1: Write the failing tests**

```python
def test_lock_then_reset_slews_over_slew_time():
    t = TrimState(slew_s=0.5)
    t.lock(0.5, -0.25); t.step(0.25)
    assert t.center_pitch == pytest.approx(0.25) and t.center_roll == pytest.approx(-0.125)
    t.step(1.0)
    assert (t.center_pitch, t.center_roll) == (0.5, -0.25)
    t.reset(); t.step(10)
    assert (t.center_pitch, t.center_roll) == (0.0, 0.0)

def test_lock_at_full_deflection_clamps_to_unit():   # Review Focus 3
    t = TrimState(slew_s=0)
    t.lock(1.7, -3.0); t.step(0)
    assert (t.center_pitch, t.center_roll) == (1.0, -1.0)

def test_nothing_but_lock_and_reset_moves_center():
    t = TrimState(slew_s=0); t.step(5.0)
    assert (t.center_pitch, t.center_roll) == (0.0, 0.0)
```

- [ ] **Step 2: Run — FAIL. Step 3: implement `trim.py`. Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: trim lock/reset state with slew"`

---

### Task 5: Rotor model

**Files:**
- Create: `src/wardogs_flight_eng/engine/rotor.py`
- Test: `tests/test_rotor.py`

**Interfaces:**
- Produces: `class RotorModel` with `__init__(self, operating_rpm: float, spool_up_s: float, spool_down_rpm_per_s: float, base_amplitude: float, deflection_factor: float)`; `running: bool` (starts `True`), `toggle() -> None`, `step(dt: float) -> None` (rpm rises linearly to `operating_rpm` over `spool_up_s` when running, falls at `spool_down_rpm_per_s` when not, never below 0), `rpm: float`, `frequency_hz -> float` (= rpm / 60), `amplitude(collective: float, deflection: float) -> float` = `base_amplitude * (rpm / operating_rpm) * collective * (1 + deflection_factor * deflection)` clamped to `0..1`, where `deflection` is the cyclic's distance from the trim centre `0..1`.

- [ ] **Step 1: Write the failing tests**

```python
def test_spools_up_to_operating_rpm():
    r = RotorModel(330.4, spool_up_s=2.0, spool_down_rpm_per_s=850, base_amplitude=0.3, deflection_factor=0.5)
    r.step(1.0); assert r.rpm == pytest.approx(165.2)
    r.step(5.0); assert r.frequency_hz == pytest.approx(5.5067, abs=1e-3)

def test_spool_down_uses_game_rate():
    r = RotorModel(330.4, 2.0, 850, 0.3, 0.5); r.step(10); r.toggle(); r.step(0.2)
    assert r.rpm == pytest.approx(330.4 - 170)
    r.step(10); assert r.rpm == 0

def test_amplitude_follows_collective_and_deflection():
    r = RotorModel(270, 0, 850, 0.4, 0.5); r.step(0)
    assert r.amplitude(0.0, 0.0) == 0
    assert r.amplitude(1.0, 0.0) == pytest.approx(0.4)
    assert r.amplitude(1.0, 1.0) == pytest.approx(0.6)
```

- [ ] **Step 2: Run — FAIL. Step 3: implement. Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: rotor spool and buzz amplitude model"`

---

### Task 6: Weapon model

**Files:**
- Create: `src/wardogs_flight_eng/engine/weapon.py`
- Test: `tests/test_weapon.py`

**Interfaces:**
- Consumes: `constants.model.Weapon`.
- Produces: `class WeaponModel` with `__init__(self, weapon: Weapon, amplitude: float, rocket_kick: tuple[float, float] = (0.0, -1.0))`; `step(dt: float, fire_held: bool, reload_tapped: bool) -> list[tuple[float, float]]` returning the `(roll, pitch)` unit-direction × amplitude × (`shake_multiplier` or 1) of each round fired during this `dt` (at most `ceil(dt * rate)`), where MG directions step through `recoil_pattern` (`(yaw, pitch)` → `(roll, pitch)`, each divided by the pattern's largest vector length) and non-pattern weapons use `rocket_kick`; `scaled(v: tuple[float, float]) -> tuple[float, float]` is `v` divided by the largest vector length in the pattern; `shake: Shake | None` (the weapon's envelope, resolved by the caller from constants and passed as `shake=` to `__init__`); `state -> Literal["idle", "winding", "firing", "reloading"]`. Reload tapped → `reloading` for `weapon.reload_s`, during which nothing fires; when the window ends with fire still held, wind-up restarts.

- [ ] **Step 1: Write the failing tests**

```python
def test_minigun_winds_up_then_fires_at_25hz():
    w = WeaponModel(MINIGUNS, amplitude=0.5)
    assert w.step(0.25, True, False) == [] and w.state == "firing"
    rounds = w.step(1.0, True, False)
    assert len(rounds) == 25
    assert rounds[0] == pytest.approx(scaled(MINIGUNS.recoil_pattern[0]) * 0.5 * 0.15)
    assert len(w.step(1.0, True, False)) == 25          # pattern wraps 7 → 14 → ...

def test_rockets_kick_rearward_at_game_rate():
    w = WeaponModel(ROCKETS_LB, amplitude=1.0)
    rounds = w.step(1.0, True, False)
    assert len(rounds) == 6 and all(r == (0.0, -1.0) for r in rounds)   # 350 rpm

def test_reload_silences_then_rewinds():                # Review Focus 4
    w = WeaponModel(MINIGUNS, amplitude=1.0); w.step(0.5, True, False)
    assert w.step(0.1, True, True) == [] and w.state == "reloading"
    assert w.step(6.0, True, False) == [] and w.state == "reloading"   # 6.1 s into the 6.25 s window
    assert w.step(0.2, True, False) == []                # window ends at 6.25; wind-up restarts
    assert w.state == "winding"
    w.step(0.25, True, False); assert len(w.step(0.2, True, False)) == 5

def test_release_resets_windup():
    w = WeaponModel(HAVOC_MG, amplitude=1.0); w.step(0.9, True, False)
    w.step(0.1, False, False); assert w.state == "idle"
    assert w.step(0.9, True, False) == []                # wind-up 1.0 s again
```

- [ ] **Step 2: Run — FAIL. Step 3: implement `weapon.py` with an accumulator (`time since last round`) so rate is exact across ticks. Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: weapon wind-up, fire-rate pulses and reload window"`

---

### Task 7: Profile model and the flight engine

**Files:**
- Create: `src/wardogs_flight_eng/engine/profile.py`, `src/wardogs_flight_eng/engine/synth.py`, `profiles/littlebird-miniguns.json`, `profiles/littlebird-rockets.json`, `profiles/lakota.json`, `profiles/havoc.json`
- Test: `tests/test_profile.py`, `tests/test_synth.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces (profile): pydantic models `DeviceRef(guid: str | None, product: str | None)`, `AxisBinding(device: str, axis: int, invert: bool = False)`, `ButtonBinding(device: str, button: int)`, `Calibration(collective_bottom_raw: float = -1, collective_top_raw: float = 1, pedals_center_raw: float = 0)`, `DeviceMap(devices: dict[str, DeviceRef], axes: dict[Literal["pitch","roll","collective","pedals"], AxisBinding], buttons: dict[Button, ButtonBinding], calibration: Calibration)`, `Feel(spring_coefficient: float, roll_scale: float = 0.5, deadband: float, trim_slew_s: float)` (AB9 owners report roll reading ~2x pitch at equal settings — `docs/reference/community-ffb-references.md`; the roll spring coefficient is `spring_coefficient * roll_scale`), `Rotor(base_amplitude, deflection_factor, spool_up_s, spool_down_rpm_per_s: float | None)`, `Recoil(amplitude: float, rocket_kick: tuple[float, float], shake_amplitude: float)`, `Safety(force_ceiling: float = 0.6, watchdog_s: float = 0.25)`, `Profile(name, airframe: str, pilot_weapon: str | None, verify_in_game: list[str], device_map: DeviceMap, feel, rotor, recoil, safety, taste: list[str])`; `load_profile(path: Path) -> Profile` raising `ProfileError(ValueError)` whose message names the offending field; `Profile.validate_against(constants: GameConstants) -> None` raising `ProfileError` if `airframe` or `pilot_weapon` is not a constants key.
- Produces (engine): `class FlightEngine` with `__init__(self, profile: Profile, constants: GameConstants)`, `step(dt: float, frame: ControlFrame) -> list[Command]`, `all_off: bool`. Each tick returns: two `SpringCommand`s (pitch, roll) centred on the trim state with `feel.spring_coefficient` / `feel.deadband`; two `SineCommand`s at `rotor.frequency_hz` with `rotor.amplitude(...)`; zero or more `PulseCommand`s per axis from the weapon (duration `0.5 / rate`) plus, when the weapon has a `shake`, one `TransientCommand` per round on each axis (`frequency_hz`, `duration_s`, `blend_out_s` from the shake, magnitude `recoil.shake_amplitude`); a `ROTOR_TOGGLE` tap calls `RotorModel.toggle()`; exactly `[AllOffCommand()]` when `dt > safety.watchdog_s` or after `ALL_OFF` was tapped (until `ALL_OFF` is tapped again). Button *taps* are rising edges against the previous frame's `held`.

- [ ] **Step 1: Write the four profiles. Shared values (owner taste, listed under `taste`): `deadband 0.02`, `trim_slew_s 0.3`, `rotor.deflection_factor 0.5`, `rotor.spool_up_s 3.0`, `recoil.rocket_kick [0, -1]`, `recoil.shake_amplitude 0.3`, `safety` defaults. Per profile: `littlebird-miniguns` — airframe `littlebird`, weapon `littlebird_miniguns`, `spring_coefficient 0.35`, `base_amplitude 0.25`, `recoil.amplitude 0.6`; `littlebird-rockets` — same with weapon `littlebird_rockets`; `lakota` — `lakota`, weapon `lakota_rockets`, `verify_in_game ["pilot_weapon"]`, spring `0.5`, buzz `0.3`, recoil `0.8`; `havoc` — `havoc`, weapon `null`, spring `0.65`, buzz `0.35`, recoil `0`. `device_map.devices` and `buttons` empty, `axes` empty; `spool_down_rpm_per_s null` (engine falls back to the airframe's value, then to `850`).**

- [ ] **Step 2: Write the failing profile tests**

```python
@pytest.mark.parametrize("name", ["littlebird-miniguns", "littlebird-rockets", "lakota", "havoc"])
def test_shipped_profiles_load_and_validate(name):
    p = load_profile(PROFILES / f"{name}.json"); p.validate_against(load_constants())
    assert "spring_coefficient" in p.taste

def test_bad_field_named_in_error(tmp_path):
    bad = tmp_path / "p.json"; bad.write_text('{"name": "x", "airframe": "littlebird", "feel": {"spring_coefficient": "soft"}}')
    with pytest.raises(ProfileError, match="spring_coefficient"):
        load_profile(bad)

def test_unknown_weapon_rejected():
    p = load_profile(PROFILES / "lakota.json").model_copy(update={"pilot_weapon": "laser"})
    with pytest.raises(ProfileError, match="laser"):
        p.validate_against(load_constants())
```

- [ ] **Step 3: Write the failing engine tests**

```python
def frame(pitch=0, roll=0, collective=0, pedals=0, *held):
    return ControlFrame(pitch, roll, collective, pedals, frozenset(held))

def test_idle_tick_emits_centered_springs_and_silent_buzz():
    e = engine_for("littlebird-miniguns")
    cmds = e.step(0.01, frame())
    springs = [c for c in cmds if isinstance(c, SpringCommand)]
    assert {s.axis for s in springs} == {Axis.PITCH, Axis.ROLL} and all(s.center == 0 for s in springs)
    assert {s.axis: s.coefficient for s in springs} == {Axis.PITCH: 0.35, Axis.ROLL: pytest.approx(0.175)}   # roll_scale 0.5
    assert all(c.magnitude == 0 for c in cmds if isinstance(c, SineCommand))   # collective 0

def test_trim_lock_tap_moves_spring_center_once():
    e = engine_for("littlebird-miniguns")
    e.step(0.01, frame(0.4, -0.2, 0.5, 0, Button.TRIM_LOCK))
    for _ in range(100): cmds = e.step(0.01, frame(0.4, -0.2, 0.5, 0, Button.TRIM_LOCK))   # still held: no re-lock
    centers = {c.axis: c.center for c in cmds if isinstance(c, SpringCommand)}
    assert centers == {Axis.PITCH: pytest.approx(0.4), Axis.ROLL: pytest.approx(-0.2)}

def test_buzz_frequency_is_airframe_one_per_rev():
    e = engine_for("havoc")
    for _ in range(400): cmds = e.step(0.01, frame(collective=1.0))
    assert [c.frequency_hz for c in cmds if isinstance(c, SineCommand)] == [pytest.approx(4.5)] * 2

def test_fire_yields_pulses_on_both_axes_after_windup():
    e = engine_for("littlebird-miniguns")
    for _ in range(30): e.step(0.01, frame(0, 0, 0.5, 0, Button.FIRE))
    cmds = e.step(0.04, frame(0, 0, 0.5, 0, Button.FIRE))
    pulses = [c for c in cmds if isinstance(c, PulseCommand)]
    assert len(pulses) == 2 and {p.axis for p in pulses} == {Axis.PITCH, Axis.ROLL}
    assert pulses[0].duration_s == pytest.approx(0.02)

def test_watchdog_dt_emits_all_off_not_pulses():      # Review Focus 5
    e = engine_for("littlebird-miniguns")
    for _ in range(30): e.step(0.01, frame(0, 0, 1, 0, Button.FIRE))
    assert e.step(0.5, frame(0, 0, 1, 0, Button.FIRE)) == [AllOffCommand()]

def test_all_off_latches_until_tapped_again():
    e = engine_for("lakota")
    assert e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF)) == [AllOffCommand()]
    assert e.step(0.01, frame()) == [AllOffCommand()]
    e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))
    assert any(isinstance(c, SpringCommand) for c in e.step(0.01, frame()))

def test_havoc_has_no_recoil():
    e = engine_for("havoc")
    for _ in range(300): cmds = e.step(0.01, frame(0, 0, 1, 0, Button.FIRE))
    assert not any(isinstance(c, PulseCommand) for c in cmds)

def test_rockets_emit_transient_shake_per_round():
    e = engine_for("littlebird-rockets")
    cmds = e.step(0.2, frame(0, 0, 0.5, 0, Button.FIRE))          # 350 rpm, no wind-up: rounds at t=0 and t=0.171 s
    shakes = [c for c in cmds if isinstance(c, TransientCommand)]
    assert len(shakes) == 4 and shakes[0].frequency_hz == 6 and shakes[0].duration_s == 0.4 and shakes[0].magnitude == 0.3

def test_rotor_toggle_tap_spools_down():
    e = engine_for("littlebird-miniguns")
    for _ in range(400): e.step(0.01, frame(collective=1.0))
    e.step(0.01, frame(0, 0, 1, 0, Button.ROTOR_TOGGLE))
    for _ in range(100): cmds = e.step(0.01, frame(collective=1.0))   # 1 s at 850 rpm/s: 330.4 → 0
    assert {c.frequency_hz for c in cmds if isinstance(c, SineCommand)} == {0.0}
    assert all(c.magnitude == 0 for c in cmds if isinstance(c, SineCommand))
```

- [ ] **Step 4: Run both files — FAIL. Step 5: implement `profile.py` then `synth.py` (`FlightEngine` owns one `TrimState`, one `RotorModel`, one optional `WeaponModel`; deflection for the rotor = Euclidean distance of `(pitch, roll)` from the trim centre, clamped `0..1`). Step 6: run — PASS; `uv run mypy src` clean. Step 7: Commit** — `git commit -m "feat: profiles and flight engine synthesis"`

---

### Task 8: Input protocol, composite, calibration and simulated devices

**Files:**
- Create: `src/wardogs_flight_eng/inputs/protocol.py`, `src/wardogs_flight_eng/inputs/composite.py`, `src/wardogs_flight_eng/inputs/simulated.py`, `tests/scenarios/takeoff-trim-fire.json`
- Test: `tests/test_composite.py`, `tests/test_simulated.py`

**Interfaces:**
- Consumes: `engine.frame.ControlFrame`, `engine.profile.DeviceMap`.
- Produces: `class InputDevice(Protocol)` with `name: str`, `guid: str`, `axis_count: int`, `button_count: int`, `poll() -> None`, `axis(index: int) -> float` (raw `-1..1`), `button(index: int) -> bool`, `alive: bool`; `class CompositeInput` with `__init__(self, device_map: DeviceMap, devices: dict[str, InputDevice])` raising `InputConfigError(ValueError)` at construction naming any logical channel whose device is missing or whose axis/button index is out of range, and `read() -> ControlFrame` raising `DeviceLostError(RuntimeError)` if any device reports `alive == False`; collective normalised `(raw - bottom) / (top - bottom)` clamped `0..1` (works when `bottom > top`), pedals `raw - center` clamped `-1..1`, `invert` negates pitch/roll; `class SimulatedDevice(InputDevice)` with settable `axes: list[float]`, `buttons: list[bool]`, `alive`; `class Scenario` loaded by `Scenario.load(path) -> Scenario` from JSON `{"rate_hz": 100, "device_map": {...same schema as a profile's device_map, naming the simulated devices...}, "devices": {"stick": {"axes": 2, "buttons": 0}, "grip": {"axes": 0, "buttons": 8}, "coll": {"axes": 1, "buttons": 0}, "ped": {"axes": 1, "buttons": 0}}, "steps": [{"t": 0.0, "set": {"stick.axis0": 0.1, "coll.axis0": -1.0, "grip.button3": true}}, ...]}` with `apply_until(t: float) -> None` on its devices, `devices: dict[str, SimulatedDevice]`, and `device_map: DeviceMap` (so a dry run can build a `CompositeInput` from the scenario alone).

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_button_index_fails_at_construction():   # Review Focus 1
    dm = device_map(buttons={"trim_lock": ("grip", 40)}); grip = SimulatedDevice("grip", button_count=32)
    with pytest.raises(InputConfigError, match="trim_lock"):
        CompositeInput(dm, {"grip": grip, "stick": stick(), "coll": coll(), "ped": ped()})

def test_inverted_collective_calibration():                # Review Focus 2
    dm = device_map(calibration=Calibration(collective_bottom_raw=0.9, collective_top_raw=-0.8))
    c = CompositeInput(dm, devices); devices["coll"].axes[0] = 0.9
    assert c.read().collective == 0.0
    devices["coll"].axes[0] = -0.8; assert c.read().collective == 1.0

def test_device_lost_raises():
    c = CompositeInput(device_map(), devices); devices["ped"].alive = False
    with pytest.raises(DeviceLostError, match="ped"):
        c.read()

def test_scenario_drives_devices_over_time():
    s = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    s.apply_until(2.0); assert s.devices["coll"].axes[0] == pytest.approx(0.2)
    s.apply_until(5.05); assert s.devices["grip"].buttons[0] is True     # trim lock down at 5.0
    s.apply_until(6.0); assert s.devices["grip"].buttons[0] is False     # released at 5.1
```

- [ ] **Step 2: Write `tests/scenarios/takeoff-trim-fire.json`: 12 s at 100 Hz — collective from -1 to 0.2 over 0–2 s, stick pitch to 0.3 at 4 s, trim-lock button down at 5.0 and up at 5.1, fire held 7.0–9.0, trim-reset tapped at 10.0.**

- [ ] **Step 3: Run — FAIL. Step 4: implement the three modules. Step 5: run — PASS. Step 6: Commit** — `git commit -m "feat: composite multi-device input with calibration and simulated devices"`

---

### Task 9: Output backends: protocol, clamp, logging, null

**Files:**
- Create: `src/wardogs_flight_eng/outputs/protocol.py`, `clamp.py`, `logging_backend.py`, `null_backend.py`
- Test: `tests/test_backends.py`

**Interfaces:**
- Consumes: `engine.commands.Command`.
- Produces: `class ForceBackend(Protocol)` with `apply(t: float, commands: Sequence[Command]) -> None`, `all_off() -> None`, `close() -> None`; `class ClampedBackend(ForceBackend)` wrapping another with `ceiling: float`, scaling any `coefficient` / `magnitude` above the ceiling down to it (sign preserved); `class LoggingBackend(ForceBackend)` writing one JSON line per command `{"t": float, "kind": "spring"|"sine"|"pulse"|"transient"|"all_off", ...fields}` to a path and flushing on `close()`; `class NullBackend`.

- [ ] **Step 1: Write the failing tests**

```python
def test_clamp_scales_magnitudes_to_ceiling():
    inner = RecordingBackend(); b = ClampedBackend(inner, ceiling=0.6)
    b.apply(0.0, [SineCommand(Axis.PITCH, 5.5, 0.9), PulseCommand(Axis.ROLL, -1.0, 0.02)])
    assert inner.last == [SineCommand(Axis.PITCH, 5.5, 0.6), PulseCommand(Axis.ROLL, -0.6, 0.02)]

def test_logging_backend_writes_jsonl(tmp_path):
    p = tmp_path / "forces.jsonl"; b = LoggingBackend(p)
    b.apply(0.01, [SpringCommand(Axis.PITCH, 0.0, 0.35, 0.02)]); b.all_off(); b.close()
    lines = [json.loads(l) for l in p.read_text().splitlines()]
    assert lines[0]["kind"] == "spring" and lines[0]["coefficient"] == 0.35 and lines[-1]["kind"] == "all_off"
```

- [ ] **Step 2: Run — FAIL. Step 3: implement. Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: force backend protocol with clamp, logging and null backends"`

---

### Task 10: Runtime loop with watchdog and clean teardown

**Files:**
- Create: `src/wardogs_flight_eng/runtime/loop.py`, `src/wardogs_flight_eng/runtime/paths.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `FlightEngine`, `CompositeInput`, `ForceBackend`.
- Produces: `run_loop(engines: Sequence[FlightEngine], source: CompositeInput, backend: ForceBackend, *, rate_hz: float, watchdog_s: float, clock: Callable[[], float] = time.perf_counter, sleep: Callable[[float], None] = time.sleep, stop: Callable[[], bool] = lambda: False, max_ticks: int | None = None) -> LoopResult` where `LoopResult(ticks: int, stopped_by: Literal["stop", "max_ticks", "device_lost", "error"], active_profile: str)`; the loop drives `engines[0]` first and, on a rising edge of `Button.PROFILE_CYCLE` in the frame, calls `backend.all_off()` and advances to the next engine (wrapping), logging the new profile name at `INFO`; the loop always calls `backend.all_off()` then `backend.close()` in a `finally`; a `DeviceLostError` is logged at `ERROR` and ends the loop with `"device_lost"`; a tick whose measured `dt` is outside `0..watchdog_s` is still passed to the engine, but the loop then replaces whatever the engine returned with `[AllOffCommand()]` and logs it at `WARNING` (the loop's `watchdog_s` is the shortest across the run's profiles while each engine gates on its own profile's, so the loop's override is what makes the strictest watchdog hold for every profile); `config_dir() -> Path` = `%LOCALAPPDATA%\WardogsFlightEng`, created on first use; `setup_logging(verbose: bool) -> None` with a rotating file handler in `config_dir() / "logs"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_loop_runs_fixed_ticks_and_tears_down():
    backend = RecordingBackend(); r = run_loop(engine, source, backend, rate_hz=100, watchdog_s=0.25, clock=fake_clock, sleep=lambda s: None, max_ticks=50)
    assert r.ticks == 50 and backend.closed and backend.all_off_calls >= 1

def test_device_lost_ends_loop_and_zeroes_forces():
    devices["ped"].alive = False
    r = run_loop(engine, source, backend, rate_hz=100, watchdog_s=0.25, clock=fake_clock, sleep=lambda s: None)
    assert r.stopped_by == "device_lost" and backend.all_off_calls >= 1 and backend.closed

def test_stalled_tick_applies_all_off(caplog):              # Review Focus 5
    clock = StepClock([0.0, 0.01, 0.6, 0.61]); r = run_loop(..., clock=clock, max_ticks=3)
    assert AllOffCommand() in backend.applied[1] and "watchdog" in caplog.text.lower()

def test_profile_cycle_switches_engine_and_zeroes_forces():
    devices["grip"].buttons[PROFILE_CYCLE_IDX] = True
    r = run_loop([engine_lb, engine_lakota], source, backend, rate_hz=100, watchdog_s=0.25, clock=fake_clock, sleep=lambda s: None, max_ticks=2)
    assert r.active_profile == "lakota" and backend.all_off_calls >= 1
```

- [ ] **Step 2: Run — FAIL. Step 3: implement. Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: fixed-rate runtime loop with watchdog and guaranteed teardown"`

---

### Task 11: Dry run and force plot

**Files:**
- Create: `src/wardogs_flight_eng/runtime/plot.py`
- Test: `tests/test_plot.py`, `tests/test_dry_run.py`

**Interfaces:**
- Consumes: `Scenario`, `LoggingBackend`, `run_loop`.
- Produces: `write_plot_html(log_path: Path, out_path: Path) -> None` producing a self-contained HTML file (inline SVG, no external scripts) with one row per axis showing spring centre, sine magnitude and pulse events over time; `dry_run(profile: Profile, constants: GameConstants, scenario: Scenario, out_dir: Path) -> tuple[Path, Path]` (log path, plot path) that builds `SimulatedDevice`s from the scenario, a `CompositeInput` from a scenario-provided device map, runs the loop with a scenario clock at `scenario.rate_hz`, and returns both paths.

- [ ] **Step 1: Write the failing tests**

```python
def test_dry_run_log_shows_trim_lock_and_fire(tmp_path):
    log, plot = dry_run(profile("littlebird-miniguns"), load_constants(), Scenario.load(SCENARIOS / "takeoff-trim-fire.json"), tmp_path)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    springs_after_lock = [r for r in rows if r["kind"] == "spring" and r["axis"] == "pitch" and r["t"] > 5.5]
    assert springs_after_lock[0]["center"] == pytest.approx(0.3, abs=0.01)
    pulses = [r for r in rows if r["kind"] == "pulse" and 7.3 < r["t"] < 9.0]
    assert 80 <= len(pulses) <= 90                        # 2 pulses per round; ~25 Hz for ~1.7 s after 0.25 s wind-up → 42 rounds
    assert sum(r["axis"] == "pitch" for r in pulses) == sum(r["axis"] == "roll" for r in pulses) == 42
    assert plot.exists() and "<svg" in plot.read_text()

def test_plot_has_one_row_per_axis(tmp_path):
    ...; assert html.count('class="axis-row"') == 2
```

- [ ] **Step 2: Run — FAIL. Step 3: implement `plot.py` (hand-written SVG) and `dry_run` in `runtime/loop.py` or a new `runtime/dry_run.py` (builder's choice; keep files < 200 lines). Step 4: run — PASS. Step 5: Commit** — `git commit -m "feat: scenario dry run with force log and SVG plot"`

---

### Task 12: SDL2 input device and haptic backend

**Files:**
- Create: `src/wardogs_flight_eng/inputs/sdl_device.py`, `src/wardogs_flight_eng/outputs/sdl_haptic.py`
- Test: `tests/test_sdl_device.py`, `tests/test_sdl_haptic.py` (both against a fake `sdl2` module injected via a `SdlApi` seam), `tests/test_sdl_hardware.py` (skipped unless env `WFE_HARDWARE=1`)

**Interfaces:**
- Consumes: `InputDevice`, `ForceBackend`.
- Produces: `class SdlApi(Protocol)` — the subset of `sdl2` calls used (`SDL_Init`, `SDL_NumJoysticks`, `SDL_JoystickOpen`, `SDL_JoystickGetGUID`, `SDL_JoystickNameForIndex`, `SDL_JoystickNumAxes/Buttons`, `SDL_JoystickGetAxis/Button`, `SDL_JoystickGetAttached`, `SDL_HapticOpenFromJoystick`, `SDL_HapticQuery`, `SDL_HapticNewEffect`, `SDL_HapticUpdateEffect`, `SDL_HapticRunEffect`, `SDL_HapticStopAll`, `SDL_HapticClose`, `SDL_JoystickUpdate`) so tests can substitute a fake; `enumerate_devices(api: SdlApi | None = None) -> list[DeviceInfo(index, guid, name, axis_count, button_count, has_haptic)]`; `class SdlDevice(InputDevice)` opened by guid (`open_by_guid(guid, api) -> SdlDevice`), `axis()` returning `value / 32767`; `class SdlHapticBackend(ForceBackend)` keeping one persistent spring effect per axis (`SDL_HAPTIC_SPRING` condition with `center` set from `SpringCommand.center * 32767`, `right_coeff = left_coeff = coefficient * 32767`, `deadband * 32767`), one persistent sine per axis (`SDL_HAPTIC_SINE`, `period = round(1000 / frequency_hz)` ms, `magnitude * 32767`), and short-lived effects for pulses (`SDL_HAPTIC_CONSTANT`, `length = duration_s * 1000` ms) and transients (`SDL_HAPTIC_SINE` with `length = duration_s * 1000`, `fade_length = blend_out_s * 1000`, `fade_level = 0`); persistent effects are updated in place, never recreated per tick; short-lived effects are created from a small pool and destroyed when their length elapses; `probe_primitives(guid, api) -> PrimitiveReport(spring: bool, spring_center_moves: bool, sine: bool, constant: bool)` used by `check-device`.

- [ ] **Step 1: Write the failing tests with a `FakeSdl` recording calls: `test_spring_update_in_place_not_recreated` (100 ticks → exactly 1 `SDL_HapticNewEffect` per persistent effect, ≥99 `SDL_HapticUpdateEffect`), `test_sine_period_from_frequency` (5.5067 Hz → period 182 ms), `test_pulse_creates_short_constant_effect` (duration 0.02 → length 20 ms, sign carried in `level`), `test_transient_is_fading_sine` (0.4 s / blend-out 0.25 → length 400 ms, fade_length 250 ms, period 167 ms at 6 Hz), `test_all_off_stops_everything` (`SDL_HapticStopAll` then zero-coefficient spring update), `test_axis_scaled_to_unit` (raw 16383 → 0.49998).**

- [ ] **Step 2: Write `tests/test_sdl_hardware.py` as the AB9 conformance check: skipped without `WFE_HARDWARE=1`; when run, opens the first haptic device, runs `probe_primitives`, asserts all four flags, and holds a spring at centre `0.5` for 2 s so the tester can feel it.**

- [ ] **Step 3: Run — FAIL. Step 4: implement both modules against the real `sdl2` module by default. Step 5: run (fakes) — PASS. Step 6: Commit** — `git commit -m "feat: SDL2 joystick input and haptic force backend"`

---

### Task 13: Command-line interface

**Files:**
- Create: `src/wardogs_flight_eng/cli.py`; modify `src/wardogs_flight_eng/__main__.py`
- Test: `tests/test_cli.py` (via `CliRunner`-style invocation of `main(argv)`; SDL calls faked)

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int` with subcommands: `run --profile PATH [--profile PATH ...] [--rate 200] [--verbose]` (repeatable; the order is the `PROFILE_CYCLE` order, all profiles must share one `device_map`); `dry-run --profile PATH --scenario PATH [--out DIR]` (default out `config_dir()/dry-runs/<timestamp>`); `list-devices [--live]` (prints guid, name, axes, buttons, haptic; `--live` refreshes axis/button values every 100 ms until Ctrl+C); `check-device [--guid G]` (prints the `PrimitiveReport` and exit code 0 only if all four are true); `calibrate --profile PATH` (prompts: "collective fully down, press Enter", "fully up, Enter", "pedals centred, Enter"; writes `calibration` into the profile file, preserving all other fields and key order); `show-constants` (prints the table with `UNKNOWN` sentinels). Exit codes: 0 ok, 1 usage/profile error (message names the field), 2 device missing/lost.

- [ ] **Step 1: Write the failing tests: `test_run_with_empty_device_map_exits_1_and_says_calibrate`, `test_dry_run_writes_log_and_plot`, `test_show_constants_prints_unknown_sentinel`, `test_check_device_exit_code_reflects_report`, `test_calibrate_rewrites_only_calibration(tmp_path)`.**

- [ ] **Step 2: Run — FAIL. Step 3: implement with `argparse`; all output through a `Console` object writing to `sys.stdout` (so `src` keeps no `print` outside it) and `logging` for diagnostics. Step 4: run — PASS; `uv run ruff check src tests && uv run mypy src` clean. Step 5: Commit** — `git commit -m "feat: command-line interface"`

---

### Task 14: Packaging and README

**Files:**
- Create: `packaging/wardogs-flight-eng.spec`; modify `README.md`, `pyproject.toml`
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Write the PyInstaller spec: one-file, console, bundles `data/` and `profiles/` as data, includes the `pysdl2-dll` binaries; add `pyinstaller` to the dev group and a `[tool.uv] scripts` / README command `uv run pyinstaller packaging/wardogs-flight-eng.spec`.**

- [ ] **Step 2: Write the failing test `test_package_data_included`: `importlib.resources.files("wardogs_flight_eng")` resolves `data/wardogs_heli_constants.json` and all four profiles.**

- [ ] **Step 3: Finish `README.md`: first-run sequence (`list-devices --live` → fill `device_map` → `calibrate` → `check-device` → `run`), the dry-run command and what the plot shows, the anti-cheat posture section from Task 1, the provenance rule (how to contribute a constant: asset path + property + build id, never a dump), and the Python API example (`FlightEngine`, `SimulatedDevice`, `LoggingBackend` in ten lines).**

- [ ] **Step 4: Run `uv run pytest -v`, `uv run ruff check src tests`, `uv run mypy src`; build the exe and run `dist/wardogs-flight-eng.exe show-constants` — expected: the constants table with `UNKNOWN` rows. Step 5: Commit** — `git commit -m "feat: PyInstaller packaging and README"`

---

## Hardware tuning pass (after the AB9, collective and pedals arrive — not a code task)

0. Before flying: choose division of labour A or B from `docs/reference/community-ffb-references.md` ("Two valid divisions of labour"). For A (default): import one of the owner's three Wardogs presets into Moza Cockpit, set `bacic_spring` 0 and `hardware_balancing_enable` 0 (Flight Eng owns spring + trim; two springs break trim lock), keep damper / friction / inertia / breakout, confirm `bacic_gameForceFeedback` 100. For B: keep the Cockpit spring, bind `hardware_balancing_trim` / `_recenter` to grip buttons, and set `feel.spring_coefficient` 0 in every Flight Eng profile. Then compare with the built-in Hind / UH-1H presets and the community AH-6J and R66 presets (Moza Discord `flying-settings-sharing`) and seed `feel.*` and `rotor.base_amplitude` from them.
1. `wardogs-flight-eng list-devices --live`; record each device's guid and which axis/button is which; fill `device_map` in each profile.
2. `calibrate --profile profiles/littlebird-miniguns.json`.
3. `check-device` with `WFE_HARDWARE=1 uv run pytest tests/test_sdl_hardware.py`; if `spring_center_moves` is false, open an issue titled "dinput8 fallback backend" (spec: `ctypes` binding behind `ForceBackend`).
4. Fly each profile; adjust `taste` values only; commit the tuned profiles.

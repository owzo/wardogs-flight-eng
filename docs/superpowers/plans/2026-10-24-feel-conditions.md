# Feel Conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every profile friction, damper and inertia conditions and two feel modes (force-trim Lakota/Havoc, unboosted Littlebird with a friction clamp), driven by an airspeed estimate the engine reads through a replaceable seam, all on the existing fail-closed force path.

**Architecture:** The pure engine gains a `FeelModel` (mode logic, clamp blend, the four conditions per axis), a `FlightState` seam with an input-only `InputEstimator`, and a profile handoff; three new condition commands flow through the clamp, the logger and new SDL condition effects that are persistent like the spring and gated by the base's reported capabilities. Profiles gain required fields; a v0.1.0 profile fails with a migration message.

**Tech Stack:** Python 3.12, pydantic v2, PySDL2 (haptic conditions `SDL_HAPTIC_FRICTION` 1<<10, `SDL_HAPTIC_DAMPER` 1<<8, `SDL_HAPTIC_INERTIA` 1<<9), pytest, ruff, mypy --strict, uv.

**Spec:** `docs/superpowers/specs/2026-10-24-feel-conditions-design.md` (reference: `docs/reference/real-cyclic-feel-references.md`)

## Global Constraints

- `engine/` imports nothing from `inputs/`, `outputs/`, `runtime/`, the CLI modules or `sdl2` (`tests/test_layering.py` enforces it); the estimator lives in `engine/`.
- Every new profile gain is `0..1`, finite, and `<= safety.force_ceiling`; both modes require `friction <= spring_coefficient / 4`; `unboosted` requires `clamp_friction >= friction`.
- New profile fields `feel.mode`, `feel.friction`, `feel.damper`, `feel.inertia`, `rotor.airspeed_factor`, `estimator` are required with no defaults; `feel.clamp_friction` is required in `unboosted` and rejected in `force_trim`.
- Persistent conditions use the spring's finite length (`max(1.0, 2 x min watchdog)` from the CLI), change-detection upload, half-life re-run, and are silenced to zero coefficients in `all_off`.
- Roll static forces (spring, friction) are multiplied by `roll_scale`; damper and inertia are equal on both axes.
- Airspeed estimate: `target = max(0, (pitch - forward_threshold) / (1 - forward_threshold))`, `airspeed += (target - airspeed) * (1 - exp(-dt / tau_s))`, clamped `0..1`, `tau_s = 0` snaps. `ControlFrame.pitch` +1 is forward.
- Rotor amplitude gains the factor `(1 + airspeed_factor * airspeed)` before the existing `0..1` clamp.
- Unboosted: spring centre always `(0, 0)`; blend `c` moves at rate `1 / trim_slew_s` per second toward 1 (clamped) or 0 (free), `trim_slew_s = 0` snaps; spring `= spring_coefficient * (1 - c)`; friction `= friction + (clamp_friction - friction) * c`; lock while clamped and reset while free are no-ops.
- Capability: an unsupported condition kind is logged once at WARNING and its commands dropped; a query mask of 0 counts every condition as unsupported; `run` refuses (exit 1) an `unboosted` profile on a base without friction.
- Profile handoff on `PROFILE_CYCLE`: anchor to centre, clamp off, blend 0, airspeed 0, fresh weapon, rotor spool fraction and running flag copied, ALL_OFF latch and previous buttons carried.
- Shipped values: littlebird-* `unboosted` spring 0.12, friction 0.02, clamp_friction 0.50, damper 0.15, inertia 0.05, airspeed_factor 0.6; lakota `force_trim` 0.50 / 0.10 / — / 0.25 / 0.08 / 0.15; havoc `force_trim` 0.60 / 0.12 / — / 0.30 / 0.10 / 0.15; estimator `{"kind": "input", "forward_threshold": 0.15, "tau_s": 4.0}` everywhere.
- Files under 200 lines, functions under 50, `logging` not `print`, no bare `except`, no TODOs; every value here is owner taste or doctrine shape, never a game value.
- Version becomes 0.2.0; README never claims a hardware result.

## Review Focus

1. Reset tapped mid-blend (lock, then reset before `trim_slew_s` elapsed): the blend must turn back from its current value with no jump. Test in Task 5 (`test_reset_mid_blend_turns_back_from_current_value`).
2. `trim_slew_s = 0` in unboosted mode: the blend must snap, never divide by zero. Test in Task 5 (`test_zero_slew_snaps_the_clamp`).
3. A base whose `SDL_HapticQuery` returns 0: every condition is treated as unsupported with one warning, springs and sines still play, and an unboosted profile is refused at `run`. Tests in Task 8 (`test_zero_capability_mask_disables_every_condition_once`) and Task 9 (`test_run_refuses_unboosted_profile_when_query_is_zero`).
4. `airspeed_factor` that pushes the buzz past 1.0 (high collective, full deflection, fast): the amplitude stays clamped at 1.0. Test in Task 4 (`test_airspeed_factor_is_clamped_to_unit_range`).
5. `PROFILE_CYCLE` while the Littlebird is clamped, then cycling back: the incoming engine starts free and centred both times, and the rotor keeps its spool. Test in Task 6 (`test_cycling_back_to_a_clamped_engine_starts_it_free`).

---

### Task 1: Condition commands through the clamp and the force log

**Files:**
- Modify: `src/wardogs_flight_eng/engine/commands.py`
- Modify: `src/wardogs_flight_eng/outputs/clamp.py`
- Modify: `src/wardogs_flight_eng/outputs/logging_backend.py`
- Test: `tests/test_frame_commands.py`, `tests/test_backends.py`

**Interfaces:**
- Produces: `FrictionCommand(axis: Axis, coefficient: float)`, `DamperCommand(axis: Axis, coefficient: float)`, `InertiaCommand(axis: Axis, coefficient: float)` (frozen, slots, coefficient 0..1), `ConditionCommand = FrictionCommand | DamperCommand | InertiaCommand`, and `Command` extended with them. Log kinds `"friction"`, `"damper"`, `"inertia"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_frame_commands.py (extend the hashability test)
def test_condition_commands_are_hashable_value_objects() -> None:
    a = FrictionCommand(Axis.PITCH, 0.1)
    assert a == FrictionCommand(Axis.PITCH, 0.1) and hash(a) == hash(FrictionCommand(Axis.PITCH, 0.1))
    assert {DamperCommand(Axis.ROLL, 0.2), InertiaCommand(Axis.ROLL, 0.05)}  # distinct kinds

# tests/test_backends.py
def test_clamp_limits_condition_coefficients_to_ceiling() -> None:
    inner = RecordingBackend()
    ClampedBackend(inner, ceiling=0.3).apply(
        0.0,
        [FrictionCommand(Axis.PITCH, 0.9), DamperCommand(Axis.ROLL, 0.2),
         InertiaCommand(Axis.PITCH, float("nan"))],
    )
    assert inner.commands == [
        FrictionCommand(Axis.PITCH, 0.3), DamperCommand(Axis.ROLL, 0.2),
        InertiaCommand(Axis.PITCH, 0.0),
    ]

def test_logging_backend_records_condition_kinds(tmp_path: Path) -> None:
    log = tmp_path / "f.jsonl"
    b = LoggingBackend(log)
    b.apply(0.5, [FrictionCommand(Axis.PITCH, 0.02), DamperCommand(Axis.ROLL, 0.15),
                  InertiaCommand(Axis.ROLL, 0.05)])
    b.close()
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(r["kind"], r["axis"], r["coefficient"]) for r in rows] == [
        ("friction", "pitch", 0.02), ("damper", "roll", 0.15), ("inertia", "roll", 0.05)
    ]
```

Use the recording backend `tests/test_backends.py` already uses for the clamp tests (see `test_clamp_limits_each_command_kind_independently`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_frame_commands.py tests/test_backends.py -v`
Expected: FAIL with `ImportError: cannot import name 'FrictionCommand'`

- [ ] **Step 3: Add the three dataclasses and `ConditionCommand` to `engine/commands.py`; extend `Command`**

Docstring each as a single-axis condition with a normalised coefficient; the module docstring's magnitude note already covers them.

- [ ] **Step 4: Extend `ClampedBackend._clamp` and `_unchanged` in `outputs/clamp.py`**

Add a `case FrictionCommand(coefficient=value) | DamperCommand(coefficient=value) | InertiaCommand(coefficient=value)` that limits to `[0, ceiling]` and replaces `coefficient`; widen `_unchanged`'s parameter type to include `ConditionCommand`. Add `ConditionCommand` to `_KINDS` in `logging_backend.py` with the kind names above.

- [ ] **Step 5: Run the tests and the type checker**

Run: `uv run pytest tests/test_frame_commands.py tests/test_backends.py -v && uv run mypy --strict src`
Expected: PASS; mypy clean (an `assert_never` in `clamp.py` and `sdl_haptic.py` will fail mypy until Task 8 handles the new kinds there, so add a temporary `case FrictionCommand() | DamperCommand() | InertiaCommand(): log.debug("condition %s not yet played", command)` branch in `sdl_haptic._dispatch`; Task 8 replaces it).

- [ ] **Step 6: Commit**

```bash
git add src/wardogs_flight_eng/engine/commands.py src/wardogs_flight_eng/outputs/clamp.py src/wardogs_flight_eng/outputs/logging_backend.py src/wardogs_flight_eng/outputs/sdl_haptic.py tests/test_frame_commands.py tests/test_backends.py
git commit -m "feat: friction, damper and inertia commands through the clamp and the log"
```

---

### Task 2: Profile schema for feel modes, conditions and the estimator

**Files:**
- Create: `src/wardogs_flight_eng/engine/profile_sections.py` (the `Feel`, `Rotor`, `Recoil`, `Safety`, `Estimator` models moved out of `profile.py`)
- Modify: `src/wardogs_flight_eng/engine/profile.py` (keeps `Profile`, `ProfileError`, `load_profile`, `PROFILES_DIR`, the `__all__` re-exports)
- Create: `tests/fixtures/littlebird-v0.1.0.json` (a verbatim copy of the current `profiles/littlebird-miniguns.json`, taken before this task edits it)
- Modify: `src/wardogs_flight_eng/profiles/littlebird-miniguns.json`, `littlebird-rockets.json`, `lakota.json`, `havoc.json`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `FeelMode = Literal["force_trim", "unboosted"]`; `Feel` fields `mode: FeelMode`, `spring_coefficient`, `roll_scale`, `deadband`, `trim_slew_s`, `friction: Unit`, `clamp_friction: Unit | None = None`, `damper: Unit`, `inertia: Unit`; `Rotor.airspeed_factor: NonNegative`; `Estimator(kind: Literal["input"], forward_threshold: Annotated[float, Field(ge=0, lt=1, allow_inf_nan=False)], tau_s: NonNegative)`; `Profile.estimator: Estimator`; `Profile.from_document(raw: dict[str, Any]) -> Profile` (classmethod; pydantic failures become `ProfileError`, used by `load_profile`). Rule messages: `feel.friction {v} must be <= spring_coefficient / 4 ({limit})`, `feel.clamp_friction is required when feel.mode is 'unboosted'`, `feel.clamp_friction is only valid when feel.mode is 'unboosted'`, `feel.clamp_friction {v} must be >= feel.friction {f}`. `load_profile` appends the migration hint `"this profile predates 0.2.0: copy the shipped profile for its airframe from the profiles directory, fill device_map and re-run calibrate"` when a required field under `feel`, `rotor` or `estimator` is missing.

- [ ] **Step 1: Copy the fixture, then write the failing tests**

```bash
mkdir -p tests/fixtures && cp src/wardogs_flight_eng/profiles/littlebird-miniguns.json tests/fixtures/littlebird-v0.1.0.json
```

```python
def test_shipped_profiles_carry_the_decided_feel() -> None:
    lb = load_profile(PROFILES / "littlebird-miniguns.json")
    assert (lb.feel.mode, lb.feel.spring_coefficient, lb.feel.friction, lb.feel.clamp_friction,
            lb.feel.damper, lb.feel.inertia, lb.rotor.airspeed_factor) == (
        "unboosted", 0.12, 0.02, 0.5, 0.15, 0.05, 0.6)
    assert lb.estimator == Estimator(kind="input", forward_threshold=0.15, tau_s=4.0)
    havoc = load_profile(PROFILES / "havoc.json")
    assert havoc.feel.mode == "force_trim" and havoc.feel.clamp_friction is None
    assert {"friction", "damper", "inertia", "airspeed_factor"} <= set(havoc.taste)

def test_v0_1_0_profile_fails_with_migration_hint() -> None:
    with pytest.raises(ProfileError, match="feel.mode.*predates 0.2.0.*calibrate"):
        load_profile(Path(__file__).parent / "fixtures" / "littlebird-v0.1.0.json")

@pytest.mark.parametrize(
    ("update", "needle"),
    [
        ({"mode": "force_trim", "clamp_friction": 0.4}, "clamp_friction"),   # rejected in force_trim
        ({"mode": "unboosted", "clamp_friction": None}, "clamp_friction"),    # required in unboosted
        ({"friction": 0.2}, "spring_coefficient / 4"),                        # 0.2 > 0.5 / 4 on lakota
        ({"mode": "unboosted", "friction": 0.1, "clamp_friction": 0.05}, "clamp_friction"),
    ],
)
def test_feel_rules_are_enforced(update: dict[str, Any], needle: str) -> None:
    raw = _raw("lakota"); raw["feel"].update(update)
    with pytest.raises(ProfileError, match=needle):
        Profile.model_validate(raw)   # wrap: load_profile on a tmp file is also fine

def test_condition_gains_above_ceiling_are_profile_errors() -> None:
    raw = _raw("lakota"); raw["feel"]["damper"] = 0.7
    with pytest.raises(ProfileError, match="feel.damper"):
        Profile.model_validate(raw).validate_against(load_constants())

def test_estimator_threshold_below_one() -> None:
    raw = _raw("lakota"); raw["estimator"]["forward_threshold"] = 1.0
    with pytest.raises(ProfileError, match="forward_threshold"):
        Profile.model_validate(raw)
```

The `friction <= spring_coefficient / 4` and `clamp_friction` rules are pydantic `model_validator(mode="after")` checks on `Feel`; a pydantic `ValidationError` must surface as `ProfileError` from `load_profile` and from `Profile.model_validate` alike (wrap `model_validate` in a classmethod `Profile.from_document(raw)` that converts, and use it in the tests and in `load_profile`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_profile.py -v`
Expected: FAIL (`Estimator` not importable; shipped profiles lack the fields)

- [ ] **Step 3: Create `engine/profile_sections.py` and slim `profile.py`**

Move `Unit`, `SignedUnit`, `NonNegative`, `Positive`, `Feel`, `Rotor`, `Recoil`, `Safety` into the new module unchanged, add the fields and validators above and the `Estimator` model; `profile.py` imports and re-exports them (`__all__` gains `Estimator`, `FeelMode`). Extend `_check_gains_within_ceiling` with `feel.friction`, `feel.clamp_friction` (when set), `feel.damper`, `feel.inertia`. In `load_profile` / `from_document`, when any error has `type == "missing"` and `loc[0] in ("feel", "rotor", "estimator")`, append the migration hint to the message.

- [ ] **Step 4: Update the four shipped profiles**

Values from Global Constraints; add `"mode"`, `"friction"`, `"clamp_friction"` (Littlebird only), `"damper"`, `"inertia"` under `feel`, `"airspeed_factor"` under `rotor`, the `estimator` block after `safety`, and the new names to `taste`.

- [ ] **Step 5: Run the profile tests, then the whole suite**

Run: `uv run pytest tests/test_profile.py -v && uv run pytest -q`
Expected: profile tests PASS; the full suite passes except `tests/test_synth.py::test_idle_tick_emits_centered_springs_and_silent_buzz` (spring 0.35 is now 0.12) — fix that assertion to `{Axis.PITCH: 0.12, Axis.ROLL: pytest.approx(0.06)}` in this task so the suite is green at the commit.

- [ ] **Step 6: Commit**

```bash
git add src/wardogs_flight_eng/engine/profile.py src/wardogs_flight_eng/engine/profile_sections.py src/wardogs_flight_eng/profiles tests/fixtures tests/test_profile.py tests/test_synth.py
git commit -m "feat: profile feel modes, condition gains and estimator block with a migration hint"
```

---

### Task 3: Flight state seam and the input estimator

**Files:**
- Create: `src/wardogs_flight_eng/engine/flight_state.py`
- Test: `tests/test_flight_state.py`

**Interfaces:**
- Produces: `FlightState(airspeed: float, collective: float, deflection: float)` (frozen, slots); `StateEstimator` Protocol with `step(self, dt: float, frame: ControlFrame, deflection: float) -> FlightState` and `restart(self) -> None`; `InputEstimator(forward_threshold: float, tau_s: float)` with property `airspeed`.

- [ ] **Step 1: Write the failing tests**

```python
def _est() -> InputEstimator:
    return InputEstimator(forward_threshold=0.15, tau_s=4.0)

def test_full_forward_reaches_63_percent_at_tau() -> None:
    e = _est()
    for _ in range(400):
        state = e.step(0.01, frame(pitch=1.0), 0.0)
    assert state.airspeed == pytest.approx(1 - math.exp(-1), abs=1e-3)

def test_partial_forward_targets_the_scaled_value() -> None:
    e = InputEstimator(0.15, 0.0)          # tau 0 snaps
    assert e.step(0.01, frame(pitch=0.5), 0.0).airspeed == pytest.approx(0.35 / 0.85)

def test_aft_and_below_threshold_decay_to_zero() -> None:
    e = InputEstimator(0.15, 0.0)
    e.step(0.01, frame(pitch=1.0), 0.0)
    assert e.step(0.01, frame(pitch=0.1), 0.0).airspeed == 0.0
    e.step(0.01, frame(pitch=1.0), 0.0)
    assert e.step(0.01, frame(pitch=-1.0), 0.0).airspeed == 0.0

def test_state_carries_collective_and_deflection_and_zero_dt_holds() -> None:
    e = _est()
    e.step(0.01, frame(pitch=1.0, collective=0.7), 0.3)
    before = e.airspeed
    state = e.step(0.0, frame(pitch=1.0, collective=0.7), 0.3)
    assert (state.collective, state.deflection, state.airspeed) == (0.7, 0.3, before)

def test_restart_zeroes_the_estimate() -> None:
    e = InputEstimator(0.15, 0.0)
    e.step(0.01, frame(pitch=1.0), 0.0)
    e.restart()
    assert e.airspeed == 0.0

def test_rejects_threshold_of_one_and_negative_tau() -> None:
    with pytest.raises(ValueError): InputEstimator(1.0, 1.0)
    with pytest.raises(ValueError): InputEstimator(0.1, -1.0)
```

Use a local `frame(...)` helper like `tests/test_synth.py`'s.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_flight_state.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `engine/flight_state.py`**

`InputEstimator.step` applies the Global Constraints formula; negative `dt` counts as zero (as `TrimState.step` does); `restart` sets the estimate to 0. Validate `0 <= forward_threshold < 1` and `tau_s >= 0` in `__init__` with `ValueError` messages naming the argument.

- [ ] **Step 4: Run the tests and the layering test**

Run: `uv run pytest tests/test_flight_state.py tests/test_layering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/engine/flight_state.py tests/test_flight_state.py
git commit -m "feat: FlightState seam with the input-only airspeed estimator"
```

---

### Task 4: Rotor texture with airspeed and the spool handoff

**Files:**
- Modify: `src/wardogs_flight_eng/engine/rotor.py`
- Test: `tests/test_rotor.py`

**Interfaces:**
- Produces: `RotorModel.__init__(..., airspeed_factor: float = 0.0)` (validated `>= 0`); `amplitude(self, collective: float, deflection: float, airspeed: float = 0.0) -> float`; property `spool_fraction -> float` (`rpm / operating_rpm`); `take_over(self, spool_fraction: float, running: bool) -> None` (sets `rpm = clamp(fraction, 0, 1) * operating_rpm` and `running`).

- [ ] **Step 1: Write the failing tests**

```python
def test_amplitude_grows_with_airspeed_factor() -> None:
    r = RotorModel(300, 0, 850, base_amplitude=0.4, deflection_factor=0.5, airspeed_factor=0.6)
    r.step(0.01)
    assert r.amplitude(1.0, 0.0, airspeed=0.5) == pytest.approx(0.4 * 1.3)
    assert r.amplitude(1.0, 0.0) == pytest.approx(0.4)          # default airspeed 0

def test_airspeed_factor_is_clamped_to_unit_range() -> None:   # Review Focus 4
    r = RotorModel(300, 0, 850, base_amplitude=0.6, deflection_factor=1.0, airspeed_factor=2.0)
    r.step(0.01)
    assert r.amplitude(1.0, 1.0, airspeed=1.0) == 1.0

def test_take_over_copies_spool_fraction_into_this_rotor_speed() -> None:
    r = RotorModel(250, 0, 850, 0.3, 0.5)
    r.take_over(0.5, running=False)
    assert (r.rpm, r.running, r.spool_fraction) == (125.0, False, 0.5)
    r.take_over(1.7, running=True)
    assert r.rpm == 250.0

def test_rejects_negative_airspeed_factor() -> None:
    with pytest.raises(ValueError, match="airspeed_factor"):
        RotorModel(300, 0, 850, 0.3, 0.5, airspeed_factor=-0.1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rotor.py -v`
Expected: FAIL with `TypeError: unexpected keyword argument 'airspeed_factor'`

- [ ] **Step 3: Implement in `engine/rotor.py`**

Add the constructor argument to the validation loop, the `airspeed` term to `amplitude` (multiply by `1 + airspeed_factor * airspeed` before the clamp), the `spool_fraction` property and `take_over`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_rotor.py -v`
Expected: PASS (existing tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/engine/rotor.py tests/test_rotor.py
git commit -m "feat: rotor buzz grows with the airspeed estimate; spool handoff"
```

---

### Task 5: The feel model (modes, clamp blend, four conditions per axis)

**Files:**
- Create: `src/wardogs_flight_eng/engine/feel.py`
- Test: `tests/test_feel.py`

**Interfaces:**
- Consumes: `Feel` (Task 2), `TrimState` (`engine/trim.py`), commands (Task 1).
- Produces: `FeelModel(feel: Feel)` with properties `center_pitch`, `center_roll`, `clamp_blend`; methods `lock(pitch: float, roll: float) -> None`, `reset() -> None`, `step(dt: float) -> None`, `conditions() -> list[Command]`, `restart() -> None`. `conditions()` returns, in this order: `SpringCommand` pitch, `SpringCommand` roll, `FrictionCommand` pitch, `FrictionCommand` roll, `DamperCommand` pitch, `DamperCommand` roll, `InertiaCommand` pitch, `InertiaCommand` roll.

- [ ] **Step 1: Write the failing tests**

```python
LB = load_profile(PROFILES_DIR / "littlebird-miniguns.json").feel     # unboosted
LAK = load_profile(PROFILES_DIR / "lakota.json").feel                  # force_trim

def by_kind(cmds: list[Command], kind: type, axis: Axis) -> float:
    (c,) = [c for c in cmds if isinstance(c, kind) and c.axis is axis]
    return c.coefficient

def test_force_trim_emits_constant_conditions_and_moves_the_anchor() -> None:
    f = FeelModel(LAK)
    f.lock(0.4, -0.2); f.step(1.0)
    cmds = f.conditions()
    springs = [c for c in cmds if isinstance(c, SpringCommand)]
    assert [(s.axis, s.center, s.coefficient) for s in springs] == [
        (Axis.PITCH, pytest.approx(0.4), 0.5), (Axis.ROLL, pytest.approx(-0.2), 0.25)]
    assert by_kind(cmds, FrictionCommand, Axis.PITCH) == 0.1
    assert by_kind(cmds, FrictionCommand, Axis.ROLL) == pytest.approx(0.05)   # roll_scale
    assert by_kind(cmds, DamperCommand, Axis.ROLL) == 0.25 == by_kind(cmds, DamperCommand, Axis.PITCH)
    assert by_kind(cmds, InertiaCommand, Axis.ROLL) == 0.08
    assert [type(c) for c in cmds] == [SpringCommand] * 2 + [FrictionCommand] * 2 + [DamperCommand] * 2 + [InertiaCommand] * 2

def test_unboosted_free_is_weak_spring_about_centre_with_light_friction() -> None:
    f = FeelModel(LB); f.step(0.01)
    cmds = f.conditions()
    pitch_spring = next(c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH)
    assert (pitch_spring.center, pitch_spring.coefficient) == (0.0, 0.12)
    assert by_kind(cmds, FrictionCommand, Axis.PITCH) == 0.02

def test_unboosted_lock_clamps_over_the_slew_and_never_moves_the_centre() -> None:
    f = FeelModel(LB)                              # trim_slew_s 0.3
    f.lock(0.6, 0.1)
    f.step(0.15)
    assert f.clamp_blend == pytest.approx(0.5)
    half = f.conditions()
    assert by_kind(half, SpringCommand, Axis.PITCH) == pytest.approx(0.06)
    assert by_kind(half, FrictionCommand, Axis.PITCH) == pytest.approx(0.26)
    f.step(0.15)
    done = f.conditions()
    assert by_kind(done, SpringCommand, Axis.PITCH) == 0.0
    assert by_kind(done, FrictionCommand, Axis.PITCH) == 0.5
    assert by_kind(done, FrictionCommand, Axis.ROLL) == 0.25
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)

def test_lock_while_clamped_and_reset_while_free_are_no_ops() -> None:
    f = FeelModel(LB)
    f.reset(); f.step(0.01)
    assert f.clamp_blend == 0.0
    f.lock(0.5, 0.0); f.step(1.0); f.lock(-0.5, 0.0); f.step(0.01)
    assert f.clamp_blend == 1.0

def test_reset_mid_blend_turns_back_from_current_value() -> None:   # Review Focus 1
    f = FeelModel(LB)
    f.lock(0.5, 0.0); f.step(0.15)
    f.reset(); f.step(0.075)
    assert f.clamp_blend == pytest.approx(0.25)

def test_zero_slew_snaps_the_clamp() -> None:                        # Review Focus 2
    f = FeelModel(LB.model_copy(update={"trim_slew_s": 0.0}))
    f.lock(0.0, 0.0); f.step(0.0)
    assert f.clamp_blend == 1.0

def test_restart_frees_and_centres_immediately() -> None:
    f = FeelModel(LAK); f.lock(0.4, 0.4); f.step(1.0); f.restart()
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)
    g = FeelModel(LB); g.lock(0.0, 0.0); g.step(1.0); g.restart()
    assert g.clamp_blend == 0.0
```

(`by_kind` for `SpringCommand` reads `.coefficient`, which springs also carry.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_feel.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `engine/feel.py`**

A private `_Blend(slew_s)` holds `value` and `target`, `retarget(target)`, `step(dt)` moving `value` toward `target` by `dt / slew_s` (snap when `slew_s == 0`), clamped to `[0, 1]`. `FeelModel` owns a `TrimState` (force_trim) or the blend (unboosted) and builds the eight commands from `Feel` per the Global Constraints. `restart` recreates both from scratch.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_feel.py tests/test_layering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/engine/feel.py tests/test_feel.py
git commit -m "feat: FeelModel with force-trim and unboosted modes and a slewed clamp"
```

---

### Task 6: Engine integration and the profile handoff

**Files:**
- Create: `src/wardogs_flight_eng/engine/builders.py` (`DEFAULT_SPOOL_DOWN_RPM_PER_S`, `build_rotor(profile, airframe) -> RotorModel`, `build_weapon(profile, constants) -> tuple[WeaponModel | None, float]` returning the model and `pulse_s`, `build_estimator(profile) -> StateEstimator`; the `_spool_down` and `_weapon_model` bodies move here)
- Modify: `src/wardogs_flight_eng/engine/synth.py` (re-exports `DEFAULT_SPOOL_DOWN_RPM_PER_S`; `_springs` is replaced by `self._feel.conditions()`)
- Modify: `src/wardogs_flight_eng/runtime/loop.py:95-104` (`_cycle_profile`)
- Test: `tests/test_synth.py`, `tests/test_loop.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 5.
- Produces: `FlightEngine.__init__(profile, constants, estimator: StateEstimator | None = None)` (None builds from `profile.estimator`); `FlightEngine.take_over(outgoing: FlightEngine) -> None` (Global Constraints handoff list; also copies `all_off` and the previous held buttons); property `state -> FlightState` (the last tick's); `step` returns `[*feel.conditions(), *buzz, *recoil]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_synth.py — change test_trim_lock_tap_moves_spring_center_once to use "lakota" (expect 0.4 / -0.2 as before) and add:
def test_idle_tick_emits_all_four_conditions_per_axis() -> None:
    cmds = engine_for("lakota").step(0.01, frame())
    assert [type(c) for c in cmds[:8]] == [SpringCommand] * 2 + [FrictionCommand] * 2 + [DamperCommand] * 2 + [InertiaCommand] * 2

def test_littlebird_lock_clamps_instead_of_moving_the_centre() -> None:
    e = engine_for("littlebird-miniguns")
    e.step(0.01, frame(0.4, 0.0, 0.5, 0, Button.TRIM_LOCK))
    for _ in range(40):
        cmds = e.step(0.01, frame(0.4, 0.0, 0.5, 0))
    spring = next(c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH)
    friction = next(c for c in cmds if isinstance(c, FrictionCommand) and c.axis is Axis.PITCH)
    assert (spring.center, spring.coefficient, friction.coefficient) == (0.0, 0.0, 0.5)

def test_buzz_grows_with_sustained_forward_stick() -> None:
    e = engine_for("littlebird-miniguns")
    early = e.step(0.01, frame(pitch=0.6, collective=1.0))
    for _ in range(2000):
        late = e.step(0.01, frame(pitch=0.6, collective=1.0))
    mag = lambda cmds: next(c.magnitude for c in cmds if isinstance(c, SineCommand))
    assert mag(late) > 1.2 * mag(early)
    assert e.state.airspeed == pytest.approx((0.6 - 0.15) / 0.85, abs=0.01)

def test_stub_estimator_is_used_when_given() -> None:
    class Fast:
        def step(self, dt, frame, deflection): return FlightState(1.0, frame.collective, deflection)
        def restart(self): pass
    e = FlightEngine(load_profile(PROFILES / "lakota.json"), load_constants(), estimator=Fast())
    for _ in range(400):
        cmds = e.step(0.01, frame(collective=1.0))
    assert next(c.magnitude for c in cmds if isinstance(c, SineCommand)) == pytest.approx(0.3 * 1.15)

def pitch_friction(cmds: list[Command]) -> float:
    return next(c.coefficient for c in cmds if isinstance(c, FrictionCommand) and c.axis is Axis.PITCH)

def test_watchdog_tick_advances_neither_blend_nor_airspeed() -> None:
    e = engine_for("littlebird-miniguns")          # trim_slew_s 0.3, tau_s 4.0
    e.step(0.01, frame(1.0, 0, 0.5, 0, Button.TRIM_LOCK))   # blend 1/30, airspeed 1 - e^-0.0025
    assert e.step(5.0, frame(1.0)) == [AllOffCommand()]
    assert e.state.airspeed == pytest.approx(1 - math.exp(-0.0025), abs=1e-5)
    cmds = e.step(0.01, frame(1.0))                   # blend 2/30 now, not more
    assert pitch_friction(cmds) == pytest.approx(0.02 + 0.48 * 2 / 30, abs=1e-3)

def test_take_over_resets_feel_and_airspeed_and_carries_the_rotor() -> None:
    lb, lak = engine_for("littlebird-miniguns"), engine_for("lakota")
    lb.step(0.01, frame(1.0, 0, 1.0, 0, Button.TRIM_LOCK))
    for _ in range(300):                               # 3 s: the Littlebird spools fully
        lb.step(0.01, frame(1.0, 0, 1.0, 0))
    lak.take_over(lb)
    cmds = lak.step(0.01, frame())
    spring = next(c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH)
    sine = next(c for c in cmds if isinstance(c, SineCommand))
    assert spring.center == 0.0 and lak.state.airspeed == 0.0
    assert sine.frequency_hz == pytest.approx(250 / 60, rel=0.01)   # Lakota rpm at full spool

def test_cycling_back_to_a_clamped_engine_starts_it_free() -> None:   # Review Focus 5
    lb, lak = engine_for("littlebird-miniguns"), engine_for("lakota")
    lb.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    for _ in range(40):
        clamped = lb.step(0.01, frame())
    assert pitch_friction(clamped) == 0.5
    lak.take_over(lb)
    lb.take_over(lak)
    assert pitch_friction(lb.step(0.01, frame())) == 0.02
```

Use the module's existing `frame(pitch, roll, collective, pedals, *held)` helper and `import math`. Keep every `dt` at or below the profile watchdog (0.25 s) except where a test exercises it. In `tests/test_loop.py`, keep every existing profile-cycle test green and add:

```python
def test_profile_cycle_hands_over_through_take_over(...) -> None:
    # two engines; drive TRIM_LOCK on the first, cycle; assert the second's first
    # spring command has center 0.0 and that take_over carried the all_off latch
```

(Follow the fixtures the existing `test_profile_cycle_*` tests use.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_synth.py tests/test_loop.py -v`
Expected: FAIL (`FrictionCommand` never emitted; `take_over` missing)

- [ ] **Step 3: Create `engine/builders.py`, rewire `synth.py`, update `loop._cycle_profile`**

`FlightEngine` holds `_feel: FeelModel`, `_estimator`, `_state`. `step`: after the watchdog gate, dispatch taps to `_feel.lock/reset` and the rotor, `_feel.step(dt)`, `_rotor.step(dt)`, compute deflection from `_feel.center_*`, `self._state = self._estimator.step(dt, frame, deflection)`, then `[*self._feel.conditions(), *self._buzz(), *self._recoil(...)]` with `_buzz` using `self._state`. `take_over` per Global Constraints: `_feel.restart()`, `_estimator.restart()`, `_rotor.take_over(outgoing._rotor.spool_fraction, outgoing._rotor.running)`, rebuild the weapon via `build_weapon`, copy `all_off` and `_previous_held`. `loop._cycle_profile` replaces the two `incoming.*` lines with `incoming.take_over(outgoing)`.

- [ ] **Step 4: Run the suite, lint and types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy --strict src`
Expected: all green; `synth.py` and `builders.py` each under 200 lines (`wc -l`).

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/engine/builders.py src/wardogs_flight_eng/engine/synth.py src/wardogs_flight_eng/runtime/loop.py tests/test_synth.py tests/test_loop.py
git commit -m "feat: engine emits feel conditions, reads airspeed through the estimator, hands off on profile cycle"
```

---

### Task 7: SDL condition effects and the capability probe

**Files:**
- Modify: `src/wardogs_flight_eng/inputs/sdl_api.py` (Protocol gains `SDL_HAPTIC_DAMPER`, `SDL_HAPTIC_INERTIA`, `SDL_HAPTIC_FRICTION`)
- Modify: `src/wardogs_flight_eng/inputs/sdl_real.py` (the three attributes; `_member` maps them to `"condition"`)
- Modify: `tests/sdl_support.py` (`FakeSdl` constants `1 << 8`, `1 << 9`, `1 << 10`; default `supported` includes all three)
- Create: `src/wardogs_flight_eng/outputs/sdl_conditions.py` (`spring_effect` moves here; new `condition_effect`)
- Modify: `src/wardogs_flight_eng/outputs/sdl_effects.py` (`_on_axis` -> `on_axis`, `_direction` -> `direction`, both public; `spring_effect` removed), `outputs/sdl_haptic.py`, `outputs/sdl_probe.py`, `tests/test_sdl_real.py` (import `spring_effect` from `sdl_conditions`)
- Test: `tests/test_sdl_haptic.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `condition_effect(api: SdlApi, axes: HapticAxisMap, command: ConditionCommand, length_ms: int) -> HapticEffect` (type from the command class; coefficient on the haptic axis for both `right_coeff` and `left_coeff`; saturation `0xFFFF` on that axis; centre and deadband zero); `PrimitiveReport` gains `friction: bool`, `damper: bool`, `inertia: bool`; `check_device_command` passes on spring, spring_center_moves, sine and constant, and prints `WARN: not accepted: <kinds> (unboosted profiles cannot run without friction; force_trim profiles run without the missing conditions)` with exit 0 when only conditions are missing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sdl_haptic.py
@pytest.mark.parametrize(
    ("command", "kind", "coeff"),
    [
        (FrictionCommand(Axis.PITCH, 0.1), "SDL_HAPTIC_FRICTION", 3277),
        (DamperCommand(Axis.ROLL, 0.25), "SDL_HAPTIC_DAMPER", 8192),
        (InertiaCommand(Axis.PITCH, 0.08), "SDL_HAPTIC_INERTIA", 2621),
    ],
)
def test_condition_effect_shape(command, kind, coeff) -> None:
    fake = FakeSdl(stick())
    effect = condition_effect(fake, STANDARD_AXES, command, 1000)
    assert effect.type == getattr(fake, kind)
    on = (0, coeff, 0) if command.axis is Axis.PITCH else (coeff, 0, 0)
    assert effect.condition.right_coeff == effect.condition.left_coeff == on
    assert effect.condition.center == effect.condition.deadband == (0, 0, 0)
    assert effect.condition.length == 1000

# tests/test_cli.py
def test_check_device_reports_conditions_and_warns_when_only_they_are_missing() -> None:
    legacy = FakeSdl(stick(), supported=FakeSdl.SDL_HAPTIC_CONSTANT | FakeSdl.SDL_HAPTIC_SINE | FakeSdl.SDL_HAPTIC_SPRING)
    result = invoke(["check-device"], api=legacy)
    assert result.code == 0 and "WARN" in result.output and "friction" in result.output
    full = invoke(["check-device"], api=FakeSdl(stick()))
    assert full.code == 0 and "PASS" in full.output and "inertia" in full.output
```

Keep `test_check_device_exit_code_reflects_report` as it is (spring-only still exits 1).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sdl_haptic.py tests/test_cli.py -v`
Expected: FAIL (`condition_effect` missing; `FakeSdl` lacks the constants)

- [ ] **Step 3: Implement**

Add the constants to the Protocol, the real adapter and the fake. Create `sdl_conditions.py` with the moved `spring_effect` and `condition_effect` (a `dict[type, str]` from command class to the api attribute name, resolved with `getattr`). In `sdl_probe._probe` create one zero-coefficient effect of each condition kind with `attempt`, fill the three new report fields. In `cli_devices.check_device_command` split the required primitives from the condition ones for the PASS / WARN / FAIL decision.

- [ ] **Step 4: Run the suite, lint and types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy --strict src`
Expected: green

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/inputs/sdl_api.py src/wardogs_flight_eng/inputs/sdl_real.py src/wardogs_flight_eng/outputs/sdl_conditions.py src/wardogs_flight_eng/outputs/sdl_effects.py src/wardogs_flight_eng/outputs/sdl_haptic.py src/wardogs_flight_eng/outputs/sdl_probe.py src/wardogs_flight_eng/cli_devices.py tests/sdl_support.py tests/test_sdl_haptic.py tests/test_sdl_real.py tests/test_cli.py
git commit -m "feat: SDL friction, damper and inertia effects; check-device reports them"
```

---

### Task 8: Backend plays conditions persistently, gated by capability

**Files:**
- Create: `src/wardogs_flight_eng/outputs/sdl_capabilities.py`
- Modify: `src/wardogs_flight_eng/outputs/sdl_haptic.py` (replace the Task 1 placeholder branch)
- Modify: `tests/sdl_support.py` (`FakeSdl.query_result: int | None = None`; when set, `SDL_HapticQuery` returns it instead of `supported`)
- Test: `tests/test_sdl_haptic.py`

**Interfaces:**
- Consumes: Task 7 effects; `PersistentEffects` (`sdl_persistent.py`); `HapticChannel.query()`.
- Produces: `ConditionSupport(api: SdlApi, mask: int)` with `allows(command: ConditionCommand) -> bool` (logs one WARNING per unsupported kind, naming the kind and "the feel runs without it"; a mask of 0 logs one WARNING "the base did not report its capabilities; friction, damper and inertia are disabled" and marks all three missing), property `missing -> frozenset[str]` over `{"friction", "damper", "inertia"}`, classmethod `from_channel(api, channel)`. `SdlHapticBackend` gains property `missing_conditions -> frozenset[str]`. Conditions are persistent effects keyed `("friction", axis)`, `("damper", axis)`, `("inertia", axis)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_conditions_are_persistent_and_updated_only_on_change() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    tick = [FrictionCommand(Axis.PITCH, 0.02), DamperCommand(Axis.PITCH, 0.15), InertiaCommand(Axis.PITCH, 0.05)]
    for n in range(50):
        backend.apply(n / 100, tick)
    assert len(effect_calls(fake, "SDL_HapticNewEffect")) == 3
    assert fake.count("SDL_HapticUpdateEffect") == 0
    backend.apply(0.5, [FrictionCommand(Axis.PITCH, 0.5)])
    assert fake.count("SDL_HapticUpdateEffect") == 1
    assert last_effect(fake, fake.SDL_HAPTIC_FRICTION).condition.right_coeff == (0, 16384, 0)

def test_unsupported_condition_is_dropped_with_one_warning(caplog) -> None:
    fake = FakeSdl(stick(), supported=FakeSdl.SDL_HAPTIC_CONSTANT | FakeSdl.SDL_HAPTIC_SINE | FakeSdl.SDL_HAPTIC_SPRING | FakeSdl.SDL_HAPTIC_FRICTION)
    backend = open_backend(fake)
    with caplog.at_level(logging.WARNING):
        for n in range(10):
            backend.apply(n / 100, [DamperCommand(Axis.ROLL, 0.3), FrictionCommand(Axis.ROLL, 0.1)])
    assert backend.missing_conditions == frozenset({"damper", "inertia"})
    assert len([r for r in caplog.records if "damper" in r.message]) == 1
    assert all(e.type != fake.SDL_HAPTIC_DAMPER for e in fake.effects.values())
    assert any(e.type == fake.SDL_HAPTIC_FRICTION for e in fake.effects.values())

def test_zero_capability_mask_disables_every_condition_once(caplog) -> None:   # Review Focus 3
    fake = FakeSdl(stick(), supported=0)
    with caplog.at_level(logging.WARNING):
        backend = open_backend(fake)
        backend.apply(0.0, [SpringCommand(Axis.PITCH, 0.0, 0.3, 0.0), FrictionCommand(Axis.PITCH, 0.1)])
    assert backend.missing_conditions == frozenset({"friction", "damper", "inertia"})
    assert sum("did not report" in r.message for r in caplog.records) == 1

def test_all_off_silences_conditions_and_close_destroys_them() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, [FrictionCommand(Axis.PITCH, 0.3), InertiaCommand(Axis.ROLL, 0.1)])
    backend.all_off()
    assert all(e.condition.right_coeff == (0, 0, 0) for e in fake.effects.values())
    backend.close()
    assert len(destroyed_ids(fake)) == 2
```

With `supported=0` the fake also rejects `SDL_HapticNewEffect` for the spring; for Review Focus 3 build the fake so `SDL_HapticQuery` returns 0 while `SDL_HapticNewEffect` still accepts (add a `query_result: int | None` attribute to `FakeSdl`, used by `SDL_HapticQuery` when set).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sdl_haptic.py -v`
Expected: FAIL (`missing_conditions` missing; no condition effects created)

- [ ] **Step 3: Implement `sdl_capabilities.py` and wire `sdl_haptic.py`**

`SdlHapticBackend.__init__` builds `ConditionSupport.from_channel(...)` after the channel; `_dispatch` gets `case FrictionCommand() | DamperCommand() | InertiaCommand(): self._condition(t, command)`, which returns early unless `self._support.allows(command)`, else builds `condition_effect(...)` and plays it through `self._persistent` under its key. Keep `sdl_haptic.py` under 200 lines (move `_sine`/`_sine_effect` into `sdl_persistent.py` if needed).

- [ ] **Step 4: Run the suite, lint and types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy --strict src`
Expected: green; no `assert_never` gaps

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/outputs/sdl_capabilities.py src/wardogs_flight_eng/outputs/sdl_haptic.py src/wardogs_flight_eng/outputs/sdl_persistent.py tests/sdl_support.py tests/test_sdl_haptic.py
git commit -m "feat: persistent condition effects gated by the base's reported capabilities"
```

---

### Task 9: `run` refuses an unboosted profile on a base without friction

**Files:**
- Modify: `src/wardogs_flight_eng/cli_run_checks.py`, `src/wardogs_flight_eng/cli_run.py:143-170`
- Test: `tests/test_cli_run.py`

**Interfaces:**
- Consumes: `ConditionSupport` (Task 8), `HapticChannel`.
- Produces: `missing_conditions(device: SdlDevice) -> frozenset[str]` (opens a `HapticChannel`, reads `ConditionSupport.from_channel(...).missing`, closes the channel in a `finally`); `refuse_unboosted_without_friction(profiles: Sequence[Profile], missing: frozenset[str], device_name: str) -> None` raising `CliError(..., EXIT_CONFIG)` with the message `profile {name!r} uses feel.mode 'unboosted' but the base {device_name!r} reports no friction primitive, so the trim clamp could not hold; set feel.mode to 'force_trim' in that profile or use a base with friction`. `run_command` calls both after the `SDL_JoystickIsHaptic` check and before `_fly`.

- [ ] **Step 1: Write the failing tests**

```python
LEGACY = FakeSdl.SDL_HAPTIC_CONSTANT | FakeSdl.SDL_HAPTIC_SINE | FakeSdl.SDL_HAPTIC_SPRING

def bound_lakota(tmp_path: Path) -> Path:
    doc = json.loads((PROFILES_DIR / "lakota.json").read_text(encoding="utf-8"))
    doc["device_map"] = copy.deepcopy(BOUND_MAP)
    return write_profile(tmp_path / "lakota.json", doc)

def test_run_refuses_unboosted_profile_without_friction(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=200, then=detach_all, supported=LEGACY)
    result = invoke(["run", "--profile", str(profile)], api=fake)       # the fixture is the bound Littlebird
    assert result.code == 1 and "unboosted" in result.output and "friction" in result.output
    assert fake.count("SDL_HapticClose") >= 1 and joysticks_released(fake)

def test_run_refuses_unboosted_profile_when_query_is_zero(profile: Path) -> None:   # Review Focus 3
    fake = TickingSdl(stick(), pedals(), after=200, then=detach_all)
    fake.query_result = 0
    assert invoke(["run", "--profile", str(profile)], api=fake).code == 1

def test_run_allows_force_trim_profile_without_friction(tmp_path: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=200, then=detach_all, supported=LEGACY)
    result = invoke(["run", "--profile", str(bound_lakota(tmp_path))], api=fake)
    assert "unboosted" not in result.output and result.code == 2       # ran until the fake detached
```

`profile`, `_bounded`, `TickingSdl`, `detach_all`, `BOUND_MAP`, `write_profile` and `joysticks_released` already exist in `tests/test_cli_run.py` / `tests/cli_support.py`; `TickingSdl` must forward `supported=` to `FakeSdl` if it does not already.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_run.py -v`
Expected: FAIL (run proceeds; exit 0 or 2)

- [ ] **Step 3: Implement the two functions and the call site**

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy --strict src`
Expected: green

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/cli_run_checks.py src/wardogs_flight_eng/cli_run.py tests/test_cli_run.py
git commit -m "feat: run refuses an unboosted profile on a base without friction"
```

---

### Task 10: Plot gain rows, the clamp-cruise scenario and the dry run

**Files:**
- Create: `src/wardogs_flight_eng/runtime/plot_rows.py` (row rendering moved from `plot.py`: `_series`, `_changes`, `_polyline`, `_pulse`, `_transient`, `_axis_row`, plus new `_gain_row`)
- Modify: `src/wardogs_flight_eng/runtime/plot.py` (four rows: `pitch`, `roll`, `pitch gains`, `roll gains`; CSS classes `friction-line`, `damper-line`, `inertia-line`; legend entries `friction`, `damper`, `inertia`, `spring coefficient`; `HEIGHT` grows with the row count)
- Create: `tests/scenarios/littlebird-clamp-cruise.json`
- Test: `tests/test_plot.py`, `tests/test_dry_run.py`

**Interfaces:**
- Consumes: log kinds from Task 1.
- Produces: the scenario (same `device_map` and `devices` as `takeoff-trim-fire.json`; steps: `t 0.0 coll.axis0 -1.0`; `t 1.0 coll.axis0 0.2`; `t 4.0 stick.axis0 0.6` (after the 3 s spool-up, so the buzz comparison isolates airspeed); `t 10.0 grip.button0 true`; `t 10.1 grip.button0 false`; `t 14.0 grip.button1 true`; `t 14.1 grip.button1 false`; `t 15.0 stick.axis0 0.0`; `t 17.0 set {}`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plot.py — update test_plot_has_one_row_per_axis to expect 4 titled rows, and add:
def test_plot_draws_gain_lines_for_each_condition(tmp_path: Path) -> None:
    log = tmp_path / "f.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"t": 0.0, "kind": "friction", "axis": "pitch", "coefficient": 0.02},
        {"t": 0.3, "kind": "friction", "axis": "pitch", "coefficient": 0.5},
        {"t": 0.0, "kind": "damper", "axis": "roll", "coefficient": 0.15},
        {"t": 0.0, "kind": "inertia", "axis": "roll", "coefficient": 0.05},
        {"t": 0.0, "kind": "spring", "axis": "pitch", "center": 0.0, "coefficient": 0.12, "deadband": 0.02},
    ]) + "\n")
    out = tmp_path / "f.html"; write_plot_html(log, out)
    page = out.read_text()
    assert page.count('class="friction-line"') == 1 and 'class="damper-line"' in page and 'class="inertia-line"' in page
    assert ">pitch gains<" in page and ">roll gains<" in page

# tests/test_dry_run.py
def _clamp_run(tmp_path: Path) -> list[dict[str, Any]]:
    scenario = Scenario.load(SCENARIOS / "littlebird-clamp-cruise.json")
    log, _ = dry_run(profile("littlebird-miniguns"), load_constants(), scenario, tmp_path)
    return _rows(log)

def _at(rows, kind, axis, t):           # the record of `kind` on `axis` nearest to t
    return min((r for r in rows if r["kind"] == kind and r["axis"] == axis), key=lambda r: abs(r["t"] - t))

def test_dry_run_clamp_swaps_spring_for_friction_and_back(tmp_path: Path) -> None:
    rows = _clamp_run(tmp_path)
    assert (_at(rows, "friction", "pitch", 9.0)["coefficient"], _at(rows, "spring", "pitch", 9.0)["coefficient"]) == (0.02, 0.12)
    assert _at(rows, "friction", "pitch", 11.0)["coefficient"] == pytest.approx(0.5)
    assert _at(rows, "spring", "pitch", 11.0)["coefficient"] == 0.0
    assert _at(rows, "spring", "pitch", 11.0)["center"] == 0.0
    assert _at(rows, "spring", "pitch", 15.0)["coefficient"] == 0.12
    assert _at(rows, "friction", "pitch", 15.0)["coefficient"] == 0.02

def test_dry_run_buzz_grows_with_the_airspeed_estimate(tmp_path: Path) -> None:
    rows = _clamp_run(tmp_path)
    early = _at(rows, "sine", "pitch", 4.05)["magnitude"]; late = _at(rows, "sine", "pitch", 9.9)["magnitude"]
    assert late > 1.15 * early        # airspeed 0.41 x factor 0.6 after 5.9 s at tau 4 s; spool and collective equal

def test_dry_run_lakota_conditions_are_constant(tmp_path: Path) -> None:
    scenario = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    log, _ = dry_run(profile("lakota"), load_constants(), scenario, tmp_path)
    rows = _rows(log)
    assert {r["coefficient"] for r in rows if r["kind"] == "damper" and r["axis"] == "pitch"} == {0.25}
    assert {r["coefficient"] for r in rows if r["kind"] == "friction" and r["axis"] == "roll"} == {pytest.approx(0.05)}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_plot.py tests/test_dry_run.py -v`
Expected: FAIL (two rows; scenario file missing)

- [ ] **Step 3: Implement the plot split and rows, write the scenario**

`_gain_row(scale, row, axis, rows)` draws the four coefficient series with the existing `_changes` / `_polyline`; both files stay under 200 lines.

- [ ] **Step 4: Run the suite and the CLI dry run**

Run: `uv run pytest -q && uv run wardogs-flight-eng dry-run --profile src/wardogs_flight_eng/profiles/littlebird-miniguns.json --scenario tests/scenarios/littlebird-clamp-cruise.json --out <scratch dir>`
Expected: green; the HTML shows friction rising at 10 s and the spring falling to 0 (open it once and look).

- [ ] **Step 5: Commit**

```bash
git add src/wardogs_flight_eng/runtime/plot.py src/wardogs_flight_eng/runtime/plot_rows.py tests/scenarios/littlebird-clamp-cruise.json tests/test_plot.py tests/test_dry_run.py
git commit -m "feat: gain rows in the force plot and the Littlebird clamp-cruise scenario"
```

---

### Task 11: README, version 0.2.0 and the final checks

**Files:**
- Modify: `README.md` (Status; "What the forces are" gains a **Feel modes** subsection and the three conditions; "Hardware tuning pass" gains steps 6 **clamp hold** and 7 **release settle** per the spec, renumbering "Commit the tuned profiles" to 8; "First run" step 4 mentions the WARN line; Python API mentions `estimator=`)
- Modify: `pyproject.toml` (`version = "0.2.0"`), `src/wardogs_flight_eng/__init__.py` (`__version__ = "0.2.0"`), `README.md:30` (`Version 0.2.0.`); confirm nothing else with `grep -rn "0\.1\.0" --include=*.py --include=*.toml --include=*.md . | grep -v docs/superpowers`

- [ ] **Step 1: Make the edits**

Copy for the feel-modes subsection, in this order: what `force_trim` does (anchor spring, breakout friction, damper, inertia), what `unboosted` does (weak centring spring, light friction, clamp on `trim_lock`, release on `trim_reset`, stopping band `friction / spring_coefficient`), the estimator block ("today: sustained forward stick; the `kind` field is where a future game-state feed would plug in; nothing reads the game"), the capability rule (missing damper or inertia: runs with a warning; missing friction: unboosted profiles refuse to run), and the migration note ("profiles copied from 0.1.0 must be re-copied; the error says so"). Cite `docs/reference/real-cyclic-feel-references.md` for the shapes.

- [ ] **Step 2: Run everything**

Run: `uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && wc -l src/wardogs_flight_eng/*/*.py | sort -n | tail -5`
Expected: green; no source file at or above 200 lines

- [ ] **Step 3: Commit**

```bash
git add README.md pyproject.toml src/wardogs_flight_eng/__init__.py
git commit -m "docs: feel modes, tuning steps and version 0.2.0"
```

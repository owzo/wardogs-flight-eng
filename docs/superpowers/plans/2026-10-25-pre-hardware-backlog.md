# Pre-hardware Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear every no-hardware item: the deferred-minor wave, the rotor buzz floor and refresh flag, CI workflows, hold-to-release trim, the Moza Cockpit preset emitter and the scenario recorder.

**Architecture:** Seven small, independent tasks on the existing layering: engine changes stay pure (`feel.py`, `rotor.py`, `synth.py`, `profile_sections.py`), new CLI commands get their own `cli_*.py` modules with pure helper modules beside them (`cockpit_preset.py`, `runtime/recorder.py`), CI is two workflow files pinned by a text test.

**Tech Stack:** Python 3.12, pydantic v2, argparse, pytest, ruff, mypy --strict (src and tests), uv, GitHub Actions (`astral-sh/setup-uv`), PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-25-pre-hardware-backlog-design.md`

## Global Constraints

- `engine/` imports nothing from `inputs/`, `outputs/`, `runtime/`, CLI modules or `sdl2` (`tests/test_layering.py`).
- Every new profile field defaults to today's behaviour: `rotor.min_amplitude: Unit = 0.0`, `feel.trim_style: Literal["tap", "hold"] = "tap"`; the four shipped profiles are not edited for these.
- Gates: `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, plain `uv run mypy`; files under 200 lines, functions under 50, `logging` never `print` (CLI text via `ctx.console` / `CliError`), no bare `except`, no TODOs.
- `record` constructs no force backend and never calls `SDL_HapticOpenFromJoystick`.
- `make-preset` never ships or reads a real preset in tests; the fixture is synthetic.
- Division A rewrites exactly: `bacic_spring` 0, `bacic_damper` 0, `bacic_friction` 0, `bacic_inertia` 0, `bacic_start_force_enble` 0, `hardware_balancing_enable` 0, `bacic_gameForceFeedback` 100. Division B rewrites exactly: `bacic_damper` 0, `bacic_friction` 0, `bacic_inertia` 0, `hardware_balancing_enable` 1, `bacic_gameForceFeedback` 100; B requires a `force_trim` profile with `feel.spring_coefficient == 0` and template `hardware_balancing_trim` and `hardware_balancing_recenter` both present and non-zero.
- Hold style: force_trim — while held the spring coefficient slews to 0 at rate `1 / trim_slew_s` and the anchor does not move; on release the anchor is locked at the stick position (`TrimState.lock`) and the spring slews back at the same rate from its current fraction; `TRIM_RESET` tap recentres. unboosted — clamp engaged while held, released when let go, through the existing blend; `TRIM_RESET` is a no-op. A `TRIM_LOCK` held across a handoff is blocked until first released.
- Buzz floor: a computed magnitude strictly below `min_amplitude` is emitted as 0.0; the sine frequency is unchanged.
- The builder never pushes; CI's live proof happens at release time.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. `TRIM_LOCK` held across a profile switch into a `hold` profile must not slacken or clamp the incoming engine. Test in Task 5 (`test_held_trim_lock_across_handoff_is_blocked_until_released`).
2. `record` on a profile whose `device_map` lacks the collective or pedals binding still records the bound devices (no `CompositeInput`). Test in Task 7 (`test_record_works_without_collective_or_pedals_bound`).
3. `make-preset` on a template whose value types are ints must write ints, not floats, for the rewritten keys. Test in Task 6 (`test_rewritten_values_keep_integer_type`).
4. Buzz floor at exactly `min_amplitude` plays (strictly-below rule). Test in Task 3 (`test_buzz_at_the_floor_plays`).
5. `--refresh-every-tick` must not change behaviour when absent. Test in Task 3 (`test_run_without_refresh_flag_updates_only_on_change`).

---

### Task 1: Deferred-minor wave, source side

**Files:**
- Modify: `src/wardogs_flight_eng/engine/profile.py` (hint keyed on the six field names; `MIGRATION_HINT` in `__all__`), `src/wardogs_flight_eng/cli_profiles.py:38` (`Profile.from_document(json.loads(text))`), `src/wardogs_flight_eng/outputs/sdl_capabilities.py` and `outputs/sdl_conditions.py` (direct attribute reads, warnings at construction), `src/wardogs_flight_eng/engine/feel.py` (assert narrowing), `src/wardogs_flight_eng/engine/synth.py` (drop the `all_off` setter and `prime_buttons`; `take_over` assigns `_all_off` and `_previous_held` directly), `src/wardogs_flight_eng/engine/flight_state.py:37` (docstring), `src/wardogs_flight_eng/outputs/clamp.py` (`ClampableCommand` alias), `src/wardogs_flight_eng/cli_run_checks.py:1` (docstring)
- Test: `tests/test_profile.py`, `tests/test_sdl_conditions.py`, `tests/test_condition_backends.py`, `tests/test_synth_handoff.py`, `tests/test_loop_profile_cycle.py`

**Interfaces:**
- Produces: `MIGRATION_HINT_FIELDS: frozenset[str] = {"feel.mode", "feel.friction", "feel.damper", "feel.inertia", "rotor.airspeed_factor", "estimator"}` in `profile.py`; `ClampableCommand = SpringCommand | SineCommand | PulseCommand | TransientCommand | ConditionCommand` in `clamp.py`; `ConditionSupport.__init__` logs the warnings, `allows()` is silent.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile.py
def test_missing_pre_existing_field_gets_no_migration_hint() -> None:
    raw = _raw("lakota"); del raw["rotor"]["base_amplitude"]
    with pytest.raises(ProfileError) as err:
        Profile.from_document(raw)
    assert "predates 0.2.0" not in str(err.value) and "base_amplitude" in str(err.value)

def test_calibrate_rewrite_path_reports_the_migration_hint(tmp_path: Path) -> None:
    old = tmp_path / "old.json"; old.write_bytes((Path("tests/fixtures/littlebird-v0.1.0.json")).read_bytes())
    with pytest.raises(ProfileError, match="predates 0.2.0"):
        write_calibration(old, Calibration())

# tests/test_sdl_conditions.py
def test_every_condition_command_has_an_sdl_type() -> None:
    fake = FakeSdl(stick())
    for kind in get_args(ConditionCommand):
        effect = condition_effect(fake, STANDARD_AXES, kind(Axis.PITCH, 0.1), 1000)
        assert effect.type in {fake.SDL_HAPTIC_FRICTION, fake.SDL_HAPTIC_DAMPER, fake.SDL_HAPTIC_INERTIA}

def test_capability_warnings_fire_at_construction(caplog) -> None:
    fake = FakeSdl(stick(), supported=FakeSdl.SDL_HAPTIC_CONSTANT | FakeSdl.SDL_HAPTIC_SINE | FakeSdl.SDL_HAPTIC_SPRING)
    with caplog.at_level(logging.WARNING):
        backend = open_backend(fake)
    assert sum("friction" in r.message for r in caplog.records) == 1
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        backend.apply(0.0, [FrictionCommand(Axis.PITCH, 0.1)])
    assert not caplog.records

# tests/test_condition_backends.py — parametrise over the three kinds
@pytest.mark.parametrize("kind", [FrictionCommand, DamperCommand, InertiaCommand])
def test_clamp_limits_and_fails_closed_per_condition_kind(kind) -> None: ...

# tests/test_synth_handoff.py
def test_engine_has_no_public_latch_setter_or_prime() -> None:
    assert not hasattr(FlightEngine, "prime_buttons")
    assert FlightEngine.all_off.fset is None
```

Keep every existing `test_profile_cycle_*` and handoff test green; where one used `prime_buttons` or the setter, rewrite it through `take_over` or the loop.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_profile.py tests/test_sdl_conditions.py tests/test_condition_backends.py tests/test_synth_handoff.py -v`
Expected: FAIL on each new test

- [ ] **Step 3: Implement every bullet of spec section 1 that names a `src` file**

- [ ] **Step 4: Run the four gates**

- [ ] **Step 5: Commit**

```bash
git commit -am "refactor: deferred-minor wave, source side (migration hint keys, direct SDL constants, construction-time warnings, narrower guards)"
```

---

### Task 2: Deferred-minor wave, test and docs side

**Files:**
- Modify: `tests/test_cli_devices.py` (WARN text verbatim), `tests/test_cli_run_unboosted.py` (mask-0 test: one open, one close, no `SDL_HapticNewEffect`, `joysticks_released`; probe open failure → exit 2 and released), `tests/test_sdl_conditions.py` (inverted binding: `HapticAxisMap(pitch=HapticAxis(1, -1.0), roll=HapticAxis(0, 1.0))`, coefficient unsigned), `tests/test_plot.py` (empty log has two `gain-row`s; rename `test_plot_has_four_rows`), `tests/test_flight_state.py` (rename the tau-0 test to `test_aft_stick_snaps_to_zero_with_tau_zero`; add `test_pitch_at_threshold_targets_zero`; `InputEstimator(0.1, float("nan"))` raises), `tests/test_rotor.py` (`take_over(-0.5, True)` → rpm 0), `tests/test_profile_feel.py` (friction exactly `spring / 4` accepted; littlebird-rockets and lakota value tests), `tests/test_dry_run.py` (axis predicate on the friction filter), `README.md:284-287`
- Modify: `src/wardogs_flight_eng/engine/flight_state.py` only if the NaN `tau_s` check needs `not tau_s >= 0`

- [ ] **Step 1: Write the tests listed above** (each named in the spec's section 1); run them; fix the one source line if the NaN test fails.

- [ ] **Step 2: Edit README.md 284-287** so division A says Cockpit's damper, friction and inertia are set low or 0 and division B says Flight Eng supplies damper, inertia, buzz and recoil.

- [ ] **Step 3: Run the four gates**

- [ ] **Step 4: Commit**

```bash
git commit -am "test: deferred-minor wave, test and docs side"
```

---

### Task 3: Rotor buzz floor and the refresh flag

**Files:**
- Modify: `src/wardogs_flight_eng/engine/profile_sections.py` (`Rotor.min_amplitude: Unit = 0.0`), `src/wardogs_flight_eng/engine/rotor.py` (`RotorModel(..., min_amplitude: float = 0.0)`, validated `0..1`), `src/wardogs_flight_eng/engine/builders.py` (pass it), `src/wardogs_flight_eng/cli.py` (`run --refresh-every-tick`, `action="store_true"`), `src/wardogs_flight_eng/cli_run.py` (`refresh_every_tick=args.refresh_every_tick`), `README.md` (tuning step 3 names the flag; profile field table gains `min_amplitude`)
- Test: `tests/test_rotor.py`, `tests/test_profile.py`, `tests/test_cli_run.py`

**Interfaces:**
- Produces: `RotorModel.amplitude` returns `0.0` when the clamped value is `< min_amplitude`.

- [ ] **Step 1: Write the failing tests**

```python
def test_buzz_below_the_floor_is_silenced() -> None:
    r = RotorModel(300, 0, 850, 0.4, 0.0, min_amplitude=0.1); r.step(0.01)
    assert r.amplitude(0.2, 0.0) == 0.0          # 0.08 < 0.1

def test_buzz_at_the_floor_plays() -> None:        # Review Focus 4
    r = RotorModel(300, 0, 850, 0.4, 0.0, min_amplitude=0.1); r.step(0.01)
    assert r.amplitude(0.25, 0.0) == pytest.approx(0.1)

def test_min_amplitude_defaults_to_zero_in_shipped_profiles() -> None:
    assert load_profile(PROFILES / "havoc.json").rotor.min_amplitude == 0.0

# tests/test_cli_run.py
def test_run_with_refresh_flag_updates_every_tick(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=20, then=detach_all)
    invoke(["run", "--profile", str(profile), "--refresh-every-tick"], api=fake)
    assert fake.count("SDL_HapticUpdateEffect") >= 40     # >= 4 persistent effects x >= 10 ticks

def test_run_without_refresh_flag_updates_only_on_change(profile: Path) -> None:   # Review Focus 5
    fake = TickingSdl(stick(), pedals(), after=20, then=detach_all)
    invoke(["run", "--profile", str(profile)], api=fake)
    assert fake.count("SDL_HapticUpdateEffect") < 10
```

- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: rotor buzz floor and run --refresh-every-tick`

---

### Task 4: CI workflows

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/build-exe.yml`
- Modify: `README.md` (Status badge line `![CI](https://github.com/owzo/wardogs-flight-eng/actions/workflows/ci.yml/badge.svg)`; a "Releasing" paragraph: tag `vX.Y.Z`, download the `wardogs-flight-eng-vX.Y.Z` artifact, attach the exe and `SHA256SUMS` to the GitHub release)
- Test: `tests/test_workflows.py`

**Interfaces:**
- Produces: `ci.yml`: `on: push: branches: [main]` and `pull_request`, matrix `os: [ubuntu-latest, windows-latest]`, `actions/checkout@v4`, `astral-sh/setup-uv@v5` with `python-version: "3.12"`, steps `uv sync --all-groups`, the four gate commands verbatim. `build-exe.yml`: `on: push: tags: ["v*"]`, `windows-latest`, `uv sync --all-groups`, `uv run pyinstaller packaging/wardogs-flight-eng.spec`, `certutil -hashfile dist\wardogs-flight-eng.exe SHA256 > dist\SHA256SUMS` (or PowerShell `Get-FileHash`), `actions/upload-artifact@v4` with `name: wardogs-flight-eng-${{ github.ref_name }}` and `path: dist/wardogs-flight-eng.exe` plus `dist/SHA256SUMS`.

- [ ] **Step 1: Write the failing test**

```python
WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
GATES = ["uv run pytest -q", "uv run ruff check src tests", "uv run ruff format --check src tests", "uv run mypy"]

def test_ci_workflow_runs_the_four_gates_on_both_platforms() -> None:
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert all(gate in text for gate in GATES)
    assert "ubuntu-latest" in text and "windows-latest" in text and 'python-version: "3.12"' in text
    assert "pull_request" in text

def test_tag_workflow_builds_and_uploads_the_exe() -> None:
    text = (WORKFLOWS / "build-exe.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text or "tags:\n      - \"v*\"" in text
    assert "pyinstaller packaging/wardogs-flight-eng.spec" in text
    assert "dist/wardogs-flight-eng.exe" in text and "SHA256SUMS" in text and "upload-artifact" in text
```

- [ ] **Step 2: Run to verify it fails** — [ ] **Step 3: Write the two workflows and the README lines** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `ci: gates on push and pull request, exe artifact on tags`

---

### Task 5: Hold-to-release trim

**Files:**
- Modify: `src/wardogs_flight_eng/engine/profile_sections.py` (`Feel.trim_style: TrimStyle = "tap"`, `TrimStyle = Literal["tap", "hold"]`), `src/wardogs_flight_eng/engine/feel.py` (`hold()`, a `_slack: _Blend`, `_held: bool`; spring coefficient `* (1 - slack)` in force_trim), `src/wardogs_flight_eng/engine/synth.py` (`_trim_lock_blocked`, dispatch by style), `README.md` ("Feel modes": a "Trim styles" paragraph)
- Test: `tests/test_feel_hold.py` (new), `tests/test_synth_handoff.py`, `tests/test_profile_feel.py`

**Interfaces:**
- Produces: `FeelModel.hold(self, pressed: bool, pitch: float, roll: float) -> None`; property `slack -> float` (0..1, force_trim only); `FlightEngine.step` calls `hold()` every dispatched tick when `feel.trim_style == "hold"` with `pressed = Button.TRIM_LOCK in frame.held and not self._trim_lock_blocked`, and never calls `lock()` in that style; `take_over` sets `_trim_lock_blocked = Button.TRIM_LOCK in outgoing._previous_held`; the flag clears on the first dispatched tick with `TRIM_LOCK` not held.

- [ ] **Step 1: Write the failing tests**

```python
HOLD_FT = LAK.model_copy(update={"trim_style": "hold"})       # lakota feel, slew 0.3, spring 0.5
HOLD_UB = LB.model_copy(update={"trim_style": "hold"})        # littlebird feel

def test_force_trim_hold_slackens_the_spring_without_moving_the_anchor() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.4, 0.0); f.step(0.15)
    assert by_kind(f.conditions(), SpringCommand, Axis.PITCH) == pytest.approx(0.25)
    assert f.center_pitch == 0.0
    f.step(0.15)
    assert by_kind(f.conditions(), SpringCommand, Axis.PITCH) == 0.0

def test_force_trim_release_anchors_at_the_stick_and_restiffens() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0); f.step(0.3)
    f.hold(False, 0.4, -0.2); f.step(0.3)
    springs = [c for c in f.conditions() if isinstance(c, SpringCommand)]
    assert [s.center for s in springs] == pytest.approx([0.4, -0.2])
    assert [s.coefficient for s in springs] == [0.5, 0.25]

def test_release_mid_slew_continues_from_the_current_fraction() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0); f.step(0.15)         # slack 0.5
    f.hold(False, 0.0, 0.0); f.step(0.075)       # back to 0.25
    assert f.slack == pytest.approx(0.25)

def test_unboosted_hold_is_a_momentary_clamp_and_reset_is_a_no_op() -> None:
    f = FeelModel(HOLD_UB)
    f.hold(True, 0.0, 0.0); f.step(0.3)
    assert f.clamp_blend == 1.0
    f.reset(); f.step(0.01)
    assert f.clamp_blend == 1.0
    f.hold(False, 0.0, 0.0); f.step(0.3)
    assert f.clamp_blend == 0.0

def test_restart_clears_a_held_slack() -> None:
    f = FeelModel(HOLD_FT); f.hold(True, 0.0, 0.0); f.step(0.3); f.restart()
    assert f.slack == 0.0 and by_kind(f.conditions(), SpringCommand, Axis.PITCH) == 0.5

# tests/test_synth_handoff.py
def test_held_trim_lock_across_handoff_is_blocked_until_released() -> None:   # Review Focus 1
    hold_lak = FlightEngine(load_profile(PROFILES / "lakota.json").model_copy(update={"feel": HOLD_FT}), load_constants())
    lb = engine_for("littlebird-miniguns")
    lb.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    hold_lak.take_over(lb)
    for _ in range(40):
        cmds = hold_lak.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    assert pitch_spring(cmds).coefficient == 0.5            # still stiff: blocked
    hold_lak.step(0.01, frame())                             # released once
    for _ in range(40):
        cmds = hold_lak.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    assert pitch_spring(cmds).coefficient == 0.0            # now it slackens

# tests/test_profile_feel.py
def test_trim_style_defaults_to_tap_and_rejects_others() -> None: ...
```

(`Profile.model_copy(update={"feel": ...})` keeps validation; use `Profile.from_document` on a modified `_raw` dict if `model_copy` bypasses the ceiling check you need.)

- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** (`feel.py` may need a split: move `_Blend` to `engine/blend.py` if `feel.py` passes 200 lines) — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: hold-to-release trim style in both feel modes`

---

### Task 6: Moza Cockpit preset emitter

**Files:**
- Create: `src/wardogs_flight_eng/cockpit_preset.py` (pure: `Division = Literal["A", "B"]`, `Change(key: str, old: object, new: object)`, `REQUIRED_KEYS`, `rewrite_preset(document: dict[str, Any], division: Division, profile: Profile, *, name: str | None, now: int, new_uuid: str) -> tuple[dict[str, Any], list[Change]]`, raising `PresetError(ValueError)` with the spec's messages), `src/wardogs_flight_eng/cli_preset.py` (`make_preset_command(args, ctx)`: reads the template with `json.loads` preserving order, calls `rewrite_preset` with `int(time.time())` and `f"{{{uuid.uuid4()}}}"`, writes `json.dumps(doc, indent=4, ensure_ascii=False) + "\n"`, prints the change table and the path), `tests/fixtures/cockpit-template.preset` (synthetic: `version "1.0.4"`, `name "Synthetic"`, `uuid`, `date "1700000000"`, `device_params` with the seven A keys, `hardware_balancing_trim` 3, `hardware_balancing_recenter` 17, `bacic_overall_strength` 70 and two unrelated keys, `telemetry_params {}`), `tests/fixtures/cockpit-template-unbound.preset` (same with trim and recenter 0)
- Modify: `src/wardogs_flight_eng/cli.py` (`make-preset` parser: `--profile`, `--template`, `--division {A,B}`, `--out`, `--name`; `PresetError` in `_CONFIG_ERRORS`), `README.md` ("Moza Cockpit companion settings": the command and what each division writes)
- Test: `tests/test_cockpit_preset.py`, `tests/test_cli_preset.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_division_a_rewrites_exactly_the_seven_keys_and_keeps_order(template, lakota) -> None:
    doc, changes = rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")
    assert {c.key: c.new for c in changes if c.key.startswith(("bacic", "hardware"))} == {
        "bacic_spring": 0, "bacic_damper": 0, "bacic_friction": 0, "bacic_inertia": 0,
        "bacic_start_force_enble": 0, "hardware_balancing_enable": 0, "bacic_gameForceFeedback": 100}
    assert list(doc["device_params"]) == list(template["device_params"])
    assert doc["device_params"]["bacic_overall_strength"] == 70 and doc["name"] == "Synthetic + Flight Eng A"
    assert doc["uuid"] == "{u}" and doc["date"] == "1"

def test_rewritten_values_keep_integer_type(template, lakota) -> None:   # Review Focus 3
    doc, _ = rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")
    assert all(type(doc["device_params"][k]) is int for k in ("bacic_spring", "bacic_gameForceFeedback"))

def test_division_b_requires_force_trim_with_zero_spring(template, lakota, littlebird) -> None:
    with pytest.raises(PresetError, match="spring_coefficient"): rewrite_preset(template, "B", lakota, ...)
    with pytest.raises(PresetError, match="force_trim"): rewrite_preset(template, "B", littlebird, ...)
    zero = lakota_with_spring_zero  # from_document on a modified raw dict (friction 0 too)
    doc, changes = rewrite_preset(template, "B", zero, ...)
    assert doc["device_params"]["bacic_spring"] == template["device_params"]["bacic_spring"]
    assert doc["device_params"]["hardware_balancing_enable"] == 1

def test_division_b_refuses_unbound_trim_buttons(template_unbound, zero) -> None:
    with pytest.raises(PresetError, match="hardware_balancing_trim.*hardware_balancing_recenter"): ...

def test_missing_required_key_names_it(template, lakota) -> None:
    del template["device_params"]["bacic_damper"]
    with pytest.raises(PresetError, match="bacic_damper"): ...

# tests/test_cli_preset.py
def test_make_preset_writes_the_file_and_prints_the_table(tmp_path) -> None:
    out = tmp_path / "new.preset"
    result = invoke(["make-preset", "--profile", str(PROFILES / "lakota.json"), "--template", str(FIXTURE), "--division", "A", "--out", str(out)])
    assert result.code == 0 and out.exists() and "bacic_spring" in result.output and str(out) in result.output
    assert json.loads(out.read_text(encoding="utf-8"))["device_params"]["bacic_spring"] == 0
    assert out.read_text(encoding="utf-8").endswith("}\n")

def test_make_preset_with_a_non_json_template_exits_1(tmp_path) -> None: ...
```

- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: make-preset writes a Moza Cockpit preset for division A or B`

---

### Task 7: Scenario recorder

**Files:**
- Create: `src/wardogs_flight_eng/runtime/recorder.py` (`ScenarioRecorder(rate_hz: float, min_change: float)` with `begin(t: float, snapshot: Mapping[str, DeviceSnapshot]) -> None`, `observe(t: float, snapshot) -> None`, `finish(t: float, device_map: DeviceMap) -> dict[str, Any]`; `DeviceSnapshot(axes: tuple[float, ...], buttons: tuple[bool, ...])`; `step_count` property), `src/wardogs_flight_eng/cli_record.py` (`record_command(args, ctx)`: `load_checked_profile`, `open_devices(device_map, ctx.api)`, warn if `calibration == Calibration()`, loop at `--rate` with `time.perf_counter`/`time.sleep` under `ctrl_c_requests_stop()`, stop on `--duration`, on `DeviceLostError`/`SdlError` write the partial file and raise so exit is 2, always `close_devices`; prints ticks, seconds, steps)
- Modify: `src/wardogs_flight_eng/cli.py` (`record` parser: `--profile`, `--out`, `--rate` default 100.0, `--duration` float optional, `--min-change` default 0.005), `README.md` ("Try it without hardware": recording a real flight and replaying it)
- Test: `tests/test_recorder.py`, `tests/test_cli_record.py`

**Interfaces:**
- Produces: the written document has `rate_hz`, `device_map` (profile's, verbatim via `model_dump(mode="json")`), `devices` (`{alias: {"axes": n, "buttons": m}}`), `steps` (first `t 0.0` with every `alias.axisN` and `alias.buttonN`, then change-only steps, last `{"t": end, "set": {}}`); `Scenario.load` reads it.

- [ ] **Step 1: Write the failing tests**

```python
def test_recorder_writes_initial_changes_and_closing_steps() -> None:
    r = ScenarioRecorder(100.0, 0.005)
    r.begin(0.0, {"stick": DeviceSnapshot((0.0, 0.1), (False,))})
    r.observe(0.01, {"stick": DeviceSnapshot((0.0, 0.1), (False,))})      # no change
    r.observe(0.02, {"stick": DeviceSnapshot((0.003, 0.1), (False,))})    # below min_change
    r.observe(0.03, {"stick": DeviceSnapshot((0.2, 0.1), (True,))})       # two changes, one step
    doc = r.finish(0.05, DEVICE_MAP)
    assert doc["steps"] == [
        {"t": 0.0, "set": {"stick.axis0": 0.0, "stick.axis1": 0.1, "stick.button0": False}},
        {"t": 0.03, "set": {"stick.axis0": 0.2, "stick.button0": True}},
        {"t": 0.05, "set": {}},
    ]
    assert doc["devices"] == {"stick": {"axes": 2, "buttons": 1}} and doc["rate_hz"] == 100.0

def test_recorded_document_round_trips_through_scenario_load(tmp_path) -> None: ...

# tests/test_cli_record.py
def test_record_never_opens_haptics_and_writes_a_loadable_scenario(profile, tmp_path) -> None:
    fake = TickingSdl(stick(), pedals(), after=30, then=detach_all)
    out = tmp_path / "flight.json"
    result = invoke(["record", "--profile", str(profile), "--out", str(out), "--duration", "0.1", "--rate", "100"], api=fake)
    assert fake.count("SDL_HapticOpenFromJoystick") == 0 and fake.count("SDL_HapticNewEffect") == 0
    assert out.exists() and Scenario.load(out).rate_hz == 100.0 and joysticks_released(fake)

def test_record_writes_a_partial_file_and_exits_2_on_device_loss(profile, tmp_path) -> None:
    fake = TickingSdl(stick(), pedals(), after=5, then=detach_all)
    result = invoke(["record", "--profile", str(profile), "--out", str(tmp_path / "f.json")], api=fake)
    assert result.code == 2 and (tmp_path / "f.json").exists()

def test_record_works_without_collective_or_pedals_bound(tmp_path) -> None:   # Review Focus 2
    doc = bound_document(); del doc["device_map"]["axes"]["pedals"]; del doc["device_map"]["axes"]["collective"]
    ... invoke record with --duration 0.05 → code 0 and the file loads
```

- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: record captures the real controls into a replayable scenario`

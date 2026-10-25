# dinput8 Fallback Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second force backend that drives (and reads) the base through DirectInput 8 behind the existing `ForceBackend` and `InputDevice` protocols, selectable with `--backend dinput8`, verified against a fake DirectInput exactly as the SDL path is verified against a fake SDL.

**Architecture:** A `DirectInputApi` seam with dataclass mirrors (`inputs/dinput_api.py`), a ctypes COM adapter split into `dinput_real.py` and `dinput_structs.py`, a `DInputJoystick` input device and SDL-GUID matcher, pure effect builders, a channel with error classification, held-effect logic with in-place updates, the backend, a probe, and a `backend_choice` module that is the one place the CLI interprets `--backend`. The verified SDL modules are not refactored.

**Tech Stack:** Python 3.12, ctypes (Windows, `dinput8.dll`, `user32.dll`), pytest, ruff, mypy --strict, uv.

**Spec:** `docs/superpowers/specs/2026-10-25-dinput8-backend-design.md` (read its "Builder-check rulings" first)

## Global Constraints

- `engine/` untouched. `outputs/dinput_*` import only `engine.commands`, `inputs.dinput_api`, `inputs.protocol`, `outputs.haptic_axes` (and each other). `ctypes` is imported only by `inputs/dinput_real.py`, `inputs/dinput_structs.py` and `inputs/sdl_real.py`; the layering test asserts it.
- DirectInput units: magnitudes, coefficients and offsets on ±10000 (`DI_FFNOMINALMAX`), saturation and deadband 0..10000, durations and periods in microseconds, phase 0..35999, gain 10000. Non-finite inputs scale to 0 (same rule as `sdl_effects.scale`).
- Effect lifetimes: created with the finite length `persistent_length_s` (same CLI value as SDL); `Start(1, 0)` on creation, after `all_off`, and at the half-life re-run; a change is applied with `SetParameters(DIEP_TYPESPECIFICPARAMS | DIEP_DIRECTION | DIEP_NORESTART)` and no `Start`; `DIERR_EFFECTPLAYING` is retried once without `DIEP_NORESTART`, latched per effect kind, logged once at INFO; every other failing HRESULT raises `DInputError`, and `DIERR_INPUTLOST`, `DIERR_NOTACQUIRED`, `DIERR_UNPLUGGED` raise `DeviceLostError`.
- Open sequence: `DirectInput8Create` → `CreateDevice(guidInstance)` → `SetDataFormat(joystick2)` → `SetCooperativeLevel(hidden hwnd, DISCL_EXCLUSIVE | DISCL_BACKGROUND)` → `SetProperty(DIPROP_AUTOCENTER, off)` → `SetProperty(DIPROP_FFGAIN, 10000)` → `Acquire` → `SendForceFeedbackCommand(DISFFC_RESET)` → `SendForceFeedbackCommand(DISFFC_SETACTUATORSON)`; `all_off` = `DISFFC_STOPALL` then zero every held effect; `close` = `all_off`, release effects, `Unacquire`, release device, release DirectInput, destroy window; idempotent.
- Device matching: SDL GUID hex chars 8–11 are the vendor id little-endian, 16–19 the product id; the DirectInput candidate has `guidProduct.Data1 == (pid << 16) | vid`; prefer a force-feedback instance; two force-feedback candidates is a configuration error naming both instance names; none is a device error.
- Axes: haptic index n = the n-th axis object in `dwOfs` order; pitch and roll must carry `DIDOI_FFACTUATOR`.
- `--backend {sdl,dinput8}` on `run`, `check-device`, `list-devices`; default `sdl`; `--refresh-every-tick` with `dinput8` is a usage error; on a non-Windows platform `dinput8` is a configuration error naming the platform.
- Capability: `missing` frozenset over `{"friction", "damper", "inertia"}` from `EnumEffects`, same warning texts as `ConditionSupport`, warnings at construction; `refuse_unboosted_without_friction` reused.
- Gates and file rules as in every plan; commit trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. The version bump to 0.3.0 is Task 8.

## Review Focus

1. A `SetParameters` that fails with any HRESULT other than `DIERR_EFFECTPLAYING` must raise, never be retried. Test in Task 4 (`test_other_set_parameters_failures_raise`).
2. `apply` after `close` must make no DirectInput call. Test in Task 5 (`test_apply_after_close_is_ignored`).
3. A device that detaches between `Acquire` and the first `apply`: the input poll raises `DeviceLostError` and the loop tears down with `all_off` and `close` still attempted. Test in Task 5 (`test_loss_on_first_poll_still_tears_down`).
4. `check-device --backend dinput8` on a device whose spring update fails must report `spring_center_moves` false and exit 1, releasing everything. Test in Task 6 (`test_dinput_probe_reports_a_failed_centre_update`).
5. `run --backend dinput8` must never call `SDL_HapticOpenFromJoystick`, and must still open the pedals through SDL. Test in Task 6 (`test_run_dinput8_opens_the_base_through_directinput_only`).

---

### Task 1: The DirectInput seam and its fake

**Files:**
- Create: `src/wardogs_flight_eng/inputs/dinput_api.py`, `tests/dinput_support.py`
- Test: `tests/test_dinput_api.py`

**Interfaces:**
- Produces (all frozen slots dataclasses unless noted): `DiGuid = str` (the `{xxxxxxxx-xxxx-...}` text form); `DiDeviceInfo(instance_guid: DiGuid, product_guid: DiGuid, vid: int, pid: int, instance_name: str, product_name: str, force_feedback: bool)`; `DiAxisInfo(offset: int, name: str, ff_actuator: bool)`; `DiCondition(offset: int, positive_coefficient: int, negative_coefficient: int, positive_saturation: int, negative_saturation: int, dead_band: int)`; `DiPeriodic(magnitude: int, offset: int, phase: int, period_us: int)`; `DiConstant(magnitude: int)`; `DiEnvelope(attack_level: int, attack_time_us: int, fade_level: int, fade_time_us: int)`; `DiEffect(kind: EffectKind, axes: tuple[int, ...], direction: tuple[int, ...], duration_us: int, gain: int, condition: tuple[DiCondition, ...] = (), periodic: DiPeriodic | None = None, constant: DiConstant | None = None, envelope: DiEnvelope | None = None)` with `EffectKind = Literal["spring", "damper", "inertia", "friction", "sine", "constant"]`; `DiState(axes: tuple[int, ...], buttons: tuple[bool, ...])` (axes raw 0..65535 after the data format's range property, see Task 3); `DInputError(RuntimeError)`; error-code constants `DIERR_INPUTLOST`, `DIERR_NOTACQUIRED`, `DIERR_UNPLUGGED`, `DIERR_EFFECTPLAYING`, `DI_EFFECTRESTARTED`, `DI_OK` (as ints from the headers).
- `DirectInputApi` Protocol: `enumerate_devices() -> list[DiDeviceInfo]`; `open_device(instance_guid) -> DiDeviceHandle` (an opaque object); `axes(dev) -> list[DiAxisInfo]`; `set_cooperative_exclusive_background(dev) -> int`; `set_autocenter_off(dev) -> int`; `set_ff_gain(dev, gain: int) -> int`; `get_ff_gain(dev) -> int`; `acquire(dev) -> int`; `unacquire(dev) -> int`; `ff_command(dev, command: int) -> int`; `enum_effect_kinds(dev) -> frozenset[EffectKind]`; `poll_state(dev) -> tuple[int, DiState]` (status, state); `create_effect(dev, effect: DiEffect) -> tuple[int, object]`; `set_parameters(effect_handle, effect: DiEffect, norestart: bool) -> int`; `start(effect_handle) -> int`; `stop(effect_handle) -> int`; `release_effect(effect_handle) -> None`; `release_device(dev) -> None`; `close() -> None`. Status ints are HRESULTs: `< 0` failure. Constants `DISFFC_RESET`, `DISFFC_STOPALL`, `DISFFC_SETACTUATORSON` as attributes.
- `FakeDirectInput(*devices: FakeDiDevice)` in `tests/dinput_support.py`: records `calls: list[tuple[str, tuple]]`, in-memory effects `{id: DiEffect}` with `playing` flags, `fail: dict[str, int]` (method name → HRESULT to return), `norestart_unsupported: bool` (then `set_parameters(norestart=True)` on a playing effect returns `DIERR_EFFECTPLAYING`), `attached` per device (detached → lost-device codes from `poll_state`, `start`, `set_parameters`, `ff_command`), `FakeDiDevice(vid, pid, instance_name, product_name, force_feedback, axes: list[DiAxisInfo], kinds: frozenset[EffectKind], state: DiState)`; helper `ab9()` returning a device with vid 0x346E, pid 0x0010 (placeholder ids for tests only, named as such), axes X/Y/Z/Rz with FF on X and Y, all six kinds.

- [ ] **Step 1: Write the failing tests** (`tests/test_dinput_api.py`): the fake satisfies `DirectInputApi` under mypy (a typed assignment), `enumerate_devices` lists `ab9()`, a detached device makes `poll_state` return `DIERR_INPUTLOST`, `fail["acquire"]` makes `acquire` return that code, `norestart_unsupported` makes a playing effect's norestart update return `DIERR_EFFECTPLAYING` while a non-norestart update succeeds.
- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement seam and fake** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: DirectInput seam and its test fake`

---

### Task 2: Effect builders

**Files:**
- Create: `src/wardogs_flight_eng/outputs/dinput_effects.py`
- Test: `tests/test_dinput_effects.py`

**Interfaces:**
- Produces: `di_scale(value: float) -> int` (−1..1 → ±10000, clamped, non-finite → 0); `microseconds(seconds: float) -> int`; `period_us(frequency_hz: float) -> int | None` (`None` for non-positive); `di_phase(phase_turn: int) -> int` (the SDL hundredths-of-a-degree phase is the same unit; identity with wrap); `offset_for(axis: HapticAxis) -> int` (haptic index → `DIJOFS_X` 0, `DIJOFS_Y` 4, `DIJOFS_Z` 8 ... from `dinput_api` constants `DIJOFS_BY_INDEX`); `spring_effect(axes, command: SpringCommand, length_us) -> DiEffect` (`DiCondition(offset_for, coeff, coeff, 10000, 10000, dead_band)`, condition offset = `di_scale(center * sign)`), `condition_effect(axes, command: ConditionCommand, length_us) -> DiEffect`, `sine_effect(axes, axis, *, period_us, magnitude, length_us, phase, fade_us=0) -> DiEffect` (envelope with `fade_time_us` when `fade_us > 0`), `pulse_effect(axes, command: PulseCommand) -> DiEffect` (`DiConstant(di_scale(magnitude * sign))`, direction `(1,)` on the axis), `silenced(effect: DiEffect) -> DiEffect`.

- [ ] **Step 1: Write the failing tests** — pin: `di_scale(0.35) == 3500`, `di_scale(float("nan")) == 0`, `microseconds(1.0) == 1_000_000`, `period_us(5.5067) == 181_597`, spring on pitch with inverted sign has offset `-2500` for centre 0.25, condition coefficients both `1000` for 0.1, saturation `10000`, sine magnitude `4000` for 0.4, pulse level `-6000` for magnitude −0.6 on a non-inverted axis, `silenced` zeroes coefficients, magnitude and level.
- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: DirectInput effect builders`

---

### Task 3: Device matching and the DirectInput input device

**Files:**
- Create: `src/wardogs_flight_eng/inputs/dinput_device.py`
- Test: `tests/test_dinput_device.py`

**Interfaces:**
- Produces: `vid_pid_from_sdl_guid(guid: str) -> tuple[int, int]` (raises `InputConfigError` on a malformed GUID); `match_sdl_guid(sdl_guid: str, infos: Sequence[DiDeviceInfo]) -> DiDeviceInfo` (rules in Global Constraints; errors: `InputConfigError` for ambiguity, `DeviceLostError` for none attached); `open_dinput_joystick(api: DirectInputApi, sdl_guid: str) -> DInputJoystick` (performs the open sequence through `Acquire`, `DISFFC_RESET`, `DISFFC_SETACTUATORSON`); `DInputJoystick(InputDevice)` with `name` (instance name), `guid` (the SDL GUID string given), `axis_count`, `button_count`, `alive`, `poll()` (`poll_state`; lost-device codes → `alive=False` and `DeviceLostError`; other failures `DInputError`), `axis(i)` (raw 0..65535 → −1..1), `button(i)`, `axes_info: list[DiAxisInfo]`, `handle`, `api`, `close()` (`unacquire`, `release_device`); `ff_actuator_check(joystick, axis_map: HapticAxisMap) -> None` raising `InputConfigError` naming a non-actuator pitch or roll axis.

- [ ] **Step 1: Write the failing tests** — `vid_pid_from_sdl_guid("0300ab9c6e34000010000000...")`-style string built from `ab9()`'s ids; matching prefers the FF instance; two FF instances → `InputConfigError` naming both; none → `DeviceLostError`; `open_dinput_joystick` call order is exactly `open_device, set_cooperative_exclusive_background, set_autocenter_off, set_ff_gain(10000), acquire, ff_command(DISFFC_RESET), ff_command(DISFFC_SETACTUATORSON)`; `axis(0)` maps 65535 → 1.0 and 0 → −1.0; a detached device makes `poll()` raise `DeviceLostError` and set `alive` False; `ff_actuator_check` rejects roll on axis 2 (Z, no actuator in `ab9()`).
- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: DirectInput device matching from the SDL GUID and the input device`

---

### Task 4: Channel, held effects and capability

**Files:**
- Create: `src/wardogs_flight_eng/outputs/dinput_channel.py` (`DInputChannel(api, handle)` with status-checked `create(effect) -> int`, `update(effect_id, effect, *, norestart: bool) -> int` (returns the status so the caller can see `DI_EFFECTRESTARTED`), `start`, `stop`, `release`, `stop_all()` (`DISFFC_STOPALL`), `_classify(status, call)`; `DInputPool` = the four-slot pool pattern over this channel), `src/wardogs_flight_eng/outputs/dinput_persistent.py` (`HeldEffects(channel, length_s)` with `due(t, key, steady) -> bool` (same rule as `PersistentEffects.due`), `play(t, key, effect)` (new → create+start; changed → `update(norestart=True)`; on `DIERR_EFFECTPLAYING` → `update(norestart=False)` and set `restart_latched[kind] = True`, log INFO once; re-run → `start`), `silence(failures)`, `effect_ids`, `restarted(key) -> bool` for the sine phase carry), `src/wardogs_flight_eng/outputs/dinput_capabilities.py` (`DInputConditionSupport(kinds: frozenset[EffectKind])` with `missing`, `allows(command)`, warnings at construction with the same three texts as `ConditionSupport`)
- Test: `tests/test_dinput_persistent.py`, `tests/test_dinput_capabilities.py`

- [ ] **Step 1: Write the failing tests** — `play` of a new key calls `create` then `start`; the same effect again within half the length makes no call; a changed effect calls `set_parameters(norestart=True)` and no `start`; with `norestart_unsupported` the first change calls `set_parameters` twice (norestart then not) and later changes once (not norestart) — the latch; `test_other_set_parameters_failures_raise` (Review Focus 1: `fail["set_parameters"] = -2147024809` (`E_INVALIDARG`) → `DInputError`); after `t > length / 2` a `start` happens; `silence` updates every held effect to its silenced form; `DInputConditionSupport(frozenset({"spring", "sine", "constant"}))` → `missing == {"friction", "damper", "inertia"}` and three WARNING lines at construction, none on `allows`.
- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: DirectInput channel, held effects with in-place updates, capability support`

---

### Task 5: The backend

**Files:**
- Create: `src/wardogs_flight_eng/outputs/dinput_haptic.py` (`DInputHapticBackend(joystick: DInputJoystick, persistent_length_s: float, *, axis_map: HapticAxisMap)`, `ForceBackend`; `missing_conditions`; `apply` (closed → warning and return; dispatch per command kind exactly as `SdlHapticBackend._dispatch`, sines through a `HeldSines` helper mirroring `PersistentSines` with phase carry applied only when `restarted(key)`), `all_off` (`stop_all`, `silence`, raise the first failure after attempting all), `close` (idempotent: `all_off`, release every effect, `joystick.close()`, `api.close()`))
- Test: `tests/test_dinput_haptic.py`, `tests/test_dinput_teardown.py`

- [ ] **Step 1: Write the failing tests** — mirror `tests/test_sdl_haptic.py`, `test_sdl_persistent.py` and `test_sdl_teardown.py` case by case against `FakeDirectInput` (spring shape on its axis, sine period and magnitude, zero frequency silences, pulses pooled four deep, transient envelope, conditions persistent and gated, `all_off` zeroes and stops, close order `[stop_all, release_effect..., unacquire, release_device, close]`, `test_apply_after_close_is_ignored` (Review Focus 2: no call recorded), `test_loss_on_first_poll_still_tears_down` (Review Focus 3: run the real `run_loop` with a `CompositeInput` over a detached `DInputJoystick` and the backend; result `device_lost`; the fake recorded `stop_all` and `release_device`)).
- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** (split `HeldSines` into `dinput_sines.py` if the backend passes 200 lines) — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: DInputHapticBackend`

---

### Task 6: Probe, backend choice and the CLI

**Files:**
- Create: `src/wardogs_flight_eng/outputs/dinput_probe.py` (`probe_dinput(api, sdl_guid) -> tuple[PrimitiveReport, DInputProbeDetail]` with `DInputProbeDetail(instance_name, acquired: bool, ff_gain: int, axes: list[DiAxisInfo])`; creates each kind with zero coefficients, never starts, tests the spring-centre update with `set_parameters(norestart=False)` on the unstarted spring, releases everything), `src/wardogs_flight_eng/outputs/backend_choice.py` (`BackendKind = Literal["sdl", "dinput8"]`; `platform_supports(kind) -> bool`; `build_force_backend(kind, *, sdl_device, dinput_joystick, axis_map, persistent_length_s, refresh_every_tick) -> ForceBackend`)
- Modify: `src/wardogs_flight_eng/cli.py` (`--backend` on `run`, `check-device`, `list-devices`; usage error for `--refresh-every-tick` with `dinput8`), `src/wardogs_flight_eng/cli_devices.py` (`open_devices(..., dinput_base: str | None = None, dinput_api=None)` opens that alias with `open_dinput_joystick`; `list-devices --backend dinput8` table: instance, product, vid:pid, force feedback, axes with offset name and actuator flag and live values with `--live`; `check-device --backend dinput8` prints the detail then the primitive table with the same PASS/WARN/FAIL rule), `src/wardogs_flight_eng/cli_run.py` (`_force_backend` builds through `build_force_backend`; the `SDL_JoystickIsHaptic` check applies only to the SDL kind; non-Windows refusal before any device opens), `src/wardogs_flight_eng/cli_console.py` (`CliContext` gains `dinput_api: DirectInputApi | None`), `tests/cli_support.py` (`invoke(..., dinput_api=...)`)
- Test: `tests/test_cli_dinput.py`

- [ ] **Step 1: Write the failing tests** — `test_run_dinput8_opens_the_base_through_directinput_only` (Review Focus 5: `SDL_HapticOpenFromJoystick` count 0, `SDL_JoystickOpen` called for the pedals, the fake DirectInput saw `acquire` and `create_effect`), `run --backend dinput8 --refresh-every-tick` → exit 1 with "refresh-every-tick" in the output, `test_dinput_probe_reports_a_failed_centre_update` (Review Focus 4: `fail["set_parameters"]` → `spring_center_moves` false, exit 1, `release_device` and `close` recorded), `check-device --backend dinput8` PASS output names the instance and gain, non-Windows refusal (monkeypatch `platform_supports`), ambiguity error surfaces as exit 1 naming both instances, unboosted refusal on a fake without friction exits 1 with the existing message.
- [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement** — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: --backend dinput8 on run, check-device and list-devices`

---

### Task 7: The real ctypes adapter, layering and the hardware test

**Files:**
- Create: `src/wardogs_flight_eng/inputs/dinput_structs.py` (GUIDs, `DIDEVICEINSTANCEW`, `DIDEVICEOBJECTINSTANCEW`, `DIPROPDWORD`, `DIPROPRANGE`, `DIDATAFORMAT` + `DIOBJECTDATAFORMAT` for `DIJOYSTATE2` built by hand, `DIJOYSTATE2`, `DIEFFECT`, `DICONDITION`, `DIPERIODIC`, `DICONSTANTFORCE`, `DIENVELOPE`, `DIEFFECTINFOW`, vtable index tables for `IDirectInput8W`, `IDirectInputDevice8W`, `IDirectInputEffect`, HRESULT constants), `src/wardogs_flight_eng/inputs/dinput_real.py` (`RealDirectInput(DirectInputApi)`: `DirectInput8Create`, hidden window via `user32.CreateWindowExW` (class registered once, `WS_OVERLAPPED`, never shown), COM calls through `WINFUNCTYPE` prototypes, lazy `shared()` like `sdl_real.shared`), `tests/test_dinput_hardware.py` (skipped unless `WFE_HARDWARE=1` and `WFE_BACKEND=dinput8`; mirrors `test_sdl_hardware.py`: spring hold and centre move with measured axis values, sine, pulse, conditions accepted, unplug → `DeviceLostError`)
- Modify: `tests/test_layering.py` (`ctypes` allowed only in `dinput_real`, `dinput_structs`, `sdl_real`; `FORBIDDEN` gains the two modules), `tests/test_dinput_structs.py` (new: `ctypes.sizeof` of `DIEFFECT` == 80 on 64-bit Windows and the other struct sizes the builder confirms against the SDK header, the `DIJOYSTATE2` data-format object count == 164, GUID text round trips; skipped off Windows)

- [ ] **Step 1: Write the failing tests** (struct sizes and the layering rule) — [ ] **Step 2: Run to verify they fail** — [ ] **Step 3: Implement the adapter** (import-only smoke: `RealDirectInput` constructs on Windows and `enumerate_devices()` returns a list, as a test skipped off Windows) — [ ] **Step 4: Gates** — [ ] **Step 5: Commit** `feat: real DirectInput 8 adapter over ctypes; hardware conformance test`

---

### Task 8: README, release notes section and version 0.3.0

**Files:**
- Modify: `README.md` (new section "Choosing the force backend": what `sdl` and `dinput8` do, that under `dinput8` the base is read through DirectInput and the other devices through SDL, `list-devices --backend dinput8` to confirm axis indices; "Hardware tuning pass" step 3 rewritten: if SDL's `spring_center_moves` is false or the measured test fails, run `check-device --backend dinput8` then `WFE_HARDWARE=1 WFE_BACKEND=dinput8 uv run pytest tests/test_dinput_hardware.py`; Status 0.3.0 with a "Changed from 0.2.0" list covering both 2026-10-25 specs), `pyproject.toml`, `src/wardogs_flight_eng/__init__.py`, `uv.lock` (via `uv lock`)
- Test: none new; `grep -rn "0\.2\.0" --include=*.py --include=*.toml --include=*.md . | grep -v docs/superpowers` shows only history mentions.

- [ ] **Step 1: Edit** — [ ] **Step 2: Run the four gates and the grep** — [ ] **Step 3: Commit** `docs: force backend choice, tuning pass, version 0.3.0`

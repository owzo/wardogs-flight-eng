# dinput8 fallback force backend

Status: owner-directed, 2026-10-25 (clear the no-hardware backlog). No
question round; the author's calls are marked. The README has promised this
since 0.1.0: "if `spring_center_moves` is false, open an issue titled
'dinput8 fallback backend' (the planned fix is a ctypes binding to
`dinput8.dll` behind the same `ForceBackend` interface)".

## Intent

The whole force path is verified only against a fake SDL. The single
largest unknown on hardware day is whether the Moza AB9's DirectInput driver
accepts what SDL2's haptic layer sends: condition effects, spring-centre
updates, finite-length restarts. If it does not, SDL gives no second
chance. A second backend that speaks DirectInput 8 directly, through the
same `ForceBackend` protocol and the same clamp, watchdog and release
paths, turns that day from "stop and rewrite" into "switch a flag".

## Goals

1. `outputs/dinput_haptic.py::DInputHapticBackend` implements `ForceBackend`
   with the same observable behaviour as `SdlHapticBackend`: persistent
   spring, friction, damper, inertia and sine effects with finite length,
   change-detection update and half-life re-run; four-slot pools for pulses
   and transients; `all_off` zeroes and stops everything; `close` releases
   everything; a detached device raises `DeviceLostError`.
2. A `DirectInputApi` seam (`inputs/dinput_api.py`) mirroring the subset of
   DirectInput 8 used, with a real ctypes adapter (`inputs/dinput_real.py`)
   and a test fake (`tests/dinput_support.py`), exactly as `SdlApi` /
   `sdl_real` / `FakeSdl` are arranged.
3. Device matching from the profile's existing SDL GUID to the DirectInput
   device instance, with `list-devices --backend dinput8` to show what
   DirectInput sees.
4. `run --backend {sdl,dinput8}` (default `sdl`) and
   `check-device --backend {sdl,dinput8}`; with `dinput8` the **force base
   is read and driven through one DirectInput device object**, while every
   other device (collective, pedals, grips) stays on SDL. See "Builder-check
   rulings" for why.
5. Capability gating equivalent to the SDL one: unsupported condition
   kinds dropped with one warning; an `unboosted` profile refused without
   friction.
6. A hardware conformance test for the new backend, skipped without
   `WFE_HARDWARE=1`.

## Non-goals

- Replacing SDL for enumeration, calibration, or the input of any device
  other than the force base under `--backend dinput8`.
- Supporting effects the engine does not emit (ramp, square, custom).
- The Moza Flight SDK (proprietary; the reference doc covers why).
- XInput, RawInput or Windows.Gaming.Input.
- Linux or macOS.

## Anti-goals

- A force that can appear or persist outside the clamp, watchdog and
  release paths; the new backend sits behind `ClampedBackend` and
  `ReleaseWatch` exactly like SDL.
- Two backends holding the base at once: `run` constructs exactly one
  force backend.
- Hiding a driver refusal: every DirectInput HRESULT failure is surfaced
  as `SdlError`-equivalent (`DInputError`) or `DeviceLostError`, never
  swallowed.
- Vendoring anything: `dinput8.dll` is a Windows system component loaded
  by name at runtime; the package adds no dependency.

## Constraints

- Project rules as before (pure `engine/`, 200-line files, 50-line
  functions, `logging`, no bare `except`, no TODOs, the four gates).
- `engine/` is untouched. `outputs/dinput_*` import `engine.commands`, the
  seam, `inputs/protocol` (`InputDevice`, `DeviceLostError`) and
  `outputs/haptic_axes` only; the verified SDL modules are not refactored
  (shared logic is duplicated within the file limits rather than
  generalised). `ctypes` is imported only by the `inputs/dinput_*`
  adapter modules (`dinput_real`, `dinput_real_root`,
  `dinput_real_device`, `dinput_real_effects`, `dinput_com`,
  `dinput_structs`, `dinput_format`) and the pre-existing
  `inputs/sdl_real.py`.
- The layering test gains `inputs.dinput_real` and `inputs.dinput_structs`
  to the set of modules the pure packages must not import, and asserts
  `ctypes` is imported nowhere but those modules.
- Windows-only at runtime: on another OS `--backend dinput8` is a
  configuration error naming the platform. The fake makes the suite pass
  everywhere.

## DirectInput facts the design relies on (author's knowledge; the builder verifies against the SDK headers)

- Entry: `DirectInput8Create(hInstance, DIRECTINPUT_VERSION 0x0800,
  IID_IDirectInput8W, &ppv, NULL)` from `dinput8.dll`. All interfaces are
  COM vtables called through `ctypes.WINFUNCTYPE` prototypes; `HRESULT`
  negative means failure.
- Enumeration: `IDirectInput8::EnumDevices(DI8DEVCLASS_GAMECTRL,
  callback, ctx, DIEDFL_ATTACHEDONLY)`; each `DIDEVICEINSTANCEW` carries
  `guidInstance`, `guidProduct` (`Data1 = (PID << 16) | VID`),
  `tszInstanceName`, `tszProductName`. `DIEDFL_FORCEFEEDBACK` filters to
  force-feedback devices.
- Device: `CreateDevice(guidInstance)` → `IDirectInputDevice8W`;
  `SetDataFormat(&c_dfDIJoystick2)`; `SetCooperativeLevel(hwnd,
  DISCL_EXCLUSIVE | DISCL_BACKGROUND)` (force feedback requires exclusive;
  background so the game keeps focus); `Acquire()`; `Unacquire()`;
  `SendForceFeedbackCommand(DISFFC_RESET | DISFFC_STOPALL |
  DISFFC_SETACTUATORSON)`; `GetProperty(DIPROP_FFGAIN)`;
  `CreateEffect(rguid, &DIEFFECT, &ppEffect, NULL)`.
- Effect GUIDs: `GUID_ConstantForce`, `GUID_Sine`, `GUID_Spring`,
  `GUID_Damper`, `GUID_Inertia`, `GUID_Friction` (the standard
  `13541C2x-8E33-11D0-9AD0-00A0C9A06E35` family).
- `DIEFFECT`: `dwFlags = DIEFF_CARTESIAN | DIEFF_OBJECTOFFSETS`;
  `dwDuration` in microseconds (`INFINITE` allowed but not used);
  `dwGain 0..10000`; `cAxes`, `rgdwAxes` (`DIJOFS_X`, `DIJOFS_Y` …),
  `rglDirection`; `cbTypeSpecificParams` + `lpvTypeSpecificParams` =
  `DICONDITION` per axis (`lOffset`, `lPositiveCoefficient`,
  `lNegativeCoefficient`, `dwPositiveSaturation`, `dwNegativeSaturation`,
  `lDeadBand`, all on the ±10000 scale), `DIPERIODIC` (`dwMagnitude`,
  `lOffset`, `dwPhase 0..35999`, `dwPeriod` µs) or `DICONSTANTFORCE`
  (`lMagnitude` ±10000); envelope (`DIENVELOPE`) for the transient's
  fade-out.
- `IDirectInputEffect`: `SetParameters(&DIEFFECT, flags)` with
  `DIEP_TYPESPECIFICPARAMS | DIEP_DIRECTION | DIEP_DURATION …`. With
  `DIEP_NORESTART` a driver that cannot update a playing effect in place
  **fails with `DIERR_EFFECTPLAYING`** and leaves the parameters unchanged;
  without it the driver may restart and report `DI_EFFECTRESTARTED`.
  `Start(iterations, 0)`; `Stop()`; `Release()`.
- `SendForceFeedbackCommand` takes one command at a time: `DISFFC_RESET`
  (invalidates every created effect, so it is sent at open before any
  `CreateEffect`), then `DISFFC_SETACTUATORSON`; `DISFFC_STOPALL` in
  `all_off`.
- `c_dfDIJoystick2` is data in the static import library, not an export of
  `dinput8.dll`: the `DIDATAFORMAT` for `DIJOYSTATE2` is built by hand in
  `dinput_structs.py`.
- `DIPROP_AUTOCENTER` is set to off and `DIPROP_FFGAIN` to 10000 before
  `Acquire`, then `DIPROP_FFGAIN` is read back for the probe report. SDL's
  haptic layer sets both after `Acquire` and tolerates a refusal; this
  backend sets them before `Acquire`, because Windows' HID path refuses
  `DIPROP_AUTOCENTER` on an acquired device, and tolerates
  `DIERR_UNSUPPORTED` from either with one WARNING each. Every other
  failure of either call aborts the open (lost codes as `DeviceLostError`,
  the rest as `DInputError`).
- `DIERR_INPUTLOST`, `DIERR_NOTACQUIRED`, `DIERR_UNPLUGGED` mean the device
  went away or lost acquisition.
- A window handle is required for the cooperative level. SDL uses a
  hidden helper window; this backend creates its own message-only window
  through `user32` (`CreateWindowExW` with the `HWND_MESSAGE` parent, as
  SDL's helper window; never shown) and destroys it in `close`.

## Architecture (decided)

```
inputs/dinput_api.py      DirectInputApi Protocol + dataclass mirrors:
                          DiDeviceInfo, DiEffect (kind, axes, direction,
                          duration_us, gain, condition | periodic | constant,
                          envelope), DiError codes. No ctypes.
inputs/dinput_real.py     RealDirectInput: ctypes COM binding, hidden
                          window, GUIDs, struct definitions; lazy, Windows.
                          (split into dinput_real.py + dinput_structs.py to
                          stay under 200 lines)
inputs/dinput_device.py   enumerate_dinput_devices(api) -> list[DiDeviceInfo];
                          match_sdl_guid(sdl_guid, infos) -> DiDeviceInfo
                          (VID/PID from the SDL GUID bytes; prefer the
                          force-feedback instance; ambiguity -> error
                          naming both instances)
outputs/dinput_effects.py pure builders: command -> DiEffect, with
                          scale(value) -> ±10000, µs lengths, phase
outputs/dinput_persistent.py  the held effects (reuse the PersistentEffects
                          pattern with a DirectInput channel; DIEP_NORESTART
                          first, restart fallback)
outputs/dinput_channel.py DInputChannel: status-checked calls, error
                          classification, effect pool
outputs/dinput_haptic.py  DInputHapticBackend(ForceBackend)
outputs/dinput_probe.py   probe for check-device --backend dinput8
outputs/backend_choice.py build_force_backend(kind, ...) used by cli_run
tests/dinput_support.py   FakeDirectInput (records calls, in-memory effects,
                          failure injection, detach)
tests/test_dinput_*.py    effects, device matching, backend, probe, CLI
tests/test_dinput_hardware.py  WFE_HARDWARE=1 conformance (skipped)
```

- **Device matching.** The profile keeps its SDL GUID; `match_sdl_guid`
  parses VID (GUID hex chars 8–11, little-endian) and PID (chars 16–19)
  and picks the attached DirectInput instance whose `guidProduct.Data1`
  equals `(PID << 16) | VID`, preferring one reported with force feedback.
  Several candidates with force feedback is a configuration error listing
  their instance names; none is a device error.
- **Axes.** `HapticAxisMap` is reused: haptic index 0 → `DIJOFS_X`,
  1 → `DIJOFS_Y`, 2 → `DIJOFS_Z`; the sign flips centre and pulse level as
  in SDL. Single-axis effects use `cAxes = 1`.
- **Persistence.** Same keys and semantics as the SDL backend; an update
  tries `DIEP_NORESTART` and records whether the driver honoured it
  (`DI_EFFECTRESTARTED` → fall back to counting it as a restart; the sine
  phase carry applies only then).
- **Capability.** From `DIDEVCAPS.dwFlags` (`DIDC_FORCEFEEDBACK`) and
  `EnumEffects(DIEFT_ALL)`; `ConditionSupport` is reused with a mask built
  from the enumerated effect GUIDs so the same warnings, `missing` set and
  `run` refusal apply.
- **Errors.** `DInputError(RuntimeError)` for any failing HRESULT except
  the lost-device codes, which raise `DeviceLostError`; the loop maps them
  to exit 2 as today. No reacquire attempts.
- **CLI.** `--backend` on `run`, `check-device` and `list-devices`;
  `backend_choice.build_force_backend` is the one place the kind is
  interpreted. `check-device --backend dinput8` reports the device matched,
  acquisition, each effect kind created (never started) and the
  `DIPROP_FFGAIN` value.
- **Hardware test.** `tests/test_dinput_hardware.py` mirrors the SDL one:
  spring holds and moves, sine plays, pulse pushes, conditions accepted,
  unplug raises `DeviceLostError`, all under `WFE_HARDWARE=1` and
  `WFE_BACKEND=dinput8`.

## Safety

- `DInputHapticBackend` is wrapped by `ClampedBackend` and `ReleaseWatch`
  like SDL; the loop's teardown order (`all_off` then `close`) is
  unchanged.
- `all_off`: `DISFFC_STOPALL`, then every persistent effect's coefficients
  and magnitudes set to 0; `close`: `all_off`, release every effect,
  `Unacquire`, release the device and the DirectInput object, destroy the
  hidden window, idempotent.
- Finite effect lengths carry over, so a frozen loop lets the base time
  the forces out.
- Ctrl+C during effect creation follows the same `_fly`/`_close_unowned`
  path. Under `dinput8` the `Acquire` happens in `open_devices`, before
  `_fly` installs its handler; a Ctrl+C there is covered by the
  `BaseException` release in `open_dinput_joystick` (through
  `open_dinput_instance`), which releases the device and re-raises.

## Builder-check rulings (author's calls, 2026-10-25)

1. **One device object for the base.** SDL2's DirectInput *joystick*
   driver opens devices `DISCL_NONEXCLUSIVE | DISCL_BACKGROUND`; it is
   SDL's *haptic* open that is exclusive, and non-exclusive readers are
   permitted beside an exclusive holder. Under `--backend dinput8` the base
   is **never held open by SDL**: one DirectInput device object reads it
   and drives its force, and that design stands. SDL's GUID scan (finding
   each SDL-opened alias by its GUID) opens the attached joysticks in turn
   and closes each one that does not match, so it may open and close the
   base transiently, before the DirectInput open. `open_devices` opens the
   base last, after every SDL alias, as belt-and-braces: a non-exclusive
   scan would not be refused by the exclusive holder anyway. `SDL_INIT_HAPTIC`
   still does a transient, non-acquiring `CreateDevice` on the base under
   `dinput8`.
   `inputs/dinput_device.py::DInputJoystick` implements `InputDevice`
   (`poll` = `Poll` + `GetDeviceState(DIJOYSTATE2)`, `axis`, `button`,
   `alive`, `name`, and `guid` = the profile's SDL GUID string so
   `device_map` is unchanged) over the acquired device, and
   `DInputHapticBackend` drives force on that same object. `open_devices`
   gains a `dinput_base: str | None` alias to open that way; every other
   alias stays SDL. Axis indices come from the device's axis objects
   enumerated in `dwOfs` order (`EnumObjects(DIDFT_AXIS)`), which is the
   order SDL's DirectInput driver numbers them; `list-devices --backend
   dinput8` prints each axis with its offset name, `DIDOI_FFACTUATOR` flag
   and live value so the owner can confirm the profile's indices before
   flying. Pitch and roll must be `FFACTUATOR` axes, else a configuration
   error naming the axis.
2. **Update in place, with one tolerated failure.** A changed persistent
   effect is updated with `SetParameters(... | DIEP_NORESTART)` and **not**
   started again. `DIERR_EFFECTPLAYING` is the single HRESULT handled rather
   than raised: the update is retried without `DIEP_NORESTART` (accepting
   the restart, applying the sine phase carry), the refusal is latched per
   effect kind so it is tried once, and an INFO line records it. `Start`
   is called on creation, after `all_off`, and at the half-life re-run
   (the duration counts from the last `Start`, so the half-life timer is
   per `Start`, never reset by an in-place update). `dinput_persistent.py`
   therefore has its own held-effect logic, not a reuse of
   `PersistentEffects`.
3. **Auto-centre off, gain full** before `Acquire`, as stated above; the
   probe reports the read-back gain.
4. **Probe never starts an effect**, like the SDL probe: it creates each
   kind with zero coefficients and tests the spring-centre update with
   `SetParameters(DIEP_TYPESPECIFICPARAMS)` on the never-started spring. It
   fills the same `PrimitiveReport` fields and uses the same PASS / WARN /
   FAIL rules; the report also prints the matched instance, the acquire
   result, the gain and the axis table. The hardware test does the
   force-bearing checks.
5. **Device loss** is noticed by the input poll every tick
   (`DIERR_INPUTLOST` / `DIERR_NOTACQUIRED` / `DIERR_UNPLUGGED` →
   `DeviceLostError`), so the loop exits `device_lost` within one tick; the
   force side classifies the same codes on its own calls. No extra
   per-tick force call.
6. **No SDL refactor.** `dinput_capabilities.py` builds the same `missing`
   frozenset with the same warning texts from `EnumEffects`; the existing
   `refuse_unboosted_without_friction` already takes a frozenset.
7. **`--refresh-every-tick`** (from the backlog spec) is an SDL option;
   with `--backend dinput8` it is a usage error.

8. **Sine phase clock (amended after Task 5's review).** The backend
   re-anchors the sine phase clock on every send, as SDL's
   `PersistentSines` does: the uploaded effect always carries the phase the
   waveform has reached, because `HeldEffects` only learns whether the
   driver restarted after the effect is built, and holding the phase
   between `Start`s made `due` true every tick. This is continuous across
   a fallback restart, the half-life re-run and a steady sine, and it is
   an **unverified assumption** for an in-place update (continuous only if
   the driver ignores `dwPhase` while playing or treats it as the current
   phase; a firmware that applies it from the last `Start` would jump on
   every send) and for an in-place period change during spool-up. The
   hardware test carries a magnitude ramp and a spool-up frequency sweep
   to tell these apart; if the AB9 shows the jump, the backend switches to
   holding the phase between `Start`s using `HeldEffects.restarted`, which
   is kept for that purpose. Ruling 2's phrase "applying the sine phase
   carry" and the Architecture bullet "applies only then" are superseded
   by this ruling.

## Left to the builder

- The exact ctypes struct layouts and vtable indices (from the DirectInput 8
  headers). Decided: the window is message-only (`HWND_MESSAGE` parent,
  see the DirectInput facts above), not `WS_OVERLAPPED`; a
  `SetCooperativeLevel` failure is a clear `DInputError`.
- Whether `dinput_persistent.py` can reuse `PersistentEffects` through a
  small channel protocol or needs its own copy.
- Log wording; `list-devices --backend dinput8` table columns.

## Acceptance

1. Gates green; layering test passes with `ctypes` confined to the
   `inputs/dinput_*` adapter modules and `sdl_real.py`.
2. Effect builder tests pin every scale and unit (±10000, µs, phase).
3. Backend tests against the fake mirror the SDL backend suite: persistent
   update-on-change (no `Start` after an in-place update) and half-life
   re-run, `DIERR_EFFECTPLAYING` → retry without `DIEP_NORESTART` latched
   per kind, pools, `all_off` zeroing, `close` release order (effects,
   `Unacquire`, device, DirectInput, window), device lost from the input
   poll and from a force call, apply after close ignored, capability gating
   and `unboosted` refusal; `DInputJoystick` input tests (axis order from
   enumerated objects, button reads, loss on poll).
4. Device-matching tests: VID/PID parse, force-feedback preference,
   ambiguity error, no-match error.
5. CLI tests: `run --backend dinput8` builds the DirectInput backend and
   never opens an SDL haptic; `check-device --backend dinput8` report and
   exit codes; non-Windows refusal.
6. README: a "Choosing the force backend" section, the hardware tuning
   pass step 3 rewritten (if SDL's `spring_center_moves` is false, run
   `check-device --backend dinput8`), and the new hardware test.

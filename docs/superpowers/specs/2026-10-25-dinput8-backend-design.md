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
   `check-device --backend {sdl,dinput8}`; input always stays on SDL.
5. Capability gating equivalent to the SDL one: unsupported condition
   kinds dropped with one warning; an `unboosted` profile refused without
   friction.
6. A hardware conformance test for the new backend, skipped without
   `WFE_HARDWARE=1`.

## Non-goals

- Replacing SDL for input, enumeration or calibration.
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
  seam and `outputs/haptic_axes` only; `inputs/dinput_real.py` is the only
  module that imports `ctypes`.
- The layering test gains `inputs.dinput_real` to the set of modules the
  pure packages must not import, and asserts `ctypes` is imported nowhere
  else.
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
  `DIEP_TYPESPECIFICPARAMS | DIEP_DIRECTION | DIEP_DURATION …` and
  `DIEP_NORESTART` to update a playing effect without restarting it
  (returns `DI_EFFECTRESTARTED` if the driver restarted anyway);
  `Start(iterations, 0)`; `Stop()`; `Release()`.
- `DIERR_INPUTLOST`, `DIERR_NOTACQUIRED`, `DIERR_UNPLUGGED` mean the device
  went away or lost acquisition.
- A window handle is required for the cooperative level. SDL uses a
  hidden helper window; this backend creates its own hidden top-level
  window through `user32` (`CreateWindowExW`, never shown) and destroys it
  in `close`.

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
- Ctrl+C during `Acquire` or effect creation follows the same
  `_fly`/`_close_unowned` path.

## Left to the builder

- The exact ctypes struct layouts and vtable indices (from the DirectInput 8
  headers); whether to generate the hidden window with `WS_OVERLAPPED` or
  a message-only parent (try the former; a `SetCooperativeLevel` failure is
  a clear `DInputError`).
- Whether `dinput_persistent.py` can reuse `PersistentEffects` through a
  small channel protocol or needs its own copy.
- Log wording; `list-devices --backend dinput8` table columns.

## Acceptance

1. Gates green; layering test passes with `ctypes` confined to
   `dinput_real.py` / `dinput_structs.py`.
2. Effect builder tests pin every scale and unit (±10000, µs, phase).
3. Backend tests against the fake mirror the SDL backend suite: persistent
   update-on-change and half-life re-run, `DIEP_NORESTART` honoured vs
   restarted, pools, `all_off` zeroing, `close` release order, device
   lost, apply after close ignored, capability gating and `unboosted`
   refusal.
4. Device-matching tests: VID/PID parse, force-feedback preference,
   ambiguity error, no-match error.
5. CLI tests: `run --backend dinput8` builds the DirectInput backend and
   never opens an SDL haptic; `check-device --backend dinput8` report and
   exit codes; non-Windows refusal.
6. README: a "Choosing the force backend" section, the hardware tuning
   pass step 3 rewritten (if SDL's `spring_center_moves` is false, run
   `check-device --backend dinput8`), and the new hardware test.

# Wardogs Flight Eng — design

Date: 2026-10-22. Owner: Skye Stubbins (Owzo). Status: draft for owner approval.

## Intent

Wardogs (Bulkhead, UE 5.7, Steam 1867240) sends no force feedback to any
joystick: there is no DirectInput FFB path, no telemetry output, and no
force-feedback asset in the game files. The owner is receiving a Moza AB9
force-feedback base and wants the game's helicopters (Littlebird, Lakota,
Havoc) to feel like a hydraulically boosted attack helicopter: an artificial
feel spring around a trim point, tap-to-lock / tap-to-reset trim, a rotor
buzz through the grip, and weapons that kick — without the stick ever
fighting the pilot.

Wardogs Flight Eng is a standalone, open-source program that produces those
forces from the only live signal it is allowed to read: the stick's own axes
and buttons. The game is never touched (Elytra kernel anti-cheat makes
memory reading, injection and virtual input devices unacceptable). The
stick is both sensor and actuator.

It is written so that Python users can import the core, extend it and send
improvements back, and so that any DirectInput force-feedback base — not
only the AB9 — works with it.

## Goals

1. On day one, with the AB9 plugged in and Wardogs running, the Littlebird,
   Lakota and Havoc each feel distinct: trim spring, rotor buzz, recoil.
2. Trim lock / trim reset on two grip buttons, behaving as the owner
   described (tap to capture the current stick position as the new centre;
   tap to return to origin).
3. The engine is fully testable with no hardware attached: a simulated stick
   drives it and a force log records what would have been sent.
4. Any DirectInput PID base works; the AB9 is the first-class, tested target.
5. Publishable: MIT licence, no game-file contents, every game-derived number
   carries its provenance (Steam build id, asset path, property name).

## Non-goals

- Reading anything from the running game (memory, screen, audio, network).
  Screen-derived state ("Tier 2") is a possible later project, not this one.
- Elevation, charge, or any fire-support computation — that is Wardogs Fire
  Support, a separate repo; nothing is imported from it.
- Collective (throttle axis) force feedback. Moza throttles have none; the
  stick carries everything.
- Yaw force feedback. The AB9 base drives pitch and roll; the game's own
  yaw assist already holds heading while the pedal is inside its 0.05
  threshold.
- A graphical editor. Profiles are JSON files edited by hand; a GUI is a
  later project.
- Linux / macOS. Windows only (the game is Windows only).

## Anti-goals (failure even if it "works")

- Anything that moves the trim centre on its own. Every effect other than
  the trim buttons is additive and transient; the stick never twitches or
  wanders.
- Any dependency the game's anti-cheat could object to: no vJoy, no ViGEm,
  no virtual HID devices, no hooks, no injected DLLs, no reading the game
  process.
- Numbers invented from real aircraft. Rotor speed, fire rates, reload
  times and shake envelopes come from the game files with provenance; feel
  stiffness, amplitudes and button choices are declared as owner taste in
  the profile, never dressed up as game data.
- A resident driver. The program is started for a Wardogs session and
  stopped afterwards; it must not interfere with Pit House, TelemFFB, DCS or
  MSFS when it is not running, and must release the device cleanly on exit
  or crash.
- Shipping pak contents, the AES key, or mappings files.

## Constraints

- No force-feedback hardware is available until the AB9 arrives; nothing
  can be felt-tested before then. The simulated path is therefore the
  primary acceptance path for the first release, followed by a short
  on-hardware tuning pass.
- Windows 11, Python 3.12+, uv, ruff, pytest, mypy (owner's standard stack).
- Device access through SDL2's haptic API (`pysdl2` + `pysdl2-dll`), which on
  Windows is DirectInput underneath and exposes the three primitives needed:
  spring condition with a centre offset, periodic sine, constant force. If
  the AB9 conformance check (below) shows SDL does not move the spring
  centre on this base, the fallback is a `ctypes` binding to `dinput8.dll`
  behind the same backend interface. Both are pure Python.
- Loop rate 100–250 Hz; effect updates must never block the loop.
- The engine cannot know which helicopter the pilot is in; the pilot selects
  the airframe.
- **Hardware on the desk (owner):** the AB9 base with its grip, a full
  collective, and rudder pedals — three separate USB HID devices. Force
  feedback exists only on the base; the collective and pedals are read-only
  inputs. The engine reads all three.

## Game constants (provenance: Steam build 25937608, extracted 2026-10-22)

Every value below is a raw game value from the asset named; the public repo
carries these in `data/wardogs_heli_constants.json` with the same provenance
fields as the Wardogs Fire Support weapon records (`build_id`, `asset`,
`property`, `extracted_at`). The builder copies them from the owner's
`Wardogs/docs/heli-ffb-game-constants.md`; no extraction tooling ships.

| Airframe | Plugin | Mass kg | Main rotor RPM | 1/rev Hz | Source |
|---|---|---|---|---|---|
| Littlebird | ROT_03 | 722 | 330.4 (blur-curve top) | 5.51 | `FC_ROT_03_MainRotorRPM_MaterialValue` |
| Lakota | ROT_02 | 7500 | 250 (blur-curve top) | 4.17 | `FC_ROT_02_MainRotorRPM_MaterialValue` |
| Havoc | ROT_04 | 9500 | 270 (`MainRotorOperatingRPM`) | 4.50 | `DA_ROT_04_Engine` |

Blade count is not in any game asset: no N/rev harmonic is generated.

| Weapon (extension asset) | Airframe | RPM | Pulse Hz | Wind-up s | Reload s | Shake envelope |
|---|---|---|---|---|---|---|
| `WE_ROT_03_AttachedMachineGuns` | Littlebird | 1500 | 25 | 0.25 | 4.25 (+1 start, +1 end) | multiplier 0.15 |
| `WE_ROT_03_Weapon_122mm` | Littlebird | 350 | 5.83 | 0 | 6 (1 start, 0.75 per round) | `B_CameraShake_Littlebird_HeliFiring` |
| `WE_ROT_02_Weapon_30mmCannon` | Lakota | 250 | 4.17 | 0 | 8 | `B_CameraShake_HeliFiring` |
| `WE_ROT_02_Weapon_122mm` | Lakota | 500 | 8.33 | 0 | 6 (1 start, 0.75 per round) | `B_CameraShake_HeliFiring` |
| `WE_ROT_04_MountedMachineGun` | Havoc | 1500 | 25 | 1.0 | 5 (+1, +1) | `BP_ROT_04_Camera_MachineGun_FiringShake`, 0.15 |

Shake envelopes (Perlin noise; rotation amplitude in degrees):
`B_CameraShake_HeliFiring` rotation 1.0 x freq 8, yaw 0.5 @ 2 Hz, FOV 2.0 @
5 Hz, 0.4 s, blend-out 0.25; `B_CameraShake_Littlebird_HeliFiring` rotation
2.0 x 6, yaw 0.5 @ 2 Hz, 0.4 s, blend-out 0.25; Havoc MG pitch 12 Hz, yaw
0.1, FOV 1.0 @ 30 Hz, 0.4 s, blend-out 0.6. Crash: 50 Hz, 0.25 s, location
1.5 x 2 (first person). Landed: location 4 x 2, 0.3 s, blend-in 0.1.
MG recoil pattern (yaw, pitch), seven steps, shared by both MGs:
(1.107, 2.406) (-0.308, 1.661) (-0.988, 0.876) (-0.548, 1.838) (0.504, 1.501)
(-0.205, 2.853) (-1.093, 2.003).

Game input facts the engine relies on: HOTAS roll/pitch feed the cyclic
positionally; the throttle axis is the absolute collective; the in-game
HOTAS deadzone defaults to 0.05 (max 0.5) and sensitivity to 1.0; the game
drops its own heading hold when the pedal exceeds 0.05. Crash and Landed are
game events the stick cannot observe; their envelopes are included so a
later state source can trigger them, and the simulated stick can fire them.

## The feel model (decided)

Four effects, all per-airframe, all defined in the profile JSON.

1. **Feel spring.** A DirectInput spring condition on pitch and roll whose
   centre is the current trim point. Stiffness is fixed per airframe
   (owner taste); the Littlebird is the lightest, the Havoc the heaviest,
   with mass used only as the ordering. Optional deadband near centre.
   Stiffness does not vary with speed (no speed is available).
2. **Trim.** Two grip buttons. *Trim lock* (tap): the spring centre is set
   to the stick's current pitch/roll. *Trim reset* (tap): the centre
   returns to origin. Nothing else ever moves the centre. The transition
   is slewed over a short, profile-set time so the stick does not snap.
3. **Rotor buzz.** A periodic sine on both axes at the airframe's 1/rev
   frequency. Amplitude = base amplitude x collective position (0 at
   bottom, 1 at top) x an optional cyclic-deflection factor, all profile
   values. Starts from zero on engine start with the profile's spool-up
   time; the game's spool-down (850 RPM/s, `DA_ROT_03_Engine`) is the
   default spool-down.
4. **Weapon recoil.** While the fire button is held: after the weapon's
   wind-up, a constant-force pulse per round at the weapon's fire rate,
   direction stepping through the seven-step recoil pattern (MGs) or a
   fixed rearward kick (rockets, cannon), amplitude from the profile and
   scaled by the game's shake multiplier where one exists.

   *One pilot weapon per profile (game fact).* The pilot-seat input
   context `IMC_RotaryVehicles_DriverGunner` binds only Fire and Reload;
   weapon cycling (`IA_Vehicle_Weapon_CycleWeapons`, key Z) and the
   1–6 weapon slots exist only in the mounted-gunner context. The pilot's
   weapon is fixed by the vehicle variant bought (AH-6M miniguns, AH-6R
   rockets are separate vehicles). Profiles are therefore per variant,
   each naming its single pilot weapon; there is no weapon-cycle button.
   Shipped profiles: `littlebird-miniguns`, `littlebird-rockets`,
   `lakota`, `havoc`. The Havoc's MG is a mounted-gunner weapon, so the
   `havoc` profile has no recoil. Which of the Lakota's two extensions the
   pilot seat fires is not stated in the dumped assets; the `lakota`
   profile defaults to the B-13 rockets and the owner corrects it in game
   (builder marks the field `verify_in_game`).

   *Reload (my call, game-data rule).* Magazine capacity is in no dumped
   asset: `WeaponStartingInventoryItems` is reserve ammo
   (`AmmoInsertionMethod: PullsAmmoFromReserve`), not a magazine. So the
   engine never auto-reloads. The Reload button starts a silence window
   of the weapon's summed `ReloadSetupData`, using the repo convention
   from Wardogs Fire Support (start + reload + end): Littlebird MGs
   1 + 4.25 + 1 = 6.25 s; Lakota cannon 8 s; rockets 1 + 6 = 7 s with the
   0.75 s per-round loop omitted because the round count is unknown (the
   profile shows `rounds_per_reload: UNKNOWN - WARDOGS GAME VALUE
   REQUIRED`). Firing during the window produces no pulses.

5. **Rotor state (my call).** The game starts the engine on entry with no
   player key (there is a start-up audio sequence but no engine action in
   any input context), so the stick cannot observe it. The rotor model is
   *running* from program start, spooling up over the profile's spool-up
   time; an optional **rotor on/off** toggle button lets the pilot spool
   it down (default 850 RPM/s, `DA_ROT_03_Engine`) when parked, and
   program exit spools down before releasing the device.

Transient envelopes (firing shake, crash, landed) are modelled as additive
periodic effects with the game's duration, frequency and blend-out; the
first release triggers only the firing shake (from the fire button).

## Architecture (decided)

```
wardogs_flight_eng/
  engine/        pure logic, no SDL, no I/O: trim state machine, effect
                 synthesis, weapon timing, profile model. 100% unit tested.
  constants/     game constants with provenance, loaded from data/*.json.
  inputs/        InputSource protocol over a *composite* of devices:
                 SdlDevice (real, one per USB device), SimulatedDevice
                 (scripted or scenario-driven). A DeviceMap in the profile
                 binds logical channels (cyclic_pitch, cyclic_roll,
                 collective, pedals, and every button) to
                 (device, axis-or-button) pairs.
  outputs/       ForceBackend protocol: SdlHaptic (real), LoggingBackend
                 (writes a CSV/JSONL force log), NullBackend.
  profiles/      JSON schema + the three shipped airframe profiles.
  cli.py         wardogs-flight-eng run|dry-run|list-devices|check-device
```

- `engine/` imports nothing from `inputs/`, `outputs/`, or SDL; a layering
  test enforces it, as in Wardogs Fire Support. The engine sees only
  logical channels; it never knows how many physical devices exist.
- **Multi-device input (decided).** Devices are identified in the DeviceMap
  by SDL joystick GUID with the product name as a human-readable fallback,
  never by enumeration order (hot-plug order changes). Only the device that
  carries `cyclic_pitch` / `cyclic_roll` receives force effects. A missing
  device at start is a clear error naming the channel it was to supply;
  a device lost mid-session zeroes all forces and the program exits
  cleanly rather than guessing. `list-devices` prints every device's GUID,
  name, axes and buttons, and shows live values so the owner can identify
  which physical axis is which. A `calibrate` command records the
  collective's bottom and top raw values and the pedals' centre, stored in
  the DeviceMap; the engine normalises collective to 0..1 and pedals to
  -1..1 from those.
- Pedal position is read and logged but drives no force in the first
  release (no yaw FFB on the base); it is available to effects so a later
  profile can, for example, damp the cyclic while the game's heading hold
  is released (pedal beyond 0.05).
- The loop: read input → engine.step(dt, input) → list of effect commands →
  backend.apply(commands). Commands are value objects; the backend owns
  effect lifetimes and never blocks the loop.
- `check-device` performs the conformance check on a real base: creates a
  spring, moves its centre, creates a sine and a constant pulse, and reports
  which primitives the device accepted. This is the first thing run when
  the AB9 arrives.
- `dry-run` runs a scenario (take-off, trim lock, fire miniguns, trim
  reset) against simulated stick, collective and pedals and writes the
  force log plus a small HTML plot, so behaviour can be reviewed before any
  hardware exists.
- Profiles declare the airframe variant and its pilot weapon, the button
  map (trim lock, trim reset, fire, reload, rotor on/off, profile cycle,
  all-forces-off), spring stiffness and deadband, buzz amplitudes and spool
  times, recoil amplitude, and a `taste` block marking which values are
  owner preference versus game data.
- Packaging: `uv` project, `pyproject.toml`, entry point
  `wardogs-flight-eng`; PyInstaller spec producing one `.exe` for non-Python
  users. MIT licence. README states the anti-cheat posture plainly: the
  program never touches the game.

## Safety and coexistence (decided)

- On start the program acquires the device exclusively only for the
  duration of the session and releases it on exit, `Ctrl+C`, and on any
  unhandled exception (`finally`-guarded teardown that zeroes all effects).
- A global "all forces off" button in the profile and a watchdog: if the
  input loop stalls for more than a profile-set interval, every effect is
  zeroed.
- Force magnitudes are clamped at the backend to a profile-set ceiling
  (default well below the AB9's maximum) so a bad profile cannot slam the
  stick.
- The program does not autostart, install services, or persist anything
  outside its own config folder.

## Left to the builder

- Exact JSON schema fields and validation (pydantic or hand-rolled, builder's
  choice; must give clear errors for a bad profile).
- Default button numbers and which physical device (grip or collective
  head) carries each button: the owner assigns them on first run from
  `list-devices`; shipped profiles ship with the DeviceMap empty and a clear
  "run list-devices and calibrate first" error.
- The slew curve for trim transitions and the default deadband.
- How the dry-run HTML plot is produced (any dependency-light approach).
- Logging layout (`logging`, never `print`), log rotation, config folder
  location (`%LOCALAPPDATA%\WardogsFlightEng`).
- Whether the Moza Flight SDK backend is worth adding after the SDL path is
  proven; it is out of scope for the first release.

## Acceptance for the first release

1. `pytest` green, layering test included; engine behaviour covered by
   scenario tests against the simulated stick (trim lock/reset, buzz
   follows collective, recoil at 25 Hz with wind-up and reload gaps).
2. `wardogs-flight-eng dry-run --airframe littlebird` produces a force log
   and plot the owner can read without hardware.
3. `wardogs-flight-eng check-device` reports the AB9's primitive support.
4. With the hardware: all four shipped profiles load, `calibrate` maps the
   collective and pedals, trim lock/reset work, buzz follows the real
   collective, and the program releases the base cleanly on exit.

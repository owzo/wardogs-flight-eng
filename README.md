# Wardogs Flight Eng

Force-feedback synthesiser for Wardogs helicopters.

Wardogs sends no force feedback to any joystick. Flight Eng produces it from
the only signal it is allowed to read: your own stick, collective and pedals.
It gives the Littlebird, Lakota and Havoc a centring spring around a trim
point you set with a button, a rotor buzz through the grip, and weapon recoil,
through a Moza AB9 or any other DirectInput force-feedback base. It is MIT
licensed, Windows only, and Python 3.12+.

## What this does and does not touch

- It reads your own HID devices (your stick, pedals and collective).
- It writes force-feedback effects to your own base.
- It never reads the game process, the screen, memory or the network.
- It installs no drivers and no virtual devices.

## Status

Version 0.1.0 (v1).

- **Complete and tested:** the whole engine and the no-hardware path. A
  scripted scenario drives simulated devices through the engine and writes a
  force log and a plot (see "Try it without hardware"). The test suite covers
  the engine, the profile and constants loading, the runtime loop and the CLI.
- **Built but not yet run on an AB9:** the SDL haptic path that talks to a
  real base. It was written and tested against a fake SDL implementation, and
  SDL's joystick enumeration works in the packaged `.exe`, but no force has yet
  been played on a Moza AB9: the owner's base has not arrived. Treat the first
  run as a tuning session (see "Hardware tuning pass"), keep a hand near the
  stick, and keep the default `force_ceiling` in the shipped profiles. Do not
  assume the feel values are right for your base.
- **Not in v1:** collective or yaw force feedback, a GUI, reading any game
  state, Linux or macOS.

## Install

**Developers:** install [uv](https://docs.astral.sh/uv/), then

```
git clone <this repository>
cd wardogs-flight-eng
uv sync
uv run wardogs-flight-eng --help
```

In a checkout, prefix every command below with `uv run`. To build the `.exe`
yourself:

```
uv run pyinstaller packaging/wardogs-flight-eng.spec
```

The result is `dist/wardogs-flight-eng.exe`.

**Everyone else:** use `wardogs-flight-eng.exe`, a single file that needs no
Python (take it from a release once one is published, or build it yourself as
above). Put it in a folder of your own and run it from a terminal there. The
commands below write `wardogs-flight-eng`; with the `.exe` type
`wardogs-flight-eng.exe`.

The shipped profiles are the four JSON files in
`src/wardogs_flight_eng/profiles/` of the repository: copy the one you want out
of there into a folder of your own and edit the copy. (The `.exe` carries them
inside itself, where you cannot edit them.) If you only have the `.exe`,
download the repository as a ZIP from its page and take the profiles from
`src/wardogs_flight_eng/profiles/` and the scenario from `tests/scenarios/`.

## First run

Plug in the base, collective and pedals. Close Moza Cockpit or set it to a
plain DirectInput preset first (see "Moza Cockpit companion settings"). Then,
in order:

### 1. Identify your devices

```
wardogs-flight-eng list-devices --live
```

Prints a table of every joystick (`index`, `guid`, `name`, `axes`, `buttons`,
`haptic`), then reprints live values every 0.1 s until Ctrl+C. Move each
control and note which device and which axis number moves (and in which
direction), and press each grip button you want to use and note its number.
Axis and button numbers start at 0. The base is the device with `haptic` set
to `yes`.

### 2. Fill `device_map` in your profile

Open your copy of a profile and replace its empty `device_map`. A complete
example for a stick, a collective and pedals (the GUIDs and numbers are
placeholders; use your own from step 1):

```json
"device_map": {
  "devices": {
    "stick": {"guid": "0300aaaa0000000000000000deadbeef", "product": null},
    "collective": {"guid": "0300bbbb0000000000000000deadbeef", "product": null},
    "pedals": {"guid": "0300cccc0000000000000000deadbeef", "product": null}
  },
  "axes": {
    "pitch": {"device": "stick", "axis": 1, "invert": false},
    "roll": {"device": "stick", "axis": 0, "invert": false},
    "collective": {"device": "collective", "axis": 0, "invert": false},
    "pedals": {"device": "pedals", "axis": 0, "invert": false}
  },
  "buttons": {
    "trim_lock": {"device": "stick", "button": 0},
    "trim_reset": {"device": "stick", "button": 1},
    "fire": {"device": "stick", "button": 2},
    "reload": {"device": "stick", "button": 3},
    "rotor_toggle": {"device": "collective", "button": 0},
    "profile_cycle": {"device": "collective", "button": 1},
    "all_off": {"device": "stick", "button": 4}
  },
  "calibration": {
    "collective_bottom_raw": -1.0,
    "collective_top_raw": 1.0,
    "pedals_center_raw": 0.0
  }
}
```

Rules the loader enforces: the names under `devices` are your own aliases;
every binding must name one of them; `guid` and `product` must both be present
(set one to `null`; with no `guid` the first device whose name contains
`product` is used). `pitch` and `roll` must be axes of the force-feedback base
itself, and their `axis` numbers are also the haptic axis numbers sent to the
base, so they must be 0, 1 or 2. `invert: true` flips an axis's sign (and the
forces with it). The `calibration` block is overwritten by the next step.

What the seven buttons do:

| Button | Tap or hold | Effect |
|---|---|---|
| `trim_lock` | tap | the spring centre moves to where the stick is now |
| `trim_reset` | tap | the spring centre returns to origin |
| `fire` | hold | recoil pulses after the weapon's wind-up (profiles with a pilot weapon) |
| `reload` | tap | silences recoil for the weapon's reload time |
| `rotor_toggle` | tap | spools the rotor buzz down, or back up |
| `profile_cycle` | tap | switches to the next profile given to `run` |
| `all_off` | tap | latches every force off; tap again to resume |

### 3. Calibrate

```
wardogs-flight-eng calibrate --profile my-littlebird-miniguns.json
```

It asks for three positions, each followed by Enter: collective fully down,
collective fully up, pedals centred. It rewrites only the profile's
`device_map.calibration` (atomically; the rest of the file is untouched) and
refuses to write if the collective read the same value at both ends.

### 4. Check the base

```
wardogs-flight-eng check-device
```

Opens the first force-feedback device (or `--guid GUID` for a specific one) and
asks it to create a spring, a moving spring centre, a sine and a constant
force. Nothing is played, so the stick does not move. It prints one `yes`/`no`
per primitive and `PASS` or `FAIL`. Note that "accepted" means the driver took
the request; only flying it, or `tests/test_sdl_hardware.py` (see the tuning
pass), shows the stick actually moves.

### 5. Run

```
wardogs-flight-eng run --profile my-littlebird-miniguns.json
```

Add `--rate HZ` (default 200) to change the loop rate, `--log forces.jsonl` to
also record every command, and `--verbose` for debug logging (it goes after the
subcommand). To switch airframes in flight, give several profiles and tap the
`profile_cycle` button:

```
wardogs-flight-eng run --profile a.json --profile b.json
```

Profiles in one run must have an identical `device_map` (`run` names the first
field that differs), and the strictest `force_ceiling` and the shortest
`watchdog_s` among them apply to all.

**Stopping.** Press Ctrl+C once: the loop finishes its tick, zeroes every
force and releases the base, and prints `stopped: ...`. Further presses within
3 seconds are ignored so they cannot cut the release short. A press after 3
seconds escapes a hung tick (the release still runs). If the final message says
`the force base did not confirm its release; power-cycle it if it still
pushes`, the release could not be confirmed: do what it says. If a device is
unplugged mid-flight the forces are zeroed and the program exits with code 2.

**Exit codes.** `0` success (stopped by Ctrl+C or a tick limit); `1` a usage,
profile, scenario or configuration error (the message names the file and
field); `2` a device is missing or was lost, SDL or the force base failed
during the run (`stopped: error`), or the base's release was not confirmed.

Logs are written to `%LOCALAPPDATA%\WardogsFlightEng\logs\wardogs-flight-eng.log`
and to stderr.

## Try it without hardware

```
wardogs-flight-eng dry-run --profile src/wardogs_flight_eng/profiles/littlebird-miniguns.json --scenario tests/scenarios/takeoff-trim-fire.json
```

Needs no devices; with the `.exe`, copy the profile and the scenario file out
of the repository first. The scenario (`tests/scenarios/takeoff-trim-fire.json` in the
repository) scripts a 12-second flight on simulated devices: collective up,
a stick push, a trim lock, a burst of fire, a trim reset. The profile's
`device_map` is not used (the scenario carries its own). The command prints
the paths of two files, written to `--out DIR` or by default to
`%LOCALAPPDATA%\WardogsFlightEng\dry-runs\<timestamp>\`:

- `forces.jsonl`: every command the engine issued, one JSON object per line.
- `forces.html`: a self-contained page (no scripts) with a pitch row and a roll
  row on a shared time axis in seconds. Each row shows the spring centre and
  the rotor sine magnitude as lines, recoil pulses as ticks above or below the
  zero line (the sign is the push direction), shake transients as short bars
  whose length is their duration, and any `all_off` as a red band across both
  rows. You should see the spring centre step at the trim lock and return at
  the reset.

## Moza Cockpit companion settings

If you use a Moza base, Moza Cockpit and Flight Eng must not both drive the
spring. `docs/reference/community-ffb-references.md` lays out the two valid
divisions of labour: **A** (Flight Eng owns spring and trim; Cockpit keeps
damper, friction, inertia and breakout, with its `bacic_spring` and hardware
balancing at 0/off) or **B** (Cockpit owns spring and hardware trim; Flight Eng
profile sets `feel.spring_coefficient` to 0 and supplies only buzz and recoil).
Pick one, and never run two springs at once: the stick would be pulled to a
point between the two centres and trim lock would break.

## What the forces are and where the numbers come from

Four effects, per airframe, all set in the profile JSON:

1. **Feel spring.** A centring spring on pitch and roll around the trim point
   (the roll spring is `spring_coefficient * roll_scale`), with a deadband.
2. **Trim.** `trim_lock` and `trim_reset` move the spring centre, slewed over
   `trim_slew_s`. Nothing else ever moves it: the stick never wanders.
3. **Rotor buzz.** A sine at the airframe's main-rotor frequency on both axes,
   scaled by the collective position and a little by cyclic deflection, with a
   spool-up when the program starts.
4. **Weapon recoil.** While `fire` is held, after the weapon's wind-up, one
   force pulse per round at the weapon's fire rate, stepping through the game's
   recoil pattern (or a fixed rearward kick for rockets), plus the weapon's
   shake. One pilot weapon per profile; the `havoc` profile has none.

**Game data with provenance.** Rotor speeds, fire rates, wind-ups, reload times
and shake envelopes are game facts and live only in
`src/wardogs_flight_eng/data/wardogs_heli_constants.json`, with the Steam build
id, extraction date and asset names recorded. Stiffnesses, amplitudes and
ceilings are the owner's taste, listed in each profile's `taste` field, and are
never presented as game data. Nothing is guessed from real aircraft.

```
wardogs-flight-eng show-constants
```

prints every airframe and weapon constant with its build. A value the game
files do not give is `null` in the data and is displayed as
`UNKNOWN - WARDOGS GAME VALUE REQUIRED`. Where the engine must have a number
to run, it uses a stated placeholder, which is **not game data**. There are
exactly two:

- **Spool-down rate, 850 rpm/s.** This is the Littlebird's game value
  (`DA_ROT_03_Engine`). The Lakota and Havoc have no known value (their
  `spool_down_rpm_per_s` shows as UNKNOWN), so on them `rotor_toggle` spools the
  rotor buzz down at the Littlebird's rate until the real value is found. A
  profile's `rotor.spool_down_rpm_per_s`, if you set it, overrides this.
- **Shake multiplier, 1.0.** A weapon whose `shake_multiplier` is UNKNOWN
  (the rockets and the Lakota cannon) has its recoil gain scaled by 1.0, i.e.
  not scaled.

**`verify_in_game`.** Each profile has a `verify_in_game` list naming values the
owner must confirm in the game because the game files do not settle them. It is
empty for most profiles; the Lakota profile lists `pilot_weapon` (which of the
Lakota's weapons the pilot seat fires is not stated in the game files, so the
profile assumes its rockets). Check the entries, correct the profile if the game
disagrees, and then empty the list.

**Contributing a constant.** Open an issue or pull request giving, for each
value: the game asset path, the property name, the Steam build id you read it
from, and the value. Never paste or attach game files, pak contents, dumps,
keys or mappings files.

## Python API

The engine is plain Python and needs no hardware. This runs 100 ticks of the
Littlebird profile on simulated devices and logs every force command (run it
from the repository root; the scenario file is used only for its device map,
which names the four devices created below):

```python
from pathlib import Path

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.simulated import Scenario, SimulatedDevice
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend
from wardogs_flight_eng.runtime.loop import run_loop

constants = load_constants()
profile = load_profile(PROFILES_DIR / "littlebird-miniguns.json")
device_map = Scenario.load(Path("tests/scenarios/takeoff-trim-fire.json")).device_map
devices = {
    "stick": SimulatedDevice("stick", axis_count=2),
    "grip": SimulatedDevice("grip", button_count=8),
    "coll": SimulatedDevice("coll", axis_count=1),
    "ped": SimulatedDevice("ped", axis_count=1),
}
devices["coll"].axes[0] = 0.8  # collective well up
result = run_loop(
    [FlightEngine(profile, constants)],
    CompositeInput(device_map, devices),
    LoggingBackend(Path("forces.jsonl")),
    rate_hz=200,
    watchdog_s=profile.safety.watchdog_s,
    max_ticks=100,
)
print(result)  # LoopResult(ticks=100, stopped_by='max_ticks', ...)
```

`FlightEngine.step(dt, frame)` is pure: give it a `ControlFrame`, get back the
force commands. A force backend is any object implementing the `ForceBackend`
protocol (`wardogs_flight_eng.outputs.protocol`), and an input device any
object implementing `InputDevice` (`wardogs_flight_eng.inputs.protocol`).

## Hardware tuning pass

Do this once the base, collective and pedals are in front of you. It is not a
code task.

1. Before flying, open Moza Cockpit's built-in Hind / UH-1H preset and the
   community AH-6J and R66 presets (Moza Discord `flying-settings-sharing`; see
   `docs/reference/community-ffb-references.md`). Note their spring, damper,
   friction and inertia percentages and seed `feel.*` and `rotor.base_amplitude`
   from them. Set Moza Cockpit to a plain DirectInput / no-telemetry preset
   while Flight Eng runs so the two never fight.
2. Run `wardogs-flight-eng list-devices --live`, record each device's guid and
   which axis and button is which, and fill `device_map` in each profile. Then
   run `wardogs-flight-eng calibrate --profile <your littlebird-miniguns copy>`.
3. Run `wardogs-flight-eng check-device`, then the measured conformance test
   with `WFE_HARDWARE=1 uv run pytest tests/test_sdl_hardware.py` (base powered,
   stick released; `WFE_PITCH_AXIS`, `WFE_ROLL_AXIS`, `WFE_PITCH_INVERT` and
   `WFE_ROLL_INVERT` set the stick's bindings). If `spring_center_moves` is
   false, open an issue titled "dinput8 fallback backend" (the planned fix is a
   `ctypes` binding to `dinput8.dll` behind the same `ForceBackend` interface).
4. Fly each profile and adjust only the `taste` values.
5. Commit the tuned profiles.

## Licence

MIT. See `LICENSE`. Copyright (c) 2026 Skye Stubbins.

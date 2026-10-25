# Wardogs Flight Eng

Force-feedback synthesiser for Wardogs helicopters.

Wardogs sends no force feedback to any joystick. Flight Eng produces it from
the only signal it is allowed to read: your own stick, collective and pedals.
It gives the Lakota and Havoc a force-trim spring around a trim point you set
with a button, the Littlebird a light unboosted stick with a friction clamp,
and all three friction, damping, inertia, a rotor buzz through the grip and
weapon recoil, through a Moza AB9 or any other DirectInput force-feedback
base. It is MIT licensed, Windows only, and Python 3.12+.

> **⚠️ Not yet tested on real hardware.** Every force path in this program
> has been verified only against a simulated SDL layer. The author's Moza AB9,
> collective and pedals are still in shipment, so **no force has ever been
> played on a physical base**. If you run it on yours before the first
> hardware pass is reported here: keep a hand on the stick, keep the shipped
> `force_ceiling` (0.6), start with `check-device` and the conformance test
> described under "Hardware tuning pass", and treat every feel value as a
> placeholder. You are the first test pilot.

## What this does and does not touch

- It reads your own HID devices (your stick, pedals and collective).
- It writes force-feedback effects to your own base.
- It never reads the game process, the screen, memory or the network.
- It installs no drivers and no virtual devices.

## Status

Version 0.2.0.

![CI](https://github.com/owzo/wardogs-flight-eng/actions/workflows/ci.yml/badge.svg)

- **Complete and tested:** the whole engine and the no-hardware path,
  including the two feel modes, the friction, damper and inertia conditions
  and the airspeed estimate (see "Feel modes"). Scripted scenarios drive
  simulated devices through the engine and write a force log and a plot (see
  "Try it without hardware"). The test suite covers the engine, the profile
  and constants loading, the runtime loop and the CLI.
- **Built but not yet run on an AB9:** the SDL haptic path that talks to a
  real base, the friction, damper and inertia effects among it. It was written
  and tested against a fake SDL implementation, and SDL's joystick enumeration
  works in the packaged `.exe`, but no force has yet been played on a Moza
  AB9: the owner's base has not arrived. Treat the first run as a tuning
  session (see "Hardware tuning pass"), keep a hand near the stick, and keep
  the default `force_ceiling` in the shipped profiles. Do not assume the feel
  values are right for your base.
- **Changed from 0.1.0:** the profile format. Profiles copied from 0.1.0 must
  be re-copied; the error says so (see "Feel modes").
- **Not built:** collective or yaw force feedback, a GUI, reading any game
  state, Linux or macOS.

## Install

**Developers:** install [uv](https://docs.astral.sh/uv/), then

```
git clone https://github.com/owzo/wardogs-flight-eng.git
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
download the repository as a ZIP from https://github.com/owzo/wardogs-flight-eng and take the profiles from
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
| `trim_lock` | tap | `force_trim`: the spring centre moves to where the stick is now; `unboosted`: clamps the stick where it is (see "Feel modes"; with `feel.trim_style` `hold` it acts while held instead) |
| `trim_reset` | tap | `force_trim`: the spring centre returns to origin; `unboosted`: releases the clamp |
| `fire` | hold | recoil pulses after the weapon's wind-up (profiles with a pilot weapon) |
| `reload` | tap | silences recoil for the weapon's reload time |
| `rotor_toggle` | tap | spools the rotor buzz down, or back up |
| `profile_cycle` | tap | switches to the next profile given to `run`; forces drop to zero for the switch, the trim and clamp start fresh and the rotor keeps its spool (see "Run") |
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
asks it to create a spring, a moving spring centre, a sine, a constant force,
and a friction, a damper and an inertia condition. Nothing is played, so the
stick does not move. It prints one `yes`/`no` per primitive and one verdict:

- `PASS`: every primitive was accepted.
- `WARN: not accepted: ...` (exit 0): only friction, damper or inertia were
  refused. The line names them. `force_trim` profiles run without them;
  `unboosted` profiles cannot run without friction (see "Feel modes").
- `FAIL: not accepted: ...` (exit 1): the spring, the moving centre, the sine
  or the constant force was refused.

Note that "accepted" means the driver took the request; only flying it, or
`tests/test_sdl_hardware.py` (see the tuning pass), shows the stick actually
moves.

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
`watchdog_s` among them apply to all. If any of them is an `unboosted`
profile and the base reports no friction primitive, `run` refuses to start
(exit 1) and names the profile and the remedy (see "Feel modes").

Every switch hands over the same way, whether or not you flew that profile
before. The incoming profile starts with its trim centre at origin, its clamp
released, its airspeed estimate at 0 and its weapon fresh (no wind-up, no
reload in progress); tap `trim_lock` again to re-trim. The rotor keeps its
spool: the incoming rotor runs at the same fraction of its own operating
speed as the outgoing one, and a rotor spooled down stays down. The `all_off`
latch and which buttons are held carry over.

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
- `forces.html`: a self-contained page (no scripts) with four rows on a
  shared time axis in seconds. The pitch and roll rows show the spring centre
  and the rotor sine magnitude as lines, recoil pulses as ticks above or below
  the zero line (the sign is the push direction), and shake transients as
  short bars whose length is their duration. The pitch gains and roll gains
  rows show the spring, friction, damper and inertia coefficients as lines.
  Any `all_off` is a red band across every row.

The shipped Littlebird is `unboosted`, so with this scenario its spring
centre stays at origin and the trim lock shows instead in the gains rows:
the clamp engages at the lock and releases at the reset. With
`src/wardogs_flight_eng/profiles/lakota.json` (`force_trim`) you should see
the spring centre move to the stick at the trim lock and return at the reset,
under constant friction, damper and inertia.

A second scenario exercises the clamp and the airspeed estimate:

```
wardogs-flight-eng dry-run --profile src/wardogs_flight_eng/profiles/littlebird-miniguns.json --scenario tests/scenarios/littlebird-clamp-cruise.json
```

It lifts at 1 s, pushes the stick forward and holds it from 4 s (the
airspeed estimate rises and the buzz grows), clamps at 10 s, releases at
14 s and returns the stick to centre at 15 s. In the gains rows, friction
rises to `clamp_friction` and the spring falls to 0 over `trim_slew_s` after
the clamp, and both return after the release.

## Moza Cockpit companion settings

If you use a Moza base, Moza Cockpit and Flight Eng must not both drive the
spring. `docs/reference/community-ffb-references.md` lays out the two valid
divisions of labour: **A** (Flight Eng owns spring and trim; Cockpit's
damper, friction and inertia are set low or 0, with its `bacic_spring` and
hardware balancing at 0/off) or **B** (Cockpit owns spring and hardware trim;
Flight Eng profile sets `feel.spring_coefficient` to 0 and supplies damper,
inertia, buzz and recoil).
Pick one, and never run two springs at once: the stick would be pulled to a
point between the two centres and trim lock would break.

Since 0.2.0 Flight Eng also plays friction, damper and inertia (see "Feel
modes"), so under **A** any damper, friction or inertia left in Cockpit acts
alongside Flight Eng's; how the base combines the two has not been measured.
Under **B**,
`spring_coefficient` 0 forces `feel.friction` to 0 too (it may be at most a
quarter of the spring), and Flight Eng supplies buzz, recoil, damper and
inertia, plus the clamp's friction in an `unboosted` profile.

## What the forces are and where the numbers come from

Five effects, per airframe, all set in the profile JSON:

1. **Feel spring.** A centring spring on pitch and roll (the roll spring is
   `spring_coefficient * roll_scale`), with a deadband. Its centre is the
   trim point in `force_trim` mode and the mechanical centre in `unboosted`
   mode (see "Feel modes").
2. **Friction, damper and inertia.** Three condition effects on pitch and
   roll. Friction (`feel.friction`) resists any motion with a constant
   force; it is the breakout, the force needed to start the stick moving.
   The damper (`feel.damper`) resists speed and the inertia (`feel.inertia`)
   resists acceleration. Roll friction is `friction * roll_scale`; the damper
   and inertia are the same on both axes.
3. **Trim.** `trim_lock` and `trim_reset` move the spring centre
   (`force_trim`) or engage and release a friction clamp (`unboosted`), in
   both cases slewed over `trim_slew_s` so the force never steps. Nothing
   else ever moves the spring centre: the stick never wanders.
4. **Rotor buzz.** A sine at the airframe's main-rotor frequency on both axes,
   scaled by the collective position, a little by cyclic deflection and by
   the airspeed estimate (`1 + rotor.airspeed_factor * airspeed`), with a
   spool-up when the program starts. `rotor.min_amplitude` (optional, `0..1`,
   default `0`) is a floor for bases that cannot render a very weak sine: a
   buzz strictly below it is sent as zero, one at or above it plays as is.
5. **Weapon recoil.** While `fire` is held, after the weapon's wind-up, one
   force pulse per round at the weapon's fire rate, stepping through the game's
   recoil pattern (or a fixed rearward kick for rockets), plus the weapon's
   shake. One pilot weapon per profile; the `havoc` profile has none.

### Feel modes

`feel.mode` picks how the stick feels. The shapes (breakout a fraction of
the spring, roll lighter than pitch, a damped stick that does not ring)
follow `docs/reference/real-cyclic-feel-references.md`, which summarises the
FAA Helicopter Flying Handbook, ADS-33E-PRF and a NASA force-feel study. Only
ratios and shapes are taken from it, never a number. The values in `feel`,
the buzz gains and the estimator's `forward_threshold` and `tau_s` are owner
taste, listed in each profile's `taste` field.

**`force_trim`** (the Lakota and Havoc, which copy hydraulically boosted
helicopters with force trim). The spring pulls toward a trim anchor that
`trim_lock` moves to the stick and `trim_reset` returns to origin. Friction
is constant and acts as the breakout. Damper and inertia are constant.

**`unboosted`** (the Littlebird, which copies a light helicopter whose stick
is linked straight to the rotor). A weak spring pulls toward the mechanical
centre, against light friction, so a released stick eases back toward
centre. `trim_lock` engages a clamp: over `trim_slew_s` the spring fades to
0 while friction rises to `feel.clamp_friction`, so the stick holds wherever
you leave it and re-holds if you push it somewhere else. `trim_reset`
releases the clamp the same way. A lock while clamped, or a reset while
free, does nothing. Damper and inertia are constant.

**Trim styles.** `feel.trim_style` (optional, default `tap`) picks how the
`trim_lock` button acts. `tap` is the 0.2.0 behaviour described above: each
press locks. In `hold`, the button acts while it is held. In `force_trim`
mode, holding it lets the spring go slack (it fades to 0 over
`trim_slew_s`; the anchor stays put), and letting go anchors the spring
where the stick is at that instant and stiffens it back over `trim_slew_s`;
a release part-way through picks up from where the fade had got to.
`trim_reset` still returns the anchor to origin. In `unboosted` mode the
clamp is momentary: engaged while the button is held, released when you let
go, each over `trim_slew_s`; `trim_reset` does nothing, since nothing stays
latched. A `trim_lock` held through a profile switch is ignored until you
release it once, so the incoming profile never starts slack or clamped. The
shipped profiles use `tap`.

**The stopping band.** Friction has no centre: it resists motion
everywhere. A released stick therefore stops wherever the spring's pull has
fallen to the friction level, which is anywhere within
`friction / spring_coefficient` of travel from the spring's centre (the
mechanical centre, or the trim anchor). The loader refuses a profile whose
`feel.friction` is more than `spring_coefficient / 4`, so the band is never
wider than a quarter of the travel; the shipped profiles keep it to a fifth
or less. That is why the Littlebird's free friction is small and the clamp
supplies the hold. Raising `feel.damper` never narrows the band; it only
stops the stick overshooting.

**Rules the loader enforces.** `feel.mode` is `force_trim` or `unboosted`.
`feel.clamp_friction` is required in `unboosted` mode, rejected in
`force_trim` mode, and must be at least `feel.friction`; it is exempt from
the quarter rule, because a fully clamped stick has no spring. `friction`,
`clamp_friction`, `damper`, `inertia` and the other gains must each be at
or below `safety.force_ceiling`.

**The airspeed estimate.** Real light-helicopter sticks carry more rotor in
the hand at speed, so the rotor buzz grows with an airspeed estimate (item 4
above). The Littlebird ships a large `rotor.airspeed_factor`; the boosted
Lakota and Havoc, whose real counterparts pass little of this to the hand,
ship a small one. The profile's `estimator` block says where the estimate comes from:

```json
"estimator": {"kind": "input", "forward_threshold": 0.15, "tau_s": 4.0}
```

Today the only kind is `input`: sustained forward stick. Forward stick
beyond `forward_threshold` sets a target airspeed between 0 and 1, and the
estimate follows it with the time constant `tau_s` in seconds (0 follows at
once); stick at or behind `forward_threshold`, aft stick included, brings it
back toward 0. The `kind` field is where a future game-state feed would plug
in. Nothing reads the game: the estimate comes only from your own stick.

**When the base lacks a condition.** At start, `run` asks the base which of
friction, damper and inertia it supports. A missing damper or inertia (or,
in a `force_trim` profile, a missing friction) is dropped and logged once as
a WARNING; the rest of the feel runs without it. A base without friction,
or one that reports no capabilities at all, cannot hold an `unboosted`
clamp, so when any loaded profile is `unboosted`, `run` refuses the whole
run on it (exit 1) and says to set that profile's `feel.mode` to
`force_trim` or use a base with friction. `check-device` shows the same
support up front (see "First run").

**Profiles from 0.1.0.** The profile format changed in 0.2.0: `feel.mode`,
`feel.friction`, `feel.damper`, `feel.inertia`, `rotor.airspeed_factor` and
the `estimator` block are required, with no defaults. Profiles copied from
0.1.0 must be re-copied; the error says so. It lists the missing fields and
tells you to copy the shipped profile for that airframe, fill `device_map`
again and re-run `calibrate`.

### Where the numbers come from

**Game data with provenance.** Rotor speeds, fire rates, wind-ups, reload times
and shake envelopes are game facts and live only in
`src/wardogs_flight_eng/data/wardogs_heli_constants.json`, with the Steam build
id, extraction date and asset names recorded. Stiffnesses, amplitudes and
ceilings are the owner's taste, listed in each profile's `taste` field, and are
never presented as game data. No game value is guessed from real aircraft.

```
wardogs-flight-eng show-constants
```

prints every airframe and weapon constant with its build. A value the game
files do not give is `null` in the data and is displayed as
`UNKNOWN - WARDOGS GAME VALUE REQUIRED`. Where the engine must have a number
to run, it uses a stated placeholder, which is **not game data for the
airframe or weapon it is applied to**. There are exactly two:

- **Spool-down rate, 850 rpm/s.** This is the Littlebird's game value
  (`DA_ROT_03_Engine`), not game data for the airframe it is applied to. The
  Lakota and Havoc have no known value (their `spool_down_rpm_per_s` shows as
  UNKNOWN), so on them `rotor_toggle` spools the rotor buzz down at the
  Littlebird's rate until the real value is found; an INFO log line naming
  the airframe says so each time such a profile is loaded. A profile's
  `rotor.spool_down_rpm_per_s`, if you set it, overrides this.
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
`FlightEngine(profile, constants, estimator=...)` takes any object
implementing `StateEstimator` (`wardogs_flight_eng.engine.flight_state`) in
place of the one the profile's `estimator` block builds: this is the seam a
future game-state feed, or a test stub, plugs into. Its `step(dt, frame,
deflection)` returns the tick's `FlightState` (airspeed, collective and
deflection, each 0..1) and `restart()` returns it to rest on a profile
switch.

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
   Then A/B the persistent-effect refresh. By default the backend uploads a
   spring or rotor sine only when it changes and re-runs it every half
   effect length (about twice a second), because on Windows every update or
   run restarts a playing effect. `SdlHapticBackend(...,
   refresh_every_tick=True)` restores the earlier behaviour: update and re-run
   all four persistent effects every tick; from the command line that is
   `run --refresh-every-tick`. Run the conformance test once
   as above and once with `WFE_REFRESH_EVERY_TICK=1` added, and compare the
   spring hold and the logged sine range: the buzz should be smooth in both,
   and if only the per-tick mode feels right, report it in an issue.
4. Fly each profile and adjust only the `taste` values. While `run` is
   active, SDL holds the base's DirectInput device exclusively for force
   feedback: the game still reads the stick, but no other program can play
   force effects on the base until `run` exits.
5. Unplug the base mid-run: expect `stopped: device_lost`, exit code 2 and no
   residual force when it is plugged back in. If it still pushes,
   power-cycle it and open an issue.
6. **Clamp hold** (`unboosted` profiles). Fly with the stick off centre,
   tap `trim_lock` to clamp, and let go. Over 10 s the stick must not creep:
   ADS-33E-PRF §3.6.6 asks for no objectionable slippage of the trim
   position. If it creeps, raise `feel.clamp_friction` until it holds,
   keeping it at or below `safety.force_ceiling`.
7. **Release settle.** Tap `trim_reset` (in an `unboosted` profile this
   releases the clamp) and let go. The stick must come back to within the
   stopping band, `friction / spring_coefficient` of travel from the centre,
   and stop there without overshoot (see "Feel modes"). If it stops short,
   lower `feel.friction` or raise `feel.spring_coefficient`. If it
   overshoots or oscillates, raise `feel.damper`.
8. Commit the tuned profiles.

## Releasing

Tag the release commit `vX.Y.Z` and push the tag. The `build-exe` workflow
runs on a Windows runner, builds `wardogs-flight-eng.exe` with PyInstaller and
uploads it with a `SHA256SUMS` file as the `wardogs-flight-eng-vX.Y.Z`
artifact. Download that artifact from the workflow run, then attach the exe
and `SHA256SUMS` to the GitHub release.

## Licence

MIT. See `LICENSE`. Copyright (c) 2026 Skye Stubbins.

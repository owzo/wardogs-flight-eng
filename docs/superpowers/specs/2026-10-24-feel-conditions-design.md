# Feel conditions: breakout, friction, damper, inertia and the unboosted Littlebird

Status: draft for owner approval, 2026-10-24. Builds on
`2026-10-22-wardogs-flight-eng-design.md` (v0.1.0) and is grounded in
`docs/reference/real-cyclic-feel-references.md` (FAA-H-8083-21B,
ADS-33E-PRF §3.6 and Tables X–XIII, NASA NTRS 20130013798).

## Intent

v0.1.0 gives every airframe the same thing: a force-trim spring on a
tap-lock anchor, rotor buzz and recoil. A real cyclic also has breakout,
friction, damping and inertia, and the three Wardogs airframes copy two
different real control systems. The owner's decision (2026-10-24):

- **Littlebird feels unboosted**, like the MD 500 / MH-6 it is modelled on:
  weak centring, friction, more rotor in the hand, and a trim button that
  acts as a friction clamp. Clamped, the stick stays where it is and holds
  the trim. Unclamped, it returns to centre.
- **Lakota and Havoc stay boosted with force trim**, as in v0.1.0, gaining
  breakout, damper and inertia around the anchor.
- **Mimic the real thing as closely as the inputs allow**, and leave a seam
  so a live game-state feed, if one ever exists, plugs straight into the
  same place the input-derived estimates occupy today.

## Goals

1. Two feel modes selectable per profile: `force_trim` and `unboosted`.
2. Three new persistent force conditions on pitch and roll: friction,
   damper, inertia, driven from the profile and the engine state.
3. An airspeed estimate the engine consumes through a `FlightState` value,
   produced today by an input-only estimator (sustained forward stick),
   replaceable later by a telemetry-fed one without touching the engine.
4. Rotor texture that grows with the airspeed estimate (real unboosted
   cyclics load up with speed), scaled per profile.
5. Graceful behaviour on a base that lacks a condition primitive: the
   program says which ones the device refused and runs without them,
   except where the missing primitive *is* the trim mechanism.
6. The same safety path for every new force: profile gains ≤ force ceiling,
   per-command clamp, watchdog, ALL_OFF, finite-length persistent effects,
   zeroed on every exit path.
7. Dry-run coverage (scenario, force log, plot) for both modes before any
   hardware exists.

## Non-goals

- A telemetry source itself. Only the seam ships; no adapter, no file or
  socket reader, no HUD reader.
- Yaw or collective forces; the pedals and collective remain inputs only.
- A hold-to-release trim variant (real force-trim-release buttons are held,
  not tapped). Noted as a possible later profile option; not built now.
- Moza SDK backend, Cockpit preset emitter, CI, blade-count extraction.
- Any change to the game-data rule, the weapon model or the recoil model.

## Anti-goals

- Reading game memory, screen, network or process state to get airspeed.
  The estimate comes from the user's own controls; a future feed must be
  something the game or its publisher explicitly offers.
- Two springs at once (Flight Eng + Moza Cockpit) or a spring faked in
  place of a missing friction primitive.
- A force that appears before the device has been confirmed, or that
  survives an exit path.
- Transcribing ADS-33 pounds into profile numbers. Ratios and shapes only.

## Constraints

- Pure engine: `engine/` imports no SDL, inputs, outputs or runtime. The
  estimator lives in `engine/` because it is arithmetic on frames; a
  telemetry adapter would live in `inputs/` and produce the same value.
- Every new profile gain is `0..1`, finite, and ≤ `safety.force_ceiling`
  (extend `_check_gains_within_ceiling`).
- Persistent conditions follow the spring: finite length
  `max(1.0, 2 × min watchdog)`, change-detection upload, half-life re-run,
  silenced to zero coefficients in `all_off`.
- Files under 200 lines, functions under 50; `sdl_effects.py` (155 lines)
  and `synth.py` (199) must be split rather than grown.
- Sign convention: `ControlFrame.pitch` +1 is forward stick, −1 is aft (the
  rocket kick `(0, −1)` is a rearward push). The builder confirms this
  against `weapon.py` before using it in the estimator.

## The model (decided)

### Flight state seam

`engine/flight_state.py`:

- `FlightState` (frozen dataclass): `airspeed: float` (0..1, 0 = hover,
  1 = fast cruise), `collective: float` (0..1), `deflection: float`
  (0..1, cyclic distance from the current spring centre). Fields are
  estimates or inputs; the dataclass carries no provenance.
- `StateEstimator` (Protocol): `step(dt, frame, deflection) -> FlightState`.
- `InputEstimator`: the only implementation now. Airspeed is a first-order
  low-pass of forward stick beyond a threshold:
  `target = max(0, (pitch − forward_threshold) / (1 − forward_threshold))`,
  `airspeed += (target − airspeed) × (1 − exp(−dt / tau_s))`, clamped 0..1.
  Aft stick drives the target to 0 (decelerating). `tau_s = 0` snaps.
  Profile block `estimator: {"kind": "input", "forward_threshold": 0.15,
  "tau_s": 4.0}`; `kind` is a discriminator reserved for future estimators.
- `FlightEngine.__init__` takes the estimator built from the profile; a
  test may pass a stub. Nothing in the engine reads `frame.pitch` for
  airspeed except through the estimator.

### Feel modes

`feel.mode` is `"force_trim"` (Lakota, Havoc) or `"unboosted"` (Littlebird).
Both modes emit, every tick, per axis: spring, friction, damper, inertia,
then the buzz sines and any recoil. Roll static forces (spring, friction)
are multiplied by `roll_scale`; damper and inertia are the same on both
axes (stick dynamics are isotropic; ADS-33 only separates the static
forces by axis). My call.

**force_trim** (unchanged trim behaviour):

- Spring about the slewed trim anchor, as v0.1.0.
- Friction `feel.friction` constant: this is the ADS-33 "breakout" (force
  to start moving from trim).
- Damper `feel.damper`, inertia `feel.inertia` constant.

**Friction against a spring: the stopping band (my call, from the builder
check).** A friction condition has no centre: it resists motion everywhere,
and on a base that holds a stationary stick it stops the stick wherever the
spring force has fallen to the friction level, i.e. anywhere within
`friction / spring_coefficient` of the centre or anchor. That band is real
(a physical cyclic stops short of centre too) and is accepted, but bounded:
both modes validate `friction ≤ spring_coefficient / 4`, so a released
stick always ends within a quarter of the travel of its centre, and the
shipped values keep it near a fifth or less. The band is also why the
Littlebird's free-mode friction is small: the owner wants an unclamped
stick to return to centre, so free mode keeps only enough friction for
grit, and the clamp supplies the hold. Raising `damper` never shrinks the
band; it only removes overshoot (see the README tuning steps).

**unboosted**:

- The spring centre is always the mechanical centre `(0, 0)`.
  `TRIM_LOCK` and `TRIM_RESET` keep their names and buttons but drive a
  **clamp**: lock = clamp on, reset = clamp off. Lock while clamped and
  reset while free are no-ops.
- A blend `c` slews linearly from 0 to 1 over `feel.trim_slew_s` when
  clamping and back when releasing (reusing the `TrimState` slew shape, so
  ADS-33 §3.6.6 "no stick jump" holds in both directions).
- Spring coefficient `= spring_coefficient × (1 − c)`; friction
  `= friction + (clamp_friction − friction) × c`. Fully clamped: no spring,
  heavy friction, the stick holds wherever it is left and re-holds if
  pushed through. Fully free: weak spring beats light friction and the
  stick eases back to centre (owner, 2026-10-24).
- Validation: `clamp_friction ≥ friction`, and the shared
  `friction ≤ spring_coefficient / 4` rule above (free mode must come
  back close to centre). `clamp_friction` is exempt: when clamped the
  spring is 0, so the clamp holds everywhere by design.
- Damper and inertia constant, as in force_trim.
- Buzz deflection is measured from the mechanical centre.

### Rotor texture with airspeed

`RotorModel.amplitude` gains the factor `(1 + rotor.airspeed_factor ×
state.airspeed)`, clamped to 0..1 as before. Lakota and Havoc ship with a
small factor (boosted cyclics pass little of this on), the Littlebird a
large one. The spool fraction, collective and deflection terms stay.

### Profile switch (settles open decision (a) from the v0.1.0 review)

On `PROFILE_CYCLE` the incoming engine takes a **handoff** from the
outgoing one (`FlightEngine.take_over(outgoing)`), precisely:

- trim anchor to centre, clamp off, blend 0, airspeed estimate 0 (a stale
  clamp or anchor from minutes ago is a surprise force; a reset is not);
- rotor: the incoming rotor's RPM is set to the outgoing rotor's spool
  fraction × the incoming airframe's operating RPM, and its running flag
  copied, so the rotor neither stops nor restarts across a switch;
- weapon: reset to a fresh weapon (no wind-up, no reload window). Inactive
  engines are never stepped, so a frozen reload timer would be wrong
  either way, and the two profiles' weapons are different weapons;
- the ALL_OFF latch and `prime_buttons` carry over as today.

My call; the owner may veto.

### Commands and backend

New frozen commands in `engine/commands.py`: `FrictionCommand`,
`DamperCommand`, `InertiaCommand`, each `(axis, coefficient)` with
`coefficient` 0..1. The `Command` union grows; `ClampedBackend` limits the
coefficient to `[0, ceiling]` with the same warn-once behaviour;
`LoggingBackend` writes kinds `friction`, `damper`, `inertia`.

SDL: `SDL_HAPTIC_FRICTION`, `SDL_HAPTIC_DAMPER`, `SDL_HAPTIC_INERTIA`
condition effects, single-axis like the spring (coefficient on the haptic
axis, saturation max, other axes zero, centre 0). Builders live in a new
`outputs/sdl_conditions.py`; `spring_effect` moves there too. They are
persistent effects keyed `("friction", axis)` etc. `silenced()` already
zeroes condition coefficients, so `all_off` needs no change beyond the new
keys being held.

Capability: `SdlHapticBackend` reads `SDL_HapticQuery` once at construction
and records which of the three condition types the base supports. An
unsupported kind is logged once at WARNING, naming the type and that the
feel runs without it, and its commands are dropped. **Exception:** a
profile in `unboosted` mode whose device lacks `SDL_HAPTIC_FRICTION` is a
configuration error at `run` start (exit 1) with a message that names the
profile, the missing primitive and the remedy (switch the profile to
`force_trim`), because without friction the clamp holds nothing and the
spring-off stick would be free. `check-device` reports friction, damper
and inertia alongside spring, sine and constant.

### Profile schema additions

```
"feel": {
  "mode": "unboosted",            // or "force_trim"
  "spring_coefficient": 0.12,     // existing; weak in unboosted mode
  "roll_scale": 0.5,              // existing; applies to spring and friction
  "deadband": 0.02,               // existing
  "trim_slew_s": 0.3,             // existing; also the clamp blend time
  "friction": 0.02,               // baseline friction / breakout; <= spring / 4
  "clamp_friction": 0.5,          // unboosted only; must be >= friction
  "damper": 0.15,
  "inertia": 0.05
},
"rotor": { ..., "airspeed_factor": 0.6 },
"estimator": { "kind": "input", "forward_threshold": 0.15, "tau_s": 4.0 }
```

`clamp_friction` is required in `unboosted` mode and rejected in
`force_trim` mode (a clear error either way). All of `friction`,
`clamp_friction`, `damper`, `inertia` join the ≤ ceiling check and the
`taste` list.

**Existing user copies (my call).** `feel.mode`, `friction`, `damper`,
`inertia`, `rotor.airspeed_factor` and `estimator` are **required**, with
no defaults: a v0.1.0 profile copy fails to load with an error that lists
the missing fields and says to re-copy the shipped profile of that
airframe and re-run `calibrate`. Defaults would silently leave a user's
Littlebird on the old force-trim feel, the opposite of the decision. No
migration command: v0.1.0 is a two-day-old pre-release with no hardware
users. The release that ships this is 0.2.0 and its notes name the
profile format change.

Shipped starting values (owner taste, placeholders until the hardware pass;
ratios follow the reference: breakout about a fifth of the gradient, roll
lighter than pitch, Havoc heaviest, damping high):

| Profile | mode | spring | friction | clamp_friction | damper | inertia | airspeed_factor |
|---------|------|--------|----------|----------------|--------|---------|-----------------|
| littlebird-* | unboosted | 0.12 | 0.02 | 0.50 | 0.15 | 0.05 | 0.6 |
| lakota | force_trim | 0.50 | 0.10 | — | 0.25 | 0.08 | 0.15 |
| havoc | force_trim | 0.60 | 0.12 | — | 0.30 | 0.10 | 0.15 |

### Dry run and plot

- New scenario `tests/scenarios/littlebird-clamp-cruise.json`: lift, push
  forward and hold (airspeed estimate rises, buzz grows), clamp, hold
  position, release, return the stick to centre. The force log must show
  friction rising to `clamp_friction` and the spring falling to 0 over the
  slew, then the reverse.
- The plot gains a coefficients row (spring, friction, damper, inertia per
  axis) so clamp transitions can be reviewed by eye. Layout is the
  builder's.
- `dry-run` output for the Lakota profile must show constant friction,
  damper and inertia with the spring centre moving on lock/reset as before.

### README and hardware pass

- README: a "Feel modes" section (what the two modes do, the clamp
  semantics, the estimator block and its future), the capability warning
  wording, and two new tuning-pass steps: **clamp hold** (clamp, let go,
  the stick must not creep more than a stated fraction of travel in 10 s;
  raise `clamp_friction` until it holds) and **release settle** (release
  clamp or tap reset: the stick must come back to within the stopping
  band, `friction / spring_coefficient` of travel, and stop without
  overshoot. Stops short: lower `friction` or raise `spring_coefficient`.
  Overshoots or oscillates: raise `damper`).
- `docs/reference/real-cyclic-feel-references.md` is cited from the
  profile comments and the README rather than copied.

## Safety (restated for the new forces)

- Every coefficient goes through `ClampedBackend`; non-finite → 0 with a
  WARNING.
- Conditions are persistent with the finite length and half-life re-run
  of the spring, so a frozen loop times them out.
- `all_off` silences friction, damper and inertia along with spring and
  sines; teardown order and Ctrl+C behaviour are unchanged.
- The clamp blend and airspeed estimate are engine state advanced only by
  `step`; a watchdog tick (`[AllOffCommand()]`) advances neither.

## Left to the builder

- Exact split of `synth.py` (suggested: `synth.py` orchestrates; a
  `feel.py` holds the mode logic and blend; `flight_state.py` the
  estimator) and of `sdl_effects.py` into `sdl_conditions.py`.
- The plot row layout and legend entries.
- Whether `InputEstimator` also feeds `deflection` and `collective` into
  `FlightState` from the frame (it should; they are inputs, not estimates).
- Logging text for the capability warnings and the unboosted/friction
  refusal; the `check-device` report format.
- Test fixtures for a fake SDL that reports partial condition support.

## Acceptance

1. `pytest`, `ruff`, `ruff format --check`, `mypy --strict` green; layering
   test still passes with the estimator in `engine/`.
2. Engine tests: both modes emit the four conditions per axis; unboosted
   clamp blend reaches `clamp_friction` and spring 0 exactly at
   `trim_slew_s`; release reverses; lock-while-clamped and
   reset-while-free are no-ops; airspeed step response reaches 63 % of
   target at `tau_s`; aft stick decays the estimate; buzz grows by
   `airspeed_factor`; profile handoff resets anchor, clamp, airspeed and
   weapon and carries the rotor spool fraction.
3. Profile tests: mode validation, `clamp_friction` presence rules,
   `friction ≤ spring_coefficient / 4` in both modes, gains vs ceiling,
   all four shipped profiles load, a v0.1.0-shaped profile fails with the
   migration message.
4. Backend tests: condition effects built with the right SDL type, axis
   and sign; persistent keys held and silenced; unsupported kinds dropped
   with one warning; unboosted + no friction refused at `run`.
5. `dry-run` on `littlebird-miniguns` with the new scenario and on `lakota`
   with the existing scenario produce logs and plots showing the behaviour
   above.
6. `check-device` prints friction, damper and inertia support.
7. README updated as above; nothing claims a hardware result.

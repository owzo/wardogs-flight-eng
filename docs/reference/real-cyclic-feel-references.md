# What a real helicopter cyclic does — sourced reference for the feel-conditions design

Retrieved 2026-10-24. This file grounds the damper / friction / inertia /
breakout design (the "feel conditions" that follow v0.1.0). It is **not game
data**: nothing here may be used to fill a Wardogs value. It tells us what a
physical cyclic feels like so the synthesised feel can imitate a real one,
within the device's normalised force range.

Every number is a **ratio or a shape** for us, never an absolute: the AB9 is
driven in normalised units (0–1 of the base's torque), and the Moza Cockpit
`overall_strength` / `bacic_max_torque` scale it again. Keep the relationships
(breakout : gradient : limit, pitch : roll, hover : cruise); do not transcribe
pounds.

## Sources

| ID | Document | Where it was read | Status |
|----|----------|-------------------|--------|
| HFH | FAA Helicopter Flying Handbook, FAA-H-8083-21B, ch. 3 "Helicopter Flight Controls" and ch. 4 "Helicopter Components, Sections, and Systems" | faa.gov per-chapter PDFs (`hfh_ch03.pdf`, `hfh_ch04.pdf`), text extracted | primary, verified |
| ADS-33 | ADS-33E-PRF, *Handling Qualities Requirements for Military Rotorcraft*, US Army AMCOM, 2000: §3.6 Controller characteristics, Tables X–XIII (doc pp. 21–22, 69–70) | scanned PDF, pages rendered and read by eye, tables OCR'd and checked against the image | primary, verified |
| NTRS | Malpica & Lusardi, *Analysis of Handling Qualities Design Criteria for Active Inceptor Force-Feel Characteristics*, NASA Ames / AMRDEC, NTRS 20130013798 (AHS Forum 2013 abstract) | NTRS PDF, text extracted | primary, verified |
| WEB | Pilot forums, type write-ups, manufacturer pages on MD500/OH-6, Bell 206/UH-1, Mi-8/17, Apache force-feel | web search during the earlier session | secondary, **unverified** — treat as colour, not fact |

ADS-33E-PRF and the FAA handbook are US Government works (public domain); the
NASA abstract is a US Government work. Short quotations below are fine in an
MIT repository.

## 1. The two kinds of real cyclic

**Unboosted (light helicopters: Robinson R22/R44, MD500/OH-6 family, Bell 47).**
Pushrods run straight from the stick to the swashplate. The pilot feels rotor
feedback: the one-per-rev and the control loads, which change with airspeed
and collective. There is no centring spring worth the name; a released stick
drifts with the rotor loads, so the pilot never lets go. WEB sources describe
the MD500/OH-6 as having electric trim motors that bias the stick against
those loads, plus adjustable friction; this is unverified here.

**Hydraulically boosted with force trim (Bell 206/UH-1, UH-60, EC145/UH-72
Lakota, AH-64, Mi-8/17 family).** Servo actuators between the stick and the
swashplate carry the rotor loads, so the hand feels *nothing* from the rotor.
HFH ch. 4, "Hydraulics": the servo "provides an assisting force to move the
respective flight control, thus reducing the force the pilot must provide";
with hydraulics failed "the control forces are very heavy." Everything the
pilot feels is artificial: a **force trim** system. HFH ch. 4, "Force Trim":

> The system uses a magnetic clutch and springs to hold the cyclic control in
> the position where it was released. … the pilot can override the system by
> disengaging the system through the use of a force trim release button or,
> with greater resistance, can physically manipulate the controls.

So in a boosted helicopter the stick (a) is held wherever it was last
released, (b) has a spring gradient around *that* point, not around the
mechanical centre, (c) can be moved against the spring, and (d) goes slack
the instant the force-trim-release button is pressed, re-anchoring where the
button is let go. This is close to the tap-to-lock / tap-to-reset trim the
owner specified for Flight Eng, with one difference: real force trim is
*hold-to-release* (button down = slack, button up = re-anchor); Flight Eng's
is tap-to-lock. Both patterns exist in service (hold-and-release on the
Apache and Lakota; some types add a four-way "beep" trim). Keep the owner's
tap design; note the hold-to-release variant as a possible profile option.

## 2. What the stick does when released

| Situation | Unboosted (R22, OH-6) | Boosted + force trim (Lakota, Havoc class) |
|-----------|-----------------------|--------------------------------------------|
| Hover, hand off | Stick wanders with rotor loads; helicopter diverges within seconds. Pilots do not let go. | Stick stays where released (mag brake). Helicopter still diverges slowly (hover is unstable), but the stick itself does not move. |
| Cruise, hand off | Rotor loads grow with airspeed; stick wants to move, needs trim motor or friction to hold. | Stick stays put; aircraft holds attitude if trimmed. |
| Push forward from hover to cruise, release | Stick does *not* return to the hover position. It sits wherever drag and friction leave it. | With trim engaged: spring pulls it **back toward the hover trim point**, which is wrong for cruise, so the pilot presses force-trim-release while moving, lets go at the new position, and the spring re-centres there. |
| Trim release pressed | n/a | All spring force vanishes immediately; stick is free, with only friction and inertia. |

ADS-33 §3.6.1.1 makes "positive centering in flight at any normal trim
setting" a requirement, and §3.6.6 requires that trimming to zero force "shall
not produce an objectionable change in rotorcraft attitude" and "no
objectionable stick jump, trim rates, or slippage in the trim control
position." Translation for Flight Eng: when trim locks or resets, the force
step must be slewed (`feel.trim_slew_s` already does this), and the anchor
must not creep.

The game has no rotor-load signal we may read, so an "unboosted" feel can
only be imitated as static texture, never as true aero feedback.

## 3. ADS-33E-PRF controller characteristics (faithful summary)

§3.6.1.1 **Centering and breakout forces.** Pitch, roll and yaw controls shall
exhibit positive centering at any normal trim setting. "Breakout forces,
including friction, preload, etc., refer to the cockpit control force
required to start movement of the control surface in flight." Limits in
Tables X (hover / low speed) and XI (forward flight). The change in breakout
with speed shall not be objectionable.

§3.6.1.2 **Force gradients.** Within Table XII throughout the travel. "The
force produced by a one inch travel from trim by the gradient chosen shall
not be less than the breakout force." Local gradient shall not change by more
than 50 % in one inch of travel. Collective preferably zero gradient.

§3.6.1.3 **Limit control forces.** Max forces for any MTE manoeuvre without
retrimming shall not exceed Table XIII.

§3.6.4 **Free play** (stick motion that moves nothing) "shall not be
objectionable." §3.6.5 **Control harmony**: forces, displacements and
sensitivities of pitch, roll, yaw, collective "shall be compatible."
§3.6.7 **Dynamic coupling**: "there shall be no lightly damped, high
frequency oscillations that cease when the pilot releases the controller."

### Table X — allowable breakout forces, pounds, hover and low speed

| Control | Level 1 min/max | Level 2 min/max | Level 3 max |
|---------|-----------------|-----------------|-------------|
| Pitch (centerstick) | 0.5 / 1.5 | 0.5 / 3.0 | 6.0 |
| Roll (centerstick) | 0.5 / 1.5 | 0.5 / 2.0 | 4.0 |
| Yaw (pedals) | 2.0 / 7.0 | 1.0 / 7.0 | 14.0 |
| Collective | 1.0 / 3.0 | 0.75 / 4.5 | 6.0 |

### Table XI — allowable breakout forces, pounds, forward flight (Levels 1–2; Level 3 may double the max)

| Control | min | max |
|---------|-----|-----|
| Pitch | 0.5 | 5.0 |
| Roll | 0.5 | 4.0 |
| Yaw | 2.0 | 14.0 |

### Table XII — allowable control force gradients, pounds per inch

| Control | Level 1 min / max | Level 2 min / max |
|---------|-------------------|-------------------|
| Pitch | 0.5 / 3.0 | 0.5 / 5.0 |
| Roll | 0.5 / 2.5 | 0.5 / 5.0 |
| Yaw | 3.0 / 10.0 | 2.0 / 20.0 |

### Table XIII — limit cockpit control forces, pounds

| Control | Hover L1 / L2 / L3 | Forward flight L1 / L2 / L3 |
|---------|--------------------|-----------------------------|
| Pitch | 15 / 20 / 40 | 30 / 35 / 40 |
| Roll | 10 / 15 / 20 | 15 / 20 / 25 |
| Yaw | 30 / 40 / 80 | 75 / 100 / 125 |
| Collective | 10 | 10 |

## 4. Dynamic feel: natural frequency and damping (NTRS)

The NASA/Army abstract summarises the flight-test literature on *stick
dynamics* (what a damper and inertia condition actually set):

- Conventional helicopters: feel is "set based on the characteristics of the
  mechanical components in the control system (mass, springs, friction
  dampers, etc.)" and "typically remain[s] constant over the entire flight
  envelope, with perhaps a trim release to minimize control forces while
  maneuvering."
- Earlier CH-47B work proposed boundaries on cyclic natural frequency and
  inertia "with the stipulation of a lower damping ratio limit of 0.3."
- The RASCAL JUH-60A / ACT-FHS EC-135 flight tests used **gradient 0.75 lb/in,
  breakout 1 lb**, and centre-stick configurations of natural frequency
  **7–23 rad/s** with damping ratio **0.7–1.5**. Pilots showed "a clear
  preference for a high damping ratio and natural frequency of the center
  stick"; case B (23 rad/s, ζ 1.5) was liked, case D (7 rad/s, ζ 0.7)
  disliked in the Hover MTE. Side-sticks were less damping-sensitive.
- A ground study found little benefit from damping variation once the
  natural frequency exceeded 17 rad/s and the damping ratio 2.0.

For us: a cyclic should feel **over-damped and stiff in its own dynamics**
(no ringing after a sharp input, §3.6.7 again), with the low-frequency
softness coming from the gradient, not from the stick wobbling.

## 5. Per-airframe real-world regime (for the owner's decision)

| Wardogs airframe | Real counterpart | Real cyclic regime |
|------------------|------------------|--------------------|
| Littlebird | MD 500 / MH-6 (OH-6 family) | **Unboosted**: direct pushrods, rotor feedback in the hand, friction, no force-trim mag brake (WEB: electric trim motors on some; unverified) |
| Lakota | EC145 / UH-72A | **Boosted**, dual hydraulics, force trim with release, SAS |
| Havoc | Mi-28 | **Boosted**, hydraulic boosters; Mil-pattern feel springs + electromagnetic trim brakes (WEB: Mi-8/17 pattern; unverified for Mi-28) |

Flight Eng v0.1.0 gives all three a force-trim style tap-lock spring. If the
Littlebird is to feel unboosted, its profile would carry **low or zero spring
gradient, higher friction, and more rotor texture**, with the trim button
acting as a friction clamp rather than a spring anchor. That is a design
choice, not a data fact, and belongs in the feel-conditions spec.

## 6. Mapping to Flight Eng knobs

| Real-world quantity | ADS-33 / NTRS shape | Flight Eng home |
|---------------------|---------------------|-----------------|
| Breakout (friction + preload) | L1 pitch and roll 0.5–1.5 lb hover; force at 1 in of travel ≥ breakout | new `feel.breakout` (constant-magnitude force opposing motion near the anchor) and/or an SDL friction condition; must be ≤ spring force at a modest deflection |
| Gradient | L1 pitch 0.5–3.0, roll 0.5–2.5 lb/in; roll ≤ pitch | existing `feel.spring_coefficient` and `roll_scale` (roll < 1.0 has a doctrinal basis) |
| Limit force | hover pitch 15 lb, roll 10 lb; cruise 30 / 15 | `safety.force_ceiling` is the analogue; pitch : roll about 3 : 2 |
| Damping | ζ 0.7–1.5, high preferred; never < 0.3 | new `feel.damper` → SDL damper condition, tuned so a released stick does not overshoot the anchor |
| Inertia | bounded together with natural frequency; high natural frequency preferred | new `feel.inertia` → SDL inertia condition, small |
| Trim release | force to zero immediately; no stick jump when re-trimmed | existing tap-lock / tap-reset with `trim_slew_s`; hold-to-release is a future option |
| Free play | not objectionable | existing `feel.deadband` must stay small (0.02 today) |
| Dynamic coupling | no lightly damped high-frequency oscillation | the rotor buzz is intentional and *not* this; keep its amplitude below the spring force so it never masks the anchor |

## 7. Not found / not used

- No primary text giving numeric friction or damping for the MD500/OH-6 or
  Mi-28 cyclic. WEB colour only.
- MIL-H-8501A (1961) breakout tables were not retrieved; ADS-33E-PRF
  supersedes it for our purpose.
- ADS-33 §3.6.2 sidestick controllers is "reserved for future requirements";
  nothing there to apply.

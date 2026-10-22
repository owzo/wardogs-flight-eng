# Community force-feedback references (for tuning, not for copying)

Collected 2026-10-22 while designing Wardogs Flight Eng. Nothing here is
Wardogs game data; these are other people's *taste* values for other sims,
useful as starting points for the owner-preference fields in a profile
(`feel.spring_coefficient`, `rotor.base_amplitude`, `recoil.amplitude`,
`recoil.shake_amplitude`). Licences matter: TelemFFB and the preset repo are
GPL-3.0 — read them for numbers, never copy code into this MIT project.

## Moza Cockpit itself ships helicopter presets

DCS AB9 owners mostly use the presets built into Moza Cockpit rather than
sharing files: "I just use the preset that's already there for the Hind";
another uses the UH-1H preset. The presets sit in the preset dropdown at the
top of the Cockpit window (second or third from the bottom of the list in
the 2025 layout). Moza's own DCS integration also exposes helicopter module
effects including VRS.
Source: [Moza AB9 settings for Rotary](https://forum.dcs.world/topic/369829-moza-ab9-settings-for-rotary/),
[AB9 and autopilot](https://forum.dcs.world/topic/390073-ab9-and-autopilot/).

Owner action when the base arrives: open the Hind / UH-1H preset, read its
spring / damper / friction / inertia percentages, and use them as the first
guess for `feel.*`. Export it with Save As; the file is JSON (see below).

## A "Wardogs" Moza Cockpit preset (owner-supplied, author and licence unknown)

Found by the owner 2026-10-22 (`WD.preset`, Moza Cockpit format 1.0.4,
`devices: ["AB6"]`, `product_type: "AS23"`, `games: [""]`, dated
2026-09-26). Because no game is bound, none of its telemetry effects can
fire (rotor rumble 50, gun vibration 100, weapon release 67, blade slap /
VRS / ETL off are all inert); what the base actually does with it is the
`device_params` block:

| Field | Value | Meaning |
|---|---|---|
| `bacic_spring` | 50 | centring spring, % of max |
| `bacic_damper` | 30 | velocity damping |
| `bacic_inertia` | 10 | |
| `bacic_friction` | 10 | |
| `bacic_overall_strength` | 70 | global scale |
| `bacic_max_torque` | 100 | torque ceiling |
| `bacic_start_force_enble` / `_coefficient` / `_transition_zone` | 1 / 20 / 10 | breakout force 20 % with a 10 % blend |
| `bacic_gameForceFeedback` | 100 | DirectInput game effects pass through at 100 % |
| `bacic_force_model` | 2 | advanced force model |
| `hardware_balancing_enable` | 0 | Moza's own trim/centering helper off |
| `spring_x_link_y`, `spring_pos_link_neg` | true | one spring value for both axes and directions |
| `Main_VariablePointCurve_AileronPositiveBack` | 15, 32, 49, 66, 83, 100 | roll spring curve starts at 15 % (pre-load), linear to 100 |
| `Main_VariablePointCurve_ElevatorPositiveBack` | 0, 20, 40, 60, 80, 100 | pitch spring curve linear |
| `Main_DirectInput_Spring_Effect_Cp_Offset` | [0, 0] | DirectInput spring centre offset passes through unchanged |

How it combines with Flight Eng: this preset is the right *companion*
profile, with one change. Flight Eng owns the spring (its centre moves with
trim lock), so **set `bacic_spring` to 0 in the Cockpit copy** and let Cockpit
keep damper 30 / friction 10 / inertia 10 / breakout 20 — effects Flight Eng
does not synthesise in v1. Two springs at once (Cockpit's at origin, Flight
Eng's at the trim point) would pull the stick to a point between them and
break trim lock. The `_Cp_Offset [0, 0]` pass-through and
`bacic_gameForceFeedback 100` are what let Flight Eng's DirectInput spring,
sine and constant effects reach the motors.

Seeds for the profiles' `taste` fields: `feel.spring_coefficient 0.5`
(matches the preset's 50 %), overall ceiling 0.7 (`safety.force_ceiling`),
a 20 % breakout is worth adding as a later `feel.breakout` once v1 is felt.

### Two more AB9 Littlebird presets (owner-supplied 2026-10-22, authors unknown)

`wardogs helo icemanisaac.preset` ("helo icemanisaac", 2026-09-20) and
`WARDOGS-beta-preset.preset` ("**HELO DEFAULT** WARDOGS LITTLE BIRD",
2026-09-04). Both `devices: ["AB9"]`, `games: ["dcs_world"]`,
`vehicles: "OH-6A"`: their telemetry blocks only ever fired in DCS (OH-6A
mod); in Wardogs only `device_params` act.

| Field | icemanisaac | HELO DEFAULT |
|---|---|---|
| `bacic_spring` | 30 | 40 |
| `bacic_damper` | 30 | 55 |
| `bacic_friction` | 10 | 77 |
| `bacic_inertia` | 10 | 15 |
| `bacic_overall_strength` | 70 | 100 |
| `bacic_gameForceFeedback` | 100 | 75 |
| `bacic_start_force_enble` / coefficient | 1 / 20 | 0 / 20 |
| `bacic_force_model` | 2 | 1 |
| `hardware_balancing_enable` (buttons all 0) | 1 | 1 |
| `ad_y_axis_follow_ratio` | 20 | 20 |

Three independent Wardogs presets converge on damper 30–55, inertia
10–15, spring 30–50 and overall 70–100; the "HELO DEFAULT" author went the
classic helicopter route (high friction 77 + damper 55, lower spring) so the
stick stays where it is put. Their DCS-only helicopter telemetry values are
still useful magnitude references: rotor rumble 20, blade slap 20 (13–30 kt,
5–20 deg AoA), VRS max 13, ETL 12 (4–20 kt), gun vibration 16, weapon release
31 at direction 180, wind 11 — all on the 0–100 Cockpit scale.

**Moza Cockpit has built-in hardware trim.** The `hardware_balancing_*`
block is a firmware trim helper: `hardware_balancing_trim` and
`hardware_balancing_recenter` take button ids (the AB6 Cessna preset binds
them to buttons 3 and 17, with nose-up/down and wing-down nudges on 200–203),
`hardware_balancing_speed` is the slew. Both AB9 presets enable it but bind no
buttons. This is the same tap-to-lock / tap-to-reset model as Flight Eng's
trim, done in firmware.

Two valid divisions of labour for the tuning pass; pick one, never both:
- **A (spec default):** Flight Eng owns spring + trim; Cockpit `bacic_spring`
  0, `hardware_balancing_enable` 0, Cockpit keeps damper / friction / inertia
  / breakout. Portable to any DirectInput base.
- **B (Moza-native trim):** Cockpit owns spring + hardware trim (bind the
  trim and recenter buttons); Flight Eng profile sets
  `feel.spring_coefficient` 0 and supplies only rotor buzz and recoil. Lower
  latency trim in firmware, AB9-only. No code change: a zero spring
  coefficient disables Flight Eng's spring and makes its trim buttons inert.

## Moza Cockpit `.preset` file format (from a public AB6 preset, GPL-3.0 repo)

JSON, `"version": "1.0.3"` / `"1.0.4"`, keys `device_params`,
`telemetry_params`, `device_type`, `games`, `vehicles`, `name`, `uuid`.
Base-force fields (percent): `bacic_spring`, `bacic_damper`,
`bacic_inertia`, `bacic_friction`, `bacic_max_torque`,
`bacic_overall_strength`, `bacic_gameForceFeedback`; per-direction
`base_spring_{x,y}_{pos,neg}_advanced` etc.; centering block
`hardware_balancing_*`; follow block `ad_{x,y}_axis_follow_ratio`,
`follow_algorithm`; axis block `axis_range_*`, `center_x/y`.
A fixed-wing Cessna 172 preset used spring 45 / damper 50 / inertia 17 /
friction 10 — fixed-wing numbers, *not* a helicopter baseline, listed only
to show the scale.
Source: [highinthefssky/moza-flight-profiles](https://github.com/highinthefssky/moza-flight-profiles)
(AB6, MSFS 2024, nine fixed-wing presets, no helicopters).

Flight Eng could later *emit* a Moza preset from a profile (optional
backend, out of scope for v1).

## Moza Cockpit parameter list (AB9, 2026)

A DCS forum post reproduces the complete Cockpit parameter tree — useful as
a checklist of what the base can do natively: Expert centering (adaptive
compensation, hands-off detection, effect strength, compensation), max
torque per axis, overall intensity per axis, Spring / Damper / Inertia /
Friction overall strength, Trim Follow (axis follow mode and ratios,
light / heavy aircraft options, physical stick follow ratio 1-20), Autopilot
Following (follow scale, breakout force strength and range, follow rate),
telemetry effects (stick shaker 5-30 Hz, stall buffet 0-20 Hz, transonic
buffet 5-45 Hz, gear buffet, ground vibration, airflow and turbulence, jet
engine vibration 0-20 Hz, propeller vibration), and per-axis output mapping
curves, travel limits and offset (-75 % to +75 %).
Source: [FFB profile (F-100D thread)](https://forum.dcs.world/topic/388874-ffb-profile/).

Two AB9-specific observations from that thread worth carrying into the
profiles: the base's **roll force reads much stronger than pitch** at equal
settings (owners set roll to ~50 % in Expert; a Rhino owner uses 25 %), so
`feel` should carry separate pitch and roll coefficients with roll defaulting
lower; and DirectInput-only modules produce "no shake effects at all", which
is exactly the gap this project fills for Wardogs.

## Shared helicopter presets (not retrievable here)

- An **AH-6J** (Littlebird) Moza Cockpit preset was shared on the Moza
  Discord by "Nimbus North Wales" and re-attached in a DCS forum post by
  user brvt1000; the attachment and that user's post list are behind the
  forum's sign-in. The same thread notes DCS weapon effects (rockets,
  flares) reach the AB9 but gun effects do not.
  Source: [search result](https://forum.dcs.world/profile/72161-brvt1000/content/) (login required).
- An **R66** preset by belatu42 on the Moza Discord is recommended as a base
  for any helicopter ("works great in any I have flown so far").
  Source: [Moza AB9 Cockpit help](https://forums.flightsimulator.com/t/moza-ab9-cockpit-help/720003).
- Moza Discord channel `flying-settings-sharing`
  (invite quoted in that thread: https://discord.com/invite/zp7WSTDf).

Owner action: pull the AH-6J and R66 presets from the Discord with your
own account; record their spring / damper / friction / inertia percentages
in `profiles/*.json` `taste` notes as "community starting point".

## TelemFFB defaults (VPforce, GPL-3.0) — effect magnitudes on a 0-1 scale

From `defaults.xml` (helicopter class unless noted). These are the most
widely flown open numbers for synthetic helicopter effects:

| Effect | Default | Notes |
|---|---|---|
| `heli_engine_rumble_intensity` | 0.12 | rotor/engine rumble |
| `engine_rumble_lowrpm` / `_intensity` | 650 / 0.06 | |
| `engine_rumble_highrpm` / `_intensity` | 2800 / 0.03 | |
| `rotor_blade_count` | 2 | class default; per-aircraft overrides exist |
| `etl_effect_intensity`, start / stop | 0.25, 16 kt / 31 kt | translational-lift shudder |
| `vrs_effect_intensity` | 0.12 | vortex ring state |
| `blade_slap_intensity`, band centre, g factor | 0.15, 63 kt, 0.8 | |
| `touchdown_effect_max_force` / `max_gs` | 0.5 / 3 | |
| `gun_vibration_intensity` | 0.2 | DCS gunfire |
| `weapon_release_intensity` | 0.2 | |
| `weapon_effect_direction` | -1 (random, else 0-359 deg) | recoil direction |
| `cyclic_spring_gain` | 0.5 (0.8 in MSFS) | |
| `dcs_tr_damper_force` | 0.3 | trim-release damper |
| `collective_ft_trim_slew_rate` | 200 | |
| base aileron / elevator spring gain | 0.3 | fixed wing |
| `stick_shaker_intensity` / frequency | 0.4 / 40 Hz | |

Mapping to Flight Eng profile fields (owner taste, starting guesses):
`rotor.base_amplitude` ≈ 0.12-0.15; `recoil.amplitude` ≈ 0.2 before the
game's 0.15 shake multiplier (so ~0.6 raw to land near 0.1 felt);
`feel.spring_coefficient` ≈ 0.5 pitch / 0.25-0.35 roll; a trim-release
damper is not modelled in v1 (tap-to-lock has no release phase).
Sources: [VPforce-TelemFFB](https://github.com/walmis/VPforce-TelemFFB),
[defaults.xml](https://raw.githubusercontent.com/walmis/VPforce-TelemFFB/master/defaults.xml).
TelemFFB's "DirectLink" integration drives third-party DirectInput devices;
the AB9 is not named as supported.

## FFB-Bridge (Rohsam, free, closed) — behaviour worth imitating

For Moza bases it implements helicopter force trim that captures one
consistent physical and simulator position, a one-press trim reset, a
configurable hold strength that may exceed the in-flight ceiling, a
configurable breakout, and a "gentle standby spring" when disarmed. It fixed
"an unwanted pitch-up pull after releasing force trim" — the same failure
mode Flight Eng's slewed centre transition exists to avoid. Vibration
follows rotor speed and blade count including 2-per-rev.
Source: [FFB-Bridge 1.4.1](https://forums.flightsimulator.com/t/update-1-4-1-ffb-bridge-rohsam-inc/767512/6).

## Apache artificial-feel description (owner-supplied)

Lateral / longitudinal feel springs; magnetic-brake force trim (release →
stick free, re-engage → new centre); steady high-frequency buzz that changes
with rotor speed and airframe stress; SAS corrections isolated from the
stick. This is the feel model the spec adopts (tap-to-lock variant).

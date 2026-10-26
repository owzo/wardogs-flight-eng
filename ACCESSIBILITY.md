# Accessibility

## Commitment

Wardogs Flight Eng is a command-line program. The maintainer's aim is that
everything it tells you is plain text that a screen reader, a braille display
or a high-contrast terminal can present, and that nothing it does depends on
seeing colour or hearing sound.

## What is in place

- **Text only.** Every command prints plain text to the terminal; the program
  emits no ANSI colour, no cursor movement and no sound. Verdicts are words
  (`PASS`, `WARN`, `FAIL`, `stopped: device_lost`) and exit codes, never a
  colour.
- **Live views are line-based.** `list-devices --live` and `check-device`
  reprint a table on a fixed interval; they do not redraw in place, so a
  screen reader can follow them.
- **Logs are files.** Everything printed is also written to
  `%LOCALAPPDATA%\WardogsFlightEng\logs\wardogs-flight-eng.log`, so a session
  can be read back later at your own pace.
- **Dry-run plots are scriptless HTML** with the same data in `forces.jsonl`,
  a plain line-per-record file, for anyone who cannot use the plot.
- **Every physical interaction is optional and announced.** `calibrate` asks
  for three positions with a prompt and waits for Enter; `run` never plays a
  force until the devices are open and the profile is loaded, and the
  README's hardware pass says before each step what the stick will do.

## Known limitations

- The plot (`forces.html`) has no text alternative beyond the raw
  `forces.jsonl`; a screen reader will not describe its shape.
- The program is Windows-only and needs a terminal; there is no GUI and no
  plan for one.
- Force feedback itself is a physical interface. The program cannot judge
  whether a given force level is safe for a given hand; the shipped
  `safety.force_ceiling` is a starting point, not medical advice. Anyone with
  reduced grip strength, a wrist or hand injury, or a tremor should start
  lower and keep the stick released during the measured tests.
- The time-limited Ctrl+C handling (a second press within 3 seconds is
  ignored) is documented but not adjustable.

## Supported environments

Windows 10 and 11, in Windows Terminal, PowerShell or the classic console,
with Python 3.12 or the packaged exe. The README is the only documentation
the program ships; the wiki mirrors it in shorter pages.

## Reporting a barrier

Open an issue with the "Bug report" template and start the title with
`accessibility:`. Say which assistive technology or terminal you use and
what you could not do. Barriers are prioritised with bugs, not with feature
requests.

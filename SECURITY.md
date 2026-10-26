# Security policy

## What counts as a security issue here

This program drives a force-feedback base that can move a stick against a
person's hand. "Security" therefore covers physical safety as well as the
usual meanings. Report privately if you find any of the following:

- **A force path that escapes the fail-closed design**: a command that can
  reach the base without the per-command clamp (NaN → 0, `force_ceiling`), a
  persistent effect that can outlive the watchdog or the release on exit, a
  way to leave the base pushing after Ctrl+C, device loss, or a crash, or a
  profile value the loader should refuse and does not.
- **Anything that reads the game**: a dependency, a code path or a build step
  that touches the Wardogs process, memory, screen, files or network. The
  project's rule is that nothing does; a breach of it is a defect of the most
  serious kind.
- **Code execution or file damage** from a crafted profile, scenario,
  recording, Moza Cockpit preset or constants file. These are JSON, parsed
  with the standard library and validated on load; `make-preset`, `calibrate`
  and `record` write their output atomically, and `make-preset` refuses to
  write over its template or profile. A bypass of any of this is in scope.
- **Supply chain**: a compromised or typosquatted dependency, a tampered
  release asset, or a difference between the tagged source and the published
  exe beyond PyInstaller's non-reproducibility.
- **Secrets**: any key, token or credential found in the repository, its
  history, the wiki or a release.

Out of scope: feel values you dislike (open an ordinary issue), the game's
own behaviour, and Moza Cockpit itself.

## How to report

Use GitHub's private vulnerability reporting for this repository:
**Security → Report a vulnerability** at
https://github.com/owzo/wardogs-flight-eng/security/advisories/new. It reaches
only the maintainer. Please do not open a public issue for anything that
could hurt a user or expose data until a fix is released.

Include the version (the release tag, or the commit for a checkout), the
backend (`sdl` or `dinput8`), the command, the log from
`%LOCALAPPDATA%\WardogsFlightEng\logs\`, and the smallest profile or scenario
that shows the problem. Do **not** include game assets, keys or mappings.

## What to expect

- Acknowledgement within 7 days.
- An assessment and, where the report is valid, a fix or mitigation plan
  within 30 days. Physical-safety issues are treated as the highest severity
  and fixed first.
- Credit in the release notes if you want it.
- A GitHub security advisory for anything that affected a published release.

## Supported versions

Only the latest release receives fixes. Every release so far is a pre-release
that has not been run on real hardware; the README's status section is the
authority on what has and has not been verified.

| Version | Supported |
|---|---|
| latest release | yes |
| older releases | no, update |

## How the release is protected

- The exe is built by the `build-exe` workflow from the tagged commit and
  attached with a `SHA256SUMS` file; verify the hash before running it.
- Secret scanning and push protection are on for the repository.
- Dependencies are pinned in `uv.lock`; the direct ones are `pydantic`,
  `pysdl2` and `pysdl2-dll`. The DirectInput backend uses only `dinput8.dll`
  from Windows through `ctypes`; nothing is installed.

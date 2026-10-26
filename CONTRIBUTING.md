# Contributing

Thank you for looking. The most valuable contribution right now is a
**hardware report**: nobody, including the maintainer, has yet played a force
from this program on a real Moza AB9. If you have one, the
[Hardware tuning pass](https://github.com/owzo/wardogs-flight-eng/wiki/Hardware-tuning-pass)
on the wiki says what to run and the "Hardware test report" issue template
says what to send.

## Ground rules that every change must keep

These are not style preferences. A change that breaks one is declined
whatever else it does.

1. **Nothing reads the game.** No process, memory, screen, file, network or
   telemetry access to Wardogs, now or in any future "feed". The only inputs
   are the user's own controls.
2. **No game asset contents, keys or mappings in the repository**, in issues,
   or in the wiki. Every number in a profile is owner taste or a doctrine
   shape with a citation in `docs/reference/`. Nothing is inferred from a
   real weapon or aircraft.
3. **Never two springs.** Flight Eng and Moza Cockpit must not both centre
   the stick. See `make-preset` and the README's companion-settings section.
4. **No force outside the fail-closed path.** Every command goes through the
   per-command clamp, the finite-length persistent effects, the engine and
   loop watchdogs, and the release on every exit path. New effects join that
   path; they do not bypass it.
5. **The model could yield sight data or other game-advantaging output.**
   It deliberately does not, and no change adds it.

## Before you open a pull request

Run the four gates from a checkout (they are what CI runs on Windows and
Linux):

```
uv sync --all-groups
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

Run `mypy` plain: the configured gate covers `src` and `tests`, and
`mypy --strict src` alone is not the same check.

Code rules the reviewers hold to:

- Every file under 200 lines; every function under 50. Split by domain, not
  into `utils` or `helpers`.
- Type hints on every public signature; `mypy --strict` is the configuration.
- Early return over nested conditionals. Specific exceptions, never bare
  `except:`. `logging`, never `print()`, outside the CLI's own output.
- Tests for every behaviour change, and a test that would have failed before
  the fix for every bug fix. UI-free: the suite runs with no devices through
  the fake SDL and DirectInput layers in `tests/`.
- No placeholders or TODOs in committed code.

## How changes are designed

Anything larger than a bug fix starts as a design document in
`docs/superpowers/specs/` and an implementation plan in
`docs/superpowers/plans/` (the [Design specs](https://github.com/owzo/wardogs-flight-eng/wiki/Design-specs)
wiki page indexes the existing ones). Open an issue first and say what you
want to change and why; the maintainer will say whether it needs a spec. A
pull request that arrives without that conversation for a large change may be
asked to go back and have it.

Procedure or convention numbers (rounding steps, tolerances, bands) live in
named constants with the source cited in a comment, never in profile JSON.

## Profiles and feel values

Profile values are the maintainer's taste until the hardware pass and will be
replaced by measured ones. A pull request that changes a shipped profile's
`feel`, `rotor` or `safety` values needs a hardware report behind it.
`safety.force_ceiling` is not raised in a shipped profile.

## Commits and pull requests

- One topic per pull request. Describe what changed and why, and name the
  tests that cover it. The pull request template asks for this.
- CI must be green on both runners.
- The maintainer merges with a fast-forward or a rebase; keep your branch
  rebased on `main`.
- Releases are tagged `vX.Y.Z` by the maintainer; the tag builds the exe.

## Reporting a problem

Use the issue templates. A **bug report** needs the version, the backend, the
command, and the log from `%LOCALAPPDATA%\WardogsFlightEng\logs\`. A
**hardware test report** needs the measured-test output. A **security or
safety concern** that could hurt someone or expose data goes through
[SECURITY.md](SECURITY.md), not a public issue.

## Licence

Contributions are accepted under the project's MIT licence. By opening a pull
request you agree your change is yours to give and is licensed the same way.

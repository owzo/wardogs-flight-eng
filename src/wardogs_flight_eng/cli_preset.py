"""``make-preset``: write a Moza Cockpit preset for division A or B.

Reads the user's own Cockpit export as the template, rewrites it with
``cockpit_preset.rewrite_preset`` and writes the result as Cockpit does
(4-space indent, LF line endings, trailing newline).
"""

import argparse
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from wardogs_flight_eng.cli_console import EXIT_OK, CliContext, CliError
from wardogs_flight_eng.cli_profiles import load_checked_profile
from wardogs_flight_eng.cockpit_preset import rewrite_preset
from wardogs_flight_eng.constants.loader import load_constants

log = logging.getLogger(__name__)


def _read_template(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as err:
        raise CliError(f"cannot read template {path}: {err.strerror}") from err
    try:
        document = json.loads(text)
    except json.JSONDecodeError as err:
        raise CliError(f"template {path} is not JSON: {err}") from err
    if not isinstance(document, dict):
        raise CliError(f"template {path} is not a JSON object")
    return document


def _write_preset(path: Path, document: dict[str, Any]) -> None:
    """Write via a uniquely named staging file and ``os.replace``: never a
    truncated preset, and never another writer's ``.tmp`` file."""
    text = json.dumps(document, indent=4, ensure_ascii=False) + "\n"
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            staging = Path(handle.name)
            handle.write(text)
        os.replace(staging, path)
    except OSError as err:
        if staging is not None:
            staging.unlink(missing_ok=True)
        raise CliError(f"cannot write preset {path}: {err.strerror}") from err
    log.info("Moza Cockpit preset written to %s", path)


def _shown(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def make_preset_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Write the preset to ``--out``; print every changed key and the path."""
    out: Path = args.out
    if out.resolve() == args.template.resolve():
        raise CliError(f"--out {out}: refuses to overwrite the template it reads")
    if out.resolve() == args.profile.resolve():
        raise CliError(f"--out {out}: refuses to overwrite the profile it reads")
    profile = load_checked_profile(args.profile, load_constants())
    template = _read_template(args.template)
    document, changes = rewrite_preset(
        template,
        args.division,
        profile,
        name=args.name,
        now=int(time.time()),
        new_uuid=f"{{{uuid.uuid4()}}}",
    )
    _write_preset(out, document)
    ctx.console.line(
        f"division {args.division} for profile {profile.name!r} ({profile.feel.mode})"
    )
    ctx.console.table(
        ("key", "old", "new"),
        [(change.key, _shown(change.old), _shown(change.new)) for change in changes],
    )
    ctx.console.line(f"wrote {out}")
    return EXIT_OK

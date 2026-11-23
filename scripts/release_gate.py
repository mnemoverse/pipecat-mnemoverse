#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

"""The release gate: a tag vX.Y.Z may publish only when __version__ is X.Y.Z and CHANGELOG.md has
the heading ``## [X.Y.Z] - YYYY-MM-DD``. release.yml runs it in the test job, which the publish
job waits for; ci.yml runs it in the release rehearsal on every pull request. Nothing else decides
whether a tag may publish.

Run from the repository root (Python 3.11+, standard library only)::

    python scripts/release_gate.py check vX.Y.Z  # exit 0: may publish; exit 1: refused,
                                                 # with the reasons
    python scripts/release_gate.py version       # print __version__, found through
                                                 # pyproject.toml
    python scripts/release_gate.py stage STATE   # rewrite CHANGELOG.md so the heading of
                                                 # __version__ is dated (today), bare or missing

Between releases the heading of __version__ is legally in one of three states: dated (released, or
the release PR merged), bare ``## [X.Y.Z]`` (the release PR in progress) or missing (__version__
bumped before the heading was written). Only the dated one passes the gate.

Exit 1 means a refusal and nothing else. When the gate cannot decide (no CHANGELOG.md, no
version, a usage error, any other exception) it exits 2, so a crash is never mistaken for a
refusal.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
import traceback
from datetime import date
from pathlib import Path

CHANGELOG = "CHANGELOG.md"
STATES = ("dated", "bare", "missing")
_DATED = re.compile(r" - (\d{4}-\d{2}-\d{2})")


def read_version(root: Path) -> str:
    """``[project] version``, or the ``__version__`` in the file ``[tool.hatch.version] path``
    names."""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    static = pyproject.get("project", {}).get("version")
    if static:
        return str(static)
    path = root / pyproject["tool"]["hatch"]["version"]["path"]
    match = re.search(
        r"""^__version__\s*=\s*["']([^"']+)["']""", path.read_text(encoding="utf-8"), re.M
    )
    if not match:
        raise ValueError(f"no __version__ = '...' line in {path}")
    return match.group(1)


def _headings(text: str, version: str) -> list[tuple[int, str]]:
    prefix = f"## [{version}]"
    return [(i, line) for i, line in enumerate(text.splitlines()) if line.startswith(prefix)]


def heading_state(text: str, version: str) -> str:
    """``dated``, ``bare`` or ``missing``; anything else is ``undated`` or ``duplicate``."""
    found = _headings(text, version)
    if not found:
        return "missing"
    if len(found) > 1:
        return "duplicate"
    rest = found[0][1].removeprefix(f"## [{version}]").rstrip()
    if rest == "":
        return "bare"
    match = _DATED.fullmatch(rest)
    if match:
        try:
            date.fromisoformat(match.group(1))
        except ValueError:
            return "undated"
        return "dated"
    return "undated"


def refusals(tag: str, version: str, text: str) -> list[str]:
    """Why ``tag`` may not publish this tree; an empty list means it may."""
    if not tag.startswith("v"):
        return [f"tag {tag} is not v<version>"]
    wanted = tag[1:]
    problems = []
    if wanted != version:
        problems.append(f"__version__ reads {version}, the tag expects {wanted}")
    state = heading_state(text, wanted)
    if state == "missing":
        problems.append(f"{CHANGELOG} has no '## [{wanted}]' heading")
    elif state == "duplicate":
        problems.append(
            f"{CHANGELOG} has {len(_headings(text, wanted))} headings for {wanted}; keep one"
        )
    elif state != "dated":
        line = _headings(text, wanted)[0][1]
        problems.append(
            f"{CHANGELOG} reads '{line}'; date the heading first: '## [{wanted}] - YYYY-MM-DD'"
        )
    return problems


def stage(text: str, version: str, state: str, today: date) -> str:
    """``text`` with the heading of ``version`` in ``state``; every other line as it was."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}, not {state!r}")
    lines = text.splitlines()
    found = [i for i, _ in _headings(text, version)]
    for i in reversed(found):
        del lines[i]
    if state != "missing":
        heading = f"## [{version}] - {today.isoformat()}" if state == "dated" else f"## [{version}]"
        if found:
            lines.insert(found[0], heading)
        else:
            # Above the newest release, below `## [Unreleased]`; at the end when there is none.
            at = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if line.startswith("## [") and line != "## [Unreleased]"
                ),
                len(lines),
            )
            lines[at:at] = [heading, ""]
    return "\n".join(lines) + "\n"


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="may this tag publish the tree?").add_argument("tag")
    commands.add_parser("version", help="print __version__")
    commands.add_parser("stage", help="rewrite the CHANGELOG heading of __version__").add_argument(
        "state", choices=STATES
    )
    args = parser.parse_args(argv)

    root = Path.cwd()
    version = read_version(root)
    if args.command == "version":
        print(version)
        return 0
    path = root / CHANGELOG
    text = path.read_text(encoding="utf-8")
    if args.command == "stage":
        path.write_text(stage(text, version, args.state, date.today()), encoding="utf-8")
        print(f"{CHANGELOG}: the heading of {version} is now {args.state}")
        return 0
    problems = refusals(args.tag, version, text)
    error = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "refused: "
    for problem in problems:
        print(f"{error}{problem}")
    if problems:
        return 1
    print(f"tag {args.tag} may publish {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """``run``, with every unexpected exception turned into exit 2: 1 stays a refusal only."""
    try:
        return run(argv)
    except Exception as exc:  # noqa: BLE001 - any crash, reported and kept apart from a refusal
        traceback.print_exc()
        error = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "error: "
        print(
            f"{error}the release gate could not decide ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

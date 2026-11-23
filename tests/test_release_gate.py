#
# Copyright (c) 2026, Mnemoverse
#
# SPDX-License-Identifier: BSD-2-Clause
#

"""The release gate in scripts/release_gate.py is the one both workflows run, and the files
release.yml publishes come from a job that runs no test code."""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml  # PyYAML, a dependency of pipecat-ai

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
WORKFLOWS = ROOT / ".github" / "workflows"
GATE_SCRIPT = ROOT / "scripts" / "release_gate.py"

# The workflows and scripts live in the repository; the sdist ships the tests without them.
pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="no .github/workflows (an unpacked sdist)"
)


def workflow(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return data


# -- the release gate ------------------------------------------------------------------------
#
# A tag vX.Y.Z may publish only when __version__ is X.Y.Z and CHANGELOG.md has
# `## [X.Y.Z] - YYYY-MM-DD`. Between releases the heading of __version__ is legally in one of
# three states: dated (the release PR merged, or nothing changed since the last release), bare
# `## [X.Y.Z]` (the release PR in progress) or missing (__version__ bumped before the heading was
# written). The gate is tested on synthetic text for each, so no test depends on which state the
# committed CHANGELOG is in.


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_gate", GATE_SCRIPT)
    assert spec and spec.loader, GATE_SCRIPT
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def changelog(*headings: str) -> str:
    sections = "".join(f"{h}\n\n### Added\n\n- Something.\n\n" for h in headings)
    return f"# Changelog\n\nAll notable changes.\n\n## [Unreleased]\n\n{sections}"


@pytest.mark.parametrize(
    ("state", "text"),
    [
        ("dated", changelog("## [1.2.3] - 2026-11-22", "## [1.2.2] - 2026-10-01")),
        ("bare", changelog("## [1.2.3]", "## [1.2.2] - 2026-10-01")),
        ("missing", changelog("## [1.2.2] - 2026-10-01")),
        ("missing", changelog("## [1.2.30] - 2026-11-22", "## [11.2.3] - 2026-11-22")),
        ("undated", changelog("## [1.2.3] - unreleased")),
        ("undated", changelog("## [1.2.3] - TBD")),
        ("undated", changelog("## [1.2.3] - 2026-11-22 (yanked)")),
        ("undated", changelog("## [1.2.3] - 2026-13-01")),
        ("duplicate", changelog("## [1.2.3] - 2026-11-22", "## [1.2.3]")),
    ],
)
def test_heading_state(gate: ModuleType, state: str, text: str) -> None:
    assert gate.heading_state(text, "1.2.3") == state


@pytest.mark.parametrize(
    ("tag", "text", "refusal"),
    [
        ("v1.2.3", changelog("## [1.2.3] - 2026-11-22"), None),
        ("v1.2.3", changelog("## [1.2.3]"), "date the heading first: '## [1.2.3] - YYYY-MM-DD'"),
        (
            "v1.2.3",
            changelog("## [1.2.2] - 2026-10-01"),
            "CHANGELOG.md has no '## [1.2.3]' heading",
        ),
        ("v1.2.3", changelog("## [1.2.3] - unreleased"), "date the heading first"),
        ("v1.2.3", changelog("## [1x2x3] - 2026-11-22"), "has no '## [1.2.3]' heading"),
        ("v1.2.3", changelog("## [1.2.3] - 2026-11-22", "## [1.2.3]"), "2 headings for 1.2.3"),
        (
            "v1.2.4",
            changelog("## [1.2.4] - 2026-11-22"),
            "__version__ reads 1.2.3, the tag expects 1.2.4",
        ),
        ("1.2.3", changelog("## [1.2.3] - 2026-11-22"), "tag 1.2.3 is not v<version>"),
    ],
)
def test_the_gate_wants_the_version_and_a_dated_heading(
    gate: ModuleType, tag: str, text: str, refusal: str | None
) -> None:
    problems: list[str] = gate.refusals(tag, "1.2.3", text)
    if refusal is None:
        assert problems == []
    else:
        assert any(refusal in p for p in problems), problems


@pytest.mark.parametrize("state", ["dated", "bare", "missing"])
@pytest.mark.parametrize(
    "text",
    [
        changelog("## [1.2.3] - 2026-11-22", "## [1.2.2] - 2026-10-01"),
        changelog("## [1.2.3]", "## [1.2.2] - 2026-10-01"),
        changelog("## [1.2.2] - 2026-10-01"),
        "# Changelog\n",
    ],
)
def test_stage_puts_the_heading_in_the_state_asked_for(
    gate: ModuleType, state: str, text: str
) -> None:
    staged: str = gate.stage(text, "1.2.3", state, date(2026, 11, 23))
    assert gate.heading_state(staged, "1.2.3") == state
    assert (gate.refusals("v1.2.3", "1.2.3", staged) == []) is (state == "dated")
    # The other releases are left as they were.
    assert staged.count("## [1.2.2] - 2026-10-01") == text.count("## [1.2.2] - 2026-10-01")


def test_the_committed_tree_is_in_a_legal_state(gate: ModuleType) -> None:
    version: str = gate.read_version(ROOT)
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    state = gate.heading_state(text, version)
    assert state in {"dated", "bare", "missing"}, (
        f"the CHANGELOG heading for {version} is {state}; use `## [{version}] - YYYY-MM-DD`, "
        f"`## [{version}]`, or keep the entries under `## [Unreleased]`"
    )
    assert (gate.refusals(f"v{version}", version, text) == []) is (state == "dated")


def test_the_version_comes_from_the_file_pyproject_names(gate: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.hatch.version]\npath = "pkg/_v.py"\n')
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "_v.py").write_text('"""Doc."""\n\n__version__ = "4.5.6"\n')
    assert gate.read_version(tmp_path) == "4.5.6"
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "7.8.9"\n')
    assert gate.read_version(tmp_path) == "7.8.9"


@pytest.mark.parametrize(
    ("heading", "code", "message"),
    [
        ("## [1.2.3] - 2026-11-22", 0, "may publish 1.2.3"),
        ("## [1.2.3]", 1, "date the heading first"),
        ("## [1.2.2] - 2026-11-22", 1, "has no '## [1.2.3]' heading"),
    ],
)
def test_the_command_line(tmp_path: Path, heading: str, code: int, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog(heading))
    env = {"PATH": os.environ["PATH"]}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(GATE_SCRIPT), *args]
        return subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True)

    assert run("version").stdout == "1.2.3\n"
    result = run("check", "v1.2.3")
    assert result.returncode == code, result.stdout + result.stderr
    assert message in result.stdout + result.stderr
    assert run("stage", "missing").returncode == 0
    assert "has no '## [1.2.3]' heading" in run("check", "v1.2.3").stdout


# -- workflows -----------------------------------------------------------------------------


def test_both_workflows_run_the_one_gate() -> None:
    steps = [s for job in workflow("release.yml")["jobs"].values() for s in job.get("steps", [])]
    name = "Tag must match __version__ and a dated CHANGELOG heading"
    tag_gate = next(s for s in steps if s.get("name") == name)
    assert shlex.split(tag_gate["run"]) == [
        "python",
        "scripts/release_gate.py",
        "check",
        "$GITHUB_REF_NAME",
    ]
    rehearsal = workflow("ci.yml")["jobs"]["release-rehearsal"]
    assert rehearsal["strategy"]["matrix"]["state"] == ["dated", "bare", "missing"]
    runs = "\n".join(s.get("run", "") for s in rehearsal["steps"])
    assert "scripts/release_gate.py stage" in runs and "scripts/release_gate.py check" in runs
    assert "python -m pytest" in runs
    # Nobody reads the CHANGELOG but the gate.
    for file in ("ci.yml", "release.yml"):
        scripts = [
            s.get("run", "")
            for job in workflow(file)["jobs"].values()
            for s in job.get("steps", [])
        ]
        assert not [s for s in scripts if "CHANGELOG" in s], file


def test_the_published_files_come_from_a_job_that_runs_no_dev_dependency() -> None:
    jobs = workflow("release.yml")["jobs"]
    builders = [
        name
        for name, job in jobs.items()
        if any("python -m build" in s.get("run", "") for s in job["steps"])
    ]
    assert builders == ["build"]
    runs = [s.get("run", "") for s in jobs["build"]["steps"]]
    installs = [line for run in runs for line in run.splitlines() if "pip install" in line]
    assert installs and all(
        "-e" not in shlex.split(line) and ".[dev]" not in line for line in installs
    )
    for line in installs:
        packages = [
            a
            for a in shlex.split(line)
            if not a.startswith("-") and a not in {"python", "pip", "install"}
        ]
        assert packages and all("==" in p for p in packages), line
    assert not any("pytest" in run or "ruff" in run or "mypy" in run for run in runs)
    publish = jobs["publish"]
    assert set(publish["needs"]) == {"test", "build", "verify"}
    assert [name for name, job in jobs.items() if "id-token" in job.get("permissions", {})] == [
        "publish"
    ]


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_no_checkout_keeps_the_job_token_on_disk(name: str) -> None:
    checkouts = [
        step
        for job in workflow(name)["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts
    assert all(step.get("with", {}).get("persist-credentials") is False for step in checkouts)


def test_every_action_is_pinned_by_commit() -> None:
    # A tag can be moved to other code; a commit cannot. The comment names the tag for readers and
    # for Dependabot, which updates both.
    uses = [
        (path.name, line.strip())
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(- )?uses:", line)
    ]
    assert uses
    unpinned = [
        u
        for u in uses
        if not re.fullmatch(r"(- )?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\S+", u[1])
    ]
    assert unpinned == []


def test_dependabot_keeps_the_pinned_actions_current() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = {u["package-ecosystem"]: u for u in config["updates"]}
    assert updates["github-actions"]["schedule"]["interval"] == "weekly"


def test_the_build_backend_is_pinned_exactly() -> None:
    # The sdist and wheel are built by whatever [build-system] resolves to on release day.
    requires = PYPROJECT["build-system"]["requires"]
    assert requires and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9.]*", r) for r in requires), (
        requires
    )

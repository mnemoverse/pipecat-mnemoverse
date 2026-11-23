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
import shutil
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

# The workflows live in the repository; the sdist ships the tests and scripts/ without them.
pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="no .github/workflows (an unpacked sdist)"
)


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def workflow(name: str) -> dict[str, Any]:
    return load(WORKFLOWS / name)


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
        # Accepted on purpose: trailing whitespace or a CRLF line end after the heading. Editors add
        # them, a reader sees the same heading, and refusing a release over them would help nobody.
        ("dated", changelog("## [1.2.3] - 2026-11-22  ")),
        ("dated", changelog("## [1.2.3] - 2026-11-22\t")),
        ("dated", changelog("## [1.2.3] - 2026-11-22\r")),
        ("dated", changelog("## [1.2.3] - 2026-11-22").replace("\n", "\r\n")),
        ("bare", changelog("## [1.2.3] \r")),
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

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return run_gate(tmp_path, *args)

    assert run("version").stdout == "1.2.3\n"
    result = run("check", "v1.2.3")
    assert result.returncode == code, result.stdout + result.stderr
    assert message in result.stdout + result.stderr
    assert run("stage", "missing").returncode == 0
    assert "has no '## [1.2.3]' heading" in run("check", "v1.2.3").stdout


def run_gate(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(GATE_SCRIPT), *args]
    env = {"PATH": os.environ["PATH"]}
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


DATED = changelog("## [1.2.3] - 2026-11-22")


@pytest.mark.parametrize(
    ("files", "args"),
    [
        ({"pyproject.toml": '[project]\nname = "x"\nversion = "1.2.3"\n'}, ["check", "v1.2.3"]),
        ({"pyproject.toml": '[project]\nname = "x"\n', "CHANGELOG.md": DATED}, ["check", "v1.2.3"]),
        (
            {
                "pyproject.toml": '[tool.hatch.version]\npath = "_v.py"\n',
                "_v.py": "VERSION = '1.2.3'\n",
            },
            ["version"],
        ),
        ({"pyproject.toml": "[project\n", "CHANGELOG.md": DATED}, ["check", "v1.2.3"]),
        (
            {"pyproject.toml": '[project]\nname = "x"\nversion = "1.2.3"\n', "CHANGELOG.md": DATED},
            ["check"],
        ),
    ],
    ids=["no-changelog", "no-version", "no-version-line", "broken-pyproject", "no-tag"],
)
def test_the_command_line_exits_2_when_the_gate_cannot_decide(
    tmp_path: Path, files: dict[str, str], args: list[str]
) -> None:
    # 1 is a refusal and nothing else: a gate that crashed must not pass for one that refused.
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    result = run_gate(tmp_path, *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "may publish" not in result.stdout


# -- workflows -----------------------------------------------------------------------------
#
# Every workflow and composite action of the repository, found once and checked by every test
# below: a file added under another extension or as an action is not left out of the checks.


def keys(value: Any) -> set[str]:
    """Every mapping key anywhere inside ``value``."""
    if isinstance(value, dict):
        return {str(k) for k in value} | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def steps_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps of every job of a workflow, or of a composite action."""
    if "jobs" in doc:
        return [step for job in doc["jobs"].values() for step in job.get("steps", [])]
    steps: list[dict[str, Any]] = doc.get("runs", {}).get("steps", [])
    return steps


def uses(step: dict[str, Any], action: str) -> bool:
    return str(step.get("uses", "")).startswith(f"{action}@")


def needs(job: dict[str, Any]) -> set[str]:
    found = job.get("needs", [])
    return {found} if isinstance(found, str) else set(found)


WORKFLOW_FILES = sorted(
    {
        *WORKFLOWS.glob("*.yml"),
        *WORKFLOWS.glob("*.yaml"),
        *(ROOT / ".github" / "actions").glob("**/action.y*ml"),
    }
)
REHEARSAL = "${{ runner.temp }}/rehearsal"


def test_the_workflow_files_are_found() -> None:
    names = {path.relative_to(ROOT).as_posix() for path in WORKFLOW_FILES}
    assert names, "no workflow or composite action found"
    assert {".github/workflows/ci.yml", ".github/workflows/release.yml"} <= names, names


def test_both_workflows_run_the_one_gate() -> None:
    jobs = workflow("release.yml")["jobs"]
    # In the test job, which publish waits for; nowhere else in release.yml.
    name = "Tag must match __version__ and a dated CHANGELOG heading"
    tag_gate = [s for s in jobs["test"]["steps"] if s.get("name") == name]
    assert len(tag_gate) == 1, f"the test job of release.yml has no step {name!r}"
    assert shlex.split(tag_gate[0]["run"]) == [
        "python",
        "scripts/release_gate.py",
        "check",
        "$GITHUB_REF_NAME",
    ]
    assert (
        not {"if", "continue-on-error"} & set(tag_gate[0])
        and "continue-on-error" not in jobs["test"]
    )
    assert "test" in needs(jobs["publish"])
    others = [
        n
        for n, job in jobs.items()
        if n != "test"
        for s in job["steps"]
        if "release_gate" in s.get("run", "")
    ]
    assert others == []
    # Nobody reads the CHANGELOG but the gate.
    for path in WORKFLOW_FILES:
        assert not [s for s in steps_of(load(path)) if "CHANGELOG" in s.get("run", "")], path.name


def rehearsal_steps() -> dict[str, dict[str, Any]]:
    """The steps of the release rehearsal, by what they run."""
    steps = workflow("ci.yml")["jobs"]["release-rehearsal"]["steps"]
    found = {}
    for what, marker in REHEARSAL_STEPS.items():
        matching = [s for s in steps if marker in s.get("run", "")]
        assert len(matching) == 1, f"one rehearsal step runs {marker!r}, not {len(matching)}"
        found[what] = matching[0]
    return found


REHEARSAL_STEPS = {
    "stage": "release_gate.py stage",
    "install": "pip install",
    "test": "pytest",
    "verdict": "release_gate.py check",
}


def runs_in_the_staged_copy(step: dict[str, Any], marker: str) -> bool:
    if step.get("working-directory") == REHEARSAL:
        return True
    lines = [line.strip() for line in step["run"].splitlines()]
    command = next(i for i, line in enumerate(lines) if marker in line)
    return 'cd "$RUNNER_TEMP/rehearsal"' in lines[:command]


def test_the_rehearsal_stages_each_state_and_tests_the_staged_copy() -> None:
    ci = workflow("ci.yml")["jobs"]
    job = ci["release-rehearsal"]
    assert job["strategy"]["matrix"] == {"state": ["dated", "bare", "missing"]}
    assert job["env"]["STATE"] == "${{ matrix.state }}"
    steps = rehearsal_steps()
    stage = [line.strip() for line in steps["stage"]["run"].splitlines()]
    assert stage[0] == "set -euo pipefail"
    assert 'git archive HEAD | tar -x -C "$RUNNER_TEMP/rehearsal"' in stage
    assert [shlex.split(line) for line in stage if REHEARSAL_STEPS["stage"] in line] == [
        ["python", "scripts/release_gate.py", "stage", "$STATE"]
    ]
    for what, marker in REHEARSAL_STEPS.items():
        assert runs_in_the_staged_copy(steps[what], marker), (
            f"the {what} step runs outside the staged copy"
        )
        assert not {"shell", "continue-on-error"} & set(steps[what]), what
    # The whole unit suite, as the test job runs it, and nothing swallows a failure.
    unit_suite = next(s for s in ci["test"]["steps"] if s.get("name") == "Test")["run"]
    assert steps["test"]["run"].strip() == unit_suite.strip()
    for what in ("stage", "install", "test"):
        assert "||" not in steps[what]["run"] and "if" not in steps[what], what
    assert "continue-on-error" not in job
    # The verdict also runs when the suite failed, so each run reports both.
    assert steps["verdict"]["if"] == "${{ !cancelled() }}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="the verdict step is a bash script")
@pytest.mark.parametrize("code", [0, 1, 2])
@pytest.mark.parametrize("state", ["dated", "bare", "missing"])
def test_the_rehearsal_verdict_wants_0_for_dated_and_exactly_1_otherwise(
    tmp_path: Path, state: str, code: int
) -> None:
    # The verdict step itself, run by bash as the runner runs it, against a stand-in gate that
    # exits `code`: 0 may publish, 1 refused, 2 the gate crashed.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "python"
    fake.write_text(
        "#!/bin/sh\n"
        '[ "$1" = scripts/release_gate.py ] || exit 97\n'
        'case "$2" in\n'
        "  version) echo 1.2.3 ;;\n"
        '  check) [ "$3" = v1.2.3 ] || exit 98; exit "$GATE_EXIT" ;;\n'
        "  *) exit 99 ;;\n"
        "esac\n"
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STATE": state,
        "GATE_EXIT": str(code),
    }
    script = rehearsal_steps()["verdict"]["run"]
    result = subprocess.run(
        ["bash", "-e", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    expected = 0 if state == "dated" else 1
    assert (result.returncode == 0) is (code == expected), result.stdout + result.stderr


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
    assert needs(publish) == {"test", "build", "verify"}


def test_the_build_job_runs_no_code_but_the_build() -> None:
    jobs = workflow("release.yml")["jobs"]
    actions = [str(s["uses"]).split("@")[0] for s in jobs["build"]["steps"] if "uses" in s]
    assert actions == ["actions/checkout", "actions/setup-python", "actions/upload-artifact"]
    # No cache: what another run saved could change the files that get built and published.
    cached = [
        (name, s.get("name") or s.get("uses"))
        for name, job in jobs.items()
        for s in job["steps"]
        if {"cache", "cache-dependency-path"} & set(s.get("with") or {}) or uses(s, "actions/cache")
    ]
    assert cached == []
    # No build hook: hatchling would run its code while building.
    assert "hooks" not in keys(PYPROJECT.get("tool", {}).get("hatch", {}))
    # verify and publish get exactly the files build uploaded, and verify checks out no source.
    uploaded = [
        s["with"]["name"] for s in jobs["build"]["steps"] if uses(s, "actions/upload-artifact")
    ]
    downloaded = {
        name: [
            s["with"]["name"] for s in jobs[name]["steps"] if uses(s, "actions/download-artifact")
        ]
        for name in ("verify", "publish")
    }
    assert len(uploaded) == 1 and downloaded == {"verify": uploaded, "publish": uploaded}
    assert not [s for s in jobs["verify"]["steps"] if uses(s, "actions/checkout")]


def test_only_the_publish_job_can_get_an_oidc_token() -> None:
    assert workflow("release.yml")["permissions"] == {"contents": "read"}
    assert workflow("ci.yml")["permissions"] == {"contents": "read"}
    assert "id-token" not in keys(workflow("ci.yml"))
    holders = []
    for path in WORKFLOW_FILES:
        doc = load(path)
        if "jobs" not in doc:
            continue
        blocks = [("(workflow)", doc.get("permissions"))]
        blocks += [(name, job.get("permissions")) for name, job in doc["jobs"].items()]
        for job_name, permissions in blocks:
            if permissions == "write-all":  # write-all includes id-token: write
                holders.append((path.name, job_name, "write-all"))
            elif isinstance(permissions, dict) and "id-token" in permissions:
                holders.append((path.name, job_name, permissions["id-token"]))
    assert holders == [("release.yml", "publish", "write")]


def test_no_checkout_keeps_the_job_token_on_disk() -> None:
    checkouts = [
        (path.name, step)
        for path in WORKFLOW_FILES
        for step in steps_of(load(path))
        if uses(step, "actions/checkout")
    ]
    assert checkouts
    kept = [
        name
        for name, step in checkouts
        if (step.get("with") or {}).get("persist-credentials") is not False
    ]
    assert kept == []


def test_every_action_is_pinned_by_commit() -> None:
    # A tag can be moved to other code; a commit cannot. The comment names the tag for readers and
    # for Dependabot, which updates both.
    found = [
        (path.relative_to(ROOT).as_posix(), line.strip())
        for path in WORKFLOW_FILES
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(- )?uses:", line)
    ]
    assert found
    unpinned = [
        u
        for u in found
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

"""CLI surface tests for ``codex-broker``.

Most tests exercise ``main`` in process. One smoke test additionally installs
the local project into a disposable virtual environment built from a temporary
copy of the project, so nothing here installs into Bob's global environment,
reaches a network, writes build artifacts into the checkout, or invokes real
WorkBuddy.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from codex_task_broker.cli import main

TASK_ID = "TASK-CLI"
TARGET_FILE = "src/example.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
DENIED_SENTINEL = "CTB_CLI_PARENT_SENTINEL"
ALLOWED_SENTINEL = "CTB_CLI_ALLOWED_SENTINEL"
BASE_ENVIRONMENT_ALLOW = ["PATH"]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def _init_repo(worktree: Path) -> str:
    worktree.mkdir(parents=True, exist_ok=True)
    _git(worktree, "init", "--quiet")
    _git(worktree, "config", "user.email", "cli@example.invalid")
    _git(worktree, "config", "user.name", "CLI Test")
    _git(worktree, "config", "commit.gpgsign", "false")
    target = worktree / TARGET_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 0\n", encoding="utf-8")
    _git(worktree, "add", "--all")
    _git(worktree, "commit", "--quiet", "-m", "base commit")
    return _git(worktree, "rev-parse", "HEAD")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _contributor(path: Path, base_sha: str, briefing_sha256: str, **options) -> None:
    commit = options.get("commit", True)
    exit_code = options.get("exit_code", 0)
    env_dump_path = options.get("env_dump_path")
    message = options.get(
        "message",
        "feat: cli mock change\n\n"
        + "\n".join(
            [
                f"Task-ID: {TASK_ID}",
                "Task-Revision: 1",
                "Attempt: 1",
                f"Base-SHA: {base_sha}",
                f"Briefing-SHA256: {briefing_sha256}",
            ]
        ),
    )
    source = f"""
import json
import os
import pathlib
import subprocess
import sys

repo = pathlib.Path.cwd()
if {env_dump_path!r} is not None:
    pathlib.Path({env_dump_path!r}).write_text(
        json.dumps(dict(os.environ)), encoding="utf-8"
    )
if {commit!r}:
    target = repo / {TARGET_FILE!r}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\\n", encoding="utf-8")
    subprocess.run(["git", "add", "--all"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", {message!r}], cwd=repo, check=True
    )
sys.exit({exit_code!r})
"""
    path.write_text(source, encoding="utf-8")


def _build_request(
    tmp_path: Path,
    *,
    base_sha: str | None = None,
    verification_commands: list[list[str]] | None = None,
    environment_allow: list[str] | None = None,
    **contributor_options: object,
) -> Path:
    worktree = tmp_path / "worktree"
    head_sha = _init_repo(worktree)
    effective_base = base_sha or head_sha

    briefing_path = tmp_path / "briefing.json"
    work_order_path = tmp_path / "work-order.json"
    _write_json(
        briefing_path,
        {
            "task_id": TASK_ID,
            "task_revision": 1,
            "attempt": 1,
            "base_sha": effective_base,
            "objective": "one disposable cli contribution",
        },
    )
    briefing_sha256 = _canonical_sha256(
        json.loads(briefing_path.read_text(encoding="utf-8"))
    )
    _write_json(
        work_order_path,
        {
            "task_id": TASK_ID,
            "task_revision": 1,
            "attempt": 1,
            "base_sha": effective_base,
            "briefing_sha256": briefing_sha256,
            "allowed_files": [TARGET_FILE],
            "forbidden_files": [".env"],
        },
    )

    contributor_path = tmp_path / "contributor.py"
    _contributor(
        contributor_path, effective_base, briefing_sha256, **contributor_options
    )

    request_path = tmp_path / "run-request.json"
    request_path.write_text(
        json.dumps(
            {
                "schema": "codex-task-broker-run-request",
                "schema_version": 1,
                "mode": "mock_only",
                "task_id": TASK_ID,
                "task_revision": 1,
                "attempt": 1,
                "work_order_path": str(work_order_path),
                "briefing_path": str(briefing_path),
                "worktree_path": str(worktree),
                "run_store_path": str(tmp_path / "run-store"),
                "base_sha": effective_base,
                "briefing_sha256": briefing_sha256,
                "allowed_files": [TARGET_FILE],
                "forbidden_files": [".env"],
                "contributor": {
                    "executable": sys.executable,
                    "argv": [str(contributor_path)],
                    "timeout_seconds": 120,
                    "environment_allow": list(
                        BASE_ENVIRONMENT_ALLOW
                        if environment_allow is None
                        else environment_allow
                    ),
                },
                "verification_commands": verification_commands
                or [[sys.executable, "-c", "print('verified')"]],
            }
        ),
        encoding="utf-8",
    )
    return request_path


def _stdout_json(capsys: pytest.CaptureFixture[str]) -> dict:
    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert isinstance(value, dict)
    return value


def test_help_exits_zero_and_lists_both_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "validate" in out
    assert "run" in out


def test_no_subcommand_exits_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert excinfo.value.code == 2
    assert capsys.readouterr().err


def test_validate_accepts_a_valid_request_and_prints_one_json_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path)

    exit_code = main(["validate", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 0
    assert payload["command"] == "validate"
    assert payload["state"] == "VALIDATED"
    assert payload["ready"] is True
    assert payload["errors"] == []


def test_validate_success_is_validated_and_never_review_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Validation produces no execution evidence, so it cannot claim review readiness."""
    request_path = _build_request(tmp_path)

    exit_code = main(["validate", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 0
    assert payload["state"] == "VALIDATED"
    assert payload["state"] != "REVIEW_READY"


def test_validate_rejects_a_wrong_base_sha_with_exit_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path, base_sha="0" * 40)

    exit_code = main(["validate", str(request_path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"
    assert "base_sha_mismatch" in payload["errors"]
    assert captured.err


def test_validate_rejects_an_unknown_request_field_with_exit_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path)
    data = json.loads(request_path.read_text(encoding="utf-8"))
    data["allow_push"] = True
    request_path.write_text(json.dumps(data), encoding="utf-8")

    exit_code = main(["validate", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"
    assert any("allow_push" in error for error in payload["errors"])


def test_validate_rejects_a_non_mock_mode_with_exit_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path)
    data = json.loads(request_path.read_text(encoding="utf-8"))
    data["mode"] = "project_prototype"
    request_path.write_text(json.dumps(data), encoding="utf-8")

    exit_code = main(["validate", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 2
    assert any("mock_only" in error for error in payload["errors"])


def test_validate_rejects_a_missing_request_file_with_exit_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["validate", str(tmp_path / "absent.json")])

    payload = _stdout_json(capsys)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"


def test_validate_does_not_start_the_contributor(tmp_path: Path) -> None:
    request_path = _build_request(tmp_path)

    main(["validate", str(request_path)])

    worktree = Path(json.loads(request_path.read_text(encoding="utf-8"))["worktree_path"])
    assert _git(worktree, "rev-list", "--count", "HEAD") == "1"


def test_run_reaches_review_ready_with_exit_code_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path)

    exit_code = main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 0
    assert payload["command"] == "run"
    assert payload["state"] == "REVIEW_READY"
    assert payload["errors"] == []
    assert payload["codebuddy_invoked"] is False
    assert payload["snapshot_sha"]


def test_run_gives_the_contributor_only_allowlisted_environment_variables(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DENIED_SENTINEL, "parent-only-value")
    monkeypatch.setenv(ALLOWED_SENTINEL, "explicitly-allowed-value")
    dump = tmp_path / "contributor-environment.json"
    request_path = _build_request(
        tmp_path,
        environment_allow=[ALLOWED_SENTINEL, *BASE_ENVIRONMENT_ALLOW],
        env_dump_path=str(dump),
    )

    exit_code = main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    child_environment = json.loads(dump.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["state"] == "REVIEW_READY"
    assert child_environment[ALLOWED_SENTINEL] == "explicitly-allowed-value"
    assert DENIED_SENTINEL not in child_environment


def test_run_repeats_validation_and_exits_two_on_preflight_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path, base_sha="0" * 40)

    exit_code = main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"
    assert "base_sha_mismatch" in payload["errors"]


def test_run_exits_three_when_the_contributor_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path, commit=False, exit_code=5)

    exit_code = main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 3
    assert payload["state"] == "CONTRIBUTOR_STOPPED"


def test_run_exits_four_when_evidence_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(
        tmp_path,
        verification_commands=[[sys.executable, "-c", "raise SystemExit(1)"]],
    )

    exit_code = main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 4
    assert payload["state"] == "EVIDENCE_FAILED"
    assert "verification_failed:1" in payload["errors"]


def test_run_exits_five_on_an_unexpected_internal_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = _build_request(tmp_path)

    def _boom(_request: object) -> None:
        raise RuntimeError("unexpected coordinator failure")

    monkeypatch.setattr("codex_task_broker.cli.run_once", _boom)

    exit_code = main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    assert exit_code == 5
    assert payload["state"] == "INTERNAL_ERROR"


def test_every_terminal_result_prints_exactly_one_json_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path)

    main(["run", str(request_path)])

    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert len(out.strip().splitlines()) >= 1
    json.loads(out)


def test_run_reports_the_external_run_store_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path = _build_request(tmp_path)

    main(["run", str(request_path)])

    payload = _stdout_json(capsys)
    run_store = Path(payload["run_store_path"])
    worktree = Path(json.loads(request_path.read_text(encoding="utf-8"))["worktree_path"])
    assert run_store.is_dir()
    with pytest.raises(ValueError):
        run_store.relative_to(worktree)


def test_pyproject_registers_the_console_script() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]

    assert scripts["codex-broker"] == "codex_task_broker.cli:main"


def test_public_identity_is_codex_task_broker() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "codex-task-broker"
    assert data["project"]["scripts"] == {
        "codex-broker": "codex_task_broker.cli:main"
    }
    assert "codex-workbuddy" not in data["project"]["scripts"]


def test_old_runtime_namespace_is_absent() -> None:
    assert not (REPO_ROOT / "src" / "bob_skills").exists()


def test_public_identity_cli_result_schema_is_codex_task_broker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The machine-readable CLI result schema carries the new identity."""
    request_path = _build_request(tmp_path)

    main(["validate", str(request_path)])

    payload = _stdout_json(capsys)
    assert payload["schema"] == "codex-task-broker-cli-result"


def test_public_identity_command_profile_id_is_codex_task_broker() -> None:
    """The persisted command profile identifier carries the new identity."""
    from codex_task_broker.profile import PROFILE_ID

    assert PROFILE_ID == "codex-task-broker-mock-contributor-v1"


def test_package_spawns_no_hardcoded_agent_executable() -> None:
    """Only the Run Request may name an executable.

    A substring scan for "workbuddy" would match a product name, so this
    instead asserts that no package module hardcodes an agent binary or a
    non-mock mode into a spawned command.
    """
    package = REPO_ROOT / "src" / "codex_task_broker"

    for module in sorted(package.glob("*.py")):
        source = module.read_text(encoding="utf-8").lower()
        for forbidden in (
            '"workbuddy"',
            "'workbuddy'",
            '"codebuddy"',
            "'codebuddy'",
            "workbuddy.exe",
            "codebuddy.exe",
            "project_prototype",
            "shell=true",
        ):
            assert forbidden not in source, f"{module.name}: {forbidden}"


def test_runner_only_spawns_request_supplied_commands() -> None:
    """Contributor and verification argv come from the request, not the code.

    Only the leading executable name may be resolved to an absolute path, and
    that resolution happens in the broker, never through a shell.
    """
    runner_source = (
        REPO_ROOT / "src" / "codex_task_broker" / "runner.py"
    ).read_text(encoding="utf-8")

    assert "[resolve_executable(profile.executable), *profile.argv]" in runner_source
    assert "shell=False" in runner_source
    assert "shell=True" not in runner_source


def test_runner_never_passes_the_parent_environment_to_a_child() -> None:
    """No spawned child may be started with an inherited environment."""
    runner_source = (
        REPO_ROOT / "src" / "codex_task_broker" / "runner.py"
    ).read_text(encoding="utf-8")

    assert "env=os.environ" not in runner_source
    assert "env=dict(os.environ)" not in runner_source
    assert runner_source.count("env=child_environment") == 2


def _offline_environment() -> dict[str, str]:
    """Environment for packaging subprocesses with the index disabled."""
    environment = dict(os.environ)
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _copy_installable_project(destination: Path) -> Path:
    """Copy only the packaging inputs, so no build artifact enters the checkout."""
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copy2(REPO_ROOT / "README.md", destination / "README.md")
    shutil.copytree(
        REPO_ROOT / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return destination


def test_disposable_install_exposes_the_console_command(tmp_path: Path) -> None:
    """A throwaway virtual environment must expose a working console command.

    The environment is created with ``--system-site-packages`` only so the
    existing build backend is importable without a network download; the
    project itself is installed into the disposable environment, never into
    Bob's global environment.
    """
    project = _copy_installable_project(tmp_path / "project")
    venv_dir = tmp_path / "venv"
    environment = _offline_environment()

    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    scripts = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    venv_python = scripts / ("python.exe" if os.name == "nt" else "python")
    console_script = scripts / (
        "codex-broker.exe" if os.name == "nt" else "codex-broker"
    )

    install = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-build-isolation",
            "--no-deps",
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    assert console_script.is_file()

    help_result = subprocess.run(
        [str(console_script), "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    assert "validate" in help_result.stdout
    assert "run" in help_result.stdout

    request_path = _build_request(tmp_path)
    validate_result = subprocess.run(
        [str(console_script), "validate", str(request_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    payload = json.loads(validate_result.stdout)
    assert validate_result.returncode == 0, validate_result.stderr
    assert payload["command"] == "validate"
    assert payload["state"] == "VALIDATED"
    assert payload["ready"] is True

    assert not (REPO_ROOT / "build").exists()
    assert not list((REPO_ROOT / "src").glob("*.egg-info"))

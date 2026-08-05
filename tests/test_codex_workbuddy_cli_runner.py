"""Disposable-Git tests for the one-shot mock-only Runner.

Every test builds a throwaway Git repository, runs one explicitly configured
local mock Contributor, and asserts that the Runner recalculates Git,
Snapshot, scope, trailer, workspace, and verification facts itself.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bob_skills.codex_workbuddy_coordinator.artifacts import (
    read_manifest,
    read_result,
)
from bob_skills.codex_workbuddy_coordinator.request import RunRequest
from bob_skills.codex_workbuddy_coordinator.runner import (
    ValidationResult,
    resolve_executable,
    run_once,
    validate_request,
)

TASK_ID = "TASK-RUNNER"
TARGET_FILE = "src/example.py"
DENIED_SENTINEL = "CWBC_PARENT_SENTINEL"
ALLOWED_SENTINEL = "CWBC_ALLOWED_SENTINEL"
# The mock Contributor spawns Git itself, so it needs one harmless allowlisted
# variable. Everything else must stay in the coordinator process.
BASE_ENVIRONMENT_ALLOW = ["PATH"]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _force_remove(func, path, exc) -> None:
    """Git keeps object files read-only on Windows."""
    Path(path).chmod(0o700)
    func(path)


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
    _git(worktree, "config", "user.email", "runner@example.invalid")
    _git(worktree, "config", "user.name", "Runner Test")
    _git(worktree, "config", "commit.gpgsign", "false")
    target = worktree / TARGET_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 0\n", encoding="utf-8")
    _git(worktree, "add", "--all")
    _git(worktree, "commit", "--quiet", "-m", "base commit")
    return _git(worktree, "rev-parse", "HEAD")


def _trailers(base_sha: str, briefing_sha256: str) -> str:
    return "\n".join(
        [
            f"Task-ID: {TASK_ID}",
            "Task-Revision: 1",
            "Attempt: 1",
            f"Base-SHA: {base_sha}",
            f"Briefing-SHA256: {briefing_sha256}",
        ]
    )


def _contributor_script(
    path: Path,
    *,
    body: str = "",
    commit: bool = True,
    message: str | None = None,
    exit_code: int = 0,
    changed_file: str = TARGET_FILE,
    extra_commits: int = 0,
    sleep_seconds: float = 0.0,
    post_commit_body: str = "",
) -> None:
    """Write one disposable mock Contributor script.

    The script only edits files and creates commits in its own disposable
    repository. It never contacts a network, a credential store, or WorkBuddy.
    """
    source = f"""
import pathlib
import subprocess
import sys
import time

repo = pathlib.Path.cwd()


def git(*args):
    subprocess.run(["git", *args], cwd=repo, check=True)


time.sleep({sleep_seconds!r})
{body}
if {commit!r}:
    target = repo / {changed_file!r}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("VALUE = 1\\n", encoding="utf-8")
    git("add", "--all")
    git("commit", "--quiet", "-m", {message!r})
    for index in range({extra_commits!r}):
        extra = repo / {changed_file!r}
        extra.write_text("VALUE = %d\\n" % (index + 2), encoding="utf-8")
        git("add", "--all")
        git("commit", "--quiet", "-m", {message!r})
{post_commit_body}
sys.exit({exit_code!r})
"""
    path.write_text(source, encoding="utf-8")


def _env_dump_body(path: Path) -> str:
    """Contributor body that records the child's own environment verbatim."""
    return (
        "import json as _json\n"
        "import os as _os\n"
        "pathlib.Path({path!r}).write_text("
        "_json.dumps(dict(_os.environ)), encoding='utf-8')\n"
    ).format(path=str(path))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _build_case(
    tmp_path: Path,
    *,
    base_sha: str | None = None,
    allowed_files: list[str] | None = None,
    verification_commands: list[list[str]] | None = None,
    timeout_seconds: int = 120,
    run_store_name: str = "run-store",
    environment_allow: list[str] | None = None,
    **contributor_options: object,
) -> RunRequest:
    worktree = tmp_path / "worktree"
    head_sha = _init_repo(worktree)
    run_store = tmp_path / run_store_name

    briefing_path = tmp_path / "briefing.json"
    work_order_path = tmp_path / "work-order.json"
    effective_base = base_sha or head_sha

    _write_json(
        briefing_path,
        {
            "task_id": TASK_ID,
            "task_revision": 1,
            "attempt": 1,
            "base_sha": effective_base,
            "objective": "one disposable mock contribution",
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
            "allowed_files": allowed_files or [TARGET_FILE],
            "forbidden_files": [".env"],
        },
    )

    contributor_path = tmp_path / "contributor.py"
    contributor_options.setdefault(
        "message", "feat: mock change\n\n" + _trailers(effective_base, briefing_sha256)
    )
    _contributor_script(contributor_path, **contributor_options)

    request_data = {
        "schema": "codex-workbuddy-run-request",
        "schema_version": 1,
        "mode": "mock_only",
        "task_id": TASK_ID,
        "task_revision": 1,
        "attempt": 1,
        "work_order_path": str(work_order_path),
        "briefing_path": str(briefing_path),
        "worktree_path": str(worktree),
        "run_store_path": str(run_store),
        "base_sha": effective_base,
        "briefing_sha256": briefing_sha256,
        "allowed_files": allowed_files or [TARGET_FILE],
        "forbidden_files": [".env"],
        "contributor": {
            "executable": sys.executable,
            "argv": [str(contributor_path)],
            "timeout_seconds": timeout_seconds,
            "environment_allow": list(
                BASE_ENVIRONMENT_ALLOW if environment_allow is None
                else environment_allow
            ),
        },
        "verification_commands": verification_commands
        or [[sys.executable, "-c", "print('verified')"]],
    }
    request_path = tmp_path / "run-request.json"
    request_path.write_text(json.dumps(request_data), encoding="utf-8")
    return RunRequest.from_path(request_path)


def test_validate_request_accepts_a_clean_base_worktree(tmp_path: Path) -> None:
    request = _build_case(tmp_path)

    result = validate_request(request)

    assert isinstance(result, ValidationResult)
    assert result.ready is True
    assert result.errors == []


def test_validate_request_reports_validated_not_review_ready(tmp_path: Path) -> None:
    """Validation alone produces no execution evidence, so it cannot be review ready."""
    request = _build_case(tmp_path)

    result = validate_request(request)

    assert result.state == "VALIDATED"
    assert result.exit_code == 0


def test_validate_request_rejects_a_dirty_worktree(tmp_path: Path) -> None:
    request = _build_case(tmp_path)
    (request.worktree_path / "untracked.txt").write_text("dirt\n", encoding="utf-8")

    result = validate_request(request)

    assert result.ready is False
    assert "worktree_dirty" in result.errors


def test_validate_request_rejects_a_wrong_base_sha(tmp_path: Path) -> None:
    request = _build_case(tmp_path, base_sha="0" * 40)

    result = validate_request(request)

    assert result.ready is False
    assert "base_sha_mismatch" in result.errors


def test_validate_request_rejects_a_missing_git_repository(tmp_path: Path) -> None:
    request = _build_case(tmp_path)
    shutil.rmtree(request.worktree_path / ".git", onexc=_force_remove)

    result = validate_request(request)

    assert result.ready is False
    assert any("git" in error for error in result.errors)


def test_validate_request_rejects_a_briefing_hash_mismatch(tmp_path: Path) -> None:
    request = _build_case(tmp_path)
    request.briefing_path.write_text('{"task_id": "OTHER"}', encoding="utf-8")

    result = validate_request(request)

    assert result.ready is False
    assert "briefing_sha256_mismatch" in result.errors


def test_validate_request_binds_the_briefing_by_canonical_json(
    tmp_path: Path,
) -> None:
    """Reformatting the Briefing must not break binding; editing it must."""
    request = _build_case(tmp_path)
    briefing = json.loads(request.briefing_path.read_text(encoding="utf-8"))
    request.briefing_path.write_text(
        json.dumps(briefing, indent=4) + "\n", encoding="utf-8"
    )

    result = validate_request(request)

    assert hashlib.sha256(request.briefing_path.read_bytes()).hexdigest() != (
        request.briefing_sha256
    )
    assert result.ready is True
    assert "briefing_sha256_mismatch" not in result.errors


def test_validate_request_rejects_work_order_binding_drift(tmp_path: Path) -> None:
    request = _build_case(tmp_path)
    order = json.loads(request.work_order_path.read_text(encoding="utf-8"))
    order["task_id"] = "TASK-OTHER"
    _write_json(request.work_order_path, order)

    result = validate_request(request)

    assert result.ready is False
    assert "work_order_task_id" in result.errors


def test_run_once_reaches_review_ready_for_one_mock_contribution(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path)

    result = run_once(request)

    assert result.state == "REVIEW_READY"
    assert result.errors == []
    assert result.exit_code == 0
    assert result.codebuddy_invoked is False


def test_run_once_writes_every_documented_artifact(tmp_path: Path) -> None:
    request = _build_case(tmp_path)

    result = run_once(request)

    store = request.run_store_path
    for name in (
        "preflight.json",
        "command-profile.json",
        "contributor-stdout.log",
        "contributor-stderr.log",
        "verification-1-stdout.log",
        "verification-1-stderr.log",
        "execution-report.json",
        "evidence.json",
        "run-manifest.json",
        "review-input.json",
        "runner-result.json",
    ):
        assert (store / name).is_file(), name
    assert result.state == "REVIEW_READY"


def test_run_once_keeps_runtime_artifacts_out_of_the_commit(tmp_path: Path) -> None:
    request = _build_case(tmp_path)

    result = run_once(request)

    changed = _git(
        request.worktree_path,
        "diff",
        "--name-only",
        f"{request.base_sha}..{result.snapshot_sha}",
    ).splitlines()
    assert changed == [TARGET_FILE]
    assert _git(request.worktree_path, "status", "--porcelain") == ""


def test_run_once_binds_manifest_and_result_to_exact_artifact_bytes(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path)

    run_once(request)

    store = request.run_store_path
    manifest = read_manifest(store / "run-manifest.json", store / "evidence.json")
    result = read_result(
        store / "runner-result.json",
        store / "run-manifest.json",
        store / "evidence.json",
    )
    assert manifest["base_sha"] == request.base_sha
    assert manifest["workspace_clean"] is True
    assert result["state"] == "REVIEW_READY"
    assert result["codebuddy_invoked"] is False


def test_run_once_rejects_manifest_drift_after_the_run(tmp_path: Path) -> None:
    request = _build_case(tmp_path)
    run_once(request)
    store = request.run_store_path
    evidence_path = store / "evidence.json"
    evidence_path.write_text(
        evidence_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )

    with pytest.raises(ValueError):
        read_manifest(store / "run-manifest.json", evidence_path)


def test_run_once_recalculates_git_facts_instead_of_trusting_the_contributor(
    tmp_path: Path,
) -> None:
    request = _build_case(
        tmp_path,
        body=(
            "print('changed_files: []')\n"
            "print('verification: all green')\n"
            "print('state: REVIEW_READY')\n"
        ),
    )

    result = run_once(request)

    store = request.run_store_path
    evidence = json.loads((store / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["changed_files"] == [TARGET_FILE]
    assert evidence["parent_sha"] == request.base_sha
    assert evidence["implementation_sha"] == result.snapshot_sha
    assert evidence["snapshot_sha"] == result.snapshot_sha


def test_run_once_invokes_the_contributor_exactly_once(tmp_path: Path) -> None:
    counter = tmp_path / "invocations.log"
    request = _build_case(
        tmp_path,
        body=(
            "with open({path!r}, 'a', encoding='utf-8') as handle:\n"
            "    handle.write('call\\n')\n"
        ).format(path=str(counter)),
    )

    run_once(request)

    assert counter.read_text(encoding="utf-8").count("call") == 1


def test_run_once_fails_preflight_before_starting_the_contributor(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "started.log"
    request = _build_case(
        tmp_path,
        base_sha="0" * 40,
        body="open({path!r}, 'w', encoding='utf-8').write('started')\n".format(
            path=str(marker)
        ),
    )

    result = run_once(request)

    assert result.state == "PREFLIGHT_FAILED"
    assert result.exit_code == 2
    assert marker.exists() is False


def test_run_once_reports_contributor_stopped_on_nonzero_exit(tmp_path: Path) -> None:
    request = _build_case(tmp_path, commit=False, exit_code=3)

    result = run_once(request)

    assert result.state == "CONTRIBUTOR_STOPPED"
    assert result.exit_code == 3
    assert "contributor_nonzero" in result.errors


def test_run_once_reports_contributor_stopped_on_timeout(tmp_path: Path) -> None:
    request = _build_case(
        tmp_path, commit=False, sleep_seconds=5.0, timeout_seconds=1
    )

    result = run_once(request)

    assert result.state == "CONTRIBUTOR_STOPPED"
    assert result.exit_code == 3
    assert "contributor_timeout" in result.errors


def test_run_once_reports_contributor_stopped_when_it_cannot_start(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path)
    request_path = tmp_path / "run-request.json"
    data = json.loads(request_path.read_text(encoding="utf-8"))
    data["contributor"]["executable"] = str(
        tmp_path / "no-such-contributor-executable"
    )
    request_path.write_text(json.dumps(data), encoding="utf-8")

    result = run_once(RunRequest.from_path(request_path))

    assert result.state == "CONTRIBUTOR_STOPPED"
    assert result.exit_code == 3
    assert "contributor_start_failed" in result.errors


def test_run_once_reports_evidence_failed_when_no_snapshot_is_created(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path, commit=False)

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "snapshot_missing" in result.errors


def test_run_once_reports_evidence_failed_on_parent_mismatch(tmp_path: Path) -> None:
    request = _build_case(tmp_path, extra_commits=1)

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "parent_sha_mismatch" in result.errors


def test_run_once_reports_evidence_failed_for_out_of_scope_files(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path, changed_file="src/other.py")

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "out_of_scope_files" in result.errors
    evidence = json.loads(
        (request.run_store_path / "evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["out_of_scope_files"] == ["src/other.py"]


def test_run_once_reports_evidence_failed_for_missing_trailers(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path, message="feat: mock change without trailers")

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert any(error.startswith("trailer:missing:") for error in result.errors)


def test_run_once_reports_evidence_failed_for_mismatched_trailers(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    request = _build_case(tmp_path)
    bad_message = "feat: mock change\n\n" + "\n".join(
        [
            f"Task-ID: {TASK_ID}",
            "Task-Revision: 1",
            "Attempt: 9",
            f"Base-SHA: {request.base_sha}",
            f"Briefing-SHA256: {request.briefing_sha256}",
        ]
    )
    _contributor_script(tmp_path / "contributor.py", message=bad_message)
    assert worktree.is_dir()

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "trailer:mismatch:Attempt" in result.errors


def test_run_once_reports_evidence_failed_for_non_contiguous_trailers(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path)
    split_message = "\n".join(
        [
            "feat: mock change",
            "",
            f"Task-ID: {TASK_ID}",
            "Task-Revision: 1",
            "",
            "Attempt: 1",
            f"Base-SHA: {request.base_sha}",
            f"Briefing-SHA256: {request.briefing_sha256}",
        ]
    )
    _contributor_script(tmp_path / "contributor.py", message=split_message)

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "trailer:snapshot_trailers_not_contiguous" in result.errors


def test_run_once_reports_evidence_failed_for_a_failing_verification(
    tmp_path: Path,
) -> None:
    request = _build_case(
        tmp_path,
        verification_commands=[[sys.executable, "-c", "raise SystemExit(7)"]],
    )

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "verification_failed:1" in result.errors
    evidence = json.loads(
        (request.run_store_path / "evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verification"][0]["exit_code"] == 7


def test_run_once_reports_evidence_failed_for_a_verification_timeout(
    tmp_path: Path,
) -> None:
    request = _build_case(
        tmp_path,
        timeout_seconds=1,
        verification_commands=[[sys.executable, "-c", "import time; time.sleep(5)"]],
    )

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "verification_timeout:1" in result.errors
    evidence = json.loads(
        (request.run_store_path / "evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verification"][0]["timed_out"] is True


def test_run_once_reports_evidence_failed_for_a_dirty_post_run_workspace(
    tmp_path: Path,
) -> None:
    request = _build_case(
        tmp_path,
        post_commit_body=(
            "(repo / 'leftover.txt').write_text('dirty', encoding='utf-8')\n"
        ),
    )

    result = run_once(request)

    assert result.state == "EVIDENCE_FAILED"
    assert result.exit_code == 4
    assert "workspace_dirty" in result.errors


def test_run_once_runs_verification_commands_as_argv_without_a_shell(
    tmp_path: Path,
) -> None:
    request = _build_case(
        tmp_path,
        verification_commands=[
            [sys.executable, "-c", "import sys; print(sys.argv[1:])", "a b", "c|d"]
        ],
    )

    result = run_once(request)

    assert result.state == "REVIEW_READY"
    stdout = (request.run_store_path / "verification-1-stdout.log").read_text(
        encoding="utf-8"
    )
    assert stdout.strip() == "['a b', 'c|d']"


def test_run_once_denies_an_unlisted_parent_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Contributor must not inherit the coordinator process environment."""
    monkeypatch.setenv(DENIED_SENTINEL, "parent-only-value")
    dump = tmp_path / "contributor-environment.json"
    request = _build_case(tmp_path, body=_env_dump_body(dump))

    result = run_once(request)

    child_environment = json.loads(dump.read_text(encoding="utf-8"))
    assert result.state == "REVIEW_READY"
    assert DENIED_SENTINEL not in child_environment
    assert set(child_environment) == set(BASE_ENVIRONMENT_ALLOW)


def test_run_once_passes_only_allowlisted_variables_to_the_contributor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DENIED_SENTINEL, "parent-only-value")
    monkeypatch.setenv(ALLOWED_SENTINEL, "explicitly-allowed-value")
    dump = tmp_path / "contributor-environment.json"
    request = _build_case(
        tmp_path,
        body=_env_dump_body(dump),
        environment_allow=[ALLOWED_SENTINEL, *BASE_ENVIRONMENT_ALLOW],
    )

    result = run_once(request)

    child_environment = json.loads(dump.read_text(encoding="utf-8"))
    assert result.state == "REVIEW_READY"
    assert child_environment[ALLOWED_SENTINEL] == "explicitly-allowed-value"
    assert DENIED_SENTINEL not in child_environment
    assert set(child_environment) == {ALLOWED_SENTINEL, *BASE_ENVIRONMENT_ALLOW}


def test_run_once_applies_the_same_environment_allowlist_to_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DENIED_SENTINEL, "parent-only-value")
    monkeypatch.setenv(ALLOWED_SENTINEL, "explicitly-allowed-value")
    request = _build_case(
        tmp_path,
        environment_allow=[ALLOWED_SENTINEL, *BASE_ENVIRONMENT_ALLOW],
        verification_commands=[
            [
                sys.executable,
                "-c",
                "import json, os, sys; sys.stdout.write(json.dumps(dict(os.environ)))",
            ]
        ],
    )

    result = run_once(request)

    child_environment = json.loads(
        (request.run_store_path / "verification-1-stdout.log").read_text(
            encoding="utf-8"
        )
    )
    assert result.state == "REVIEW_READY"
    assert child_environment[ALLOWED_SENTINEL] == "explicitly-allowed-value"
    assert DENIED_SENTINEL not in child_environment


def test_run_once_omits_an_allowlisted_variable_that_the_parent_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ALLOWED_SENTINEL, raising=False)
    dump = tmp_path / "contributor-environment.json"
    request = _build_case(
        tmp_path,
        body=_env_dump_body(dump),
        environment_allow=[ALLOWED_SENTINEL, *BASE_ENVIRONMENT_ALLOW],
    )

    result = run_once(request)

    child_environment = json.loads(dump.read_text(encoding="utf-8"))
    assert result.state == "REVIEW_READY"
    assert ALLOWED_SENTINEL not in child_environment


def test_resolve_executable_resolves_a_bare_name_without_a_shell() -> None:
    resolved = Path(resolve_executable("git"))

    assert resolved.is_absolute()
    assert resolved.is_file()
    assert resolve_executable(sys.executable) == sys.executable


def test_run_once_runs_a_bare_name_verification_command(tmp_path: Path) -> None:
    """A restricted child environment must not break ordinary command names."""
    request = _build_case(tmp_path, verification_commands=[["git", "--version"]])

    result = run_once(request)

    stdout = (request.run_store_path / "verification-1-stdout.log").read_text(
        encoding="utf-8"
    )
    assert result.state == "REVIEW_READY"
    assert stdout.startswith("git version")


def test_run_once_treats_the_contributor_report_as_advisory_only(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path)

    run_once(request)

    report = json.loads(
        (request.run_store_path / "execution-report.json").read_text(encoding="utf-8")
    )
    assert report["advisory"] is True
    assert report["claims_are_authoritative"] is False


def test_run_once_never_records_a_workbuddy_invocation(tmp_path: Path) -> None:
    request = _build_case(tmp_path)

    result = run_once(request)

    store = request.run_store_path
    runner_result = json.loads(
        (store / "runner-result.json").read_text(encoding="utf-8")
    )
    assert runner_result["codebuddy_invoked"] is False
    assert result.codebuddy_invoked is False


def test_run_once_stops_at_review_ready_without_review_or_merge(
    tmp_path: Path,
) -> None:
    request = _build_case(tmp_path)

    result = run_once(request)

    review = json.loads(
        (request.run_store_path / "review-input.json").read_text(encoding="utf-8")
    )
    assert result.state == "REVIEW_READY"
    assert review["review_required"] is True
    assert review["state"] == "REVIEW_READY"
    assert "decision" not in review

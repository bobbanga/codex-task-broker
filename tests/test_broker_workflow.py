"""End-to-end tests for one brokered run against an injected fake adapter.

No test discovers, installs, or launches a real executor. The fake adapter
implements the same terminal-state contract and edits the isolated worktree
directly, so orchestration, evidence, and handoff can be proven without
consuming model capacity.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from codex_task_broker.broker import (
    Broker,
    BrokerError,
    BrokerRequest,
    ExecutionSpec,
    TaskBrief,
    build_prompt,
)

TARGET = "src/example.py"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "--quiet")
    git(source, "config", "user.email", "broker@example.invalid")
    git(source, "config", "user.name", "Broker Test")
    git(source, "config", "commit.gpgsign", "false")
    target = source / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 0\n", encoding="utf-8")
    git(source, "add", "--all")
    git(source, "commit", "--quiet", "-m", "base commit")
    return source


# --- fake adapter -------------------------------------------------------


@dataclass
class FakeExecutorResult:
    """Terminal facts in the shape the broker consumes."""

    state: str
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"state": self.state, "errors": list(self.errors)}


@dataclass
class FakeAdapter:
    """One injected adapter with fully scripted behaviour.

    ``writes`` maps repository-relative paths to their new contents. ``commit``
    controls whether the fake creates a commit, so the broker's independent Git
    checks can be exercised in both directions.
    """

    state: str = "EXECUTOR_OK"
    errors: tuple[str, ...] = ()
    writes: dict = field(default_factory=lambda: {TARGET: "VALUE = 1\n"})
    commit: bool = True
    leave_dirty: bool = False
    calls: list = field(default_factory=list)

    def execute(self, spec: ExecutionSpec) -> FakeExecutorResult:
        self.calls.append(spec)
        if self.state != "EXECUTOR_OK":
            return FakeExecutorResult(self.state, self.errors)

        worktree = Path(spec.worktree_path)
        for relative, content in self.writes.items():
            path = worktree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")

        if self.commit:
            git(worktree, "config", "user.email", "fake@example.invalid")
            git(worktree, "config", "user.name", "Fake Executor")
            git(worktree, "config", "commit.gpgsign", "false")
            git(worktree, "add", "--all")
            git(worktree, "commit", "--quiet", "-m", "fake: apply requested change")

        if self.leave_dirty:
            (worktree / "scratch.tmp").write_text("left behind\n", encoding="utf-8")

        return FakeExecutorResult("EXECUTOR_OK")


def _brief(**overrides) -> TaskBrief:
    data = {
        "schema": "codex-task-broker-task-brief",
        "schema_version": 1,
        "task_id": "demo-001",
        "objective": "Set VALUE to 1.",
        "allowed_files": [TARGET],
        "verification_commands": [[sys.executable, "-c", "print('verified')"]],
        "model": "test-model",
    }
    data.update(overrides)
    return TaskBrief.from_dict(data)


def _request(repo: Path, tmp_path: Path, **overrides) -> BrokerRequest:
    return BrokerRequest(
        source_repo=repo,
        brief=overrides.pop("brief", _brief(**overrides)),
        run_root=tmp_path / "runs",
    )


# --- the successful path ------------------------------------------------


def test_broker_reaches_review_ready_with_the_fake_adapter(
    repo: Path, tmp_path: Path
) -> None:
    request = _request(repo, tmp_path)

    result = Broker(executor=FakeAdapter()).run(request)

    assert result.state == "REVIEW_READY"
    assert result.errors == ()
    assert result.worktree_path.exists()
    assert result.run_store_path.exists()
    assert result.changed_files == (TARGET,)
    assert result.verification_results[0].exit_code == 0
    assert result.exit_code == 0


def test_run_store_stays_outside_the_worktree(repo: Path, tmp_path: Path) -> None:
    result = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    with pytest.raises(ValueError):
        result.run_store_path.relative_to(result.worktree_path)


def test_the_adapter_is_invoked_exactly_once(repo: Path, tmp_path: Path) -> None:
    adapter = FakeAdapter()

    Broker(executor=adapter).run(_request(repo, tmp_path))

    assert len(adapter.calls) == 1


def test_evidence_and_manifest_are_written_to_the_run_store(
    repo: Path, tmp_path: Path
) -> None:
    result = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert evidence["state"] == "REVIEW_READY"
    assert evidence["changed_files"] == [TARGET]
    assert evidence["base_sha"] == result.base_sha
    assert evidence["implementation_sha"] != result.base_sha
    assert result.manifest_path.is_file()


def test_the_brief_and_binding_are_frozen_before_execution(
    repo: Path, tmp_path: Path
) -> None:
    result = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    binding = json.loads(
        (result.run_store_path / "run-binding.json").read_text(encoding="utf-8")
    )
    assert binding["base_sha"] == result.base_sha
    assert binding["allowed_files"] == [TARGET]
    assert binding["brief_sha256"]
    assert (result.run_store_path / "task-brief.json").is_file()


def test_manifest_binds_the_frozen_command_profile(repo: Path, tmp_path: Path) -> None:
    result = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    profile_path = result.run_store_path / "command-profile.json"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    import hashlib

    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    assert manifest["command_profile_sha256"] == profile_sha
    assert manifest["command_profile_sha256"] != manifest["briefing_sha256"]


def test_the_source_repository_is_never_modified(repo: Path, tmp_path: Path) -> None:
    before = git(repo, "rev-parse", "HEAD")

    Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    assert git(repo, "rev-parse", "HEAD") == before
    assert (repo / TARGET).read_text(encoding="utf-8") == "VALUE = 0\n"
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_the_result_never_claims_a_merge_or_push(repo: Path, tmp_path: Path) -> None:
    result = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    payload = result.to_dict()
    assert payload["merged"] is False
    assert payload["pushed"] is False
    assert payload["review_required"] is True


def test_executor_claims_are_recorded_as_advisory(repo: Path, tmp_path: Path) -> None:
    result = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    report = json.loads(
        (result.run_store_path / "execution-report.json").read_text(encoding="utf-8")
    )
    assert report["advisory"] is True
    assert report["claims_are_authoritative"] is False


# --- independent evidence recalculation ---------------------------------


def test_out_of_scope_changes_fail_evidence(repo: Path, tmp_path: Path) -> None:
    adapter = FakeAdapter(writes={TARGET: "VALUE = 1\n", "src/other.py": "X = 1\n"})

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    assert result.state == "EVIDENCE_FAILED"
    assert "out_of_scope_files" in result.errors
    assert result.out_of_scope_files == ("src/other.py",)
    assert result.exit_code == 4


def test_a_run_without_a_commit_fails_evidence(repo: Path, tmp_path: Path) -> None:
    adapter = FakeAdapter(commit=False)

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    assert result.state == "EVIDENCE_FAILED"
    assert "no_commit_produced" in result.errors


def test_a_dirty_workspace_fails_evidence(repo: Path, tmp_path: Path) -> None:
    adapter = FakeAdapter(leave_dirty=True)

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    assert result.state == "EVIDENCE_FAILED"
    assert "workspace_dirty" in result.errors


def test_failing_verification_fails_evidence(repo: Path, tmp_path: Path) -> None:
    brief = _brief(
        verification_commands=[[sys.executable, "-c", "raise SystemExit(1)"]]
    )

    result = Broker(executor=FakeAdapter()).run(
        BrokerRequest(source_repo=repo, brief=brief, run_root=tmp_path / "runs")
    )

    assert result.state == "EVIDENCE_FAILED"
    assert "verification_failed:1" in result.errors
    assert result.verification_results[0].passed is False


# --- executor and preflight failures ------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        "EXECUTOR_TIMEOUT",
        "EXECUTOR_FAILED",
        "EXECUTOR_OUTPUT_INVALID",
        "EXECUTOR_PERMISSION_REQUIRED",
    ],
)
def test_every_executor_stop_state_stops_the_run(
    repo: Path, tmp_path: Path, state: str
) -> None:
    adapter = FakeAdapter(state=state, errors=("stopped",))

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    assert result.state == "CONTRIBUTOR_STOPPED"
    assert result.executor_state == state
    assert result.exit_code == 3


def test_a_failed_run_preserves_its_worktree_and_reports_cleanup(
    repo: Path, tmp_path: Path
) -> None:
    adapter = FakeAdapter(state="EXECUTOR_FAILED", errors=("boom",))

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    assert result.worktree_path.is_dir()
    assert result.cleanup_command[0] == "git"
    assert str(result.worktree_path) in result.cleanup_command
    payload = json.loads(result.result_path.read_text(encoding="utf-8"))
    assert payload["worktree_preserved"] is True


def test_a_dirty_source_repository_stops_at_preflight(
    repo: Path, tmp_path: Path
) -> None:
    (repo / TARGET).write_text("VALUE = 99\n", encoding="utf-8")
    adapter = FakeAdapter()

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    assert result.state == "PREFLIGHT_FAILED"
    assert result.errors == ("source_dirty",)
    assert result.exit_code == 2
    assert adapter.calls == []


def test_a_duplicate_task_id_stops_at_preflight(repo: Path, tmp_path: Path) -> None:
    broker = Broker(executor=FakeAdapter())
    broker.run(_request(repo, tmp_path))

    second = Broker(executor=FakeAdapter()).run(_request(repo, tmp_path))

    assert second.state == "PREFLIGHT_FAILED"
    assert second.errors == ("duplicate_task_id",)


def test_a_run_root_inside_the_source_repository_is_rejected(repo: Path) -> None:
    with pytest.raises(BrokerError) as excinfo:
        BrokerRequest(source_repo=repo, brief=_brief(), run_root=repo / "runs")

    assert excinfo.value.code == "invalid_request"


def test_an_executor_must_be_injected() -> None:
    with pytest.raises(BrokerError) as excinfo:
        Broker(executor=None)

    assert excinfo.value.code == "missing_executor"


# --- task brief contract ------------------------------------------------


def test_brief_rejects_unknown_fields() -> None:
    with pytest.raises(BrokerError, match="unexpected"):
        TaskBrief.from_dict(
            {
                "schema": "codex-task-broker-task-brief",
                "schema_version": 1,
                "task_id": "t",
                "objective": "do it",
                "allowed_files": ["a.py"],
                "verification_commands": [["py"]],
                "model": "m",
                "allow_push": True,
            }
        )


def test_brief_rejects_absolute_and_escaping_paths() -> None:
    for bad in ("C:/outside.py", "../outside.py", "src/../../outside.py"):
        with pytest.raises(BrokerError):
            _brief(allowed_files=[bad])


def test_brief_rejects_secret_shaped_environment_names() -> None:
    with pytest.raises(BrokerError, match="secret-shaped"):
        _brief(environment_allow=["API_TOKEN"])


def test_brief_rejects_a_string_verification_command() -> None:
    with pytest.raises(BrokerError):
        _brief(verification_commands=["pytest -q"])


def test_brief_requires_an_explicit_model() -> None:
    with pytest.raises(BrokerError):
        _brief(model="   ")


def test_brief_round_trips_and_hashes_stably(tmp_path: Path) -> None:
    brief = _brief()
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief.to_dict()), encoding="utf-8")

    assert TaskBrief.from_path(path).sha256() == brief.sha256()


def test_prompt_states_the_scope_and_forbids_external_effects() -> None:
    prompt = build_prompt(_brief())

    assert TARGET in prompt
    assert "only" in prompt
    for forbidden in ("push", "merge", "publish", "deploy", "install"):
        assert forbidden in prompt


def test_the_spec_handed_to_the_adapter_is_bounded(repo: Path, tmp_path: Path) -> None:
    adapter = FakeAdapter()

    result = Broker(executor=adapter).run(_request(repo, tmp_path))

    spec = adapter.calls[0]
    assert spec.worktree_path == result.worktree_path
    assert spec.run_store_path == result.run_store_path
    assert spec.model == "test-model"
    assert spec.timeout_seconds == 900

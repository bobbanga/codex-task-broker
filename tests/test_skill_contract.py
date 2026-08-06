"""Contract tests for the natural-language Skill and the brokered CLI surface.

The Skill is the front door for a non-technical user, so its governance rules
are asserted here as text contracts rather than left to review. These tests
never invoke a real executor.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from codex_task_broker.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "codex-task-broker"
SKILL = SKILL_DIR / "SKILL.md"
REFERENCE = SKILL_DIR / "references" / "request-contract.md"


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _reference_text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


# --- Skill file structure -----------------------------------------------


def test_skill_and_reference_exist() -> None:
    assert SKILL.is_file()
    assert REFERENCE.is_file()


def test_skill_has_name_and_description_frontmatter() -> None:
    text = _skill_text()
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert "name: codex-task-broker" in frontmatter
    assert "description:" in frontmatter


def test_skill_description_states_the_explicit_delegation_trigger() -> None:
    frontmatter = _skill_text().split("---", 2)[1].lower()
    assert "explicit" in frontmatter
    assert "delegat" in frontmatter


def test_skill_recognizes_the_standard_chinese_workbuddy_request() -> None:
    text = _skill_text()
    assert "继续当前项目，把下一项实现交给 WorkBuddy，你负责审核并提交候选结果。" in text


def test_skill_links_its_reference() -> None:
    assert "references/request-contract.md" in _skill_text()


# --- Skill governance rules ---------------------------------------------


def test_skill_triggers_only_on_explicit_delegation() -> None:
    lowered = _skill_text().lower()
    assert "only when the user explicitly asks" in lowered
    assert "ambiguity means no delegation" in lowered


def test_skill_keeps_planning_and_review_with_codex() -> None:
    lowered = _skill_text().lower()
    assert "planning" in lowered
    assert "review" in lowered
    assert "read the actual diff" in lowered


def test_skill_runs_doctor_before_the_first_task() -> None:
    text = _skill_text()
    assert "codex-broker doctor" in text
    lowered = text.lower()
    assert "before the first delegated task" in lowered
    assert "installation" in lowered


def test_skill_never_calls_the_executor_outside_the_broker() -> None:
    lowered = _skill_text().lower()
    assert "never call the executor directly" in lowered
    assert "goes through" in lowered


def test_skill_never_merges_pushes_or_publishes() -> None:
    lowered = _skill_text().lower()
    assert "never merge, push, open a pr, publish, or deploy" in lowered
    assert "the run ends at your review" in lowered


def test_skill_requires_approval_only_for_real_permission_expansion() -> None:
    lowered = _skill_text().lower()
    assert "never widen permissions" in lowered
    assert "let the user decide" in lowered
    assert "not a retry" in lowered


def test_skill_preserves_failed_worktrees() -> None:
    lowered = _skill_text().lower()
    assert "never delete a failed worktree" in lowered
    assert "cleanup command" in lowered


def test_skill_treats_executor_reports_as_non_authoritative() -> None:
    lowered = _skill_text().lower()
    assert "never present the executor's own summary as evidence" in lowered


def test_skill_hides_json_from_ordinary_users() -> None:
    lowered = _skill_text().lower()
    assert "do not show json" in lowered
    assert "unless the user is debugging" in lowered


def test_skill_delegates_one_task_per_run() -> None:
    assert "one task per run" in _skill_text().lower()


def test_skill_covers_every_terminal_state() -> None:
    text = _skill_text()
    for state in (
        "REVIEW_READY",
        "PREFLIGHT_FAILED",
        "CONTRIBUTOR_STOPPED",
        "EVIDENCE_FAILED",
    ):
        assert state in text, state


def test_skill_stays_thin_and_defers_implementation_detail() -> None:
    """The Skill must not restate adapter or runner internals."""
    lowered = _skill_text().lower()
    for leaked in (
        "--permission-mode",
        "--mcp-config",
        "--max-turns",
        "subprocess",
        "shell=false",
    ):
        assert leaked not in lowered, leaked


# --- reference contract -------------------------------------------------


def test_reference_documents_every_brief_field() -> None:
    from codex_task_broker.broker import BRIEF_KEYS

    text = _reference_text()
    for field in BRIEF_KEYS:
        assert f"`{field}`" in text, field


def test_reference_marks_required_and_optional_fields() -> None:
    from codex_task_broker.broker import BRIEF_REQUIRED

    text = _reference_text()
    required_section = text.split("### Required", 1)[1].split("### Optional", 1)[0]
    for field in BRIEF_REQUIRED:
        assert f"`{field}`" in required_section, field


def test_reference_example_parses_as_a_valid_brief() -> None:
    from codex_task_broker.broker import TaskBrief

    block = _reference_text().split("```json", 1)[1].split("```", 1)[0]
    brief = TaskBrief.from_dict(json.loads(block))

    assert brief.task_id
    assert brief.allowed_files
    assert brief.verification_commands


def test_reference_states_that_no_external_effect_is_requestable() -> None:
    lowered = _reference_text().lower()
    for effect in ("network", "credential", "push", "merge", "deploy", "publication"):
        assert effect in lowered
    assert "cannot be requested" in lowered


def test_reference_lists_the_terminal_states_and_exit_codes() -> None:
    text = _reference_text()
    for state in (
        "REVIEW_READY",
        "PREFLIGHT_FAILED",
        "CONTRIBUTOR_STOPPED",
        "EVIDENCE_FAILED",
        "INTERNAL_ERROR",
    ):
        assert state in text, state


def test_reference_does_not_copy_adapter_or_runner_implementation() -> None:
    lowered = _reference_text().lower()
    for leaked in ("subprocess.run", "def ", "import ", "--strict-mcp-config"):
        assert leaked not in lowered, leaked


# --- brokered CLI surface -----------------------------------------------


def test_run_accepts_the_brokered_options() -> None:
    args = build_parser().parse_args(
        ["run", "--repo", "C:/repo", "--brief", "C:/brief.json", "--executor",
         "workbuddy", "--json"]
    )

    assert args.command == "run"
    assert args.request is None
    assert args.repo == "C:/repo"
    assert args.brief == "C:/brief.json"
    assert args.json is True


def test_run_still_accepts_the_original_request_file() -> None:
    args = build_parser().parse_args(["run", "C:/run-request.json"])

    assert args.request == "C:/run-request.json"
    assert args.repo is None


def test_run_rejects_mixing_a_request_file_with_brokered_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["run", "C:/run-request.json", "--repo", "C:/repo"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"
    assert any("mutually exclusive" in error for error in payload["errors"])


def test_brokered_run_requires_repo_brief_and_executor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["run", "--repo", "C:/repo"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"
    assert any("--brief" in error for error in payload["errors"])
    assert any("--executor" in error for error in payload["errors"])


def test_brokered_run_reports_an_invalid_brief_without_running(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text('{"schema": "wrong"}', encoding="utf-8")

    exit_code = main(
        [
            "run",
            "--repo",
            str(tmp_path),
            "--brief",
            str(brief),
            "--executor",
            "workbuddy",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["state"] == "PREFLIGHT_FAILED"


def test_help_lists_the_brokered_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])

    out = capsys.readouterr().out
    assert excinfo.value.code == 0
    for flag in ("--repo", "--brief", "--executor", "--json"):
        assert flag in out, flag


def test_the_cli_exposes_no_merge_push_or_publish_command() -> None:
    parser = build_parser()
    actions = [
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    ]
    commands = set()
    for action in actions:
        if isinstance(action.choices, dict):
            commands.update(action.choices)

    assert commands == {"validate", "run", "doctor"}
    for forbidden in ("merge", "push", "publish", "deploy", "install"):
        assert forbidden not in commands


def test_a_brokered_run_reaches_review_ready_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI path is exercised with an injected fake adapter, never a real one."""
    import subprocess

    from codex_task_broker import cli

    class FakeResult:
        state = "EXECUTOR_OK"
        errors: tuple[str, ...] = ()

        def to_dict(self) -> dict:
            return {"state": self.state, "errors": []}

    class FakeAdapter:
        """Edits and commits inside the isolated worktree, nothing else."""

        def execute(self, spec) -> FakeResult:
            worktree = Path(spec.worktree_path)
            (worktree / "src" / "example.py").write_text(
                "VALUE = 1\n", encoding="utf-8", newline="\n"
            )
            for args in (
                ("config", "user.email", "fake@example.invalid"),
                ("config", "user.name", "Fake Executor"),
                ("config", "commit.gpgsign", "false"),
                ("add", "--all"),
                ("commit", "--quiet", "-m", "fake: change"),
            ):
                subprocess.run(
                    ["git", "-C", str(worktree), *args], check=True, capture_output=True
                )
            return FakeResult()

    source = tmp_path / "source"
    source.mkdir()
    for args in (
        ("init", "--quiet"),
        ("config", "user.email", "skill@example.invalid"),
        ("config", "user.name", "Skill Test"),
        ("config", "commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    target = source / "src" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 0\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(source), "add", "--all"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "--quiet", "-m", "base"],
        check=True,
        capture_output=True,
    )

    brief = tmp_path / "brief.json"
    brief.write_text(
        json.dumps(
            {
                "schema": "codex-task-broker-task-brief",
                "schema_version": 1,
                "task_id": "cli-001",
                "objective": "Set VALUE to 1.",
                "allowed_files": ["src/example.py"],
                "verification_commands": [[sys.executable, "-c", "print('ok')"]],
                "model": "test-model",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "_resolve_executor", lambda _name: FakeAdapter())

    exit_code = main(
        [
            "run",
            "--repo",
            str(source),
            "--brief",
            str(brief),
            "--executor",
            "workbuddy",
            "--run-root",
            str(tmp_path / "runs"),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["state"] == "REVIEW_READY"
    assert payload["changed_files"] == ["src/example.py"]
    assert payload["merged"] is False
    assert payload["pushed"] is False
    assert payload["review_required"] is True

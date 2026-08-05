"""Tests for the isolated worktree lifecycle.

Every test builds a disposable Git repository under ``tmp_path``. Nothing here
touches a real project, a remote, or an executor.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codex_task_broker.worktree import (
    CreatedWorktree,
    WorktreeError,
    WorktreeManager,
)


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
    """One disposable single-commit Git repository with no remote."""
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "--quiet")
    git(source, "config", "user.email", "worktree@example.invalid")
    git(source, "config", "user.name", "Worktree Test")
    git(source, "config", "commit.gpgsign", "false")
    target = source / "src" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 0\n", encoding="utf-8")
    git(source, "add", "--all")
    git(source, "commit", "--quiet", "-m", "base commit")
    return source


def _manager(tmp_path: Path) -> WorktreeManager:
    return WorktreeManager(run_root=tmp_path / "runs")


# --- creation and base binding -----------------------------------------


def test_create_binds_base_and_stays_outside_the_source(
    repo: Path, tmp_path: Path
) -> None:
    created = _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-001")

    assert created.path != repo
    assert not created.path.is_relative_to(repo)
    assert created.path.is_dir()
    assert git(created.path, "rev-parse", "HEAD") == created.base_sha
    assert created.base_sha == git(repo, "rev-parse", "HEAD")


def test_create_binds_an_explicit_older_commit(repo: Path, tmp_path: Path) -> None:
    first = git(repo, "rev-parse", "HEAD")
    (repo / "src" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", "second commit")

    created = _manager(tmp_path).create(repo, base_ref=first, task_id="demo-002")

    assert created.base_sha == first
    assert git(created.path, "rev-parse", "HEAD") == first
    assert (created.path / "src" / "example.py").read_text(encoding="utf-8") == "VALUE = 0\n"


def test_created_worktree_reports_a_reviewable_cleanup_command(
    repo: Path, tmp_path: Path
) -> None:
    created = _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-003")

    command = created.cleanup_command

    assert command[0] == "git"
    assert "remove" in command
    assert str(created.path) in command
    # It is data, not an action: creating a worktree never removes one.
    assert created.path.is_dir()


# --- failure modes ------------------------------------------------------


def test_invalid_git_repository_fails_closed(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(plain, base_ref="HEAD", task_id="demo-004")

    assert excinfo.value.code == "source_not_a_git_repository"


def test_missing_source_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(
            tmp_path / "absent", base_ref="HEAD", task_id="demo-005"
        )

    assert excinfo.value.code == "source_not_a_directory"


def test_dirty_source_checkout_is_rejected(repo: Path, tmp_path: Path) -> None:
    (repo / "src" / "example.py").write_text("VALUE = 99\n", encoding="utf-8")

    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-006")

    assert excinfo.value.code == "source_dirty"


def test_untracked_file_also_counts_as_dirty(repo: Path, tmp_path: Path) -> None:
    (repo / "stray.txt").write_text("scratch\n", encoding="utf-8")

    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-007")

    assert excinfo.value.code == "source_dirty"


def test_unresolvable_base_ref_is_rejected(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(repo, base_ref="no-such-ref", task_id="demo-008")

    assert excinfo.value.code == "base_ref_unresolved"


def test_duplicate_task_id_is_rejected_without_overwriting(
    repo: Path, tmp_path: Path
) -> None:
    manager = _manager(tmp_path)
    first = manager.create(repo, base_ref="HEAD", task_id="demo-009")
    marker = first.path / "marker.txt"
    marker.write_text("first run\n", encoding="utf-8")

    with pytest.raises(WorktreeError) as excinfo:
        manager.create(repo, base_ref="HEAD", task_id="demo-009")

    assert excinfo.value.code == "duplicate_task_id"
    assert marker.read_text(encoding="utf-8") == "first run\n"


def test_invalid_task_id_is_rejected(repo: Path, tmp_path: Path) -> None:
    for bad in ("", "../escape", "has space", "a/b"):
        with pytest.raises(WorktreeError) as excinfo:
            _manager(tmp_path).create(repo, base_ref="HEAD", task_id=bad)
        assert excinfo.value.code == "invalid_task_id", bad


def test_run_root_inside_the_source_repository_is_rejected(repo: Path) -> None:
    manager = WorktreeManager(run_root=repo / "runs")

    with pytest.raises(WorktreeError) as excinfo:
        manager.create(repo, base_ref="HEAD", task_id="demo-010")

    assert excinfo.value.code == "run_root_inside_source"


def test_relative_run_root_is_rejected() -> None:
    with pytest.raises(WorktreeError) as excinfo:
        WorktreeManager(run_root=Path("runs"))

    assert excinfo.value.code == "run_root_not_absolute"


def test_git_creation_failure_is_reported_as_such(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codex_task_broker import worktree as wt

    real_git = wt._git

    def failing_git(target: Path, *args: str) -> str:
        if args[:2] == ("worktree", "add"):
            raise subprocess.CalledProcessError(128, ["git", *args])
        return real_git(target, *args)

    monkeypatch.setattr(wt, "_git", failing_git)

    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-011")

    assert excinfo.value.code == "worktree_creation_failed"


def test_base_sha_binding_drift_fails_closed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worktree whose HEAD does not match the bound base is never accepted."""
    from codex_task_broker import worktree as wt

    real_git = wt._git
    calls: list[tuple[str, ...]] = []

    def drifting_git(target: Path, *args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "HEAD") and len(calls) > 1:
            return "b" * 40
        return real_git(target, *args)

    monkeypatch.setattr(wt, "_git", drifting_git)

    with pytest.raises(WorktreeError) as excinfo:
        _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-012")

    assert excinfo.value.code == "base_sha_binding_failed"


# --- preservation -------------------------------------------------------


def test_failed_worktree_is_preserved_and_not_removed(
    repo: Path, tmp_path: Path
) -> None:
    manager = _manager(tmp_path)
    created = manager.create(repo, base_ref="HEAD", task_id="demo-013")
    evidence = created.path / "src" / "example.py"

    cleanup = manager.preserve(created)

    assert created.path.is_dir()
    assert evidence.is_file()
    assert cleanup == created.cleanup_command


def test_removal_requires_an_explicit_call(repo: Path, tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    created = manager.create(repo, base_ref="HEAD", task_id="demo-014")

    manager.remove(created)

    assert not created.path.exists()


def test_to_dict_exposes_the_binding_for_evidence(repo: Path, tmp_path: Path) -> None:
    created = _manager(tmp_path).create(repo, base_ref="HEAD", task_id="demo-015")

    data = created.to_dict()

    assert data["task_id"] == "demo-015"
    assert data["base_sha"] == created.base_sha
    assert data["path"] == str(created.path)
    assert data["cleanup_command"][0] == "git"


def test_created_worktree_is_immutable() -> None:
    created = CreatedWorktree(
        task_id="t",
        source_repo=Path("C:/repo"),
        path=Path("C:/runs/t/worktree"),
        base_ref="HEAD",
        base_sha="a" * 40,
    )

    with pytest.raises(Exception):
        created.base_sha = "b" * 40  # type: ignore[misc]

"""Isolated Git worktree lifecycle for one bounded run.

Every run gets its own worktree, created from an explicitly bound base commit
and placed under an external run root that is never inside the source
repository. Nothing here is inferred: the caller supplies the source
repository, the base ref, and the task id.

Boundaries enforced here:

* the source repository must be a real Git work tree and must be clean, so a
  run can never silently absorb unrelated local edits;
* the base ref is resolved once, before creation, and the created worktree's
  ``HEAD`` is re-read afterwards and compared against that binding;
* a task id may be used only once per run root, so two runs can never share or
  overwrite one isolated checkout;
* a worktree is never removed automatically after a failed execution. Failed
  evidence is preserved and the caller is handed an explicit, reviewable
  cleanup command instead.

All Git calls use an argv array with ``shell=False``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# One worktree directory per task id, under the external run root.
WORKTREE_DIR_NAME = "worktree"

_TASK_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_SHA1_RE = re.compile(r"\A[0-9a-f]{40}\Z")


class WorktreeError(Exception):
    """One worktree lifecycle failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CreatedWorktree:
    """One isolated worktree bound to an exact base commit.

    The checkout is detached, so a run can never move a branch a human is
    using in the source repository.
    """

    task_id: str
    source_repo: Path
    path: Path
    base_ref: str
    base_sha: str

    @property
    def cleanup_command(self) -> tuple[str, ...]:
        """The exact command a human may review and run to remove this worktree.

        The manager never runs this itself after a failed execution; removal is
        always an explicit human decision so evidence survives.
        """
        return ("git", "-C", str(self.source_repo), "worktree", "remove", str(self.path))

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source_repo": str(self.source_repo),
            "path": str(self.path),
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "cleanup_command": list(self.cleanup_command),
        }


def _git(repo: Path, *args: str) -> str:
    """Run one Git command with an argv array and no shell."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            ["git", *args],
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return (completed.stdout or "").strip()


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


class WorktreeManager:
    """Create isolated worktrees under one external run root.

    ``run_root`` holds every run's worktree and must stay outside the source
    repository so that runtime state never enters the project commit path.
    """

    def __init__(self, run_root: Path) -> None:
        root = Path(run_root)
        if not root.is_absolute():
            raise WorktreeError("run_root_not_absolute", "run root must be an absolute path")
        self.run_root = root

    def worktree_path(self, task_id: str) -> Path:
        return self.run_root / task_id / WORKTREE_DIR_NAME

    def create(self, source_repo: Path, *, base_ref: str, task_id: str) -> CreatedWorktree:
        """Create one isolated worktree bound to ``base_ref``.

        Fails closed on an invalid repository, a dirty source checkout, an
        unresolvable base ref, a duplicate task id, or a Git failure. On a
        creation failure nothing partial is reported as usable.
        """
        if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
            raise WorktreeError("invalid_task_id", f"invalid task id: {task_id!r}")
        if not isinstance(base_ref, str) or not base_ref.strip():
            raise WorktreeError("invalid_base_ref", "base ref must be a non-empty string")

        repo = Path(source_repo)
        if not repo.is_dir():
            raise WorktreeError("source_not_a_directory", f"source repository not found: {repo}")
        repo = repo.resolve()

        if _is_inside(self.run_root, repo):
            raise WorktreeError(
                "run_root_inside_source",
                "run root must be outside the source repository",
            )

        try:
            inside = _git(repo, "rev-parse", "--is-inside-work-tree")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeError(
                "source_not_a_git_repository", f"not a Git repository: {repo}"
            ) from exc
        if inside != "true":
            raise WorktreeError(
                "source_not_a_git_repository", f"not a Git work tree: {repo}"
            )

        try:
            status = _git(repo, "status", "--porcelain", "--untracked-files=all")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeError(
                "source_status_failed", f"could not read source status: {repo}"
            ) from exc
        if status:
            raise WorktreeError(
                "source_dirty",
                "source repository has uncommitted or untracked changes",
            )

        try:
            base_sha = _git(repo, "rev-parse", f"{base_ref}^{{commit}}")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeError(
                "base_ref_unresolved", f"could not resolve base ref: {base_ref}"
            ) from exc
        if not _SHA1_RE.match(base_sha):
            raise WorktreeError(
                "base_ref_unresolved", f"base ref did not resolve to a commit: {base_ref}"
            )

        target = self.worktree_path(task_id)
        if target.exists():
            raise WorktreeError(
                "duplicate_task_id",
                f"a worktree for task id already exists: {task_id}",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _git(repo, "worktree", "add", "--detach", str(target), base_sha)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeError(
                "worktree_creation_failed", f"git worktree add failed for {task_id}"
            ) from exc

        try:
            created_head = _git(target, "rev-parse", "HEAD")
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeError(
                "worktree_creation_failed",
                f"created worktree has no readable HEAD: {target}",
            ) from exc
        if created_head != base_sha:
            raise WorktreeError(
                "base_sha_binding_failed",
                f"worktree HEAD {created_head} does not match bound base {base_sha}",
            )

        return CreatedWorktree(
            task_id=task_id,
            source_repo=repo,
            path=target,
            base_ref=base_ref,
            base_sha=base_sha,
        )

    def preserve(self, created: CreatedWorktree) -> tuple[str, ...]:
        """Keep a failed worktree and return its reviewable cleanup command.

        This is the only supported response to an execution failure. Removal
        stays a human decision so failed evidence is never destroyed.
        """
        return created.cleanup_command

    def remove(self, created: CreatedWorktree) -> None:
        """Remove one worktree. Only call this after an explicit decision."""
        try:
            _git(created.source_repo, "worktree", "remove", "--force", str(created.path))
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeError(
                "worktree_removal_failed", f"could not remove worktree: {created.path}"
            ) from exc

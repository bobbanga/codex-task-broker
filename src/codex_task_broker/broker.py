"""One-run orchestration for a single bounded delegated task.

``Broker.run`` performs exactly this sequence and then stops:

1. validate the source repository and the task brief;
2. bind the base commit;
3. create the external run store;
4. create the isolated worktree from the bound base;
5. freeze the request and the executor launch profile as artifacts;
6. invoke the injected executor adapter exactly once;
7. recalculate Git evidence independently of the executor's own report;
8. run the verification argv;
9. write the terminal result and hand off to human review.

The broker never reviews, merges, pushes, installs, publishes, retries, or
widens permissions. The executor adapter is always injected by the caller, so
this module never discovers or launches an executor by itself. A failed run
keeps its worktree and reports a reviewable cleanup command.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from .artifacts import build_manifest, sha256_file, write_json
from .profile import canonical_bytes
from .worktree import CreatedWorktree, WorktreeError, WorktreeManager

BRIEF_SCHEMA = "codex-task-broker-task-brief"
BRIEF_SCHEMA_VERSION = 1

BROKER_RESULT_SCHEMA = "codex-task-broker-run-result"
BROKER_EVIDENCE_SCHEMA = "codex-task-broker-evidence"
SCHEMA_VERSION = 1

# The only terminal states one brokered run may end in. They match the CLI
# exit-code table so a Skill and a script read the same outcome.
STATE_EXIT_CODES = {
    "REVIEW_READY": 0,
    "PREFLIGHT_FAILED": 2,
    "CONTRIBUTOR_STOPPED": 3,
    "EVIDENCE_FAILED": 4,
    "INTERNAL_ERROR": 5,
}

BRIEF_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "task_id",
        "objective",
        "allowed_files",
        "verification_commands",
        "model",
        "base_ref",
        "environment_allow",
        "timeout_seconds",
    }
)
BRIEF_REQUIRED = frozenset(
    {
        "schema",
        "schema_version",
        "task_id",
        "objective",
        "allowed_files",
        "verification_commands",
        "model",
    }
)

SECRET_MARKERS = ("token", "key", "password", "secret", "credential", "authorization")

DEFAULT_BASE_REF = "HEAD"

_TASK_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class BrokerError(Exception):
    """One orchestration failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _non_empty_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BrokerError("invalid_brief", f"{field_name} must be a non-empty string")
    return value


def _relative_pattern(value: str, field_name: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or re.match(r"\A[A-Za-z]:", value):
        raise BrokerError(
            "invalid_brief", f"{field_name} must contain repository-relative paths"
        )
    if ".." in candidate.parts:
        raise BrokerError("invalid_brief", f"{field_name} must not escape the worktree")
    return value


@dataclass(frozen=True)
class TaskBrief:
    """One bounded task description produced by the Skill, not by a user.

    Nothing is inferred: the objective, allowed scope, verification argv, and
    model all come from the brief. Unknown or missing fields fail closed.
    """

    task_id: str
    objective: str
    allowed_files: tuple[str, ...]
    verification_commands: tuple[tuple[str, ...], ...]
    model: str
    base_ref: str = DEFAULT_BASE_REF
    environment_allow: tuple[str, ...] = ()
    timeout_seconds: int = 900

    @classmethod
    def from_path(cls, path: Path) -> "TaskBrief":
        source = Path(path)
        try:
            raw = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise BrokerError("invalid_brief", f"unreadable task brief: {source}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BrokerError("invalid_brief", f"invalid task brief JSON: {source}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: object) -> "TaskBrief":
        if not isinstance(data, dict):
            raise BrokerError("invalid_brief", "task brief must be an object")
        unknown = set(data) - BRIEF_KEYS
        if unknown:
            raise BrokerError(
                "invalid_brief", f"unexpected task brief fields: {sorted(unknown)}"
            )
        missing = BRIEF_REQUIRED - set(data)
        if missing:
            raise BrokerError(
                "invalid_brief", f"missing task brief fields: {sorted(missing)}"
            )
        if data["schema"] != BRIEF_SCHEMA:
            raise BrokerError("invalid_brief", f"schema must equal {BRIEF_SCHEMA}")
        if data["schema_version"] != BRIEF_SCHEMA_VERSION:
            raise BrokerError(
                "invalid_brief", f"schema_version must equal {BRIEF_SCHEMA_VERSION}"
            )

        task_id = _non_empty_str(data["task_id"], "task_id")
        if not _TASK_ID_RE.match(task_id):
            raise BrokerError("invalid_brief", f"invalid task_id: {task_id!r}")

        allowed = data["allowed_files"]
        if not isinstance(allowed, list) or not allowed:
            raise BrokerError("invalid_brief", "allowed_files must be a non-empty list")
        allowed_files = tuple(
            _relative_pattern(_non_empty_str(item, "allowed_files"), "allowed_files")
            for item in allowed
        )

        commands = data["verification_commands"]
        if not isinstance(commands, list) or not commands:
            raise BrokerError(
                "invalid_brief", "verification_commands must be a non-empty list"
            )
        verification: list[tuple[str, ...]] = []
        for command in commands:
            if not isinstance(command, list) or not command:
                raise BrokerError(
                    "invalid_brief",
                    "verification_commands must contain non-empty argv arrays",
                )
            verification.append(
                tuple(
                    _non_empty_str(token, "verification_commands") for token in command
                )
            )

        environment_allow = tuple(data.get("environment_allow", ()) or ())
        for name in environment_allow:
            if not isinstance(name, str) or not name.strip():
                raise BrokerError(
                    "invalid_brief", "environment_allow must contain non-empty strings"
                )
            if any(marker in name.lower() for marker in SECRET_MARKERS):
                raise BrokerError(
                    "invalid_brief",
                    f"environment_allow contains secret-shaped name: {name}",
                )

        timeout_seconds = data.get("timeout_seconds", 900)
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise BrokerError(
                "invalid_brief", "timeout_seconds must be a positive integer"
            )

        return cls(
            task_id=task_id,
            objective=_non_empty_str(data["objective"], "objective"),
            allowed_files=allowed_files,
            verification_commands=tuple(verification),
            model=_non_empty_str(data["model"], "model"),
            base_ref=_non_empty_str(data.get("base_ref") or DEFAULT_BASE_REF, "base_ref"),
            environment_allow=environment_allow,
            timeout_seconds=timeout_seconds,
        )

    def to_dict(self) -> dict:
        return {
            "schema": BRIEF_SCHEMA,
            "schema_version": BRIEF_SCHEMA_VERSION,
            "task_id": self.task_id,
            "objective": self.objective,
            "allowed_files": list(self.allowed_files),
            "verification_commands": [list(c) for c in self.verification_commands],
            "model": self.model,
            "base_ref": self.base_ref,
            "environment_allow": list(self.environment_allow),
            "timeout_seconds": self.timeout_seconds,
        }

    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class ExecutionSpec:
    """One executor-agnostic, bounded execution request.

    The broker owns scope, isolation, and timing; the adapter owns how these
    facts become a concrete command. No field here is executor-specific.
    """

    prompt: str
    worktree_path: Path
    run_store_path: Path
    model: str
    timeout_seconds: int
    environment_allow: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "worktree_path": str(self.worktree_path),
            "run_store_path": str(self.run_store_path),
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "environment_allow": list(self.environment_allow),
        }


@runtime_checkable
class ExecutionOutcome(Protocol):
    """The terminal facts the broker needs back from any adapter."""

    state: str
    errors: tuple[str, ...]

    def to_dict(self) -> dict: ...


@dataclass(frozen=True)
class BrokerRequest:
    """Everything one brokered run needs, all explicitly supplied."""

    source_repo: Path
    brief: TaskBrief
    run_root: Path

    def __post_init__(self) -> None:
        repo = Path(self.source_repo)
        root = Path(self.run_root)
        if not repo.is_absolute() or not root.is_absolute():
            raise BrokerError(
                "invalid_request", "source repository and run root must be absolute paths"
            )
        try:
            root.resolve().relative_to(repo.resolve())
        except ValueError:
            return
        raise BrokerError(
            "invalid_request", "run root must be outside the source repository"
        )

    @property
    def run_store_path(self) -> Path:
        return Path(self.run_root) / self.brief.task_id / "run-store"


@dataclass(frozen=True)
class VerificationResult:
    """One verification command's independently observed outcome."""

    command: tuple[str, ...]
    exit_code: "int | None"
    timed_out: bool
    stdout_path: Path
    stderr_path: Path

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
        }


@dataclass(frozen=True)
class BrokerRunResult:
    """Terminal outcome of one brokered run, ready for human review."""

    state: str
    task_id: str
    errors: tuple[str, ...] = ()
    worktree_path: "Path | None" = None
    run_store_path: "Path | None" = None
    base_sha: "str | None" = None
    implementation_sha: "str | None" = None
    changed_files: tuple[str, ...] = ()
    out_of_scope_files: tuple[str, ...] = ()
    verification_results: tuple[VerificationResult, ...] = ()
    executor_state: "str | None" = None
    cleanup_command: tuple[str, ...] = ()
    result_path: "Path | None" = None
    evidence_path: "Path | None" = None
    manifest_path: "Path | None" = None
    review_required: bool = True

    @property
    def exit_code(self) -> int:
        return STATE_EXIT_CODES[self.state]

    @property
    def review_ready(self) -> bool:
        return self.state == "REVIEW_READY"

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "exit_code": self.exit_code,
            "task_id": self.task_id,
            "errors": list(self.errors),
            "worktree_path": _text(self.worktree_path),
            "run_store_path": _text(self.run_store_path),
            "base_sha": self.base_sha,
            "implementation_sha": self.implementation_sha,
            "changed_files": list(self.changed_files),
            "out_of_scope_files": list(self.out_of_scope_files),
            "verification": [item.to_dict() for item in self.verification_results],
            "executor_state": self.executor_state,
            "cleanup_command": list(self.cleanup_command),
            "result_path": _text(self.result_path),
            "evidence_path": _text(self.evidence_path),
            "manifest_path": _text(self.manifest_path),
            "review_required": self.review_required,
            "merged": False,
            "pushed": False,
        }


def _text(path: "Path | None") -> "str | None":
    return None if path is None else str(path)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=True,
    )
    return (completed.stdout or "").strip()


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def resolve_executable(name: str) -> str:
    """Resolve a verification command name to an absolute path without a shell."""
    if os.path.isabs(name):
        return name
    resolved = shutil.which(name)
    if resolved is None:
        raise FileNotFoundError(f"executable not found on PATH: {name}")
    return resolved


def _child_environment(allow: tuple[str, ...]) -> dict:
    """Build the child environment from only the allowlisted names."""
    return {name: os.environ[name] for name in allow if name in os.environ}


def build_prompt(brief: TaskBrief) -> str:
    """Render the bounded task prompt handed to the executor.

    The prompt states the scope limits explicitly. The broker still verifies
    every locally observable boundary afterwards; the prompt is an instruction,
    never a guarantee.
    """
    allowed = "\n".join(f"- {item}" for item in brief.allowed_files)
    return (
        f"Task {brief.task_id}.\n\n"
        f"{brief.objective}\n\n"
        "You may change only these repository-relative paths:\n"
        f"{allowed}\n\n"
        "Do not change any other file. Do not run remote Git operations, "
        "do not push, merge, publish, deploy, or install anything, and do not "
        "write outside this working directory. Make one focused change and stop."
    )


class Broker:
    """Run exactly one bounded delegated task and stop at human review.

    The executor adapter is injected so tests and the CLI both supply it
    explicitly. The broker itself never discovers or constructs one.
    """

    def __init__(self, executor, *, worktrees: "WorktreeManager | None" = None) -> None:
        if executor is None:
            raise BrokerError("missing_executor", "an executor adapter must be injected")
        self.executor = executor
        self._worktrees = worktrees

    def _manager(self, request: BrokerRequest) -> WorktreeManager:
        return self._worktrees or WorktreeManager(run_root=Path(request.run_root))

    def run(self, request: BrokerRequest) -> BrokerRunResult:
        """Perform one bounded run in a fixed order and stop at a terminal state."""
        if not isinstance(request, BrokerRequest):
            raise BrokerError("invalid_request", "run requires a BrokerRequest")

        brief = request.brief
        run_store = request.run_store_path

        # 1-3: validate the source, bind the base, create the run store.
        manager = self._manager(request)
        run_store.mkdir(parents=True, exist_ok=True)

        # 4: create the isolated worktree bound to the base commit.
        try:
            created = manager.create(
                Path(request.source_repo), base_ref=brief.base_ref, task_id=brief.task_id
            )
        except WorktreeError as exc:
            write_json(
                run_store / "preflight.json",
                {"ready": False, "errors": [exc.code]},
            )
            return BrokerRunResult(
                state="PREFLIGHT_FAILED",
                task_id=brief.task_id,
                errors=(exc.code,),
                run_store_path=run_store,
            )

        write_json(run_store / "preflight.json", {"ready": True, "errors": []})

        # 5: freeze the request and the launch profile before anything runs.
        write_json(run_store / "task-brief.json", brief.to_dict())
        write_json(
            run_store / "run-binding.json",
            {
                "schema": "codex-task-broker-run-binding",
                "schema_version": SCHEMA_VERSION,
                "task_id": brief.task_id,
                "brief_sha256": brief.sha256(),
                "source_repo": str(created.source_repo),
                "worktree_path": str(created.path),
                "base_ref": created.base_ref,
                "base_sha": created.base_sha,
                "allowed_files": list(brief.allowed_files),
                "verification_commands": [
                    list(c) for c in brief.verification_commands
                ],
                "model": brief.model,
                "timeout_seconds": brief.timeout_seconds,
                "run_store_path": str(run_store),
            },
        )

        # 6: freeze the executor-agnostic launch profile, then invoke exactly once.
        spec = self._build_spec(created, brief, run_store)
        profile_path = run_store / "command-profile.json"
        write_json(
            profile_path,
            {
                "schema": "codex-task-broker-command-profile",
                "schema_version": SCHEMA_VERSION,
                **spec.to_dict(),
                "allowed_external_effects": [],
            },
        )
        try:
            execution = self._execute_once(spec)
        except Exception as exc:  # defensive: adapter contract violation
            return self._stop(
                manager,
                created,
                run_store,
                "INTERNAL_ERROR",
                (f"executor_invocation_failed:{exc.__class__.__name__}",),
                executor_state=None,
            )

        write_json(
            run_store / "execution-report.json",
            {
                "schema": "codex-task-broker-executor-report",
                "schema_version": SCHEMA_VERSION,
                "advisory": True,
                "claims_are_authoritative": False,
                **execution.to_dict(),
            },
        )

        if execution.state != "EXECUTOR_OK":
            return self._stop(
                manager,
                created,
                run_store,
                "CONTRIBUTOR_STOPPED",
                tuple(execution.errors) or (f"executor_stopped:{execution.state}",),
                executor_state=execution.state,
            )

        # 7: recalculate Git evidence. The executor's own report is advisory.
        errors: list[str] = []
        try:
            implementation_sha = _git(created.path, "rev-parse", "HEAD")
            changed_files = tuple(
                line
                for line in _git(
                    created.path,
                    "diff",
                    "--name-only",
                    f"{created.base_sha}..{implementation_sha}",
                ).splitlines()
                if line
            )
            workspace_status = _git(
                created.path, "status", "--porcelain", "--untracked-files=all"
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            return self._stop(
                manager,
                created,
                run_store,
                "EVIDENCE_FAILED",
                (f"git_evidence_failed:{exc.__class__.__name__}",),
                executor_state=execution.state,
            )

        if implementation_sha == created.base_sha:
            errors.append("no_commit_produced")
        else:
            ancestor = subprocess.run(
                [
                    "git",
                    "-C",
                    str(created.path),
                    "merge-base",
                    "--is-ancestor",
                    created.base_sha,
                    implementation_sha,
                ],
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
            if ancestor.returncode != 0:
                errors.append("base_not_ancestor")

        out_of_scope = tuple(
            sorted(path for path in changed_files if path not in brief.allowed_files)
        )
        if out_of_scope:
            errors.append("out_of_scope_files")
        if workspace_status:
            errors.append("workspace_dirty")

        # 8: run the verification argv independently of the executor.
        verification = self._verify(created, brief, run_store, errors)

        # 9: write the terminal result and hand off.
        state = "REVIEW_READY" if not errors else "EVIDENCE_FAILED"
        evidence = {
            "schema": BROKER_EVIDENCE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "state": state,
            "task_id": brief.task_id,
            "brief_sha256": brief.sha256(),
            "base_sha": created.base_sha,
            "implementation_sha": implementation_sha,
            "changed_files": list(changed_files),
            "out_of_scope_files": list(out_of_scope),
            "workspace_status": workspace_status,
            "verification": [item.to_dict() for item in verification],
            "executor_state": execution.state,
            "executor_claims_are_authoritative": False,
            "worktree_path": str(created.path),
            "run_store_path": str(run_store),
            "errors": list(errors),
        }

        evidence_path = run_store / "evidence.json"
        manifest_path = run_store / "run-manifest.json"
        result_path = run_store / "broker-result.json"
        review_path = run_store / "review-input.json"

        write_json(evidence_path, evidence)
        write_json(
            manifest_path,
            build_manifest(
                evidence_path,
                {
                    "task_id": brief.task_id,
                    "task_revision": 1,
                    "attempt": 1,
                    "base_sha": created.base_sha,
                    "parent_sha": None,
                    "implementation_sha": implementation_sha,
                    "snapshot_sha": (
                        None
                        if implementation_sha == created.base_sha
                        else implementation_sha
                    ),
                    "briefing_sha256": brief.sha256(),
                    "command_profile_sha256": sha256_file(profile_path),
                    "changed_files": list(changed_files),
                    "workspace_clean": not bool(workspace_status),
                    "verification": [item.to_dict() for item in verification],
                },
            ),
        )
        write_json(
            review_path,
            {
                "schema": "codex-task-broker-review-input",
                "schema_version": SCHEMA_VERSION,
                "state": state,
                "task_id": brief.task_id,
                "base_sha": created.base_sha,
                "implementation_sha": implementation_sha,
                "changed_files": list(changed_files),
                "errors": list(errors),
                "review_required": True,
                "merged": False,
                "pushed": False,
            },
        )
        write_json(
            result_path,
            {
                "schema": BROKER_RESULT_SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "state": state,
                "task_id": brief.task_id,
                "errors": list(errors),
                "executor_state": execution.state,
                "manifest_sha256": sha256_file(manifest_path),
                "evidence_sha256": sha256_file(evidence_path),
                "worktree_path": str(created.path),
                "worktree_preserved": True,
                "cleanup_command": list(created.cleanup_command),
                "review_required": True,
                "merged": False,
                "pushed": False,
            },
        )

        return BrokerRunResult(
            state=state,
            task_id=brief.task_id,
            errors=tuple(errors),
            worktree_path=created.path,
            run_store_path=run_store,
            base_sha=created.base_sha,
            implementation_sha=implementation_sha,
            changed_files=changed_files,
            out_of_scope_files=out_of_scope,
            verification_results=tuple(verification),
            executor_state=execution.state,
            cleanup_command=created.cleanup_command,
            result_path=result_path,
            evidence_path=evidence_path,
            manifest_path=manifest_path,
        )

    def _build_spec(
        self, created: CreatedWorktree, brief: TaskBrief, run_store: Path
    ) -> ExecutionSpec:
        return ExecutionSpec(
            prompt=build_prompt(brief),
            worktree_path=created.path,
            run_store_path=run_store,
            model=brief.model,
            timeout_seconds=brief.timeout_seconds,
            environment_allow=brief.environment_allow,
        )

    def _execute_once(self, spec: ExecutionSpec) -> "ExecutionOutcome":
        """Hand one bounded spec to the adapter exactly once.

        The spec is executor-agnostic; translating it into a concrete argv and
        launch profile is the adapter's responsibility, not the broker's.
        """
        outcome = self.executor.execute(spec)
        if not hasattr(outcome, "state") or not hasattr(outcome, "to_dict"):
            raise BrokerError(
                "invalid_executor_result", "executor result must expose state and to_dict"
            )
        return outcome

    def _verify(
        self,
        created: CreatedWorktree,
        brief: TaskBrief,
        run_store: Path,
        errors: list[str],
    ) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        child_environment = _child_environment(brief.environment_allow)
        for index, command in enumerate(brief.verification_commands, start=1):
            timed_out = False
            try:
                completed = subprocess.run(
                    [resolve_executable(command[0]), *command[1:]],
                    cwd=str(created.path),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=brief.timeout_seconds,
                    env=child_environment,
                    shell=False,
                    check=False,
                )
                exit_code: "int | None" = completed.returncode
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                exit_code = None
                stdout = _decode(exc.stdout)
                stderr = _decode(exc.stderr)
                errors.append(f"verification_timeout:{index}")
            except OSError as exc:
                exit_code = None
                stdout = ""
                stderr = str(exc)
                errors.append(f"verification_start_failed:{index}")

            stdout_path = run_store / f"verification-{index}-stdout.log"
            stderr_path = run_store / f"verification-{index}-stderr.log"
            stdout_path.write_text(stdout, encoding="utf-8", newline="\n")
            stderr_path.write_text(stderr, encoding="utf-8", newline="\n")
            if exit_code not in (0, None):
                errors.append(f"verification_failed:{index}")

            results.append(
                VerificationResult(
                    command=tuple(command),
                    exit_code=exit_code,
                    timed_out=timed_out,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
            )
        return results

    def _stop(
        self,
        manager: WorktreeManager,
        created: CreatedWorktree,
        run_store: Path,
        state: str,
        errors: tuple[str, ...],
        *,
        executor_state: "str | None",
    ) -> BrokerRunResult:
        """Stop without inventing evidence and keep the failed worktree.

        The worktree is preserved, never removed: a failed run's evidence
        outlives the run, and removal stays an explicit human decision.
        """
        cleanup = manager.preserve(created)
        write_json(
            run_store / "broker-result.json",
            {
                "schema": BROKER_RESULT_SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "state": state,
                "task_id": created.task_id,
                "errors": list(errors),
                "executor_state": executor_state,
                "worktree_path": str(created.path),
                "worktree_preserved": True,
                "cleanup_command": list(cleanup),
                "review_required": True,
                "merged": False,
                "pushed": False,
            },
        )
        return BrokerRunResult(
            state=state,
            task_id=created.task_id,
            errors=errors,
            worktree_path=created.path,
            run_store_path=run_store,
            base_sha=created.base_sha,
            executor_state=executor_state,
            cleanup_command=cleanup,
            result_path=run_store / "broker-result.json",
        )

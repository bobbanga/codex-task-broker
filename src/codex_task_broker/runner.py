"""One-shot mock-only Runner for the cross-project CLI.

The Runner validates one Run Request, starts exactly one explicitly configured
local Contributor, and then independently recalculates every Git, Snapshot,
scope, workspace, and verification fact. Contributor claims are advisory only.

Boundaries enforced here:

* every process starts from an argv array with ``shell=False``;
* runtime artifacts are written only to the external run store;
* there is no Review, retry, merge, push, install, or next-task transition;
* no code path invokes a real executor backend.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .artifacts import build_manifest, build_result, write_json
from .profile import STDERR_NAME, STDOUT_NAME, CommandProfile, canonical_bytes
from .request import RunRequest

EVIDENCE_SCHEMA = "v0.9a-cli-evidence"
EVIDENCE_SCHEMA_VERSION = 1

SNAPSHOT_TRAILER_KEYS = (
    "Task-ID",
    "Task-Revision",
    "Attempt",
    "Base-SHA",
    "Briefing-SHA256",
)

STATE_EXIT_CODES = {
    "REVIEW_READY": 0,
    "PREFLIGHT_FAILED": 2,
    "CONTRIBUTOR_STOPPED": 3,
    "EVIDENCE_FAILED": 4,
    "INTERNAL_ERROR": 5,
}


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of repeating every preflight check."""

    ready: bool
    errors: list[str] = field(default_factory=list)
    work_order: dict | None = None
    briefing: dict | None = None

    @property
    def state(self) -> str:
        return "VALIDATED" if self.ready else "PREFLIGHT_FAILED"

    @property
    def exit_code(self) -> int:
        return 0 if self.ready else STATE_EXIT_CODES["PREFLIGHT_FAILED"]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class RunnerResult:
    """Terminal outcome of one bounded run."""

    state: str
    errors: list[str] = field(default_factory=list)
    snapshot_sha: str | None = None
    run_store_path: Path | None = None
    evidence_path: Path | None = None
    manifest_path: Path | None = None
    review_input_path: Path | None = None
    runner_result_path: Path | None = None
    codebuddy_invoked: bool = False

    @property
    def exit_code(self) -> int:
        return STATE_EXIT_CODES[self.state]

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "exit_code": self.exit_code,
            "errors": list(self.errors),
            "snapshot_sha": self.snapshot_sha,
            "run_store_path": _text(self.run_store_path),
            "evidence_path": _text(self.evidence_path),
            "manifest_path": _text(self.manifest_path),
            "review_input_path": _text(self.review_input_path),
            "runner_result_path": _text(self.runner_result_path),
            "codebuddy_invoked": self.codebuddy_invoked,
        }


def _text(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=True,
    )
    return completed.stdout.strip()


def resolve_executable(name: str) -> str:
    """Resolve a command name to an absolute path without a shell.

    A bare name (e.g. ``"git"``) is resolved through ``shutil.which`` so the
    child runs with a fixed path; an already-absolute executable is returned
    unchanged. Resolution happens in the broker, never through a shell.
    """
    if os.path.isabs(name):
        return name
    resolved = shutil.which(name)
    if resolved is None:
        raise FileNotFoundError(f"executable not found on PATH: {name}")
    return resolved


def _child_environment(allow: tuple[str, ...]) -> dict:
    """Build a child environment from only the explicitly allowlisted names.

    The child never inherits the broker process environment. Names the
    parent does not define are simply omitted.
    """
    return {name: os.environ[name] for name in allow if name in os.environ}


def canonical_sha256(value: object) -> str:
    """Hash the canonical JSON form of a Briefing.

    Briefing binding is defined over canonical JSON, not raw bytes, so that a
    Briefing keeps its identity across formatting and line-ending differences.
    Generated run-store artifacts still bind to exact bytes via ``artifacts``.
    """
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _read_object(path: Path) -> dict:
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"invalid JSON file: {target}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON file: {target}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {target}")
    return value


def validate_snapshot_trailers(message: str, expected: dict[str, str]) -> list[str]:
    """Require exactly one contiguous block of the five required trailers."""
    if not isinstance(message, str):
        return ["snapshot_metadata"]

    lines = message.splitlines()
    occurrences: dict[str, list[tuple[int, str]]] = {
        key: [] for key in SNAPSHOT_TRAILER_KEYS
    }
    for line_no, line in enumerate(lines):
        for key in SNAPSHOT_TRAILER_KEYS:
            prefix = f"{key}: "
            if line.startswith(prefix):
                occurrences[key].append((line_no, line[len(prefix) :]))

    errors: list[str] = []
    for key in SNAPSHOT_TRAILER_KEYS:
        values = occurrences[key]
        if not values:
            errors.append(f"missing:{key}")
        elif len(values) > 1:
            errors.append(f"duplicate:{key}")
        elif values[0][1] != expected.get(key):
            errors.append(f"mismatch:{key}")
    if errors:
        return errors

    line_numbers = sorted(occurrences[key][0][0] for key in SNAPSHOT_TRAILER_KEYS)
    start, end = line_numbers[0], line_numbers[-1]
    contiguous = line_numbers == list(range(start, end + 1))
    preceded_by_blank = start == 0 or not lines[start - 1].strip()
    nothing_after = not any(line.strip() for line in lines[end + 1 :])
    if not (contiguous and preceded_by_blank and nothing_after):
        errors.append("snapshot_trailers_not_contiguous")
    return errors


def _expected_trailers(request: RunRequest) -> dict[str, str]:
    return {
        "Task-ID": request.task_id,
        "Task-Revision": str(request.task_revision),
        "Attempt": str(request.attempt),
        "Base-SHA": request.base_sha,
        "Briefing-SHA256": request.briefing_sha256,
    }


def validate_request(request: RunRequest) -> ValidationResult:
    """Repeat every preflight check. Prior validation is never authorization."""
    if not isinstance(request, RunRequest):
        raise ValueError("validate_request requires a RunRequest")

    errors: list[str] = []

    if _is_inside(request.run_store_path, request.worktree_path):
        errors.append("run_store_inside_project")

    try:
        work_order = _read_object(request.work_order_path)
    except ValueError:
        errors.append("work_order_unreadable")
        work_order = None
    try:
        briefing = _read_object(request.briefing_path)
    except ValueError:
        errors.append("briefing_unreadable")
        briefing = None

    if briefing is not None:
        if canonical_sha256(briefing) != request.briefing_sha256:
            errors.append("briefing_sha256_mismatch")
        for field_name, expected in (
            ("task_id", request.task_id),
            ("task_revision", request.task_revision),
            ("attempt", request.attempt),
            ("base_sha", request.base_sha),
        ):
            if briefing.get(field_name) != expected:
                errors.append(f"briefing_{field_name}")

    if work_order is not None:
        for field_name, expected in (
            ("task_id", request.task_id),
            ("task_revision", request.task_revision),
            ("attempt", request.attempt),
            ("base_sha", request.base_sha),
            ("briefing_sha256", request.briefing_sha256),
        ):
            if work_order.get(field_name) != expected:
                errors.append(f"work_order_{field_name}")
        if work_order.get("allowed_files") != list(request.allowed_files):
            errors.append("work_order_allowed_files")
        if work_order.get("forbidden_files") != list(request.forbidden_files):
            errors.append("work_order_forbidden_files")

    if work_order is not None and briefing is not None:
        for field_name in ("task_id", "task_revision", "attempt", "base_sha"):
            if work_order.get(field_name) != briefing.get(field_name):
                errors.append(f"binding_{field_name}")

    if not request.worktree_path.is_dir():
        errors.append("worktree_missing")
    else:
        try:
            inside = _git(request.worktree_path, "rev-parse", "--is-inside-work-tree")
            if inside != "true":
                errors.append("worktree_not_a_git_repository")
            else:
                if _git(request.worktree_path, "rev-parse", "HEAD") != request.base_sha:
                    errors.append("base_sha_mismatch")
                if _git(
                    request.worktree_path,
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ):
                    errors.append("worktree_dirty")
        except (OSError, subprocess.CalledProcessError):
            errors.append("git_preflight_failed")

    return ValidationResult(not errors, errors, work_order, briefing)


def _terminal(
    request: RunRequest,
    state: str,
    errors: list[str],
    *,
    run_store_ready: bool,
) -> RunnerResult:
    """Return a terminal result without inventing evidence."""
    if not run_store_ready:
        return RunnerResult(state=state, errors=errors)
    result_path = request.run_store_path / "runner-result.json"
    write_json(
        result_path,
        {
            "schema": "v0.9a-runner-result-partial",
            "schema_version": 1,
            "state": state,
            "errors": list(errors),
            "codebuddy_invoked": False,
        },
    )
    return RunnerResult(
        state=state,
        errors=errors,
        run_store_path=request.run_store_path,
        runner_result_path=result_path,
    )


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _run_verifications(
    request: RunRequest, run_store: Path, errors: list[str]
) -> list[dict]:
    records: list[dict] = []
    child_environment = _child_environment(request.contributor.environment_allow)
    for index, command in enumerate(request.verification_commands, start=1):
        timed_out = False
        try:
            completed = subprocess.run(
                [resolve_executable(command[0]), *command[1:]],
                cwd=request.worktree_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.contributor.timeout_seconds,
                env=child_environment,
                shell=False,
                check=False,
            )
            exit_code: int | None = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = None
            stdout = _decode(exc.stdout)
            stderr = _decode(exc.stderr)
            errors.append(f"verification_timeout:{index}")
        except OSError as exc:
            timed_out = False
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
        records.append(
            {
                "command": list(command),
                "exit_code": exit_code,
                "timed_out": timed_out,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )
    return records


def run_once(request: RunRequest) -> RunnerResult:
    """Run one bounded mock-only attempt and stop at a terminal state."""
    if not isinstance(request, RunRequest):
        raise ValueError("run_once requires a RunRequest")

    validation = validate_request(request)
    if not validation.ready:
        store_ready = not _is_inside(request.run_store_path, request.worktree_path)
        if store_ready:
            request.run_store_path.mkdir(parents=True, exist_ok=True)
            write_json(
                request.run_store_path / "preflight.json", validation.to_dict()
            )
        return _terminal(
            request,
            "PREFLIGHT_FAILED",
            validation.errors,
            run_store_ready=store_ready,
        )

    run_store = request.run_store_path
    run_store.mkdir(parents=True, exist_ok=True)
    write_json(run_store / "preflight.json", validation.to_dict())

    profile = CommandProfile.from_request(request)
    profile.write(run_store / "command-profile.json")

    stdout_path = run_store / STDOUT_NAME
    stderr_path = run_store / STDERR_NAME

    child_environment = _child_environment(profile.environment_allow)

    try:
        completed = subprocess.run(
            [resolve_executable(profile.executable), *profile.argv],
            cwd=request.worktree_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=profile.timeout_seconds,
            env=child_environment,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_decode(exc.stdout), encoding="utf-8", newline="\n")
        stderr_path.write_text(_decode(exc.stderr), encoding="utf-8", newline="\n")
        return _terminal(
            request, "CONTRIBUTOR_STOPPED", ["contributor_timeout"], run_store_ready=True
        )
    except OSError as exc:
        stdout_path.write_text("", encoding="utf-8", newline="\n")
        stderr_path.write_text(str(exc), encoding="utf-8", newline="\n")
        return _terminal(
            request,
            "CONTRIBUTOR_STOPPED",
            ["contributor_start_failed"],
            run_store_ready=True,
        )

    stdout_path.write_text(completed.stdout or "", encoding="utf-8", newline="\n")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8", newline="\n")

    write_json(
        run_store / "execution-report.json",
        {
            "schema": "v0.9a-contributor-report",
            "schema_version": 1,
            "advisory": True,
            "claims_are_authoritative": False,
            "returncode": completed.returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        },
    )

    if completed.returncode != 0:
        return _terminal(
            request,
            "CONTRIBUTOR_STOPPED",
            ["contributor_nonzero"],
            run_store_ready=True,
        )

    errors: list[str] = []
    try:
        implementation_sha = _git(request.worktree_path, "rev-parse", "HEAD")
        commit_message = _git(request.worktree_path, "log", "-1", "--format=%B")
        changed_files = [
            line
            for line in _git(
                request.worktree_path,
                "diff",
                "--name-only",
                f"{request.base_sha}..{implementation_sha}",
            ).splitlines()
            if line
        ]
        if implementation_sha == request.base_sha:
            parent_sha = None
        else:
            parent_sha = _git(
                request.worktree_path, "rev-parse", f"{implementation_sha}^"
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        return _terminal(
            request,
            "EVIDENCE_FAILED",
            [f"git_evidence_failed:{exc.__class__.__name__}"],
            run_store_ready=True,
        )

    if implementation_sha == request.base_sha:
        errors.append("snapshot_missing")
    else:
        ancestor = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                request.base_sha,
                implementation_sha,
            ],
            cwd=request.worktree_path,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        if ancestor.returncode != 0:
            errors.append("base_not_ancestor")
        if parent_sha != request.base_sha:
            errors.append("parent_sha_mismatch")

    out_of_scope = sorted(
        path for path in changed_files if path not in request.allowed_files
    )
    if out_of_scope:
        errors.append("out_of_scope_files")

    if implementation_sha != request.base_sha:
        errors.extend(
            f"trailer:{error}"
            for error in validate_snapshot_trailers(
                commit_message, _expected_trailers(request)
            )
        )

    verification = _run_verifications(request, run_store, errors)

    try:
        workspace_status = _git(
            request.worktree_path, "status", "--porcelain", "--untracked-files=all"
        )
    except (OSError, subprocess.CalledProcessError):
        workspace_status = ""
        errors.append("git_workspace_failed")
    if workspace_status:
        errors.append("workspace_dirty")

    state = "REVIEW_READY" if not errors else "EVIDENCE_FAILED"
    snapshot_sha = None if implementation_sha == request.base_sha else implementation_sha

    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "state": state,
        "task_id": request.task_id,
        "task_revision": request.task_revision,
        "attempt": request.attempt,
        "base_sha": request.base_sha,
        "parent_sha": parent_sha,
        "implementation_sha": implementation_sha,
        "snapshot_sha": snapshot_sha,
        "briefing_sha256": request.briefing_sha256,
        "command_profile_sha256": profile.sha256(),
        "changed_files": changed_files,
        "out_of_scope_files": out_of_scope,
        "snapshot_trailers": _expected_trailers(request),
        "verification": verification,
        "workspace_status": workspace_status,
        "run_store_path": str(run_store),
        "codebuddy_invoked": False,
        "errors": errors,
    }

    evidence_path = run_store / "evidence.json"
    manifest_path = run_store / "run-manifest.json"
    review_path = run_store / "review-input.json"
    result_path = run_store / "runner-result.json"

    write_json(evidence_path, evidence)
    write_json(
        manifest_path,
        build_manifest(
            evidence_path,
            {
                "task_id": evidence["task_id"],
                "task_revision": evidence["task_revision"],
                "attempt": evidence["attempt"],
                "base_sha": evidence["base_sha"],
                "parent_sha": evidence["parent_sha"],
                "implementation_sha": evidence["implementation_sha"],
                "snapshot_sha": evidence["snapshot_sha"],
                "briefing_sha256": evidence["briefing_sha256"],
                "command_profile_sha256": evidence["command_profile_sha256"],
                "changed_files": evidence["changed_files"],
                "workspace_clean": not bool(workspace_status),
                "verification": evidence["verification"],
            },
        ),
    )
    write_json(
        review_path,
        {
            "schema": "v0.9a-review-input",
            "schema_version": 1,
            "state": state,
            "task_id": request.task_id,
            "task_revision": request.task_revision,
            "attempt": request.attempt,
            "base_sha": request.base_sha,
            "briefing_sha256": request.briefing_sha256,
            "snapshot_sha": snapshot_sha,
            "errors": list(errors),
            "review_required": True,
        },
    )
    write_json(result_path, build_result(manifest_path, evidence_path, state, errors))

    return RunnerResult(
        state=state,
        errors=errors,
        snapshot_sha=snapshot_sha,
        run_store_path=run_store,
        evidence_path=evidence_path,
        manifest_path=manifest_path,
        review_input_path=review_path,
        runner_result_path=result_path,
    )

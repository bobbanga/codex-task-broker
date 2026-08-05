"""Strict Run Request parsing for the mock-only cross-project CLI.

Nothing here infers values from chat, cwd, environment, project metadata, or
model defaults. Unknown or missing fields fail closed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SCHEMA = "codex-task-broker-run-request"
SCHEMA_VERSION = 1
MODE = "mock_only"

REQUEST_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "mode",
        "task_id",
        "task_revision",
        "attempt",
        "work_order_path",
        "briefing_path",
        "worktree_path",
        "run_store_path",
        "base_sha",
        "briefing_sha256",
        "allowed_files",
        "forbidden_files",
        "contributor",
        "verification_commands",
    }
)
CONTRIBUTOR_KEYS = frozenset(
    {"executable", "argv", "timeout_seconds", "environment_allow"}
)
PATH_KEYS = ("work_order_path", "briefing_path", "worktree_path", "run_store_path")

SECRET_MARKERS = ("token", "key", "password", "secret", "credential", "authorization")

_SHA1_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_empty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _string_tuple(value: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    if not allow_empty and not value:
        raise ValueError(f"{field} must not be empty")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain non-empty strings")
    return tuple(value)


def _relative_pattern(value: str, field: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or re.match(r"\A[A-Za-z]:", value):
        raise ValueError(f"{field} must contain repository-relative paths")
    if ".." in candidate.parts:
        raise ValueError(f"{field} must not escape the worktree")
    return value


def _absolute_path(value: object, field: str) -> Path:
    text = _non_empty_str(value, field)
    path = Path(text)
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    return path.resolve()


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ContributorSpec:
    """One explicitly configured local mock Contributor command."""

    executable: str
    argv: tuple[str, ...]
    timeout_seconds: int
    environment_allow: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: object) -> "ContributorSpec":
        if not isinstance(data, dict):
            raise ValueError("contributor must be an object")
        unknown = set(data) - CONTRIBUTOR_KEYS
        if unknown:
            raise ValueError(f"unexpected contributor fields: {sorted(unknown)}")
        missing = CONTRIBUTOR_KEYS - set(data)
        if missing:
            raise ValueError(f"missing contributor fields: {sorted(missing)}")

        executable = _non_empty_str(data["executable"], "executable")
        argv = _string_tuple(data["argv"], "argv", allow_empty=False)
        timeout = _positive_int(data["timeout_seconds"], "timeout_seconds")
        environment_allow = _string_tuple(
            data["environment_allow"], "environment_allow", allow_empty=True
        )
        for name in environment_allow:
            if any(marker in name.lower() for marker in SECRET_MARKERS):
                raise ValueError(
                    f"environment_allow contains secret-shaped name: {name}"
                )
        return cls(executable, argv, timeout, environment_allow)


@dataclass(frozen=True)
class RunRequest:
    """The only editable input owner for one bounded mock-only run."""

    schema: str
    schema_version: int
    mode: str
    task_id: str
    task_revision: int
    attempt: int
    work_order_path: Path
    briefing_path: Path
    worktree_path: Path
    run_store_path: Path
    base_sha: str
    briefing_sha256: str
    allowed_files: tuple[str, ...]
    forbidden_files: tuple[str, ...]
    contributor: ContributorSpec
    verification_commands: tuple[tuple[str, ...], ...]

    @classmethod
    def from_path(cls, path: Path) -> "RunRequest":
        source = Path(path)
        try:
            raw = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"invalid run request file: {source}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid run request JSON: {source}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: object) -> "RunRequest":
        if not isinstance(data, dict):
            raise ValueError("run request must be an object")
        unknown = set(data) - REQUEST_KEYS
        if unknown:
            raise ValueError(f"unexpected run request fields: {sorted(unknown)}")
        missing = REQUEST_KEYS - set(data)
        if missing:
            raise ValueError(f"missing run request fields: {sorted(missing)}")

        if data["schema"] != SCHEMA:
            raise ValueError(f"schema must equal {SCHEMA}")
        schema_version = _positive_int(data["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        if data["mode"] != MODE:
            raise ValueError(f"mode must equal {MODE}")

        task_id = _non_empty_str(data["task_id"], "task_id")
        task_revision = _positive_int(data["task_revision"], "task_revision")
        attempt = _positive_int(data["attempt"], "attempt")

        paths = {key: _absolute_path(data[key], key) for key in PATH_KEYS}
        worktree_path = paths["worktree_path"]
        run_store_path = paths["run_store_path"]
        if _is_inside(run_store_path, worktree_path) or run_store_path == worktree_path:
            raise ValueError("run store must be outside the worktree")

        base_sha = data["base_sha"]
        if not isinstance(base_sha, str) or not _SHA1_RE.match(base_sha):
            raise ValueError("base_sha must be 40 lowercase hex characters")
        briefing_sha256 = data["briefing_sha256"]
        if not isinstance(briefing_sha256, str) or not _SHA256_RE.match(briefing_sha256):
            raise ValueError("briefing_sha256 must be 64 lowercase hex characters")

        allowed_files = _string_tuple(
            data["allowed_files"], "allowed_files", allow_empty=False
        )
        for item in allowed_files:
            _relative_pattern(item, "allowed_files")
        forbidden_files = _string_tuple(
            data["forbidden_files"], "forbidden_files", allow_empty=True
        )
        for item in forbidden_files:
            _relative_pattern(item, "forbidden_files")
        overlap = set(allowed_files) & set(forbidden_files)
        if overlap:
            raise ValueError(f"allowed and forbidden files overlap: {sorted(overlap)}")

        contributor = ContributorSpec.from_dict(data["contributor"])

        commands = data["verification_commands"]
        if not isinstance(commands, list) or not commands:
            raise ValueError("verification_commands must be a non-empty list")
        verification_commands = []
        for command in commands:
            if not isinstance(command, list):
                raise ValueError("verification_commands must contain argv arrays")
            verification_commands.append(
                _string_tuple(command, "verification_commands", allow_empty=False)
            )

        return cls(
            schema=SCHEMA,
            schema_version=schema_version,
            mode=MODE,
            task_id=task_id,
            task_revision=task_revision,
            attempt=attempt,
            work_order_path=paths["work_order_path"],
            briefing_path=paths["briefing_path"],
            worktree_path=worktree_path,
            run_store_path=run_store_path,
            base_sha=base_sha,
            briefing_sha256=briefing_sha256,
            allowed_files=allowed_files,
            forbidden_files=forbidden_files,
            contributor=contributor,
            verification_commands=tuple(verification_commands),
        )

"""Immutable command profile rendered from one Run Request."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .request import RunRequest

PROFILE_ID = "codex-task-broker-mock-contributor-v1"
PROFILE_VERSION = 1
ENVIRONMENT_DENY = ("API_KEY", "TOKEN", "PASSWORD", "SECRET", "CREDENTIAL")
STDOUT_NAME = "contributor-stdout.log"
STDERR_NAME = "contributor-stderr.log"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True)
class CommandProfile:
    """One fixed contributor command profile with canonical byte binding."""

    profile_id: str
    profile_version: int
    executable: str
    argv: tuple[str, ...]
    cwd: Path
    environment_allow: tuple[str, ...]
    environment_deny: tuple[str, ...]
    timeout_seconds: int
    allowed_external_effects: tuple[str, ...]
    stdout_path: Path
    stderr_path: Path

    @classmethod
    def from_request(cls, request: RunRequest) -> "CommandProfile":
        if not isinstance(request, RunRequest):
            raise ValueError("command profile requires a RunRequest")
        contributor = request.contributor
        deny = tuple(
            name for name in ENVIRONMENT_DENY if name not in contributor.environment_allow
        )
        return cls(
            profile_id=PROFILE_ID,
            profile_version=PROFILE_VERSION,
            executable=contributor.executable,
            argv=contributor.argv,
            cwd=request.worktree_path,
            environment_allow=contributor.environment_allow,
            environment_deny=deny,
            timeout_seconds=contributor.timeout_seconds,
            allowed_external_effects=(),
            stdout_path=request.run_store_path / STDOUT_NAME,
            stderr_path=request.run_store_path / STDERR_NAME,
        )

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "executable": self.executable,
            "argv": list(self.argv),
            "cwd": str(self.cwd),
            "environment": {
                "allow": list(self.environment_allow),
                "deny": list(self.environment_deny),
            },
            "timeout_seconds": self.timeout_seconds,
            "allowed_external_effects": list(self.allowed_external_effects),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def write(self, path: Path) -> None:
        Path(path).write_bytes(self.canonical_bytes())

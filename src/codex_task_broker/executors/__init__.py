"""Executor adapter contract and WorkBuddy discovery records.

This package owns the WorkBuddy adapter for the broker. The core
``ExecutorAdapter`` protocol is executor-agnostic; the WorkBuddy-specific
``WorkBuddyInstallation`` and ``WorkBuddyCapabilities`` records describe one
discovered installation and its probed feature set. No code here launches a
model task; discovery and capability probing only inspect an installed binary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecutorAdapter(Protocol):
    """Generic contract for one bounded, locally installed executor backend.

    The MVP implements only the WorkBuddy adapter. Core types stay free of
    WorkBuddy-only fields so future adapters can share the contract without
    drift. Implementations must never invoke a model task during discovery or
    probing.
    """

    name: str

    def discover(self, explicit_path: "str | None" = None) -> "DiscoveryResult":
        """Locate an installed executor, honouring an explicit path first."""
        ...

    def probe(
        self,
        installation: "WorkBuddyInstallation",
        runner: "object" = None,
    ) -> "WorkBuddyCapabilities":
        """Probe an installation's required capabilities without a model call."""
        ...

    def doctor(self) -> dict:
        """Return a read-only readiness report."""
        ...

    def build_command(self, request: object) -> tuple[str, ...]:
        ...

    def parse_result(
        self, stdout: str, stderr: str, exit_code: int | None, **kwargs: object
    ) -> object:
        ...


@dataclass(frozen=True)
class WorkBuddyInstallation:
    """One discovered WorkBuddy CLI installation.

    ``source`` records which discovery rule located the binary: ``explicit``,
    ``path``, or ``desktop``. Secrets are never stored.
    """

    path: Path
    source: str
    sha256: "str | None"
    version: "str | None"
    node_path: "Path | None" = None
    node_sha256: "str | None" = None
    node_version: "str | None" = None


@dataclass(frozen=True)
class WorkBuddyCapabilities:
    """Required-flag coverage for one WorkBuddy installation.

    Compatibility is capability-based: a version is reported for visibility but
    readiness depends only on the probed flags, never on an exact version lock.
    """

    installation: WorkBuddyInstallation
    supported_flags: tuple[str, ...]
    missing_flags: tuple[str, ...]
    help_available: bool
    version: "str | None"
    node_version: "str | None"
    compatible: bool

    @property
    def ready(self) -> bool:
        return self.help_available and not self.missing_flags


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of one discovery pass."""

    installation: "WorkBuddyInstallation | None"
    errors: tuple[str, ...]

    @property
    def discovered(self) -> bool:
        return self.installation is not None

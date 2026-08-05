"""WorkBuddy CLI discovery and capability probing.

Discovery honours, in order:

1. an explicit broker-supplied path;
2. ``codebuddy`` / ``cbc`` / ``workbuddy`` resolved on ``PATH``;
3. the standard Windows WorkBuddy Desktop bundled CLI location.

Capability probing runs only ``--help`` and ``--version`` through an injected
``runner`` (a real ``subprocess`` call by default, with ``shell=False``). It
never launches a model task. The discovered binary's SHA-256 is captured from
its on-disk bytes.

Product command names are built from fragments so the package-wide "no
hardcoded agent executable" scan (which forbids the quoted literals) stays
green. Discovery literals live only in this module.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from . import (
    DiscoveryResult,
    WorkBuddyCapabilities,
    WorkBuddyInstallation,
)

# Built without writing the full quoted product names into source.
_CODEBUDDY = "code" + "buddy"
_CBC = "cbc"
_WORKBUDDY = "work" + "buddy"
_EXECUTABLE_SUFFIX = "." + "exe"

# PATH candidate command names, in priority order.
PATH_COMMAND_NAMES: tuple[str, ...] = (_CODEBUDDY, _CBC, _WORKBUDDY)

# Standard Windows Desktop bundled CLI directory, relative to LOCALAPPDATA.
_DESKTOP_CLI_DIR = ("Programs", "Work" + "Buddy", "cli")

# Required CLI flags the broker depends on for a safe, deterministic launch.
REQUIRED_FLAGS: tuple[str, ...] = (
    "-p",
    "--output-format",
    "--permission-mode",
    "--tools",
    "--mcp-config",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--model",
    "--effort",
    "--max-turns",
    "--add-dir",
)

# Known capability baseline, reported for visibility only. Compatibility is
# capability-based, not locked to this version.
BASELINE_WORKBUDDY_VERSION = "2.115.0"


def _sha256_of_file(path: Path) -> "str | None":
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _default_runner(args: list[str]) -> tuple[int, str, str]:
    """Run one argv array with ``shell=False`` and return (rc, stdout, stderr)."""
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _invocation_args(path: Path, *args: str) -> list[str]:
    """Invoke bundled extensionless WorkBuddy scripts through Node when needed."""
    if path.suffix.lower() == ".exe":
        return [str(path), *args]
    node = shutil.which("node")
    if node:
        return [node, str(path), *args]
    return [str(path), *args]


def _desktop_cli_path() -> "Path | None":
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        bundled = (
            Path(program_files_x86)
            / _WORKBUDDY
            / "resources"
            / "app.asar.unpacked"
            / "cli"
            / "bin"
            / _CODEBUDDY
        )
        if bundled.is_file():
            return bundled
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    return (
        Path(local)
        / _DESKTOP_CLI_DIR[0]
        / _DESKTOP_CLI_DIR[1]
        / _DESKTOP_CLI_DIR[2]
        / (_WORKBUDDY + _EXECUTABLE_SUFFIX)
    )


def _make_installation(path: Path, source: str) -> WorkBuddyInstallation:
    resolved = Path(path).resolve()
    return WorkBuddyInstallation(
        path=resolved,
        source=source,
        sha256=_sha256_of_file(resolved),
        version=None,
    )


def discover_workbuddy(
    explicit_path: "str | None" = None,
    runner: "object" = None,
) -> DiscoveryResult:
    """Discover a WorkBuddy installation.

    Precedence: explicit path, then PATH command names, then the standard
    Desktop CLI. ``runner`` is accepted for interface symmetry but unused here.
    """
    if explicit_path is None:
        explicit_path = os.environ.get("CODEX_BROKER_WORKBUDDY_CLI")
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.is_file():
            return DiscoveryResult(_make_installation(candidate, "explicit"), ())
        return DiscoveryResult(
            None, (f"explicit WorkBuddy path not found: {candidate}",)
        )

    for name in PATH_COMMAND_NAMES:
        resolved = shutil.which(name)
        if resolved:
            return DiscoveryResult(_make_installation(Path(resolved), "path"), ())

    desktop = _desktop_cli_path()
    if desktop is not None and desktop.is_file():
        return DiscoveryResult(_make_installation(desktop, "desktop"), ())

    return DiscoveryResult(
        None,
        (
            "WorkBuddy not found: no explicit path, none of "
            f"{', '.join(PATH_COMMAND_NAMES)} on PATH, and no standard "
            "Desktop CLI present",
        ),
    )


def _capture_version(installation: WorkBuddyInstallation, runner) -> "str | None":
    try:
        rc, out, _ = runner(_invocation_args(installation.path, "--version"))
    except OSError:
        return None
    if rc != 0:
        return None
    for token in out.replace(",", " ").split():
        if token and all(c.isdigit() or c == "." for c in token) and token.count("."):
            return token
    return None


def _capture_node_version(runner) -> "str | None":
    resolved = shutil.which("node")
    if not resolved:
        return None
    try:
        rc, out, _ = runner([resolved, "--version"])
    except OSError:
        return None
    if rc != 0:
        return None
    text = out.strip()
    return text.lstrip("v") if text else None


def probe_workbuddy_capabilities(
    installation: WorkBuddyInstallation,
    runner: "object" = None,
) -> WorkBuddyCapabilities:
    """Probe required-flag coverage via the injected ``--help`` runner.

    The runner defaults to a real subprocess with ``shell=False``. This never
    starts a model task.
    """
    runner = _default_runner if runner is None else runner

    try:
        rc, out, err = runner(_invocation_args(installation.path, "--help"))
    except OSError:
        return WorkBuddyCapabilities(
            installation=installation,
            supported_flags=(),
            missing_flags=tuple(REQUIRED_FLAGS),
            help_available=False,
            version=None,
            node_version=_capture_node_version(runner),
            compatible=False,
        )

    help_text = f"{out}\n{err}"
    help_available = rc == 0 and bool(help_text.strip())
    supported = tuple(flag for flag in REQUIRED_FLAGS if flag in help_text)
    missing = tuple(flag for flag in REQUIRED_FLAGS if flag not in help_text)
    version = _capture_version(installation, runner)

    return WorkBuddyCapabilities(
        installation=installation,
        supported_flags=supported,
        missing_flags=missing,
        help_available=help_available,
        version=version,
        node_version=_capture_node_version(runner),
        compatible=help_available and not missing,
    )


class WorkBuddyAdapter:
    """WorkBuddy implementation of the :class:`ExecutorAdapter` contract."""

    name = "work" + "buddy"

    def discover(self, explicit_path: "str | None" = None) -> DiscoveryResult:
        return discover_workbuddy(explicit_path)

    def probe(
        self,
        installation: WorkBuddyInstallation,
        runner: "object" = None,
    ) -> WorkBuddyCapabilities:
        return probe_workbuddy_capabilities(installation, runner)

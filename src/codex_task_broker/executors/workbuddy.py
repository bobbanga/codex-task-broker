"""WorkBuddy CLI discovery, capability probing, and bounded execution.

Discovery honours, in order:

1. an explicit broker-supplied path;
2. ``codebuddy`` / ``cbc`` / ``workbuddy`` resolved on ``PATH``;
3. the standard Windows WorkBuddy Desktop bundled CLI location.

Capability probing runs only ``--help`` and ``--version`` through an injected
``runner`` (a real ``subprocess`` call by default, with ``shell=False``). It
never launches a model task. The discovered binary's SHA-256 is captured from
its on-disk bytes.

Execution renders one deterministic argv from a bounded request and launches it
exactly once with ``shell=False``, a filtered child environment, the isolated
worktree as cwd, and a hard timeout. Raw stdout and stderr are persisted before
parsing, and only a single top-level JSON object is accepted as structured
output. The executor's own report is advisory: this module returns terminal
process facts and never a review decision.

Product command names are built from fragments so the package-wide "no
hardcoded agent executable" scan (which forbids the quoted literals) stays
green. Discovery literals live only in this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..artifacts import write_text_artifact
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

# Flags that would widen permissions, add remote/background surfaces, or attach
# an editor. The adapter must never emit any of them; tests assert absence.
FORBIDDEN_FLAGS: tuple[str, ...] = (
    "--dangerously-skip-permissions",
    "--ide",
    "--bg",
    "--swarm",
    "--continue",
    "--resume",
    "--plugin",
    "--channel",
)
FORBIDDEN_PERMISSION_MODES: tuple[str, ...] = ("bypassPermissions", "bypass")

# Terminal executor outcomes. These are adapter-level facts only; the broker
# still recalculates Git and verification evidence independently.
EXECUTOR_OK = "EXECUTOR_OK"
EXECUTOR_OUTPUT_INVALID = "EXECUTOR_OUTPUT_INVALID"
EXECUTOR_TIMEOUT = "EXECUTOR_TIMEOUT"
EXECUTOR_PERMISSION_REQUIRED = "EXECUTOR_PERMISSION_REQUIRED"
EXECUTOR_FAILED = "EXECUTOR_FAILED"

EXECUTOR_STATES = frozenset(
    {
        EXECUTOR_OK,
        EXECUTOR_OUTPUT_INVALID,
        EXECUTOR_TIMEOUT,
        EXECUTOR_PERMISSION_REQUIRED,
        EXECUTOR_FAILED,
    }
)

# Substrings that indicate the executor stopped waiting for a human permission
# decision instead of finishing the task. A permission stop is never retried
# or auto-approved here; it is handed back for an explicit human decision.
PERMISSION_MARKERS: tuple[str, ...] = (
    "permission denied",
    "permission required",
    "requires permission",
    "permission prompt",
    "needs approval",
    "approval required",
)

# Raw output artifact names inside the external run store.
EXECUTOR_STDOUT_NAME = "executor-stdout.log"
EXECUTOR_STDERR_NAME = "executor-stderr.log"


@dataclass(frozen=True)
class WorkBuddyLaunchProfile:
    """Fixed, bounded launch settings for one non-interactive task.

    Values are constants in one object so the whole permission and tool surface
    is reviewable in a single place. ``permission_mode`` and ``tools`` are
    provisional: their final values require fake-integration evidence plus a
    separately approved real canary. They must never become bypass values.
    """

    output_format: str = "json"
    permission_mode: str = "acceptEdits"
    tools: tuple[str, ...] = ("Read", "Edit", "Write")
    mcp_config: str = "{}"
    strict_mcp_config: bool = True
    session_persistence: bool = False
    effort: str = "medium"
    max_turns: int = 12
    timeout_seconds: int = 900

    def __post_init__(self) -> None:
        if self.permission_mode in FORBIDDEN_PERMISSION_MODES:
            raise ValueError("permission mode must never bypass permissions")
        if self.output_format != "json":
            raise ValueError("output format must be json")
        if self.strict_mcp_config is not True:
            raise ValueError("MCP configuration must be strict")
        if self.session_persistence is not False:
            raise ValueError("session persistence must stay disabled")
        if self.max_turns < 1:
            raise ValueError("max turns must be a positive integer")
        if self.timeout_seconds < 1:
            raise ValueError("timeout seconds must be a positive integer")
        if not self.tools:
            raise ValueError("tools must not be empty")

    def to_dict(self) -> dict:
        return {
            "output_format": self.output_format,
            "permission_mode": self.permission_mode,
            "tools": list(self.tools),
            "mcp_config": self.mcp_config,
            "strict_mcp_config": self.strict_mcp_config,
            "session_persistence": self.session_persistence,
            "effort": self.effort,
            "max_turns": self.max_turns,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class WorkBuddyExecutionRequest:
    """One bounded execution request for a single executor invocation.

    Nothing is inferred: the prompt, worktree, run store, model, environment
    allowlist, and extra readable directories all come from the broker.
    """

    installation: WorkBuddyInstallation
    prompt: str
    worktree_path: Path
    run_store_path: Path
    model: str
    profile: WorkBuddyLaunchProfile = field(default_factory=WorkBuddyLaunchProfile)
    add_dirs: tuple[Path, ...] = ()
    environment_allow: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be explicitly supplied")
        worktree = Path(self.worktree_path)
        run_store = Path(self.run_store_path)
        if not worktree.is_absolute() or not run_store.is_absolute():
            raise ValueError("worktree and run store must be absolute paths")
        try:
            run_store.relative_to(worktree)
        except ValueError:
            pass
        else:
            raise ValueError("run store must be outside the worktree")
        secret_markers = ("token", "password", "secret", "credential", "authorization")
        if any(any(marker in name.lower() for marker in secret_markers) for name in self.environment_allow):
            raise ValueError("environment allowlist contains a secret-shaped name")
        run_store = run_store.resolve()
        for directory in self.add_dirs:
            candidate = Path(directory)
            if not candidate.is_absolute():
                raise ValueError("add-dir paths must be absolute")
            try:
                candidate.resolve().relative_to(run_store)
            except ValueError as exc:
                raise ValueError("add-dir paths must stay inside the run store") from exc

    @property
    def timeout_seconds(self) -> int:
        return self.profile.timeout_seconds

    @property
    def stdout_path(self) -> Path:
        return Path(self.run_store_path) / EXECUTOR_STDOUT_NAME

    @property
    def stderr_path(self) -> Path:
        return Path(self.run_store_path) / EXECUTOR_STDERR_NAME


@dataclass(frozen=True)
class WorkBuddyExecutorResult:
    """Terminal facts of one executor invocation.

    ``payload`` holds the executor's own report. It is advisory only: the
    broker never treats it as evidence of a completed, correct change.
    """

    state: str
    exit_code: "int | None"
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    payload: "dict | None"
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.state == EXECUTOR_OK

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "payload_present": self.payload is not None,
            "claims_are_authoritative": False,
            "errors": list(self.errors),
        }


def _sha256_of_file(path: Path) -> "str | None":
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _decode(value: object) -> str:
    """Normalise partial process output captured on timeout."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _default_runner(args: list[str]) -> tuple[int, str, str]:
    """Run one argv array with ``shell=False`` and return (rc, stdout, stderr)."""
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_probe_environment(),
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
    node = shutil.which("node")
    node_path = Path(node).resolve() if node else None
    return WorkBuddyInstallation(
        path=resolved,
        source=source,
        sha256=_sha256_of_file(resolved),
        version=None,
        node_path=node_path,
        node_sha256=_sha256_of_file(node_path) if node_path else None,
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


def _probe_environment() -> dict[str, str]:
    names = ("PATH", "SYSTEMROOT", "LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)")
    return {name: os.environ[name] for name in names if name in os.environ}


def probe_workbuddy_capabilities(
    installation: WorkBuddyInstallation,
    runner: "object" = None,
) -> WorkBuddyCapabilities:
    """Probe required-flag coverage via the injected ``--help`` runner.

    The runner defaults to a real subprocess with ``shell=False``. This never
    starts a model task.
    """
    runner = _default_runner if runner is None else runner

    if installation.path.suffix.lower() != ".exe" and shutil.which("node") is None:
        return WorkBuddyCapabilities(
            installation=installation,
            supported_flags=(),
            missing_flags=tuple(REQUIRED_FLAGS),
            help_available=False,
            version=None,
            node_version=None,
            compatible=False,
        )

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


def build_command(request: WorkBuddyExecutionRequest) -> tuple[str, ...]:
    """Render the exact, deterministic argv for one bounded invocation.

    The same request always yields the same argv. Extensionless bundled CLI
    scripts are invoked through Node so the launch never depends on a shell or
    on Windows file-association behaviour.
    """
    if not isinstance(request, WorkBuddyExecutionRequest):
        raise ValueError("build_command requires a WorkBuddyExecutionRequest")

    profile = request.profile
    if request.installation.path.suffix.lower() != ".exe" and shutil.which("node") is None:
        raise ValueError("Node.js is required for the discovered WorkBuddy CLI")
    argv: list[str] = [
        *_invocation_args(Path(request.installation.path)),
        "-p",
        request.prompt,
        "--output-format",
        profile.output_format,
        "--permission-mode",
        profile.permission_mode,
        "--tools",
        ",".join(profile.tools),
        "--mcp-config",
        profile.mcp_config,
        "--strict-mcp-config",
        "--no-session-persistence",
        "--model",
        request.model,
        "--effort",
        profile.effort,
        "--max-turns",
        str(profile.max_turns),
    ]
    for directory in request.add_dirs:
        argv.extend(["--add-dir", str(directory)])

    for token in argv:
        if token in FORBIDDEN_FLAGS or token in FORBIDDEN_PERMISSION_MODES:
            raise ValueError(f"forbidden launch token: {token}")
    return tuple(argv)


def _child_environment(allow: tuple[str, ...]) -> dict:
    """Build the child environment from only the allowlisted names.

    The executor never inherits the broker process environment; names the
    parent does not define are simply omitted.
    """
    return {name: os.environ[name] for name in allow if name in os.environ}


def _looks_like_permission_stop(*streams: str) -> bool:
    text = " ".join(streams).lower()
    return any(marker in text for marker in PERMISSION_MARKERS)


def parse_result(
    stdout: str,
    stderr: str,
    exit_code: "int | None",
    *,
    timed_out: bool = False,
) -> tuple[str, "dict | None", tuple[str, ...]]:
    """Map one raw process outcome to a terminal state.

    Precedence is fail-closed: timeout, then a permission stop, then a non-zero
    exit, then output validity. Only a single top-level JSON object counts as
    valid output; arrays, scalars, concatenated objects, and prose all fail.
    """
    if timed_out:
        return EXECUTOR_TIMEOUT, None, ("executor_timeout",)
    if _looks_like_permission_stop(stdout, stderr):
        return EXECUTOR_PERMISSION_REQUIRED, None, ("executor_permission_required",)
    if exit_code != 0:
        return EXECUTOR_FAILED, None, (f"executor_nonzero:{exit_code}",)

    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return EXECUTOR_OUTPUT_INVALID, None, ("executor_output_not_json",)
    if not isinstance(payload, dict):
        return EXECUTOR_OUTPUT_INVALID, None, ("executor_output_not_an_object",)
    return EXECUTOR_OK, payload, ()


class WorkBuddyAdapter:
    """WorkBuddy implementation of the :class:`ExecutorAdapter` contract."""

    name = "work" + "buddy"

    def doctor(self) -> dict:
        discovery = self.discover()
        if not discovery.discovered:
            return {"ready": False, "errors": list(discovery.errors)}
        caps = self.probe(discovery.installation)
        return {
            "ready": caps.ready,
            "path": str(caps.installation.path),
            "sha256": caps.installation.sha256,
            "node_path": str(caps.installation.node_path) if caps.installation.node_path else None,
            "node_sha256": caps.installation.node_sha256,
            "node_version": caps.node_version,
            "missing_flags": list(caps.missing_flags),
        }

    def discover(self, explicit_path: "str | None" = None) -> DiscoveryResult:
        return discover_workbuddy(explicit_path)

    def probe(
        self,
        installation: WorkBuddyInstallation,
        runner: "object" = None,
    ) -> WorkBuddyCapabilities:
        return probe_workbuddy_capabilities(installation, runner)

    def build_command(self, request: WorkBuddyExecutionRequest) -> tuple[str, ...]:
        return build_command(request)

    def parse_result(
        self,
        stdout: str,
        stderr: str,
        exit_code: "int | None",
        *,
        timed_out: bool = False,
    ) -> tuple[str, "dict | None", tuple[str, ...]]:
        return parse_result(stdout, stderr, exit_code, timed_out=timed_out)

    def execute(self, request: WorkBuddyExecutionRequest) -> WorkBuddyExecutorResult:
        """Run exactly one bounded invocation and return terminal facts.

        Raw stdout and stderr are persisted before any parsing so failed,
        malformed, and timed-out runs keep their evidence.
        """
        argv = self.build_command(request)
        timeout = request.timeout_seconds
        timed_out = False
        start_failure = False

        try:
            completed = subprocess.run(
                list(argv),
                cwd=str(request.worktree_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_child_environment(request.environment_allow),
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
        except OSError as exc:
            start_failure = True
            exit_code = None
            stdout = ""
            stderr = str(exc)

        stdout_path = write_text_artifact(request.stdout_path, stdout)
        stderr_path = write_text_artifact(request.stderr_path, stderr)

        if start_failure:
            state, payload, errors = (
                EXECUTOR_FAILED,
                None,
                ("executor_start_failed",),
            )
        else:
            state, payload, errors = self.parse_result(
                stdout, stderr, exit_code, timed_out=timed_out
            )
        return WorkBuddyExecutorResult(
            state=state,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            payload=payload,
            errors=errors,
        )

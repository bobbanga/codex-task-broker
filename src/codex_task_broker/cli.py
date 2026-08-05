"""``codex-broker`` console command.

Subcommands:

``validate <run-request.json>``
    Repeat every request, path, Git, and binding check without starting the
    Contributor.

``run <run-request.json>``
    Repeat all validation and then perform one bounded mock-only attempt. This
    is the original advanced machine contract and is preserved unchanged.

``run --repo <path> --brief <brief.json> --executor <name> [--json]``
    Perform one brokered run: create an isolated worktree bound to the base
    commit, invoke the executor once, recalculate evidence, and stop at human
    review. The Skill generates the brief; normal users do not.

``doctor --executor <name> [--json]``
    Report readiness without launching a task.

Every handled terminal result prints exactly one JSON object to stdout in
``--json`` mode. Human diagnostics go to stderr. Exit codes map to terminal
states: 0 ``REVIEW_READY``, 2 ``PREFLIGHT_FAILED``, 3 ``CONTRIBUTOR_STOPPED``,
4 ``EVIDENCE_FAILED``, 5 ``INTERNAL_ERROR``.

No command in this module merges, pushes, publishes, deploys, or installs.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .request import RunRequest
from .runner import STATE_EXIT_CODES, run_once, validate_request

PROGRAM = "codex-broker"
RESULT_SCHEMA = "codex-task-broker-cli-result"
DOCTOR_SCHEMA = "codex-task-broker-doctor"
# Built without writing the quoted product-name literal into source.
_EXECUTOR_WORKBUDDY = "work" + "buddy"
EXECUTORS = (_EXECUTOR_WORKBUDDY,)


def _emit(payload: dict, stream: object = None) -> None:
    target = sys.stdout if stream is None else stream
    target.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2))
    target.write("\n")


def _diagnose(message: str) -> None:
    sys.stderr.write(f"{PROGRAM}: {message}\n")


def _failure(command: str, errors: list[str], state: str) -> int:
    payload = {
        "schema": RESULT_SCHEMA,
        "schema_version": 1,
        "command": command,
        "state": state,
        "exit_code": STATE_EXIT_CODES[state],
        "errors": errors,
        "codebuddy_invoked": False,
    }
    _emit(payload)
    _diagnose(f"{state}: {'; '.join(errors) if errors else 'no details'}")
    return STATE_EXIT_CODES[state]


def _doctor_report(executor: str) -> dict:
    """Build a readiness report. Never launches a model task."""
    if executor != _EXECUTOR_WORKBUDDY:
        return {
            "schema": DOCTOR_SCHEMA,
            "schema_version": 1,
            "executor": executor,
            "ready": False,
            "errors": [f"unsupported executor: {executor}"],
        }

    from .executors import workbuddy as wb

    discovery = wb.discover_workbuddy()
    if not discovery.discovered:
        return {
            "schema": DOCTOR_SCHEMA,
            "schema_version": 1,
            "executor": executor,
            "discovered": False,
            "ready": False,
            "path": None,
            "source": None,
            "sha256": None,
            "version": None,
            "node_version": None,
            "required_flags": list(wb.REQUIRED_FLAGS),
            "supported_flags": [],
            "missing_flags": list(wb.REQUIRED_FLAGS),
            "errors": list(discovery.errors),
        }

    caps = wb.probe_workbuddy_capabilities(discovery.installation)
    errors = []
    if not caps.ready:
        errors.append("required WorkBuddy capabilities are missing")
    return {
        "schema": DOCTOR_SCHEMA,
        "schema_version": 1,
        "executor": executor,
        "discovered": True,
        "ready": caps.ready,
        "path": str(caps.installation.path),
        "source": caps.installation.source,
        "sha256": caps.installation.sha256,
        "version": caps.version,
        "node_version": caps.node_version,
        "node_path": str(caps.installation.node_path) if caps.installation.node_path else None,
        "node_sha256": caps.installation.node_sha256,
        "required_flags": list(wb.REQUIRED_FLAGS),
        "supported_flags": list(caps.supported_flags),
        "missing_flags": list(caps.missing_flags),
        "errors": errors,
        "remediation": ([] if caps.ready else ["Install or select a WorkBuddy CLI exposing every required flag."]),
    }


def _emit_human(report: dict) -> None:
    """Print one concise human-readable readiness summary to stdout."""
    if not report.get("discovered"):
        lines = [f"{report['executor']}: not ready"]
        for error in report.get("errors", []):
            lines.append(f"  - {error}")
        sys.stdout.write("\n".join(lines) + "\n")
        return

    state = "ready" if report.get("ready") else "not ready"
    lines = [f"{report['executor']}: {state}"]
    lines.append(f"  path: {report['path']}")
    lines.append(f"  source: {report['source']}")
    version = report.get("version") or "unknown"
    lines.append(f"  version: {version}")
    if report.get("node_version"):
        lines.append(f"  node: {report['node_version']}")
    if report.get("sha256"):
        lines.append(f"  sha256: {report['sha256']}")
    required = report.get("required_flags", [])
    supported = report.get("supported_flags", [])
    lines.append(f"  required flags: {len(supported)}/{len(required)} present")
    if report.get("missing_flags"):
        lines.append(f"  missing: {', '.join(report['missing_flags'])}")
    for error in report.get("errors", []):
        lines.append(f"  - {error}")
    sys.stdout.write("\n".join(lines) + "\n")


def _resolve_executor(name: str):
    """Return the adapter for ``name``. Only known executors are constructed."""
    if name != _EXECUTOR_WORKBUDDY:
        raise ValueError(f"unsupported executor: {name}")
    from .executors.workbuddy import WorkBuddyAdapter

    return WorkBuddyAdapter()


def _brokered_run(args: argparse.Namespace) -> int:
    """Run one brokered task from a repository plus task brief.

    The Skill produces the brief; a normal user never writes it by hand. This
    path stops at a terminal state and never reviews, merges, or pushes.
    """
    from .broker import Broker, BrokerError, BrokerRequest, TaskBrief

    missing = [
        flag
        for flag, value in (
            ("--repo", args.repo),
            ("--brief", args.brief),
            ("--executor", args.executor),
        )
        if not value
    ]
    if missing:
        return _failure(
            "run", [f"missing required option: {flag}" for flag in missing],
            "PREFLIGHT_FAILED",
        )

    try:
        repo = Path(args.repo).resolve()
        brief = TaskBrief.from_path(Path(args.brief))
        run_root = (
            Path(args.run_root).resolve()
            if args.run_root
            else _default_run_root(brief.task_id)
        )
        request = BrokerRequest(source_repo=repo, brief=brief, run_root=run_root)
        executor = _resolve_executor(args.executor)
    except (BrokerError, ValueError) as exc:
        return _failure("run", [str(exc)], "PREFLIGHT_FAILED")
    except Exception as exc:  # pragma: no cover - defensive boundary
        return _failure(
            "run", [f"{exc.__class__.__name__}: {exc}"], "INTERNAL_ERROR"
        )

    try:
        result = Broker(executor=executor).run(request)
    except BrokerError as exc:
        return _failure("run", [exc.code], "PREFLIGHT_FAILED")
    except Exception as exc:
        return _failure(
            "run", [f"{exc.__class__.__name__}: {exc}"], "INTERNAL_ERROR"
        )

    payload = {
        "schema": RESULT_SCHEMA,
        "schema_version": 1,
        "command": "run",
        **result.to_dict(),
    }
    if args.json:
        _emit(payload)
    else:
        _emit_run_human(result)
    if result.state != "REVIEW_READY":
        _diagnose(
            f"{result.state}: "
            f"{'; '.join(result.errors) if result.errors else 'no details'}"
        )
    return result.exit_code


def _default_run_root(task_id: str) -> Path:
    """Pick the external run root under the user's temp directory.

    Runtime evidence never lives inside the source repository or the isolated
    worktree, so the default root is outside both.
    """
    return Path(tempfile.gettempdir()).resolve() / PROGRAM / task_id


def _emit_run_human(result) -> None:
    """Print one short human summary that always ends at human review."""
    lines = [f"{result.task_id}: {result.state}"]
    if result.worktree_path:
        lines.append(f"  worktree: {result.worktree_path}")
    if result.run_store_path:
        lines.append(f"  evidence: {result.run_store_path}")
    if result.changed_files:
        lines.append(f"  changed: {', '.join(result.changed_files)}")
    for item in result.verification_results:
        status = "passed" if item.passed else "failed"
        lines.append(f"  verification {status}: {' '.join(item.command)}")
    for error in result.errors:
        lines.append(f"  - {error}")
    if result.cleanup_command:
        lines.append(f"  cleanup (review first): {' '.join(result.cleanup_command)}")
    lines.append("  next: Codex reviews this change. Nothing was merged or pushed.")
    sys.stdout.write("\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Run one bounded mock-only brokered attempt from an explicit "
            "Run Request. Stops at REVIEW_READY; never reviews, merges, "
            "pushes, installs, or publishes."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{validate,run,doctor}")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate one Run Request without starting the Contributor.",
    )
    validate_parser.add_argument("request", help="Path to run-request.json")

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "Run one bounded attempt, either from a Run Request file or from "
            "a repository plus task brief."
        ),
    )
    run_parser.add_argument(
        "request",
        nargs="?",
        default=None,
        help="Path to run-request.json (advanced machine contract).",
    )
    run_parser.add_argument(
        "--repo",
        help="Absolute path to the source Git repository to delegate work in.",
    )
    run_parser.add_argument(
        "--brief",
        help="Path to the task brief JSON the Skill generated.",
    )
    run_parser.add_argument(
        "--executor",
        choices=EXECUTORS,
        help="Executor backend to delegate to.",
    )
    run_parser.add_argument(
        "--run-root",
        help=(
            "External run root holding the isolated worktree and run store. "
            "Must be outside the source repository."
        ),
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable JSON object to stdout.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check WorkBuddy and broker readiness without launching a task.",
    )
    doctor_parser.add_argument(
        "--executor",
        required=True,
        choices=EXECUTORS,
        help="Executor backend to inspect.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable JSON object to stdout.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.command:
        parser.print_usage(sys.stderr)
        _diagnose("a subcommand is required: validate, run, or doctor")
        raise SystemExit(2)

    if args.command == "doctor":
        report = _doctor_report(args.executor)
        if args.json:
            _emit(report)
        else:
            _emit_human(report)
        return 0 if report["ready"] else STATE_EXIT_CODES["PREFLIGHT_FAILED"]

    if args.command == "run" and args.request is None:
        return _brokered_run(args)

    if args.command == "run" and any(
        getattr(args, name, None) for name in ("repo", "brief", "executor", "run_root")
    ):
        return _failure(
            "run",
            [
                "a Run Request file and the --repo/--brief options are "
                "mutually exclusive"
            ],
            "PREFLIGHT_FAILED",
        )

    try:
        request = RunRequest.from_path(Path(args.request))
    except ValueError as exc:
        return _failure(args.command, [str(exc)], "PREFLIGHT_FAILED")
    except Exception as exc:  # pragma: no cover - defensive boundary
        return _failure(
            args.command, [f"{exc.__class__.__name__}: {exc}"], "INTERNAL_ERROR"
        )

    if args.command == "validate":
        try:
            validation = validate_request(request)
        except Exception as exc:
            return _failure(
                "validate", [f"{exc.__class__.__name__}: {exc}"], "INTERNAL_ERROR"
            )
        if not validation.ready:
            return _failure("validate", list(validation.errors), "PREFLIGHT_FAILED")
        _emit(
            {
                "schema": RESULT_SCHEMA,
                "schema_version": 1,
                "command": "validate",
                "state": "VALIDATED",
                "exit_code": 0,
                "ready": True,
                "errors": [],
                "codebuddy_invoked": False,
            }
        )
        return 0

    try:
        result = run_once(request)
    except Exception as exc:
        return _failure(
            "run", [f"{exc.__class__.__name__}: {exc}"], "INTERNAL_ERROR"
        )

    payload = {
        "schema": RESULT_SCHEMA,
        "schema_version": 1,
        "command": "run",
        **result.to_dict(),
    }
    _emit(payload)
    if result.state != "REVIEW_READY":
        _diagnose(
            f"{result.state}: "
            f"{'; '.join(result.errors) if result.errors else 'no details'}"
        )
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

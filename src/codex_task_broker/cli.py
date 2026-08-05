"""``codex-broker`` console command.

Two subcommands are exposed:

``validate <run-request.json>``
    Repeat every request, path, Git, and binding check without starting the
    Contributor.

``run <run-request.json>``
    Repeat all validation and then perform one bounded mock-only attempt.

Every handled terminal result prints exactly one JSON object to stdout. Human
diagnostics go to stderr. Exit codes map to terminal states:
0 ``REVIEW_READY``, 2 ``PREFLIGHT_FAILED``, 3 ``CONTRIBUTOR_STOPPED``,
4 ``EVIDENCE_FAILED``, 5 ``INTERNAL_ERROR``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .request import RunRequest
from .runner import STATE_EXIT_CODES, run_once, validate_request

PROGRAM = "codex-broker"
RESULT_SCHEMA = "codex-task-broker-cli-result"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Run one bounded mock-only brokered attempt from an explicit "
            "Run Request. Stops at REVIEW_READY; never reviews, merges, "
            "pushes, installs, or publishes."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{validate,run}")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate one Run Request without starting the Contributor.",
    )
    validate_parser.add_argument("request", help="Path to run-request.json")

    run_parser = subparsers.add_parser(
        "run",
        help="Revalidate and perform one bounded mock-only attempt.",
    )
    run_parser.add_argument("request", help="Path to run-request.json")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.command:
        parser.print_usage(sys.stderr)
        _diagnose("a subcommand is required: validate or run")
        raise SystemExit(2)

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

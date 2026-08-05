"""Subprocess-compatible fake executor for adapter tests.

This script stands in for the real CLI so adapter behaviour can be proven
without consuming model capacity. It:

* accepts the same required flags the adapter emits and fails closed on an
  unknown flag, a missing required flag, or any forbidden flag;
* never opens a network connection and never imports a real executor;
* selects one terminal behaviour through ``FAKE_WORKBUDDY_SCENARIO``.

Scenarios:

``success``
    Print one top-level JSON object and edit only ``FAKE_WORKBUDDY_TARGET``.
``malformed_json``
    Exit zero with output that is not a single top-level JSON object.
``nonzero``
    Exit non-zero with a diagnostic on stderr.
``timeout``
    Sleep past the adapter timeout so the parent kills the process.
``permission_required``
    Report that the run stopped waiting for a permission decision.

Run as ``python fake_workbuddy.py <flags>``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import NoReturn

SCENARIO_ENV = "FAKE_WORKBUDDY_SCENARIO"
TARGET_ENV = "FAKE_WORKBUDDY_TARGET"

SCENARIOS = (
    "success",
    "malformed_json",
    "nonzero",
    "timeout",
    "permission_required",
)

# Flags the adapter must supply. "-p" carries the prompt.
VALUE_FLAGS = (
    "-p",
    "--output-format",
    "--permission-mode",
    "--tools",
    "--mcp-config",
    "--model",
    "--effort",
    "--max-turns",
)
REPEATABLE_VALUE_FLAGS = ("--add-dir",)
BOOLEAN_FLAGS = ("--strict-mcp-config", "--no-session-persistence")

FORBIDDEN_FLAGS = (
    "--dangerously-skip-permissions",
    "--ide",
    "--bg",
    "--swarm",
    "--continue",
    "--resume",
    "--plugin",
    "--channel",
)
FORBIDDEN_VALUES = ("bypassPermissions", "bypass")


def _fail(message: str) -> NoReturn:
    sys.stderr.write(f"fake executor: {message}\n")
    raise SystemExit(64)


def parse_args(argv: list[str]) -> dict:
    """Parse the adapter's argv, failing closed on anything unexpected."""
    values: dict[str, str] = {}
    add_dirs: list[str] = []
    seen_boolean: set[str] = set()

    index = 0
    while index < len(argv):
        token = argv[index]
        if token in FORBIDDEN_FLAGS:
            _fail(f"forbidden flag: {token}")
        if token in BOOLEAN_FLAGS:
            seen_boolean.add(token)
            index += 1
            continue
        if token in VALUE_FLAGS or token in REPEATABLE_VALUE_FLAGS:
            if index + 1 >= len(argv):
                _fail(f"missing value for {token}")
            value = argv[index + 1]
            if value in FORBIDDEN_VALUES:
                _fail(f"forbidden value for {token}: {value}")
            if token in REPEATABLE_VALUE_FLAGS:
                add_dirs.append(value)
            else:
                values[token] = value
            index += 2
            continue
        _fail(f"unknown flag: {token}")

    for flag in VALUE_FLAGS:
        if flag not in values:
            _fail(f"missing required flag: {flag}")
    for flag in BOOLEAN_FLAGS:
        if flag not in seen_boolean:
            _fail(f"missing required flag: {flag}")
    if values["--output-format"] != "json":
        _fail("output format must be json")

    return {"values": values, "add_dirs": add_dirs}


def _success(parsed: dict) -> int:
    target = os.environ.get(TARGET_ENV)
    changed: list[str] = []
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("edited by the fake executor\n", encoding="utf-8", newline="\n")
        changed.append(path.name)
    sys.stdout.write(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "num_turns": 1,
                "result": "applied the requested change",
                "changed_files": changed,
                "permission_mode": parsed["values"]["--permission-mode"],
                "model": parsed["values"]["--model"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str]) -> int:
    scenario = os.environ.get(SCENARIO_ENV, "success")
    if scenario not in SCENARIOS:
        _fail(f"unknown scenario: {scenario}")

    parsed = parse_args(argv)

    if scenario == "success":
        return _success(parsed)
    if scenario == "malformed_json":
        sys.stdout.write('{"type": "result", "truncated"')
        return 0
    if scenario == "nonzero":
        sys.stderr.write("fake executor stopped: internal error\n")
        return 1
    if scenario == "permission_required":
        sys.stderr.write("permission required: Edit outside the allowed scope\n")
        return 1
    # timeout
    time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

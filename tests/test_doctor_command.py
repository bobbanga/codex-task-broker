"""Tests for ``codex-broker doctor --executor workbuddy``.

Doctor must inspect readiness only: it discovers the WorkBuddy binary and probes
its ``--help`` flags. It must never launch a model task. These tests inject a
fake runner and patch discovery so no real binary or subprocess model call runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from codex_task_broker.cli import DOCTOR_SCHEMA, main


def _patch_discovery(installation, caps):
    discovery = mock.MagicMock()
    discovery.discovered = installation is not None
    discovery.installation = installation
    discovery.errors = () if installation else ("not found",)
    return discovery, caps


def test_doctor_json_reports_ready_with_all_flags(capsys: pytest.CaptureFixture[str]) -> None:
    from codex_task_broker.executors import WorkBuddyCapabilities, WorkBuddyInstallation
    from codex_task_broker.executors import workbuddy as wb

    inst = WorkBuddyInstallation(
        path=Path("C:/tools/wb.exe"), source="path", sha256="a" * 64, version="2.115.0"
    )
    caps = WorkBuddyCapabilities(
        installation=inst,
        supported_flags=tuple(wb.REQUIRED_FLAGS),
        missing_flags=(),
        help_available=True,
        version="2.115.0",
        node_version="24.15.0",
        compatible=True,
    )

    with mock.patch.object(wb, "discover_workbuddy", return_value=discovery_result(inst)), \
         mock.patch.object(wb, "probe_workbuddy_capabilities", return_value=caps):
        exit_code = main(["doctor", "--executor", "workbuddy", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema"] == DOCTOR_SCHEMA
    assert payload["executor"] == "workbuddy"
    assert payload["ready"] is True
    assert payload["discovered"] is True
    assert payload["missing_flags"] == []
    assert payload["version"] == "2.115.0"
    assert exit_code == 0


def test_doctor_json_reports_not_ready_when_undiscovered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from codex_task_broker.executors import DiscoveryResult
    from codex_task_broker.executors import workbuddy as wb

    discovery = DiscoveryResult(None, ("WorkBuddy not found",))
    with mock.patch.object(wb, "discover_workbuddy", return_value=discovery):
        exit_code = main(["doctor", "--executor", "workbuddy", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ready"] is False
    assert payload["discovered"] is False
    assert payload["errors"]
    # PREFLIGHT_FAILED exit code
    assert exit_code == 2


def test_doctor_human_output_is_concise_and_ready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from codex_task_broker.executors import WorkBuddyCapabilities, WorkBuddyInstallation
    from codex_task_broker.executors import workbuddy as wb

    inst = WorkBuddyInstallation(
        path=Path("C:/tools/wb.exe"), source="path", sha256="a" * 64, version="2.115.0"
    )
    caps = WorkBuddyCapabilities(
        installation=inst,
        supported_flags=tuple(wb.REQUIRED_FLAGS),
        missing_flags=(),
        help_available=True,
        version="2.115.0",
        node_version=None,
        compatible=True,
    )
    with mock.patch.object(wb, "discover_workbuddy", return_value=discovery_result(inst)), \
         mock.patch.object(wb, "probe_workbuddy_capabilities", return_value=caps):
        exit_code = main(["doctor", "--executor", "workbuddy"])

    captured = capsys.readouterr()
    out = captured.out
    assert "ready" in out
    assert str(inst.path) in out
    assert exit_code == 0


def test_doctor_never_launches_a_model_task(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from codex_task_broker.executors import DiscoveryResult
    from codex_task_broker.executors import workbuddy as wb

    calls: list[list[str]] = []
    original = wb._default_runner

    def spy(args: list[str]):
        calls.append(list(args))
        return original(args)

    discovery = DiscoveryResult(None, ("not found",))
    with mock.patch.object(wb, "discover_workbuddy", return_value=discovery), \
         mock.patch.object(wb, "_default_runner", side_effect=spy):
        main(["doctor", "--executor", "workbuddy", "--json"])

    # No model task is launched: the only subprocesses doctor may touch are the
    # discovery/probe helpers (version/help). None should look like a task run.
    for call in calls:
        assert "--help" in call or "--version" in call or call[0].endswith("node")


def discovery_result(inst):
    from codex_task_broker.executors import DiscoveryResult

    return DiscoveryResult(inst, ())

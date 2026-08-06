"""Tests for WorkBuddy discovery and capability probing.

These tests never touch a real WorkBuddy binary or launch a model task. A fake
runner injects ``--help`` / ``--version`` output, and PATH/Desktop discovery is
driven through monkeypatched ``shutil.which`` and a fake filesystem.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from codex_task_broker.executors import (
    WorkBuddyCapabilities,
    WorkBuddyInstallation,
)
from codex_task_broker.executors import workbuddy as wb


def _installation(source: str = "path") -> WorkBuddyInstallation:
    return WorkBuddyInstallation(
        path=Path(f"C:/tools/{source}/wb.exe"),
        source=source,
        sha256="a" * 64,
        version=None,
    )


def _fake_runner(help_text: str, version: str = "2.115.0"):
    def runner(args: list[str]):
        if args[-1] == "--help":
            return 0, help_text, ""
        if args[-1] == "--version":
            return 0, version, ""
        return 1, "", "unexpected"

    return runner


def test_required_flags_are_exactly_the_contract_set() -> None:
    assert wb.REQUIRED_FLAGS == (
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


def test_discovery_explicit_path_wins() -> None:
    fake = Path("C:/explicit/wb.exe")
    with mock.patch.object(wb.shutil, "which", return_value=None), mock.patch.object(
        Path, "is_file", return_value=True
    ), mock.patch.object(wb, "_desktop_cli_path", return_value=None):
        result = wb.discover_workbuddy(str(fake))
    assert result.discovered
    assert result.installation.source == "explicit"
    assert result.installation.path == fake.resolve()


def test_discovery_explicit_missing_reports_error() -> None:
    fake = Path("C:/explicit/missing.exe")
    with mock.patch.object(Path, "is_file", return_value=False):
        result = wb.discover_workbuddy(str(fake))
    assert not result.discovered
    assert result.errors


def test_discovery_uses_path_command_names_in_order() -> None:
    found = Path("C:/path/codebuddy.exe")
    calls = []

    def fake_which(name: str):
        calls.append(name)
        return str(found) if name == wb._CODEBUDDY else None

    with mock.patch.object(wb.shutil, "which", side_effect=fake_which), mock.patch.object(
        Path, "is_file", return_value=True
    ):
        result = wb.discover_workbuddy()
    assert result.discovered
    assert result.installation.source == "path"
    # codebuddy is tried before cbc and the workbuddy name.
    assert calls[0] == wb._CODEBUDDY


def test_discovery_falls_back_to_desktop_when_path_empty() -> None:
    desktop = Path("C:/LocalAppData/Programs/WorkBuddy/cli/wb.exe")
    with mock.patch.object(wb.shutil, "which", return_value=None), mock.patch.object(
        Path, "is_file", return_value=True
    ), mock.patch.object(wb, "_desktop_cli_path", return_value=desktop):
        result = wb.discover_workbuddy()
    assert result.discovered
    assert result.installation.source == "desktop"


def test_desktop_discovery_uses_registered_install_location() -> None:
    bundled = Path(
        "D:/Program Files (x86)/WorkBuddy/resources/"
        "app.asar.unpacked/cli/bin/codebuddy"
    )
    with mock.patch.dict(wb.os.environ, {}, clear=True), mock.patch.object(
        wb, "_registered_desktop_roots", return_value=(bundled.parents[4],)
    ), mock.patch.object(Path, "is_file", return_value=True):
        assert wb._desktop_cli_path() == bundled


def test_discovery_reports_error_when_nothing_found() -> None:
    with mock.patch.object(wb.shutil, "which", return_value=None), mock.patch.object(
        Path, "is_file", return_value=False
    ), mock.patch.object(wb, "_desktop_cli_path", return_value=None):
        result = wb.discover_workbuddy()
    assert not result.discovered
    assert result.errors


def test_probe_detects_all_required_flags() -> None:
    help_text = " ".join(wb.REQUIRED_FLAGS)
    caps = wb.probe_workbuddy_capabilities(
        _installation(), runner=_fake_runner(help_text)
    )
    assert isinstance(caps, WorkBuddyCapabilities)
    assert caps.ready
    assert set(caps.supported_flags) == set(wb.REQUIRED_FLAGS)
    assert caps.missing_flags == ()
    assert caps.version == "2.115.0"


def test_probe_reports_missing_flags() -> None:
    help_text = "-p --model --effort"
    caps = wb.probe_workbuddy_capabilities(
        _installation(), runner=_fake_runner(help_text)
    )
    assert not caps.ready
    assert set(caps.missing_flags) == set(wb.REQUIRED_FLAGS) - {"-p", "--model", "--effort"}


def test_probe_help_failure_is_not_ready() -> None:
    def runner(args: list[str]):
        if args[-1] == "--help":
            return 1, "", "command not found-ish"
        return 0, "", ""

    caps = wb.probe_workbuddy_capabilities(_installation(), runner=runner)
    assert not caps.help_available
    assert not caps.ready
    assert caps.missing_flags == tuple(wb.REQUIRED_FLAGS)


def test_probe_captures_node_version_when_present() -> None:
    def runner(args: list[str]):
        if args[-1] == "--help":
            return 0, " ".join(wb.REQUIRED_FLAGS), ""
        if args[-1] == "--version":
            return 0, "2.115.0", ""
        return 0, "", ""

    with mock.patch.object(wb.shutil, "which", return_value="C:/node/node.exe"):
        caps = wb.probe_workbuddy_capabilities(_installation(), runner=runner)
    assert caps.node_version is not None


def test_workbuddy_adapter_satisfies_protocol() -> None:
    from codex_task_broker.executors import ExecutorAdapter

    adapter = wb.WorkBuddyAdapter()
    assert isinstance(adapter, ExecutorAdapter)
    assert adapter.name == "workbuddy"

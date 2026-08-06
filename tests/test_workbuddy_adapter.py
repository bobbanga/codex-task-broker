"""Tests for the bounded executor adapter.

No test touches a real executor binary or a model. Argv tests build the command
from a synthetic installation, and end-to-end tests launch the subprocess-based
fake in ``tests/fakes/fake_workbuddy.py`` through the current Python
interpreter.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from codex_task_broker.broker import ExecutionSpec
from codex_task_broker.executors import WorkBuddyInstallation
from codex_task_broker.executors import workbuddy as wb

FAKE = Path(__file__).resolve().parent / "fakes" / "fake_workbuddy.py"


def _installation(path: Path) -> WorkBuddyInstallation:
    return WorkBuddyInstallation(
        path=path, source="explicit", sha256="a" * 64, version="2.115.0"
    )


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    worktree = tmp_path / "worktree"
    run_store = tmp_path / "runs" / "task-001"
    worktree.mkdir(parents=True)
    run_store.mkdir(parents=True)
    return worktree, run_store


def _request(tmp_path: Path, **overrides) -> wb.WorkBuddyExecutionRequest:
    worktree, run_store = _paths(tmp_path)
    defaults = {
        "installation": _installation(tmp_path / "tools" / "agent.exe"),
        "prompt": "Fix the failing test in src/example.py.",
        "worktree_path": worktree,
        "run_store_path": run_store,
        "model": "test-model",
    }
    defaults.update(overrides)
    return wb.WorkBuddyExecutionRequest(**defaults)


def _fake_request(
    tmp_path: Path, *, timeout_seconds: int = 30, **overrides
) -> wb.WorkBuddyExecutionRequest:
    """Build a request whose argv launches the fake through this interpreter."""
    profile = wb.WorkBuddyLaunchProfile(timeout_seconds=timeout_seconds)
    return _request(
        tmp_path,
        installation=_installation(FAKE),
        profile=profile,
        environment_allow=("FAKE_WORKBUDDY_SCENARIO", "FAKE_WORKBUDDY_TARGET"),
        **overrides,
    )


def _run_fake(
    monkeypatch: pytest.MonkeyPatch,
    request: wb.WorkBuddyExecutionRequest,
    scenario: str,
    target: "Path | None" = None,
) -> wb.WorkBuddyExecutorResult:
    """Execute the fake, forcing the interpreter as the argv[0] launcher."""
    monkeypatch.setenv("FAKE_WORKBUDDY_SCENARIO", scenario)
    if target is not None:
        monkeypatch.setenv("FAKE_WORKBUDDY_TARGET", str(target))
    monkeypatch.setattr(
        wb,
        "_invocation_args",
        lambda path, *args: [sys.executable, str(path), *args],
    )
    return wb.WorkBuddyAdapter().execute(request)


def test_adapter_accepts_the_brokers_generic_execution_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = _installation(tmp_path)
    capabilities = wb.WorkBuddyCapabilities(
        installation=installation,
        supported_flags=wb.REQUIRED_FLAGS,
        missing_flags=(),
        help_available=True,
        version="2.115.0",
        node_version="24.15.0",
        compatible=True,
    )
    adapter = wb.WorkBuddyAdapter()
    monkeypatch.setattr(
        adapter,
        "discover",
        lambda explicit_path=None: wb.DiscoveryResult(installation, ()),
    )
    monkeypatch.setattr(adapter, "probe", lambda found, runner=None: capabilities)
    monkeypatch.setattr(
        wb,
        "build_command",
        lambda request: (
            sys.executable,
            "-c",
            "import json; print(json.dumps({'ok': True}))",
        )
        if isinstance(request, wb.WorkBuddyExecutionRequest)
        else (_ for _ in ()).throw(AssertionError("request was not adapted")),
    )
    worktree = tmp_path / "worktree"
    run_store = tmp_path / "run-store"
    worktree.mkdir()
    run_store.mkdir()
    spec = ExecutionSpec(
        prompt="make the bounded change",
        worktree_path=worktree,
        run_store_path=run_store,
        model="hy3",
        timeout_seconds=30,
        environment_allow=(),
    )

    result = adapter.execute(spec)

    assert result.state == wb.EXECUTOR_OK
    assert result.payload == {"ok": True}


# --- argv construction -------------------------------------------------


def test_command_is_bounded_and_deterministic(tmp_path: Path) -> None:
    request = _request(tmp_path)
    adapter = wb.WorkBuddyAdapter()

    argv = adapter.build_command(request)

    assert argv == adapter.build_command(request)
    assert argv[0] == str(request.installation.path)
    assert argv[1] == "-p"
    assert argv[2] == request.prompt
    assert "--output-format" in argv and "json" in argv
    assert "--strict-mcp-config" in argv
    assert "--no-session-persistence" in argv
    assert "--max-turns" in argv
    assert argv[argv.index("--model") + 1] == "test-model"
    assert argv[argv.index("--mcp-config") + 1] == "{}"


def test_command_never_contains_bypass_or_extra_surfaces(tmp_path: Path) -> None:
    argv = wb.WorkBuddyAdapter().build_command(_request(tmp_path))

    for forbidden in wb.FORBIDDEN_FLAGS:
        assert forbidden not in argv
    for forbidden in wb.FORBIDDEN_PERMISSION_MODES:
        assert forbidden not in argv
    assert "--ide" not in argv and "--bg" not in argv and "--swarm" not in argv


def test_extensionless_cli_is_invoked_through_node(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wb.shutil, "which", lambda _: "C:/node/node.exe")
    request = _request(tmp_path, installation=_installation(tmp_path / "bin" / "agent"))

    argv = wb.WorkBuddyAdapter().build_command(request)

    assert argv[0] == "C:/node/node.exe"
    assert argv[1] == str(request.installation.path)
    assert argv[2] == "-p"


def test_add_dir_is_emitted_once_per_directory(tmp_path: Path) -> None:
    first = tmp_path / "runs" / "task-001"
    second = tmp_path / "runs" / "task-001" / "shared"
    request = _request(tmp_path, add_dirs=(first, second))

    argv = wb.WorkBuddyAdapter().build_command(request)

    assert [argv[i + 1] for i, t in enumerate(argv) if t == "--add-dir"] == [
        str(first),
        str(second),
    ]


def test_profile_rejects_permission_bypass() -> None:
    with pytest.raises(ValueError, match="bypass"):
        wb.WorkBuddyLaunchProfile(permission_mode="bypassPermissions")


def test_profile_defaults_stay_bounded() -> None:
    profile = wb.WorkBuddyLaunchProfile()

    assert profile.output_format == "json"
    assert profile.strict_mcp_config is True
    assert profile.session_persistence is False
    assert profile.max_turns >= 1
    assert profile.permission_mode not in wb.FORBIDDEN_PERMISSION_MODES


def test_request_rejects_run_store_inside_the_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(ValueError, match="outside the worktree"):
        wb.WorkBuddyExecutionRequest(
            installation=_installation(tmp_path / "agent.exe"),
            prompt="do the task",
            worktree_path=worktree,
            run_store_path=worktree / "runs",
            model="test-model",
        )


def test_request_requires_an_explicit_model(tmp_path: Path) -> None:
    worktree, run_store = _paths(tmp_path)

    with pytest.raises(ValueError, match="model"):
        wb.WorkBuddyExecutionRequest(
            installation=_installation(tmp_path / "agent.exe"),
            prompt="do the task",
            worktree_path=worktree,
            run_store_path=run_store,
            model="   ",
        )


def test_request_rejects_secret_shaped_environment_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="secret-shaped"):
        _request(tmp_path, environment_allow=("API_TOKEN",))


def test_request_rejects_add_dir_outside_run_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside the run store"):
        _request(tmp_path, add_dirs=(tmp_path / "outside",))


# --- output parsing ----------------------------------------------------


def test_parse_accepts_only_a_top_level_json_object() -> None:
    state, payload, errors = wb.parse_result('{"result": "ok"}', "", 0)
    assert state == wb.EXECUTOR_OK
    assert payload == {"result": "ok"}
    assert errors == ()

    for stdout in ("[]", '"text"', "null", "not json", '{"a":1}{"b":2}', ""):
        state, payload, errors = wb.parse_result(stdout, "", 0)
        assert state == wb.EXECUTOR_OUTPUT_INVALID, stdout
        assert payload is None
        assert errors


def test_parse_maps_timeout_before_anything_else() -> None:
    state, payload, errors = wb.parse_result("", "", None, timed_out=True)

    assert state == wb.EXECUTOR_TIMEOUT
    assert payload is None
    assert errors == ("executor_timeout",)


def test_parse_maps_permission_output_before_exit_code() -> None:
    state, _, errors = wb.parse_result("", "permission required: Write", 1)

    assert state == wb.EXECUTOR_PERMISSION_REQUIRED
    assert errors == ("executor_permission_required",)


def test_parse_maps_non_zero_exit_to_failure() -> None:
    state, payload, errors = wb.parse_result('{"result": "ok"}', "boom", 1)

    assert state == wb.EXECUTOR_FAILED
    assert payload is None
    assert errors == ("executor_nonzero:1",)


# --- fake executor scenarios -------------------------------------------


def test_fake_success_parses_and_edits_only_the_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)
    target = request.worktree_path / "example.py"

    result = _run_fake(monkeypatch, request, "success", target)

    assert result.state == wb.EXECUTOR_OK
    assert result.ok
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.payload["subtype"] == "success"
    assert target.read_text(encoding="utf-8") == "edited by the fake executor\n"
    assert [p.name for p in request.worktree_path.iterdir()] == ["example.py"]


def test_fake_malformed_json_maps_to_output_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    result = _run_fake(monkeypatch, request, "malformed_json")

    assert result.state == wb.EXECUTOR_OUTPUT_INVALID
    assert result.payload is None
    assert result.exit_code == 0


def test_fake_nonzero_exit_maps_to_executor_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    result = _run_fake(monkeypatch, request, "nonzero")

    assert result.state == wb.EXECUTOR_FAILED
    assert result.exit_code == 1
    assert result.errors == ("executor_nonzero:1",)


def test_fake_permission_required_maps_to_permission_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    result = _run_fake(monkeypatch, request, "permission_required")

    assert result.state == wb.EXECUTOR_PERMISSION_REQUIRED
    assert "permission required" in result.stderr_path.read_text(encoding="utf-8")


def test_fake_timeout_maps_to_executor_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path, timeout_seconds=1)

    result = _run_fake(monkeypatch, request, "timeout")

    assert result.state == wb.EXECUTOR_TIMEOUT
    assert result.timed_out is True
    assert result.exit_code is None


# --- evidence and isolation --------------------------------------------


def test_raw_output_is_persisted_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    result = _run_fake(monkeypatch, request, "malformed_json")

    assert result.stdout_path == request.run_store_path / wb.EXECUTOR_STDOUT_NAME
    assert result.stderr_path == request.run_store_path / wb.EXECUTOR_STDERR_NAME
    # Unparseable output is still kept verbatim as evidence.
    assert result.stdout_path.read_text(encoding="utf-8").startswith('{"type"')


def test_result_never_claims_executor_reports_are_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    result = _run_fake(monkeypatch, request, "success", request.worktree_path / "x.py")

    assert result.to_dict()["claims_are_authoritative"] is False


def test_child_environment_contains_only_allowlisted_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_BROKER_SECRET_LIKE", "must-not-leak")
    monkeypatch.setenv("CODEX_BROKER_ALLOWED", "visible")

    environment = wb._child_environment(("CODEX_BROKER_ALLOWED",))

    assert environment == {"CODEX_BROKER_ALLOWED": "visible"}


def test_execute_uses_shell_false_and_the_worktree_as_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)

        class Completed:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return Completed()

    monkeypatch.setattr(wb.subprocess, "run", fake_run)
    wb.WorkBuddyAdapter().execute(request)

    assert captured["shell"] is False
    assert captured["check"] is False
    assert captured["cwd"] == str(request.worktree_path)
    assert captured["timeout"] == request.timeout_seconds


def test_execute_invokes_the_executor_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))

        class Completed:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return Completed()

    monkeypatch.setattr(wb.subprocess, "run", fake_run)
    wb.WorkBuddyAdapter().execute(request)

    assert len(calls) == 1


def test_start_failure_maps_to_executor_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    def fake_run(argv, **kwargs):
        raise OSError("executable not found")

    monkeypatch.setattr(wb.subprocess, "run", fake_run)
    result = wb.WorkBuddyAdapter().execute(request)

    assert result.state == wb.EXECUTOR_FAILED
    assert result.errors == ("executor_start_failed",)
    assert "not found" in result.stderr_path.read_text(encoding="utf-8")


def test_fake_rejects_a_forbidden_flag() -> None:
    """The fake fails closed, so a widened argv can never silently pass."""
    sys.path.insert(0, str(FAKE.parent))
    try:
        import fake_workbuddy
    finally:
        sys.path.pop(0)

    with pytest.raises(SystemExit) as excinfo:
        fake_workbuddy.parse_args(["--dangerously-skip-permissions"])
    assert excinfo.value.code == 64


def test_fake_scenarios_cover_every_terminal_state() -> None:
    sys.path.insert(0, str(FAKE.parent))
    try:
        import fake_workbuddy
    finally:
        sys.path.pop(0)

    assert set(fake_workbuddy.SCENARIOS) == {
        "success",
        "malformed_json",
        "nonzero",
        "timeout",
        "permission_required",
    }


def test_success_payload_is_a_single_top_level_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _fake_request(tmp_path)

    result = _run_fake(monkeypatch, request, "success", request.worktree_path / "a.py")
    raw = result.stdout_path.read_text(encoding="utf-8")

    assert isinstance(json.loads(raw), dict)

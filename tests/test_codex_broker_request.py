from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_task_broker.profile import CommandProfile
from codex_task_broker.request import RunRequest

BASE_SHA = "0123456789abcdef0123456789abcdef01234567"
BRIEFING_SHA256 = "b" * 64


def _request(tmp_path: Path, **overrides: object) -> dict:
    worktree = tmp_path / "worktree"
    run_store = tmp_path / "run-store"
    data: dict = {
        "schema": "codex-task-broker-run-request",
        "schema_version": 1,
        "mode": "mock_only",
        "task_id": "TASK-001",
        "task_revision": 1,
        "attempt": 1,
        "work_order_path": str(tmp_path / "work-order.json"),
        "briefing_path": str(tmp_path / "briefing.json"),
        "worktree_path": str(worktree),
        "run_store_path": str(run_store),
        "base_sha": BASE_SHA,
        "briefing_sha256": BRIEFING_SHA256,
        "allowed_files": ["src/example.py"],
        "forbidden_files": [".git/**", ".env"],
        "contributor": {
            "executable": "py",
            "argv": ["contributor.py"],
            "timeout_seconds": 120,
            "environment_allow": [],
        },
        "verification_commands": [["py", "-3", "-m", "pytest", "-q"]],
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: object, name: str = "run-request.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_run_request_accepts_the_approved_design_example(tmp_path: Path) -> None:
    path = _write(tmp_path, _request(tmp_path))

    request = RunRequest.from_path(path)

    assert request.schema == "codex-task-broker-run-request"
    assert request.schema_version == 1
    assert request.mode == "mock_only"
    assert request.task_id == "TASK-001"
    assert request.task_revision == 1
    assert request.attempt == 1
    assert request.base_sha == BASE_SHA
    assert request.briefing_sha256 == BRIEFING_SHA256
    assert request.worktree_path == (tmp_path / "worktree").resolve()
    assert request.run_store_path == (tmp_path / "run-store").resolve()
    assert request.work_order_path == (tmp_path / "work-order.json").resolve()
    assert request.briefing_path == (tmp_path / "briefing.json").resolve()
    assert request.allowed_files == ("src/example.py",)
    assert request.forbidden_files == (".git/**", ".env")
    assert request.contributor.executable == "py"
    assert request.contributor.argv == ("contributor.py",)
    assert request.contributor.timeout_seconds == 120
    assert request.contributor.environment_allow == ()
    assert request.verification_commands == (("py", "-3", "-m", "pytest", "-q"),)


def test_run_request_values_are_immutable(tmp_path: Path) -> None:
    request = RunRequest.from_path(_write(tmp_path, _request(tmp_path)))

    with pytest.raises(Exception):
        request.mode = "project_prototype"  # type: ignore[misc]
    with pytest.raises(Exception):
        request.contributor.timeout_seconds = 1  # type: ignore[misc]


def test_run_request_rejects_the_old_codex_workbuddy_schema(tmp_path: Path) -> None:
    """The superseded schema name is not an accepted alias.

    There has been no PyPI release, so no old Run Request needs to keep working.
    """
    data = _request(tmp_path, schema="codex-workbuddy-run-request")

    with pytest.raises(ValueError, match="codex-task-broker-run-request"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    data = _request(tmp_path)
    data["model"] = "inferred"

    with pytest.raises(ValueError, match="unexpected"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_unknown_contributor_field(tmp_path: Path) -> None:
    data = _request(tmp_path)
    data["contributor"] = {**data["contributor"], "shell": True}  # type: ignore[dict-item]

    with pytest.raises(ValueError, match="unexpected"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_missing_field(tmp_path: Path) -> None:
    data = _request(tmp_path)
    del data["run_store_path"]

    with pytest.raises(ValueError, match="missing"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_non_mock_mode(tmp_path: Path) -> None:
    data = _request(tmp_path, mode="project_prototype")

    with pytest.raises(ValueError, match="mode"):
        RunRequest.from_path(_write(tmp_path, data))


@pytest.mark.parametrize("field", ["schema_version", "task_revision", "attempt"])
def test_run_request_rejects_boolean_integer_fields(tmp_path: Path, field: str) -> None:
    data = _request(tmp_path)
    data[field] = True

    with pytest.raises(ValueError, match=field):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_boolean_contributor_timeout(tmp_path: Path) -> None:
    data = _request(tmp_path)
    data["contributor"] = {**data["contributor"], "timeout_seconds": True}  # type: ignore[dict-item]

    with pytest.raises(ValueError, match="timeout_seconds"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_non_positive_contributor_timeout(tmp_path: Path) -> None:
    data = _request(tmp_path)
    data["contributor"] = {**data["contributor"], "timeout_seconds": 0}  # type: ignore[dict-item]

    with pytest.raises(ValueError, match="timeout_seconds"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_string_verification_command(tmp_path: Path) -> None:
    data = _request(tmp_path, verification_commands=["py -3 -m pytest -q"])

    with pytest.raises(ValueError, match="verification_commands"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_empty_verification_commands(tmp_path: Path) -> None:
    data = _request(tmp_path, verification_commands=[])

    with pytest.raises(ValueError, match="verification_commands"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_run_store_inside_worktree(tmp_path: Path) -> None:
    data = _request(tmp_path)
    data["run_store_path"] = str(tmp_path / "worktree" / "run-store")

    with pytest.raises(ValueError, match="run store"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_allowed_and_forbidden_overlap(tmp_path: Path) -> None:
    data = _request(tmp_path, allowed_files=["src/example.py", ".env"])

    with pytest.raises(ValueError, match="overlap"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_empty_allowed_files(tmp_path: Path) -> None:
    data = _request(tmp_path, allowed_files=[])

    with pytest.raises(ValueError, match="allowed_files"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_absolute_forbidden_files(tmp_path: Path) -> None:
    data = _request(tmp_path, forbidden_files=["C:/outside.py"])

    with pytest.raises(ValueError, match="forbidden_files"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_escaping_forbidden_files(tmp_path: Path) -> None:
    data = _request(tmp_path, forbidden_files=["../escape.py"])

    with pytest.raises(ValueError, match="forbidden_files"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_absolute_and_escaping_allowed_files(tmp_path: Path) -> None:
    escaping = _request(tmp_path, allowed_files=["../outside.py"])
    with pytest.raises(ValueError, match="allowed_files"):
        RunRequest.from_path(_write(tmp_path, escaping))

    absolute = _request(tmp_path, allowed_files=["C:/outside.py"])
    with pytest.raises(ValueError, match="allowed_files"):
        RunRequest.from_path(_write(tmp_path, absolute))


@pytest.mark.parametrize("name", ["API_TOKEN", "my_secret", "PASSWORD", "AWS_KEY"])
def test_run_request_rejects_secret_shaped_environment_allow(tmp_path: Path, name: str) -> None:
    data = _request(tmp_path)
    data["contributor"] = {  # type: ignore[dict-item]
        **data["contributor"],
        "environment_allow": [name],
    }

    with pytest.raises(ValueError, match="environment_allow"):
        RunRequest.from_path(_write(tmp_path, data))


@pytest.mark.parametrize("value", ["", "abc", "A" * 40, "0" * 39, "0" * 41])
def test_run_request_rejects_malformed_base_sha(tmp_path: Path, value: str) -> None:
    data = _request(tmp_path, base_sha=value)

    with pytest.raises(ValueError, match="base_sha"):
        RunRequest.from_path(_write(tmp_path, data))


@pytest.mark.parametrize("value", ["", "abc", "B" * 64, "b" * 63, "b" * 65])
def test_run_request_rejects_malformed_briefing_sha256(tmp_path: Path, value: str) -> None:
    data = _request(tmp_path, briefing_sha256=value)

    with pytest.raises(ValueError, match="briefing_sha256"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_relative_paths(tmp_path: Path) -> None:
    data = _request(tmp_path, worktree_path="worktree")

    with pytest.raises(ValueError, match="worktree_path"):
        RunRequest.from_path(_write(tmp_path, data))


def test_run_request_rejects_malformed_json_and_non_object(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        RunRequest.from_path(broken)

    with pytest.raises(ValueError, match="object"):
        RunRequest.from_path(_write(tmp_path, ["run-request"], name="list.json"))


def test_run_request_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid"):
        RunRequest.from_path(tmp_path / "absent.json")


def test_command_profile_renders_from_request_and_binds_canonical_bytes(tmp_path: Path) -> None:
    request = RunRequest.from_path(_write(tmp_path, _request(tmp_path)))

    profile = CommandProfile.from_request(request)

    assert profile.executable == "py"
    assert profile.argv == ("contributor.py",)
    assert profile.cwd == request.worktree_path
    assert profile.timeout_seconds == 120
    assert profile.environment_allow == ()
    assert profile.allowed_external_effects == ()
    assert profile.stdout_path.is_relative_to(request.run_store_path)
    assert profile.stderr_path.is_relative_to(request.run_store_path)
    assert len(profile.sha256()) == 64


def test_command_profile_write_is_deterministic_and_reproducible(tmp_path: Path) -> None:
    request = RunRequest.from_path(_write(tmp_path, _request(tmp_path)))
    profile = CommandProfile.from_request(request)
    path = tmp_path / "command-profile.json"

    profile.write(path)
    first = path.read_bytes()
    profile.write(path)

    assert path.read_bytes() == first
    written = json.loads(first.decode("utf-8"))
    assert written["executable"] == "py"
    assert written["argv"] == ["contributor.py"]
    assert written["allowed_external_effects"] == []
    assert CommandProfile.from_request(request).sha256() == profile.sha256()


def test_command_profile_is_immutable(tmp_path: Path) -> None:
    request = RunRequest.from_path(_write(tmp_path, _request(tmp_path)))
    profile = CommandProfile.from_request(request)

    with pytest.raises(Exception):
        profile.executable = "cmd"  # type: ignore[misc]

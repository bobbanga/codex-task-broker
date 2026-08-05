"""Contract tests for the public open-source surface of this repository."""

import json
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]


def _schema() -> dict:
    return json.loads((ROOT / "schemas/run-request.schema.json").read_text("utf-8"))


def _example() -> dict:
    return json.loads((ROOT / "examples/minimal-run-request.json").read_text("utf-8"))


def test_required_public_files_exist() -> None:
    for name in (
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "CHANGELOG.md",
        "ROADMAP.md",
        "README.md",
        "README.en.md",
    ):
        assert (ROOT / name).is_file(), name


def test_license_is_mit_for_bob_zhang() -> None:
    text = (ROOT / "LICENSE").read_text("utf-8")
    assert "MIT License" in text
    assert "Copyright (c) 2026 Bob Zhang" in text
    assert "WITHOUT WARRANTY OF ANY KIND" in text


def test_package_metadata_is_complete() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["license"] == "MIT"
    assert project["authors"]
    assert project["urls"]["Repository"].endswith("/codex-task-broker")
    assert project["classifiers"]


def test_project_urls_point_at_the_public_repository() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    urls = project["urls"]
    home = "https://github.com/bobbanga/codex-task-broker"
    assert urls["Homepage"] == home
    assert urls["Repository"] == home
    assert urls["Issues"] == f"{home}/issues"
    assert urls["Changelog"] == f"{home}/blob/main/CHANGELOG.md"
    # PEP 639 forbids the legacy "License :: OSI Approved :: MIT License"
    # classifier alongside the `license` SPDX expression; setuptools rejects it.
    assert not any(item.startswith("License ::") for item in project["classifiers"])


def test_security_policy_uses_github_advisories_without_personal_email() -> None:
    text = (ROOT / "SECURITY.md").read_text("utf-8")
    assert "Security Advisories" in text
    assert "@" not in text


def test_roadmap_has_exactly_three_horizons_and_no_promises() -> None:
    text = (ROOT / "ROADMAP.md").read_text("utf-8")
    horizons = [line for line in text.splitlines() if line.startswith("## ")]
    assert len(horizons) == 3, horizons
    lowered = text.lower()
    assert "workbuddy" in lowered
    assert "adapter" in lowered
    assert "routing" in lowered
    assert "not promises" in lowered


def test_dev_extra_provides_the_schema_validator() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    dev = project["optional-dependencies"]["dev"]
    assert "jsonschema>=4.23" in dev


def test_build_backend_minimum_supports_pep_639_metadata() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    # PEP 639 `license`/`license-files` need setuptools 77 or newer.
    assert "setuptools>=77" in config["build-system"]["requires"]
    assert config["project"]["license-files"] == ["LICENSE"]


def test_example_conforms_to_public_schema_identity() -> None:
    schema = _schema()
    assert schema["$id"].endswith("run-request.schema.json")
    assert _example()["schema"] == "codex-task-broker-run-request"


def test_schema_itself_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_schema())


def test_example_validates_against_the_schema() -> None:
    Draft202012Validator(_schema()).validate(_example())


def test_schema_is_strict_draft_2020_12_matching_the_request_model() -> None:
    from codex_task_broker.request import CONTRIBUTOR_KEYS, REQUEST_KEYS

    schema = json.loads((ROOT / "schemas/run-request.schema.json").read_text("utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == REQUEST_KEYS
    assert set(schema["properties"]) == REQUEST_KEYS

    contributor = schema["properties"]["contributor"]
    assert contributor["additionalProperties"] is False
    assert set(contributor["required"]) == CONTRIBUTOR_KEYS
    assert set(contributor["properties"]) == CONTRIBUTOR_KEYS


def test_example_request_parses_and_carries_no_credentials() -> None:
    from codex_task_broker.request import RunRequest

    raw = (ROOT / "examples/minimal-run-request.json").read_text("utf-8")
    request = RunRequest.from_dict(json.loads(raw))
    assert request.mode == "mock_only"
    lowered = raw.lower()
    for marker in ("token", "password", "secret", "credential", "apikey"):
        assert marker not in lowered
    assert "users\\" not in lowered


@pytest.mark.parametrize(
    "bad_path",
    ["/example/runs/task", "\\example\\runs\\task", "/", "\\", "example\\runs"],
)
def test_schema_rejects_paths_that_are_not_windows_absolute(bad_path: str) -> None:
    instance = _example() | {"worktree_path": bad_path}
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(instance)


@pytest.mark.parametrize(
    "good_path",
    ["C:\\example\\worktrees\\demo", "c:/example/worktrees/demo", "\\\\server\\share\\demo"],
)
def test_schema_accepts_drive_root_and_unc_paths(good_path: str) -> None:
    instance = _example() | {"worktree_path": good_path}
    Draft202012Validator(_schema()).validate(instance)


@pytest.mark.parametrize(
    "escape",
    ["..", "../outside.py", "..\\outside.py", "src/../../outside.py", "src\\..\\out.py", "src/.."],
)
def test_schema_rejects_repository_escapes(escape: str) -> None:
    instance = _example() | {"allowed_files": [escape]}
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(instance)


@pytest.mark.parametrize("name", ["src/demo/file..txt", "a..b.py", "src/..hidden/x.py"])
def test_schema_allows_ordinary_names_containing_two_dots(name: str) -> None:
    instance = _example() | {"allowed_files": [name]}
    Draft202012Validator(_schema()).validate(instance)


def test_ci_covers_windows_python_311_and_312_with_a_build_smoke_test() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text("utf-8")
    assert "windows-latest" in text
    assert '"3.11"' in text
    assert '"3.12"' in text
    assert "ruff check src tests" in text
    assert "pytest" in text
    assert "python -m build" in text
    assert "codex-broker --help" in text


def test_github_community_templates_exist() -> None:
    for name in (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/pull_request_template.md",
    ):
        assert (ROOT / name).is_file(), name

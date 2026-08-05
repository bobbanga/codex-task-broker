from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from codex_task_broker.artifacts import (
    build_manifest,
    build_result,
    read_manifest,
    read_result,
    sha256_file,
    write_json,
)


def _facts() -> dict:
    return {
        "task_id": "TASK-001",
        "task_revision": 1,
        "attempt": 1,
        "base_sha": "a" * 40,
        "parent_sha": "a" * 40,
        "implementation_sha": "b" * 40,
        "snapshot_sha": "b" * 40,
        "briefing_sha256": "c" * 64,
        "command_profile_sha256": "d" * 64,
        "changed_files": ["src/example.py"],
        "workspace_clean": True,
        "verification": [{"command": ["py", "-3", "-m", "pytest", "-q"], "exit_code": 0}],
    }


def _chain(tmp_path: Path, state: str = "REVIEW_READY") -> tuple[Path, Path, Path]:
    evidence_path = tmp_path / "evidence.json"
    manifest_path = tmp_path / "run-manifest.json"
    result_path = tmp_path / "runner-result.json"

    write_json(evidence_path, _facts())
    write_json(manifest_path, build_manifest(evidence_path, _facts()))
    write_json(result_path, build_result(manifest_path, evidence_path, state, []))
    return evidence_path, manifest_path, result_path


def test_sha256_file_hashes_exact_artifact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b'{"a": 1}\n')

    assert sha256_file(path) == hashlib.sha256(b'{"a": 1}\n').hexdigest()


def test_write_json_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_json(first, {"b": 2, "a": 1})
    write_json(second, {"a": 1, "b": 2})

    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


def test_manifest_binds_exact_evidence_bytes(tmp_path: Path) -> None:
    evidence_path, manifest_path, _ = _chain(tmp_path)

    manifest = read_manifest(manifest_path, evidence_path)

    assert manifest["schema"] == "v0.9a-evidence-manifest"
    assert manifest["schema_version"] == 1
    assert manifest["task_id"] == "TASK-001"
    assert (
        manifest["evidence_sha256"]
        == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    )


def test_result_binds_exact_manifest_and_evidence_bytes(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)

    result = read_result(result_path, manifest_path, evidence_path)

    assert result["schema"] == "v0.9a-runner-result"
    assert result["state"] == "REVIEW_READY"
    assert result["errors"] == []
    assert result["codebuddy_invoked"] is False
    assert (
        result["manifest_sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )
    assert (
        result["evidence_sha256"]
        == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    )


def test_readers_reject_evidence_drift(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)
    evidence_path.write_text("drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="evidence"):
        read_manifest(manifest_path, evidence_path)
    with pytest.raises(ValueError, match="evidence"):
        read_result(result_path, manifest_path, evidence_path)


def test_result_reader_rejects_manifest_drift(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)
    drifted = read_manifest(manifest_path, evidence_path)
    drifted["changed_files"] = ["src/example.py", "src/extra.py"]
    write_json(manifest_path, drifted)

    with pytest.raises(ValueError, match="manifest"):
        read_result(result_path, manifest_path, evidence_path)


def test_whitespace_only_drift_is_rejected(tmp_path: Path) -> None:
    evidence_path, manifest_path, _ = _chain(tmp_path)
    evidence_path.write_bytes(evidence_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="evidence"):
        read_manifest(manifest_path, evidence_path)


def test_readers_reject_unknown_fields(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)

    manifest = read_manifest(manifest_path, evidence_path)
    manifest["model"] = "inferred"
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="manifest schema"):
        read_manifest(manifest_path, evidence_path)

    evidence_path, manifest_path, result_path = _chain(tmp_path)
    result = read_result(result_path, manifest_path, evidence_path)
    result["approved"] = True
    write_json(result_path, result)
    with pytest.raises(ValueError, match="result schema"):
        read_result(result_path, manifest_path, evidence_path)


def test_readers_reject_missing_fields(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)

    manifest = read_manifest(manifest_path, evidence_path)
    del manifest["workspace_clean"]
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="manifest schema"):
        read_manifest(manifest_path, evidence_path)

    evidence_path, manifest_path, result_path = _chain(tmp_path)
    result = read_result(result_path, manifest_path, evidence_path)
    del result["state"]
    write_json(result_path, result)
    with pytest.raises(ValueError, match="result schema"):
        read_result(result_path, manifest_path, evidence_path)


def test_readers_reject_wrong_schema_version(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)

    manifest = read_manifest(manifest_path, evidence_path)
    manifest["schema_version"] = 2
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="manifest schema version"):
        read_manifest(manifest_path, evidence_path)

    evidence_path, manifest_path, result_path = _chain(tmp_path)
    result = read_result(result_path, manifest_path, evidence_path)
    result["schema"] = "v0.9a-review-input"
    write_json(result_path, result)
    with pytest.raises(ValueError, match="result schema version"):
        read_result(result_path, manifest_path, evidence_path)


def test_readers_reject_malformed_json_and_non_objects(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)

    manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid artifact"):
        read_manifest(manifest_path, evidence_path)

    manifest_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        read_manifest(manifest_path, evidence_path)

    result_path.write_text("null", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        read_result(result_path, manifest_path, evidence_path)


def test_readers_reject_missing_artifact_files(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)
    manifest_path.unlink()

    with pytest.raises(ValueError, match="invalid artifact"):
        read_manifest(manifest_path, evidence_path)
    with pytest.raises(ValueError, match="invalid artifact"):
        read_result(result_path, manifest_path, evidence_path)


def test_result_reader_rejects_codebuddy_invoked_not_false(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)
    result = read_result(result_path, manifest_path, evidence_path)
    result["codebuddy_invoked"] = True
    write_json(result_path, result)

    with pytest.raises(ValueError, match="codebuddy_invoked"):
        read_result(result_path, manifest_path, evidence_path)


def test_builders_reject_invalid_inputs(tmp_path: Path) -> None:
    evidence_path, manifest_path, _ = _chain(tmp_path)

    with pytest.raises(ValueError, match="facts"):
        build_manifest(evidence_path, ["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="facts"):
        build_manifest(evidence_path, {**_facts(), "schema": "override"})
    with pytest.raises(ValueError, match="facts"):
        build_manifest(evidence_path, {"task_id": "TASK-001"})
    with pytest.raises(ValueError, match="state"):
        build_result(manifest_path, evidence_path, "", [])
    with pytest.raises(ValueError, match="errors"):
        build_result(manifest_path, evidence_path, "EVIDENCE_FAILED", [1])  # type: ignore[list-item]


def test_build_manifest_requires_existing_evidence_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid artifact"):
        build_manifest(tmp_path / "absent.json", _facts())


def test_build_result_rejects_unknown_state(tmp_path: Path) -> None:
    evidence_path, manifest_path, _ = _chain(tmp_path)

    with pytest.raises(ValueError, match="state"):
        build_result(manifest_path, evidence_path, "UNKNOWN_STATE", [])


def test_read_result_rejects_unknown_persisted_state(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path)
    result = read_result(result_path, manifest_path, evidence_path)
    result["state"] = "UNKNOWN_STATE"
    write_json(result_path, result)

    with pytest.raises(ValueError, match="state"):
        read_result(result_path, manifest_path, evidence_path)


def test_failure_states_are_representable(tmp_path: Path) -> None:
    evidence_path, manifest_path, result_path = _chain(tmp_path, state="EVIDENCE_FAILED")
    write_json(
        result_path,
        build_result(manifest_path, evidence_path, "EVIDENCE_FAILED", ["scope violation"]),
    )

    result = read_result(result_path, manifest_path, evidence_path)

    assert result["state"] == "EVIDENCE_FAILED"
    assert result["errors"] == ["scope violation"]
    assert result["codebuddy_invoked"] is False

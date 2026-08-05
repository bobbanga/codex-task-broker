"""Evidence Manifest and Runner Result binding to exact artifact bytes.

Hashes always come from raw file bytes, and readers recompute them on every
call so that any drift, including whitespace-only drift, fails closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_SCHEMA = "v0.9a-evidence-manifest"
RESULT_SCHEMA = "v0.9a-runner-result"
SCHEMA_VERSION = 1

FACT_KEYS = frozenset(
    {
        "task_id",
        "task_revision",
        "attempt",
        "base_sha",
        "parent_sha",
        "implementation_sha",
        "snapshot_sha",
        "briefing_sha256",
        "command_profile_sha256",
        "changed_files",
        "workspace_clean",
        "verification",
    }
)
MANIFEST_REQUIRED = frozenset(
    {"schema", "schema_version", "evidence_sha256"} | set(FACT_KEYS)
)
RESULT_REQUIRED = frozenset(
    {
        "schema",
        "schema_version",
        "manifest_sha256",
        "evidence_sha256",
        "state",
        "errors",
        "codebuddy_invoked",
    }
)

RESULT_STATES = frozenset(
    {
        "PREFLIGHT_FAILED",
        "CONTRIBUTOR_STOPPED",
        "EVIDENCE_FAILED",
        "REVIEW_READY",
        "INTERNAL_ERROR",
    }
)


def sha256_file(path: Path) -> str:
    """Hash the exact bytes on disk."""
    target = Path(path)
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"invalid artifact: {target}") from exc


def write_json(path: Path, value: dict) -> None:
    """Write one artifact deterministically."""
    if not isinstance(value, dict):
        raise ValueError("artifact must be an object")
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    Path(path).write_text(payload, encoding="utf-8", newline="\n")


def write_text_artifact(path: Path, text: str) -> Path:
    """Persist raw executor output bytes exactly as captured.

    Raw process output is evidence, not a decision: it is written verbatim
    before any parsing so that malformed, truncated, or timed-out output stays
    inspectable. Only the line ending is normalised so hashes stay stable
    across platforms.
    """
    if not isinstance(text, str):
        raise ValueError("artifact text must be a string")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def _read_object(path: Path) -> dict:
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"invalid artifact: {target}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid artifact: {target}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be an object: {target}")
    return value


def build_manifest(evidence_path: Path, facts: dict) -> dict:
    if not isinstance(facts, dict):
        raise ValueError("facts must be an object")
    unknown = set(facts) - FACT_KEYS
    if unknown:
        raise ValueError(f"unexpected facts fields: {sorted(unknown)}")
    missing = FACT_KEYS - set(facts)
    if missing:
        raise ValueError(f"missing facts fields: {sorted(missing)}")
    return {
        "schema": MANIFEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        **facts,
        "evidence_sha256": sha256_file(evidence_path),
    }


def read_manifest(manifest_path: Path, evidence_path: Path) -> dict:
    value = _read_object(manifest_path)
    if set(value) != MANIFEST_REQUIRED:
        raise ValueError("manifest schema mismatch")
    if value["schema"] != MANIFEST_SCHEMA or value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("manifest schema version mismatch")
    if value["evidence_sha256"] != sha256_file(evidence_path):
        raise ValueError("evidence artifact drift")
    return value


def build_result(
    manifest_path: Path, evidence_path: Path, state: str, errors: list[str]
) -> dict:
    if not isinstance(state, str) or not state.strip():
        raise ValueError("state is required")
    if state not in RESULT_STATES:
        raise ValueError("state must be one of the allowed result states")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        raise ValueError("errors must be a list of strings")
    return {
        "schema": RESULT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": sha256_file(manifest_path),
        "evidence_sha256": sha256_file(evidence_path),
        "state": state,
        "errors": list(errors),
        "codebuddy_invoked": False,
    }


def read_result(result_path: Path, manifest_path: Path, evidence_path: Path) -> dict:
    value = _read_object(result_path)
    if set(value) != RESULT_REQUIRED:
        raise ValueError("result schema mismatch")
    if value["schema"] != RESULT_SCHEMA or value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("result schema version mismatch")
    if value["state"] not in RESULT_STATES:
        raise ValueError("state must be one of the allowed result states")
    if value["manifest_sha256"] != sha256_file(manifest_path):
        raise ValueError("manifest artifact drift")
    if value["evidence_sha256"] != sha256_file(evidence_path):
        raise ValueError("evidence artifact drift")
    if value["codebuddy_invoked"] is not False:
        raise ValueError("codebuddy_invoked must remain false")
    return value

# Schemas

V0.1a uses four structured JSON artifacts: Work Order, Execution Report, Run Manifest, and Review Decision.

The Work Order is the only instruction packet for the mock executor. It includes `base_sha`, `repo_path`, `worktree_path`, `allowed_files`, `forbidden_files`, `acceptance_criteria`, `required_tests`, a minimum `permission_profile`, and `limits.max_rework_attempts`.

The Execution Report is advisory. It may include summary, risks, claimed changed files, out-of-scope requests, and requested external effects. It must not be treated as evidence for changed files, implementation SHA, or test success.

The Run Manifest is coordinator evidence. It records explicit `base_sha`, explicit `implementation_sha`, `git diff base_sha..implementation_sha`, workspace scan results, coordinator-run test commands, exit codes, and external run store paths.

For `project_prototype` runs that participate in the V0.9a rehearsal, the Work Order must additionally carry `task_id`, `task_revision`, `attempt`, and `briefing_sha256`. The implementation commit must contain a contiguous trailer block with `Task-ID`, `Task-Revision`, `Attempt`, `Base-SHA`, and `Briefing-SHA256`. The coordinator must independently compare those values with the Work Order and bind Evidence and Review Decision to the same exact Snapshot SHA.

The Review Decision records exactly one of `APPROVED`, `CHANGES_REQUESTED`, `REPLAN_REQUIRED`, or `ESCALATED`.

Runtime artifacts belong in the external run store, not in the project commit path.

V0.9a Stage 1c freezes the command profile and the smallest Evidence Manifest/Runner Result chain without adding runtime authority. A profile explicitly binds its identity, executable, fixed argv, validated worktree cwd, timeout, environment boundary, and empty `allowed_external_effects`; it has no inferred model, plugin, MCP, network, credential, scheduler, or GUI fields. The Manifest records coordinator-recomputed Git, Snapshot, verification, and profile hashes. The Result records Manifest/Evidence hashes, terminal state, errors, and `codebuddy_invoked`; exact artifact-byte drift fails closed.

The implemented Stage 1c validator lives in the coordinator test-support package. `CommandProfile` rejects unknown or missing fields, secret-shaped environment allow entries, output paths outside the external run store, cwd outside the isolated worktree, and all external effects. `run-manifest.json` binds the exact bytes of `evidence.json`; `runner-result.json` binds the exact bytes of both artifacts and requires `codebuddy_invoked=false`.

## Run Request (cross-project CLI)

The `codex-workbuddy` console command reads exactly one Run Request JSON file. That file is the only editable input owner; the CLI infers nothing from chat, cwd, environment, project metadata, or model defaults.

```json
{
  "schema": "codex-workbuddy-run-request",
  "schema_version": 1,
  "mode": "mock_only",
  "task_id": "TASK-001",
  "task_revision": 1,
  "attempt": 1,
  "work_order_path": "C:/path/work-order.json",
  "briefing_path": "C:/path/briefing.json",
  "worktree_path": "C:/path/isolated-worktree",
  "run_store_path": "C:/path/external-run-store",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "briefing_sha256": "<64 lowercase hex characters>",
  "allowed_files": ["src/example.py"],
  "forbidden_files": [".git/**", ".env"],
  "contributor": {
    "executable": "py",
    "argv": ["contributor.py"],
    "timeout_seconds": 120,
    "environment_allow": []
  },
  "verification_commands": [["py", "-3", "-m", "pytest", "-q"]]
}
```

Field rules:

- Unknown, missing, or misfiled keys are rejected; `mode` must equal `mock_only`.
- `task_revision`, `attempt`, and `contributor.timeout_seconds` are positive integers; `bool` is invalid.
- `base_sha` is a 40-character hex Snapshot base; `briefing_sha256` is 64 lowercase hex characters bound to the Briefing bytes.
- `verification_commands` are argv arrays, never strings, and run with `shell=false`.
- `contributor.environment_allow` rejects secret-shaped names; the child never inherits the parent environment.
- `run_store_path` must resolve outside `worktree_path`; runtime artifacts never enter the project commit path.
- There is no requestable field for network, credentials, install, push, merge, deploy, publication, or any other external effect.

`validate` stops at `VALIDATED` without starting the Contributor. `run` repeats the same validation and stops at `REVIEW_READY`. Exit codes are `0` `REVIEW_READY`, `2` `PREFLIGHT_FAILED`, `3` `CONTRIBUTOR_STOPPED`, `4` `EVIDENCE_FAILED`, `5` `INTERNAL_ERROR`. The CLI contains no real WorkBuddy invocation path.

## Stage 1b Runner

Stage 1b Runner inputs are explicit local paths, one task attempt, one Contributor argv, and required verification commands. The mock-only Runner writes `preflight.json`, `execution-report.json` (advisory), `run-manifest.json`, `evidence.json`, `review-input.json`, and `runner-result.json` to an external run store. It independently binds the parent, implementation, changed files, verification, contiguous Snapshot trailers, and exact Snapshot SHA. A successful run ends at `REVIEW_READY`; the Runner does not approve, does not merge, and does not start the next task.

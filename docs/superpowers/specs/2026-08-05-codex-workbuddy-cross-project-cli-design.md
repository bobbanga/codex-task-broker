# Codex WorkBuddy Cross-Project CLI Design

## Status

Approved design for implementation planning. This document does not install the CLI, invoke WorkBuddy, merge, push, publish, or reopen the rejected generic WorkBuddy adapter.

## Goal

Provide a stable Python console command that other Git projects can use to run the existing V0.9a mock-only coordination protocol without importing `tests/support` or depending on a repository-relative script path.

The first public command is `codex-workbuddy`. It validates one structured Run Request, invokes one explicitly configured local Contributor, independently recalculates Git and verification facts, writes bound artifacts to an external run store, and stops at `REVIEW_READY`.

## Chosen Approach

Create a normal Python package under `src/bob_skills/codex_workbuddy_coordinator` and register a console script in `pyproject.toml`:

```toml
[project.scripts]
codex-workbuddy = "bob_skills.codex_workbuddy_coordinator.cli:main"
```

This replaces `tests/support` as the cross-project API. Test support may continue to exercise historical contracts, but other projects must use the installed console command or the formal package API.

Rejected alternatives:

- a Skill-local repository script, because it couples consumers to a checkout path;
- a console wrapper around `tests/support`, because test helpers are not a stable production interface.

## Commands

The first release exposes exactly two subcommands:

```powershell
codex-workbuddy validate <run-request.json>
codex-workbuddy run <run-request.json>
```

Both commands print one structured JSON result to stdout. Human diagnostics go to stderr. `run` repeats all validation performed by `validate`; prior validation is never trusted as authorization.

## Run Request

Run Request JSON is the only editable input owner. The strict schema is:

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

Unknown or missing fields are rejected. `mode` must equal `mock_only`. Paths are explicit and must not be inferred from chat, cwd, environment, project metadata, or model defaults.

## Package Boundaries

```text
src/bob_skills/
├── __init__.py
└── codex_workbuddy_coordinator/
    ├── __init__.py
    ├── cli.py
    ├── request.py
    ├── profile.py
    ├── artifacts.py
    └── runner.py
```

- `request.py`: strict Run Request parsing, type checks, immutable values, Git/path boundaries, and Work Order/Briefing binding.
- `profile.py`: immutable command profile and canonical/exact-byte SHA-256 behavior.
- `artifacts.py`: Evidence Manifest and Runner Result writers/readers with exact artifact-byte drift detection.
- `runner.py`: preflight, one Contributor invocation, Git/verification recalculation, artifact writing, and terminal state mapping.
- `cli.py`: argument parsing, JSON stdout, stderr diagnostics, and stable exit codes.

No package module imports from `tests`.

## Execution Flow

1. Parse the Run Request as strict JSON.
2. Validate schema, paths, Git repository, clean workspace, Base SHA, Briefing hash, Work Order binding, allowed/forbidden files, and external run-store boundary.
3. Render and persist one fixed command profile.
4. Start exactly one Contributor with an argv array and `shell=false`.
5. Recalculate parent SHA, implementation/Snapshot SHA, changed files, contiguous commit trailers, workspace status, and required verification results.
6. Run each verification command as an argv array with `shell=false`.
7. Write runtime artifacts outside the project checkout.
8. Bind Manifest and Result to exact artifact bytes.
9. Return a terminal state and exit. There is no Review, retry, merge, or next-task transition.

## Artifacts

The external run store contains:

- `preflight.json`;
- `command-profile.json`;
- Contributor stdout/stderr logs;
- verification stdout/stderr logs;
- `execution-report.json`, advisory only;
- `evidence.json`;
- `run-manifest.json`;
- `review-input.json`;
- `runner-result.json`.

Contributor claims never replace coordinator-calculated Git, Snapshot, workspace, or verification facts.

## Security Boundaries

- The run store must be outside the target project checkout.
- The worktree must be a Git repository, clean before dispatch, and at the exact Base SHA.
- Contributor and verification commands use argv arrays and `shell=false`.
- `allowed_external_effects` remains empty.
- Secret-shaped environment names are rejected from the allowlist.
- Task network, credentials, Git remote writes, push, merge, deploy, install, publication, and external writes are not requestable fields.
- Missing, malformed, unknown, inconsistent, or drifted artifacts fail closed.
- `REVIEW_READY` is a handoff, not approval.

The CLI is not an OS sandbox. Its admission contract permits only explicitly approved local mock Contributors. It must not claim to contain a hostile executable.

## Terminal States and Exit Codes

| Exit | State | Meaning |
|---:|---|---|
| 0 | `REVIEW_READY` | Evidence is complete and awaits Maintainer review. |
| 2 | `PREFLIGHT_FAILED` | Request, path, Git, or binding validation failed. |
| 3 | `CONTRIBUTOR_STOPPED` | Contributor failed, timed out, or could not start. |
| 4 | `EVIDENCE_FAILED` | Scope, Snapshot, workspace, artifact, or verification evidence failed. |
| 5 | `INTERNAL_ERROR` | An unexpected coordinator error occurred. |

The CLI must still emit structured JSON for every handled terminal result.

## WorkBuddy Implementation Boundary

WorkBuddy may implement this feature only as a Bob-approved `project_prototype` Contributor for this repository. It does not run through the new CLI and does not become a supported CLI mode.

The implementation Work Order must bind one Base SHA, one Attempt, allowed files, forbidden files, acceptance criteria, verification commands, external-effect boundary, explicit WorkBuddy command profile/model, and required Snapshot trailers. WorkBuddy runs in an isolated worktree or disposable clone. Codex independently recalculates the diff, ancestry, tests, workspace state, and artifact evidence before accepting any change.

A successful implementation run proves only that WorkBuddy contributed to this repository task. It does not change `GENERIC_WORKBUDDY_CLI_ADAPTER_REJECTED` and does not certify WorkBuddy for arbitrary projects.

## Testing

Create four test modules:

- `tests/test_codex_workbuddy_cli_request.py`: schema, type, path, Git, and permission rejection.
- `tests/test_codex_workbuddy_cli_artifacts.py`: exact-byte hashes, strict readers, and drift rejection.
- `tests/test_codex_workbuddy_cli_runner.py`: disposable Git repository, one invocation, scope/trailer/workspace/verification failures, and `REVIEW_READY` stop.
- `tests/test_codex_workbuddy_cli_entrypoint.py`: temporary virtual-environment installation, `--help`, `validate`, `run`, JSON stdout, stderr, and exit-code mapping.

The full verification gate is:

```powershell
py -3 -m pytest -q
git diff --check
```

Installation smoke tests use a disposable virtual environment. They do not install into Bob's global environment.

## Acceptance Criteria

1. A disposable installation exposes `codex-workbuddy --help`.
2. `validate` accepts one valid request and rejects unknown, missing, malformed, or overbroad requests.
3. `run` completes one mock Contributor pass in a disposable Git repository.
4. The external run store contains the documented artifacts and no runtime artifact enters the target commit.
5. Git, Snapshot, changed files, workspace, and verification facts are independently recalculated.
6. Artifact drift is rejected by machine readers.
7. Contributor and verification commands use argv arrays with `shell=false`.
8. Exit codes map exactly to terminal states.
9. No real WorkBuddy invocation exists in the CLI.
10. Full repository tests and `git diff --check` pass.
11. Codex independently verifies that the WorkBuddy implementation changed only allowed files.
12. Completion stops at the global installation and integration approval gate.

## Non-Goals

- real WorkBuddy adapter or `project_prototype` CLI mode;
- GUI, scheduler, queue, multiple tasks, concurrency, or automatic retry;
- automatic Review, approval, merge, push, PR, deploy, or publication;
- Windows process-level sandboxing;
- Cargo or any business-project changes;
- global installation during implementation.

## Release Gate

Implementation approval is not installation approval. After Codex review and full verification, Bob must separately approve integration into `main` and installation of the console command. Only after that gate may other projects be told that the CLI is available for `mock_only` use.

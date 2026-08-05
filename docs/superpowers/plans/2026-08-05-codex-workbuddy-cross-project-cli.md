# Codex WorkBuddy Cross-Project CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable `codex-workbuddy` console command that other Git projects can use for one bounded `mock_only` coordination run.

**Architecture:** Promote the verified Stage 1c protocol from `tests/support` into a formal `src/bob_skills/codex_workbuddy_coordinator` package. Keep strict request parsing, profile validation, artifact binding, one-shot execution, and CLI concerns in separate modules. WorkBuddy implements each Work Order in an isolated worktree; Codex independently reviews the diff, ancestry, tests, workspace, and artifacts before accepting it.

**Tech Stack:** Python 3.11+, setuptools, standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `pathlib`, `subprocess`), pytest.

## Global Constraints

- The public CLI supports only `mode="mock_only"`.
- Contributor and verification commands use argv arrays with `shell=false`.
- Runtime artifacts live outside the target project checkout.
- Unknown request or artifact fields fail closed.
- No package module imports from `tests`.
- No real WorkBuddy invocation is exposed by the new CLI.
- No global installation, push, merge, deploy, publication, task network, credentials, or external writes.
- WorkBuddy implementation uses a project-specific isolated worktree, model `hy3`, one task per Work Order, and no subagents.

---

### Task 1: Formal request, profile, and artifact package

**Files:**
- Create: `src/bob_skills/__init__.py`
- Create: `src/bob_skills/codex_workbuddy_coordinator/__init__.py`
- Create: `src/bob_skills/codex_workbuddy_coordinator/request.py`
- Create: `src/bob_skills/codex_workbuddy_coordinator/profile.py`
- Create: `src/bob_skills/codex_workbuddy_coordinator/artifacts.py`
- Create: `tests/test_codex_workbuddy_cli_request.py`
- Create: `tests/test_codex_workbuddy_cli_artifacts.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `RunRequest.from_path(path: Path) -> RunRequest`
- Produces: `CommandProfile.from_request(request: RunRequest) -> CommandProfile`
- Produces: `CommandProfile.write(path: Path) -> None`
- Produces: `build_manifest(evidence_path: Path, facts: dict) -> dict`
- Produces: `read_manifest(manifest_path: Path, evidence_path: Path) -> dict`
- Produces: `build_result(manifest_path: Path, evidence_path: Path, state: str, errors: list[str]) -> dict`
- Produces: `read_result(result_path: Path, manifest_path: Path, evidence_path: Path) -> dict`

- [ ] **Step 1: Write failing request tests**

Create tests for the exact request in the approved design and rejection of unknown fields, `mode != mock_only`, boolean integer fields, string verification commands, run store inside worktree, forbidden/allowed overlap, secret-shaped environment allow entries, malformed Base SHA, and malformed Briefing SHA-256.

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m pytest tests/test_codex_workbuddy_cli_request.py -q
```

Expected: import failure because the formal package does not exist.

- [ ] **Step 3: Implement immutable request/profile types**

Use frozen dataclasses and strict top-level/contributor key sets. Resolve paths without inferring defaults. Preserve argv arrays as tuples and require a positive integer timeout where `bool` is invalid.

- [ ] **Step 4: Write failing artifact tests**

Test exact-file-byte SHA-256 binding, missing and unknown fields, malformed JSON, Manifest/Evidence drift, Result/Manifest drift, and `codebuddy_invoked != false`.

- [ ] **Step 5: Implement strict artifact writers/readers**

Use raw `Path.read_bytes()` for artifact hashes and deterministic JSON writes for generated artifacts. Readers recompute hashes every time.

- [ ] **Step 6: Verify Task 1**

```powershell
py -3 -m pytest tests/test_codex_workbuddy_cli_request.py tests/test_codex_workbuddy_cli_artifacts.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit with required trailers**

Commit only Task 1 files and include the Work Order trailers.

### Task 2: One-shot Runner and CLI commands

**Files:**
- Create: `src/bob_skills/codex_workbuddy_coordinator/runner.py`
- Create: `src/bob_skills/codex_workbuddy_coordinator/cli.py`
- Create: `tests/test_codex_workbuddy_cli_runner.py`
- Create: `tests/test_codex_workbuddy_cli_entrypoint.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Task 1 `RunRequest`, `CommandProfile`, artifact builders/readers.
- Produces: `validate_request(request: RunRequest) -> ValidationResult`
- Produces: `run_once(request: RunRequest) -> RunnerResult`
- Produces: `main(argv: list[str] | None = None) -> int`
- Produces console script: `codex-workbuddy`

- [ ] **Step 1: Write failing disposable-Git Runner tests**

Cover clean Base acceptance, dirty preflight, wrong Base, one mock Contributor commit, parent mismatch, no Snapshot, out-of-scope file, missing/mismatched trailers, verification nonzero/timeout, post-run dirty workspace, and `REVIEW_READY` stop.

- [ ] **Step 2: Verify Runner RED**

```powershell
py -3 -m pytest tests/test_codex_workbuddy_cli_runner.py -q
```

Expected: import or missing-function failure.

- [ ] **Step 3: Implement the one-shot Runner**

Repeat validation inside `run_once`, persist preflight/profile/log/report/evidence/manifest/review/result artifacts externally, invoke Contributor exactly once with `[executable, *argv]`, run every verification argv with `shell=false`, and independently recalculate Git facts.

- [ ] **Step 4: Write failing CLI tests**

Cover `--help`, `validate`, `run`, one JSON stdout object, stderr diagnostics, and exit mappings `0/2/3/4/5`.

- [ ] **Step 5: Implement `argparse` CLI and console entry point**

Register `codex-workbuddy = "bob_skills.codex_workbuddy_coordinator.cli:main"` in `pyproject.toml`. Catch expected validation/execution failures and preserve structured output.

- [ ] **Step 6: Verify Task 2**

```powershell
py -3 -m pytest tests/test_codex_workbuddy_cli_runner.py tests/test_codex_workbuddy_cli_entrypoint.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit with required trailers**

Commit only Task 2 files and include the Work Order trailers.

### Task 3: Disposable installation, documentation, and release gate

**Files:**
- Modify: `tests/test_codex_workbuddy_cli_entrypoint.py`
- Modify: `skills/codex-workbuddy-coordinator/SKILL.md`
- Modify: `skills/codex-workbuddy-coordinator/references/schemas.md`
- Modify: `README.md`
- Modify: `docs/project-status.md`

**Interfaces:**
- Consumes: installed console command from Tasks 1–2.
- Produces: documented cross-project `mock_only` workflow and verified disposable installation evidence.

- [ ] **Step 1: Add a failing disposable-venv smoke test**

Build/install the local project into a temporary virtual environment, invoke its `codex-workbuddy --help`, then run `validate` against a disposable request. Do not touch Bob's global Python environment.

- [ ] **Step 2: Verify smoke-test RED**

```powershell
py -3 -m pytest tests/test_codex_workbuddy_cli_entrypoint.py -k disposable_install -q
```

Expected: failure until packaging includes the `src` package and console script correctly.

- [ ] **Step 3: Make the minimum packaging correction**

Configure setuptools package discovery under `src` only if the smoke test proves it is missing. Do not add a new dependency.

- [ ] **Step 4: Document exact use and boundaries**

Add the two commands, request-file ownership, external run-store rule, exit codes, mock-only boundary, installation gate, and the statement that WorkBuddy implementation evidence does not certify a real adapter.

- [ ] **Step 5: Run the complete verification gate**

```powershell
py -3 -m pytest -q
git diff --check
git status --short
```

Expected: all repository tests pass, diff check is clean, and only Task 3 files are uncommitted.

- [ ] **Step 6: Commit with required trailers and stop**

Commit Task 3, write the external Execution Report, verify a clean implementation worktree, and stop at Codex review. Do not install globally or start another task.

## Codex Review Gate

For every WorkBuddy task, Codex must independently verify:

1. Base SHA is the ancestor of the implementation SHA.
2. `base..implementation` changes only allowed files.
3. Required trailers are contiguous and match the Work Order.
4. Targeted and full tests pass under Codex control.
5. `git diff --check` passes and the implementation worktree is clean.
6. No network/credential/external-write/install/push/merge/deploy evidence exists outside the approved model transport.
7. Runtime artifacts remain in the external run store.
8. The new CLI contains no path that invokes real WorkBuddy.

Any failure returns `CHANGES_REQUESTED`, `REPLAN_REQUIRED`, or `ESCALATED`; Codex never approves based only on WorkBuddy's report.

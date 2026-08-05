# Codex Task Broker MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the public project to Codex Task Broker and deliver a Windows-first, natural-language Codex workflow that runs one bounded task through a locally installed WorkBuddy CLI and returns independently verified evidence.

**Architecture:** Keep the deterministic request, artifact, and Git verification core, but rename it into a product-owned Python namespace. Add a WorkBuddy adapter behind a generic executor contract, a readiness doctor, automatic isolated-worktree orchestration, and a thin Codex Skill. The real WorkBuddy canary remains a separate approval gate after fake integration and packaging pass.

**Tech Stack:** Python 3.11+, standard library, setuptools, pytest, JSON Schema, Git, GitHub Actions, WorkBuddy CLI 2.115.0 development baseline, Node.js 24.15.0 development baseline.

## Global Constraints

- Public product name: **Codex Task Broker**; Chinese name: **Codex 任务管家**.
- Repository and distribution: `codex-task-broker`; command: `codex-broker`; Python package: `codex_task_broker`; Skill: `codex-task-broker`.
- Initial platform: Windows only; initial and only MVP executor: WorkBuddy CLI.
- Do not implement cost accounting, model routing, other adapters, GUI automation, parallel execution, or macOS/Linux support.
- Never use `bypassPermissions` or `dangerously-skip-permissions`.
- WorkBuddy launches use argv with `shell=False`, a filtered environment, a bounded timeout, one invocation, no session persistence, strict empty MCP configuration, and no plugins, channels, remote control, background mode, swarm, or IDE connection.
- WorkBuddy model transport may use its authenticated network. Do not claim OS-level sandboxing or general network denial.
- Never merge, push, publish, deploy, or modify remotes from the runtime CLI.
- A real WorkBuddy canary requires a new exact-run approval after fake integration tests pass.
- PyPI publication remains deferred to GitHub issue #1 and final approval.
- No subagents may be used unless Bob separately authorizes their maximum number and responsibilities for the implementation turn.

## Target File Structure

```text
src/codex_task_broker/
  __init__.py              # package version and public exports
  artifacts.py             # strict evidence readers/writers
  request.py               # machine request validation
  runner.py                # post-run Git and verification evidence
  worktree.py              # isolated worktree lifecycle
  broker.py                # one-run orchestration
  cli.py                   # doctor/run/validate command surface
  executors/
    __init__.py            # ExecutorAdapter protocol
    workbuddy.py           # WorkBuddy discovery, capability probe, argv, parse
skills/codex-task-broker/
  SKILL.md                 # natural-language Codex front door
schemas/
  run-request.schema.json  # public machine contract
examples/
  minimal-run-request.json # advanced-user example
tests/
  fakes/fake_workbuddy.py
  test_*.py
```

---

### Task 1: Rename the Public Identity and Runtime Namespace

**Files:**
- Modify: `pyproject.toml`
- Move: `src/bob_skills/codex_workbuddy_coordinator/*.py` to `src/codex_task_broker/*.py`
- Move/Modify: `tests/test_codex_workbuddy_cli_*.py` to `tests/test_codex_broker_*.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/protocol.md`
- Modify: `docs/project-status.md`

**Interfaces:**
- Consumes: existing `RunRequest`, `RunnerResult`, `run_once`, and CLI behavior.
- Produces: import namespace `codex_task_broker`, distribution `codex-task-broker`, command `codex-broker`, and schema id `codex-task-broker-run-request`.

- [ ] **Step 1: Rename tests first and make identity assertions fail**

Rename the four CLI test modules and replace their imports with `codex_task_broker`. Add these assertions to `tests/test_codex_broker_entrypoint.py`:

```python
def test_public_identity_is_codex_task_broker() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "codex-task-broker"
    assert data["project"]["scripts"] == {
        "codex-broker": "codex_task_broker.cli:main"
    }
    assert "codex-workbuddy" not in data["project"]["scripts"]


def test_old_runtime_namespace_is_absent() -> None:
    assert not (REPO_ROOT / "src" / "bob_skills").exists()
```

- [ ] **Step 2: Run the renamed identity tests and observe RED**

Run:

```powershell
py -3 -m pytest tests/test_codex_broker_entrypoint.py -k "public_identity or old_runtime_namespace" -q
```

Expected: failures showing the old distribution, script, and namespace.

- [ ] **Step 3: Move the package and update machine identity**

Move the package without changing behavior. Set `pyproject.toml` to:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "codex-task-broker"
version = "0.1.0"
description = "Let Codex delegate one bounded coding task and verify the result"
readme = "README.md"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["build>=1.2", "pytest>=8.3", "ruff>=0.12"]

[project.scripts]
codex-broker = "codex_task_broker.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"

[tool.ruff]
target-version = "py311"
line-length = 100
```

Replace public schema strings and CLI result schema names with the
`codex-task-broker-*` prefix. Do not retain old aliases because no PyPI release
exists.

- [ ] **Step 4: Update public docs and status to the approved identity**

Use “Codex Task Broker / Codex 任务管家” in user-facing copy. Remove claims that
the project itself is WorkBuddy-specific; state that WorkBuddy is the only MVP
adapter. Replace old install and command examples with `codex-task-broker` and
`codex-broker`.

- [ ] **Step 5: Run renamed tests and the full suite**

Run:

```powershell
py -3 -m pytest -q
py -3 -m ruff check src tests
git diff --check
```

Expected: 117 or more tests pass; Ruff and diff check pass; no tracked path
under `src/bob_skills` remains.

- [ ] **Step 6: Commit the runtime rename**

```powershell
git add -A
git commit -m "refactor: rename runtime to Codex Task Broker"
```

---

### Task 2: Establish the Public Open-Source Surface

**Files:**
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CHANGELOG.md`
- Create: `ROADMAP.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/pull_request_template.md`
- Create: `.github/workflows/ci.yml`
- Create: `schemas/run-request.schema.json`
- Create: `examples/minimal-run-request.json`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `README.en.md`
- Remove from public product docs: internal/local governance records not needed by users.

**Interfaces:**
- Consumes: Task 1 package and schema identity.
- Produces: installable MIT-licensed package metadata, public contribution/security docs, machine schema, example request, and Windows-first CI.

- [ ] **Step 1: Add failing public-surface contract tests**

Create `tests/test_public_project_surface.py`:

```python
from pathlib import Path
import json
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_required_public_files_exist() -> None:
    for name in (
        "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
        "CHANGELOG.md", "ROADMAP.md", "README.md", "README.en.md",
    ):
        assert (ROOT / name).is_file(), name


def test_package_metadata_is_complete() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["license"] == "MIT"
    assert project["authors"]
    assert project["urls"]["Repository"].endswith("/codex-task-broker")
    assert project["classifiers"]


def test_example_conforms_to_public_schema_identity() -> None:
    schema = json.loads((ROOT / "schemas/run-request.schema.json").read_text("utf-8"))
    example = json.loads((ROOT / "examples/minimal-run-request.json").read_text("utf-8"))
    assert schema["$id"].endswith("run-request.schema.json")
    assert example["schema"] == "codex-task-broker-run-request"
```

- [ ] **Step 2: Run the public-surface tests and observe RED**

```powershell
py -3 -m pytest tests/test_public_project_surface.py -q
```

Expected: missing files and metadata failures.

- [ ] **Step 3: Add MIT and complete package metadata**

Use the standard MIT license text with copyright `2026 Bob Zhang`. Add:

```toml
license = "MIT"
authors = [{name = "Bob Zhang"}]
keywords = ["codex", "workbuddy", "coding-agent", "delegation", "git"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Environment :: Console",
  "License :: OSI Approved :: MIT License",
  "Operating System :: Microsoft :: Windows",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Topic :: Software Development :: Version Control :: Git",
]

[project.urls]
Homepage = "https://github.com/bobbanga/codex-task-broker"
Repository = "https://github.com/bobbanga/codex-task-broker"
Issues = "https://github.com/bobbanga/codex-task-broker/issues"
Changelog = "https://github.com/bobbanga/codex-task-broker/blob/main/CHANGELOG.md"
```

- [ ] **Step 4: Add concise public governance documents**

`SECURITY.md` must instruct users to report vulnerabilities privately through
GitHub Security Advisories and must not list a personal email. `ROADMAP.md`
contains exactly three horizons: WorkBuddy MVP, additional executor adapters,
and optional policy/cost routing. State that roadmap items are not promises.

- [ ] **Step 5: Add schema, example, and CI**

Generate a strict Draft 2020-12 JSON Schema matching `RunRequest`. The example
uses placeholder absolute Windows paths and `mode: "mock_only"`; it must not
contain credentials or a real local user path.

Create `.github/workflows/ci.yml` with Windows jobs for Python 3.11 and 3.12:

```yaml
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: windows-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -e ".[dev]"
      - run: python -m ruff check src tests
      - run: python -m pytest
      - if: matrix.python-version == '3.12'
        run: |
          python -m build
          python -m pip install --force-reinstall --no-deps (Get-ChildItem dist\*.whl)
          codex-broker --help
```

- [ ] **Step 6: Verify and commit the public surface**

```powershell
py -3 -m pytest -q
py -3 -m ruff check src tests
py -3 -m build
git diff --check
git add -A
git commit -m "docs: establish public project surface"
```

Expected: tests and build pass; wheel contains `codex_task_broker`; no internal
absolute path or Bob-only approval language appears in public user docs.

---

### Task 3: Add WorkBuddy Discovery and `doctor`

**Files:**
- Create: `src/codex_task_broker/executors/__init__.py`
- Create: `src/codex_task_broker/executors/workbuddy.py`
- Modify: `src/codex_task_broker/cli.py`
- Create: `tests/test_workbuddy_discovery.py`
- Create: `tests/test_doctor_command.py`

**Interfaces:**
- Produces: `ExecutorAdapter` protocol, `WorkBuddyInstallation`, `WorkBuddyCapabilities`, `discover_workbuddy()`, `probe_workbuddy()`, and `codex-broker doctor`.
- Consumes: Windows environment, PATH lookup, standard Desktop path, subprocess runner injection for tests.

- [ ] **Step 1: Define tests for discovery precedence and capability failure**

```python
def test_explicit_path_wins_over_path_and_desktop(tmp_path, monkeypatch):
    explicit = make_cli(tmp_path / "explicit" / "codebuddy")
    on_path = make_cli(tmp_path / "path" / "codebuddy")
    monkeypatch.setenv("CODEX_BROKER_WORKBUDDY_CLI", str(explicit))
    monkeypatch.setattr(shutil, "which", lambda _: str(on_path))
    result = discover_workbuddy()
    assert result.cli_path == explicit.resolve()
    assert result.source == "explicit"


def test_probe_fails_closed_when_required_flag_is_missing(fake_installation):
    help_text = "Usage: codebuddy -p --output-format --max-turns"
    result = probe_workbuddy(fake_installation, run=fake_run(stdout=help_text))
    assert result.ready is False
    assert "--no-session-persistence" in result.missing_capabilities
```

- [ ] **Step 2: Run discovery tests and observe RED**

```powershell
py -3 -m pytest tests/test_workbuddy_discovery.py -q
```

Expected: import or symbol failures.

- [ ] **Step 3: Implement the generic adapter protocol and WorkBuddy records**

```python
class ExecutorAdapter(Protocol):
    name: str
    def doctor(self) -> "DoctorResult": ...
    def build_command(self, request: "ExecutionRequest") -> tuple[str, ...]: ...
    def parse_result(self, stdout: str, stderr: str, exit_code: int) -> "ExecutorResult": ...


@dataclass(frozen=True)
class WorkBuddyInstallation:
    cli_path: Path
    node_path: Path | None
    source: Literal["explicit", "path", "desktop"]
    cli_sha256: str
    node_sha256: str | None
```

Required flags are `-p`, `--output-format`, `--permission-mode`, `--tools`,
`--mcp-config`, `--strict-mcp-config`, `--no-session-persistence`, `--model`,
`--effort`, `--max-turns`, and `--add-dir`.

- [ ] **Step 4: Add a structured doctor CLI result**

`codex-broker doctor --executor workbuddy --json` prints one JSON object with
`ready`, versions, sources, hashes, capabilities, and non-secret remediation.
Human mode prints a short checklist. Doctor never sends a model request.

- [ ] **Step 5: Test against fake and local discovery without launching a task**

```powershell
py -3 -m pytest tests/test_workbuddy_discovery.py tests/test_doctor_command.py -q
codex-broker doctor --executor workbuddy --json
```

Expected locally: WorkBuddy `2.115.0`, Node `24.15.0`, `ready: true`, and all
required flags present. This is a capability probe, not a real task run.

- [ ] **Step 6: Commit doctor support**

```powershell
git add src/codex_task_broker/executors tests/test_workbuddy_discovery.py tests/test_doctor_command.py src/codex_task_broker/cli.py
git commit -m "feat: detect and diagnose WorkBuddy"
```

---

### Task 4: Implement the Bounded WorkBuddy Adapter with a Fake Executor

**Files:**
- Modify: `src/codex_task_broker/executors/workbuddy.py`
- Create: `tests/fakes/fake_workbuddy.py`
- Create: `tests/test_workbuddy_adapter.py`
- Modify: `src/codex_task_broker/artifacts.py`

**Interfaces:**
- Consumes: `WorkBuddyInstallation`, bounded execution request, task brief path, worktree path, run-store path.
- Produces: deterministic command profile and `ExecutorResult`; writes raw process artifacts but no review decision.

- [ ] **Step 1: Add exact argv and forbidden-flag tests**

```python
def test_workbuddy_command_is_bounded(request, installation):
    argv = WorkBuddyAdapter(installation).build_command(request)
    assert argv[:3] == (str(installation.node_path), str(installation.cli_path), "-p")
    assert "--output-format" in argv and "json" in argv
    assert "--no-session-persistence" in argv
    assert "--strict-mcp-config" in argv
    assert "--max-turns" in argv
    assert "--dangerously-skip-permissions" not in argv
    assert "bypassPermissions" not in argv
    assert "--ide" not in argv and "--bg" not in argv and "--swarm" not in argv
```

- [ ] **Step 2: Add fake WorkBuddy terminal scenarios**

`tests/fakes/fake_workbuddy.py` accepts the same required flags and selects a
scenario through `FAKE_WORKBUDDY_SCENARIO`: `success`, `malformed_json`,
`nonzero`, `timeout`, or `permission_required`. The success result is JSON and
edits only the configured fixture file. It never uses network.

- [ ] **Step 3: Observe RED before adapter implementation**

```powershell
py -3 -m pytest tests/test_workbuddy_adapter.py -q
```

Expected: missing adapter behavior and scenario parsing failures.

- [ ] **Step 4: Implement the minimum launch and parse path**

Use `subprocess.run(argv, cwd=worktree, env=filtered_env, shell=False,
capture_output=True, text=True, timeout=timeout, check=False)`. Write stdout and
stderr before parsing. Parse only a top-level JSON object; malformed data maps
to `EXECUTOR_OUTPUT_INVALID`, timeout to `EXECUTOR_TIMEOUT`, permission output
to `EXECUTOR_PERMISSION_REQUIRED`, and non-zero exit to `EXECUTOR_FAILED`.

The initial permission mode and tool set remain constants in one profile
object. Their final values must be chosen by fake tests plus a separately
approved real canary; they must never be permission bypass values.

- [ ] **Step 5: Verify all fake terminal states**

```powershell
py -3 -m pytest tests/test_workbuddy_adapter.py -q
py -3 -m pytest -q
git diff --check
```

Expected: all fake scenarios pass and no model request occurs.

- [ ] **Step 6: Commit the adapter**

```powershell
git add src/codex_task_broker/executors/workbuddy.py src/codex_task_broker/artifacts.py tests/fakes tests/test_workbuddy_adapter.py
git commit -m "feat: add bounded WorkBuddy adapter"
```

---

### Task 5: Add Automatic Worktree Orchestration and the Codex Skill

**Files:**
- Create: `src/codex_task_broker/worktree.py`
- Create: `src/codex_task_broker/broker.py`
- Modify: `src/codex_task_broker/cli.py`
- Create: `skills/codex-task-broker/SKILL.md`
- Create: `skills/codex-task-broker/references/request-contract.md`
- Create: `tests/test_worktree_manager.py`
- Create: `tests/test_broker_workflow.py`
- Create: `tests/test_skill_contract.py`

**Interfaces:**
- Consumes: source repository, base ref, task brief, allowed paths, verification argv, WorkBuddy adapter.
- Produces: `BrokerRunResult`, isolated worktree, external run store, Codex review handoff, and natural-language Skill instructions.

- [ ] **Step 1: Add disposable-repository worktree tests**

```python
def test_create_isolated_worktree_binds_base_and_stays_outside_source(repo, tmp_path):
    manager = WorktreeManager(run_root=tmp_path / "runs")
    created = manager.create(repo, base_ref="HEAD", task_id="demo-001")
    assert created.path != repo
    assert not created.path.is_relative_to(repo)
    assert git(created.path, "rev-parse", "HEAD") == created.base_sha
```

Cover invalid Git repo, dirty source checkout, duplicate task id, failed
creation, and preserved worktree on execution failure.

- [ ] **Step 2: Add a complete fake WorkBuddy broker test**

```python
def test_broker_reaches_review_ready_with_fake_workbuddy(repo, broker_request):
    result = Broker(workbuddy=fake_success_adapter()).run(broker_request)
    assert result.state == "REVIEW_READY"
    assert result.worktree_path.exists()
    assert result.run_store_path.exists()
    assert result.changed_files == ("src/example.py",)
    assert result.verification_results[0].exit_code == 0
```

- [ ] **Step 3: Observe RED**

```powershell
py -3 -m pytest tests/test_worktree_manager.py tests/test_broker_workflow.py -q
```

- [ ] **Step 4: Implement one-run orchestration**

`Broker.run()` performs, in order: validate source, bind base, create run store,
create worktree, freeze request/profile, invoke exactly one adapter, recalculate
Git evidence, run verification argv, write result, and stop. It never removes a
failed worktree automatically; the result includes a reviewed cleanup command.

Expose:

```powershell
codex-broker run --repo <path> --brief <brief.json> --executor workbuddy --json
```

The Skill generates `brief.json`; normal users do not.

- [ ] **Step 5: Write the thin natural-language Skill**

The Skill must:

- trigger only when the user explicitly asks Codex to delegate implementation;
- keep planning and final review with Codex;
- run `doctor` before the first task or after WorkBuddy changes;
- summarize scope and request approval only for real permission expansion;
- never expose JSON construction unless diagnostics are needed;
- never call WorkBuddy directly outside the broker;
- stop at Codex review and never auto-merge or push.

Its reference file documents the exact brief fields without copying runner or
adapter implementation.

- [ ] **Step 6: Verify broker and Skill contracts**

```powershell
py -3 -m pytest tests/test_worktree_manager.py tests/test_broker_workflow.py tests/test_skill_contract.py -q
py -3 -m pytest -q
git diff --check
```

- [ ] **Step 7: Commit the workflow**

```powershell
git add src/codex_task_broker/worktree.py src/codex_task_broker/broker.py src/codex_task_broker/cli.py skills tests
git commit -m "feat: add novice WorkBuddy delegation workflow"
```

---

### Task 6: Rename Local and Remote Repositories and Migrate Installation

**Files:**
- Modify references in: `README.md`, `README.en.md`, `docs/project-status.md`, `ROADMAP.md`, `.github/*`, `pyproject.toml`
- Modify external index: `D:\Code\PROJECTS.md`
- Modify Skill owner records in: `D:\Code\work\bob-skills`
- Rename local directory: `D:\Code\work\codex-workbuddy-coordinator` to `D:\Code\work\codex-task-broker`
- Rename GitHub repository: `bobbanga/codex-workbuddy-coordinator` to `bobbanga/codex-task-broker`

**Interfaces:**
- Consumes: Tasks 1-5 passing package.
- Produces: final local/remote identity, installed `codex-broker`, updated indexes, and no old console command.

- [ ] **Step 1: Scan current references and verify clean state**

```powershell
git status --short
rg -n "codex-workbuddy-coordinator|codex-workbuddy|bob_skills.codex_workbuddy" .
gh repo view bobbanga/codex-workbuddy-coordinator --json nameWithOwner,visibility,url
```

Expected: clean worktree; remaining old names are only explicitly identified
migration history or files scheduled in this task.

- [ ] **Step 2: Rename the GitHub repository and local directory**

```powershell
gh repo rename codex-task-broker --repo bobbanga/codex-workbuddy-coordinator --yes
git remote set-url origin https://github.com/bobbanga/codex-task-broker.git
```

From `D:\Code\work`, rename the verified clean repository directory with native
PowerShell `Move-Item -LiteralPath` after resolving both source and destination.
Do not move any worktree or unrelated project.

- [ ] **Step 3: Update external ownership records**

Change `D:\Code\PROJECTS.md` and the thin `bob-skills` Skill/status records to
the new local path, GitHub repository, product name, command, and ownership.
Historical Git commit ids and clearly marked historical names remain unchanged.

- [ ] **Step 4: Replace the installed package**

```powershell
py -3 -m pip uninstall -y codex-workbuddy-coordinator
py -3 -m pip install --user --no-build-isolation --no-deps D:\Code\work\codex-task-broker
codex-broker --help
```

Verify `Get-Command codex-workbuddy -ErrorAction SilentlyContinue` returns
nothing and `pip show codex-task-broker` reports version `0.1.0`.

- [ ] **Step 5: Run final local and remote checks**

```powershell
py -3 -m pytest -q
py -3 -m ruff check src tests
py -3 -m build
git diff --check
git status --short
gh repo view bobbanga/codex-task-broker --json nameWithOwner,visibility,url,defaultBranchRef
```

Expected: tests, lint, and build pass; worktree clean; GitHub is public with
`main`; local `main` tracks the renamed origin.

- [ ] **Step 6: Commit records and push the renamed repository**

```powershell
git add -A
git commit -m "chore: complete Codex Task Broker migration"
git push origin main
```

Do not publish to PyPI.

---

### Task 7: Prepare the Exact Real WorkBuddy Canary and Stop

**Files:**
- Create outside Git: `%LOCALAPPDATA%\Temp\codex-task-broker\approval\<id>\canary-request.json`
- Create outside Git: `%LOCALAPPDATA%\Temp\codex-task-broker\approval\<id>\approval-summary.json`
- Modify after approval only: `docs/project-status.md`

**Interfaces:**
- Consumes: installed `codex-broker`, passing fake integration, compatible `doctor` evidence.
- Produces: a hash-bound exact-run approval package; no real WorkBuddy invocation in this task.

- [ ] **Step 1: Create a disposable Git repository with one baseline test**

The repository contains one small Python function and one failing test whose
only permitted solution changes that function. It has no remote and no secrets.

- [ ] **Step 2: Generate and validate the exact canary package**

Bind repository HEAD, WorkBuddy and Node paths/hashes/versions, model, permission
mode, tool set, prompt hash, allowed file, verification argv, timeout, run-store
path, and the statement `real_workbuddy_invoked=false`.

- [ ] **Step 3: Run only preflight and fake-equivalent verification**

```powershell
codex-broker doctor --executor workbuddy --json
codex-broker validate <canary-request.json>
```

Expected: ready/validated without a model request or WorkBuddy task invocation.

- [ ] **Step 4: Stop for Bob's exact-run approval**

Report the approval-summary path and hash, exact command, model, permissions,
network assumption, allowed file, timeout, and cleanup path. Do not run the real
canary until Bob approves that exact package.

## Plan Self-Review

- Spec coverage: rename, public surface, WorkBuddy discovery, bounded adapter,
  natural-language Skill, isolated worktree/evidence, Windows packaging, remote
  migration, and separate canary/PyPI gates are each assigned to a task.
- Scope: one MVP subsystem with one adapter; future IDE/model/cost work remains
  excluded.
- Type consistency: `ExecutorAdapter`, `WorkBuddyInstallation`,
  `WorkBuddyCapabilities`, `WorktreeManager`, `Broker`, and `BrokerRunResult`
  are introduced before consumers.
- Placeholder scan: implementation values that require real compatibility
  evidence are explicitly resolved at the canary gate rather than left as code
  placeholders.

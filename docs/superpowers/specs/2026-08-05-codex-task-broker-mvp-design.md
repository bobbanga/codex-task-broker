# Codex Task Broker MVP Design

**Product name:** Codex Task Broker / Codex 任务管家  
**Public command:** `codex-broker`  
**Initial platform:** Windows  
**Initial executor:** WorkBuddy CLI  
**Status:** Approved design; implementation not started

## Purpose

Codex Task Broker lets a non-technical user ask Codex to delegate one bounded
development task to WorkBuddy and then have Codex independently verify the
result. The user interacts through natural language; the CLI is a deterministic
execution and evidence layer behind the Codex Skill.

The long-term direction is an adapter-based broker for IDE agents and lower-cost
models. The MVP proves only one reliable path: Codex to a locally installed and
authenticated WorkBuddy CLI on Windows.

## User Experience

The normal user says something equivalent to:

> Ask WorkBuddy to implement this task, then review its work.

The Codex Skill creates the task brief, checks the project, calls the broker,
and explains only decisions that need user attention. Users do not write JSON,
locate Node.js, construct WorkBuddy flags, or manage Git worktrees.

The broker returns one of three human-level outcomes:

- ready for Codex review;
- stopped with a concrete failure and preserved evidence;
- blocked because a permission or environment requirement needs user action.

The CLI and machine-readable request remain available for automation,
debugging, and advanced use.

## MVP Scope

The MVP includes:

- a Codex Skill as the primary natural-language entry point;
- `codex-broker doctor` for WorkBuddy and project readiness;
- `codex-broker run` for one bounded WorkBuddy task;
- automatic isolated Git worktree creation and cleanup guidance;
- an external run store for prompts, logs, bindings, and evidence;
- deterministic WorkBuddy command construction;
- Git scope, ancestry, workspace, trailer, and verification checks;
- a Codex review handoff that never self-approves;
- Windows installation and integration tests.

The MVP excludes:

- cost or token accounting;
- automatic model or executor selection;
- adapters other than WorkBuddy;
- GUI or IDE automation;
- parallel task execution;
- automatic merge, push, PR, deployment, or publication;
- macOS and Linux support;
- an executor/plugin marketplace.

## Architecture

```text
User
  -> Codex Skill
  -> Task Brief
  -> Broker Core
       -> Doctor / Capability Probe
       -> Policy Gate
       -> Worktree Manager
       -> WorkBuddy Adapter
       -> Evidence Collector
  -> Codex Review
  -> User Decision
```

### Codex Skill

The Skill translates a natural-language request into a bounded task brief. It
owns user interaction and review orchestration, but does not implement process
launching, Git evidence, or WorkBuddy-specific flags.

### Broker Core

The core validates input, creates the isolated worktree and external run store,
calls one adapter once, and independently recalculates evidence. It does not
trust adapter or executor completion claims.

### Adapter Contract

An adapter declares:

- identity and version;
- supported operating systems;
- executable discovery rules;
- capability probes;
- required authentication and network assumptions;
- deterministic argv construction;
- supported tool and permission controls;
- output parsing and terminal-state mapping;
- cancellation and timeout behavior.

Only the WorkBuddy adapter is implemented in the MVP. The contract must not
contain WorkBuddy-only fields in its core types.

## WorkBuddy Discovery

The adapter discovers WorkBuddy in this order:

1. an explicit broker configuration path;
2. `codebuddy` or `cbc` on `PATH`;
3. the standard WorkBuddy Desktop bundled CLI path on Windows.

It separately discovers Node.js when the selected entry point is a JavaScript
file. `doctor` records but does not expose secrets:

- WorkBuddy version;
- Node.js version;
- executable paths;
- executable SHA-256 hashes;
- required CLI capabilities;
- Git repository readiness;
- authentication readiness when it can be checked without a model call.

The observed development baseline is WorkBuddy CLI `2.115.0` with Node.js
`24.15.0`. Compatibility is capability-based rather than locked to that exact
version. Missing required flags fail closed with an actionable message.

## WorkBuddy Launch Profile

The adapter uses WorkBuddy's non-interactive print mode and structured output.
The final profile must:

- avoid `bypassPermissions` and `dangerously-skip-permissions`;
- use an explicit permission mode proven by integration tests;
- set an explicit model, effort, maximum turns, and timeout;
- disable session persistence;
- use a strict empty MCP configuration;
- omit plugins, channels, remote control, background mode, swarm, and IDE
  connection;
- restrict built-in tools to the minimum proven set;
- use argv execution with `shell=false`;
- use a filtered child environment;
- set the isolated worktree as cwd;
- expose only the minimum external run-store path required for task artifacts.

WorkBuddy needs network access for its authenticated model transport. The MVP
must describe that honestly and must not claim OS-level sandboxing. Task prompts
must prohibit unrelated network access, remote Git operations, publication, and
project-external writes. The broker verifies all locally observable boundaries
after execution.

## Git and Evidence Model

Before launch, the broker binds:

- source repository and base commit;
- isolated worktree path and initial HEAD;
- task brief bytes and hash;
- allowed and forbidden paths;
- verification argv;
- adapter version, executable hashes, and launch profile;
- timeout and stop conditions.

After launch, it records:

- stdout and stderr;
- process exit and timeout facts;
- final HEAD and ancestry;
- changed files and workspace state;
- required commit metadata;
- verification results;
- artifact hashes;
- a terminal result suitable for Codex review.

Runtime evidence is written outside both the source repository and isolated
worktree. Evidence is not committed automatically.

## Failure Handling

The broker stops without widening authority when it encounters:

- missing or incompatible WorkBuddy/Node;
- authentication not ready;
- dirty or drifting Git baseline;
- a permission prompt that cannot be handled safely;
- process start failure, malformed output, timeout, or non-zero exit;
- changed files outside the approved scope;
- missing or invalid commit bindings;
- failed verification;
- incomplete or drifting evidence.

The MVP performs no silent model fallback, automatic privilege escalation, or
unbounded retry. Evidence is preserved for diagnosis and explicit rework.

## Public Rename and Migration

The project is renamed before PyPI publication:

- GitHub repository: `bobbanga/codex-task-broker`;
- local repository: `D:\Code\work\codex-task-broker`;
- distribution: `codex-task-broker`;
- Python package: `codex_task_broker`;
- command: `codex-broker`;
- Skill: `codex-task-broker`;
- Chinese product name: Codex 任务管家.

Because no PyPI release exists, the code and machine schema use the new names
directly rather than carrying permanent aliases. The old GitHub URL may redirect
after the repository rename, but documentation, installation, issue text, local
project indexes, and the installed user package must all move to the new name.

The current `codex-workbuddy` installation is removed and replaced from the
renamed local repository. Migration is complete only when the old console
command is absent and `codex-broker --help` works from a new shell.

## Open-Source Project Surface

The public repository is written for external users and contributors, not as an
internal status notebook. It includes:

- concise Chinese and English READMEs led by the user problem and quick start;
- an MIT license;
- complete package metadata and project URLs;
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md`;
- machine-readable JSON schemas and runnable examples;
- GitHub issue and pull-request templates;
- Windows-first CI for lint, tests, package build, and clean installation;
- a public roadmap that separates MVP, future adapters, and non-goals.

Bob-specific approvals, local absolute paths, historical prototype reports, and
internal implementation plans remain in their owning private/local governance
repository. They are not part of the public product narrative.

## Testing Strategy

### Unit and Contract Tests

- discovery precedence and Windows paths;
- capability parsing and incompatibility failures;
- deterministic argv without shell use;
- environment and permission restrictions;
- request, schema, artifact, and state validation;
- Git scope, ancestry, workspace, and verification behavior;
- structured WorkBuddy output parsing;
- every documented failure state.

### Fake WorkBuddy Integration

A subprocess-compatible fake covers success, malformed JSON, prompt attempts,
non-zero exit, timeout, forbidden writes, missing commit metadata, and failed
verification without consuming model capacity.

### Real Windows Canary

An explicitly approved disposable repository run verifies the installed
WorkBuddy version, the final permission/tool profile, one bounded edit, evidence
collection, cleanup, and Codex review handoff. It must not target a business
repository.

### Packaging and CI

CI tests supported Python versions on Windows, builds wheel and sdist, inspects
their contents, and installs the wheel into a clean environment. PyPI remains a
later release gate tracked separately.

## Acceptance Criteria

The MVP is ready for external trial when:

1. A novice can ask Codex to delegate one task without writing JSON or invoking
   WorkBuddy manually.
2. `doctor` identifies a compatible local WorkBuddy installation or explains
   exactly how to fix readiness.
3. One approved disposable Windows canary reaches Codex review without broad
   permission bypasses.
4. Timeout, permission, scope, Git, output, and verification failures stop
   safely with preserved evidence.
5. The renamed package installs cleanly and exposes only `codex-broker`.
6. Public documentation contains no internal-only claims or local governance
   instructions.
7. The full test, lint, build, and clean-install gates pass in CI and locally.

## Stop Gates

- Remote rename and push require the user's explicit approval; that approval was
  given with this design request.
- A real WorkBuddy canary requires a separate exact-run approval after fake
  integration tests pass.
- PyPI publication remains deferred to its existing release issue and a final
  approval.
- Additional adapters, cost routing, GUI automation, parallelism, and
  macOS/Linux support require later designs.

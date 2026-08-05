# Project Status

Updated: 2026-08-05

## Position

This repository is the canonical source for the cross-project
`codex-broker` CLI. It was extracted from `D:\Code\work\bob-skills` after the
V0.9a Stage 1c protocol. The V0.1.0 mock-only CLI passes its own disposable
virtual-environment install and full-suite verification; `codex-task-broker` is
not installed at the user level. The superseded `codex-workbuddy-coordinator`
0.1.0 user-level installation still exists locally. User-level installation and
remote repository migration are deferred to Task 6.

## Current State

- Product: Codex Task Broker / Codex 任务管家.
- Distribution: `codex-task-broker` 0.1.0.
- Console command: `codex-broker`.
- Installed user-level package: the superseded distribution
  `codex-workbuddy-coordinator` 0.1.0 is still installed at the user level, and
  `codex-task-broker` is not installed. Task 6 replaces that installation.
- Installation and remote repository migration: these happen in Task 6. The
  renamed distribution is not yet installed at the user level and has not been
  verified through a user-level `codex-broker --help`; this Task 1 rename only
  updates the public identity and runtime namespace.
- Runtime mode: `mock_only` only. The current CLI remains mock-only and does
  not implement the real WorkBuddy adapter.
- Public stop states: `VALIDATED` for validation and `REVIEW_READY` for a
  successful bounded run.
- Real WorkBuddy adapter: WorkBuddy is the only MVP executor adapter; it was
  rejected under the previously observed generic CLI startup surface and is
  not implemented here.
- Remote repository: public GitHub repository
  `bobbanga/codex-workbuddy-coordinator`; local `main` tracks `origin/main`.
  The rename to `bobbanga/codex-task-broker` happens in Task 6, so the
  `codex-task-broker` GitHub install URL is not usable yet.
- Publication: source repository is public; no package registry release has
  been performed.

## Verification Gate

The extracted repository must pass its CLI test modules, a disposable
virtual-environment install, `codex-broker --help`, and `git diff --check`
before becoming the installed source.

## Next Gate

Use the installed mock-only CLI in one disposable external Git project. Any
real WorkBuddy backend requires a new approved architecture based on a native
narrow/no-tools mode or a separately supported API adapter.

PyPI publication is tracked in GitHub issue
[#1](https://github.com/bobbanga/codex-workbuddy-coordinator/issues/1). It may
proceed only after the issue's cross-project observation, metadata, CI,
TestPyPI, clean-install, and final Bob approval gates are satisfied.

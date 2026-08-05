# Project Status

Updated: 2026-08-06

## Position

This repository is the canonical source for the cross-project
`codex-broker` CLI. It was extracted from `D:\Code\work\bob-skills` after the
V0.9a Stage 1c protocol. Task 6 completed the public rename, local migration,
remote rename, and user-level package replacement.

## Current State

- Product: Codex Task Broker / Codex 任务管家.
- Distribution: `codex-task-broker` 0.1.0.
- Console command: `codex-broker`.
- Installed user-level package: `codex-task-broker` 0.1.0.
- Installation and remote repository migration: completed; `codex-broker --help`
  is verified from the user-level installation.
- Runtime mode: compatibility `mock_only` plus the bounded WorkBuddy broker.
- Public stop states: `VALIDATED` for validation and `REVIEW_READY` for a
  successful bounded run.
- Real WorkBuddy adapter: wired and independently tested with fakes; local
  `doctor` currently reports not ready because no compatible WorkBuddy CLI is
  discoverable on PATH or in the standard Desktop location.
- Remote repository: public GitHub repository
  `bobbanga/codex-task-broker`; local `main` tracks `origin/main`.
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
[#1](https://github.com/bobbanga/codex-task-broker/issues/1). It may
proceed only after the issue's cross-project observation, metadata, CI,
TestPyPI, clean-install, and final Bob approval gates are satisfied.

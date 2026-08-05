# Project Status

Updated: 2026-08-05

## Position

This repository is the canonical source for the cross-project
`codex-workbuddy` CLI. It was extracted from `D:\Code\work\bob-skills` after the
V0.9a Stage 1c protocol and the V0.1.0 mock-only CLI passed disposable-install
and full-suite verification.

## Current State

- Distribution: `codex-workbuddy-coordinator` 0.1.0.
- Console command: `codex-workbuddy`.
- Installation: Bob-approved user-level Python installation, verified with
  `codex-workbuddy --help`.
- Runtime mode: `mock_only` only.
- Public stop states: `VALIDATED` for validation and `REVIEW_READY` for a
  successful bounded run.
- Real WorkBuddy adapter: rejected under the previously observed generic CLI
  startup surface; not implemented here.
- Remote repository: public GitHub repository
  `bobbanga/codex-workbuddy-coordinator`; local `main` tracks `origin/main`.
- Publication: source repository is public; no package registry release has
  been performed.

## Verification Gate

The extracted repository must pass its four CLI test modules, a disposable
virtual-environment install, `codex-workbuddy --help`, and `git diff --check`
before becoming the installed source.

## Next Gate

Use the installed mock-only CLI in one disposable external Git project. Any
real WorkBuddy backend requires a new approved architecture based on a native
narrow/no-tools mode or a separately supported API adapter.

PyPI publication is tracked in GitHub issue
[#1](https://github.com/bobbanga/codex-workbuddy-coordinator/issues/1). It may
proceed only after the issue's cross-project observation, metadata, CI,
TestPyPI, clean-install, and final Bob approval gates are satisfied.

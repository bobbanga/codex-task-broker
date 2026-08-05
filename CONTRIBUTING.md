# Contributing

Thanks for your interest in Codex Task Broker. This is alpha, Windows-first
software, and the runtime protocol is deliberately conservative.

## Before You Start

Open an issue before large changes so the design can be discussed first. Small
fixes, documentation improvements, and tests are welcome directly as pull
requests.

## Development Setup

Python 3.11 or newer is required. The runtime has no third-party dependency.

```powershell
py -3 -m pip install -e ".[dev]"
py -3 -m pytest -q
py -3 -m ruff check src tests
```

## Design Constraints

Please keep these invariants intact; changes that weaken them will not be
merged without a separate design discussion:

- The Run Request JSON is the only editable runtime input. Nothing is inferred
  from chat, the current directory, environment variables, or model defaults.
- Unknown or missing request fields fail closed.
- Child processes are started from argv arrays with `shell=false`, and receive
  only explicitly allowlisted environment variables.
- The Contributor is invoked at most once per run, and its self-report is never
  treated as authoritative. Git and verification facts are recalculated.
- Run evidence is written to a run store outside the target checkout, never
  into this repository or the target project.
- A run ends at `REVIEW_READY`, which is a handoff for human review, not
  approval.

## Pull Requests

- Keep each pull request focused on one change.
- Add or update tests for any behavior change, and run the full suite.
- Do not commit build artifacts, run evidence, credentials, or absolute paths
  from your own machine.
- Update `CHANGELOG.md` under `Unreleased` for user-visible changes.

By contributing, you agree that your contributions are licensed under the MIT
License in `LICENSE`.

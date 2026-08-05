# codex-workbuddy-coordinator

English | [简体中文](README.md)

`codex-workbuddy-coordinator` is the canonical source repository for the cross-project `codex-workbuddy` CLI. It applies the V0.9a `mock_only` protocol to one explicit Run Request, invokes one bounded local Contributor, recalculates Git and verification evidence, and stops at `REVIEW_READY` for Codex review.

## Status

| Item | Status |
| --- | --- |
| CLI version | `0.1.0` |
| Supported mode | `mock_only` only |
| Python | 3.11 or newer |
| GitHub | Public |
| PyPI | Not published |
| Real WorkBuddy adapter | Not certified or implemented |

## Installation

Install from GitHub:

```powershell
py -3 -m pip install "git+https://github.com/bobbanga/codex-workbuddy-coordinator.git"
```

Install from a local checkout:

```powershell
py -3 -m pip install .
```

A PyPI release will be considered separately after cross-project observations, package metadata, CI, and TestPyPI verification are complete.

## Usage

```powershell
codex-workbuddy validate <run-request.json>
codex-workbuddy run <run-request.json>
```

- `validate` checks the request only. A valid request returns `VALIDATED` and never starts the Contributor.
- `run` repeats preflight, starts exactly one explicitly configured Contributor, writes evidence to the external `run_store_path`, and stops at `REVIEW_READY`.
- Both commands emit one JSON object to stdout and send diagnostics to stderr.

See the [protocol documentation](docs/protocol.md) for Run Request fields and examples.

## Security Boundaries

- Only `mode="mock_only"` is accepted.
- The Run Request JSON is the sole editable runtime input owner.
- Contributor and verification commands use argv arrays with `shell=false`.
- Child processes receive only explicitly allowlisted environment variables.
- `run_store_path` must be outside the target checkout.
- Contributor claims are not authoritative; the Runner recalculates Git, test, and artifact facts.
- `REVIEW_READY` is a handoff to Codex, not approval.
- The CLI contains no path that invokes real WorkBuddy.

A real WorkBuddy adapter requires a native narrow/no-tools mode or a separately supported and certified API adapter. Publishing this repository does not enable that capability.

## Source Ownership

The Python import namespace remains `bob_skills.codex_workbuddy_coordinator` for V0.1 compatibility. The distribution and canonical source repository are both named `codex-workbuddy-coordinator`.

- [Project status](docs/project-status.md)
- [Protocol](docs/protocol.md)
- [Design](docs/superpowers/specs/2026-08-05-codex-workbuddy-cross-project-cli-design.md)
- [Implementation plan](docs/superpowers/plans/2026-08-05-codex-workbuddy-cross-project-cli.md)

## Development

```powershell
py -3 -m pytest -q
```

The runtime has no third-party Python dependency. Remote changes, package publication, and any real WorkBuddy adapter work remain explicit Bob approval gates.

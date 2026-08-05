# Codex Task Broker / Codex 任务管家

English | [简体中文](README.md)

Let Codex hand one bounded coding task to another coding tool, then independently
verify the result.

You write a Run Request that names the checkout to change, the files the task may
touch, and the commands that prove it worked. `codex-task-broker` invokes the coding
tool once, then re-runs the Git and verification checks itself instead of trusting
what the tool claims it did. It stops at `REVIEW_READY` and hands you evidence you
can check.

The problem it solves: when you delegate a change, you should not have to take the
other side's word for whether it is correct.

The current CLI supports only `mock_only` mode, meaning it starts just the local
command you explicitly configure in the Run Request, and does not yet implement a
real adapter. WorkBuddy is the planned/target and only MVP-stage executor adapter.
The protocol version is V0.9a.

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

Install from a local checkout:

```powershell
py -3 -m pip install .
```

Install from GitHub, which becomes usable only after the planned repository
rename:

```powershell
py -3 -m pip install "git+https://github.com/bobbanga/codex-task-broker.git"
```

That remote does not exist yet. Until the rename lands, installing from a local
checkout is the only supported path. The project is not published on PyPI.

## Usage

```powershell
codex-broker validate <run-request.json>
codex-broker run <run-request.json>
```

- `validate` checks the request only. A valid request returns `VALIDATED` and never starts the Contributor.
- `run` repeats preflight, starts exactly one explicitly configured Contributor, writes evidence to the external `run_store_path`, and stops at `REVIEW_READY`.
- Both commands emit one JSON object to stdout and send diagnostics to stderr.

See the [protocol documentation](docs/protocol.md) for Run Request fields, the
[JSON Schema](schemas/run-request.schema.json) for machine validation, and
[`examples/minimal-run-request.json`](examples/minimal-run-request.json) for a
minimal request.

## Security Boundaries

- Only `mode="mock_only"` is accepted.
- The Run Request JSON is the sole editable runtime input owner.
- Contributor and verification commands use argv arrays with `shell=false`.
- Child processes receive only explicitly allowlisted environment variables.
- `run_store_path` must be outside the target checkout.
- Contributor claims are not authoritative; the Runner recalculates Git, test, and artifact facts.
- `REVIEW_READY` is a handoff to Codex, not approval.
- The CLI contains no path that invokes real WorkBuddy.

WorkBuddy is the only MVP-stage executor adapter. A real WorkBuddy adapter requires a native narrow/no-tools mode or a separately supported and certified API adapter. Publishing this repository does not enable that capability.

## Source Ownership

The Python import namespace is `codex_task_broker`. The distribution and canonical source repository are both named `codex-task-broker`.

- [Protocol](docs/protocol.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)

## Development

```powershell
py -3 -m pip install -e ".[dev]"
py -3 -m pytest -q
py -3 -m ruff check src tests
```

The runtime has no third-party Python dependency. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the design constraints a change must
preserve, [SECURITY.md](SECURITY.md) for private vulnerability reports, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)

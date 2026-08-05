# codex-workbuddy-coordinator

`codex-workbuddy-coordinator` is the canonical source repository for the
cross-project `codex-workbuddy` CLI. It applies the V0.9a mock-only protocol to
one explicit Run Request, invokes one bounded local Contributor, recalculates
Git and verification evidence, and stops at `REVIEW_READY`.

```powershell
codex-workbuddy validate <run-request.json>
codex-workbuddy run <run-request.json>
```

`validate` never starts a Contributor and returns `VALIDATED` for a valid
request. `run` repeats preflight, starts exactly one configured Contributor,
writes artifacts to the external `run_store_path`, and never reviews, merges,
pushes, installs, deploys, or publishes.

## Boundaries

- Only `mode="mock_only"` is accepted.
- The Run Request JSON is the sole editable runtime input owner.
- Contributor and verification commands use argv arrays with `shell=false`.
- Child processes receive only explicitly allowlisted environment variables.
- The run store must be outside the target checkout.
- `REVIEW_READY` is a handoff to Codex, not approval.
- This CLI contains no path that invokes real WorkBuddy.
- A real WorkBuddy adapter remains a separate design and certification gate.

The Python import namespace remains
`bob_skills.codex_workbuddy_coordinator` for V0.1 compatibility. The
distribution and repository owner are now `codex-workbuddy-coordinator`.

Protocol fields are documented in [docs/protocol.md](docs/protocol.md). Current
status is recorded in [docs/project-status.md](docs/project-status.md).

## Development

```powershell
py -3 -m pytest -q
```

Runtime code has no third-party dependency. Installation, remote creation,
push, publication, and real-adapter work remain explicit Bob approval gates.

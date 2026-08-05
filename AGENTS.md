# codex-workbuddy-coordinator collaboration rules

## Ownership

This repository is the single editable owner of the `codex-workbuddy` Python
package, CLI runtime, Run Request validation, artifact readers, one-shot runner,
and their tests. `D:\Code\work\bob-skills` owns only Bob-facing Skill routing and
governance guidance; it must not grow a second editable CLI implementation.

Runtime evidence belongs in the external run store selected by the Run Request,
never in this repository or the target project.

## Scope

- Keep the public CLI mock-only until Bob separately approves a real-adapter
  architecture and its certification evidence.
- Do not infer paths, permissions, commands, models, or environment variables.
- Preserve argv execution with `shell=false`, one Contributor invocation,
  filtered child environments, exact Git/evidence recalculation, and the
  `REVIEW_READY` human handoff.
- Do not treat Contributor reports as authoritative evidence.

## Development

- Read the approved design and current project status before changing behavior.
- Use the smallest change compatible with the frozen protocol.
- Add or update focused tests for behavior changes and run the full suite before
  completion.
- Keep generated build artifacts and run evidence out of Git.

## Approval gates

Bob must explicitly approve remote repository creation, push, PR, merge,
publication, deployment, global installation changes, and any real WorkBuddy
adapter execution.

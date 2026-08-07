# Roadmap

Roadmap items are directions of work, not promises. Scope, order, and delivery
may change, and anything listed here may be dropped. Only behavior documented
in the README exists today.

## WorkBuddy MVP

Make one bounded task delegation work end to end with WorkBuddy as the single
executor adapter: discovery of a local installation, an environment check
command, a Run Request that targets a Git worktree, and independent
recalculation of Git and verification evidence before the `REVIEW_READY`
handoff. The public CLI stays mock-only until a real adapter is implemented
and certified.

## Additional Executor Adapters

Generalize the executor boundary so other coding agents can be plugged in
behind the same protocol, with per-adapter capability probing so unsupported
adapters fail closed instead of silently degrading.

## Optional Policy and Cost Routing

Explore optional routing that selects an adapter from declared policy, such as
task size, required capabilities, or cost limits. This stays opt-in; the
default remains a single explicitly named executor.

### Routing Governance Backlog

The following ideas are recorded as future design inputs from a reviewed
multi-model routing project. They are not part of the WorkBuddy MVP and do not
add that project's runtime, gateway, provider configuration, or model roster:

- Define explicit task capability and role labels before selecting an executor
  or model; keep the final decision with the coordinating Codex process.
- Support opt-in fallback chains with a recorded reason for every downgrade,
  refusal, timeout, or unavailable executor.
- Add a doctor/health contract and small per-executor smoke checks before a
  routed run; treat stale model, endpoint, and capability claims as failures.
- Extend evidence manifests with route decision, selected profile, fallback
  history, and redacted health results, without storing credentials or full
  prompts.
- Document rollback, disable, and recovery procedures for routing changes;
  require explicit approval before changing installed skills, local settings,
  or external gateway configuration.
- Keep provider/model routing separate from the bounded executor protocol so
  WorkBuddy remains usable without any cost service or multi-provider gateway.

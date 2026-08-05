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

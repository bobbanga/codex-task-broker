---
name: codex-task-broker
description: Delegate one bounded coding task to a locally installed executor through the codex-broker CLI, then review the result yourself. Use only when the user explicitly asks to hand implementation work to another coding agent. Do not use for planning, review, or tasks you are implementing yourself.
---

# Codex Task Broker

Delegate exactly one bounded implementation task, then review the result.

## When to use this Skill

Use it **only** when the user explicitly asks for delegation, for example:

- "Ask the other agent to implement this, then review its work."
- "Hand this task off and check the result."
- "Delegate this fix."

Do **not** use it when:

- the user asks you to plan, explain, review, or design;
- the user asks you to implement something yourself;
- delegation is merely something you think would be faster.

Ambiguity means no delegation. Ask first.

## What stays with you

You keep the parts that require judgment:

- **Planning.** You decide what the task is and what its boundaries are.
- **Scoping.** You choose the exact files the executor may change.
- **Review.** You read the resulting diff and decide whether it is correct.

The broker only executes and collects evidence. It never decides whether work
is acceptable.

## Workflow

### 1. Check readiness first

Before the first delegated task in a session, and again after the user changes
their executor installation, run:

```
codex-broker doctor --executor <executor> --json
```

If it does not report ready, stop and tell the user exactly what to fix. Do not
attempt the task anyway.

### 2. Agree on the task and scope

Restate the task in one or two sentences and list the files the executor may
change. Confirm the verification command you will use to check the result
(usually the project's existing test command).

Keep the scope as narrow as the task allows. A task touching one file is a good
task; a task touching a whole subsystem is not ready for delegation.

### 3. Write the brief and run the broker

You generate the task brief. The user never writes JSON. See
[references/request-contract.md](references/request-contract.md) for the exact
fields.

```
codex-broker run --repo <repository> --brief <brief.json> --executor <executor> --json
```

The broker creates an isolated Git worktree bound to the current base commit,
invokes the executor exactly once, and then independently recalculates the Git
and verification evidence. It does not trust what the executor reports about
its own work.

### 4. Read the outcome

`REVIEW_READY`
: The run finished and evidence is consistent. Go to step 5.

`PREFLIGHT_FAILED`
: Nothing ran. Usually the repository is dirty, the base ref is wrong, or the
  task id was already used. Fix the cause and retry.

`CONTRIBUTOR_STOPPED`
: The executor stopped: timeout, non-zero exit, unusable output, or a pending
  permission decision. The worktree is preserved.

`EVIDENCE_FAILED`
: The executor finished but the result does not hold up: files outside the
  allowed scope, no commit, a dirty workspace, or failing verification.

For any non-ready state, report what happened in plain language and where the
evidence is. Do not retry automatically.

### 5. Review the change yourself

Read the actual diff in the worktree. Confirm that it does what the task asked,
that it is correct, and that nothing unrelated changed. Verification passing is
necessary but not sufficient — you still have to read the code.

Then report to the user: what changed, whether you consider it correct, and
what you recommend. Stop there.

## Hard rules

- **Never call the executor directly.** Every invocation goes through
  `codex-broker`. If you find yourself building executor flags by hand, stop.
- **Never merge, push, open a PR, publish, or deploy.** The run ends at your
  review. Applying the change is the user's decision, made separately.

The run ends at your review; never apply it automatically.
- **Never widen permissions to make a run succeed.** If a run stops because it
  needs broader access, explain what it wants and why, and let the user decide.
  A permission stop is a question for a human, not a retry.
- **Never delete a failed worktree on your own.** Failed runs keep their
  evidence. The result includes a cleanup command; show it, and only run it
  after the user has finished with the evidence.
- **Never present the executor's own summary as evidence.** Only the broker's
  recalculated Git and verification facts count.
- **One task per run.** Do not chain a second delegation off a first without
  the user asking.

## Talking to the user

Speak in plain language. Do not show JSON, worktree mechanics, or executor
flags unless the user is debugging or asks for them.

Good: "It changed `src/parser.py` to handle the empty-input case, and the tests
pass. I read the diff and it looks correct — want me to apply it?"

Bad: pasting the run result object.

Surface a decision to the user only when it genuinely needs one: a real
permission expansion, an ambiguous scope, or a failure they must choose how to
handle.

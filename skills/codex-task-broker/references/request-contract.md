# Task brief contract

The task brief is the only input you write for a brokered run. The broker
infers nothing from chat, the current directory, the environment, project
metadata, or model defaults. Unknown or missing fields are rejected.

Pass it with `codex-broker run --brief <path>`.

## Example

```json
{
  "schema": "codex-task-broker-task-brief",
  "schema_version": 1,
  "task_id": "fix-empty-input-001",
  "objective": "Handle empty input in parse_line without raising IndexError. Add a regression test.",
  "allowed_files": ["src/parser.py", "tests/test_parser.py"],
  "verification_commands": [["py", "-3", "-m", "pytest", "-q"]],
  "model": "<explicit model name>",
  "base_ref": "HEAD",
  "environment_allow": ["PATH"],
  "timeout_seconds": 900
}
```

## Fields

### Required

| Field | Type | Rule |
| --- | --- | --- |
| `schema` | string | Exactly `codex-task-broker-task-brief`. |
| `schema_version` | integer | Exactly `1`. |
| `task_id` | string | 1–64 characters, `A-Z a-z 0-9 . _ -`, starting with a letter or digit. Must be unique per run root: a reused id is rejected rather than overwriting an earlier run. |
| `objective` | string | Non-empty. What to do and what "done" means, in prose. This becomes the executor's instructions, so write it for the executor, not for the user. |
| `allowed_files` | array of strings | Non-empty. Repository-relative paths only. No absolute paths, no drive letters, no `..` segments. Any change outside this list fails the run. |
| `verification_commands` | array of argv arrays | Non-empty. Each entry is an array of strings, never a single command string. Run in the isolated worktree with `shell=false`. |
| `model` | string | Non-empty. Always explicit; there is no default and no fallback. |

### Optional

| Field | Type | Default | Rule |
| --- | --- | --- | --- |
| `base_ref` | string | `HEAD` | The commit the isolated worktree is bound to. Resolved once, before creation, and re-checked afterwards. |
| `environment_allow` | array of strings | `[]` | Environment variable names the child process may see. The child never inherits your environment. Secret-shaped names (containing `token`, `key`, `password`, `secret`, `credential`, or `authorization`) are rejected. |
| `timeout_seconds` | integer | `900` | Positive integer. Bounds both the executor invocation and each verification command. |

## What cannot be requested

There is no field for network access, credentials, installation, push, merge,
deploy, publication, permission mode, or any other external effect. If a task
appears to need one, it is not a task for this broker.

## Preconditions the broker enforces

These are checked before anything runs; a failure stops the run at
`PREFLIGHT_FAILED`:

- the source path is a real Git work tree;
- the source repository has no uncommitted or untracked changes;
- `base_ref` resolves to a commit;
- `task_id` has not already been used under this run root;
- the run root resolves outside the source repository.

## What the broker recalculates afterwards

The executor's own report is advisory and never counted as evidence. After the
single invocation, the broker independently determines:

- the worktree's final `HEAD` and whether the base is its ancestor;
- the changed files, and which of them fall outside `allowed_files`;
- whether the workspace is clean;
- each verification command's exit code and captured output.

## Outcome states

| State | Exit code | Meaning |
| --- | --- | --- |
| `REVIEW_READY` | 0 | Ran and the evidence is consistent. Review the diff. |
| `PREFLIGHT_FAILED` | 2 | Nothing ran; a precondition failed. |
| `CONTRIBUTOR_STOPPED` | 3 | The executor timed out, exited non-zero, produced unusable output, or stopped for a permission decision. |
| `EVIDENCE_FAILED` | 4 | It finished, but scope, commit, workspace, or verification checks failed. |
| `INTERNAL_ERROR` | 5 | An unexpected broker failure. |

A failed run keeps its worktree and evidence. The result carries a cleanup
command; it is never run automatically.

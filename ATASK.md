# ATASK.md — the A-task native contract (portable, one page)

Paste this file (or its rules) into ANY agent's instructions — opencode,
Claude Code, cron job, other VPS. No dependencies, no daemon. The queue is
files; the audit is `acheck.py`; the autonomous tick is `driver.py pulse`.
If the agent follows this, it is A-task native and your life gets easier:
one shape everywhere, one dashboard over all boxes.

## The canonical loop

1. **Set an A-goal.** One active end-state with checkable acceptance
   (`goal set --statement ... --accept ...`). The goal is DONE when every
   acceptance index is covered by DONE tasks — derived, never declared.
2. **Decompose into A-tasks.** Each task maps to goal indices
   (`--covers-goal 0,2`) and carries its own acceptance + evidence plan.
   READY = status in (JUSTIFIED, EXECUTING) AND every `blocked_by` id DONE.
3. **Log all activity to A-logs.** Every action appends a line
   (`a-logs/<id>.jsonl`) tagging which acceptance indices it covers and
   where the re-runnable evidence is (`command:...`). No log, no claim.
4. **A validator judges the match.** `validators/<task-id>.py` (a dummy
   script, stdlib) reads the task + its a-log and returns pass/fail with
   reasons. The stoplight runs it plus re-runs every evidence claim.
   Validators are additive: they can fail a task, never excuse one.
5. **Repeat until complete.** REPORTED → pulse promotes to DONE iff the
   stoplight is green. `goal check` tells you when the goal is done.

## The 5 rules

1. **The queue is truth.** `tasks.jsonl` holds all work. Never invent work
   outside the queue — `spawn` it as PROPOSED under a parent first.
2. **Execute lowest-blocked, branch deeper freely.** `spawn --parent ...`
   creates a child that inherits the parent's blockers; the parent then
   waits on the child (children finish first). Depth is recorded; depth 8
   refuses — split the goal instead of recursing forever.
3. **Log every action.** A-log lines as you go: what, which acceptance it
   covers, re-runnable evidence. No log, no claim.
4. **DONE needs proof.** Report file + resolvable `sha256:` receipt +
   green stoplight (covers + evidence + validator). No receipt, no DONE.
5. **Blocked on human → escalate, never guess.** `escalate --id ... --need`
   files an h-task with exactly what is needed from whom and parks the
   A-task PAUSED. Keep working the rest, optionally against a `--predict`
   payload. When the human `answer`s, dependents that ran on the prediction
   flip back to EXECUTING with a reverify line — nothing silently passes
   on stale data.

## Record shapes

```json
{"id": "a-slug", "tier": "A", "summary": "what done looks like",
 "acceptance": ["checkable end-state 1"],
 "evidence_required": [{"kind": "command", "spec": "pytest tests/ -q"}],
 "blocked_by": [], "status": "PROPOSED", "depth": 0, "covers_goal": [0],
 "report_ref": "reports/a-slug.md", "validation_ref": "runs/sha256….json"}
```

```json
{"id": "h-abc123", "task": "a-slug", "need": "which API key?",
 "options": ["key-a", "key-b"], "recommendation": "key-a",
 "predicted": {"key": "key-a"}, "status": "open", "answer": null}
```

Lifecycle: `PROPOSED → JUSTIFIED → EXECUTING → REPORTED → DONE`
(`PAUSED` = h-task cited in `paused_on`; `REJECTED` carries reasons and
re-enters at PROPOSED, never straight to DONE.)

## Turn loop

```
driver.py boot → drain READY (execute → a-log → report → receipt → DONE)
  → spawn sub-tasks where blocked → escalate where human-needed
  → pulse → halt ONLY with dryness proof (nothing ready, nothing splittable)
```

## Self-audit

`python3 acheck.py --dir .atask` — exit 0 = native. `goal check` — exit 0 =
goal done. Wire both into CI. An agent that passes acheck on its own queue
is A-task native by measurement, not by promise.

# DELEGATION.md — who does what, and how work crosses agents

Stolen straight: Cursor's subagent registry (markdown + frontmatter lanes,
auto-delegation by description), the cost-tier triage tree (cheap models
first, architect only when genuinely architectural), and Hermes' one hard
rule — **Kanban, not function calls**: delegation crosses agents as durable
queue records with frozen briefs, never as in-memory calls that die on
restart.

## The lanes (`agents/*.md`)

Each lane is a markdown file with frontmatter (Cursor-compatible shape):

```md
---
name: coder
description: Mechanical implementation of well-specified tasks.
model: standard
readonly: false
---
...the lane's prompt...
```

Shipped defaults: `analyst` (cheap, read-only recon) · `coder`
(standard, mechanical implementation) · `architect` (strong, decisions
only). `init` seeds them; edit or add lanes per repo — never overwrite
another repo's lanes by hand-merging.

## Triage (cheapest model that can do the job — always)

```
task arrives
├─ read-only research? ............ analyst   (cheap)
├─ mechanical / well-specified? ... coder     (standard)
├─ genuinely architectural? ..... architect (strong)
└─ otherwise .................... do it yourself (you are the parent)
```

The parent only works itself what no lane fits. After delegated work
lands, the stoplight + validator re-verify it — the harness's stoplight
IS the reviewer lane, always on, no separate review step to forget.

## How to delegate

```bash
python3 atask.py delegate --dir .atask --parent a-x --id a-y \
  --to coder --brief "exact end-state + acceptance + evidence plan"
```

This spawns a child (parent waits on it, children-first) and freezes the
brief to `briefs/<id>.<lane>.md`, sha-pinned on the record. The delegate
— you in another session, a cron worker, a subagent on its own machine —
drains it like any task: execute → a-log → report → receipt → DONE.
Mid-task brief edits void the assignment (new sha, new task).

## Rules

1. **Frozen briefs.** The delegate works from the pinned sha, not from
   chat. If reality breaks the brief, the delegate escalates — never
   silently reinterprets.
2. **Judge separation.** Whoever writes the brief never grades it: the
   stoplight + validator grade the log, mechanically.
3. **Money never delegates silently.** Spend routes M (see `policy`);
   caps in `atask.yaml`/`budget set` brake every lane equally, and the
   remaining budget rides every pulse (`advertise`) so subagents see it.
4. **Humans promote, never spawn.** H-tasks only arrive via `escalate`
   from a blocked A-task — same for delegates as for parents.

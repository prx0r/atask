# atask — the canonical autonomous agent harness (one shape everywhere)

Stdlib-only Python. No install beyond `git clone` + Python 3.11. Any agent —
opencode, Claude Code, cron job, other VPS — becomes A-task native by
following `ATASK.md` (one page) and passing `acheck.py` (exit 0).

```bash
python3 atask.py init --dir .atask
python3 atask.py goal set --dir .atask --statement "ship demo" --accept "demo runs" --accept "docs exist"
python3 atask.py add --dir .atask --id a-run --summary "make demo run" --accept "demo runs" --covers-goal 0
python3 atask.py justify --dir .atask --id a-run && python3 atask.py execute --dir .atask --id a-run
python3 atask.py log --dir .atask --id a-run --covers 0 --evidence "command:./demo --self-test"
python3 atask.py report --dir .atask --id a-run --report reports/a-run.md --receipt sha256:...
python3 driver.py pulse --dir .atask     # promotes to DONE iff stoplight green
python3 atask.py goal check --dir .atask # exit 0 = goal done
python3 acheck.py --dir .atask           # exit 0 = native
python3 -m unittest discover tests       # harness self-tests (23 green)
```

Branch deeper with `spawn`, park on humans with `escalate` / resume with
`answer`, judge logs with per-task `validators/<id>.py` (see VALIDATORS.md).
Cap spend with `budget set` (SpendLimits semantics: the crossing call
completes, the next is refused; exhausted budget refuses the pulse).
Delegate across agents with frozen briefs (`delegate --to`, see
DELEGATION.md). Route every step with `policy` (prohibited blocks in code;
spend → M, human/irreversible → H, else A). Repo config lives in
`.atask/atask.yaml` (caps, extra prohibited patterns).

| File | Role |
|---|---|
| `budget.py` | Durable spend brake (`budgets.json`, env advertise) |
| `agents/` | Default delegation lanes (analyst/coder/architect, Cursor-style frontmatter) |
| `DELEGATION.md` | Triage doctrine: cheapest-capable first, Kanban not function calls |

## Files

| File | Role |
|---|---|
| `ATASK.md` | One-page contract: goal → tasks → alogs → validator → done |
| `atask.py` | Queue core: goal/spawn/log/stoplight/escalate/answer/done-gate/budget/policy |
| `driver.py` | Autonomous pulse: `boot` / `pulse` (one tick) / `run` (to halt-legal) |
| `instrument.py` | 10-key control harness: `press <chain>` (digits), `presses` (the log) |
| `keys.json` + `chain.py` | Key contract + digit grammar (only 4 takes a digit) |
| `press.py` | Press rows in predictor shape: shown/picked/context/outcome |
| `mcp_server.py` | Read-only A-language tools over stdio (agent reads, digits write) |
| `acheck.py` | Self-audit: exit 0 = A-task native |
| `runs.py` | Content-addressed receipts (`sha256:` ids, tamper-evident) |
| `VALIDATORS.md` | The dummy-judge contract + minimal example |
| `AGENTS.md` | Binding laws for agents working under this harness |
| `tests/` | Self-tests (stdlib unittest, no deps) |

## Control harness (the 0-9 endgame)

Give the agent the MCP (`mcp_server.py`); it speaks A-language and surfaces
needs only as h-tasks. You answer in digits (`instrument.py press <chain>`):
1 GO · 2 ZOOM · 3 DIG · 4 PICK#n · 5 OK · 6 NO · 7 TELL · 8 GOAL · 9 FIX ·
0 STOP. Every press logs a predictor-shaped row to `presses.jsonl` — the
start-to-end sequence of a build, ready to model and automate later.

```bash
python3 instrument.py press 2 --dir .atask --session build1
python3 instrument.py press 41 --dir .atask --session build1   # PICK#1
python3 instrument.py presses --dir .atask
```

## State (per adopting repo, default `.atask/`)

`goal.json` (one active end-state) · `tasks.jsonl` (the queue) ·
`h-tasks.jsonl` (human queue) · `a-logs/<id>.jsonl` (action lines) ·
`reports/*.md` (claim, evidence, self-review, needs, cost) ·
`validators/*.py` (dummy judges) · `runs/sha256_*.json` (receipts) ·
`pulse.jsonl` (driver ticks).

## Autonomy

Cron fires `driver.py pulse`; the agent drains the READY orders it emits;
goal progress + open humans ride every pulse. Judgment stays with the
agent; verification stays mechanical. Next layer up (not here): the 10-key
press instrument + phone dashboard (digits + voice) over any `.atask/` dir.

## Cron

```cron
*/15 * * * * cd /path/to/repo && python3 /path/to/atask/driver.py pulse --dir .atask >> .atask/driver.log 2>&1
```

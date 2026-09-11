# atask — the control language for one autonomous agent

Stdlib-only Python. No install beyond clone + Python 3.11. atask knows
nothing about building software: its entire job is goal → autonomous work
→ externally validated claims → bounded human decisions (0–9) → record →
continue. Learning how you press belongs one layer up (Seed0); this repo
only guarantees the presses are worth learning from.

```bash
python3 atask.py init --dir .atask
python3 atask.py goal set --dir .atask --statement "ship demo" --accept "demo runs"
python3 atask.py add --dir .atask --id a-run --summary "make it run" --accept "runs" --covers-goal 0
# ... work, log, report, receipt ...
python3 driver.py pulse --dir .atask
python3 instrument.py press 0 --dir .atask --session build1   # accept
python3 instrument.py digest --dir .atask --session build1    # outcome row
python3 -m unittest discover tests                            # 36 green
```

## The seven verbs (MCP)

`a_goal` (exit-truth) · `a_status` (start every turn here) · `a_task`
(READY orders) · `a_proof` (GO/NOGO per task) · `a_ask` (open questions:
kind/options/recommendation — all the agent may ask) · `a_answer` (HUMAN
SIDE: digits) · `a_done` (pulse promotes iff green). The MCP is read-only;
digits write. Config: `{"mcp": {"atask": {"type": "local", "command":
["python3", "/path/to/atask/mcp_server.py", "--dir", "/path/to/.atask"]}}}`.

## The keypad

0 accept (=GO when idle) · 1 orders · 2 status · 3 blockers · 4 pick 1–7 ·
5 approve · 6 deny · 7 answer/correction · 8 expand · 9 halt. Modes (idle /
question) ride in every press row with question + context + choice;
`digest` appends the session outcome. Seed0 joins on session.

## Files

| File | Role |
|---|---|
| `ATASK.md` | The contract (paste into any agent's instructions) |
| `atask.py` | Queue: goal/spawn/log/stoplight/ask-gate/escalate/answer/done-gate/verify |
| `driver.py` | `boot` / `pulse` / `run` — mechanical promotion + BATS resource block |
| `events.py` | Canonical `events.jsonl` (wall + monotonic clocks) — the only analytics format |
| `instrument.py` | `press` / `presses` / `digest` — digits in, dataset out |
| `keys.json` + `chain.py` | Key contract + digit grammar |
| `press.py` | Predictor-shaped rows (shown/picked/question/context/choice) |
| `mcp_server.py` | Seven verbs over stdio |
| `acheck.py` | Exit 0 = native |
| `runs.py` | Content-addressed receipts + `Run` dataclass (mono timing, counters) |
| `VALIDATORS.md` | Dummy-judge contract |
| `staging/` | Pruned subsystems (budgets, lanes, triage) — Seed0-side, recoverable |

## State (per repo, `.atask/`)

`goal.json` · `tasks.jsonl` · `h-tasks.jsonl` · `a-logs/` · `reports/`
(validators check 5 sections) · `validators/` · `runs/` · `presses.jsonl`
· `events.jsonl` · `corrections.jsonl` · `pulse.jsonl` · `HALT.json`.

## Layers (what lives where)

```text
L0 KERNEL (this repo, stdlib only)
  goal/task/proof/human boundary, Run counters, event emission.
  NO intelligence. `grep pydantic|opentelemetry kernel/` = nothing (CI-tested).

L1 OBSERVABILITY (outside)
  events.jsonl → OTel adapter → Phoenix; SQLite/DuckDB over the stream.
  NO control.

L2 POLICY (outside: Seed0)
  BATS resource-awareness → forecasts → contextual bandits → routing.
  LEARNS control. The kernel never refuses on budget; it reports remaining.
```

## Boundary rule (what belongs here)

If a feature does not help an agent communicate an externally verifiable
state or request a bounded human decision, it does not belong in atask.

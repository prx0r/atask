#!/usr/bin/env python3
"""events.py — one canonical append-only event stream. Stdlib only.

Every state change in the kernel emits a tiny row to events.jsonl:

  {ts, mono_ns, event, ...fields}

ts (wall) answers "when did this happen?"; mono_ns (monotonic) answers
"exactly how long did this take?" (immune to NTP/clock changes).
L1 observability (OTel/Phoenix/SQLite) and L2 policy (BATS/bandits/Seed0)
consume this stream — they never become kernel dependencies.

Core event names:
  task.status      task_id, from, to, attempts
  run.started      task_id, run_id, attempt
  run.finished     task_id, run_id, outcome, elapsed_ms
  validator.passed task_id
  validator.failed task_id, reasons[]
  resource.used    task_id, cost_usd, tokens
  human.asked      hid, task_id, kind, options[], recommended
  human.choice     hid, kind, recommended, selected
  goal.done        acceptance, spent_usd
  session.outcome  session, goal_done, spent_usd, presses
"""
from __future__ import annotations
import json
import time
from pathlib import Path

EVENTS = "events.jsonl"


def emit(root: str | Path, event: str, **fields) -> dict:
    """Append one event row. Returns the row. Never raises on I/O."""
    root = Path(root)
    row = {"ts": time.time(), "mono_ns": time.monotonic_ns(),
           "event": event}
    row.update({k: v for k, v in fields.items() if v is not None})
    try:
        with open(root / EVENTS, "a") as f:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        pass
    return row


def read(root: str | Path, event: str | None = None, limit: int = 0) -> list[dict]:
    """All rows (optional event filter, optional tail limit). No file = []."""
    p = Path(root) / EVENTS
    if not p.exists():
        return []
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if event:
        rows = [r for r in rows if r.get("event") == event]
    return rows[-limit:] if limit else rows

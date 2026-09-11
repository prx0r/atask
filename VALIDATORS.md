# VALIDATORS.md — the dummy judge contract

Each task may ship a validator: `validators/<task-id>.py`. It answers one
question — **does the a-log match the criteria set for this task?** The
stoplight runs it (plus re-runs every `command:` evidence claim) before any
REPORTED→DONE promotion. Validators are **additive-only**: they can add
failure reasons, never excuse uncovered acceptance, missing reports, or
missing receipts. No validator file = no-op (evidence + covers still gate).

## Contract

- **argv:** `[validator.py, task_id, tasks.jsonl_path, alog_path]`
- **stdout:** one JSON line: `{"pass": true|false, "reasons": ["..."]}`
- **exit code:** 0 always. Non-zero exit, unparseable stdout, or a verdict
  without `pass` = a `validator error:` entry (a broken judge fails the
  task loudly, never passes it silently).
- **timeout:** 60s, then error.
- **stdlib only.** Read the task + a-log, check what you need, print verdict.

## Minimal example

```python
#!/usr/bin/env python3
"""validators/a-deploy.py — did the deploy task really deploy? Stdlib only."""
import json, sys

_, tid, queue_path, alog_path = sys.argv
recs = {r["id"]: r for r in
        map(json.loads, open(queue_path).read().splitlines()) if r.strip()}
alog = [json.loads(l) for l in open(alog_path).read().splitlines()
        if l.strip()]
reasons = []
if not any("deploy-ok" in (e.get("detail", "") or "") for e in alog):
    reasons.append("no a-log line records deploy-ok")
print(json.dumps({"pass": not reasons, "reasons": reasons}))
```

## Rules

1. Judge the **log against the criteria**, not vibes: cite line numbers or
   missing acceptance indices in reasons.
2. Keep it dumb and mechanical (string matches, file existence, JSON shape).
   LLM judgment, if ever used, sits *above* this as a binary check — never
   inside the gate.
3. The agent that did the work may write the validator, but the validator
   runs from the recorded files at stoplight time — claimed-but-unlogged
   work fails here, mechanically.

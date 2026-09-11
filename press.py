#!/usr/bin/env python3
"""press.py — press-log writer/reader. Stdlib only.

Every keypress appends one (context -> decision -> outcome) row to
.atask/presses.jsonl. Rows carry shown+picked in the predictor's shape
(shown = the 10 key names in order, picked = index) so a sequence miner
can model start-to-end builds unmodified; context/outcome ride as extras.
"""
from __future__ import annotations
import json
import time
from datetime import date
from pathlib import Path

PRESSES = "presses.jsonl"
SHOWN = ["GO", "ZOOM", "DIG", "PICK", "OK", "NO", "TELL", "MORE", "STOP", "ACCEPT"]
# index i == key str((i + 1) % 10): position 0 is "1" ... position 9 is "0".


def key_index(key: str) -> int:
    return (int(key) - 1) % 10


def log(root: str | Path, session: str | None, key: str, arg,
        chain: str, context: dict, outcome: dict) -> dict:
    """Append one press row. Returns the row."""
    root = Path(root)
    row = {"ts": time.time(),
           "session": session or f"sess-{date.today().isoformat()}",
           "shown": SHOWN, "picked": key_index(key),
           "picked_text": SHOWN[key_index(key)], "arg": arg, "chain": chain,
           "context": context, "outcome": outcome}
    with open(root / PRESSES, "a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read(root: str | Path = ".") -> list[dict]:
    """All press rows. Missing file = no presses yet, never an error."""
    p = Path(root) / PRESSES
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

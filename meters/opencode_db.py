#!/usr/bin/env python3
"""opencode_db.py — L1 adapter: real token telemetry from OpenCode's own
session store. Stdlib only (sqlite3), read-only. This is NOT kernel code:
it consumes the world; the kernel only records what workers report.

Sources (all already on-box, no plugins, no daemons):
  session table  per-session totals: tokens_in/out/reasoning/cache + cost
  message table  per-message tokens+cost+model (data JSON)

Usage:
  python3 meters/opencode_db.py session ses_XXXX          # totals row
  python3 meters/opencode_db.py messages ses_XXXX [--since MIN]  # attribution
  python3 meters/opencode_db.py calibration ses_XXXX      # estimate-vs-actual
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

DEFAULT_DB = str(Path.home() / ".local" / "share" / "opencode" / "opencode.db")


def _db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def session_totals(session_id: str, path: str = DEFAULT_DB) -> dict:
    db = _db(path)
    r = db.execute("select id, title, model, agent, tokens_input, tokens_output,"
                   " tokens_reasoning, tokens_cache_read, tokens_cache_write,"
                   " cost from session where id=?", (session_id,)).fetchone()
    if not r:
        return {"session": session_id, "found": False}
    d = dict(r)
    try:
        d["model"] = json.loads(d.get("model") or "{}")
    except Exception:
        pass
    d["found"] = True
    d["token_source"] = "provider"
    return d


def message_usage(session_id: str, since_min: float = 0,
                  path: str = DEFAULT_DB) -> dict:
    """Sum assistant-message tokens inside the window (run attribution)."""
    db = _db(path)
    cutoff_ms = (time.time() - since_min * 60) * 1000 if since_min else 0
    rows = db.execute("select data from message where session_id=? and"
                      " time_created>=?", (session_id, cutoff_ms)).fetchall()
    tot = {"messages": 0, "in": 0, "out": 0, "reasoning": 0, "cost": 0.0}
    for (blob,) in rows:
        try:
            m = json.loads(blob)
        except Exception:
            continue
        if m.get("role") != "assistant":
            continue
        t = m.get("tokens", {}) or {}
        tot["messages"] += 1
        tot["in"] += int(t.get("input", 0))
        tot["out"] += int(t.get("output", 0))
        tot["reasoning"] += int(t.get("reasoning", 0))
        tot["cost"] = round(tot["cost"] + float(m.get("cost", 0) or 0), 6)
    tot["token_source"] = "provider"
    return tot


def calibration(session_id: str, path: str = DEFAULT_DB) -> dict:
    """chars/4 estimate over stored message text vs actual token counts."""
    db = _db(path)
    rows = db.execute("select data from message where session_id=?",
                      (session_id,)).fetchall()
    chars, actual_in, actual_out = 0, 0, 0
    for (blob,) in rows:
        chars += len(blob or "")
        try:
            m = json.loads(blob)
        except Exception:
            continue
        if m.get("role") == "assistant":
            t = m.get("tokens", {}) or {}
            actual_in += int(t.get("input", 0))
            actual_out += int(t.get("output", 0))
    est = chars / 4
    act = actual_in + actual_out
    return {"chars": chars, "estimated_tokens": round(est),
            "actual_tokens": act,
            "ratio_est_over_actual": round(est / act, 3) if act else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opencode_db.py")
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("session")
    p.add_argument("session_id")
    p = sub.add_parser("messages")
    p.add_argument("session_id")
    p.add_argument("--since", type=float, default=0)
    p = sub.add_parser("calibration")
    p.add_argument("session_id")
    a = ap.parse_args(argv)
    if a.cmd == "session":
        print(json.dumps(session_totals(a.session_id, a.db), indent=1)[:3000])
    elif a.cmd == "messages":
        print(json.dumps(message_usage(a.session_id, a.since, a.db), indent=1)[:3000])
    else:
        print(json.dumps(calibration(a.session_id, a.db), indent=1)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

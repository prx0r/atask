#!/usr/bin/env python3
"""driver.py — the autonomous pulse. Stdlib only, cron-friendly.

One pulse = one mechanical runtime iteration, then the agent (or cron)
does judgment work. The driver never judges quality; it only promotes
REPORTED -> DONE where stoplight() is already GO, lists the READY set as
orders, and appends one pulse line. Pure JSON on stdout, exit 0 always
(exit 2 = queue unreadable).

  python3 driver.py pulse [--dir .atask]            # one iteration
  python3 driver.py run [--dir .atask] [--max 50]   # pulse until halt-legal
  python3 driver.py boot [--dir .atask]             # init-if-missing + zoom

Cron (every 15 min, one repo):
  */15 * * * * cd /path/to/repo && python3 /path/to/atask/driver.py pulse >> .atask/driver.log 2>&1

Halt-legal = nothing READY, nothing NOGO, nothing still REPORTED.
Halt-legal means: propose next PROPOSED tasks with justification, or stop.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atask import goal_check, load, load_config, open_h, ready, set_status, stoplight
from budget import BudgetExceeded, FileBudget


def budget_state(root: Path) -> dict:
    """Live budget: budgets.json wins; atask.yaml caps seed it when unset."""
    b = FileBudget(root)
    cfg = load_config(root)
    if b.max_usd is None and isinstance(cfg.get("budget_usd"), (int, float)):
        b.set_caps(float(cfg["budget_usd"]), b.max_tokens)
    if b.max_tokens is None and isinstance(cfg.get("budget_tokens"), (int, float)):
        b.set_caps(b.max_usd, int(cfg["budget_tokens"]))
    return {"snapshot": b.snapshot(), "advertise": b.advertise()}


def zoom(root: Path) -> dict:
    root = Path(root)
    recs = load(root / "tasks.jsonl")
    done = [r for r in recs if r.get("status") == "DONE"]
    missing = [r for r in recs if r.get("status") not in ("DONE", "REJECTED")]
    gc = goal_check(root)
    return {"done": len(done), "missing": len(missing),
            "ready": len(ready(recs)),
            "open_h": len(open_h(root)),
            "goal_done": gc.get("goal_done", False) if gc.get("goal") else None}


def pulse(root: Path) -> dict:
    root = Path(root)
    t0 = time.monotonic()
    q = root / "tasks.jsonl"
    if not q.exists():
        return {"error": f"queue missing: {q} (run boot)",
                "halt_legal": False, "elapsed_s": 0.0}
    try:
        recs = load(q)
    except Exception as e:
        return {"error": f"queue unreadable: {e}"[:160],
                "halt_legal": False, "elapsed_s": 0.0}
    try:
        FileBudget(root).check("pulse")
    except BudgetExceeded as ex:
        return {"error": str(ex)[:200], "halt_legal": False,
                "budget": budget_state(root)["snapshot"],
                "elapsed_s": round(time.monotonic() - t0, 3),
                "close": "refused: budget exhausted — top up or revoke caps"}
    promoted, nogos = [], {}
    for r in recs:
        if r.get("status") != "REPORTED":
            continue
        sl = stoplight(r["id"], root)
        if sl["go"]:
            ok, _ = set_status(r["id"], "DONE", root)
            if ok:
                promoted.append(r["id"])
            else:
                nogos[r["id"]] = ["DONE gate refused"]
        else:
            nogos[r["id"]] = sl["missing"][:4]
    orders = [{"id": r.get("id"), "summary": (r.get("summary") or "")[:100],
               "acceptance": (r.get("acceptance") or [])[:3]}
              for r in ready(load(q))]
    still_reported = [r.get("id") for r in load(q)
                      if r.get("status") == "REPORTED"]
    halt_legal = not orders and not nogos and not still_reported
    gc = goal_check(root)
    oh = open_h(root)
    line = {"ts": time.time(), "promoted": promoted, "nogo": list(nogos),
            "ready": [o["id"] for o in orders], "halt_legal": halt_legal,
            "open_h": [h["id"] for h in oh],
            "goal_done": gc.get("goal_done") if gc.get("goal") else None}
    try:
        with open(root / "pulse.jsonl", "a") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        pass
    return {"promoted": promoted, "nogo": nogos, "orders": orders,
            "halt_legal": halt_legal,
            "open_h": [h["id"] for h in oh],
            "budget": budget_state(root),
            "goal": ({k: gc[k] for k in ("goal_done", "items") if k in gc}
                     if gc.get("goal") else {"goal": False}),
            "elapsed_s": round(time.monotonic() - t0, 3),
            "close": (f"pulse: promoted {len(promoted)}, {len(nogos)} nogo, "
                      f"{len(orders)} ready, {len(oh)} open human"
                      + (" — HALT-LEGAL" if halt_legal else ""))}


def boot(root: Path) -> dict:
    root = Path(root)
    created = False
    if not (root / "tasks.jsonl").exists():
        root.mkdir(parents=True, exist_ok=True)
        for sub in ("a-logs", "reports", "runs", "validators", "agents", "briefs"):
            (root / sub).mkdir(exist_ok=True)
        (root / "tasks.jsonl").write_text("")
        if not (root / "h-tasks.jsonl").exists():
            (root / "h-tasks.jsonl").write_text("")
        created = True
    from atask import seed_agents
    seeded = seed_agents(root)
    z = zoom(root)
    if z["open_h"]:
        nxt = f"answer {z['open_h']} open human tasks first"
    elif z["ready"]:
        nxt = f"drain {z['ready']} ready tasks"
    elif z["missing"]:
        nxt = "advance REPORTED/PROPOSED tasks toward DONE"
    else:
        nxt = "halt-legal: propose next tasks with justification"
    return {"booted": True, "created": created, "zoom": z, "next": nxt,
            "seeded_agents": seeded,
            "close": (f"runtime up. achieved {z['done']} / missing {z['missing']}. "
                      f"next: {nxt}")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="driver.py")
    ap.add_argument("--dir", default=".atask")
    ap.add_argument("--max", type=int, default=50)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pulse", "boot", "run"):
        p = sub.add_parser(name)
        p.add_argument("--dir", default=argparse.SUPPRESS)
        p.add_argument("--max", type=int, default=50)
    a = ap.parse_args(argv)
    root = Path(getattr(a, "dir", ".atask"))
    if a.cmd == "boot":
        print(json.dumps(boot(root), indent=1)[:2000])
        return 0
    if a.cmd == "pulse":
        print(json.dumps(pulse(root), indent=1)[:4000])
        return 0
    for _ in range(max(1, a.max)):
        rep = pulse(root)
        if rep.get("error") or rep.get("halt_legal"):
            print(json.dumps(rep, indent=1)[:4000])
            return 0
    print(json.dumps(rep, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

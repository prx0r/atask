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
from atask import goal_check, goal_get, load, open_h, ready, set_status, stoplight
from budget import BudgetExceeded, FileBudget
from events import emit as _emit, read as _eread


def spent_totals(root: Path) -> dict:
    """Spend/tokens from A-RUNs ONLY (sole accounting source); attempts is
    the lifecycle count on task records (includes still-open runs)."""
    usd, toks, tools, attempts = 0.0, 0, 0, 0
    try:
        from runs import read_runs as _read
        for r in _read(root):
            if r.get("reported_cost_usd") is not None:
                usd = round(usd + float(r["reported_cost_usd"]), 6)
            for k in ("input_tokens", "output_tokens"):
                if r.get(k) is not None:
                    toks += int(r[k])
    except Exception:
        pass
    try:
        for t in load(Path(root) / "tasks.jsonl"):
            attempts += int(t.get("attempts", 0) or 0)
    except Exception:
        pass
    return {"spent_usd": usd, "spent_tokens": toks, "tool_calls": tools,
            "attempts": attempts}


def resources(root: Path, last_failures: list | None = None) -> dict:
    """BATS-style block: used vs caps (context for the agent, never refusal).
    Caps live on the goal as declared context; missing cap = unmetered."""
    root = Path(root)
    spent = spent_totals(root)
    goal = goal_get(root) or {}
    block: dict = {"spent_usd": spent["spent_usd"],
                   "spent_tokens": spent["spent_tokens"],
                   "tool_calls": spent["tool_calls"],
                   "attempts": spent["attempts"],
                   "last_validator": last_failures or "ok"}
    for used_k, cap_k in (("spent_usd", "budget_usd"),
                          ("spent_tokens", "token_budget"),
                          ("tool_calls", "tool_budget")):
        cap = goal.get(cap_k)
        if isinstance(cap, (int, float)) and cap > 0:
            block[cap_k] = cap
            block[used_k.replace("spent_", "remaining_").replace("tool_calls", "remaining_tools")] = \
                round(cap - spent[used_k], 6)
    ddl = goal.get("deadline_min")
    if isinstance(ddl, (int, float)) and ddl > 0:
        age_min = round((time.time() - goal.get("ts", time.time())) / 60, 2)
        block["elapsed_min"] = age_min
        block["remaining_min"] = round(ddl - age_min, 2)
    return block


def zoom(root: Path) -> dict:
    root = Path(root)
    recs = load(root / "tasks.jsonl")
    done = [r for r in recs if r.get("status") == "DONE"]
    missing = [r for r in recs if r.get("status") not in ("DONE", "REJECTED")]
    gc = goal_check(root)
    last_fail = "ok"
    try:
        pl = root / "pulse.jsonl"
        if pl.exists():
            lines = pl.read_text().splitlines()
            if lines:
                ng = json.loads(lines[-1]).get("nogo", [])
                if ng:
                    last_fail = [f"{t}" for t in ng][:3]
    except Exception:
        pass
    return {"done": len(done), "missing": len(missing),
            "ready": len(ready(recs)),
            "open_h": len(open_h(root)),
            "goal_done": gc.get("goal_done", False) if gc.get("goal") else None,
            "resources": resources(root, last_fail)}


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
                "elapsed_s": round(time.monotonic() - t0, 3),
                "close": "refused: budget exhausted — raise caps or stop"}
    promoted, nogos = [], {}
    for r in recs:
        if r.get("status") != "REPORTED":
            continue
        sl = stoplight(r["id"], root)
        if sl["go"]:
            ok, _ = set_status(r["id"], "DONE", root)
            if ok:
                promoted.append(r["id"])
                _emit(root, "validator.passed", task_id=r["id"])
            else:
                nogos[r["id"]] = ["DONE gate refused"]
        else:
            nogos[r["id"]] = sl["missing"][:4]
            _emit(root, "validator.failed", task_id=r["id"],
                  reasons=sl["missing"][:4])
    recs = load(q)  # refresh after promotions (single re-read)
    from runs import task_run_stats as _stats
    last_fail: dict = {}
    for ev in _eread(root, "validator.failed"):
        rs = ev.get("reasons") or []
        last_fail[ev.get("task_id", "")] = (rs[0] if rs else "fail")[:120]
    orders = []
    for r in ready(recs):
        st = _stats(root, r.get("id"))
        orders.append({"id": r.get("id"),
                       "summary": (r.get("summary") or "")[:100],
                       "acceptance": (r.get("acceptance") or [])[:3],
                       "attempts": st["attempts"],
                       "tokens": {"in": st["input_tokens"],
                                  "out": st["output_tokens"],
                                  "known": st["tokens_known"]},
                       "cost_usd": st["cost_usd"],
                       "last_validator": last_fail.get(r.get("id"), "ok")})
    still_reported = [r.get("id") for r in recs
                      if r.get("status") == "REPORTED"]
    halt_legal = not orders and not nogos and not still_reported
    gc = goal_check(root)
    oh = open_h(root)
    if gc.get("goal_done") and not _eread(root, "goal.done"):
        spent = spent_totals(root)
        _emit(root, "goal.done",
              acceptance=len(gc.get("items", [])),
              spent_usd=spent["spent_usd"], attempts=spent["attempts"])
    fails = [f"{tid}: {msgs[0]}"[:120] for tid, msgs in nogos.items()][:3]
    res = resources(root, fails or "ok")
    line = {"ts": time.time(), "promoted": promoted, "nogo": list(nogos),
            "ready": [o["id"] for o in orders], "halt_legal": halt_legal,
            "open_h": [h["id"] for h in oh],
            "goal_done": gc.get("goal_done") if gc.get("goal") else None,
            "spent_usd": res["spent_usd"]}
    try:
        with open(root / "pulse.jsonl", "a") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        pass
    return {"promoted": promoted, "nogo": nogos, "orders": orders,
            "halt_legal": halt_legal,
            "open_h": [h["id"] for h in oh],
            "spent": {"spent_usd": res["spent_usd"],
                      "spent_tokens": res["spent_tokens"]},
            "resources": res,
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
        for sub in ("a-logs", "reports", "runs", "validators"):
            (root / sub).mkdir(exist_ok=True)
        (root / "tasks.jsonl").write_text("")
        if not (root / "h-tasks.jsonl").exists():
            (root / "h-tasks.jsonl").write_text("")
        created = True
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
            "close": (f"runtime up. achieved {z['done']} / missing {z['missing']}. "
                      f"next: {nxt}")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="driver.py")
    ap.add_argument("--dir", default=".atask")
    ap.add_argument("--quiet", "-q", action="store_true")
    ap.add_argument("--max", type=int, default=50)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pulse", "boot", "run"):
        p = sub.add_parser(name)
        p.add_argument("--dir", default=argparse.SUPPRESS)
        p.add_argument("--quiet", "-q", action="store_true",
                       default=argparse.SUPPRESS)
        p.add_argument("--max", type=int, default=50)
    a = ap.parse_args(argv)
    root = Path(getattr(a, "dir", ".atask"))
    Q = bool(getattr(a, "quiet", False))
    if a.cmd == "boot":
        rep = boot(root)
        print(rep["close"] if Q else json.dumps(rep, indent=1)[:2000])
        return 0
    if a.cmd == "pulse":
        rep = pulse(root)
        print(rep.get("close", rep.get("error", "")) if Q
              else json.dumps(rep, indent=1)[:4000])
        return 0
    for _ in range(max(1, a.max)):
        rep = pulse(root)
        if rep.get("error") or rep.get("halt_legal"):
            print(rep.get("close", rep.get("error", "")) if Q
                  else json.dumps(rep, indent=1)[:4000])
            return 0
    print(rep.get("close", rep.get("error", "")) if Q
          else json.dumps(rep, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

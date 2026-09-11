#!/usr/bin/env python3
"""instrument.py — the 10-key control harness over any .atask/ dir. Stdlib only.

Two modes (recorded in every row): IDLE (no open questions — digits drive
the agent: 0=GO, 1=orders, 2=status, 3=blockers, 7=correction, 8=goal,
9=halt) and QUESTION (0=accept recommendation, 1-7=pick, 5/6=approve/deny,
7=text answer, 8=expand, 9=halt). 0 means "I accept your judgment."

Every press logs a rich row: STATE (goal/stm/queue position) + QUESTION
(type/options/recommendation) + CHOICE + CONTEXT (elapsed/spent/progress).
`digest` closes a session with its OUTCOME. That join is the
preference-learning dataset. Nothing here raises past run().

  python3 instrument.py press 041 --dir .atask --session build1 [--text "7=..."]
  python3 instrument.py presses --dir .atask [--session build1]
  python3 instrument.py digest --dir .atask --session build1
"""
from __future__ import annotations
import json
import re as _re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain as _chain
import press as _press
from atask import answer, goal_check, load, open_h, ready, stoplight
from driver import spent_totals, zoom as _zoom

HALT = "HALT.json"
CORR = "corrections.jsonl"

# TELL-guard: key-shaped payloads never enter the queue from the dash.
_SECRET_RES = [
    _re.compile(r"sk-[A-Za-z0-9]{12,}"),
    _re.compile(r"ghp_[A-Za-z0-9]{36}"),
    _re.compile(r"xox[bap]-[A-Za-z0-9-]+"),
    _re.compile(r"AKIA[0-9A-Z]{16}"),
    _re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    _re.compile(r"\d{6,12}:AA[A-Za-z0-9_-]{33}"),
    _re.compile(r"cfat_[A-Za-z0-9_-]{10,}"),
    _re.compile(r"apify_api_[A-Za-z0-9]+"),
    _re.compile(r"(?i)\b(api[_-]?key|api[_-]?token|access_token|secret|mnemonic|bearer|private_key|password|key)\b\s*[:=]\s*\S{8,}"),
]

READONLY = {"2", "3", "8"}


def _halted(root: Path) -> bool:
    return (root / HALT).exists()


def _session_elapsed(root: Path, session: str) -> float:
    if not session:
        return 0.0
    starts = [r["ts"] for r in _press.read(root) if r.get("session") == session]
    return round((time.time() - min(starts)) / 60, 2) if starts else 0.0


def _goal_progress(root: Path):
    gc = goal_check(root)
    if not gc.get("goal"):
        return None
    items = gc.get("items", [])
    if not items:
        return None
    return round(sum(len(x["done"]) for x in items)
                 / max(1, sum(len(x["mapped"]) for x in items)), 3)


def _question_block(opens: list[dict]) -> dict | None:
    if not opens:
        return None
    h = opens[0]
    return {"hid": h["id"], "task": h.get("task"), "kind": h.get("kind"),
            "reason": (h.get("need") or "")[:300], "options": h.get("options", []),
            "recommended": (h.get("recommendation") or "")[:200],
            "n_open": len(opens)}


def _context(root: Path, session: str) -> dict:
    opens = open_h(root)
    spent = spent_totals(root)
    return {"mode": "question" if opens else "idle",
            "question": _question_block(opens),
            "context": {"elapsed_min": _session_elapsed(root, session),
                        "spent_usd": spent["spent_usd"],
                        "spent_tokens": spent["spent_tokens"],
                        "goal_progress": _goal_progress(root),
                        "ready": [r["id"] for r in ready(load(root / "tasks.jsonl"))][:8]},
            "halted": _halted(root)}


def _refuse(key, arg, why="halted — press 9 to resume"):
    return {"key": key, "arg": arg, "ok": False, "action": "refused",
            "detail": {}, "close": why}


def _act(key: str, arg, root: Path, session: str, payloads: dict) -> dict:
    ok, action, detail, close = True, "", {}, ""
    recs = load(root / "tasks.jsonl")
    opens = open_h(root)
    if key == "9":
        hp = root / HALT
        if hp.exists():
            hp.unlink()
            action, close = "resume", "resumed — halt lifted"
        else:
            hp.write_text(json.dumps({"ts": time.time(), "session": session}) + "\n")
            action, close = "halt", "halted — packet pending; 2,3,8 still work; 9 resumes"
    elif key in READONLY:
        if key == "2":
            z = _zoom(root)
            spent = spent_totals(root)
            action = "zoom"
            detail = {**z, **spent}
            close = (f"achieved {z['done']} / missing {z['missing']}; "
                     f"ready {z['ready']}; open {z['open_h']}; "
                     f"goal {z['goal_done']}; spent ${spent['spent_usd']}")
        elif key == "3":
            nogos = {}
            for r in recs:
                if r.get("status") == "REPORTED":
                    sl = stoplight(r["id"], root)
                    if not sl["go"]:
                        nogos[r["id"]] = sl["missing"][:2]
            action = "dig"
            detail = {"open": [(h["id"], h.get("kind"), h.get("need", "")[:100])
                               for h in opens[:3]], "nogo": nogos}
            first = detail["open"][0][2] if detail["open"] else (
                next(iter(nogos.values()))[0] if nogos else "no open blockers — queue is the finding")
            close = f"obvious answer: {first}"[:200]
        else:  # 8 MORE
            if opens:
                h = opens[0]
                action, detail = "expand", {"hid": h["id"], "kind": h.get("kind"),
                                            "need": h.get("need", "")[:500],
                                            "options": h.get("options", []),
                                            "recommended": h.get("recommendation", "")[:300],
                                            "task": h.get("task")}
                close = f"expanded {h['id']} [{h.get('kind')}]: " + (h.get("need", "")[:200])
            else:
                gc = goal_check(root)
                action, detail = "goal", {"goal_done": gc.get("goal_done"),
                                          "statement": gc.get("statement", "")[:200]}
                close = ("goal done" if gc.get("goal_done")
                         else f"goal open: {gc.get('statement', 'no goal')[:100]}")
    elif _halted(root):
        return _refuse(key, arg)
    elif key == "0":
        if opens:
            h = opens[0]
            rec = (h.get("recommendation") or "").strip()
            if h.get("options") and rec in (h.get("options") or []):
                answer(root, h["id"], f"accepted recommendation: {rec}")
                action, detail = "accept", {"hid": h["id"], "pick": rec}
                close = f"accepted {h['id']}: {rec}"[:160]
            else:
                answer(root, h["id"],
                       f"accepted via key 0{': ' + rec if rec else ''}"[:500])
                action, detail = "accept", {"hid": h["id"]}
                close = f"accepted {h['id']}"
        else:
            rs = ready(recs)
            action, detail = "drain-ordered", {"ready": [r["id"] for r in rs]}
            close = (f"ready {len(rs)}: {', '.join(detail['ready'][:4])}"
                     if rs else "nothing ready — halt-legal")
    elif key == "1":
        rs = ready(recs)
        action, detail = "drain-ordered", {"ready": [r["id"] for r in rs]}
        close = (f"ready {len(rs)}: {', '.join(detail['ready'][:4])}"
                 f"{'…' if len(rs) > 4 else ''}; agent working"
                 if rs else "nothing ready — halt-legal")
    elif key in ("4", "5", "6", "7"):
        if key == "4":
            cand = next((o for o in opens if o.get("options")), None)
            if cand is None:
                ok, action, close = False, "no-choice", "no open question with options"
            else:
                opts = cand.get("options") or []
                if arg is None or not 1 <= arg <= min(7, len(opts)):
                    ok, action, close = False, "bad-pick", f"option 1-{min(7, len(opts))} required"
                else:
                    answer(root, cand["id"], f"picked: {opts[arg - 1]}")
                    action, detail = "pick", {"hid": cand["id"], "pick": opts[arg - 1]}
                    close = f"answered {cand['id']} with option {arg}"
        elif key == "5":
            if not opens:
                ok, action, close = False, "nothing", "nothing to approve"
            else:
                answer(root, opens[0]["id"], "approved via key 5")
                action, detail = "approve", {"hid": opens[0]["id"]}
                close = f"approved {opens[0]['id']}"
        elif key == "6":
            if not opens:
                ok, action, close = False, "nothing", "nothing to deny"
            else:
                answer(root, opens[0]["id"], "denied via key 6", status="denied")
                action, detail = "deny", {"hid": opens[0]["id"]}
                close = f"denied {opens[0]['id']}, replanning"
        else:  # 7 TELL (answer) or FIX (correction when idle)
            text = (payloads or {}).get("7", "")
            hit = next((rx for rx in _SECRET_RES if rx.search(text or "")), None)
            if not text:
                ok, action, close = False, "needs-text", "TELL needs text (key 7 opens capture)"
            elif hit:
                ok, action, close = False, "secret-refused", (
                    "key-shaped input refused — secrets travel server-side only")
            elif opens:
                answer(root, opens[0]["id"], text[:2000])
                action, detail = "tell", {"hid": opens[0]["id"]}
                close = f"delivered to {opens[0]['id']}"
            else:
                cp = root / CORR
                cid = f"c-{int(time.time()) % 100000:05d}"
                with open(cp, "a") as f:
                    f.write(json.dumps({"id": cid, "ts": time.time(),
                                        "session": session, "text": text[:1000]},
                                       sort_keys=True) + "\n")
                action, detail = "fix", {"cid": cid}
                close = f"correction {cid} logged"
    return {"key": key, "arg": arg, "ok": ok, "action": action,
            "detail": detail, "close": close}


def run(chain_str: str, session: str | None = None, root: str | Path = ".atask",
        payloads: dict | None = None) -> dict:
    """Parse + dispatch a chain; log every rich press row with its outcome."""
    import time as _t
    t0 = _t.monotonic()
    root = Path(root)
    actions = _chain.parse(chain_str)
    results = []
    for a in actions:
        ctx = _context(root, session or "")
        res = _act(a["key"], a["arg"], root, session or "", payloads or {})
        _press.log(root, session, a["key"], a["arg"], chain_str, ctx,
                   {"ok": res["ok"], "action": res["action"],
                    "choice": a["arg"] if a["arg"] is not None else a["key"]})
        results.append(res)
    return {"session": session, "chain": chain_str,
            "described": _chain.describe(actions),
            "results": results,
            "elapsed_s": round(_t.monotonic() - t0, 3),
            "close": " | ".join(r["close"] for r in results)}


def digest(root: str | Path, session: str) -> dict:
    """Close a session with its OUTCOME row (the learning join key)."""
    root = Path(root)
    rows = [r for r in _press.read(root) if r.get("session") == session]
    gc = goal_check(root)
    spent = spent_totals(root)
    by_h = {}
    try:
        from atask import hload as _hload
        for h in _hload(root):
            by_h[h.get("status", "open")] = by_h.get(h.get("status", "open"), 0) + 1
    except Exception:
        pass
    out = {"type": "digest", "session": session, "ts": time.time(),
           "outcome": {"goal_done": gc.get("goal_done"),
                       "spent_usd": spent["spent_usd"],
                       "spent_tokens": spent["spent_tokens"],
                       "presses": len(rows),
                       "h_tasks": by_h,
                       "elapsed_min": round((time.time() - min(
                           [r["ts"] for r in rows])) / 60, 2) if rows else 0.0}}
    with open(root / "presses.jsonl", "a") as f:
        f.write(json.dumps(out, sort_keys=True) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse as _ap
    ap = _ap.ArgumentParser(prog="instrument.py")
    ap.add_argument("--dir", default=".atask")
    ap.add_argument("--session", default=None)
    ap.add_argument("--text", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("press", "presses", "digest"):
        p = sub.add_parser(name)
        p.add_argument("--dir", default=_ap.SUPPRESS)
        p.add_argument("--session", default=_ap.SUPPRESS)
        p.add_argument("--text", default=_ap.SUPPRESS)
    sub.choices["press"].add_argument("chain")
    a = ap.parse_args(argv)
    root = Path(getattr(a, "dir", ".atask"))
    session = getattr(a, "session", None)
    if a.cmd == "presses":
        rows = _press.read(root)
        if session:
            rows = [r for r in rows if r.get("session") == session]
        for row in rows:
            print(json.dumps(row, sort_keys=True))
        return 0
    if a.cmd == "digest":
        if not session:
            print("digest needs --session")
            return 1
        print(json.dumps(digest(root, session), indent=1)[:2000])
        return 0
    payloads: dict = {}
    for part in (getattr(a, "text", "") or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            payloads[k.strip()] = v
    try:
        print(json.dumps(run(a.chain, session, root, payloads), indent=1)[:4000])
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)[:200]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""instrument.py — the 10-key control harness over any .atask/ dir. Stdlib only.

Digits are verbs; the human answers in numbers because the harness limits
what the agent can ever need: go / status / dig / pick / approve / deny /
tell / goal / fix / stop. Every press logs a (context -> decision ->
outcome) row for sequence modeling. Read-only keys (2, 3, 8) work under
halt; executing keys refuse while HALT.json exists; 0 toggles the halt.
Nothing here raises past run(): a failed key is a failed outcome row.

  python3 instrument.py press 294 [--dir .atask] [--session S] [--text "7=...;9=..."]
  python3 instrument.py presses [--dir .atask]   # raw press log (the training data)
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
from atask import (alog, answer, goal_check, load, open_h, ready, stoplight)
from budget import FileBudget
from driver import zoom as _zoom

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


def _context(root: Path) -> dict:
    return {"open_h": [h["id"] for h in open_h(root)][:8],
            "ready": [r["id"] for r in ready(load(root / "tasks.jsonl"))][:8],
            "halted": _halted(root)}


def _act(key: str, arg, root: Path, session: str, payloads: dict) -> dict:
    ok, action, detail, close = True, "", {}, ""
    recs = load(root / "tasks.jsonl")
    opens = open_h(root)
    if key == "0":
        hp = root / HALT
        if hp.exists():
            hp.unlink()
            action, close = "resume", "resumed — halt lifted"
        else:
            hp.write_text(json.dumps({"ts": time.time(), "session": session}) + "\n")
            action, close = "halt", "halted — packet pending; 2,3,8 still work; 0 resumes"
    elif key == "2":
        z = _zoom(root)
        b = FileBudget(root).snapshot()
        action = "zoom"
        detail = z
        close = (f"achieved {z['done']} / missing {z['missing']}; "
                 f"ready {z['ready']}; open_h {z['open_h']}; "
                 f"goal {z['goal_done']}; "
                 f"budget {'exhausted' if b['exhausted'] else 'ok'}")
    elif key == "3":
        nogos = {}
        for r in recs:
            if r.get("status") == "REPORTED":
                sl = stoplight(r["id"], root)
                if not sl["go"]:
                    nogos[r["id"]] = sl["missing"][:2]
        action = "dig"
        detail = {"open_h": [(h["id"], h.get("need", "")[:100]) for h in opens[:3]],
                  "nogo": nogos}
        first = detail["open_h"][0][1] if detail["open_h"] else (
            next(iter(nogos.values()))[0] if nogos else "no open blockers — queue is the finding")
        close = f"obvious answer: {first}"[:200]
    elif key == "1":
        if _halted(root):
            return {"key": key, "arg": arg, "ok": False, "action": "refused",
                    "detail": {}, "close": "halted — press 0 to resume"}
        rs = ready(recs)
        action = "drain-ordered"
        detail = {"ready": [r["id"] for r in rs]}
        close = (f"ready {len(rs)}: {', '.join(detail['ready'][:4])}"
                 f"{'…' if len(rs) > 4 else ''}; agent working; H surfaces on block"
                 if rs else "nothing ready — halt-legal")
    elif key == "8":
        gc = goal_check(root)
        action = "goal"
        detail = {"goal_done": gc.get("goal_done"),
                  "items": [(x["index"], len(x["done"]), len(x["mapped"]))
                            for x in gc.get("items", [])]}
        close = ("goal done" if gc.get("goal_done")
                 else f"goal open: {gc.get('statement', 'no goal')[:100]}")
    elif key in ("4", "5", "6", "7"):
        if _halted(root):
            return {"key": key, "arg": arg, "ok": False, "action": "refused",
                    "detail": {}, "close": "halted — press 0 to resume"}
        if key == "4":
            cand = next((o for o in opens if o.get("options")), None)
            if cand is None:
                ok, action, close = False, "no-choice", "no open task with options to pick from"
            else:
                opts = cand.get("options") or []
                if arg is None or arg >= len(opts):
                    ok, action, close = False, "bad-pick", f"option 0-{len(opts)-1} required"
                else:
                    answer(root, cand["id"], f"picked: {opts[arg]}")
                    action, detail = "pick", {"hid": cand["id"], "pick": opts[arg]}
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
        else:  # 7 TELL
            text = (payloads or {}).get("7", "")
            hit = next((rx for rx in _SECRET_RES if rx.search(text or "")), None)
            if not text:
                ok, action, close = False, "needs-text", "TELL needs text (key 7 opens capture)"
            elif hit:
                ok, action, close = False, "secret-refused", (
                    "key-shaped input refused — secrets travel server-side only")
            elif not opens:
                ok, action, close = False, "nothing", "no open task to tell"
            else:
                answer(root, opens[0]["id"], text[:2000])
                action, detail = "tell", {"hid": opens[0]["id"]}
                close = f"delivered to {opens[0]['id']}"
    elif key == "9":
        if _halted(root):
            return {"key": key, "arg": arg, "ok": False, "action": "refused",
                    "detail": {}, "close": "halted — press 0 to resume"}
        text = (payloads or {}).get("9", "")
        cp = root / CORR
        cid = f"c-{int(time.time()) % 100000:05d}"
        with open(cp, "a") as f:
            f.write(json.dumps({"id": cid, "ts": time.time(), "session": session,
                                "text": text[:1000] or None,
                                "auto_context": _context(root)}, sort_keys=True) + "\n")
        action, detail = "fix", {"cid": cid}
        close = f"correction {cid} logged"
    return {"key": key, "arg": arg, "ok": ok, "action": action,
            "detail": detail, "close": close}


def run(chain_str: str, session: str | None = None, root: str | Path = ".atask",
        payloads: dict | None = None) -> dict:
    """Parse + dispatch a chain; log every press with its outcome."""
    import time as _t
    t0 = _t.monotonic()
    root = Path(root)
    actions = _chain.parse(chain_str)
    results = []
    for a in actions:
        ctx = _context(root)
        res = _act(a["key"], a["arg"], root, session or "", payloads or {})
        _press.log(root, session, a["key"], a["arg"], chain_str, ctx,
                   {"ok": res["ok"], "action": res["action"]})
        results.append(res)
    return {"session": session, "chain": chain_str,
            "described": _chain.describe(actions),
            "results": results,
            "elapsed_s": round(_t.monotonic() - t0, 3),
            "close": " | ".join(r["close"] for r in results)}


def main(argv: list[str] | None = None) -> int:
    import argparse as _ap
    ap = _ap.ArgumentParser(prog="instrument.py")
    ap.add_argument("--dir", default=".atask")
    ap.add_argument("--session", default=None)
    ap.add_argument("--text", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_press = sub.add_parser("press")
    p_press.add_argument("chain")
    p_press.add_argument("--dir", default=_ap.SUPPRESS)
    p_press.add_argument("--session", default=_ap.SUPPRESS)
    p_press.add_argument("--text", default=_ap.SUPPRESS)
    p_show = sub.add_parser("presses")
    p_show.add_argument("--dir", default=_ap.SUPPRESS)
    a = ap.parse_args(argv)
    root = Path(getattr(a, "dir", ".atask"))
    if a.cmd == "presses":
        for row in _press.read(root):
            print(json.dumps(row, sort_keys=True))
        return 0
    payloads: dict = {}
    for part in (getattr(a, "text", "") or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            payloads[k.strip()] = v
    try:
        print(json.dumps(run(a.chain, getattr(a, "session", None), root, payloads),
                         indent=1)[:4000])
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)[:200]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

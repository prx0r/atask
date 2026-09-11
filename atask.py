#!/usr/bin/env python3
"""atask.py — minimal A-task queue core. Stdlib only, zero dependencies.

One JSONL queue + per-task a-logs + report files + content-addressed
receipts. No daemon, no network, no config. State lives in --dir
(default .atask/ under cwd) so ANY repo adopts it by running init.

Record shape (same as ATASK.md, portable across harnesses):
  {id, tier, summary, acceptance[], evidence_required[], blocked_by[],
   status, report_ref, validation_ref}

Lifecycle: PROPOSED -> JUSTIFIED -> EXECUTING -> REPORTED -> DONE
(PAUSED = blocked on human/money mid-task; REJECTED carries reasons and
re-enters at PROPOSED, never straight to DONE.)

READY = status in (JUSTIFIED, EXECUTING) AND every blocked_by id is DONE.
DONE requires report_ref file + resolvable sha256: validation_ref.
No receipt, no DONE — forever, no exceptions.

Usage:
  python3 atask.py init [--dir .atask]
  python3 atask.py add --id a-slug --summary "..." --accept "check 1" [--blocked-by a-other]
  python3 atask.py list [--status READY] [--dir .atask]
  python3 atask.py ready [--dir .atask]
  python3 atask.py justify|execute|report --id a-slug
  python3 atask.py log --id a-slug --covers 0 --evidence "command:pytest tests/ -q"
  python3 atask.py stoplight --id a-slug
  python3 atask.py done --id a-slug --report reports/a-slug.md --receipt sha256:...
  python3 atask.py verify [--dir .atask]
  python3 atask.py goal set --statement "..." --accept "end 1" [--accept "end 2"]
  python3 atask.py goal check
  python3 atask.py spawn --parent a-slug --id a-sub --summary "..." --accept "..."
  python3 atask.py escalate --id a-slug --need "API key with scope X" [--predict '{"k":1}']
  python3 atask.py answer --hid h-abc123 --answer "..."
"""
from __future__ import annotations
import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

STATUS = ("PROPOSED", "JUSTIFIED", "EXECUTING", "PAUSED", "REPORTED",
          "REJECTED", "DONE")
READY_STATUS = ("JUSTIFIED", "EXECUTING")
REQUIRED = ("id", "tier", "summary", "status")
DEFAULT_DIR = ".atask"


def d(p: str | Path, *parts: str) -> Path:
    return Path(p, *parts)


def load(queue: Path) -> list[dict]:
    queue = Path(queue)
    if not queue.exists():
        return []
    out = []
    for line in queue.read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def save_all(recs: list[dict], queue: Path) -> None:
    queue = Path(queue)
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))


def ready(recs: list[dict]) -> list[dict]:
    done = {r.get("id") for r in recs if r.get("status") == "DONE"}
    return [r for r in recs
            if r.get("status") in READY_STATUS
            and all(b in done for b in (r.get("blocked_by") or []))]


def resolve(ref: str, base: Path) -> Path | None:
    """sha256: URIs map to runs/sha256_<hash>.json; plain paths resolve directly."""
    base = Path(base)
    if ref.startswith("sha256:"):
        name = ref.replace(":", "_") + ".json"
        for c in (base / "runs" / name, base.parent / "runs" / name, Path("runs") / name):
            if c.exists():
                return c
        return None
    for c in (Path(ref), base / ref, base.parent / ref):
        if c.exists() and c.is_file():
            return c
    return None


def alog_path(tid: str, root: Path) -> Path:
    return Path(root) / "a-logs" / f"{tid}.jsonl"


def alog(tid: str, action: str, covers: list[int], root: Path,
         detail: str = "", evidence: str = "") -> dict:
    """Append one a-log line. evidence is "" or "command:<cmd>" (re-executed
    by stoplight) — lines without evidence count covers on trust."""
    p = alog_path(tid, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.time(), "task": tid, "action": action,
             "covers": sorted(set(int(c) for c in covers)),
             "detail": detail[:500], "evidence": evidence[:500]}
    with open(p, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def alog_read(tid: str, root: Path) -> list[dict]:
    p = alog_path(tid, root)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def check_evidence(ev: str, cwd: Path) -> str | None:
    """Re-execute one evidence claim. None = holds, else reason."""
    if not ev:
        return None
    if ev.startswith("command:"):
        cmd = ev[len("command:"):].strip()
        try:
            r = subprocess.run(shlex.split(cmd), capture_output=True,
                               text=True, timeout=120, cwd=cwd)
        except Exception as e:
            return f"evidence command failed to run: {cmd[:80]} ({e})"[:120]
        if r.returncode != 0:
            tail = ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1][:80]
            return f"evidence command red (exit {r.returncode}): {cmd[:60]} :: {tail}"
    return None


def stoplight(tid: str, root: Path) -> dict:
    """GO iff every acceptance index is a-log covered AND every evidence
    claim re-executes green AND report file exists AND validation_ref set."""
    root = Path(root)
    recs = {r.get("id"): r for r in load(root / "tasks.jsonl")}
    if tid not in recs:
        return {"go": False, "missing": ["unknown task id"]}
    rec = recs[tid]
    covered: set[int] = set()
    missing: list[str] = []
    for n, e in enumerate(alog_read(tid, root)):
        covered.update(e.get("covers", []))
        bad = check_evidence(e.get("evidence", ""), root.parent)
        if bad:
            missing.append(f"a-log line {n}: {bad}")
    missing = [f"acceptance[{i}] uncovered: {a[:60]}"
               for i, a in enumerate(rec.get("acceptance", []) or [])
               if i not in covered] + missing
    rr = rec.get("report_ref", "")
    if rr and resolve(rr, root) is None:
        missing.append("report_ref file missing")
    if not rec.get("validation_ref"):
        missing.append("validation_ref empty (no receipt)")
    missing += run_validator(tid, root)
    return {"go": not missing, "missing": missing, "covered": sorted(covered),
            "acceptance": len(rec.get("acceptance", []) or [])}


def done_gate(rec: dict, root: Path) -> list[str]:
    """Refusals for a DONE transition. Empty = may promote."""
    root = Path(root)
    errs = []
    rr = rec.get("report_ref", "")
    if not rr:
        errs.append("DONE requires report_ref (no report, no DONE)")
    elif resolve(rr, root) is None:
        errs.append(f"report_ref unresolvable: {rr}"[:120])
    vr = rec.get("validation_ref", "")
    if not vr:
        errs.append("DONE requires validation_ref (no receipt, no DONE)")
    elif not vr.startswith("sha256:") or resolve(vr, root) is None:
        errs.append(f"validation_ref unresolvable: {vr}"[:120])
    return errs


def set_status(tid: str, status: str, root: Path, **fields) -> tuple[bool, str]:
    root = Path(root)
    if status not in STATUS:
        return False, f"bad status {status!r}"
    q = root / "tasks.jsonl"
    recs = load(q)
    by_id = {r.get("id"): r for r in recs}
    if tid not in by_id:
        return False, "unknown task id"
    rec = by_id[tid]
    for b in (rec.get("blocked_by") or []):
        if b not in by_id:
            return False, f"dangling blocked_by {b!r}"
    rec.update({k: v for k, v in fields.items() if v is not None})
    if status == "DONE":
        errs = done_gate(rec, root)
        if errs:
            return False, "transition rejected: " + "; ".join(errs)
    rec["status"] = status
    save_all(recs, q)
    return True, f"{tid} -> {status}"


# ------------------------------------------------------------------
# A-goal: one active end-state; tasks map to its acceptance indices via
# covers_goal. goal_done is DERIVED (all mapped tasks DONE), never stored,
# so it cannot drift from the queue.


def goal_set(root: Path, statement: str, acceptance: list[str]) -> dict:
    root = Path(root)
    g = {"id": "g-main", "statement": statement,
         "acceptance": list(acceptance), "ts": time.time()}
    (root / "goal.json").write_text(json.dumps(g, indent=1, sort_keys=True))
    return g


def goal_get(root: Path) -> dict | None:
    p = Path(root) / "goal.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def goal_check(root: Path) -> dict:
    """Per acceptance index: which tasks map to it, which are DONE."""
    root = Path(root)
    goal = goal_get(root)
    if goal is None:
        return {"goal": False, "missing": ["no goal.json (run goal set)"]}
    recs = {r.get("id"): r for r in load(root / "tasks.jsonl")}
    items = []
    for i, a in enumerate(goal.get("acceptance", [])):
        mapped = [tid for tid, r in recs.items()
                  if i in (r.get("covers_goal") or [])
                  and r.get("status") != "REJECTED"]
        done = [tid for tid in mapped if recs[tid].get("status") == "DONE"]
        items.append({"index": i, "acceptance": a[:100],
                      "mapped": mapped, "done": done,
                      "covered": bool(mapped) and len(mapped) == len(done)})
    return {"goal": True, "statement": goal.get("statement", "")[:200],
            "items": items,
            "goal_done": bool(items) and all(x["covered"] for x in items)}


# ------------------------------------------------------------------
# spawn: branch deeper. The child inherits the parent's blockers (it does
# the parent's sub-work, so it waits on what the parent waited on); the
# parent then blocks on the child (children finish first). Depth is
# recorded; MAX_DEPTH refuses runaway recursion mechanically.


MAX_DEPTH = 8


def spawn(root: Path, parent: str, tid: str, summary: str,
          acceptance: list[str], covers_goal: list[int] | None = None) -> tuple[bool, str]:
    root = Path(root)
    q = root / "tasks.jsonl"
    recs = load(q)
    by_id = {r.get("id"): r for r in recs}
    if any(r.get("id") == tid for r in recs):
        return False, f"duplicate id: {tid}"
    if parent not in by_id:
        return False, f"unknown parent: {parent}"
    par = by_id[parent]
    if par.get("status") == "DONE":
        return False, f"parent already DONE: {parent}"
    depth = int(par.get("depth", 0)) + 1
    if depth > MAX_DEPTH:
        return False, f"refused: depth {depth} exceeds MAX_DEPTH {MAX_DEPTH}"
    child = {"id": tid, "tier": "A", "summary": summary,
             "acceptance": list(acceptance), "evidence_required": [],
             "blocked_by": list(par.get("blocked_by") or []),
             "status": "PROPOSED", "report_ref": "", "validation_ref": "",
             "parent": parent, "depth": depth,
             "covers_goal": list(covers_goal) if covers_goal is not None
             else list(par.get("covers_goal") or [])}
    recs.append(child)
    par.setdefault("blocked_by", [])
    if tid not in par["blocked_by"]:
        par["blocked_by"].append(tid)
    par["depth"] = min(int(par.get("depth", 0)), depth - 1)
    save_all(recs, q)
    return True, f"spawned {tid} under {parent} (depth {depth})"


# ------------------------------------------------------------------
# Human queue: an A-task the agent cannot do becomes PAUSED citing an
# h-task with exactly what is needed from whom. answer() delivers the
# human's payload, resumes the task, and re-opens any DONE dependents
# that ran on the prediction (nothing silently passes on stale data).


def hload(root: Path) -> list[dict]:
    p = Path(root) / "h-tasks.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def hsave(recs: list[dict], root: Path) -> None:
    root = Path(root)
    (root / "h-tasks.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))


def open_h(root: Path) -> list[dict]:
    return [h for h in hload(root) if h.get("status") == "open"]


def escalate(root: Path, tid: str, need: str, options: list[str] | None = None,
             recommendation: str = "", predicted=None) -> tuple[bool, str]:
    """A-task -> human task. The agent parks the lane and keeps working."""
    import uuid as _uuid
    root = Path(root)
    q = root / "tasks.jsonl"
    recs = load(q)
    by_id = {r.get("id"): r for r in recs}
    if tid not in by_id:
        return False, f"unknown task: {tid}"
    if by_id[tid].get("status") == "DONE":
        return False, f"task already DONE: {tid}"
    hid = "h-" + _uuid.uuid4().hex[:6]
    hs = hload(root)
    hs.append({"id": hid, "task": tid, "need": need,
               "options": list(options or []),
               "recommendation": recommendation[:500],
               "predicted": predicted, "status": "open",
               "answer": None, "ts": time.time()})
    hsave(hs, root)
    by_id[tid]["status"] = "PAUSED"
    by_id[tid]["paused_on"] = hid
    save_all(recs, q)
    return True, hid


def answer(root: Path, hid: str, answer_text="") -> tuple[bool, str]:
    """Human delivers. Resume the paused task; re-open DONE dependents that
    consumed the prediction (reconcile: real data landed, re-verify)."""
    root = Path(root)
    hs = hload(root)
    by_h = {h.get("id"): h for h in hs}
    if hid not in by_h:
        return False, f"unknown human task: {hid}"
    h = by_h[hid]
    if h.get("status") != "open":
        return False, f"human task not open: {hid}"
    h["status"] = "answered"
    h["answer"] = (answer_text or "")[:2000]
    hsave(hs, root)
    q = root / "tasks.jsonl"
    recs = load(q)
    by_id = {r.get("id"): r for r in recs}
    tid = h.get("task", "")
    affected = []
    if tid in by_id and by_id[tid].get("status") == "PAUSED":
        by_id[tid]["status"] = "EXECUTING"
        affected.append(tid)
    for r in recs:
        if tid and tid in (r.get("blocked_by") or []) \
                and r.get("status") in ("DONE", "REPORTED") \
                and r.get("id") not in affected:
            r["status"] = "EXECUTING"
            affected.append(r["id"])
    save_all(recs, q)
    for t in affected:
        alog(t, "reverify", [], root,
             f"real data landed on {hid}; re-verify before DONE")
    return True, f"{hid} answered; resumed+reverify: {affected or ['none']}"


# ------------------------------------------------------------------
# Validators: <root>/validators/<task-id>.py — a dummy script that judges
# whether the a-log matches the criteria set for the task. Contract:
# argv = [validator, task_id, tasks.jsonl, a-log path]; stdout JSON
# {"pass": true|false, "reasons": [...]}; exit 0 always (non-zero exit or
# bad JSON = an ERROR entry, never a silent pass). Validators are
# ADDITIVE: they can only add missing reasons, never excuse uncovered
# acceptance, missing reports, or missing receipts.


def validator_path(tid: str, root: Path) -> Path:
    return Path(root) / "validators" / f"{tid}.py"


def run_validator(tid: str, root: Path) -> list[str]:
    root = Path(root)
    vp = validator_path(tid, root)
    if not vp.exists():
        return []
    cmd = [sys.executable, str(vp), tid, str(root / "tasks.jsonl"),
           str(alog_path(tid, root))]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=60, cwd=root.parent)
    except Exception as e:
        return [f"validator error: could not run ({e})"[:120]]
    if r.returncode != 0:
        tail = ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1][:100]
        return [f"validator error: exit {r.returncode} :: {tail}"]
    try:
        verdict = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return ["validator error: stdout is not JSON verdict"]
    if not isinstance(verdict, dict) or "pass" not in verdict:
        return ["validator error: verdict needs {pass, reasons}"]
    if verdict["pass"]:
        return []
    reasons = verdict.get("reasons") or ["validator failed (no reasons given)"]
    return [f"validator: {x}"[:160] for x in reasons[:8]]


def verify(root: Path) -> list[str]:
    """Read-only queue audit. Empty = clean."""
    root = Path(root)
    goal = goal_get(root)
    n_accept = len(goal.get("acceptance", [])) if goal else 0
    htasks = {h.get("id"): h for h in hload(root)}
    q = root / "tasks.jsonl"
    if not q.exists():
        return [f"queue missing: {q} (run init)"]
    recs = load(q)
    by_id = {r.get("id"): r for r in recs if isinstance(r, dict)}
    out = []
    for i, r in enumerate(recs):
        tag = r.get("id", f"line{i}") if isinstance(r, dict) else f"line{i}"
        if not isinstance(r, dict):
            out.append(f"{tag}: record is not an object")
            continue
        for k in REQUIRED:
            if not r.get(k):
                out.append(f"{tag}: missing {k}")
        if r.get("status") not in STATUS:
            out.append(f"{tag}: bad status {r.get('status')!r}")
        for b in (r.get("blocked_by") or []):
            if b not in by_id:
                out.append(f"{tag}: dangling blocked_by {b!r}")
        if r.get("status") == "DONE":
            out += [f"{tag}: {e}" for e in done_gate(r, root)]
        if r.get("status") == "PAUSED":
            hid = r.get("paused_on", "")
            if not hid:
                out.append(f"{tag}: PAUSED without paused_on (which human task?)")
            elif hid not in htasks:
                out.append(f"{tag}: paused_on unresolvable: {hid}"[:120])
        for g in (r.get("covers_goal") or []):
            if goal is None:
                out.append(f"{tag}: covers_goal set but no goal.json")
                break
            if not isinstance(g, int) or not 0 <= g < n_accept:
                out.append(f"{tag}: covers_goal[{g}] outside goal acceptance")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atask.py")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _dir(p):
        p.add_argument("--dir", default=argparse.SUPPRESS)
        return p

    _dir(sub.add_parser("init"))
    p_add = _dir(sub.add_parser("add"))
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--summary", required=True)
    p_add.add_argument("--tier", default="A")
    p_add.add_argument("--accept", action="append", default=[])
    p_add.add_argument("--blocked-by", action="append", default=[])
    p_add.add_argument("--evidence", action="append", default=[])
    p_add.add_argument("--covers-goal", default="")
    for name in ("justify", "execute", "report"):
        p = _dir(sub.add_parser(name))
        p.add_argument("--id", required=True)
        p.add_argument("--report", default=None)
        p.add_argument("--receipt", default=None)
    p_log = _dir(sub.add_parser("log"))
    p_log.add_argument("--id", required=True)
    p_log.add_argument("--action", default="work")
    p_log.add_argument("--covers", default="")
    p_log.add_argument("--detail", default="")
    p_log.add_argument("--evidence", default="")
    p_sl = _dir(sub.add_parser("stoplight"))
    p_sl.add_argument("--id", required=True)
    p_done = _dir(sub.add_parser("done"))
    p_done.add_argument("--id", required=True)
    p_done.add_argument("--report", default=None)
    p_done.add_argument("--receipt", default=None)
    p_list = _dir(sub.add_parser("list"))
    p_list.add_argument("--status", default=None)
    _dir(sub.add_parser("ready"))
    _dir(sub.add_parser("verify"))
    p_goal = _dir(sub.add_parser("goal"))
    p_goal.add_argument("op", choices=("set", "show", "check"))
    p_goal.add_argument("--statement", default="")
    p_goal.add_argument("--accept", action="append", default=[])
    p_spawn = _dir(sub.add_parser("spawn"))
    p_spawn.add_argument("--parent", required=True)
    p_spawn.add_argument("--id", required=True)
    p_spawn.add_argument("--summary", required=True)
    p_spawn.add_argument("--accept", action="append", default=[])
    p_spawn.add_argument("--covers-goal", default="")
    p_esc = _dir(sub.add_parser("escalate"))
    p_esc.add_argument("--id", required=True)
    p_esc.add_argument("--need", required=True)
    p_esc.add_argument("--options", default="")
    p_esc.add_argument("--recommend", default="")
    p_esc.add_argument("--predict", default=None)
    p_ans = _dir(sub.add_parser("answer"))
    p_ans.add_argument("--hid", required=True)
    p_ans.add_argument("--answer", default="")
    _dir(sub.add_parser("hlist"))

    a = ap.parse_args(argv)
    root = Path(getattr(a, "dir", DEFAULT_DIR))

    if a.cmd == "init":
        root.mkdir(parents=True, exist_ok=True)
        for sub_d in ("a-logs", "reports", "runs", "validators"):
            (root / sub_d).mkdir(exist_ok=True)
        q = root / "tasks.jsonl"
        if not q.exists():
            q.write_text("")
        if not (root / "h-tasks.jsonl").exists():
            (root / "h-tasks.jsonl").write_text("")
        print(json.dumps({"init": True, "dir": str(root),
                          "close": f"harness ready at {root}. add tasks, drain ready."}))
        return 0

    if a.cmd == "add":
        q = root / "tasks.jsonl"
        recs = load(q)
        if any(r.get("id") == a.id for r in recs):
            print(f"duplicate id: {a.id}")
            return 1
        rec = {"id": a.id, "tier": a.tier, "summary": a.summary,
               "acceptance": a.accept, "evidence_required": a.evidence,
               "blocked_by": a.blocked_by, "status": "PROPOSED",
               "report_ref": "", "validation_ref": "",
               "depth": 0,
               "covers_goal": [int(c) for c in a.covers_goal.split(",")
                               if c.strip().isdigit()]}
        recs.append(rec)
        save_all(recs, q)
        print(json.dumps({"added": a.id, "status": "PROPOSED"}))
        return 0

    if a.cmd in ("justify", "execute", "report"):
        nxt = {"justify": "JUSTIFIED", "execute": "EXECUTING", "report": "REPORTED"}[a.cmd]
        ok, msg = set_status(a.id, nxt, root,
                             report_ref=getattr(a, "report", None),
                             validation_ref=getattr(a, "receipt", None))
        print(msg)
        return 0 if ok else 1

    if a.cmd == "log":
        covers = [int(c) for c in a.covers.split(",") if c.strip().isdigit()]
        e = alog(a.id, a.action, covers, root, a.detail, a.evidence)
        print(json.dumps({"logged": True, "covers": e["covers"]}))
        return 0

    if a.cmd == "stoplight":
        rep = stoplight(a.id, root)
        print(json.dumps(rep, indent=1)[:2000])
        return 0 if rep["go"] else 1

    if a.cmd == "done":
        ok, msg = set_status(a.id, "DONE", root,
                             report_ref=a.report, validation_ref=a.receipt)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "list":
        recs = load(root / "tasks.jsonl")
        if a.status == "READY":
            recs = ready(recs)
        elif a.status:
            recs = [r for r in recs if r.get("status") == a.status]
        for r in recs:
            print(f"{r.get('id')} [{r.get('status')}] {r.get('summary','')[:80]}")
        return 0

    if a.cmd == "ready":
        rs = ready(load(root / "tasks.jsonl"))
        print(json.dumps({"ready": [r.get("id") for r in rs]}))
        return 0

    if a.cmd == "verify":
        errs = verify(root)
        for e in errs:
            print(e)
        print(f"verify: {len(errs)} findings")
        return 1 if errs else 0

    if a.cmd == "goal":
        if a.op == "set":
            if not a.statement or not a.accept:
                print("goal set needs --statement and at least one --accept")
                return 1
            g = goal_set(root, a.statement, a.accept)
            print(json.dumps({"goal": g["id"], "acceptance": len(g["acceptance"])}))
            return 0
        if a.op == "show":
            g = goal_get(root)
            print(json.dumps(g, indent=1)[:2000] if g else "no goal.json")
            return 0 if g else 1
        rep = goal_check(root)
        print(json.dumps(rep, indent=1)[:3000])
        return 0 if rep.get("goal_done") else 1

    if a.cmd == "spawn":
        cg = [int(c) for c in a.covers_goal.split(",") if c.strip().isdigit()]
        ok, msg = spawn(root, a.parent, a.id, a.summary, a.accept,
                        cg or None)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "escalate":
        opts = [o.strip() for o in a.options.split(",") if o.strip()]
        try:
            pred = json.loads(a.predict) if a.predict else None
        except Exception:
            print("unparseable --predict (must be JSON)")
            return 1
        ok, msg = escalate(root, a.id, a.need, opts, a.recommend, pred)
        print(msg if ok else msg)
        return 0 if ok else 1

    if a.cmd == "answer":
        ok, msg = answer(root, a.hid, a.answer)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "hlist":
        for h in open_h(root):
            print(f"{h['id']} task={h.get('task')} need={h.get('need','')[:80]}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

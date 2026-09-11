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
  python3 atask.py run start --id a-slug --worker opencode --model mimo-v2.5
  # ... work happens, worker reports usage ...
  python3 atask.py run usage --run r-xxxx --input-tokens 48321 --output-tokens 7132 --cost 0.0831
  python3 atask.py run finish --run r-xxxx --result validated --validator pytest
  python3 atask.py log --id a-slug --covers 0 --evidence "command:pytest tests/ -q"
  python3 atask.py stoplight --id a-slug
  python3 atask.py done --id a-slug --report reports/a-slug.md --receipt sha256:...
  python3 atask.py verify [--dir .atask]
  python3 atask.py goal set --statement "..." --accept "end 1" [--accept "end 2"]
  python3 atask.py goal check
  python3 atask.py spawn --parent a-slug --id a-sub --summary "..." --accept "..."
  python3 atask.py escalate --id a-slug --kind PREFERENCE --need "which region?"
    [--options "eu,us"] [--recommend eu] [--predict '{"region":"eu"}']
  python3 atask.py answer --hid h-abc123 --answer "..." [--status denied]
  kinds: AUTHORIZATION SECRET PREFERENCE PHYSICAL IDENTITY AMBIGUITY (only these)
"""
from __future__ import annotations
import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from events import emit as _emit

STATUS = ("PROPOSED", "JUSTIFIED", "EXECUTING", "PAUSED", "REPORTED",
          "REJECTED", "DONE")
READY_STATUS = ("JUSTIFIED", "EXECUTING")
REQUIRED = ("id", "tier", "summary", "status")
DEFAULT_DIR = ".atask"


def d(p: str | Path, *parts: str) -> Path:
    return Path(p, *parts)


from contextlib import contextmanager as _cm
import threading as _th

_local = _th.local()


@_cm
def _locked(path: Path):
    """Cross-process exclusive lock (fcntl.flock, stdlib, Unix) +
    same-thread re-entrant (nested transact/load never self-deadlocks).
    Makes read-modify-write cycles AND plain reads safe: without covered
    reads, a reader can catch a torn write at a line boundary and
    silently miss records."""
    import fcntl as _fc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    depth = getattr(_local, "depth", 0)
    _local.depth = depth + 1
    lf = open(str(path) + ".lock", "w")
    try:
        if depth == 0:
            _fc.flock(lf.fileno(), _fc.LOCK_EX)
        yield
    finally:
        if depth == 0:
            try:
                _fc.flock(lf.fileno(), _fc.LOCK_UN)
            except Exception:
                pass
        lf.close()
        _local.depth = depth


def _opt_int(v) -> int | None:
    if v is None:
        return None
    return int(float(v))


def _opt_float(v) -> float | None:
    if v is None:
        return None
    return float(v)


def _int_list(vals) -> list[int]:
    """Union of comma lists across repeated flags: --covers 0,1 --covers 2."""
    if vals is None:
        return []
    if isinstance(vals, str):
        vals = [vals]
    out = []
    for v in vals:
        out += [int(c) for c in str(v).split(",") if c.strip().isdigit()]
    return sorted(set(out))


def load(queue: Path) -> list[dict]:
    queue = Path(queue)
    with _locked(queue):
        if not queue.exists():
            return []
        out = []
        for line in queue.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _write_all(recs: list[dict], queue: Path) -> None:
    queue = Path(queue)
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))


def save_all(recs: list[dict], queue: Path) -> None:
    queue = Path(queue)
    with _locked(queue):
        _write_all(recs, queue)


def transact(root: str | Path, fn) -> object:
    """One cross-process transaction: load queue+h/m under a single
    exclusive lock, mutate in place, write back. All state transitions
    funnel through here — concurrent workers cannot lose updates."""
    root = Path(root)
    with _locked(root / "tasks.jsonl"):
        recs = load(root / "tasks.jsonl")
        hs = hload(root)
        ms = mload(root)
        out = fn(recs, hs, ms)
        _write_all(recs, root / "tasks.jsonl")
        _write_h(hs, root)
        _write_m(ms, root)
    return out


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
    by stoplight) — lines without evidence count covers on trust.
    No work exists outside an A-task: unknown ids are refused, not filed."""
    root = Path(root)
    known = {r.get("id") for r in load(root / "tasks.jsonl")}
    if tid not in known:
        raise ValueError(f"unknown task (no work outside A-tasks): {tid}")
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


def check_required(ev: dict, root: Path) -> str | None:
    """Execute one DECLARED evidence item. None = satisfied, else reason.
    entries: {"kind": "command", "spec": "<shell cmd>"} (runs green now,
    cwd = repo root) or {"kind": "file", "spec": "<path>"} (exists now,
    resolved state-dir first). Declared pre-work, enforced at stoplight."""
    root = Path(root)
    if not isinstance(ev, dict):
        return f"required evidence malformed: {ev!r}"[:120]
    kind, spec = ev.get("kind", ""), (ev.get("spec") or "").strip()
    if kind == "command" and spec:
        return check_evidence("command:" + spec, root.parent)
    if kind == "file" and spec:
        for c in (root / spec, Path(spec), root.parent / spec):
            if c.exists() and c.is_file():
                return None
        return f"required file missing: {spec}"[:120]
    return f"required evidence needs kind command|file + spec, got: {ev!r}"[:120]


def stoplight(tid: str, root: Path) -> dict:
    """GO iff every acceptance index is a-log covered AND every DECLARED
    evidence item is satisfied now AND every a-log claim re-executes green
    AND report file exists AND validation_ref set AND validator passes."""
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
    for i, req in enumerate(rec.get("evidence_required", []) or []):
        bad = check_required(req, root)
        if bad:
            missing.append(f"required[{i}]: {bad}")
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
    else:
        # Existence is not integrity: recompute the id from content.
        try:
            import runs as _runs
            rp = resolve(vr, root)
            if not _runs.verify_file(rp):
                errs.append(f"validation_ref TAMPERED (id mismatch): {vr}"[:120])
        except Exception as e:
            errs.append(f"validation_ref unreadable: {e}"[:120])
    return errs


def set_status(tid: str, status: str, root: Path, **fields) -> tuple[bool, str]:
    root = Path(root)
    if status not in STATUS:
        return False, f"bad status {status!r}"

    def _go(recs: list[dict], hs: list[dict], ms: list[dict]):
        by_id = {r.get("id"): r for r in recs}
        if tid not in by_id:
            return (False, "unknown task id", "", 0)
        rec = by_id[tid]
        for b in (rec.get("blocked_by") or []):
            if b not in by_id:
                return (False, f"dangling blocked_by {b!r}", "", 0)
        rec.update({k: v for k, v in fields.items() if v is not None})
        if status == "DONE":
            # Gate runs on saved state (stoplight reads the queue file);
            # on refusal the previous record is restored, never dirty.
            prev_rec = dict(rec)
            rec["status"] = status
            _write_all(recs, root / "tasks.jsonl")
            errs = done_gate(rec, root)
            sl = stoplight(tid, root)
            if not sl["go"]:
                errs += [f"stoplight: {m}"[:160] for m in sl["missing"][:6]]
            if errs:
                rec.clear()
                rec.update(prev_rec)  # in-place: recs list shares the object
                _write_all(recs, root / "tasks.jsonl")
                return (False, "transition rejected: " + "; ".join(errs),
                        prev_rec.get("status", ""), int(rec.get("attempts", 0)))
            return (True, f"{tid} -> {status}",
                    prev_rec.get("status", ""), int(rec.get("attempts", 0)))
        prev = rec.get("status", "")
        if status == "EXECUTING" and prev != "EXECUTING":
            rec["attempts"] = int(rec.get("attempts", 0)) + 1
        rec["status"] = status
        return (True, f"{tid} -> {status}",
                prev, int(rec.get("attempts", 0)))

    out = transact(root, _go)
    ok, msg, prev, attempts = out[0], out[1], out[2], out[3]
    if not ok:
        return False, msg
    if status == "DONE":
        _emit(root, "run.finished", task_id=tid, outcome="validated",
              attempts=attempts)
        return True, msg
    if status == "EXECUTING" and prev != "EXECUTING":
        _emit(root, "run.started", task_id=tid, attempt=attempts)
    _emit(root, "task.status", task_id=tid, **{"from": prev, "to": status},
          attempts=attempts)
    return True, msg


# ------------------------------------------------------------------
# A-goal: one active end-state; tasks map to its acceptance indices via
# covers_goal. goal_done is DERIVED (all mapped tasks DONE), never stored,
# so it cannot drift from the queue.


def goal_set(root: Path, statement: str, acceptance: list[str],
             budget_usd: float | None = None, token_budget: int | None = None,
             tool_budget: int | None = None,
             deadline_min: float | None = None) -> dict:
    root = Path(root)
    g = {"id": "g-main", "statement": statement,
         "acceptance": list(acceptance), "ts": time.time()}
    if budget_usd is not None:
        g["budget_usd"] = budget_usd
    if token_budget is not None:
        g["token_budget"] = token_budget
    if tool_budget is not None:
        g["tool_budget"] = tool_budget
    if deadline_min is not None:
        g["deadline_min"] = deadline_min
    (root / "goal.json").write_text(json.dumps(g, indent=1, sort_keys=True))
    # Fresh goal = fresh mapping: stale covers_goal from a retired goal
    # must not complete the new one. Statuses untouched, mappings cleared.
    q = root / "tasks.jsonl"
    recs = load(q)
    for r in recs:
        if r.get("covers_goal"):
            r["covers_goal"] = []
    save_all(recs, q)
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


def create_task(root: Path, rec: dict) -> tuple[bool, str]:
    """Insert one task record transactionally (duplicate ids refused)."""
    root = Path(root)

    def _go(recs: list[dict], hs: list[dict], ms: list[dict]):
        if any(r.get("id") == rec.get("id") for r in recs):
            return (False, f"duplicate id: {rec.get('id')}")
        recs.append(rec)
        return (True, rec.get("id", ""))
    return transact(root, _go)[:2]


def spawn(root: Path, parent: str, tid: str, summary: str,
          acceptance: list[str], covers_goal: list[int] | None = None,
          evidence_required: list[dict] | None = None) -> tuple[bool, str]:
    root = Path(root)

    def _go(recs: list[dict], hs: list[dict], ms: list[dict]):
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
                 "acceptance": list(acceptance),
                 "evidence_required": list(evidence_required or []),
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
        return True, f"spawned {tid} under {parent} (depth {depth})"

    return transact(root, _go)


# ------------------------------------------------------------------
# Human queue: an A-task the agent cannot do becomes PAUSED citing an
# h-task with exactly what is needed from whom. micropattern: the agent may
# ONLY ask at a genuine human boundary (enforced in code, not advice):
ASK_KINDS = ("AUTHORIZATION", "SECRET", "PREFERENCE",
             "PHYSICAL", "IDENTITY", "AMBIGUITY")
# Kinds where no attempt is possible (nothing to try): exempt from proof.
ATTEMPT_EXEMPT = ("PHYSICAL", "IDENTITY")
# No WASM, no sidecar: proof-of-attempt is a stdlib .py rule over records
# the kernel already keeps (attempts, a-logs, validator events). The
# evidence commands in question already execute; sandboxing adds nothing.


def _failed_signal(root: Path, tid: str) -> bool:
    """True iff the task has a FAILED checkable attempt on record:
    a validator.failed event, or an a-log evidence command that runs red
    right now. Status-flapping without evidence never counts."""
    root = Path(root)
    from events import read as _eread
    if any(e.get("task_id") == tid for e in _eread(root, "validator.failed")):
        return True
    for e in alog_read(tid, root):
        ev = e.get("evidence", "") or ""
        if ev.startswith("command:") and check_evidence(ev, root.parent):
            return True
    return False


def _runtime_evidence(root: Path, tid: str) -> list[str]:
    """Evidence owned by the runtime, not the LLM: failed a-log lines
    (action + re-run verdict) plus validator.failed reasons. The claim
    (need text) rides separately; this list is the proof."""
    root = Path(root)
    from events import read as _eread
    ev: list[str] = []
    for n, e in enumerate(alog_read(tid, root)):
        claim = (e.get("evidence", "") or "")
        if claim.startswith("command:") and check_evidence(claim, root.parent):
            ev.append(f"alog:{tid}#{n} red: {claim[:100]}")
    for r in _eread(root, "validator.failed"):
        if r.get("task_id") == tid:
            for reason in (r.get("reasons") or [])[:3]:
                ev.append(f"validator: {reason}"[:140])
    return ev[:8]


def hload(root: Path) -> list[dict]:
    p = Path(root) / "h-tasks.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _write_h(recs: list[dict], root: Path) -> None:
    root = Path(root)
    (root / "h-tasks.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))


def hsave(recs: list[dict], root: Path) -> None:
    root = Path(root)
    with _locked(root / "h-tasks.jsonl"):
        _write_h(recs, root)


def open_h(root: Path) -> list[dict]:
    return [h for h in hload(root) if h.get("status") == "open"]


def escalate(root: Path, tid: str, need: str, kind: str,
             options: list[str] | None = None,
             recommendation: str = "", predicted=None,
             operation: str = "", alternatives: list | None = None
             ) -> tuple[bool, str]:
    """File a BlockClaim. The agent claims "blocked on <operation>"; the
    verifier (kind gate + proof-of-attempt gate below) certifies H_BLOCK.
    Refusal = CONTINUE verdict: keep working. operation names the blocking
    operation id; alternatives are checked {route: status} (class-C
    exhaustion); runtime evidence auto-attaches (never the LLM's prose)."""
    import uuid as _uuid
    if kind not in ASK_KINDS:
        return False, (f"refused: {kind!r} is not a human boundary "
                       f"(choose: {', '.join(ASK_KINDS)})")
    root = Path(root)
    q = root / "tasks.jsonl"
    recs = load(q)
    by_id = {r.get("id"): r for r in recs}
    if tid not in by_id:
        return False, f"unknown task: {tid}"
    if by_id[tid].get("status") == "DONE":
        return False, f"task already DONE: {tid}"
    if kind not in ATTEMPT_EXEMPT:
        # Proof-of-attempt: an agent that hasn't tried can't escalate.
        # Attempts alone don't suffice (status-flapping farms nothing);
        # a FAILED checkable attempt must be on record.
        attempts = int(by_id[tid].get("attempts", 0))
        if attempts < 2:
            return False, (f"refused: {tid} has {attempts} recorded attempt(s); "
                           f"work it (EXECUTING + a-log) at least twice first")
        if not alog_read(tid, root):
            return False, f"refused: no a-log lines on {tid} (log every action)"
        if not _failed_signal(root, tid):
            return False, (f"refused: no failed checkable attempt on {tid}; "
                           f"try something with re-runnable evidence first")
        if not (operation or "").strip():
            return False, (f"refused: name the blocking operation "
                           f"(--operation op-id: what exactly can't complete)")
    hid = "h-" + _uuid.uuid4().hex[:6]
    hs = hload(root)
    alts = []
    for a_ in (alternatives or []):
        if isinstance(a_, dict) and a_.get("route"):
            alts.append({"route": str(a_["route"])[:120],
                         "status": str(a_.get("status", ""))[:120]})
        elif isinstance(a_, str) and ":" in a_:
            r_, s_ = a_.split(":", 1)
            alts.append({"route": r_.strip()[:120], "status": s_.strip()[:120]})
    hs.append({"id": hid, "task": tid, "kind": kind, "need": need,
               "options": list(options or []),
               "recommendation": recommendation[:500],
               "predicted": predicted, "status": "open",
               "answer": None, "ts": time.time(),
               "block": {"operation": (operation or "")[:200],
                         "verdict": "H_BLOCK",
                         "evidence": _runtime_evidence(root, tid),
                         "alternatives_checked": alts}})
    hsave(hs, root)
    by_id[tid]["status"] = "PAUSED"
    by_id[tid]["paused_on"] = hid
    save_all(recs, q)
    _emit(root, "human.asked", hid=hid, task_id=tid, kind=kind,
          options=list(options or []), recommended=recommendation[:200])
    return True, hid


def answer(root: Path, hid: str, answer_text="",
           status: str = "answered") -> tuple[bool, str]:
    """Human delivers. Resume the paused task; re-open DONE/REPORTED
    dependents that consumed the prediction (reconcile: real data landed,
    re-verify). status is answered|denied (denial replans, moves nothing)."""
    if status not in ("answered", "denied"):
        return False, f"bad human-task status {status!r}"
    root = Path(root)
    hs = hload(root)
    by_h = {h.get("id"): h for h in hs}
    if hid not in by_h:
        return False, f"unknown human task: {hid}"
    h = by_h[hid]
    if h.get("status") != "open":
        return False, f"human task not open: {hid}"
    h["status"] = status
    h["answer"] = (answer_text or "")[:2000]
    hsave(hs, root)
    _emit(root, "human.choice", hid=hid, task_id=h.get("task", ""),
          kind=h.get("kind", ""), recommended=(h.get("recommendation") or "")[:200],
          selected=(answer_text or "")[:200], decision=status)
    q = root / "tasks.jsonl"
    recs = load(q)
    by_id = {r.get("id"): r for r in recs}
    tid = h.get("task", "")
    affected = []
    if tid in by_id and by_id[tid].get("status") == "PAUSED":
        by_id[tid]["status"] = "EXECUTING"
        # Resumption opens a new run: the answer changed the world.
        by_id[tid]["attempts"] = int(by_id[tid].get("attempts", 0)) + 1
        _emit(root, "run.started", task_id=tid,
              attempt=by_id[tid]["attempts"], resumed_from=hid)
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
             f"{status} on {hid}; re-verify before DONE")
    return True, f"{hid} {status}; resumed+reverify: {affected or ['none']}"


# ------------------------------------------------------------------
# M-tasks: machine authority requests. An m-task exists iff the
# capability is available BUT no current grant authorizes it
# (M_PROMOTE). Counterfactual fields are REQUIRED: the approver decides
# on marginal gain, never on "need smarter model". Resolution records
# the decision only — no treasury moves here; grant activation is
# human-side, outside the kernel.


def mload(root: Path) -> list[dict]:
    p = Path(root) / "m-tasks.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _write_m(recs: list[dict], root: Path) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / "m-tasks.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))


def msave(recs: list[dict], root: Path) -> None:
    with _locked(Path(root) / "m-tasks.jsonl"):
        _write_m(recs, root)


def open_m(root: Path) -> list[dict]:
    return [m for m in mload(root) if m.get("status") == "open"]


def autonomy(root: Path) -> dict:
    """Seed0-objective metrics, derived from events+queues (no labels needed):
    AutonomyRate = done / (done + h-promotions); h/m rates; $ requested vs
    granted; post-escalation success (parent DONE after answer/grant)."""
    from events import read as _eread
    root = Path(root)
    rows = _eread(root)
    by_ev: dict = {}
    for r in rows:
        by_ev.setdefault(r.get("event"), []).append(r)
    recs = {r.get("id"): r for r in load(root / "tasks.jsonl")}
    n_done = sum(1 for r in recs.values() if r.get("status") == "DONE")
    h_asked = by_ev.get("human.asked", [])
    h_choices = by_ev.get("human.choice", [])
    h_promotions = len({e.get("hid", "") for e in h_asked if e.get("hid")})
    post_ok = 0
    for e in h_choices:
        tid = next((h.get("task", "") for h in hload(root)
                    if h.get("id") == e.get("hid", "")), "")
        if tid and recs.get(tid, {}).get("status") == "DONE":
            post_ok += 1
    req_cents = sum(int(e.get("amount_cents", 0) or 0)
                    for e in by_ev.get("m.asked", []))
    granted_cents = 0
    for e in by_ev.get("m.decided", []):
        if e.get("decision", "").startswith("approved"):
            m = next((m for m in mload(root) if m.get("id") == e.get("mid", "")), {})
            granted_cents += int(m.get("amount_cents", 0) or 0)
    m_asked = len(by_ev.get("m.asked", []))
    denom = n_done + h_promotions
    return {"tasks_done": n_done, "tasks_total": len(recs),
            "autonomy_rate": round(n_done / denom, 3) if denom else None,
            "h_asked": len(h_asked), "h_answered": len(h_choices),
            "h_rate_per_done": round(len(h_asked) / max(1, n_done), 3),
            "m_asked": m_asked, "m_decided": len(by_ev.get("m.decided", [])),
            "cents_requested": req_cents, "cents_granted": granted_cents,
            "post_escalation_success": post_ok,
            "verdict": ("healthy" if n_done and len(h_asked) <= n_done
                        else "collecting")}


def mrequest(root: Path, tid: str, resource: str, amount_cents: int,
             baseline_succ: float, baseline_cost: float,
             req_succ: float, req_cost: float,
             reason: str = "") -> tuple[bool, str]:
    """File an M_BLOCK claim with counterfactuals. The router (human for
    now) decides on Δ success per cent, not on model desire."""
    import uuid as _uuid
    root = Path(root)
    recs = {r.get("id"): r for r in load(root / "tasks.jsonl")}
    if tid not in recs:
        return False, f"unknown task: {tid}"
    if recs[tid].get("status") == "DONE":
        return False, f"task already DONE: {tid}"
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        return False, "amount must be positive integer cents"
    for v, n in ((baseline_succ, "baseline-succ"), (req_succ, "req-succ")):
        if not 0 <= float(v) <= 1:
            return False, f"{n} must be a probability 0..1"
    gain_pp = round((float(req_succ) - float(baseline_succ)) * 100, 1)
    if gain_pp <= 0:
        return False, (f"refused: no positive marginal gain "
                       f"({req_succ} vs baseline {baseline_succ}); paid model "
                       f"must beat the free route or no request exists")
    if not (reason or "").strip():
        return False, "refused: state the reason (what threshold/evidence forces this)"
    mid = "m-" + _uuid.uuid4().hex[:6]
    ms = mload(root)
    ms.append({"id": mid, "parent": tid, "resource": resource[:200],
               "amount_cents": amount_cents,
               "baseline": {"success": float(baseline_succ),
                            "cost_usd": float(baseline_cost)},
               "requested": {"success": float(req_succ),
                             "cost_usd": float(req_cost)},
               "marginal_gain_pp": gain_pp,
               "reason": reason[:500], "status": "open",
               "decision": None, "ts": time.time()})
    msave(ms, root)
    _emit(root, "m.asked", mid=mid, task_id=tid, resource=resource[:120],
          amount_cents=amount_cents)
    return True, mid


def mresolve(root: Path, mid: str, decision: str,
             note: str = "") -> tuple[bool, str]:
    """Record the router's decision. approved-once releases exactly the
    stated cents for the stated resource, once — tracked by receipt, not
    by standing permission. denied ends it. Nothing moves money here."""
    if decision not in ("approved-once", "denied"):
        return False, "decision must be approved-once|denied"
    root = Path(root)
    ms = mload(root)
    by_m = {m.get("id"): m for m in ms}
    if mid not in by_m:
        return False, f"unknown m-task: {mid}"
    m = by_m[mid]
    if m.get("status") != "open":
        return False, f"m-task not open: {mid}"
    m["status"] = "decided"
    m["decision"] = decision
    m["note"] = (note or "")[:500]
    msave(ms, root)
    _emit(root, "m.decided", mid=mid, task_id=m.get("parent", ""),
          decision=decision)
    if decision == "approved-once":
        # The Grant: exact cents, single resource, one-shot. Tracked by
        # receipt below, never a standing permission.
        import uuid as _uuid2
        g = {"id": "g-" + _uuid2.uuid4().hex[:6], "mid": mid,
             "resource": m.get("resource", ""), "amount_cents": m.get("amount_cents", 0),
             "once": True, "ts": time.time()}
        with open(root / "grants.jsonl", "a") as f:
            f.write(json.dumps(g, sort_keys=True) + "\n")
        _emit(root, "grant.issued", grant=g["id"], mid=mid,
              amount_cents=g["amount_cents"])
    return True, f"{mid} {decision}"


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


# ------------------------------------------------------------------
# (Delegation lanes + brief-freeze live in staging/ + the Hermes-Kanban
# adapter. Kernel keeps spawn: branch deeper, parent waits on children.)


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
        if (r.get("acceptance") or []) and not (r.get("evidence_required") or []):
            out.append(f"{tag}: acceptance without declared evidence (no trust-only tasks)")
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
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="one-line closes; full JSON stays in state files")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _dir(p):
        p.add_argument("--dir", default=argparse.SUPPRESS)
        p.add_argument("--quiet", "-q", action="store_true",
                       default=argparse.SUPPRESS)
        return p

    _dir(sub.add_parser("init"))
    p_add = _dir(sub.add_parser("add"))
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--summary", required=True)
    p_add.add_argument("--tier", default="A")
    p_add.add_argument("--accept", action="append", default=[])
    p_add.add_argument("--blocked-by", action="append", default=[])
    p_add.add_argument("--evidence", action="append", default=[])
    p_add.add_argument("--covers-goal", action="append", default=[])
    for name in ("justify", "execute", "report"):
        p = _dir(sub.add_parser(name))
        p.add_argument("--id", required=True)
        p.add_argument("--report", default=None)
        p.add_argument("--receipt", default=None)
    p_rej = _dir(sub.add_parser("reject"))
    p_rej.add_argument("--id", required=True)
    p_rej.add_argument("--reasons", default="rejected without reasons recorded")
    p_log = _dir(sub.add_parser("log"))
    p_log.add_argument("--id", required=True)
    p_log.add_argument("--action", default="work")
    p_log.add_argument("--covers", action="append", default=[])
    p_log.add_argument("--detail", default="")
    p_log.add_argument("--evidence", default="")
    p_sl = _dir(sub.add_parser("stoplight"))
    p_sl.add_argument("--id", required=True)
    # NOTE: no `done` subcommand exists on purpose. The agent NEVER declares
    # DONE — it files REPORTED with proof; only driver pulse (the machine)
    # promotes, and only on green stoplight. An agent that could mark its
    # own work done would hallucinate completion; this removes the button.
    p_list = _dir(sub.add_parser("list"))
    p_list.add_argument("--status", default=None)
    _dir(sub.add_parser("ready"))
    _dir(sub.add_parser("verify"))
    p_goal = _dir(sub.add_parser("goal"))
    p_goal.add_argument("op", choices=("set", "show", "check"))
    p_goal.add_argument("--statement", default="")
    p_goal.add_argument("--accept", action="append", default=[])
    p_goal.add_argument("--budget-usd", default=None)
    p_goal.add_argument("--token-budget", default=None)
    p_goal.add_argument("--tool-budget", default=None)
    p_goal.add_argument("--deadline-min", default=None)
    p_spawn = _dir(sub.add_parser("spawn"))
    p_spawn.add_argument("--parent", required=True)
    p_spawn.add_argument("--id", required=True)
    p_spawn.add_argument("--summary", required=True)
    p_spawn.add_argument("--accept", action="append", default=[])
    p_spawn.add_argument("--evidence", action="append", default=[])
    p_spawn.add_argument("--covers-goal", action="append", default=[])
    p_esc = _dir(sub.add_parser("escalate"))
    p_esc.add_argument("--id", required=True)
    p_esc.add_argument("--need", required=True)
    p_esc.add_argument("--kind", required=True,
                       help="human boundary: AUTHORIZATION SECRET PREFERENCE PHYSICAL IDENTITY AMBIGUITY")
    p_esc.add_argument("--options", default="")
    p_esc.add_argument("--recommend", default="")
    p_esc.add_argument("--predict", default=None)
    p_esc.add_argument("--operation", default="",
                       help="blocking operation id (required unless PHYSICAL/IDENTITY)")
    p_esc.add_argument("--alt", action="append", default=[],
                       help="checked alternative route:status (repeatable)")
    p_ans = _dir(sub.add_parser("answer"))
    p_ans.add_argument("--hid", required=True)
    p_ans.add_argument("--answer", default="")
    p_ans.add_argument("--status", default="answered",
                       choices=("answered", "denied"))
    _dir(sub.add_parser("hlist"))
    p_mreq = _dir(sub.add_parser("mrequest"))
    p_mreq.add_argument("--id", required=True)
    p_mreq.add_argument("--resource", required=True)
    p_mreq.add_argument("--amount-cents", required=True)
    p_mreq.add_argument("--baseline-succ", required=True)
    p_mreq.add_argument("--baseline-cost", default="0")
    p_mreq.add_argument("--req-succ", required=True)
    p_mreq.add_argument("--req-cost", required=True)
    p_mreq.add_argument("--reason", default="")
    p_mres = _dir(sub.add_parser("mresolve"))
    p_mres.add_argument("--mid", required=True)
    p_mres.add_argument("--decision", required=True,
                        choices=("approved-once", "denied"))
    p_mres.add_argument("--note", default="")
    _dir(sub.add_parser("mlist"))
    _dir(sub.add_parser("autonomy"))
    p_run = _dir(sub.add_parser("run"))
    p_run.add_argument("op", choices=("start", "usage", "finish", "list"))
    p_run.add_argument("--id", default=None, help="task id (start/list)")
    p_run.add_argument("--run", default=None, help="run id (usage/finish)")
    p_run.add_argument("--worker", default="")
    p_run.add_argument("--model", default="")
    p_run.add_argument("--provider", default="")
    p_run.add_argument("--input-tokens", default=None)
    p_run.add_argument("--output-tokens", default=None)
    p_run.add_argument("--cached-tokens", default=None)
    p_run.add_argument("--token-source", default="agent")
    p_run.add_argument("--cost", default=None)
    p_run.add_argument("--from-session", default=None,
                       help="pull real counts from opencode session store")
    p_run.add_argument("--since", type=float, default=0,
                       help="with --from-session: attribute messages in last N minutes (0=all)")
    p_run.add_argument("--result", default="completed",
                       choices=("completed", "failed", "abandoned"))
    p_run.add_argument("--validator", default="")
    p_bud = _dir(sub.add_parser("budget"))
    p_bud.add_argument("op", choices=("set", "show", "record", "check"))
    p_bud.add_argument("--usd", default=None)
    p_bud.add_argument("--tokens", default=None)
    p_bud.add_argument("--label", default="")

    a = ap.parse_args(argv)
    root = Path(getattr(a, "dir", DEFAULT_DIR))
    Q = bool(getattr(a, "quiet", False))

    if a.cmd == "init":
        root.mkdir(parents=True, exist_ok=True)
        for sub_d in ("a-logs", "reports", "runs", "validators"):
            (root / sub_d).mkdir(exist_ok=True)
        q = root / "tasks.jsonl"
        if not q.exists():
            q.write_text("")
        if not (root / "h-tasks.jsonl").exists():
            (root / "h-tasks.jsonl").write_text("")
        if not (root / "m-tasks.jsonl").exists():
            (root / "m-tasks.jsonl").write_text("")
        print(json.dumps({"init": True, "dir": str(root),
                          "close": f"harness ready at {root}. add tasks, drain ready."}))
        return 0

    if a.cmd == "add":
        reqs = []
        for e in a.evidence:
            if ":" in e:
                k, s = e.split(":", 1)
                k, s = k.strip(), s.strip()
                if k in ("command", "file") and s:
                    reqs.append({"kind": k, "spec": s})
                    continue
            print(f"bad --evidence (need kind:spec, kind=command|file): {e}"[:160])
            return 1
        if a.accept and not reqs:
            # No trust-only tasks: acceptance without declared proof is
            # unvalidatable. Say how you'll prove it, then prove it.
            print("refused: acceptance needs ≥1 --evidence (kind:spec)")
            return 1
        rec = {"id": a.id, "tier": a.tier, "summary": a.summary,
               "acceptance": a.accept, "evidence_required": reqs,
               "blocked_by": a.blocked_by, "status": "PROPOSED",
               "report_ref": "", "validation_ref": "",
               "depth": 0,
               "covers_goal": _int_list(a.covers_goal)}
        ok, msg = create_task(root, rec)
        if ok:
            print(json.dumps({"added": a.id, "status": "PROPOSED"}))
            return 0
        print(msg)
        return 1

    if a.cmd in ("justify", "execute", "report"):
        nxt = {"justify": "JUSTIFIED", "execute": "EXECUTING", "report": "REPORTED"}[a.cmd]
        ok, msg = set_status(a.id, nxt, root,
                             report_ref=getattr(a, "report", None),
                             validation_ref=getattr(a, "receipt", None))
        print(msg)
        return 0 if ok else 1

    if a.cmd == "reject":
        ok, msg = set_status(a.id, "REJECTED", root, reasons=a.reasons)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "log":
        covers = _int_list(a.covers)
        try:
            e = alog(a.id, a.action, covers, root, a.detail, a.evidence)
        except ValueError as ex:
            print(str(ex)[:160])
            return 1
        print(json.dumps({"logged": True, "covers": e["covers"]}))
        return 0

    if a.cmd == "stoplight":
        rep = stoplight(a.id, root)
        print(json.dumps(rep, indent=1)[:2000])
        return 0 if rep["go"] else 1

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
            try:
                busd = float(a.budget_usd) if a.budget_usd is not None else None
                tb = int(float(a.token_budget)) if a.token_budget is not None else None
                tlb = int(float(a.tool_budget)) if a.tool_budget is not None else None
                ddl = float(a.deadline_min) if a.deadline_min is not None else None
            except ValueError:
                print("unparseable cap (must be numbers)")
                return 1
            g = goal_set(root, a.statement, a.accept, busd, tb, tlb, ddl)
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
        cg = _int_list(a.covers_goal)
        reqs = []
        for e in a.evidence:
            if ":" in e:
                k, s = e.split(":", 1)
                if k.strip() in ("command", "file") and s.strip():
                    reqs.append({"kind": k.strip(), "spec": s.strip()})
                    continue
            print(f"bad --evidence (need kind:spec): {e}"[:160])
            return 1
        if a.accept and not reqs:
            print("refused: acceptance needs ≥1 --evidence (kind:spec)")
            return 1
        ok, msg = spawn(root, a.parent, a.id, a.summary, a.accept,
                        cg or None, reqs or None)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "escalate":
        opts = [o.strip() for o in a.options.split(",") if o.strip()]
        try:
            pred = json.loads(a.predict) if a.predict else None
        except Exception:
            print("unparseable --predict (must be JSON)")
            return 1
        ok, msg = escalate(root, a.id, a.need, a.kind, opts, a.recommend, pred,
                           a.operation, a.alt)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "answer":
        ok, msg = answer(root, a.hid, a.answer,
                         getattr(a, "status", None) or "answered")
        print(msg)
        return 0 if ok else 1

    if a.cmd == "mrequest":
        try:
            cents = int(a.amount_cents)
            bs, bc = float(a.baseline_succ), float(a.baseline_cost)
            rs, rc = float(a.req_succ), float(a.req_cost)
        except ValueError:
            print("unparseable numbers (cents int, probs/costs float)")
            return 1
        ok, msg = mrequest(root, a.id, a.resource, cents, bs, bc, rs, rc,
                           a.reason)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "mresolve":
        ok, msg = mresolve(root, a.mid, a.decision, a.note)
        print(msg)
        return 0 if ok else 1

    if a.cmd == "mlist":
        for m in open_m(root):
            print(f"{m['id']} parent={m.get('parent')} {m.get('resource','')[:60]} "
                  f"{m.get('amount_cents')}c gain={m.get('marginal_gain_pp')}pp")
        return 0

    if a.cmd == "autonomy":
        print(json.dumps(autonomy(root), indent=1)[:2000])
        return 0

    if a.cmd == "hlist":
        for h in open_h(root):
            print(f"{h['id']} [{h.get('kind')}] task={h.get('task')} "
                  f"need={h.get('need','')[:80]}")
        return 0

    if a.cmd == "run":
        import runs as _runs
        if a.op == "start":
            if not a.id:
                print("run start needs --id (task id)")
                return 1
            q = root / "tasks.jsonl"
            recs = load(q)
            by_id = {r.get("id"): r for r in recs}
            if a.id not in by_id:
                print(f"unknown task: {a.id}")
                return 1
            rec = by_id[a.id]
            rec["attempts"] = int(rec.get("attempts", 0)) + 1
            rec["status"] = "EXECUTING"
            save_all(recs, q)
            run = _runs.Run(task_id=a.id, attempt=rec["attempts"],
                            worker=a.worker, model=a.model, provider=a.provider)
            _runs.save_open(run, root)
            _emit(root, "run.started", task_id=a.id, run_id=run.run_id,
                  attempt=run.attempt, worker=a.worker, model=a.model)
            if Q:
                print(run.run_id)
                return 0
            print(json.dumps({"run_id": run.run_id, "task_id": a.id,
                              "attempt": run.attempt,
                              "env": {"ALOOP_RUN_ID": run.run_id,
                                      "ALOOP_TASK_ID": a.id}}))
            return 0
        if a.op == "list":
            out = _runs.list_open(root, a.id or "")
            if not a.id:
                out += [{"run_id": r["run_id"], "task_id": r["task_id"],
                         "result": r.get("result", "")}
                        for r in _runs.read_runs(root)[-10:]]
            print(json.dumps(out, indent=1)[:3000])
            return 0
        if not a.run:
            print(f"run {a.op} needs --run (run id)")
            return 1
        run = _runs.load_open(a.run, root)
        if run is None:
            print(f"unknown open run: {a.run}")
            return 1
        if a.op == "usage":
            try:
                run.usage(
                    input_tokens=_opt_int(a.input_tokens),
                    output_tokens=_opt_int(a.output_tokens),
                    cached_tokens=_opt_int(a.cached_tokens),
                    token_source=a.token_source,
                    reported_cost_usd=_opt_float(a.cost),
                    model=a.model, provider=a.provider, worker=a.worker)
            except ValueError as e:
                print(str(e)[:160])
                return 1
            _runs.save_open(run, root)
            _emit(root, "resource.used", task_id=run.task_id, run_id=run.run_id,
                  cost_usd=run.reported_cost_usd, tokens=run.output_tokens,
                  token_source=run.token_source, model=run.model)
            if a.from_session:
                # Winner wiring: real provider counts from opencode's store.
                import importlib.util as _ilu
                mp = Path(__file__).resolve().parent / "meters" / "opencode_db.py"
                spec = _ilu.spec_from_file_location("meters_db", mp)
                if spec is None or spec.loader is None:
                    print("meters/opencode_db.py missing")
                    return 1
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if not mod.session_totals(a.from_session).get("found"):
                    print(f"unknown session in store: {a.from_session}")
                    return 1
                mu = mod.message_usage(a.from_session, a.since)
                run.usage(input_tokens=mu["in"], output_tokens=mu["out"],
                          token_source="provider",
                          reported_cost_usd=mu["cost"] or None,
                          model=run.model, provider=run.provider,
                          worker=run.worker)
                _runs.save_open(run, root)
                _emit(root, "resource.used", task_id=run.task_id,
                      run_id=run.run_id, cost_usd=run.reported_cost_usd,
                      tokens=run.output_tokens, token_source="provider",
                      model=run.model)
            # The usage receipt IS the metered call: charge the brake here
            # (single spend path — no double-count). Crossing completes + warns.
            out = run.snapshot()
            try:
                from budget import BudgetExceeded, FileBudget
                FileBudget(root).record(
                    tokens=sum(v for v in (run.input_tokens, run.output_tokens,
                                           run.cached_tokens) if v is not None),
                    cost=run.reported_cost_usd, label=run.run_id)
            except BudgetExceeded as ex:
                out["budget_warning"] = str(ex)[:160]
            if Q:
                print(f"{run.run_id} usage in={run.input_tokens} "
                      f"out={run.output_tokens} src={run.token_source}")
                return 0
            print(json.dumps(out, indent=1)[:2000])
            return 0
        try:
            snap = run.finish(a.result, a.validator)
        except ValueError as e:
            print(str(e)[:160])
            return 1
        if a.from_session:
            # Metered close: pull provider counts first, so finished runs
            # rarely stay null. Same honesty rules as usage (refuse unknown).
            import importlib.util as _ilu2
            mp2 = Path(__file__).resolve().parent / "meters" / "opencode_db.py"
            spec2 = _ilu2.spec_from_file_location("meters_db2", mp2)
            if spec2 is None or spec2.loader is None:
                print("meters/opencode_db.py missing")
                return 1
            mod2 = _ilu2.module_from_spec(spec2)
            spec2.loader.exec_module(mod2)
            if not mod2.session_totals(a.from_session).get("found"):
                print(f"unknown session in store: {a.from_session}")
                return 1
            mu2 = mod2.message_usage(a.from_session, a.since)
            snap["input_tokens"] = mu2["in"]
            snap["output_tokens"] = mu2["out"]
            snap["token_source"] = "provider"
            snap["reported_cost_usd"] = mu2["cost"] or None
            _runs.append_finished(run, root, snap_override=snap)
        else:
            _runs.append_finished(run, root)
        _emit(root, "run.finished", task_id=run.task_id, run_id=run.run_id,
              outcome=a.result, elapsed_ms=snap["elapsed_ms"],
              cost_usd=run.reported_cost_usd, validator=a.validator)
        if Q:
            print(f"{run.run_id} {a.result} {snap['elapsed_ms']}ms")
            return 0
        print(json.dumps(snap, indent=1)[:2000])
        return 0

    if a.cmd == "budget":
        from budget import BudgetExceeded, FileBudget
        b = FileBudget(root)
        if a.op == "set":
            try:
                usd = float(a.usd) if a.usd is not None else None
                toks = int(float(a.tokens)) if a.tokens is not None else None
            except ValueError:
                print("unparseable --usd/--tokens (must be numbers)")
                return 1
            b.set_caps(usd, toks)
            print(json.dumps({"caps": b.snapshot()}))
            return 0
        if a.op == "show":
            print(json.dumps(b.snapshot(), indent=1))
            return 0
        if a.op == "record":
            try:
                usd = float(a.usd) if a.usd is not None else None
                toks = int(float(a.tokens)) if a.tokens is not None else 0
            except ValueError:
                print("unparseable --usd/--tokens (must be numbers)")
                return 1
            try:
                b.record(tokens=toks, cost=usd, label=a.label)
            except BudgetExceeded as ex:
                print(str(ex)[:200])
                return 1
            print(json.dumps(b.snapshot(a.label)))
            return 0
        try:
            b.check(a.label or "budget check")
        except BudgetExceeded as ex:
            print(str(ex)[:200])
            return 1
        print(json.dumps({"exhausted": False, **b.snapshot(a.label)}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

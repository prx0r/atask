#!/usr/bin/env python3
"""acheck.py — self-audit for A-task nativeness. Stdlib only.

  python3 acheck.py [--dir .atask] [--stale-hours 24]

Exit 0 = native. Exit 1 = findings listed (one per line, machine-readable).
Checks: schema keys, lifecycle values, blocked_by refs resolve,
DONE -> report + resolvable sha256: receipt + 5-section report,
REPORTED -> report exists, EXECUTING -> fresh a-log (else STALE).
Read-only: never writes, never deletes.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atask import STATUS, REQUIRED, resolve

# Required report sections (numbered or bare headers).
REPORT_SECTIONS = ("claim", "evidence", "self-review", "needs", "cost")


def _report_sections(p: Path) -> list[str]:
    """Missing report sections (empty = compliant). .md only."""
    import re as _re
    if p.suffix != ".md":
        return []
    try:
        heads = set(m.group(1).lower() for m in
                    _re.finditer(r"^#+\s*(?:\d+\.\s*)?([\w-]+)",
                                 p.read_text(), _re.M))
    except Exception:
        return [f"unreadable report: {p.name}"]
    return [f"report missing section: {s}" for s in REPORT_SECTIONS
            if s not in heads]


def check(root: Path, stale_hours: float = 24) -> list[str]:
    root = Path(root)
    findings: list[str] = []
    q = root / "tasks.jsonl"
    if not q.exists():
        return [f"queue missing: {q} (run atask.py init)"]
    recs = [json.loads(l) for l in q.read_text().splitlines() if l.strip()]
    by_id = {r.get("id"): r for r in recs if isinstance(r, dict)}
    now = time.time()
    for i, r in enumerate(recs):
        tag = r.get("id", f"line{i}") if isinstance(r, dict) else f"line{i}"
        if not isinstance(r, dict):
            findings.append(f"{tag}: record is not an object")
            continue
        for k in REQUIRED:
            if not r.get(k):
                findings.append(f"{tag}: missing {k}")
        if r.get("status") not in STATUS:
            findings.append(f"{tag}: bad status {r.get('status')!r}")
        for b in (r.get("blocked_by") or []):
            if b not in by_id:
                findings.append(f"{tag}: dangling blocked_by {b!r}")
        st = r.get("status")
        if st in ("DONE", "REPORTED"):
            rr = r.get("report_ref", "")
            if not rr:
                findings.append(f"{tag}: {st} without report_ref")
            elif resolve(rr, root) is None:
                findings.append(f"{tag}: report_ref unresolvable: {rr}"[:160])
            else:
                findings += [f"{tag}: {e}"
                             for e in _report_sections(resolve(rr, root))]
            if st == "DONE":
                vr = r.get("validation_ref", "")
                if not vr:
                    findings.append(f"{tag}: DONE without validation_ref")
                elif not vr.startswith("sha256:") or resolve(vr, root) is None:
                    findings.append(f"{tag}: validation_ref unresolvable: {vr}"[:160])
        if st == "EXECUTING":
            lp = root / "a-logs" / f"{r.get('id')}.jsonl"
            if not lp.exists() or not lp.read_text().strip():
                findings.append(f"{tag}: EXECUTING with no a-log")
            elif now - lp.stat().st_mtime > stale_hours * 3600:
                findings.append(f"{tag}: STALE (no a-log in {stale_hours}h)")
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="acheck.py")
    ap.add_argument("--dir", default=".atask")
    ap.add_argument("--stale-hours", type=float, default=24)
    a = ap.parse_args(argv)
    findings = check(Path(a.dir), a.stale_hours)
    for f in findings or []:
        print(f)
    print(f"acheck: {len(findings)} findings over {a.dir}/tasks.jsonl")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

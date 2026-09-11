#!/usr/bin/env python3
"""frequencies.py — first thing that learns: choice frequencies per
question kind from presses + human.choice events. Stdlib only.

  python3 meters/frequencies.py --dir .atask
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from events import read as eread
from press import read as pread


def table(root: str | Path) -> dict:
    root = Path(root)
    by_kind: dict[str, Counter] = {}
    recs: dict[str, int] = Counter()
    for r in pread(root):
        q = (r.get("context") or {}).get("question") or {}
        kind = q.get("kind", "?")
        out = (r.get("outcome") or {})
        by_kind.setdefault(kind, Counter())[out.get("action", "?")] += 1
        recs[out.get("action", "?")] += 1
    for e in eread(root, "human.choice"):
        by_kind.setdefault(e.get("kind", "?"), Counter())["choice"] += 1
    return {"by_kind": {k: dict(v) for k, v in by_kind.items()},
            "actions": dict(recs)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="frequencies.py")
    ap.add_argument("--dir", default=".atask")
    a = ap.parse_args(argv)
    print(json.dumps(table(a.dir), indent=1, sort_keys=True)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

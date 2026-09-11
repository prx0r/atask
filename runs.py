"""Run receipts: content-addressed proof that a run happened. Stdlib only.

run_id = sha256(canonical_json(content)) where content EXCLUDES volatile fields
(timestamps, hostnames, latencies, wall times). Same inputs => same run_id, any
machine, any year. Volatile fields live BESIDE the id inside the receipt.

Receipts land in runs/<run_id>.json. Verification recomputes the id from
content — mismatch means tampering or drift, never "probably fine".
"""
from __future__ import annotations
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

VOLATILE = {"ts", "timestamp", "started_at", "finished_at", "elapsed_s",
            "elapsed_ms", "wall_ms", "hostname", "host", "duration_s"}


def canonical(content: dict) -> str:
    stable = {k: v for k, v in content.items() if k not in VOLATILE}
    return json.dumps(stable, sort_keys=True, default=str)


def run_id(content: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical(content).encode()).hexdigest()


def new_receipt(kind: str, content: dict) -> dict:
    body = dict(content)
    body["kind"] = kind
    rid = run_id(body)
    return {"run_id": rid, "ts": time.time(), "kind": kind, "content": body}


def save(receipt: dict, root: str | Path = "runs") -> Path:
    d = Path(root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / (receipt["run_id"].replace(":", "_") + ".json")
    p.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    return p


def verify(receipt: dict) -> bool:
    return run_id(receipt.get("content", {})) == receipt.get("run_id")


def verify_file(path: str | Path) -> bool:
    return verify(json.loads(Path(path).read_text()))


def verify_all(root: str | Path = "runs") -> dict:
    """Ledger audit: verify every receipt file under root."""
    ok, bad, files = 0, [], sorted(Path(root).glob("sha256_*.json"))
    for f in files:
        try:
            if verify_file(f):
                ok += 1
            else:
                bad.append(f.name)
        except Exception as e:
            bad.append(f"{f.name} ({e})"[:100])
    return {"files": len(files), "valid": ok, "invalid": bad}


@dataclass
class Run:
    """One execution attempt at a task. Measurement is environment state:
    wall clock says WHEN, monotonic clock says HOW LONG (NTP-immune).
    Counters feed the BATS-style resource block; caps live on the goal
    as context, never as kernel refusal."""
    task_id: str
    run_id: str = ""
    attempt: int = 1
    started_at: float = field(default_factory=time.time)
    started_mono_ns: int = field(default_factory=time.monotonic_ns)
    spent_usd: float = 0.0
    tokens_used: int = 0
    tool_calls: int = 0
    finished: bool = False
    outcome: str = ""

    def __post_init__(self):
        if not self.run_id:
            import uuid as _uuid
            self.run_id = "r-" + _uuid.uuid4().hex[:8]

    def note(self, cost_usd: float = 0.0, tokens: int = 0, tools: int = 0):
        self.spent_usd = round(self.spent_usd + cost_usd, 6)
        self.tokens_used += int(tokens)
        self.tool_calls += int(tools)
        return self.snapshot()

    def elapsed_ms(self) -> int:
        return (time.monotonic_ns() - self.started_mono_ns) // 1_000_000

    def finish(self, outcome: str) -> dict:
        self.finished = True
        self.outcome = outcome
        return self.snapshot()

    def snapshot(self) -> dict:
        d = asdict(self)
        d["elapsed_ms"] = self.elapsed_ms()
        return d


if __name__ == "__main__":
    import sys as _sys
    rep = verify_all(_sys.argv[1] if len(_sys.argv) > 1 else "runs")
    print(f"{rep['valid']}/{rep['files']} valid")
    for b in rep["invalid"]:
        print(f"  BAD: {b}")
    raise SystemExit(0 if not rep["invalid"] else 1)

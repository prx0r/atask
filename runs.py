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
    if p.exists():
        try:
            prior = json.loads(p.read_text())
            # Same content id + same stable content = rerun: leave the file
            # untouched (mtime clean) instead of churning timestamps.
            if (prior.get("run_id") == receipt.get("run_id")
                    and canonical(prior.get("content", {}))
                    == canonical(receipt.get("content", {}))):
                return p
        except Exception:
            pass
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
    """One execution attempt at a task (the A-RUN measurement primitive).
    Wall clock says WHEN, monotonic clock says HOW LONG (NTP-immune).
    Token counts are facts with a source; unknown stays null, never
    estimated silently. Cost is REPORTED (providers change prices);
    analytics re-derives from model+tokens. Results: running/failed/
    validated/abandoned."""
    task_id: str
    run_id: str = ""
    attempt: int = 1
    started_at: float = field(default_factory=time.time)
    started_mono_ns: int = field(default_factory=time.monotonic_ns)
    ended_at: float | None = None
    duration_ms: int | None = None
    worker: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    token_source: str = "unknown"
    reported_cost_usd: float | None = None
    # Legacy spend counters (kept: log --cost/--tokens charges these).
    spent_usd: float = 0.0
    tokens_used: int = 0
    tool_calls: int = 0
    result: str = "running"
    validator: str = ""

    TOKEN_SOURCES = ("provider", "gateway", "agent", "estimated", "unknown")
    # Worker-declared outcomes only. "validated" is NEVER worker-set: it is
    # derived downstream as (run completed + subsequent validator.passed).
    RESULTS = ("running", "completed", "failed", "abandoned")

    def __post_init__(self):
        if not self.run_id:
            import uuid as _uuid
            self.run_id = "r-" + _uuid.uuid4().hex[:8]
        if self.token_source not in self.TOKEN_SOURCES:
            raise ValueError(f"bad token_source (choose: {self.TOKEN_SOURCES})")
        if self.result not in self.RESULTS:
            raise ValueError(f"bad result (choose: {self.RESULTS})")

    def note(self, cost_usd: float = 0.0, tokens: int = 0, tools: int = 0):
        self.spent_usd = round(self.spent_usd + cost_usd, 6)
        self.tokens_used += int(tokens)
        self.tool_calls += int(tools)
        return self.snapshot()

    def usage(self, input_tokens: int | None = None,
              output_tokens: int | None = None,
              cached_tokens: int | None = None,
              token_source: str = "agent",
              reported_cost_usd: float | None = None,
              model: str = "", provider: str = "", worker: str = ""):
        """Worker-reported usage receipt. Nulls stay null (honest unknown)."""
        if token_source not in self.TOKEN_SOURCES:
            raise ValueError(f"bad token_source (choose: {self.TOKEN_SOURCES})")
        if input_tokens is not None:
            self.input_tokens = int(input_tokens)
        if output_tokens is not None:
            self.output_tokens = int(output_tokens)
        if cached_tokens is not None:
            self.cached_tokens = int(cached_tokens)
        self.token_source = token_source
        if reported_cost_usd is not None:
            self.reported_cost_usd = float(reported_cost_usd)
        if model:
            self.model = model
        if provider:
            self.provider = provider
        if worker:
            self.worker = worker
        return self.snapshot()

    def elapsed_ms(self) -> int:
        if self.duration_ms is not None:
            return self.duration_ms
        now = time.monotonic_ns()
        if now < self.started_mono_ns:
            # Rebooted mid-run: monotonic incomparable, fall back to wall.
            base = self.ended_at or time.time()
            return max(0, int((base - self.started_at) * 1000))
        return (now - self.started_mono_ns) // 1_000_000

    def finish(self, result: str, validator: str = "") -> dict:
        if result not in self.RESULTS or result in ("running", "validated"):
            raise ValueError("bad result (worker chooses: completed/failed/abandoned)")
        self.ended_at = time.time()
        self.duration_ms = self.elapsed_ms()
        self.result = result
        self.validator = validator[:200]
        return self.snapshot()

    def snapshot(self) -> dict:
        d = asdict(self)
        d["elapsed_ms"] = self.elapsed_ms()
        d.pop("TOKEN_SOURCES", None)
        d.pop("RESULTS", None)
        return d


RUNS_LOG = "runs.jsonl"
OPEN_DIR = "runs-open"


def open_runs_dir(root: str | Path) -> Path:
    p = Path(root) / OPEN_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_open(run: Run, root: str | Path) -> Path:
    p = open_runs_dir(root) / f"{run.run_id}.json"
    p.write_text(json.dumps(run.snapshot(), sort_keys=True))
    return p


def load_open(run_id: str, root: str | Path) -> Run | None:
    p = Path(root) / OPEN_DIR / f"{run_id}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    d.pop("elapsed_ms", None)
    return Run(**{k: v for k, v in d.items() if k in Run.__dataclass_fields__})


def list_open(root: str | Path, task_id: str = "") -> list[dict]:
    out = []
    d = Path(root) / OPEN_DIR
    if not d.is_dir():
        return out
    for p in sorted(d.glob("r-*.json")):
        r = load_open(p.stem, root)
        if r and (not task_id or r.task_id == task_id):
            out.append(r.snapshot())
    return out


def append_finished(run: Run, root: str | Path) -> dict:
    """Crash-safe close: append final record, remove the open stub."""
    snap = run.snapshot()
    with open(Path(root) / RUNS_LOG, "a") as f:
        f.write(json.dumps(snap, sort_keys=True) + "\n")
    try:
        (Path(root) / OPEN_DIR / f"{run.run_id}.json").unlink()
    except OSError:
        pass
    return snap


def read_runs(root: str | Path, task_id: str = "") -> list[dict]:
    """Finished runs (optional task filter). Missing file = []."""
    p = Path(root) / RUNS_LOG
    if not p.exists():
        return []
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return [r for r in rows if not task_id or r.get("task_id") == task_id]


def task_run_stats(root: str | Path, task_id: str) -> dict:
    """Derived per-task totals from A-RUNs ONLY (sole accounting source):
    duration/tokens/cost = Σ runs; attempts = n runs."""
    runs = read_runs(root, task_id)
    tot = {"attempts": len(runs), "elapsed_ms": 0, "input_tokens": 0,
           "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0,
           "results": [r.get("result", "") for r in runs],
           "last_result": runs[-1].get("result", "") if runs else "",
           "tokens_known": True}
    for r in runs:
        tot["elapsed_ms"] += int(r.get("duration_ms") or 0)
        for k in ("input_tokens", "output_tokens", "cached_tokens"):
            v = r.get(k)
            if v is None:
                tot["tokens_known"] = False
            else:
                tot[k] += int(v)
        if r.get("reported_cost_usd") is not None:
            tot["cost_usd"] = round(tot["cost_usd"] + float(r["reported_cost_usd"]), 6)
    return tot


if __name__ == "__main__":
    import sys as _sys
    rep = verify_all(_sys.argv[1] if len(_sys.argv) > 1 else "runs")
    print(f"{rep['valid']}/{rep['files']} valid")
    for b in rep["invalid"]:
        print(f"  BAD: {b}")
    raise SystemExit(0 if not rep["invalid"] else 1)

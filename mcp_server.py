#!/usr/bin/env python3
"""mcp_server.py — atask as an MCP server (stdio JSON-RPC, stdlib only).

The control language in seven verbs. Five are reads (the agent's eyes);
two live on the human side (digits) and are documented, not exposed —
the agent answers its own questions through no tool here.

  a_goal   goal acceptance mapped vs done (exit-truth for the build)
  a_status achieved/missing/ready/open/spent (start here, every turn)
  a_task   READY orders with acceptance (drain these)
  a_proof  GO/NOGO + missing for a task (green is the only path to DONE)
  a_ask    open questions: kind/options/recommendation (all the agent may ask)
  a_answer HUMAN SIDE: digits 0/4/5/6/7 (accept/pick/approve/deny/tell)
  a_done   HUMAN+AGENT SIDE: stoplight green + pulse promotes to DONE

System instruction for the agent (the whole harness, nearly):

  You are A-native. Work autonomously toward the current A-goal.
  Decompose however you judge. Never claim completion without
  externally verifiable proof. Never ask an open-ended question:
  reduce human input to a bounded A-question (kind + options +
  recommendation). Continue all work that does not depend on the answer.

  python3 mcp_server.py [--dir .atask]   # JSON-RPC 2.0, newline stdio
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atask import goal_check, load, open_h, ready, stoplight, verify
from driver import spent_totals, zoom
from press import read as presses_read

ROOT = Path(".atask")

VERBS = {
    "a_goal": "Goal acceptance mapped vs done. Exit-truth for the build.",
    "a_status": "Achieved/missing/ready/open humans/spent. Start here every turn.",
    "a_task": "READY orders with acceptance criteria. Drain these.",
    "a_proof": "GO/NOGO + missing reasons for a task id. Green is the only path to DONE.",
    "a_ask": "Open questions (kind/options/recommendation). All the agent may ask the human.",
    "a_answer": "HUMAN SIDE (digits 0/4/5/6/7): accept/pick/approve/deny/tell. Not callable here.",
    "a_done": "HUMAN+AGENT SIDE: REPORTED + green stoplight, pulse promotes. Not callable here.",
}

READABLE = ("a_goal", "a_status", "a_task", "a_proof", "a_ask")


def _tool_defs() -> list[dict]:
    def props(**kw):
        return {"type": "object", "properties": kw}
    schemas = {
        "a_goal": props(),
        "a_status": props(),
        "a_task": props(status={"type": "string"}),
        "a_proof": props(id={"type": "string"}),
        "a_ask": props(),
    }
    return [{"name": n, "description": VERBS[n], "inputSchema": schemas[n]}
            for n in READABLE]


def _call(name: str, args: dict):
    if name == "a_goal":
        return goal_check(ROOT)
    if name == "a_status":
        z = zoom(ROOT)
        z["spent"] = spent_totals(ROOT)
        z["findings"] = len(verify(ROOT))
        return z
    if name == "a_task":
        recs = load(ROOT / "tasks.jsonl")
        st = (args or {}).get("status")
        if st == "READY":
            recs = ready(recs)
        elif st:
            recs = [r for r in recs if r.get("status") == st]
        return [{"id": r["id"], "status": r.get("status"),
                 "summary": r.get("summary", "")[:200],
                 "acceptance": (r.get("acceptance") or [])[:5]} for r in recs]
    if name == "a_proof":
        return stoplight((args or {})["id"], ROOT)
    if name == "a_ask":
        return [{"id": h["id"], "task": h.get("task"), "kind": h.get("kind"),
                 "need": h.get("need", "")[:300], "options": h.get("options", []),
                 "recommendation": h.get("recommendation", "")[:200]}
                for h in open_h(ROOT)]
    if name in ("a_answer", "a_done"):
        return {"human_side": True, "how": VERBS[name]}
    raise ValueError(f"unknown verb: {name} (see: {', '.join(VERBS)})")


def _resp(rid, result=None, error=None) -> dict:
    r = {"jsonrpc": "2.0", "id": rid}
    r["result" if error is None else "error"] = result if error is None else error
    return r


def _text(obj) -> dict:
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, indent=1, default=str)[:4000]}]}


def serve() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params", {}) or {}
        try:
            if method == "initialize":
                out = {"protocolVersion": "2024-11-05",
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "atask", "version": "2"}}
            elif method == "tools/list":
                out = {"tools": _tool_defs()}
            elif method == "tools/call":
                out = _text(_call(params.get("name", ""), params.get("arguments", {}) or {}))
            else:
                raise ValueError(f"unknown method: {method}")
            print(json.dumps(_resp(mid, result=out)), flush=True)
        except Exception as e:
            print(json.dumps(_resp(mid, error={"code": -32000, "message": str(e)[:200]})), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    global ROOT
    ap = argparse.ArgumentParser(prog="mcp_server.py")
    ap.add_argument("--dir", default=".atask")
    a = ap.parse_args(argv)
    ROOT = Path(a.dir)
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""mcp_server.py — atask as an MCP server (stdio JSON-RPC, stdlib only).

Lets any MCP-capable agent speak A-language upon clone, no install.
Read-only surface: goal/queue/ready/stoplight/policy/budget/agents/presses.
NOTHING here mutates: no approvals, no status writes, no spending, no
presses. Writes stay on the agent's CLI and the human's digits, where
both can see them.

  python3 mcp_server.py [--dir .atask]   # JSON-RPC 2.0, newline-delimited, stdio

opencode config:
  {"mcp": {"atask": {"type": "local",
    "command": ["python3", "/path/to/atask/mcp_server.py", "--dir", "/path/to/.atask"]}}}
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atask import (agents_list, goal_check, load, open_h, policy_check,
                   ready, stoplight, verify)
from budget import FileBudget
from driver import zoom
from press import read as presses_read

ROOT = Path(".atask")


def _tool_defs() -> list[dict]:
    def props(**kw):
        return {"type": "object", "properties": kw}
    return [
        {"name": "atask_zoom",
         "description": "Achieved-vs-missing: done/missing/ready/open humans/goal/budget. Start here.",
         "inputSchema": props()},
        {"name": "atask_ready",
         "description": "Actionable tasks (deps satisfied) with acceptance. Drain these.",
         "inputSchema": props()},
        {"name": "atask_list",
         "description": "List queue tasks, optional status filter.",
         "inputSchema": props(status={"type": "string"})},
        {"name": "atask_stoplight",
         "description": "GO/NOGO + missing reasons for a task id. Green is the only path to DONE.",
         "inputSchema": props(id={"type": "string"})},
        {"name": "atask_goal",
         "description": "Goal acceptance mapped vs done. exit-truth for the build.",
         "inputSchema": props()},
        {"name": "atask_humans",
         "description": "Open human tasks needing digits 4/5/6/7. The only things the agent may ask.",
         "inputSchema": props()},
        {"name": "atask_policy",
         "description": "Screen an action string: CLEAR|PROHIBITED + route A|H|M.",
         "inputSchema": props(action={"type": "string"})},
        {"name": "atask_budget",
         "description": "Spend snapshot + remaining. Exhausted refuses the next pulse.",
         "inputSchema": props()},
        {"name": "atask_agents",
         "description": "Delegation lanes (name/description/model). Cheapest-capable first.",
         "inputSchema": props()},
        {"name": "atask_verify",
         "description": "Queue audit findings. Empty = clean.",
         "inputSchema": props()},
        {"name": "atask_presses",
         "description": "Recent press rows (digit sequences). Limit param, newest last.",
         "inputSchema": props(limit={"type": "integer"})},
    ]


def _text(obj) -> dict:
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, indent=1, default=str)[:4000]}]}


def _call(name: str, args: dict):
    if name == "atask_zoom":
        z = zoom(ROOT)
        z["budget"] = FileBudget(ROOT).snapshot()
        return z
    if name == "atask_ready":
        return [{"id": r["id"], "summary": r.get("summary", "")[:200],
                 "acceptance": (r.get("acceptance") or [])[:5]}
                for r in ready(load(ROOT / "tasks.jsonl"))]
    if name == "atask_list":
        recs = load(ROOT / "tasks.jsonl")
        st = (args or {}).get("status")
        if st:
            recs = [r for r in recs if r.get("status") == st]
        return [{"id": r["id"], "status": r.get("status"),
                 "summary": r.get("summary", "")[:120]} for r in recs]
    if name == "atask_stoplight":
        return stoplight((args or {})["id"], ROOT)
    if name == "atask_goal":
        return goal_check(ROOT)
    if name == "atask_humans":
        return [{"id": h["id"], "task": h.get("task"), "need": h.get("need", "")[:300],
                 "options": h.get("options", []),
                 "recommendation": h.get("recommendation", "")[:200]}
                for h in open_h(ROOT)]
    if name == "atask_policy":
        return policy_check(ROOT, (args or {}).get("action", ""))
    if name == "atask_budget":
        return {"snapshot": FileBudget(ROOT).snapshot(),
                "advertise": FileBudget(ROOT).advertise()}
    if name == "atask_agents":
        return agents_list(ROOT)
    if name == "atask_verify":
        return {"findings": verify(ROOT)}
    if name == "atask_presses":
        rows = presses_read(ROOT)
        try:
            lim = int((args or {}).get("limit", 20) or 20)
        except (TypeError, ValueError):
            lim = 20
        return rows[-lim:]
    raise ValueError(f"unknown tool: {name}")


def _resp(rid, result=None, error=None) -> dict:
    r = {"jsonrpc": "2.0", "id": rid}
    r["result" if error is None else "error"] = result if error is None else error
    return r


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
                       "capabilities": {"tools": {}}, "serverInfo": {"name": "atask", "version": "1"}}
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

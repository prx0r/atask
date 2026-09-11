#!/usr/bin/env python3
"""hermes_board.py — L1 adapter: atask lanes onto Hermes kanban boards.
Stdlib only (sqlite3), read-only except explicit push/claim. The board
stays Hermes-owned; atask only writes tasks it created (idempotency key
= atask task id) and reads completion back.

Boards live at /root/.hermes/kanban/boards/<slug>/kanban.db, table tasks
(id, title, body, assignee, status, ...). Statuses observed: ready,
blocked, triage, done.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import time
from pathlib import Path

BOARDS = Path("/root/.hermes/kanban/boards")


def _db(board: str, base: Path = BOARDS) -> sqlite3.Connection:
    p = Path(base) / board / "kanban.db"
    if not p.exists():
        raise ValueError(f"unknown board: {board}")
    db = sqlite3.connect(str(p), timeout=30)
    db.row_factory = sqlite3.Row
    return db


def push(board: str, task_id: str, title: str, body: str = "",
         assignee: str = "builder", base: Path = BOARDS) -> dict:
    """Idempotent delegate: same task_id twice = one row (updated)."""
    db = _db(board, base)
    now = time.time()
    row = db.execute("select id from tasks where idempotency_key=?",
                     (task_id,)).fetchone()
    if row:
        db.execute("update tasks set title=?, body=?, assignee=?,"
                   " status='ready' where idempotency_key=?",
                   (title[:200], body[:2000], assignee, task_id))
    else:
        db.execute("insert into tasks (title, body, assignee, status,"
                   " created_by, created_at, idempotency_key) values"
                   " (?,?,?,?,?,?,?)",
                   (title[:200], body[:2000], assignee, "ready",
                    "atask", now, task_id))
    db.commit()
    rid = db.execute("select id, status from tasks where idempotency_key=?",
                     (task_id,)).fetchone()
    db.close()
    return {"board": board, "row_id": rid["id"], "status": rid["status"],
            "task_id": task_id}


def poll(board: str, task_id: str, base: Path = BOARDS) -> dict:
    """Read back completion. Done rows carry result text for fulfillment."""
    db = _db(board, base)
    r = db.execute("select id, status, result, assignee from tasks where"
                   " idempotency_key=?", (task_id,)).fetchone()
    db.close()
    if not r:
        return {"found": False, "task_id": task_id}
    return {"found": True, "task_id": task_id, "status": r["status"],
            "result": (r["result"] or "")[:1000], "assignee": r["assignee"]}


def claim(board: str, task_id: str, worker: str,
          base: Path = BOARDS) -> dict:
    """Second worker takes the row (contention path). Fails if taken."""
    db = _db(board, base)
    r = db.execute("select assignee, status from tasks where"
                   " idempotency_key=?", (task_id,)).fetchone()
    if not r:
        db.close()
        raise ValueError(f"unknown delegated task: {task_id}")
    if r["status"] != "ready":
        db.close()
        return {"claimed": False, "reason": f"status={r['status']}"}
    db.execute("update tasks set assignee=?, status='blocked' where"
               " idempotency_key=? and status='ready'", (worker, task_id))
    db.commit()
    ok = db.total_changes > 0
    db.close()
    return {"claimed": ok, "worker": worker if ok else r["assignee"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hermes_board.py")
    ap.add_argument("--boards", default=str(BOARDS))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push")
    p.add_argument("board")
    p.add_argument("--task", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--body", default="")
    p.add_argument("--assignee", default="builder")
    p = sub.add_parser("poll")
    p.add_argument("board")
    p.add_argument("--task", required=True)
    p = sub.add_parser("claim")
    p.add_argument("board")
    p.add_argument("--task", required=True)
    p.add_argument("--worker", required=True)
    a = ap.parse_args(argv)
    base = Path(a.boards)
    try:
        if a.cmd == "push":
            print(json.dumps(push(a.board, a.task, a.title, a.body,
                                  a.assignee, base), indent=1)[:2000])
        elif a.cmd == "poll":
            print(json.dumps(poll(a.board, a.task, base), indent=1)[:2000])
        else:
            print(json.dumps(claim(a.board, a.task, a.worker, base),
                             indent=1)[:2000])
    except ValueError as e:
        print(json.dumps({"error": str(e)[:200]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""chain.py — digit grammar for the 10-key instrument. Stdlib only.

"294" -> [ZOOM, FIX, PICK#4]. Only 4 (PICK) consumes a following digit as
its argument. Anything else is a ValueError, never a guess (a misread
press must fail loudly, not execute something else).
"""
from __future__ import annotations
import json
from functools import lru_cache as _lru
from pathlib import Path

ARG_KEYS = {"4"}
ALL_KEYS = set("0123456789")

ROOT = Path(__file__).resolve().parent


@_lru(maxsize=1)
def key_defs() -> dict:
    return json.loads((ROOT / "keys.json").read_text())["keys"]


def parse(chain: str) -> list[dict]:
    """Parse a digit chain into [{key, name, arg}]. Raises ValueError."""
    if not chain or not isinstance(chain, str):
        raise ValueError("chain must be a non-empty digit string")
    bad = [c for c in chain if c not in ALL_KEYS]
    if bad:
        raise ValueError(f"not keys: {bad!r} in {chain!r}")
    defs = key_defs()
    out, i = [], 0
    while i < len(chain):
        k = chain[i]
        arg = None
        if k in ARG_KEYS:
            if i + 1 >= len(chain):
                raise ValueError(f"key {k} ({defs[k]['name']}) needs a digit after it")
            arg = int(chain[i + 1])
            i += 1
        out.append({"key": k, "name": defs[k]["name"], "arg": arg})
        i += 1
    return out


def describe(actions: list[dict]) -> str:
    """Human rendering of a parsed chain (for the dash)."""
    parts = []
    for a in actions:
        s = f"{a['key']} {a['name']}"
        if a["arg"] is not None:
            s += f"#{a['arg']}"
        parts.append(s)
    return " -> ".join(parts)

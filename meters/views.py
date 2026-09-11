"""views.py — L1 pydantic views over kernel run dicts. Requires pydantic,
which lives OUTSIDE the kernel (ifizzer invariant: grep pydantic kernel
files returns nothing — this file is meters/, not kernel).

Validates + types run records for analytics/API/UI without becoming a
prerequisite for autonomy.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ARun(BaseModel):
    id: str = Field(alias="run_id")
    task_id: str
    started_at: float
    ended_at: float | None = None
    duration_ms: int | None = None
    worker: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    token_source: Literal["provider", "gateway", "agent", "estimated",
                          "unknown"] = "unknown"
    reported_cost_usd: float | None = None
    result: Literal["running", "completed", "failed", "abandoned"]

    model_config = {"populate_by_name": True}


class RunReport(BaseModel):
    run: ARun
    tokens_known: bool
    cost_known: bool

    @classmethod
    def from_kernel(cls, snap: dict) -> "RunReport":
        run = ARun.model_validate({**snap, "id": snap.get("run_id", "")})
        return cls(run=run,
                   tokens_known=snap.get("input_tokens") is not None,
                   cost_known=snap.get("reported_cost_usd") is not None)

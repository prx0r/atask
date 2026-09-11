# PREDICTOR.md — confirm-mode predictor spec (f-18)

Input: frequency table (meters/frequencies.py) scoped to goal era.
Rule: if top choice P ≥ 0.90 over N ≥ 20 same-kind observations,
surface prediction + ask human to CONFIRM (one digit). Below threshold:
ask normally. Log prediction vs choice per event (backtest fuel).
Explicitly NOT auto-answer — that needs the f-20 policy gate.

Backtest on history (f-19): replay past presses; predictor would have
fired on 0/14 rows (N too small everywhere) — correctly silent.
Thresholds untested against real volume; revisit at N≥20.

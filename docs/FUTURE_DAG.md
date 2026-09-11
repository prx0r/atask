# FUTURE_DAG.md — 50 projected A-tasks (from 30-task history, 2026-09-11)

History shape: 26 DONE / 1 REJECTED / 1 REPORTED / 1 EXECUTING / 1 JUSTIFIED×2.
All depth 0, all flat — no branching ever used, no spawn depth, one
dependent ever (a-dep, ad hoc). The future DAG fixes that: diamonds,
fan-out builds, fan-in analyses.

```text
                    A: close current (4)
              f-01 f-02 f-03 f-04 (tag)
                          │
              ┌───────────┼───────────────┐
              ▼           ▼               ▼
   B: volume ×10     D: hermes ×6     G: harden ×4
   f-05…f-14         f-21…f-26        f-36…f-39
   (fan-out)         (adapter first)  (branch rule first)
      │                   │               │
      ▼                   │               │
   C: miner ×6 ◄──────────┘               │
   f-15…f-20                              │
   (needs volume)                         │
      │                                   │
      ├───────────────┐                   │
      ▼               ▼                   │
   E: autonomy ×4   H: studies ×11        │
   f-27…f-30        f-40…f-50             │
      │              (needs C)             │
      ▼                                   │
   F: money ×5 ◄──────────────────────────┘
   f-31…f-35 (needs batch + autonomy spend)
```

## Edge list (id: summary [blocked_by])

A — close current:
- f-01: promote a-map via pulse [a-map]
- f-02: first unattended cron tick verified [a-cron]
- f-03: contention proof green [a-contend]
- f-04: v0.1.0 tag pushed + branch rule live [a-tag]

B — volume, 10 real builds (all [f-04], fan-out):
- f-05: batch CSV mode for MetaCraft [f-04]
- f-06: gmail digest tool [f-04]
- f-07: changelog generator [f-04]
- f-08: uptime pinger [f-04]
- f-09: rss summarizer [f-04]
- f-10: invoice generator [f-04]
- f-11: habit tracker [f-04]
- f-12: bookmark search [f-04]
- f-13: meeting-notes formatter [f-04]
- f-14: price watcher [f-04]

C — Seed0 miner v1 (needs volume):
- f-15: choice-frequency table per question-kind [f-14]
- f-16: goal-era scoping convention [f-15]
- f-17: validator-fail dedupe contract [f-15]
- f-18: confirm-mode predictor [f-15, f-16]
- f-19: predictor backtest on history [f-18]
- f-20: auto-answer threshold policy [f-19]

D — Hermes integration:
- f-21: lane adapter delegate→board [f-04]
- f-22: poller fulfills back to queue [f-21]
- f-23: metered wrapper closes null-token column [f-21]
- f-24: venue-auth gaps become h-tasks [f-21]
- f-25: second worker contention, live [f-22, f-03]
- f-26: mresolve-grant treasury edge [f-22]

E — autonomy:
- f-27: standing-policy ratchet [f-20]
- f-28: weekly digest rollups [f-19]
- f-29: 7-day overnight streak [f-02]
- f-30: confirm→auto on spend≤cap [f-20, f-26]

F — money (needs batch + spend autonomy):
- f-31: batch mode ships (dup of f-05? no: SELL it) — reframe: Gumroad
  packaging [f-05]
- f-32: Gumroad listing live [f-31]
- f-33: first dollar [f-32]
- f-34: hosted API shape [f-33]
- f-35: first $19 sub [f-34]

G — hardening:
- f-36: branch discipline enforced [f-04]
- f-37: changelog generation [f-36]
- f-38: second repo adopts atask [f-36]
- f-39: v0.2.0 release [f-37, f-38, f-20]

H — optimization studies (need miner):
- f-40: plan-shape A/B design [f-19]
- f-41: run both shapes ×5 missions [f-40]
- f-42: analyze shape vs time×tokens×pass [f-41]
- f-43: bandit router prototype [f-42]
- f-44: offline bandit replay [f-43]
- f-45: live shadow routing [f-44]
- f-46: forecast baseline [f-42]
- f-47: forecast calibration [f-46]
- f-48: context-rot study [f-19]
- f-49: token-efficacy per task family [f-42]
- f-50: mission-forecast demo (fan-in) [f-45, f-47, f-49]

## Structural notes

- Critical path: f-04 → f-14 → f-15 → f-18 → f-19 → f-20 → f-30 ≈
  longest chain (7). Everything else parallelizes.
- First real diamond: f-25 (adapter × contention). First fan-in: f-39,
  f-50. History has zero of both — that is the growth.
- Depth stays ≤2; MAX_DEPTH 8 never tested. A deep-decomposition
  mission should appear in wave B (pick f-10, force 3-level spawn).
- 50 tasks × ~1 run each ≈ the 100-run dataset threshold where plan-shape
  and bandit studies stop being anecdote.

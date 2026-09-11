# Test results ledger (append-only, newest first)

## 2026-09-11 — self-hosted autonomous run (session `selfhost1`, GOAL_DONE)
- Dogfooded the kernel: `.atask/` queue in-repo (gitignored), goal with
  3 acceptance, 3 tasks worked start→DONE via CLI + pulses. acheck 0,
  verify 0, `goal check` exit 0, digest recorded.
- Suite: **51/51 green** (4 new `TestAdversarial`).
- Kernel strengthening from adversarial work: DONE gate now recomputes
  receipt ids (existence≠integrity); tampered receipt refused with
  `TAMPERED` marker at REPORTED→DONE.
- Stoplight caught a real staleness mid-run: a-selfhost evidence went red
  because a-ledger moved before promotion — re-ran green after the lane
  settled. Evidence-at-promotion-time, not claim-time. Working as designed.
- Concurrency: 2 parallel pulses → both exit 0, exactly one DONE record,
  queue loads clean. Re-pulse idempotent (promotes [], HALT-LEGAL).

## 2026-09-11 — event substrate session (commit `3bcf80f` + audit work)
- Suite: **47/47 green**, stable across 3 consecutive runs (~0.5s each).
  Raw logs: `tests/logs/run{1,2,3}-*.log` (gitignored). Receipt:
  `tests/logs/sha256_9c6795…13c942.json` (verify via `runs.verify_file`).
- E2E `/tmp/atask-audit`: 17-event stream over 7 types; validator-fail
  correctly re-emits per pulse (dedupe is L1's job, not the kernel's).
- `TestEventAudit` (new, permanent) asserts stream invariants: mono_ns
  ordering, ask→choice pairing, start→finish pairing, single goal.done,
  legal lifecycle edges, DONE⇒validator.passed.
- Defects caught by the audit before commit (3):
  1. `task.status` schema drift (`from_status` vs `from`) → standardized `from`/`to`.
  2. `answer()` resume opened no run → now emits `run.started` + attempts+1.
  3. Two test flows demoted lanes (EXECUTING→JUSTIFIED, PAUSED→JUSTIFIED) →
     flows fixed; the gate was right both times.
- Known non-issues: `validator.failed` re-emits every pulse while stuck
  (append-only truth; L1 dedupes). `acheck --dir .atask` reports 1 finding
  when no state dir exists (correct: "run init").

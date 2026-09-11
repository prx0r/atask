# Test results ledger (append-only, newest first)

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

# Test results ledger (append-only, newest first)

## 2026-09-11 — proof-of-attempt gate (session `proofgate`, GOAL_DONE, 77/77)
- `escalate` now refuses untried tasks: ≥2 attempts + a-log lines + a
  FAILED checkable try (red evidence now, or validator.failed event).
  PHYSICAL/IDENTITY exempt (nothing to attempt). No WASM: stdlib rule
  over records the kernel keeps; evidence already executes. 6 new
  `TestPromotionProof` (untried/clean-attempts/red/validator-event/
  exempt/flap-farming).
- Migration cost was real: 12 old call sites had to earn their
  escalations. The audit caught two more of mine: helper demoting
  lanes, and the poisoned-probe pattern (failed evidence that can
  never turn green blocks promotion forever) → marker-probe pattern
  documented in `earn()`: probe red until the fix file lands.
- Design note for Seed0: flapping (status churn, no evidence) is now
  measurable as distinct from trying — log attempts with/without
  evidence as separate features.

## 2026-09-11 — peer review: process vs ideas (not going well, honestly)
Verdict: the kernel works; the process around it leaks. Ranked gaps:

1. AUTONOMY UNPROVEN. Every turn this entire history was operator-driven.
   Cron never configured, H-driver D1/D2/D3 open since seed0. The loop
   has never run unattended once. Nothing else matters until one
   overnight cron run completes, promotes, and logs without touch.
2. COMPLIANCE IS OPERATOR-DEPENDENT. The framework gates the queue, not
   the worker. Skipped a-logs, loose runs, and goal overwrites all
   happened outside any gate. Missing: make bypassing harder than
   complying (e.g. wrapper-only entry, goal history append-only).
3. GOAL ROTATION DESTROYS HISTORY. Single goal.json overwritten per run;
   old definitions survive only in ledger prose; covers_goal orphaned.
   Fix: goals.jsonl append-only with eras; miners scope by era.
4. FIVE OVERLAPPING LOGS. presses + events + pulse + runs.jsonl + a-logs
   record overlapping facts after we agreed on one stream. Consolidate
   or document the split (keypad dataset vs substrate vs ticks).
5. SOFT COVERS REMAIN. Required evidence is hard, but evidence-free
   a-log lines still count toward acceptance covers. A trivial required
   echo + trust covers passes. Decide: covers need evidence-bearing
   lines, or accept the two-tier proof explicitly.
6. BRAKE NEVER TESTED IN ANGER. Caps exist, enforcement tested with
   toy cents; no dogfood run ever set a real cap. Set one next run.
7. TOKEN THRIFT IS CHAT-DEEP. Tooling went quiet; my messages didn't
   until forced. This session: millions of tokens, $0.50+, framework
   tracked $0 until the last goal. Quiet mode must cover the operator
   (me), not just the CLI.
8. GREEN-THROUGH-CRUFT HAPPENED. Duplicate Run class shipped green.
   Lesson applied (schema-shape test), principle: prefer invariant
   tests (audit) over example tests.

What's genuinely going well: gates fired correctly on every real
violation (no false refuses logged); receipts+ledger discipline held
across 15+ commits; push hygiene (one-shot URLs, env cleared) held;
event/audit substrate caught bugs unit tests couldn't see. The
foundation is sound — the next 80% is volume + unattended operation,
not more kernel.

## 2026-09-11 — quiet + incremental session (GOAL_DONE, 71/71)
- `--quiet/-q` on all three CLIs: close-lines only, JSON stays in files.
  Adopted in my own runs above (one-liners vs blobs). Default output
  unchanged (tests parse JSON).
- Stolen from opencode's own logic: event-driven incremental reads.
  `meters since --state` checkpoints last message row; second read scans
  new rows only (3→1 in fixture test). Per-call O(new), never O(history).
- Steal summary: (1) session store as source of truth, (2) update on
  events not polls, (3) one summary file per session, (4) quiet terminal
  by default. All four now mirrored.
- Verdicts held: estimation 0.02x on stored text stands as FAIL.

## 2026-09-11 — token telemetry goal (session `tokens1`, GOAL_DONE)
- 7 tasks (research, alts, 5 verdicts) worked strictly: run-tracked,
  a-logged, receipted, pulsed to DONE. Suite **69/69**.
- Answer: tokens were null because no worker ever looked. `opencode.db`
  on-box meters everything (session + per-message tables). This session:
  2.5M in / 189K out / $0.52 at research time.
- Verdicts: ALT1 session totals PASS; ALT2 message-window PASS (149
  msgs/1.1M per 30m); ALT3 estimation FAIL on stored text (0.02x —
  valid only on true prompt text at call time); ALT4 delta WEAK PASS
  (session row lags ~45s; use ALT2 per run); ALT5 Hermes FAIL
  (sporadic debug dumps + live Bearer key in headers — flagged, owner
  must rotate; never ingest blindly).
- Adopted: `meters/opencode_db.py` (L1 adapter, read-only sqlite) +
  `run usage --from-session SES [--since MIN]` pulls provider counts
  into the run (unknown sessions refused, no silent zeros). Runs now
  show real tokens; digest spent reflects brake charges.
- Strictness note: caught myself skipping a-log discipline earlier in
  the day; this whole goal ran clean to prove the loop holds.

## 2026-09-11 — pull review: 13 commits, 68 tests, remote current
Remote `prx0r/atask` == local through `baf7bfb`. Suite 68/68 (~0.9s).
Reviewed the whole stack as if it arrived as one PR:

APPROVE with findings (all non-blocking, all logged below):
- Gate integrity is real: DONE-gated stoplight, receipt recompute,
  no trust-only tasks, ask-gate kinds, no worker self-validation.
  Three separate runs proved refusals fire on real violations.
- Measurement honesty held under pressure: nulls stayed null across
  8+ tracked runs; mono+wall dual clocks; append-only streams.
- Tests earned their keep: audit caught aliasing + rooting bugs,
  adversarial caught the existence≠integrity gap, e2e caught stale
  evidence. The suite tests the contract, not the code.

FINDINGS (critical eye):
1. No gate on the gate-makers: everything lands direct to main, review
   is post-hoc chat. Ironic for a control kernel. Fix: branch discipline
   + release tags starting v0.1.0 (next step, not this commit).
2. Single-goal rotation orphans old covers_goal (verify noise). Miners
   must scope rows by goal era; document the era convention.
3. validator.failed re-emits per stuck pulse (spam by design). No
   consumer contract written for dedupe — L1 needs one line: dedupe on
   (task_id, reasons-hash), keep first+latest.
4. "7 verbs" oversells: MCP exposes 5 tools; answer/done are digit-side.
   Rename docs to "5 tools + 2 human verbs" or expose read-only
   predictors for them later. Chose honesty in docs next pass.
5. Parallel writers append JSONL safely (O_APPEND) but task-id
   uniqueness is check-then-write (TOCTOU). Fine at 1-3 workers;
   re-test before any swarm.
6. Budget brake vs "kernel never refuses" remains the one principled
   exception — kept by explicit order, re-challenge quarterly.

VISIONARY BUILDS (ordered by payoff):
- V1 Seed0 miner: choice-frequency per (question-kind, options-shape).
  Smallest thing that learns. Runs on presses+events, zero kernel change.
- Hermes-kanban lane adapter: `delegate --to hermes/<board>` with the
  atask id as idempotency key; poller fulfills back. Proves multi-agent.
- Metered worker wrapper (Hermes-side): closes the null-token column
  with provider-reported usage. Turns anecdotes into a dataset.
- Plan-shape A/B: depth/branching/granularity vs time×tokens×pass.
  Needs ~100+ runs; start collecting the fields now (already logged).
- Release + changelog discipline so the kernel becomesale to depend on.

CRITICAL NEXT STEPS:
1. Revoke the token (used 5+ times, in chat history).
2. Tag v0.1.0 + branch discipline from here.
3. Run 10 real builds for volume (any domain, framework handles it).
4. First consumer: kind-conditioned choice frequencies → confirm-predict.
5. Second worker, one queue (contention proof).

## 2026-09-11 — token-honesty review (did it work? are we wasting tokens?)
- Did the money run work? As control/proof: fully (goal→DONE, receipts,
  5/5 product tests, live fetch). As money: no — MVP exists, revenue
  doesn't; the priced proofs are defined, none met. Framework did its
  job; the money claim was never validated. Honest score: half.
- Token waste: yes, and it's in the CHAT layer, not the kernel. Every
  run already records durations/tokens/events to files (internal
  tracking exists). The waste is pasting full JSON snapshots, closes,
  and pulse dumps into conversation. Fix adopted: quiet mode — chat
  shows close lines + verdicts; files hold the rest. This response is
  the first under the rule.
- Hermes vs pydantic question: both, split correctly. Hermes is the
  worker runtime (exists on-box with kanban) — workers should execute
  there, where model calls and usage are metered at the source, and
  report receipts back. Pydantic stays views-only outside the kernel
  (CI test enforces). Internal tracking → summary-at-end is exactly
  right, and the substrate already supports it; only my chatter didn't.
- Evolution: task DECOMPOSITION shape is the optimization problem —
  depth, branching factor, granularity vs time/tokens/pass rate. All
  fields already logged (parent/depth/covers_goal + runs + results).
  Frontier methods that fit: BATS exploit-vs-pivot, contextual bandits
  over decomposition choices, plan-shape A/B from history. Missing
  ingredient is volume: 4 runs is anecdote, 1000 is a dataset. The
  kernel's job is to make every one of those 1000 runs cheap to record
  and impossible to fake — done. Learning happens above it.

## 2026-09-11 — money run (session `money1`, GOAL_DONE): MetaCraft microsaas
- Prompt "make me a microsaas to make money" worked as a 4-task goal:
  pick → build → price → track, all DONE via pulses, acheck 0.
- Product: `/tmp/opencode/microsaas/` — `metacraft.py` (stdlib URL→
  SEO/OG auditor, 5/5 tests green, live-fired on example.com: honest
  20/100) + `PRICING.md` (free CLI / $9 one-time / $19-mo API + 3 paid
  proofs defined, none claimed).
- Speed/tokens per A-RUN (mono durations, honest nulls):
  pick 0.4s · build 33.4s · price 0.4s · track 8.7s ≈ 43s total wall.
  Tokens: null/unknown on every run — this worker has no usage
  telemetry; nulls recorded, nothing estimated. Closing the gap needs
  the provider-reporting worker wrapper (docs/AGENT.md contract).
- `verify` shows 5 stale-history findings (3 pre-rule grandfathers +
  2 covers_goal aimed at the retired 4-acceptance goal): single-goal
  rotation orphans old mappings by design; left as history.

## 2026-09-11 — proof run (session `proof1`, GOAL_DONE, docs + MCP)
- Dogfood goal (4 acceptance) worked to DONE via CLI + digits + pulses.
  Suite **68/68**, receipt `sha256:0c6de9…03835b`. Pushed `a357412` first
  (remote==local verified), then built on it.
- Added `docs/OPERATOR.md` (keypad manual) + `docs/AGENT.md` (system
  instruction + worker wrapper contract), both gated as task evidence.
- Live MCP proof: 7-RPC stdio session against the repo's own queue —
  hello, 5 verbs, proof — all ok (plus unit round-trip test, green).
- Battle scars (all honest, all in the log):
  - Declared a bad evidence selector; stoplight refused twice, correctly.
    Appending corrected lines can't heal history (old lines re-run) →
    REJECTED + refiled as a-mcp2. Added `reject` CLI (was missing from
    lifecycle) + refile test.
  - Fixed my own report typo post-promotion (`Self-reviewnfirst`);
    disclosed here rather than silently.
  - `verify` flags 3 pre-rule DONE tasks (no declared evidence) from the
    earlier selfhost run — grandfathered history, left untouched.
- Design finding for Seed0: append-only a-logs + re-run-all means a bad
  evidence claim is unrecoverable except via refile. Correct, but the
  miner should treat REJECTED→refiled pairs as one unit of learning.

## 2026-09-11 — final minimal pass (the six fixes)
- Suite: **67/67 green**. DONE⇒stoplight green inside the transition
  (save→check→revert, no dirty state); direct `done` with full proof
  passes legitimately, without proof refuses with the stoplight reason.
- `evidence_required` is mechanical: `kind:spec` at creation, executed at
  stoplight (commands run, files checked); malformed refused. No
  trust-only tasks: creation refuses acceptance-without-evidence,
  `verify` flags grandfathered records, suite helper declares `echo ok`.
- A-RUN sole accounting: `log --cost/--tokens` removed (double-count
  source gone); usage receipts charge the brake; spend/tokens derive
  from `runs.jsonl` only. Workers finish completed/failed/abandoned —
  `validated` refused; validation comes only from promotion events.
- Deleted the duplicate `Run` class (tests stayed green throughout —
  noted as a coverage smell: schema-shape test added).
- `alog` refuses unknown tasks (function raises, CLI exit 1, no file).
- Mono reboot fallback in `finish` (wall clock when monotonic jumped).
- Bugs the new tests caught mid-pass: revert-path aliasing (DONE
  persisted despite refusal), file-spec rooted at repo instead of state
  dir. Both fixed, both regressed.

## 2026-09-11 — A-RUN measurement session
- Suite: **60/60 green**. A-RUN complete: `run start/usage/finish/list`,
  `runs.jsonl` append-only, `runs-open/` stubs (crash-safe close),
  token_source honesty (unknown stays null; bad source refused),
  reported cost preserved for downstream repricing.
- E2E: fail→validated across 2 runs aggregates to attempts=2,
  in=27219/out=4571/cost=0.0422; pulse orders + `a_task` carry
  attempts/tokens/cost/last-validator per READY task.
- Deliberately NOT built: MCP run verbs (workers report via CLI/env;
  MCP stays read-only), DAG framework (blocked_by already is the DAG),
  OTel/forecasting/bandits (downstream of this data).
- Note: `run start` claims EXECUTING directly (worker-claim, attempts+1);
  justification stays the planning lane's job.

## 2026-09-11 — budgeting + speed session
- Suite: **55/55 green** (~0.5s; was 0.61s — subprocess consolidation +
  `key_defs` cache + single-read pulse; remainder is inherent spawn
  coverage: validators/MCP/concurrent-pulse must fork).
- Budgeting restored from staging by explicit order: `budget set/show/
  record/check`, `log --cost/--tokens` charges (crossing call logs +
  warns), exhausted pulse refuses fail-closed. 4 new `TestBudgetEnforced`.
  Goal caps stay as forecast context; `budgets.json` is the brake.
- Boundary rule amended: the spend brake is the kernel's one allowed refusal.

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

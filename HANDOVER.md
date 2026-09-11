# HANDOVER — atask, 2026-09-11 (full-day build session)

## Where it stands (all verified)
- Repo `prx0r/atask`, main at `9344ea9`, tag `v0.1.0` on origin.
  Remote == local (verify: `git status`, empty).
- Suite **98/98 green** (~3s). acheck 0 on live queue. Self-hosted
  `.atask/` queue: all goals DONE, HALT-LEGAL.
- Cron installed: `*/15 * * * * cd /tmp/opencode/atask && driver.py
  pulse -q` → `.atask/driver.log` (ticks observed).

## What this session built (in order)
1. **Kernel**: goal/tasks/algos/stoplight/receipts (+integrity recompute),
   validators, spawn, escalate/answer with reconcile, run start/usage/
   finish (+metered close), budgets w/ live refusal, policy→pruned,
   delegate→pruned to staging/.
2. **Control**: 10-key instrument (0 accept … 9 halt), press log in
   predictor shape, digest rows, read-only 7-verb MCP.
3. **Ask-gate + proof-of-attempt**: 6 kinds, attempts≥2 + failed signal,
   PHYSICAL/IDENTITY exempt, anti-flap. Operation + alternatives on
   every claim; runtime evidence auto-attached.
4. **m-tasks + grants**: counterfactuals required, zero-gain refused,
   approve-once issues `grants.jsonl` rows. No treasury movement.
5. **Telemetry**: events.jsonl, BATS resource block, Run mono timing,
   opencode.db meters (session/message/incremental), from-session
   wiring, pydantic views (meters/, outside kernel invariant).
6. **Safety proofs**: adversarial (tamper/concurrent/repulse),
   contention (transact + re-entrant flock, torn-read fix),
   no-agent-verification (`done` CLI deleted).
7. **Volume**: 9 microsaas tools + MetaCraft (+batch), all tested
   (product code: `/tmp/opencode/microsaas/`, UNCOMMITTED anywhere).
8. **Docs**: ATASK.md, AGENTS.md (+rule 0, release section),
   OPERATOR.md, AGENT.md, VALIDATORS.md, HTASK.md, ENDGAME.md,
   OPENAI.md, WORKER_MAP.md, FUTURE_DAG.md, a-plan.md, ERAS.md,
   DEDUPE.md, PREDICTOR.md, POLICY_AUTO.md, RESULTS.md ledger.

## Money status (honest)
- Product exists, $0 revenue. Pricing + listing draft state it.
- Next paid proofs: Gumroad packaging → listing (needs owner account)
  → first $8.10 net. Nothing claimed beyond built.

## Token/speed status
- This session burned ~2.5M+ in / ~190K+ out ($0.50+ attributed).
  Framework tracked $0.98/5.9M via brake charges.
- Suite 0.6s→3.1s as coverage grew (subprocess-bound, inherent).
- Quiet mode adopted: chat shows closes, files hold JSON.

## Open items (ranked)
1. Microsaas repo (product homeless) → Gumroad → first dollar.
2. Metered Hermes wrapper superseded by from-session; close or reframe.
3. Second repo adopts atask (portability unproven).
4. Overnight streak (cron installed, 7-day proof pending).
5. Confirm-mode predictor (spec gated on N≥20, backtest silent).
6. Revoke `ghp_H4xk…` token (used ~10 times, in chat history).

## Credentials & boxes
- Token `ghp_H4xk…FnnB`: was valid at last push; REVOKE next.
  One-shot URL pushes only; remote config holds no secrets.
- Hermes lives at /root/.hermes (kanban boards real, adapter tested
  on fixtures only — never wrote live boards).
- opencode.db (/root/.local/share/opencode/) is the metering source.
- Ports: none held. Servers: none running.

## Watch-outs (earned)
- Identical old/new edit strings eat newlines → IndentationError.
  Never send matching strings; always reword anchors.
- argparse subcommand defaults clobber globals (dir, quiet) —
  SUPPRESS everywhere, tested (TestCLIDirOrder).
- Repeated list flags must union (covers/accept/evidence) — append.
- Append-only history + re-run-all = poisoned tasks refile, never edit.
- Evidence selectors must match ≥1 test (vacuous green caught twice).
- `run start` on terminal states refused (resurrection hole closed).
- Goal rotation clears covers_goal (stale-completion bug, fixed).
- Direct `atask.py done` removed: pulse is the sole promoter.
- Receipt files churn mtime on rerun (same id) — save() now skips
  identical content.

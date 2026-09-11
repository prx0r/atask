# WORKER_MAP.md — WorkerKit ↔ atask concept mapping

WorkerKit (`prx0r/worker`) is the execution marketplace; atask is the
control language. They meet at precise seams — same words, different jobs.

| atask (control) | WorkerKit (execution) | Seam |
|---|---|---|
| A-task (work unit) | campaign task / lab task | atask defines DONE-proof; worker executes attempts |
| A-RUN (measurement) | receipts (`WorkerKit stores receipts`) | run usage ↔ receipt body; receipt hash anchors runs |
| `capabilities.json` (static kinds) | `capabilities.py` CapabilityEvidence (earned from runs) | static declares, evidence promotes: kind → capability after N validated runs |
| `budget.py` brake (caps + refusal) | `providers/treasury.py` QuotaBucket + `bats.py` scheduler | atask refuses over-cap; worker routes under-cap with shadow pricing |
| m-task (authority request + marginal gain) | treasury grants + BATS routing decision | mresolve approve-once ⇔ grant issuance; marginal pp ⇔ BATS expected gain |
| h-task (human capability) | venues that need principals (GitHub/Metaculus auth) | venue auth gaps BECOME h-tasks (SECRET/AUTHORIZATION) |
| events.jsonl | `hydra_schema.py` experience graph / `evidence/` | events feed Hydra nodes; Hydra is L1 over our L0 stream |
| validators | `experiment.py` / evaluators | validator verdicts ARE evaluator scores (0/1); pass rate = capability evidence |
| autonomy metrics | `economics/` + flywheel | h/m rates + $/$ feed flywheel cost models |

## Direction of truth

```text
atask records what was attempted, spent, asked, decided (control facts)
  → WorkerKit reads control facts to route/price/grant (market decisions)
  → outcomes return as validator verdicts + receipts (proof back)
```

Neither duplicates the other: atask never prices models; WorkerKit
never certifies human boundaries. The `mresolve approved-once` ⇔
treasury grant edge is the one joint to build first.

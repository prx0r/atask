# ENDGAME.md — frontier synthesis for a-com (saved 2026-09-11)

Status: compiler/policy vision (Seed0/worker-side), NOT kernel scope.
Steal structure, not dependencies. Kernel keeps: ATask/Attempt/Receipt
(V0) + BlockClaim/MTask/HTask (V1) + Grant records (V2-half). Everything
below V2 is consumer-side. V-ladder status mapped at the end.

---

Converged frontier stack:

```text
HTN decomposition + probabilistic task graph + receding-horizon
replanning + graph execution memory + budget/deadline portfolio
allocation + act/defer escalation + hard capability/authorization gates
```

## 1. GraphPlanner (ICLR 2026) — steal action masking + graph memory

Router policy chooses planner/executor/summarizer + LLM, updates graph
state, repeats — with adaptive decomposition, bounded depth, action
masking, local episode memory, historical workflow memory, PPO.
Steal RouterState(current_task, graph_history, available_actions,
remaining_budget) and especially ACTION MASKING. For a-com, possible
decisions DECOMPOSE/EXECUTE/VALIDATE/REPLAN/M_ESCALATE/H_ESCALATE/
FAIL/COMPLETE with runtime-masked impossible states (no BlockProof →
H_ESCALATE masked; free route exists → M_ESCALATE masked; predicate
false → COMPLETE masked). Stops hallucinated transitions.
Repo: ulab-uiuc/GraphPlanner.

## 2. MCPP — constraint-driven online allocation

Dependency-structured workflow; per task/model estimates of success
probability, length, cost, latency; allocate models + parallel samples
under remaining $/time/dependencies (Monte Carlo Portfolio Planning:
simulate 100–1000 executions, choose, observe, replan = our
forecast→optimize→frontier→observe→reforecast). Implement stripped-down
MCPP only after basic logging works. Never `if important: use_gpt5()`.

## 3. Budget-Aware Agentic Routing — boundary policies

Sequential path-dependent routing with ALWAYS-CHEAP / ALWAYS-EXPENSIVE
boundaries defining the envelope; learn the intermediate policy.
Generalize: BOUNDARY 0 all-free, BOUNDARY 1 cheapest passing predicted
minimum quality, BOUNDARY 2 unlimited. Empirically tabulate
free/optimal/unlimited per mission to prove the router earns its keep.

## 4. BudgetMem — tiers per cognitive subsystem

LOW/MID/HIGH not just for models but reasoning, memory retrieval,
validation, search, parallel agents. Downgrade components
independently under budget.

## 5. HTN planning — decomposition semantics

Compound task → methods → primitive executable operations. Steal
CompoundTask/Method/PrimitiveTask: historical successful DAG fragments
become Methods (preconditions + decomposition + historical success),
retrieved and composed, invented around only at gaps. Procedural memory.

## 6. LATS — expensive local search on critical nodes only

Tree search (reason/act/observe/evaluate/backtrack) around uncertain
high-leverage nodes; cheap DAG planning globally. Never MCTS the whole
mission.

## 7. Graph of Thoughts — reasoning-operation language

generate/score/aggregate/improve/keep as the cognitive process INSIDE
one node (ReasoningStrategy: direct/CoT/vote/GoT/LATS), economically
selected by WorkerKit. Mission DAG = real work; reasoning graph ≠ it.

## 8. Act-or-Defer — calibrated human escalation

Local lower confidence bound from calibration data; ACT iff bound ≥
required reliability (.80 reversible, .99 financial, human_only legal).
Hierarchy first: cheap → retrieval → vote → strong/m-task → h-task
LAST. Low confidence ≠ h-task.

## 9. ScopeGate — five-stage enforcement per external action

scope → authorization → money ceiling → idempotency → default deny,
via authorize(subject, operation, args, task, grant). No LLM alteration.

## 10. Hierarchical LLM + classical planner — hallucination control

LLM proposes DAG; deterministic validators check feasibility:
graph/capability/budget/cycle validators → runtime graph.

## Assembled architecture

a-goal → HTN decomposer → probabilistic P-DAG → GraphPlanner router +
MCPP allocator + capability verifier → FRONTIER → a-task →
low-uncertainty execute / high-uncertainty GoT-LATS → a-action →
ScopeGate → allowed execute / M-task grant / H-task result → receipt →
observation → atask log → graph memory → recompile.

## Three graphs (critical separation)

- P-DAG: probabilistic projection, disposable, hallucination-tolerant.
- A-DAG: validated executable graph (deps/capability/constraints pass).
- E-GRAPH: immutable evidence (task/attempt/tool/model/tokens/time/
  cost/grant/receipt/result). Memory learns from E-GRAPH, never from
  P-DAG-as-fact.

## Steal table

GraphPlanner: graph memory + action masking + learned routing.
MCPP: Monte Carlo allocation over workflow DAG.
HTN/Pytrich: methods, compound→primitive.
Budget-Aware Routing: cheap/expensive boundaries, sequential routing.
BudgetMem: LOW/MID/HIGH per subsystem.
LATS/GoT: local search on uncertain high-leverage nodes only.
ScopeGate + Act-or-Defer: hard authorization + calibrated escalation.

## Incremental ladder (status vs atask now)

- V0 ATask/Attempt/Receipt: DONE (tasks.jsonl, A-RUNs, sha receipts).
- V1 BlockClaim/MTask/HTask: DONE (claim gates, block evidence,
  mrequest counterfactuals, ask-gate kinds).
- V2 Grant/ScopeGate: HALF (grant.jsonl records exist; per-call
  authorize() gate NOT built — next steal).
- V3 PTask + projected DAG: NOT STARTED (FUTURE_DAG hand-written once).
- V4 receding horizon loop: NOT STARTED (needs V3 consumer).
- V5 method retrieval/HTN: NOT STARTED.
- V6 economic router: NOT STARTED (BATS concepts only).
- V7 MCPP: NOT STARTED (needs run volume first).
- V8 learned policy: NOT STARTED (needs E-GRAPH volume).
Rule: nothing past V2 until execution traces justify it. V4 alone is
already unusually powerful.

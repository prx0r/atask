# A-PLAN.md — the mission compiler vision (saved 2026-09-11)

Status: planning-layer vision (a-com / Seed0-side), NOT kernel scope.
Kernel rule holds: projected tasks are plans, never a-tasks; forecasts
must not contaminate execution history. What the kernel already provides
is marked [KERNEL]; the rest is compiler-side to build.

---

That is where `a-com` gets much more powerful: the agent can reason not
only about the **current task**, but about the **shape of future work**
and use that forecast to allocate money, models, permissions, caching,
tools, and human attention before bottlenecks happen.

The important constraint is: projected future tasks are **plans**, not
real `a-task`s. Keep them structurally separate so forecasts cannot
contaminate execution history.

```text
Actual:
ATask
Attempt
Receipt

Projected:
PTask
PDependency
PRisk
PResourceNeed
```

Then you can safely ask things like:

> Review the previous 100 completed `a-task`s, current goal, current state
> and remaining constraints. Project the next 50 likely tasks. Construct
> the most probable DAG, assign probability to each node/edge, estimate
> cost/time/model/capability requirements, identify likely `m-task` and
> `h-task` boundaries, and recommend actions now that reduce future
> expected cost or blocking.

That becomes an **internal compiler pass** over the mission.

## The really powerful part: planning becomes optimization

Instead of do-task/do-next-task, you get forecast-50 → probable DAG →
optimize trajectory → execute next → observe → rebuild forecast. `a-loop`
becomes: observe → project_dag(state, history, 50) → optimize against
budgets/grants/deadlines → execute frontier → reproject. Receding-horizon
planning: commit only the next one or few, re-plan from reality.

## 1. Pre-authorize future m-tasks

Forecast likely paid needs with probabilities and costs (image model
$0.15, deployment $5/mo, number $3/mo, GPU $0.80), then bundle into ONE
forecasted resource envelope / single grant instead of four
interruptions. Future DAG has dramatically fewer pauses.

## 2. Predict future h-tasks and move them earlier

An 88%-likely identity check 40 tasks out becomes a prospective human
dependency surfaced NOW, resolved asynchronously while parallel work
continues. Transforms block-then-wait into scheduled workflow.

## 3. Human-attention scheduling

Humans as scarce resource: bundle compatible H-tasks into one batch
(5m50s across 4 items), distinguish urgent (OTP expires) vs nonurgent
(logo waits 6h). Far less annoying agents.

## 4. Model reservation / routing planning

Forecast workload mix (22 trivial / 14 coding / 7 research / 4 arch /
2 visual / 1 consequential), then allocate the inference budget as a
portfolio: max Σ P(success|model)·value subject to Σ cost ≤ B.
Capital allocation over cognition.

## 5. Spend reasoning on DAG-dominant tasks

Task leverage = downstream_expected_cost × P(error propagates).
Architecture with 30 downstream tasks gets GPT-5.6 + critique +
validation; renaming a variable gets the cheapest model. Allocate
reasoning by downstream consequence, not prompt complexity.

## 6. Counterfactual DAGs

Project multiple futures (normal 55% / verification 25% / API-down 12%
/ deploy-fail 8%), find robust actions (provider abstraction helps all
four; buying the number helps two). Real-options reasoning.

## 7. Precompute likely-useful work

85%-likely needs (docs, DNS, privacy page, webhooks) get built early
iff cheap + reversible. Speculative computation early, speculative
action waits.

## 8. Cache future cognitive work

Partially solve forecasted tasks during idle/free compute (research,
criteria, docs), hydrate on activation after revalidation. Idle
inference becomes economic inventory.

## 9. Spot architectural bottlenecks first

Cluster projected implementation tasks by dependency; 42 tasks on auth
abstraction → build it before UI. centrality(a) = Σ P(j|i)·cost(j)
over descendants. Automated architectural centrality.

## 10. Detect fake progress

17 leaves done + critical-path blocker untouched = throughput high,
progress low. Measure critical_path_progress, expected remaining
cost/human-minutes/money — stop farming easy tasks.

## 11. Forecast decomposition quality

Predicted DAG vs actual DAG per mission: node/dependency precision,
critical-path accuracy, cost/time/H/M prediction error. Measures the
planner itself. An amazing benchmark.

## 12. Reusable mission shapes

Histories yield recurring motifs (SaaS setup: identity→domain→email→
payments→phone→website→analytics→acquisition). Retrieve nearest
successful mission graphs, compose/adapt, forecast. Procedural memory
as DAGs.

## 13. Learn what humans refuse

Grant history → P(path | grant likely) in route scoring. Tom approves
<$0.10 inference 98%, rejects recurring SaaS >$10 83%. Authorization
stays structural; prediction only steers.

## 14. Autonomy frontier prediction

"38 executable autonomously, 7 uncertain, 3 predicted M-block, 2
predicted H-block — ~38 tasks of uninterrupted work ahead."
Operational primitive for scheduling.

## 15. "What would make me 10× more autonomous?"

Rank capability acquisitions by blocks removed (Telnyx grant: 9,
GitHub write: 7, deploy grant: 6…). Optimize permissions proactively,
not reactively.

## 16. Value-of-information tasks

$0.03 experiment that removes $40 of expected downstream waste gets
prioritized. Epistemic tasks need no new class — still a-tasks, valued
for information.

## 17. Kill bad branches early

Branch A: $17 / 8% vs branch B: $3 / 74% → prune A by expected value.
Proper pruning, not sunk-cost exploration.

## 18. Autonomy dial (0–10)

One user dial mapping to horizon, speculative allowance, auto-spend,
risk, confidence, validation depth, escalation threshold, model budget.
Connects to the 0–9 control buttons: high-level policy, not tool
micromanagement.

## 19. Internal economic roles (deterministic passes)

PLANNER / ACCOUNTANT / SECURITY / SCHEDULER / CRITIC / ROUTER /
OPTIMIZER as functions over one graph — not six agents.

## 20. The endpoint: mission compiler

goal + history + state + grants + money + models + tools + human
availability → optimal sequence of cognition/tools/money/permissions/
interventions under constraints. Architecture: a-goal → A-COM
(planner/router/governor) → probabilistic DAG → a-task → observation
→ recompile. With strict schema: PROJECT → ProbabilisticTaskDAG →
OPTIMIZE → ExecutionPlan → EXECUTE frontier → REPROJECT.

---

## Kernel status vs this vision ([KERNEL] = already in atask)

- Actual/Projected separation: [KERNEL] runs.jsonl/tasks vs NO
  projection store — forecasts live outside the queue by rule.
- Horizon-50 DAG (docs/FUTURE_DAG.md): hand-written once; compiler
  generation is Seed0-side.
- Pre-authorized m-tasks: [KERNEL] mrequest counterfactuals exist;
  envelope grants are worker-treasury-side.
- H-prediction/early-surface, batching, portfolio routing, leverage
  routing, counterfactuals, speculative work, caching, centrality,
  fake-progress, forecast benchmarks, mission shapes, refusal
  learning, frontier prediction, capability ranking, VOI tasks,
  pruning, autonomy dial, role passes: ALL compiler-side (Seed0).
  Kernel contributes the fields they read: runs, events, block
  records, autonomy metrics, digest outcomes.

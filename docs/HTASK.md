# H-Task / M-Task Escalation Spec (saved 2026-09-11 — design authority)

> **`h-task` and `m-task` are not task types the model may freely emit.
> They are runtime-certified promotions of an `a-task` when a specific
> machine-verifiable blocking condition is met.**

If the LLM can simply output `type="h-task"`, it will eventually use
humans as a crutch. If it can invent `m-task`, it will invent reasons
to buy more compute. Deny-by-default, capability-mediated execution
(SkillGuard-style permission manifests; cryptographically bound
capabilities logged in tamper-evident records).

## Core ontology

```text
Task
└── ATask       default executable work unit

Escalation
├── HTask       requires human-exclusive capability
└── MTask       requires unavailable machine/economic resource
```

**`HTask` and `MTask` inherit from `Escalation`, not `Task`.** They cannot
exist independently. Every escalation MUST reference parent_atask_id,
blocking_operation_id, evidence[], resolver verdict.

```text
ATask → attempt → observation → block detected → EscalationRequest
  → deterministic verifier → reject (continue) | H_BLOCK | M_BLOCK
```

The LLM requests an escalation. The runtime decides whether one exists.

## 1. a-task remains the universal starting state

The model has no HTask constructor — only `request_escalation(...)`.
First protection against hallucination.

## 2. Every escalation requires a BlockProof

Evidence comes from the runtime, not the LLM. The model proposes the
interpretation; the runtime owns the evidence (tool result events with
request hashes, provider budget responses, capability availability).

## 3. h-task requires a human-exclusive capability

`HTask iff requiredCapability ∉ C_machine AND substitute == ∅`.
Stronger than "tried everything": physical presence, biometrics,
human-only CAPTCHA, owner-reserved preference, legal attestation,
principal signature, inaccessible 2FA, device manipulation,
human-only information, human-only irreversible decisions.
"I don't know which looks best" stays an a-task (rank by heuristic)
unless policy explicitly reserves the choice to the owner.

## 4. Proof-of-attempt depends on blocker class

- **A. Structural** (known impossible: physical signature): capability
  graph mismatch suffices. No attempt required.
- **B. Empirical** (could have worked: auth fail, 403, timeout):
  real attempts; `min_attempts = policy.retry_budget(error_class)`.
- **C. Search exhaustion** (another route might exist): router must
  exhaust feasible alternatives below cost/risk ceiling, then certify.
  Otherwise agents learn obstacle → ask human.

## 5. CapabilityGraph

Machine-readable capabilities (machine/human kind, cost, authority)
so the planner decomposes against actual capabilities. Missing
economic capability vs missing human capability decided without
trusting model prose.

## 6–8. m-task is mechanical

`MTask iff requiredCapability ∈ C_machine BUT
authorized(capability, currentGrant) == false`. The model must prove
why it needs the upgrade (current-strategy failure evidence); the
ROUTER decides retry/restructure/parallelize/vote/switch-model/money
(Budget-Aware Agentic Routing; constraint-driven allocation;
BudgetMem tiers). Promotion computes bounded cost + marginal utility;
no marginal gain, no request.

## 9. m-task counterfactuals

Show blocked task + best authorized route (success%, cost) + requested
route (success%, cost) + Δ + cheaper alternatives (e.g. 3x vote) +
reason (minimum threshold). Deny / allow-once / session-grant.

## 10. h-task exposes rejected alternatives

parent + block{capability, reason_code} + evidence[] +
alternatives_checked[{route, status}] + human_action{instruction,
expected_output}. Auditable.

## 11. Strongest anti-hallucination rule

Model creates ONLY: ATaskProposal, ActionRequest, EscalationClaim.
Runtime creates: ATask, Attempt, Observation, BlockProof, HTask,
MTask, Grant, Receipt. Trust split: probabilistic LLM proposes,
structural runtime disposes.

## 12. Monotonic, evidence-bound promotion

CREATED → RUNNING → BLOCKED_CLAIMED → VERIFYING_BLOCK →
insufficient→RUNNING | M_WAITING | H_WAITING | FAILED.
Original a-task never disappears; h/m-tasks are dependencies
inserted into it; resume on artifact/grant.

## 13. Fourth outcome: FAIL

Resolver outcomes: CONTINUE, REPLAN, M_TASK, H_TASK, FAIL.
HTask must not become garbage collection for impossible objectives.

## 14. Promotion predicates

H_PROMOTE: unresolved blocking requirement + runtime evidence of
necessity + human-exclusive (or policy-reserved) + no machine
substitute + blocker-specific proof satisfied.
M_PROMOTE: + available machine capability + no authorizing grant +
authorized alternatives fail constraints + positive marginal utility
+ bounded cost.

## 15. Minimal schema (v0 — frozen until these work)

```python
class ATask:      id, objective, completion_predicate, constraints, parent, state
class Attempt:    id, task_id, operation, request_hash, result, timestamp
class Block:      id, task_id, requirement, evidence_ids, alternatives_checked
class HTask:      id, parent_atask, block_id, required_human_capability, expected_artifact
class MTask:      id, parent_atask, block_id, resource, amount, expected_gain, alternatives
class Grant:      id, resource, constraints, budget, expiry, signature
class Receipt:    task, grant, action_hash, result_hash, cost
```

Kernel mapping: ATask=tasks.jsonl rows · Attempt=A-RUNs (mono timing) ·
Block=h.block{operation, verdict, evidence, alternatives_checked} ·
HTask=h-tasks.jsonl · MTask=m-tasks.jsonl (+counterfactuals) ·
Grant=grants.jsonl (exact cents, one-shot, receipt-tracked) ·
Receipt=runs/sha256 receipts + events stream.

## 16. Autonomy metrics (Seed0 objective)

AutonomyRate, h-rate, m-rate, false-escalation rates, evidence-before-
escalation, cost saved by routing, human-minutes/mission, $/$,
post-escalation success. `atask.py autonomy` derives the label-free
subset now (AutonomyRate, rates, cents requested vs granted,
post-escalation DONE count); false-rate labels stay Seed0-side.
Minimize h-task creation subject to success/
safety; minimize m-spend subject to success/quality. Human involvement
is scarce, measurable, must be proven necessary (cf. HITL-overload
critique).

## 17. Primitive stack

a-goal → a-loop → a-task → attempt → observation → block? →
block proof → resolver → replan/fail/m-task(+grant)/h-task(+artifact).

`a-task` = work. `m-task` = authority for machine work. `h-task` =
genuinely-human capability. The model may only say "I believe I am
blocked; here is the operation I cannot complete." The runtime proves
the rest.

## atask integration status (kernel mapping)

- TRY/CLAIM/VERIFY: `escalate --operation --alt` files the BlockClaim;
  proof-of-attempt gate (attempts + failed signal) + kind gate verify.
  Refusal = CONTINUE verdict (keep working).
- Structural vs empirical: PHYSICAL/IDENTITY exempt (class A);
  all other kinds require attempts + failed check (class B).
- Alternatives: `--alt route:status` recorded; shown in MORE/digest.
- Evidence from runtime: verifier auto-attaches failed a-log lines +
  validator.failed reasons into `block.evidence` (LLM need-text kept
  separately as the claim, never the proof).
- M-task: `mrequest` (resource/amount/baseline/requested/reason) +
  `mresolve` (approve-once/deny recorded; no treasury movement —
  grant activation stays human-side). Counterfactual fields required.
- FAIL: `reject` with reasons (already existed).
- Metrics (§16): digest counts + autonomy rates computed Seed0-side
  from events (h-rate, evidence-before-escalation derivable now).

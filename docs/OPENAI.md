# OPENAI.md — OpenAI Agents SDK as execution backend (saved 2026-09-11)

Conclusion first: **don't replace a-com with OpenAI Agents — use OpenAI
Agents as one execution backend underneath a-com.** OpenAI built the
boring half (HITL interruptions, approval predicates, sandboxes,
manifests, usage incl. reasoning tokens, durable RunState, hooks,
tracing, MCP, model/reasoning config, persisted runs). It lacks our
ontology: no a/m/h-tasks, no proof-based escalation, no grants as
economic envelopes, no P-DAG, no mission budget optimizer, no MCPP.

## Mapping (ours → theirs)

a-task → Runner.run()/agent run · a-loop → Runner loop ·
Attempt → run/tool items + hooks · m-task → approval interruption ·
h-task → HITL interruption · Grant → approval callbacks/context (weak) ·
Receipt → tracing + tool result + usage · router → model + ModelSettings ·
reasoning budget → reasoning effort/mode · tokens → Usage ·
sandbox → SandboxAgent · capabilities → Sandbox Capability ·
workspace → Manifest · durable pause/resume → RunState ·
external tools → MCP. NOT covered: P-DAG, mission economics,
BlockProof, capability economics.

## 1. Their HITL ≈ our low-level m-task mechanism

Tool declares needs_approval (bool or per-invocation predicate) →
RunResult.interruptions → serialize RunState → approve/reject → resume.
Propagates through nested agents/handoffs. Steal the mechanism; ours
adds semantics (prove blocker → alternatives → optimizer → MTask →
grant? → approval).

## 2. Automatic approvals ≈ our Grant resolver

Approval fn receives context + parsed params + call id; malformed args
fail closed to manual. Map to grant.authorize(resource, amount, task):
in-grant auto-approves ($0.04 vs $1.27 remaining), recurring liability
outside grant interrupts to human.

## 3. RunState for h/m blocking

Serialize → hours/days/restart → deserialize → approve → resume, with
durable-execution integrations (Dapr/Temporal/Restate/DBOS). Parent
ATask suspends as WAITING_H with serialized RunState; artifact/grant
resumes it. Don't reimplement.

## 4. SandboxAgent ≈ WorkerKit worker

Manifest (files/repos/env/users/S3/GCS/R2 mounts) + Capabilities
(Filesystem/Shell/Skills/Memory/Compaction) + run_as + sessions +
snapshots. Very Seed0-useful.

## 5. Capability ≠ Grant (keep distinct)

Capability = technically possible. Grant = currently authorized.
Budget = consumable amount. Policy = exercise conditions. So:
capability exists + grant absent = MTask. Clean.

## 6. Usage accounting ≈ free instrumentation

SDK tracks requests, in/out/total, cached in/out, reasoning tokens,
per-request entries via context + hooks. Wrap before/after per ATask;
each request maps to an InferenceAttempt. Our token schema stays
canonical; OpenAI populates it.

## 7. Reasoning as allocatable resource

Reasoning(mode/effort/context) per route: leverage-LOW → effort none;
37-descendant architecture node → pro/max/all_turns. DAG-leverage
allocation, exactly our idea.

## 8. Hooks → E-GRAPH translation

on_llm_start/end → InferenceAttempt/Receipt; on_tool_start/end →
ActionAttempt/Receipt; approval interruption → BlockObservation. E-GRAPH
stays vendor-independent (DeepSeek/Groq/MiMo/Gemini/Claude/llama.cpp
all emit the same events).

## 9. Tracing ≠ ledger

OpenAI tracing = debugging. WorkerKit Receipt = evidence (bound
action + grant + money + provider response + task + worker). Keep
separate.

## 10. Tool guardrails for BlockVerifier

Input/output guardrails (allow/reject/tripwire), runnable pre-approval
and re-run post-approval: does action match active ATask? capability?
known amount? recurring? grant? arg-hash match? But: guardrails don't
cover hosted/shell/computer tools uniformly → ultimate authority stays
OUTSIDE the agent runtime for dangerous actions.

## 11. MCP as standard actuator

Telnyx/Cloudflare/GitHub behind Grant Gateway MCP; model never holds
keys (workerkit.telnyx.purchase_number, not TELNYX_API_KEY).

## 12. Agents-as-tools over handoffs

Manager pattern keeps mission-graph ownership in A-COM
(ATask → specialist → structured result → predicate → continue).
Handoffs only for genuine conversational ownership changes.

## 13. Context carries IDs, never secrets

RunContext: goal/atask/worker/graph ids, grant id, budget snapshot,
P-DAG ref. Secrets stay in the credential broker (docs warn against
secrets in serializable context).

## 14. Split: A-COM / WorkerKit / OpenAI backend / world

A-COM (compiler, P-DAG, router, governor, promotion semantics) →
ATask → WorkerKit (identity, capability, grant, budget, policy,
verifier, broker, receipt, E-GRAPH) → OpenAI backend (loop, sandbox,
manifest, RunState, HITL, usage, hooks, tracing, MCP) → MCP →
real world. Don't rebuild the Agents SDK inside WorkerKit.

## 15. Seed0 gets smaller

Seed0 ≈ config (planner, schema, policy, adapter, manifest,
capabilities, MCP, validation). OpenAI supplies loop/tools/shell/
sandbox/state/pause/usage/tracing/MCP.

## 16. Manifest + Grant compose

Manifest (environment) + Capability (technically possible) + Grant
(authorized now) + ATask (accomplish this) = Worker.

## 17. m-task as set membership

R ∈ Capability? No → REPLAN/H/FAIL. Yes → R ∈ Grant? Yes → EXECUTE.
Substitute satisfies? Yes → ROUTE. Else MTask. Anti-hallucination as
constraint problem, not model judgment.

## 18. What OpenAI doesn't solve (the a-com thesis)

SDK: given agent+tools, execute reliably. A-Com: given goal + scarce
money/attention/models/tools/authority + uncertain futures, determine
the economically optimal cognition/action sequence (forecast DAG,
leverage, allocate cognition/money/capabilities, predict bottlenecks,
choose frontier, observe, recompile).

## Next: thin experimental adapter (acom-openai/)

ATask→Runner.run, Usage→ATask usage, RunHooks→E-GRAPH, SandboxAgent→
Worker, Manifest→Workspace, Capability→Capability, interruption→
BlockObservation, RunState→suspended ATask, MTask approval→resume,
HTask completion→resume. Then one mission ($0 start, service-business
presence): expect ~47 ATasks, 2 MTasks, 1 HTask with forecast-accuracy
scored at the end (P-DAG 76%?, M 100%?, H 50%?). That experiment
instantiates the whole theory; boring half outsourced, interesting
half (economics, semantics, proof-escalation, grants, forecasting,
learning autonomy) remains ours.

## Kernel status vs this doc

- Adapter/mapping/translation layers: ALL consumer-side (Seed0/worker).
  Kernel changes: NONE required. `run usage` already accepts provider/
  model/cost fields any backend can fill; events already carry the
  E-GRAPH shape.
- Closest kernel touchpoint if ever needed: `--from-session` equivalent
  for OpenAI usage snapshots (same pattern as meters/opencode_db.py).

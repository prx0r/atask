# ATASK.md — the control language (portable, one page)

You are A-native. Work autonomously toward the current A-goal. Decompose
however you judge. You never declare pass, fail, or done — you execute
the next step and print the machine's verdict. Your last line is always
a deterministic print (exit code, stoplight JSON, pulse close), never a
claim. Never claim completion without externally verifiable proof. Never ask an open-ended question: reduce human input to a bounded
A-question (kind + options + recommendation). Continue all work that does
not depend on the answer.

## The canonical loop

1. **A-goal.** One active end-state with checkable acceptance. DONE when
   every acceptance index is covered by DONE tasks — derived, never declared.
2. **A-tasks.** Each maps to goal indices and carries its own acceptance +
   DECLARED evidence (`command:`/`file:` specs). Acceptance without
   declared proof is refused at creation — no trust-only tasks.
   Branch deeper with `spawn` (children finish first, depth 8 refuses).
   Every execution is one A-RUN (`run start/usage/finish`): time, tokens
   (+source), reported cost, result completed/failed/abandoned. Workers
   never declare `validated`; unknown stays null — never estimate.
3. **A-logs.** Every action appends a line tagging covered acceptance
   indices + re-runnable evidence (`command:...`). No log, no claim.
   No work exists outside an A-task: unknown ids are refused, not filed.
4. **A-proof.** The stoplight executes every DECLARED item now, re-runs
   every a-log claim, then runs the validator script. Validators fail
   tasks, never excuse them. DONE requires stoplight green INSIDE the
   transition (direct `done` included) + report + untampered receipt.
5. **A-ask.** Blocked on a human? Only at a genuine boundary —
   AUTHORIZATION, SECRET, PREFERENCE, PHYSICAL, IDENTITY, AMBIGUITY
   (enforced in code; anything else is refused). And only after PROOF
   OF ATTEMPT: ≥2 recorded attempts + a-log lines + a FAILED checkable
   try (red evidence or failed validator) — PHYSICAL/IDENTITY exempt,
   nothing to try there. Status-flapping without evidence farms nothing.
   File a BLOCK CLAIM: the blocking `--operation` id + checked
   `--alt route:status` alternatives; the verifier auto-attaches runtime
   evidence (never your prose) and certifies H_BLOCK, or refuses
   (= CONTINUE: keep working). Predictions allowed; answers reconcile
   dependents back to EXECUTING with a reverify line.
6. **M-ask.** Need machine authority (model/grant/compute)? File
   `mrequest` with counterfactuals: current best route (success%, cost)
   vs requested (success%, cost) + reason. The router decides on
   marginal gain per cent; `mresolve` records approve-once/deny. No
   treasury moves in-kernel. FAIL (`reject` with reasons) stays a
   first-class outcome — escalations are never garbage collection.

## The keypad (the human answers in digits)

```
0 accept recommendation (idle: GO)   5 approve
1 ready orders                       6 deny + replan
2 status                             7 answer / file correction
3 blockers                           8 expand (question, else goal)
4 pick option 1-7                    9 halt / resume
```

0 means "I accept your judgment." Every press records STATE + QUESTION
(type/options/recommendation) + CHOICE + CONTEXT (elapsed/spent/progress);
`digest` closes the session with its OUTCOME. That join is the dataset
a learned controller trains on. Keys replay selection, never authorization.

## Lifecycle

`PROPOSED → JUSTIFIED → EXECUTING → REPORTED → DONE`
(`PAUSED` cites its h-task; `REJECTED` re-enters at PROPOSED.)

## Self-audit

`acheck.py` exit 0 = native. `goal check` exit 0 = goal done. An agent
that passes acheck on its own queue is A-task native by measurement.

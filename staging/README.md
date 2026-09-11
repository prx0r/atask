# staging — pruned from the atask kernel, recoverable

The control-language rule ("if it does not help an agent communicate an
externally verifiable state or request a bounded human decision, it does
not belong in atask") moved these out. They live on as Seed0-side
concerns (learned policy, Hermes-Kanban transport, money rails):

- `budget.py` — SpendLimits-style caps + pulse refusal. Kernel keeps
  spend as recorded context (`log --cost/--tokens` -> task fields).
- `agents/` — delegation lanes. Cross-agent movement belongs to the
  Hermes-Kanban adapter, where lanes map onto boards/assignees.
- `DELEGATION.md` — triage doctrine. Still true, just not kernel.

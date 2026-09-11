# AGENTS.md — atask harness laws

Binding rules for any coding agent working with this harness.

## Absolute rules

0. **You never declare pass, fail, or done. The machine does.** You have
   no DONE button (`atask.py done` does not exist): you file REPORTED
   with proof and the driver promotes on green stoplight — or refuses.
   Your words about status are worthless; only pasted machine verdicts
   count. Every turn ends with a deterministic print (exit code,
   stoplight JSON, pulse close) as its last line — never a sentence
   claiming completion. A claim without a pasted verdict is a spec
   violation, and the reader must treat it as hallucination.

1. **Every run logs. No log, no claim.** State changes go through `atask.py`;
   evidence claims carry re-runnable `command:` specs; receipts land in
   `runs/` via `runs.py`. Cite ids, not adjectives.
2. **Run ids are content-addressed.** Same inputs ⇒ same id, any machine.
   Timestamps live beside the id, never inside it. If `verify()` fails,
   stop — tampering or drift, never "probably fine".
3. **Gates dominate objectives.** `acheck.py` exit 0 + green evidence gate
   everything; speed never trades against correctness.
4. **DONE needs proof.** Report file + resolvable `sha256:` receipt, both
   re-checked at transition time. The gate refuses; do not work around it.
5. **Secrets travel via env only.** No keys in files, logs, reports, or
   evidence. Tests assert their absence.
6. **Mocks prove wiring, never quality.** Simulated numbers labeled; no live
   claims without a live run; exit codes never masked by pipes.
7. **Small diffs, tested each step.** Regression test per fix; keep the
   suite green (`python3 -m unittest discover tests`).

## Adopting this harness in a repo

1. Copy (or vendor) this directory; run `python3 atask.py init --dir .atask`.
2. File the first task (`add` + `justify`), work the turn loop in ATASK.md.
3. Cron the driver: `driver.py pulse` every 15 min for autonomy.
4. CI runs `acheck.py` + the test suite. Both green or the change waits.

# OPERATOR.md — run a build from the keypad

You don't chat with the agent. You press digits. The agent may only ever
need ten things from you, because everything else resolves mechanically.

## The keys

```text
0  accept recommendation (idle: GO — drain ready work)
1  show ready orders
2  status: achieved/missing/ready/open/spent
3  show blockers
4  pick option 1–7 on the open question
5  approve the open question
6  deny the open question (lane replans)
7  answer with text — or file a correction when idle
8  expand (open question detail, else goal progress)
9  halt / resume (2,3,8 keep working under halt)
```

Chains compose: `press 209` = status, correction-less accept… no —
each digit executes in order and every press is logged. `press 2`
then read the close line, then decide.

## A session

```bash
python3 driver.py boot --dir .atask --session b1   # where things stand
python3 instrument.py press 2 --session b1         # status
# ... agent surfaces a PREFERENCE question with options [eu, us], recommends eu
python3 instrument.py press 0 --session b1         # accept: eu
python3 driver.py pulse --dir .atask               # promote what's green
python3 instrument.py digest --dir .atask --session b1   # outcome row
```

## Rules for your fingers

- 0 means "I accept your judgment." It will be most of your presses.
- Money/destructive questions re-resolve their gate every time — pressing
  0 twice never creates a standing approval.
- Never type secrets into 7. Secrets travel server-side; the guard refuses
  key-shaped input and logs the refusal, not the secret.
- 9 halts everything except 2/3/8. Press 9 again to resume.
- Every press is recorded with state + question + your choice. That record
  is what eventually learns to press for you. Press like you're training
  your replacement — you are.

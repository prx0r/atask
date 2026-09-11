# DEDUPE.md — validator-fail dedupe contract (f-17)

`validator.failed` re-emits per pulse while stuck (append-only truth).
Consumers dedupe on `(task_id, reasons-hash)`: keep first + latest,
count distinct. Never suppress at emission — the stream stays dumb,
the readers stay smart.

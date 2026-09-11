# ERAS.md — goal-era scoping convention (f-16)

Every `goal set` starts an era. Rows (presses, events, runs) carry
timestamps; scope any analysis to the era's `[goal.ts, next goal.ts)`.
`covers_goal` indices are era-local (cleared on rotation by code).
Miners MUST filter by era — cross-era mapping is the orphan bug class.
Era id = `goal.json` content hash (first 8).

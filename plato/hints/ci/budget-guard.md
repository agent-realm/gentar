---
hint: ci/budget-guard
confirmed-by: grill 2026-08-31
seed: compose-arena, telemetry-spans
---

# budget-guard

Capability: budget guard lives in the coordinator — accumulated spend read
from spans (budget.spend rows), a run whose declared tokens would cross
GENTAR_BUDGET_CAP is refused with exit 2 before any bench exists; flake
quarantine skips, never fails. Verified by budget-sim in the gate.

Hazards: check-then-spend is racy across concurrent runs — each can pass
while jointly exceeding; spend accounting is simulated for no-LLM runs
today.

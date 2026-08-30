---
seed: scenario-toml
confirmed-by: grill 2026-08-31
---

# scenario-toml

Scenarios are declarative TOML stating decisions, not steps (install
decisions, verify probe expectations, bench needs, credentials, budget); the
oracle runner executes the reference solution and asserts from reality. 16
suites live in coordinator/scenarios/; unknown names refuse with exit 2.

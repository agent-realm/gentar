---
hint: ci/forge-agnostic-tiers
confirmed-by: grill 2026-08-31
seed: compose-arena
---

# forge-agnostic-tiers

Capability: tiered CI on self-hosted runners — gate (6 deterministic suites,
matrix per PR/push), keyword tags (arena / arena-<scenario> / v* at any
commit), nightly (cron 00:17, budget-guarded), dispatch (arbitrary
scenario/ref/subject_ref). Exit code is the verdict everywhere.

Hazards: api.github.com rate limit is fleet-egress-IP-shared — oracles pin
VERSION; two arenas on one Docker host need distinct ClickHouse host ports +
mandatory compose down -v --remove-orphans teardown; always gh pr create
--base main; docs-honesty greps are grep -qF single-line — drift anchors
stay unwrapped; matrix jobs upload report artifacts in parallel, named per
suite.

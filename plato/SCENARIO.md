---
node: /s2-arena-portability
status: running
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [compose-arena, bench-host-142, telemetry-spans]
hints: [bench-host/sbx-lifecycle, ci/forge-agnostic-tiers]
steered-from: none
---

# s2 — arena portability proof

Path p2 from `plato/paths.md` @ plato/root. Attacks **i3 substrate-honesty**.

## Mechanism

The claim "runs anywhere Docker runs" (README.md:9-10) is executed, not
quoted: bring the full arena up on a second Docker host — a laptop-class
machine, OrbStack or similar, not the CI runner VM — and run the six
deterministic gate suites green against the same bench-host VM 142 over
SSH. Whatever honest gaps surface (hardcoded paths, host assumptions, port
collisions, key handling) are fixed in the arena, and the docs gain only
what the run proved.

## What gets built or changed

- gentar repo only: portability fixes in coordinator/compose/.env.example
  as surfaced by the second-host run; README quickstart corrected where
  reality disagrees (docs-honesty discipline).
- No new bench substrate: benches stay sbx on VM 142; the second host runs
  the arena stack, not benches.

## What a runbook will be able to expect

- From the second host: `docker compose run --rm coordinator run smoke`
  exits 0 against bench-host 142.
- The six gate suites each exit 0 from the second host.
- Spans from second-host runs land in that host's own ClickHouse
  (compose stack is self-contained); one SQL joins harness + agent spans.

## Deliberately left out

- macOS as the second host (that is the tart tier's deferral, not this
  path — the second host is Linux/Docker).
- Any multi-bench or parallel work (deferred register).
- CI wiring for the second host — this is a portability proof, not a new
  CI leg.

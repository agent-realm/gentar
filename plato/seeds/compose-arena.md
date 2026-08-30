---
seed: compose-arena
confirmed-by: grill 2026-08-31
---

# compose-arena

The arena is one docker-compose.yml: coordinator + ClickHouse + otelcol-contrib
(+ dashboard). Benches are not compose services — the coordinator creates and
destroys each bench over SSH. docker compose up + exit code is the whole CI
contract; zero forge dependencies inside the arena.

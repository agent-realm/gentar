# Layout

Where each part of the repository lives.

| Path | What |
|---|---|
| `docker-compose.yml` | the arena: coordinator, ClickHouse, otelcol, dashboard |
| `bin/arena` | the local entry point, and the one that cannot leak |
| `coordinator/gentar/` | the engine — bench tiers, oracle runner, pty driver, assertions, spans, reports |
| `coordinator/scenarios/` | the suites |
| `bench-template/` | deterministic bench template builder; `VERSION` pins the agent CLI |
| `dashboard/generate.py` | stateless HTML renderer over the spans table |
| `bin/redact`, `bin/bench-reap` | publish-time redaction; stranded-sandbox cleanup |
| `subject-template/` | the copyable adoption kit |
| `subject-template/mirror/` | the kit for a PUBLIC repository: its workflow variant (`public/`) and the private arena mirror's files (`arena/`) |
| `docs/design.md` | the design of record, with every decision and why |
| `docs/subject-integration.md` | the adoption contract |

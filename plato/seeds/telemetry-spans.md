---
seed: telemetry-spans
confirmed-by: grill 2026-08-31
---

# telemetry-spans

Every step of every run is an OTel span into ClickHouse (schema ported from
agent-gauntlet: two-row scenario spans, subject-leading sort, provenance
attrs); agent self-report (OTLP drop file relayed by the coordinator) joins
harness spans in one SQL on gentar.run_id. Verdicts come from reality —
files, processes, SQL, spans, TTY output — never agent self-report alone.

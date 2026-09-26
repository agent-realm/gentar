# Telemetry destination

Sending every run as an OTLP trace to a collector such as ClickStack, and what is scrubbed before it leaves.

An arena's ClickHouse dies with the arena; a **telemetry destination** keeps its runs. When
`GENTAR_OTLP_EXPORT` (a collector's OTLP/HTTP base URL) and `GENTAR_OTLP_KEY`
(its ingestion key, sent as the `authorization` header) are both set, the
coordinator sends each run there as one trace, through the arena's own
collector:

- `scenario` is the root; every step (`bench.create`, `subject.push`,
  `oracle.step.N`, `assert`, `run.*`) is its child, with duration, status and
  scrubbed output;
- the agent's session becomes `agent.session` → `agent.turn` → `agent.tool`
  with real start and end times and numbers only (`gentar.agent.*`: model,
  tokens, tool class, error);
- the resource names the subject (`service.name`) and the CI run
  (`gentar.ci_repo`, `gentar.ci_run_id`, …) and the engine sha.

Scrubbing is the coordinator's (the run's Redactor), applied before a span
leaves it; a driver transcript is sent only as its length. The collector
forwards only what arrives on its `otlp/scrubbed` receiver, which only the
coordinator reaches (compose network, never published): a bench's
self-report is re-sent through it scrubbed and joined to the run's trace,
while the raw copy — and anything else sent to `:4318` — stays in the local
ClickHouse. A test holds that no export pipeline reads the raw receiver.
Export is best-effort — a collector that is down is warned about once and never
changes a verdict. The arena keeps its local copy as before.

The organisation's destination is ClickStack on arf (VM 149,
`http://10.10.10.58:4318`, HyperDX on `:8080`, retention forever). For this
repository both settings are Actions secrets; locally:

```bash
GENTAR_OTLP_EXPORT=http://10.10.10.58:4318 \
  with-secret GENTAR_OTLP_KEY=keychain:pilot/clickstack-ingest -- bin/arena run smoke
```

`compose.export.yml` is what wires it (layered by `bin/arena`, the kit's
`run.sh` and CI when the URL is set); one setting without the other is
refused by the kit, and compose itself refuses the file with either unset.
It replaced the v0.5.0 history store (`history/`, `bin/history`), retired
once ClickStack was proven in CI.

# Guide — Send telemetry to ClickStack

**You want:** every run kept as a trace outside the arena. An arena's
ClickHouse dies with the arena; a telemetry destination keeps its runs.

## What leaves, and how

With both settings set, the coordinator sends each run as one OTLP trace,
through the arena's own collector:

- `scenario` is the root, and every step is its child, with duration,
  status and scrubbed output;
- the agent's session becomes `agent.session` → `agent.turn` →
  `agent.tool`, with numbers only;
- judged turns add `judge.call` spans, which carry a hash and a length of
  what was sent, never screen text;
- the resource names the subject (`service.name`) and the CI run
  (`gentar.ci_repo`, `gentar.ci_run_id`, …).

Scrubbing happens in the coordinator before a span leaves it: bench-host
settings and declared credentials, in every encoding, and any 8+
character piece of a credential. A driver transcript is sent only as its
length. Export is best-effort: a collector that is down never changes a
verdict. Details are in the [telemetry reference](../reference/telemetry.md).

## Steps

1. Get the collector's OTLP/HTTP **base URL** (no path; the exporter
   appends `/v1/traces`) and a **reference** to its ingestion key, from
   whoever runs the collector.
2. **Locally**, lend both for a run:

   ```bash
   GENTAR_OTLP_EXPORT=http://collector.example.internal:4318 \
     with-secret GENTAR_OTLP_KEY=<key-reference> -- bin/arena run smoke
   ```

   From a subject repository, use `gentar/run.sh <suite>` in place of
   `bin/arena run smoke`.
3. **In CI**, set both as repository **secrets**: `GENTAR_OTLP_EXPORT` and
   `GENTAR_OTLP_KEY`. The URL is a secret too, because an internal
   address does not belong in public logs. The kit's workflow passes them
   through.

Both or neither: the kit's `run.sh` and `bin/arena` refuse one without
the other, with exit 2, before any container starts.

## Check

Query the collector's store for your run. In ClickStack (HyperDX, or SQL
against its ClickHouse), filter `otel_traces` on
`ResourceAttributes['gentar.ci_run_id']` for a CI run, or on
`ServiceName` for a subject. You should see one trace per scenario,
rooted at `scenario`.

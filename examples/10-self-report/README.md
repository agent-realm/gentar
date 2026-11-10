# 10 — self-report, proven

**Shows:** software inside the bench reporting its own telemetry, and the
arena proving the report arrived. Use it when your tool emits OpenTelemetry
spans and you want a suite to fail if they never land.

**Introduces:**

| key | what it does |
|---|---|
| `$WORKSPACE_DIR/gentar-otlp.json` | the drop file: software in the bench writes one OTLP/HTTP-JSON body there |
| `GENTAR_RUN_ID` | given to every oracle step; tag your spans with it as the resource attribute `gentar.run_id` |
| `[verify] self_report = true` | before the verdict, the coordinator relays the drop file to the arena's collector, and the run fails unless the span joins the run's harness spans in ClickHouse within 30 seconds |

```
gentar/scenarios/example-self-report.toml
```

The oracle step stands in for your tool's exporter: it writes one span
tagged with the run id. Without `self_report`, gentar relays a drop file
best-effort and never checks it. The suite's command check only proves the
file is there, which would still pass if the collector rejected the body or
ClickHouse never kept the span. The `otlp-join run_id` assertion is the proof.

## Run it

These files are shaped like an adopted repo: copy `gentar/` from this
directory into a repo that already has the kit (see
[the adoption kit](../../subject-template/README.md)), delete the kit's
template suite `gentar/scenarios/first-suite.toml` (see
[trying an example](../README.md#trying-an-example)), then:

```bash
gentar/dryrun.py                     # replays the step; the join reads UNVERIFIED
gentar/run.sh example-self-report    # for real, on a bench; the exit code is the verdict
```

## Passing looks like

The dry-run runs the step and the file check, then reports
`example-self-report.toml: UNVERIFIED (the self-report join needs the arena)`
and exits `1`: it has no collector and no ClickHouse. `run.sh --check`
lists the same line and stays clean, since it accepts UNVERIFIED.

On a bench: exit `0` with 2 of 2 assertions passing, the command and
`otlp-join run_id`. Change the attribute key `gentar.run_id` in the step to
anything else: the file check still passes, but the join finds no span of
this run, and the suite fails with exit `1`.

The engine's own `otlp-selfreport` suite is the same check in Node, and it
runs in gentar's gate. See [the runner reference](../../docs/reference/runner.md)
for how the relay works.

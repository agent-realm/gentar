# 04 — credentials

**Shows:** a suite that needs a real agent and a real key. The agent
(claude-code, from the bench template) is asked to write a file; the file
is the verdict, never the agent's reply.

**Introduces:** `credentials`, `template`, `[budget]`.

- `credentials` lists environment variable **names**, never values.
  Entries are **alternatives**: here the first-party key alone, *or* the
  token and its endpoint **together** (a nested list is an all-of group).
- **No credentials, no run:** when no group is fully set, the run is
  **refused with exit 2 before any bench exists**. A missing key is a usage
  error, not a red test.
- Only the winning group's values reach the bench, and every declared
  value is redacted from reports, the dashboard and the telemetry.
- A flat `["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]` would mean
  *either one*: nest the pair. `plan.py lint` catches the flat shape.

## Run it

Copy `gentar/` into an adopted repo ([the adoption kit](../../subject-template/README.md)),
set one group — in CI as repository **secrets**, locally lent for one run —
and run:

```bash
with-secret ANTHROPIC_API_KEY=<your key reference> -- gentar/run.sh example-agent
```

`gentar/dryrun.py` **skips** this suite by name: it needs a real agent.

**Pass:** exit `0` and `greeting.txt` holds the line. Without any group:
exit `2`, "credential guard", and no bench was created.

Next: [05 — a judged expect](../05-judged-expect/README.md).

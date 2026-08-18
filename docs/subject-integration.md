# Subject integration — wiring a repo into the gentar arena

A **subject** is any repo that wants the arena to test it. The arena is
forge-agnostic at the transport level (a subject job just needs to reach
`workflow_dispatch` on `agent-realm/gentar`), but this doc describes the
GitHub shape actually wired today.

## What a subject contributes

1. **Scenario configs** — the subject states install *decisions* and
   verdict assertions, not steps. Either:
   - TOML scenarios in the subject repo under `gentar/`, passed to the
     coordinator via `GENTAR_SCENARIOS_DIR`, or
   - scenarios contributed to `gentar/coordinator/scenarios/` by PR
     (how `claude-playbooks-install` lives today).
2. **The subject checkout itself** — mounted into the coordinator
   (`subjects/<name>/`), never baked into any image. On the CI runner
   this is a plain `git clone` next to the compose file.
3. **A trigger** — the ~10-line job below.

## The subject-side job (GitHub shape)

```yaml
# .github/workflows/gentar.yml in the SUBJECT repo
name: gentar
on:
  pull_request:
  workflow_dispatch:
    inputs:
      ref:
        description: gentar ref to test against
        default: ""
jobs:
  arena:
    runs-on: ubuntu-latest
    steps:
      - name: dispatch gentar
        run: |
          curl -fsSL -X POST \
            -H "Authorization: Bearer ${{ secrets.GENTAR_DISPATCH_TOKEN }}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/agent-realm/gentar/actions/workflows/gentar.yml/dispatches \
            -d '{"ref":"main","inputs":{"scenario":"'"${{ github.event.inputs.ref }}"'"}}'
```

`GENTAR_DISPATCH_TOKEN` is a PAT (or fine-grained token) with
`actions:write` on `agent-realm/gentar`. The dispatch runs the requested
scenario on the arena's self-hosted runner; the subject's own job
then polls the resulting run (or simply fires-and-forgets — the arena's
dashboard is the record). Passing the PR head sha as `subject_ref` makes
the arena test exactly the code under review.

For **subject suites** (scenarios that mount the subject repo), the
arena side also needs read access to the subject checkout:
`GENTAR_SUBJECT_TOKEN` on `agent-realm/gentar` (a PAT with `repo:read`
for the subject's repo). Without it, subject suites are skipped with a
notice and only subjectless suites run.

## Trigger tiers

| Tier | Fires | Suites |
|---|---|---|
| gate | every gentar PR / push, every subject dispatch | deterministic subjectless (smoke, bench-template-verify, otlp-selfreport, budget-sim, scripted pair) |
| nightly | cron (arena repo) | subject suites behind `GENTAR_BUDGET_CAP` |
| dispatch | manual / subject repo | one named scenario, arbitrary gentar ref |

## Conventions

- Scenario names are subject-local; the `subject` column in telemetry
  separates components (gauntlet policy, ported).
- A subject never gets a private sandbox image baked from its checkout —
  that pattern is retired constellation-wide. Subjects mount, arenas run.
- Verdicts come from reality: files, commands, processes — never from
  "the agent said it worked".

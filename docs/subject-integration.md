# Subject integration — wiring a repo into the gentar arena

A **subject** is any repo that wants the arena to test it. The arena is
forge-agnostic at the transport level (a subject job just needs to reach
`workflow_dispatch` on `agent-realm/gentar`), but this doc describes the
GitHub shape actually wired today.

Two modes, pick either or both:

- **Central arena** (below) — gentar's CI runs everything; your repo
  fires a dispatch. One bench-host, one dashboard.
- **Own arena** (bottom) — your repo runs the compose stack itself in
  its own CI. Scenarios live in your repo; any trigger conditions you
  want; the arena is a `git clone` away.

Both modes start from the same kit: [`subject-template/`](../subject-template/)
in this repo — a copyable `gentar/` dir with every file, every field
commented, and the seven-step checklist. Adoption is copy-and-fill,
not archaeology.

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
| nightly | cron (arena repo) | subject suites behind `GENTAR_BUDGET_CAP`; `agent-smoke` when `ANTHROPIC_API_KEY` is set |
| dispatch | manual / subject repo | one named scenario, arbitrary gentar ref |

## Credentials (agent-in-the-loop suites)

A scenario that drives a real agent declares what it needs, by NAME:

```toml
[scenario]
credentials = ["ANTHROPIC_API_KEY"]   # env var names, nothing else
```

The contract:

- **Missing → refuse, not fail.** The coordinator exits 2 before any
  bench exists when a declared name is absent from its environment —
  a usage error, never a red test.
- **Tier-1 transport: env vars on a throwaway bench.** Present values
  are exported into every oracle step and the pty driver process
  inside the sandbox. The bench dies with the run; nothing persists.
- **Names only in the record.** Spans and run reports carry the names
  a run required, never a value.
- **Invocation:** the credential must reach the coordinator container —
  `docker compose run --rm -e ANTHROPIC_API_KEY coordinator run agent-smoke`
  (CI maps the `ANTHROPIC_API_KEY` secret to env and passes `-e`).

## Conventions

- Scenario names are subject-local; the `subject` column in telemetry
  separates components (gauntlet policy, ported).
- A subject never gets a private sandbox image baked from its checkout —
  that pattern is retired constellation-wide. Subjects mount, arenas run.
- Verdicts come from reality: files, commands, processes — never from
  "the agent said it worked".

## Own arena — a repo runs the stack itself

gentar is compose-native; nothing about it belongs to the central
instance. A repo that wants its own arena (own triggers, own
conditions, reports on disk):

1. Carry scenarios in the repo (e.g. `gentar/scenarios/*.toml`,
   `subject = "<repo-name>"`).
2. In CI (or locally): clone gentar, stage this checkout under
   `subjects/<repo-name>/` (plain copy — no symlinks, they don't
   resolve through the bind), then:

   ```bash
   GENTAR_SUBJECTS_DIR="$PWD/subjects" \
     docker compose run --rm \
       -e GENTAR_SCENARIOS_DIR=/extra \
       -v "$PWD/gentar/scenarios:/extra:ro" \
       coordinator run <suite>
   ```

   (`GENTAR_SUBJECTS_DIR` is compose-interpolated into the subjects
   bind; the scenarios dir needs the explicit `-e`/`-v` pair because
   the coordinator reads it at runtime, inside the container.)
   Exit code is the verdict, same contract.
3. Every run writes `out/report-<run_id>.md` — steps with output
   tails, assertions with actuals, verdict, reproduce command. On
   failure, feed that file to an agent (or a human): it states
   everything needed to act.

The one shared resource is the **bench-host** (any Linux machine with
`sbx`, reached over SSH; `GENTAR_BENCH_*` in `.env`). The runner needs
Docker + network reachability to it — GitHub-hosted `ubuntu-latest`
can't reach an internal bench-host, so own-arena CI runs on a
self-hosted runner inside the network (any machine with Docker; the
pilot's Mac qualifies).

`claude-playbooks` is the reference own-arena subject (see its
`gentar/` dir); [`subject-template/`](../subject-template/) is that
shape genericized into a copyable kit.

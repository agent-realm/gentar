# Subject integration — wiring a repo into the gentar arena

A **subject** is any repo that wants the arena to test it. The arena is
forge-agnostic at the transport level (a subject job just needs to reach
`workflow_dispatch` on `agent-realm/gentar`), but this doc describes the
GitHub shape actually wired today.

Two modes, pick either or both. Both are first-class; the difference is
who operates the arena, not what a subject declares.

- **Central arena** (below) — an arena someone else runs does the work;
  your repo fires a dispatch. Nothing to host. One bench-host, one
  dashboard.
- **Own arena** (bottom) — your repo runs the compose stack itself in
  its own CI. Scenarios live in your repo; any trigger conditions you
  want; the engine is a `git clone` away.

Both modes start from the same kit: [`subject-template/`](../subject-template/)
in this repo — a copyable `gentar/` dir with every file and field
commented. **This document is the contract; the kit's
[README](../subject-template/README.md) is the procedure** — the
numbered steps, the commands, and what to observe after each. Read that
to adopt; read this for what the two sides owe each other.

Adoption is a process, not a copy: a subject's scenarios are updated
alongside the code they assert, and the engine version is pinned and
bumped deliberately. See [Keeping a subject
current](#keeping-a-subject-current) below, and the kit README's "When
your code changes".

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
3. **A trigger** — the ~10-line job below, or the own-arena workflow.
4. **Maintenance** — scenarios updated in the same change as the
   behaviour they assert, and an engine pin bumped on purpose.

## What the engine guarantees

In return, and these are stable across engine versions within a major:

- **The verdict is the exit code.** `0` pass · `1` fail · `2`
  usage/config refusal. No test-report layer in between; a refusal is
  never reported as a failing test.
- **A report for every terminal outcome**, at `out/report-<run_id>.md`
  (own-arena runners copy it into the subject's `gentar/reports/`):
  every step with its output tail, every assertion with what it
  actually saw, the verdict, and a reproduce command. A failing report
  is actionable by a reader who did not watch the run.
- **Refusal before spend.** A missing credential, an unknown scenario
  name, or a declared budget above the cap exits 2 before any bench is
  created.
- **Subjects mount, never bake.** The checkout is staged at run time;
  no image built by the engine ever contains it.
- **Credential values never enter the record.** Spans and reports carry
  the NAMES a run required. Values are exported into the bench, which
  dies with the run.
- **Only the winning credential group is forwarded.** With alternatives
  declared, a stray variable belonging to a losing group cannot ride
  along and redirect the run.
- **A fresh bench per scenario.** The bench is the reset; a wedged run
  is discarded, never repaired.

## The subject-side job (GitHub shape)

```yaml
# .github/workflows/gentar.yml in the SUBJECT repo
name: gentar
on:
  pull_request:
  workflow_dispatch:
    inputs:
      scenario:
        description: scenario to run in the arena
        default: my-suite
jobs:
  arena:
    runs-on: ubuntu-latest
    steps:
      - name: dispatch gentar
        env:
          # Inputs and refs go through env, never into the command
          # line — a branch name is attacker-influenced text.
          SCENARIO: ${{ github.event.inputs.scenario || 'my-suite' }}
          # The PR HEAD sha, not github.sha: on a pull_request event
          # github.sha is the merge commit, so the arena would test
          # something that exists in no branch.
          SUBJECT_REF: ${{ github.event.pull_request.head.sha || github.sha }}
          TOKEN: ${{ secrets.GENTAR_DISPATCH_TOKEN }}
        run: |
          jq -n --arg s "$SCENARIO" --arg r "$SUBJECT_REF" \
            '{ref:"main", inputs:{scenario:$s, subject_ref:$r}}' \
          | curl -fsSL -X POST \
              -H "Authorization: Bearer $TOKEN" \
              -H "Accept: application/vnd.github+json" \
              https://api.github.com/repos/agent-realm/gentar/actions/workflows/gentar.yml/dispatches \
              --data @-
```

Three inputs the arena's `workflow_dispatch` accepts: `scenario` (which
suite), `subject_ref` (which commit of YOUR repo to check out), and
`ref` (which gentar ref runs the arena — omitted above, so the arena's
default branch runs it; pin it to a release tag or audited SHA if the
engine version matters to you).

`GENTAR_DISPATCH_TOKEN` is a PAT (or fine-grained token) with
`actions:write` on the arena repo. The dispatch runs the requested
scenario on the arena's self-hosted runner; the subject's own job then
polls the resulting run, or simply fires and forgets — the arena's
dashboard is the record. Sending the PR head sha as `subject_ref` is
what makes the arena test exactly the code under review rather than
whatever is on the subject's default branch.

Note the asymmetry with the own-arena workflow: a dispatch tests the
head sha of a PUSHED branch, so the change must be pushed first and an
uncommitted fix cannot be tested this way. The own arena stages the
working tree instead. Neither is wrong; they answer different
questions.

For **subject suites** (scenarios that mount the subject repo), the
arena side also needs read access to the subject checkout:
`GENTAR_SUBJECT_TOKEN` on the arena repo (a PAT with `repo:read` for
the subject's repo). Without it, subject suites are skipped with a
notice and only subjectless suites run.

**The arena side is not self-service today.** Its dispatch job clones a
fixed list of subject repos, so onboarding a new subject to a central
arena means a pull request against that arena's workflow (adding the
clone) and a `GENTAR_SUBJECT_TOKEN` that can read your repo — both
requiring the arena operator. A subject whose scenarios live in its own
`gentar/` dir also needs them passed to the coordinator, which the
central job does not do for arbitrary repos.

If you do not operate the arena and cannot get those changes merged,
use the **own arena** mode below: it needs nothing from anybody, and
the kit wires it end to end.

## Trigger tiers

| Tier | Fires | Suites |
|---|---|---|
| gate | every gentar PR / push, every subject dispatch | deterministic subjectless (smoke, bench-template-verify, otlp-selfreport, budget-sim, scripted pair) |
| nightly | cron (arena repo) | subject suites behind `GENTAR_BUDGET_CAP`; `agent-smoke` when `ANTHROPIC_API_KEY` is set |
| dispatch | manual / subject repo | one named scenario, arbitrary gentar ref |

## Credentials (agent-in-the-loop suites)

A scenario that drives a real agent declares what it needs, by NAME —
entries are ALTERNATIVES, and a list entry is an all-of GROUP (a token
without its endpoint is half a provider and refuses):

```toml
[scenario]
# the first-party key alone, OR the token+endpoint pair together
credentials = ["ANTHROPIC_API_KEY",
               ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]]
```

The contract:

- **Missing → refuse, not fail.** The coordinator exits 2 before any
  bench exists when no alternative group is fully present in its
  environment — a usage error, never a red test (a half-present group
  refuses too; it never starts a misconfigured credentialed bench).
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
- A subject never gets a private sandbox image baked from its checkout.
  Subjects mount, arenas run.
- Verdicts come from reality: files, commands, processes — never from
  "the agent said it worked".
- The subject is the WORKING TREE, uncommitted changes included. A fix
  loop needs no commit to test.
- The bench-host is shared. A subject's suites clean up after
  themselves; nothing removes another arena's sandboxes or kills
  processes wholesale there.

## Keeping a subject current

A subject is a standing commitment, not a one-time wiring. Three kinds
of change, and what each obliges:

| What changed | What the subject does |
|---|---|
| the subject's code, same behaviour | nothing — the PR trigger re-runs the suites and the pass is the evidence |
| what the subject DOES | update the scenarios in the SAME pull request; a scenario asserts reality, so stale reality fails honestly |
| the ENGINE | bump `GENTAR_REF` deliberately: change the pin, run every suite, commit the bump on its own |

The middle row is the one that decides whether an arena is worth
having. A suite that still passes after a behaviour change either
tested the change correctly or was never testing the behaviour — and a
suite going red because the thing it asserts moved is the suite doing
its job. Landing the code and the scenario in separate pull requests
leaves the default branch red in between, which teaches people to
ignore the arena.

The engine row is why the kit pins a release TAG and not a branch.
Tracking the engine's `main` means a subject's suites can change
behaviour on a day nobody touched the subject; that has happened (a kit
advertising a scenario feature the engine tip did not parse yet). Both
modes have a pin: own-arena sets `GENTAR_REF` in `run.sh`, central
dispatch passes the arena ref in the dispatch payload.

### The fix loop

The point of a failure is that something can act on it. Every terminal
outcome writes a report naming every step with its output, every
assertion with the actual it saw, the verdict, and a reproduce command.
On a failure: hand the report to an agent, it fixes the repo, rerun the
same suite against the working tree, iterate to green. No commit and no
CI round trip per attempt.

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

   **That invocation leaks, and must be wrapped.** `--rm` removes only
   the coordinator: `clickhouse` and `otelcol` come up via `depends_on`
   as ordinary `up` containers, and `clickhouse` owns a named volume, so
   every project strands two containers and a volume per run. Tear the
   project down after it — CI in an `if: always()` step — or copy
   `subject-template/gentar/run.sh`, which starts every service as a
   one-off `compose run -d --rm` (daemon-level `AutoRemove`, so a
   `SIGKILL`ed run still cleans up) and traps teardown on top.
3. Every run writes `out/report-<run_id>.md` — steps with output
   tails, assertions with actuals, verdict, reproduce command. On
   failure, feed that file to an agent (or a human): it states
   everything needed to act.

The one shared resource is the **bench-host** (any Linux machine with
`sbx`, reached over SSH; `GENTAR_BENCH_*` in `.env`). gentar ships no
bench-host and no default identifying one: `.env.example` carries
placeholders, and a tier whose install-identity vars are unset is
refused (exit 2) before any bench exists, naming the vars it needs.
Only the selected tier's vars are required, so an sbx-only install
never configures tart. The runner needs
Docker + network reachability to it — GitHub-hosted `ubuntu-latest`
can't reach an internal bench-host, so own-arena CI runs on a
self-hosted runner inside the network (any machine with Docker; the
pilot's Mac qualifies).

### Engine source

`run.sh` clones the engine over anonymous https by default, which is
all a public engine repo needs. Two knobs cover the rest:

- `GENTAR_REPO_URL` — any git URL: a fork, an internal mirror, a local
  path. Nothing else changes.
- `GENTAR_CLONE_SSH_KEY` — path to a read-only deploy key, for a
  PRIVATE engine repo. https then fails on a CI runner while a laptop
  may still succeed through a credential helper, which is how that
  difference stays hidden until CI.

### Ports

Two arenas on one Docker host collide on the published ClickHouse
(8123) and OTLP (4318) bindings. Both are env knobs the compose file
reads — `GENTAR_CLICKHOUSE_HOST_PORT` and `GENTAR_OTLP_HOST_PORT` —
and `run.sh` passes the environment through, so moving them needs no
file edit. Symptom when they collide: `port is already allocated`.

[`subject-template/`](../subject-template/) is this shape as a copyable
kit, with the adoption procedure in its
[README](../subject-template/README.md).

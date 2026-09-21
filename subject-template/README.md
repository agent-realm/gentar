# Subject template — adopt the arena in seven steps

This directory is a **kit**: copy it into a repo and that repo is a
gentar subject. It exists because "how do I get tested by gentar?"
should be copy-and-fill, not archaeology across the reference subject.

Everything here is genericized from **claude-playbooks**, the reference
own-arena subject (`/Users/polat/DEV/claude-playbooks/gentar` locally;
its `gentar/` dir is what this template abstracts). The two trigger
modes and the full contracts live in
[`docs/subject-integration.md`](../docs/subject-integration.md) — this
page is the doing of it.

## What a subject declares

Adopting gentar is five declarations, all living in the copied
`gentar/` directory plus one workflow:

| # | Declaration | Where it lives | Default the kit gives you |
|---|---|---|---|
| 1 | **Subject name** | `subject = "…"` in every scenario TOML; `SUBJECT` in `run.sh` | your repo's basename |
| 2 | **Suites** | `gentar/scenarios/*.toml` — install *decisions* + reality assertions, never scripts | `first-suite.toml`, fully commented |
| 3 | **Credentials** | `credentials = [names]` per suite — env var NAMES (flat strings; all-of groups aren't in the engine on `main` yet), alternatives, none = oracle suite | none (first-suite is credential-less) |
| 4 | **Trigger** | `.github/workflows/gentar-arena.yml` (own arena) and/or a ~10-line dispatch job (central arena — below) | own-arena workflow, push + tags + dispatch |
| 5 | **Engine pin** | `GENTAR_REF` (default `main`), re-fetched and rebuilt every run | `main` |

The verdict contract is the arena's, not yours: exit code `0` pass ·
`1` fail · `2` usage/config refusal, and assertions read reality
(files, processes, output) — never "the agent said it worked".

## The seven steps

1. **Copy** `subject-template/gentar/` and
   `subject-template/.github/workflows/gentar-arena.yml` into your repo
   (the workflow goes to the same relative path).

   ```bash
   cp -R subject-template/gentar        /path/to/your-repo/gentar
   cp -R subject-template/.github       /path/to/your-repo/.github   # if none
   ```

2. **Declare the name** — replace `REPLACE-ME` in
   `gentar/scenarios/first-suite.toml`'s `subject` (run.sh already
   derives the same from the repo basename; change `SUBJECT` there only
   if the two must differ).

3. **Run the template suite for real** — proves the whole chain before
   you've written a line of your own:

   ```bash
   gentar/run.sh first-suite
   ```

   Needs Docker + reach to a bench-host (any Linux machine with `sbx`;
   first run clones gentar to `gentar/.arena` and seeds `.env` from
   `.env.example`). Green here = staging, engine pin, image build,
   bench, verify and reporting all work.

4. **Write your first real suite** — duplicate `first-suite.toml`,
   replace `[oracle].steps` with what your repo does and
   `[[verify.commands]]` with reality. Keep the template suite or
   delete it. Driver (`[driver]` pty turns) and budget blocks are
   commented in the template — the vocabulary is the scenario schema:
   `coordinator/gentar/toml_scenario.py`.

5. **Prove it cheap** — `gentar/dryrun.py` replays steps, turns and
   assertions in a scratch HOME in ~1s, no bench. A scenario is shell
   in TOML three quotes deep; find the missing quote before it costs a
   bench VM. Suites declaring `credentials` are skipped (dryrun has no
   agent).

6. **Wire CI** — the copied workflow runs every suite on push. It needs
   a self-hosted runner labeled `arena` (Docker + bench-host reach; any
   always-on machine, ~5 min: repo → Settings → Actions → Runners).
   Set the secrets/vars: `BENCH_SSH_KEY`, `GENTAR_CLONE_KEY` (private
   engine repo), and agent credentials only if you have agent suites.

7. **Or dispatch instead** — if you'd rather not run anything, the
   central arena mode is a ~10-line job in YOUR repo (contract in
   [`docs/subject-integration.md`](../docs/subject-integration.md)):
   a `workflow_dispatch` curl with a `GENTAR_DISPATCH_TOKEN` PAT, and
   the arena side gets `GENTAR_SUBJECT_TOKEN` to read your checkout.
   Both modes can coexist; many subjects dispatch from PRs and run the
   own arena on pushes.

## Conventions (the ones that bite)

- **Subjects mount, never bake.** Your checkout is staged as
  `subjects/<name>/` at run time — no image ever carries it. The
  per-repo baked sandbox is the retired anti-pattern this arena exists
  to enforce.
- **Scenario names are subject-local**; the `subject` column in
  telemetry separates components.
- **Working tree is the subject** — uncommitted changes included, so
  the fix loop is fix-and-rerun, no commit needed to test.
- **A fresh checkout is not a fresh engine** — `run.sh` re-fetches
  `GENTAR_REF` AND rebuilds the coordinator image every run; don't
  delete the build step to save time.
- **Secrets travel by name only.** Credential VALUES reach the bench
  via env at run time; spans and reports carry names, never values.

## Kit layout

```
subject-template/
  gentar/                          # ← copies to <your-repo>/gentar/
    README.md                      # subject-side doc (fill in the table)
    scenarios/first-suite.toml     # every field, commented
    run.sh                         # stage, run, report (local kickoff)
    dryrun.py                      # bench-less replay (~1s)
    .gitignore                     # reports/ .arena/ .env
  .github/workflows/gentar-arena.yml   # ← copies to your workflows dir
```

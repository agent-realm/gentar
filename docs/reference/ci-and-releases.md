# CI contract and releases

How gentar runs in CI (the hosted unit tests, and the bench suites in the private mirror) and how its own releases are cut and proven.

## CI contract

`docker compose up` plus an exit code is the entire integration surface —
no forge-specific features inside the arena, so the same suites run on
GitHub, Gitea, Jenkins, cron, or a laptop unchanged.

gentar is public, so no self-hosted runner serves it: a fork's pull request
can bring its own workflow to any runner registered to a public repository
(the D5 decision, 2026-10-08). Since 2026-10-12 the GitHub wiring has two
halves:

- **The public workflow** ([`.github/workflows/gentar.yml`](../../.github/workflows/gentar.yml))
  runs on GitHub-hosted runners only, with no secrets.
- **The bench suites** run in the PRIVATE mirror `agent-realm/gentar-arena`.
  It pulls this repository and runs them on its own self-hosted runner.

| Where | Fires on | Runs |
|---|---|---|
| public `gentar.yml` | every PR, every push to `main` | the unit suite on the checkout (ubuntu-latest) |
| public `gentar.yml` | a `v*` tag | a check that the tag equals `v$(cat VERSION)` |
| mirror, `gate` tier | a dispatch with `scenario=gate`, or daily at 00:17 UTC | six deterministic bench suites: `smoke`, `bench-template-verify`, `otlp-selfreport`, `budget-sim`, `scripted-onboarding`, `scripted-danger` |
| mirror, `nightly` tier | daily at 01:17 UTC, or a dispatch with `scenario=nightly` | the nightly suites; the agent suite skips without a provider key, the subject suites without a subject token |
| mirror, one scenario | a dispatch with `scenario=<name>` | that scenario |

**The bench suites are a POST-MERGE check, not a PR gate.** The mirror
admits a commit only when it is reachable from gentar's `main` or from a
`v*` tag, so a pull request's head never reaches a bench. The order is:

1. review the pull request, which runs the hosted unit tests;
2. merge it;
3. dispatch the mirror on the merge commit, or wait for its daily gate.

**The mirror's schedule** runs on the head of gentar's `main`:

- the gate, daily at 00:17 UTC;
- the nightly, daily at 01:17 UTC. Its agent suite skips without a provider
  key, and its subject suites skip without a subject token, each with a
  notice.

These times are nominal, and the schedule is best-effort. A merge is
normally swept by the next scheduled gate, but GitHub can delay a scheduled
run, and under heavy load drop it. To be certain a merge commit was swept,
dispatch the gate on it, as the release steps do.

A fork's pull request runs the hosted unit tests and nothing else. The
mirror is private, so its runs and reports are visible to its maintainers
only.

The mirror runs one bench at a time on purpose: concurrent `sbx create`
calls on a shared bench-host contend on a cross-process auth lock and wedge
each other.

Two coordinator-side guards keep a scheduled arena from running away:
a **budget guard** (`GENTAR_BUDGET_CAP` against each scenario's declared
`[budget] tokens`, accumulated from past runs' spans) that refuses an
over-cap run with exit 2, and a **flake quarantine**
(`GENTAR_QUARANTINE=name,…`) that skips a named suite rather than failing
it. A quarantined suite does not run and is never a pass: it exits 0, its
report and span say `skip`, and the kit's `run.sh` ends with a
`run summary: … quarantined, not run` line (a warning annotation in
Actions). Both live in the engine, not in forge features, so they survive
a change of forge.

## Releases

`VERSION` at the repo root is the engine version; `CHANGELOG.md` records
what each one contains.

Cutting a release:

1. Bump `VERSION` and the kit's pin (`GENTAR_REF` default in
   `subject-template/gentar/run.sh`, and the kit READMEs).
2. Write the release document, `docs/releases/v$(cat VERSION).md`: what
   changed and why, the upgrade note for adopters, any lifted guard, any
   cleanup an adopter must do, and known limits.
3. Add the `CHANGELOG.md` entry, pointing to that document.
4. Land 1–3 through a reviewed release PR, merged as a merge commit.
5. Prove the merge commit on the mirror. Dispatch its gate on that sha
   (`gh workflow run arena.yml -R agent-realm/gentar-arena -f scenario=gate -f sha=<merge commit>`)
   and wait for it to pass.
6. Tag `v$(cat VERSION)` (annotated) on that commit and push the tag.
7. Publish the GitHub release from the document:
   `gh release create v$(cat VERSION) --title "gentar v$(cat VERSION)" --notes-file docs/releases/v$(cat VERSION).md`.

Before any release, the repo must meet the docs standard: README, `docs/`
tutorials and guides, `examples/` (each with its README) and `AGENTS.md`.

Two proofs, one commit. The mirror's green gate on the release commit
proves the bench suites; it is dispatched by hand, before the tag. Then the
public workflow's `v*` job fails if the tag does not equal
`v$(cat VERSION)`, so a release tag can never disagree with the file it
claims to be.

**What an adopter pins** is a git ref of this repo (`GENTAR_REF` in the
adoption kit). Pin a release tag, not a branch: scenario TOML schema and
the exit-code contract are stable within a minor version, engine internals
are not. Pre-1.0, a minor bump may change the schema — read the changelog
before moving.

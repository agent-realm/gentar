# CI contract and releases

How gentar runs in CI (gate, nightly, dispatch) and how its own releases are cut and proven.

## CI contract

`docker compose up` plus an exit code is the entire integration surface —
no forge-specific features inside the arena, so the same suites run on
GitHub, Gitea, Jenkins, cron, or a laptop unchanged. The GitHub wiring
that exists today ([`.github/workflows/gentar.yml`](../../.github/workflows/gentar.yml)):

| Tier | Fires on | Runs |
|---|---|---|
| gate | every PR, every push to `main` | six deterministic bench-only suites: `smoke`, `bench-template-verify`, `otlp-selfreport`, `budget-sim`, `scripted-onboarding`, `scripted-danger` |
| keyword tag | a tag pushed at **any** commit | `arena` → every gate suite at that commit, unmerged branches included; `arena-<scenario>` → that one suite (an unknown name refuses with exit 2, no bench spent); `v*` → **release proof**, the full gate. Re-run by deleting and re-pushing the tag |
| nightly | cron, post-merge | the scripted and real-agent suites plus every subject suite, behind a budget cap and a read token |
| dispatch | manual, or from another repo | one named scenario at an arbitrary engine ref and subject ref |

The gate runs one bench at a time on purpose: concurrent `sbx create`
calls on a shared bench-host contend on a cross-process auth lock and
wedge each other.

Two coordinator-side guards keep a scheduled arena from running away:
a **budget guard** (`GENTAR_BUDGET_CAP` against each scenario's declared
`[budget] tokens`, accumulated from past runs' spans) that refuses an
over-cap run with exit 2, and a **flake quarantine**
(`GENTAR_QUARANTINE=name,…`) that skips a named suite rather than failing
it. Both live in the engine, not in forge features, so they survive a
change of forge.

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
5. Tag `v$(cat VERSION)` (annotated) on `main` and push the tag.
6. Publish the GitHub release from the document:
   `gh release create v$(cat VERSION) --title "gentar v$(cat VERSION)" --notes-file docs/releases/v$(cat VERSION).md`.

Before any release, the repo must meet the docs standard: README, `docs/`
tutorials and guides, `examples/` (each with its README) and `AGENTS.md`.

The tag *is* the proof. A `v*` tag runs the full gate at that commit, and
a guard in the workflow fails the job if the tag does not equal
`v$(cat VERSION)` — so a release tag can never disagree with the file it
claims to be.

**What an adopter pins** is a git ref of this repo (`GENTAR_REF` in the
adoption kit). Pin a release tag, not a branch: scenario TOML schema and
the exit-code contract are stable within a minor version, engine internals
are not. Pre-1.0, a minor bump may change the schema — read the changelog
before moving.

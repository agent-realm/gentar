# gentar documentation

Start with the tutorials in order. Reach for a guide when you have one
job to do. Use the reference when you need every detail of one part.

## Tutorials — learn by doing, in order

| # | Tutorial | You end with |
|---|---|---|
| 1 | [First run](tutorials/01-first-run.md) | the engine's `smoke` suite green on your own bench-host, and a report you can read |
| 2 | [Adopt a repo](tutorials/02-adopt-a-repo.md) | your repo as a gentar subject: a suite, a pinned engine, CI and a run policy |
| 3 | [A judged turn](tutorials/03-a-judged-turn.md) | a brittle regex `expect` replaced by a semantic judgment, measured with fixtures |
| 4 | [A goal pilot](tutorials/04-a-goal-pilot.md) | a judge driving a TUI toward a goal over a closed action set, judged over N runs |

## Guides — one job each

| Guide | When you want to |
|---|---|
| [Deploy an arena](guides/deploy-an-arena.md) | stand up a bench-host, a self-hosted runner and the secrets CI needs |
| [An arena for a public repository](guides/public-repo-arena.md) | run phase 2 of a PUBLIC repo in a private arena mirror, with no self-hosted runner on it |
| [Send telemetry to ClickStack](guides/send-telemetry-to-clickstack.md) | keep every run as a trace outside the arena |
| [Run policy and releases](guides/run-policy-and-releases.md) | decide which suites run when, and gate a release on them |
| [Measure a judge with fixtures](guides/measure-a-judge-with-fixtures.md) | know that a judged turn answers right before it gates anything |
| [Debug a red run](guides/debug-a-red-run.md) | turn a failing or refused run into a fix |
| [Review an adaptation](guides/review-an-adaptation.md) | find what the repo now does that no suite asserts |
| [Pick a bench tier](guides/bench-tiers.md) | see why `sbx` is the 1.0 tier, and what keeps `tart`, `osb` and `daytona` experimental |

## Reference — everything about one part

| Reference | Covers |
|---|---|
| [End-to-end runner](reference/runner.md) | compose stack, benches, scenarios, the exit-code contract, `bin/arena` |
| [Reviver](reference/reviver.md) | the run report and the fix loop |
| [Pilot simulator](reference/pilot-simulator.md) | driver turns, the danger gate, credentials, semantic turns, goal pilots, rates, soft judgments |
| [Telemetry](reference/telemetry.md) | what leaves the arena, and how it is scrubbed |
| [Scenario inventory](reference/scenario-inventory.md) | the engine's own suites and what each proves |
| [CI and releases](reference/ci-and-releases.md) | the engine's own workflow tiers, guards and release procedure |
| [Bench tiers](reference/bench-tiers.md) | each tier's setup in full |
| [Design tenets](reference/design-tenets.md) | the rules the engine is built on |
| [Layout](reference/layout.md) | where everything lives in this repository |

## Examples

[`examples/`](../examples/README.md) is a ladder, from a one-step oracle
up to a full adopted subject. Each rung has its own README and is
runnable as it stands.

## Releases

[`releases/`](releases/) holds one document per release: what changed and why,
the upgrade note for adopters, and known limits. Each is also that
release's GitHub release notes.

## For agents

[`AGENTS.md`](../AGENTS.md) is the entry for an agent. It covers adopting
gentar into a repo, deploying an arena, and what must be true before any
release.

## Background and history

- [`design.md`](design.md) — the engine's design rationale.
- [`scope-map.md`](scope-map.md) (rendered: [`scope-map.html`](scope-map.html)) —
  what contains what, with every relation counted.
- [`subject-integration.md`](subject-integration.md) — the contract
  between a subject and an arena: the own arena, on a self-hosted runner or
  through the arena mirror for a public repo (the central dispatch, retired
  since 2026-10-12, has a short record there).
- [`buildplan-2026-08-18-v1.md`](buildplan-2026-08-18-v1.md) — the
  original build plan. It is **historical** and kept for the record;
  where it disagrees with the rest of the docs, the rest of the docs win.

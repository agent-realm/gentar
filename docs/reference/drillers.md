# Reference: drillers

**Status: the bench-free core only. No driller can run yet.** There is no
scenario syntax, no CLI entry and no bench wiring. Those come after the
pilot decides where drillers run (see [Where drillers run](#where-drillers-run)).

## What a driller is

A driller is an agent that wears a **hat** (the white hat security
professional first; QA, the outlier and the wanderer later). It has **no
target** and is **non-deterministic**. It uses the subject the way that
character would and writes down what it noticed. Its feedback is the
product.

| | suite | goal pilot | driller |
|---|---|---|---|
| target | fixed assertions | one stated goal | none |
| verdict | reality | reality | reality, **for the boundary only** |
| output | pass/fail | pass/fail plus a rate | typed findings, ranked over N runs |

The driller model is called by the **coordinator**, which reads the bench's
screen and types into it, as the goal pilot does. The bench itself needs no
route to the model, so a driller's bench has **no network at all** unless
its brief names a host the subject needs.

## The boundary

Every layer holds whatever the driller does. The persona prompt asks for
white hat conduct, but the prompt is not the control.

| Layer | How | Where in `gentar/driller.py` |
|---|---|---|
| network | a deny-by-default bench host (`sbx policy ls --json` must show an active global deny `**` and no global allow); one per-sandbox allow rule for the brief's exact hosts (no wildcards, no IPs), or none | `host_problems`, `allow_problems`, `policy_argv` |
| kit rules | sbx kits add per-sandbox rules on their own; any allow on the driller's sandbox that the brief did not name refuses the run before the driller types | `sandbox_problems` |
| credentials | only the brief's; any `GENTAR_`, `BENCH_`, `TYPESAFE_` or `BOUNDARY_` name is refused, by class | `never_forward` |
| hosted services | `BOUNDARY_API_KEY` present, with any value, refuses the run (exit 2) | `FORBIDDEN_ENV`, `extract` |
| after the run | `sbx policy log --json` for the sandbox: a blocked host is a finding; an allowed host off the allowlist **fails the run** | `audit`, `verdict` |
| outside the bench | the host's sandboxes and templates before and after: any change **fails the run** | `outside_changes` |

Workspace isolation (no host mounts, disposable bench), the budget caps and
the danger gate reuse the engine's existing mechanisms; they are wired in
with the run itself.

### Where drillers run

sbx cannot narrow one sandbox below its host's global policy: a deny rule
always beats an allow rule. A host whose global policy allows `**`, such as
a shared bench host that others' suites rely on, can therefore not contain
a driller. A driller refuses such a host (`start_refusals`), so it needs a
bench host whose global network policy is deny-by-default: VM 151
`gentar-driller-host` on arf, initialised with `sbx policy init deny-all`
(its global rule denies `**` for TCP and UDP).

## Findings

- **Typed with BAML:**
  - the schema is `coordinator/baml_src/drillers.baml`, and the generated
    client is committed at `coordinator/gentar/baml_client`;
  - BAML runs locally. It calls only the model route in
    `GENTAR_DRILLER_MODEL_URL` / `GENTAR_DRILLER_MODEL` /
    `GENTAR_DRILLER_MODEL_KEY` (9router on tr0);
  - BAML is pinned (`baml-py==0.226.2`), and a test holds the generator,
    the client and `requirements.txt` to the same version.
- **Evidence or nothing:** a finding stays only if its `evidence` appears
  verbatim in the transcript (`supported`). A claim the screen never
  showed is dropped.
- **Frequency:**
  - findings are clustered across N runs by category and evidence, with
    only volatile numbers normalized: timestamps, clock times, dates and
    long ids. A port or a mode is meaningful and is kept (`cluster`);
  - they are counted by runs, not by mentions, and ranked by that count;
  - a single-run finding is marked as such.
- **Reported, never a verdict:** `render` writes the report section,
  scrubbed by the run's redactor, and so is every host `verdict`
  names: a driller can put a credential into a hostname it looks up.
  The run's exit code comes from `verdict` alone.

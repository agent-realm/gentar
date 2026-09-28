# Reference: drillers

**Status: wired, not yet run live.** A scenario with a `[driller]` table
runs as N driller sessions (`bin/arena run <scenario>`), each on a fresh
bench. The first live sessions wait for the model route's key and the
pilot's choice of model provider (below).

## A driller scenario

```toml
[scenario]
name = "driller-white-hat-demo"
data = "synthetic"          # required: the scrubbed screen goes to a model

[oracle]
steps = ["..."]             # install the subject, as in any suite

[driller]
hat = "white-hat"           # the persona (gentar/driller.py PERSONAS)
runs = 5                    # sessions, each on a fresh bench (1..20)
command = "bash -l"         # the terminal the driller gets
readme = "README.md"        # in the workspace, absolute, or ~/...
help = ["tool"]             # each one's --help goes into the brief
allow = []                  # exact hosts the subject needs; none by default
max_steps = 60              # budgets end a session, not the run
seconds = 900
max_calls = 80
max_input_tokens = 400000
every = 2
```

Refused at load: any other key, a missing `data = "synthetic"`, a
`[driver]` in the same file, an unknown hat, a wildcard or IP in `allow`,
and any arena-owned credential name. The engine's calibration target is
[`driller-white-hat-demo`](../../coordinator/scenarios/driller-white-hat-demo.toml):
a synthetic CLI with two planted flaws.

## A session

The model proposes; the coordinator decides (`gentar/drill.py`). Each turn
it reads the bench's rendered screen, scrubs it, asks the model for one
step (type text, press a key, wait, or done), checks it, and only then
types it:

- the danger gate on the screen before each step, after the model answers
  and before a separate Enter, and on the text to be typed. A match ends
  the session as a boundary finding and nothing is sent;
- keys only from the engine's vocabulary; typed text printable and on one
  line;
- budgets (time, steps, model calls, input tokens) end the session, and
  the model still writes its notes.

Around it (`gentar/driller_run.py`): kit rules on the sandbox refuse the
session before the first keystroke; the brief's hosts become one allow
rule; the host is snapshotted before and after; the policy log is audited;
the notes become typed findings with evidence on screen. After N sessions
the findings are ranked (`coordinator._run_drill`) into
`driller-<scenario>-<time>.md` next to the reports. A breach stops the
sessions at once: exit 1. Findings never change the exit.

## The model route and where screens go

`GENTAR_DRILLER_MODEL_URL`, `GENTAR_DRILLER_MODEL` and
`GENTAR_DRILLER_MODEL_KEY` reach the coordinator only (compose), never a
bench, and the key and URL are scrubbed from everything exported. The
route is 9router on tr0, which is **a proxy**: the model behind it is
whichever provider the model id names (z.ai GLM, DeepSeek, Anthropic,
EVREN). So a driller's scrubbed screen leaves our infrastructure to that
provider, the same exposure as a judged turn's, which is why driller
scenarios must be synthetic.

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
| network | a deny-by-default bench host, proven by asking sbx: `sbx policy check network <canary> --json` must answer `allowed: false` in the global context for every canary, and `sbx policy ls --json` must hold no global allow; then one per-sandbox allow rule for the brief's exact hosts (no wildcards, no IPs), or none. The rule goes with the sandbox | `host_problems`, `allow_problems`, `policy_argv` |
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
`gentar-driller-host` on arf, initialised with `sbx policy init deny-all`.

Proven on VM 151 (sbx 0.45.1, 2026-09-28) from a throwaway sandbox:

- HTTP and HTTPS out get sbx's 403; raw TCP to arf, VM 142, VM 151
  and tr0 is accepted by the transparent proxy and closed, with no banner
  back; UDP and DNS are blocked by their proxies. Every attempt is in
  `sbx policy log`, and nothing is in `allowed_hosts`.
- A per-sandbox allow for one host opens exactly that host (200); every
  other host stays blocked.
- The host's own firewall (`gentar-egress.service`, nftables) also drops
  new TCP/UDP flows from VM 151 to private, tailnet, link-local and ULA
  ranges, under sbx. It survives a reboot.
- `audit` on that sandbox's real log: with the host on the brief, no
  breach; with an empty brief, the same connection is a breach and
  verdict 1.

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

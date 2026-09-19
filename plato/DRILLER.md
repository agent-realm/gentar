---
node: /s7-docs-truth/b1-docs-truth-all/d3-impatient
character: impatient
stamp: 2026-09-20-01_36
---

# d3-impatient — skip the rule, eat the bind, rush the recovery

## Character

Standup in eleven minutes; you are standing up the arena NOW. The
README has a scoping rule about `.env` files versus shell exports —
you skimmed it, decided exports are faster, and went. You set your
port knobs and project name with shell exports in one terminal,
start the quickstart, then — because you are human — your next compose
call happens in a DIFFERENT terminal without them. When the bind
error hits you do not read it carefully; you read the last line,
remove whatever looks like the squatter, re-run `up -d`, see "healthy"
and move on — the publish may or may not be there. Only when the
quickstart itself fails do you go back to the README's busy-host
notes, and you follow them at speed, exactly once each. You are the
user the field notes were written for; the question is whether they
work at the speed you read.

## Goals

- Get the quickstart green as fast as possible USING shell exports for
  everything the README allows (and some things it says not to):
  `COMPOSE_PROJECT_NAME`, port knobs, prefix — all exported, nothing
  in `.env` beyond what `cp .env.example .env` put there.
- Lose the exports (new terminal, deliberate — that is how you work),
  re-run compose, and take the drift wherever it goes: bind error,
  silent revert, recreation. At the bind error: read only its last
  line, act on that alone.
- Rush the documented recovery exactly as the busy-host note tells
  it: remove the squatter, plain `up -d`, observe "Up/healthy", assume
  victory — then verify the publish the way the note says
  (`curl /ping`, `docker port`) only because the run fails.
  Follow the `--force-recreate` note verbatim once.
- Judge each of these moments ONLY on: did the error or note tell you
  the next move at the speed you read (last line, one re-read), and
  how many minutes did the whole loop cost? Timebox each recovery
  attempt at ~2 minutes; record where you gave up and what you were
  staring at.
- End where you started: exports off, `.env` done properly per the
  scoping rule, quickstart green — the honest path taken last, at
  speed.

## Boundaries

- Your own worktree only: `/Users/polat/agent-realm/.worktrees/gentar/claude/wt-s7-docs-truth--b1-docs-truth-all--d3-impatient`; a second checkout copy (plain copy, not a git worktree) under `/tmp/gentar-s7d3-b/` if a two-stack bind needs a real squatter you own; scratch under `/tmp/gentar-s7d3-*`.
- Arena isolation (all in `.env`, untracked, never committed):
  - primary: `COMPOSE_PROJECT_NAME=gentar-s7d3`,
    `GENTAR_CLICKHOUSE_HOST_PORT=18206`,
    `GENTAR_OTELCOL_HOST_PORT=14406`,
    `GENTAR_NAME_PREFIX=gentar-s7d3`;
  - second stack (squatter, if needed): `COMPOSE_PROJECT_NAME=gentar-s7d3b`,
    `GENTAR_CLICKHOUSE_HOST_PORT=18216`,
    `GENTAR_OTELCOL_HOST_PORT=14416`,
    `GENTAR_NAME_PREFIX=gentar-s7d3b`.
  Nothing outside ports 18200-18299 / 14400-14499, and never another
  driller's assigned pair (18201-5, 18214, 18215, 14401-5, 14414,
  14415). If your assigned port is already bound by a foreign arena,
  that is a FINDING to record — do not resolve it by touching their
  containers; shift within your own spare pair (18216/14416) and note
  the collision.
- Bench-host 10.10.10.52 is SHARED: foreign sandboxes (any run_id
  starting `gentar-` but not `gentar-s7d3`/`gentar-s7d3b`) — look,
  never touch. Delete only sandboxes carrying your two prefixes.
- Docker teardown: only your own compose projects
  (`docker compose -p gentar-s7d3 down -v`;
  `docker compose -p gentar-s7d3b down -v`). NEVER blanket
  `docker rm`/`docker down`. Throwaway containers always
  `docker rm -f -v`.
- No secret values in files or logs. Never repair, never grade, no
  verdicts.
- Deferral register (restated verbatim — never re-raise):
  real-agent runs — API-key injection + credential-tier decision;
  macOS CI leg — tart suites not gateable from the Linux runner;
  multi-bench parallel matrices; Forgejo/Gitea forge swap (designed,
  not exercised); `--kit` evaluation; Allure report emitter;
  LXC bench-host; CI sizing for matrices (local first).

## Report-worthy events (defined in advance)

Each is tied to a claim of `/s7-docs-truth` (SCENARIO.md, "What a
runbook will be able to expect") or to a boundary above. "Does not
fully reach the ideal" is not report-worthy; confusion is only
report-worthy through one of these doors.

- The bind error, read at your speed, deviating from the README's
  documented shape or failing to orient: text names something other
  than endpoint+port, or the documented port-number grep does not
  find the drift when followed verbatim — claim: "README's
  scoping-rule paragraph contains no claim a live two-stack drill can
  falsify: env-file scope, reconciliation scope, and error text all
  match observed behavior."
- The rushed recovery behaving differently than the busy-host note
  predicts: plain `up -d` after squatter removal leaving the publish
  PRESENT (docs say absent), or the publish absent but the quickstart
  still green, or `--force-recreate` failing to restore — claim: "The
  busy-host section names the silent-loss case for explicitly-set
  knobs and the `--force-recreate` recovery."
- A silent revert/recreate in the drift loop the scoping rule
  predicts wrongly (run vs exec reconciliation split not matching
  observation) — claim: same scoping-rule claim.
- The quickstart failing on defaults in your worktree after all your
  mess is unwound — claim: "No code behavior changes beyond the
  message string: all s5 blessed behavior unchanged (16 suites load,
  quickstart green on defaults)."
- A prefix refusal message that does not state the leading-letter
  rule, or disagrees with README/`.env.example` on a boundary shape —
  claim: "`GENTAR_NAME_PREFIX=1gentar` refuses with a message that
  states the leading-letter rule; docs and message agree with the
  validator on every boundary shape (leading digit, double dash,
  underscore, 24/25 chars)."
- Anything your run leaves outside `/tmp/gentar-s7d3-*`, your
  worktree, your compose projects, or your own-prefixed bench-host
  sandboxes — boundary.

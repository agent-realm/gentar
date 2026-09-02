---
node: /s7-docs-truth
status: running
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [compose-arena, bench-host-142, telemetry-spans]
hints: [bench-host/sbx-lifecycle, ci/forge-agnostic-tiers]
steered-from: "/s5-arena-coexist @ f976be1"
---

# s7 — docs truth: the coexistence text says what actually happens

Steered scenario off `/s5-arena-coexist @ f976be1` (blessed
b1-coexist-all). Its drills — d1-neighbor (PASS, zero findings),
d2-tweaker, d3-impatient — confirmed the CODE holds (concurrent arenas
fully separated, attribution held, quickstart green on the new
defaults beside the native 8123 server) and found the next layer:
the coexistence TEXT I wrote in s5 has factual errors and gaps. The
pilot's steer (2026-09-02, "Fix via s7") applies them as this
scenario's opening commits. Docs-first scenario: one message string
changes in code (the prefix refusal); everything else is README,
.env.example, and the refusal text telling the same truth.

## Steers (pilot's decision, verbatim record)

Pilot chose "Fix via s7 (Recommended)" from the menu.

Findings driven in, with the drill + finding name of record:

1. **env-file-identity-split** (d2) — README claimed `--env-file`
   drives "port *interpolation* only"; it drives the project name too.
   A live drill through exactly this seam produced a sandbox stamped
   arena A's prefix writing into arena B's ClickHouse — one variable,
   two values, no error.
2. **inert-publish-after-bind-fail-recovery** (d2) — after a bind
   failure, removing the squatter and running plain `up -d` can leave
   the container Up/healthy with the publish silently ABSENT
   (`docker port` empty); only `--force-recreate` restores it. Beyond
   the docs.
3. **bind-error-text-names-project** (d2) — README said the bind error
   names "neither project nor env file"; it names the endpoint
   (`plato-x-clickhouse-1`), so the project IS legible — the env file
   and knob are what it omits.
4. **run-subcommand-recreates-telemetry** (d2) — any compose
   invocation reconciles drifted config, `run` and `exec` included,
   not just `up`.
5. **prefix-docs-vs-validator** (d2) — docs + refusal message omitted
   the leading-letter rule and digits-allowed (`1gentar` refused while
   every stated sub-rule was satisfied; `gentar-1a` legal but
   undocumented).
6. **silent-shadow-on-taken-port** (d3) — pointing a port knob at an
   occupied port loses silently on OrbStack, exactly like the default
   collision s5 moved away from; the docs stopped one sentence short
   of saying so.
7. **bind-error-names-neither-knob** (d3) — the path from the daemon's
   "port is already allocated" to the `GENTAR_*_HOST_PORT` knob is
   grep-only; docs never hand you the grep.

## Mechanism

- **README busy-host section** gains the two field notes: verify a
  knob-targeted port with `curl /ping` before relying on the publish;
  after a bind failure, recover with `--force-recreate` (plain `up -d`
  can leave the publish absent).
- **Scoping rule rewritten to the truth**: `--env-file` drives
  interpolation AND the project name (the cross-contamination seam
  described concretely); any compose invocation reconciles; the bind
  error names endpoint+port but not file/knob — grep the port number
  to find the drift.
- **Prefix shape stated completely** everywhere it appears (README,
  .env.example, refusal message): starts with a letter; lowercase
  letters, digits, single dashes; ≤24 chars — with legal/illegal
  examples.
- The single code change is the refusal MESSAGE joining the docs in
  telling the whole rule.

## What a runbook will be able to expect

- README's scoping-rule paragraph contains no claim a live two-stack
  drill can falsify: env-file scope, reconciliation scope, and error
  text all match observed behavior.
- The busy-host section names the silent-loss case for explicitly-set
  knobs and the `--force-recreate` recovery.
- `GENTAR_NAME_PREFIX=1gentar` refuses with a message that states the
  leading-letter rule; docs and message agree with the validator on
  every boundary shape (leading digit, double dash, underscore, 24/25
  chars).
- No code behavior changes beyond the message string: all s5 blessed
  behavior unchanged (16 suites load, quickstart green on defaults).

## Deliberately left out

No runtime detection of the silent-shadow class — it lives in the
Docker host's publish semantics, invisible from inside the compose
network (s5's recorded decision stands; the docs now carry the
curl-verify mitigation). Deferred-ideal topics stay parked (deferral
register). Delights recorded, unactioned.

---
node: /s5-arena-coexist
status: approved
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [compose-arena, bench-host-142, telemetry-spans]
hints: [bench-host/sbx-lifecycle, ci/forge-agnostic-tiers]
steered-from: "/s2-arena-portability @ 3849dcc"
---

# s5 — arena coexistence: two arenas, no shadows

Steered scenario off `/s2-arena-portability @ 3849dcc` (blessed
b1-second-host-all). Its drills — d1-impatient, d2-tweaker, d3-neighbor —
found the second-Docker-host claim holds but coexistence itself has
holes; the pilot's steer (2026-09-02, answer: "fix") applies them as
this scenario's opening commits.

## Steers (pilot's decision, verbatim record)

Pilot chose "fix" from the menu:
- fix all real findings in both scenarios (this one = the arena
  coexistence holes)
- delights recorded, not actioned

Findings driven in, with the drill + reproduction of record:

1. **default-collision, silent** — with a native clickhouse-server
   listening on 127.0.0.1:8123, `docker compose run` raised NO error,
   reported clickhouse Healthy, exit 0, and `docker ps` even listed the
   publish — but the host port answered the FOREIGN server (auth
   rejected) while compose-internal truth had 6 spans. On OrbStack the
   busy-host collision is silent: quickstart immune (SQL via compose
   exec), every host-side consumer reads the wrong server (d1).
2. **isolation-leak** — two checkouts that end up with the same
   COMPOSE_PROJECT_NAME are ONE merged arena: the second silently
   attaches to the first's containers; spans land in the first's
   ClickHouse volume while reports land per-checkout, so attribution
   looks separate when it is not (d2).
3. **attribution-confusion** — on a shared bench-host, `sbx ls` shows
   two `gentar-<ts>-<hex>` sandboxes with no field carrying arena,
   coordinator, or Docker-host identity; the report's Reproduce line is
   identical in every arena. Ownership is decidable only with
   out-of-band knowledge (your own report's run_id) (d3).
4. **name-collision-risk / LAN exposure** — otelcol's default published
   `0.0.0.0:4318` on all interfaces: two default-configured arenas
   cannot both start, and the publish can shadow an unrelated host OTLP
   receiver — plus the collector is exposed to the LAN for no benefit,
   since benches never POST to it (drop-file relay via the coordinator)
   (d3).
5. **bend-crash + half-applied-override** — port knobs are `.env`-scoped
   while COMPOSE_PROJECT_NAME is invocation-scoped: a compose call that
   omits the shell exports silently reverts to the file's ports,
   recreates the running stack, and dies on a bind error naming neither
   project nor file. `--env-file` is no escape: interpolation reads it,
   the coordinator container still reads the literal `.env` (d2).

## Mechanism

Same arena, coexistence made a first-class property:

- **Defaults off the canonical ports** — host publishes default to
  `18123` (ClickHouse) and `14318` (otelcol), loopback-only. The
  occupied ports on a real machine are 8123/4318 (native installs,
  other receivers); a gentar-specific default kills the silent-shadow
  class instead of documenting it. The knob stays for the residual
  two-arenas case.
- **otelcol loopback-only** — the publish is manual debugging from the
  host; benches relay OTLP through the coordinator over the compose
  network, so `127.0.0.1` closes the LAN exposure and the receiver
  shadow with nothing lost.
- **Arena identity on the bench-host** — `GENTAR_NAME_PREFIX`
  (existing knob, now documented + validated) prefixes every run_id:
  sandbox names, workspace dirs, span run_ids, and report filenames
  all carry it. Off-shape values (uppercase, double dash, >24 chars,
  spaces) refuse at startup with exit 2, never a traceback, never a
  weird filename mid-run.
- **Arena identity on the Docker host** — `.env.example` and README
  name COMPOSE_PROJECT_NAME as THE identity knob and state the scoping
  rule: one arena = one `.env`, everything in it, nothing on the shell.
  The merge failure mode and the `--env-file` split-brain are written
  down where the person standing up a second arena will read them.

## What a runbook will be able to expect

- A fresh `cp .env.example .env` + quickstart run, beside a native
  clickhouse-server on 8123: exit 0, and the host port 18123 answers
  THE ARENA (spans reachable host-side), 8123 still answers the native
  server.
- `docker compose config` shows both publishes bound to 127.0.0.1;
  `GENTAR_*_HOST_PORT` still overrides either.
- `GENTAR_NAME_PREFIX=Bad Value` (or `gentar--x`, or 25 chars) refuses
  with exit 2 and a message naming the shape rule; a valid prefix
  shows up in the run_id, the sandbox name on the bench-host, and the
  report filename.
- Two arenas with distinct COMPOSE_PROJECT_NAME + distinct ports in
  their own `.env` files coexist on one Docker host and one
  bench-host; spans stay separated; `sbx ls` distinguishes their
  sandboxes by prefix.
- The dashboard's host-side fallback reaches the arena on 18123.

## Deliberately left out

Deferred-ideal topics stay parked (deferral register). The delight
(five-minute quickstart green first try, d1) is recorded, unactioned.
No compose `name:` pin — a fixed top-level name would COLLAPSE all
checkouts onto one project, the opposite of the steer. No runtime
collision detection (bind-failure preflight): the silent case lives in
the Docker host's publish semantics, not in anything the coordinator
can see from inside the network; moving the defaults removes the class
the coordinator could not have detected.

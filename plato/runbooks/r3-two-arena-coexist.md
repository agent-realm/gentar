---
node: /s5-arena-coexist/r3-two-arena-coexist
scenario: /s5-arena-coexist
status: frozen
touches:
  - "arena A: this worktree (.env with COMPOSE_PROJECT_NAME=plato-s5-r3a, GENTAR_CLICKHOUSE_HOST_PORT=18151, GENTAR_OTELCOL_HOST_PORT=14351, GENTAR_NAME_PREFIX=gentar-s5-alpha)"
  - "arena B: a second checkout at <worktree>-b/ extracted via `git archive HEAD | tar -x` (.env with COMPOSE_PROJECT_NAME=plato-s5-r3b, GENTAR_CLICKHOUSE_HOST_PORT=18152, GENTAR_OTELCOL_HOST_PORT=14352, GENTAR_NAME_PREFIX=gentar-s5-beta)"
  - docker compose projects plato-s5-r3a and plato-s5-r3b (each with its own ClickHouse volume; both on this one Docker host simultaneously)
  - bench-host 10.10.10.52 via ssh user polat, key $HOME/.ssh/id_ed25519 (two sbx sandboxes kept alive via GENTAR_KEEP_BENCH=1, removed by EXACT run_id in teardown)
  - out/report-gentar-s5-(alpha|beta)-*.md run reports in each arena dir (gitignored)
expect:
  - both arenas' `docker compose run --rm -e GENTAR_KEEP_BENCH=1 coordinator run smoke` exit 0, arena B's run executing while arena A's stack is up
  - containers of BOTH projects run simultaneously on this Docker host (docker ps lists plato-s5-r3a-* and plato-s5-r3b-* names at the same time; two distinct clickhouse volumes exist)
  - arena A's ClickHouse holds ONLY gentar-s5-alpha-* run_ids (its own present, zero gentar-s5-beta-*); arena B's holds ONLY gentar-s5-beta-* (its own present, zero gentar-s5-alpha-*) — spans stay separated per arena
  - "`sbx ls` on the shared bench-host lists BOTH sandboxes, distinguishable by prefix (gentar-s5-alpha-* and gentar-s5-beta-*), with distinct run_ids"
stop-conditions:
  - docker context is not orbstack
  - ssh -o BatchMode=yes polat@10.10.10.52 true fails
  - any of host ports 18151, 18152, 14351, 14352 already listening
  - either arena's `docker compose config` does not resolve its publishes to its own ports loopback-only (wiring fault — record the config verbatim)
  - either `docker compose build coordinator` fails
exclusions: "default-port behavior and prefix validation mechanics (r1/r2 instruments — r3 only uses the prefix as an identity marker), the five other gate suites, tart tier, the otel_traces join, dashboard rendering, cross-arena sandbox interference on the bench-host beyond distinct names"
---

# r3 — two arenas coexist: one Docker host, one bench-host, no merged identity

Proves the scenario's expect 4: two arenas — distinct
COMPOSE_PROJECT_NAME and distinct host ports, each with its OWN .env
in its own checkout — run simultaneously on one Docker host and one
bench-host; spans stay separated (each arena's ClickHouse volume holds
only its own prefixed run_ids), and `sbx ls` distinguishes their
sandboxes by prefix. This is the direct check for the d2
isolation-leak and d3 attribution-confusion findings: same project
name would silently merge the arenas, and un-prefixed run_ids would be
unattributable.

## Environment (declared, fixed)

- Docker host: THIS Mac, OrbStack — docker context `orbstack`,
  Engine 29.4.0. All `docker` commands run on this Mac.
- Bench host: 10.10.10.52 (VM 142), ssh user `polat`, key
  `$HOME/.ssh/id_ed25519`, `sbx` installed. SHARED with sibling
  agents: foreign `gentar-*` sandboxes may exist at any moment —
  record them verbatim, never remove or exec into them.
- You touch ONLY the compose projects `plato-s5-r3a` and
  `plato-s5-r3b`. Never stop or remove any container, volume, or
  network outside those two project names; never touch a compose
  project named plato-s4-* or plato-s5-arm (sibling/other runbook
  arenas).
- Reserved host ports: arena A 18151/14351, arena B 18152/14352.
- Identity markers: arena A prefix `gentar-s5-alpha`, arena B prefix
  `gentar-s5-beta`.
- Arena A directory: this worktree
  (`/Users/polat/agent-realm/.worktrees/gentar/claude/plato-s5-r3-two-arena`).
  Arena B directory: `<arena A path>-b` — a plain extraction of the
  tracked tree (NOT a git worktree), removed in teardown.

## Steps (follow literally; never repair mid-run)

`cd` absolute in every shell call. `A` below means the arena A
directory path, `B` means `<A>-b`.

1. Record starting state:
   `docker context show` — expect `orbstack`, else stop-incomplete.
2. `ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 true` —
   expect exit 0, else stop-incomplete.
3. Verify all four ports free:
   ```
   for p in 18151 18152 14351 14352; do lsof -nP -iTCP:$p -sTCP:LISTEN; done
   ```
   Expect no output at all, else stop-incomplete (record any listener
   verbatim).
4. Arena A env (gitignored file):
   ```
   cd <A> && cp .env.example .env
   printf '\n# runbook r3 arena A\nCOMPOSE_PROJECT_NAME=plato-s5-r3a\nGENTAR_CLICKHOUSE_HOST_PORT=18151\nGENTAR_OTELCOL_HOST_PORT=14351\nGENTAR_NAME_PREFIX=gentar-s5-alpha\n' >> .env
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   ```
5. Arena B checkout + env (tracked files only; .env written by hand —
   one arena, one .env, nothing shared):
   ```
   mkdir -p <B>
   cd <A> && git archive HEAD | tar -x -C <B>
   cp <A>/.env.example <B>/.env
   printf '\n# runbook r3 arena B\nCOMPOSE_PROJECT_NAME=plato-s5-r3b\nGENTAR_CLICKHOUSE_HOST_PORT=18152\nGENTAR_OTELCOL_HOST_PORT=14352\nGENTAR_NAME_PREFIX=gentar-s5-beta\n' >> <B>/.env
   ```
6. Port wiring verification, both arenas (before any build/run):
   ```
   cd <A> && docker compose config | grep -nE '18151|14351|18152|14352|host_ip|published|^name:'
   cd <B> && docker compose config | grep -nE '18151|14351|18152|14352|host_ip|published|^name:'
   ```
   Expect: A's config resolves `published: "18151"` and `"14351"` and
   its top-level `name:` is plato-s5-r3a; B's resolves 18152/14352 and
   names plato-s5-r3b; all four `host_ip: 127.0.0.1`. A same-name
   resolution or a crossed port is a wiring fault — stop-incomplete,
   record both configs verbatim.
7. Build both coordinators (each in its own dir; separate images per
   project):
   ```
   cd <A> && docker compose build coordinator
   cd <B> && docker compose build coordinator
   ```
   Either failing = stop-incomplete.
8. Arena A runs first (expect, first bullet). Sandbox kept for step 11:
   ```
   cd <A>
   env -u GENTAR_NAME_PREFIX docker compose run --rm -e GENTAR_KEEP_BENCH=1 coordinator run smoke
   ```
   Expect exit 0; record the full output. Then capture its run id:
   ```
   REPORT_A=$(ls -t out/report-gentar-s5-alpha-*.md | head -1)
   RUN_ID_A=$(basename "$REPORT_A" | sed -e 's/^report-//' -e 's/\.md$//')
   echo "run_id_a=$RUN_ID_A"
   ```
   Expect `gentar-s5-alpha-<YYYYMMDD>-<HHMMSS>-<hex6>`. Smoke nonzero =
   **FAIL** (record output; continue teardown only).
9. Arena B runs while A's stack is up (expect, first bullet; this is
   the coexistence moment on both hosts):
   ```
   cd <B>
   env -u GENTAR_NAME_PREFIX docker compose run --rm -e GENTAR_KEEP_BENCH=1 coordinator run smoke
   ```
   Expect exit 0; record the full output; capture RUN_ID_B the same
   way from `out/report-gentar-s5-beta-*.md`. Smoke nonzero = **FAIL**.
10. Both arenas alive on the one Docker host (expect, second bullet):
    ```
    docker ps --format '{{.Names}}' | grep -E '^plato-s5-r3[ab]-' | sort
    docker volume ls --format '{{.Name}}' | grep -E '^plato-s5-r3[ab]_' | sort
    ```
    Expect: container names from BOTH projects listed simultaneously
    (at least one plato-s5-r3a-* and one plato-s5-r3b-* line, record
    all), and two distinct clickhouse volumes
    (plato-s5-r3a_clickhouse, plato-s5-r3b_clickhouse). Record both
    listings verbatim.
11. Spans separated (expect, third bullet) — one query per arena:
    ```
    cd <A> && docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
      -q "SELECT countIf(startsWith(run_id,'gentar-s5-alpha-')) AS own, countIf(startsWith(run_id,'gentar-s5-beta-')) AS foreign, countIf(run_id='<RUN_ID_A>') AS this_run FROM (SELECT DISTINCT run_id FROM gentar.spans)"
    cd <B> && docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
      -q "SELECT countIf(startsWith(run_id,'gentar-s5-beta-')) AS own, countIf(startsWith(run_id,'gentar-s5-alpha-')) AS foreign, countIf(run_id='<RUN_ID_B>') AS this_run FROM (SELECT DISTINCT run_id FROM gentar.spans)"
    ```
    Substitute the captured run ids literally. Expect A: own >= 1,
    foreign = 0, this_run = 1. Expect B: own >= 1, foreign = 0,
    this_run = 1. Any foreign > 0 (spans leaked across arenas) or
    this_run = 0 = **FAIL** — record both rows verbatim.
12. Bench-host attribution (expect, fourth bullet):
    ```
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx ls'
    ```
    Record the full listing verbatim. Expect: sandboxes named EXACTLY
    RUN_ID_A and RUN_ID_B both listed, distinguishable by prefix.
    Foreign `gentar-*` sandboxes (sibling agents) may be listed —
    record verbatim, never remove; their presence is not a finding.
    Either run_id missing = **FAIL**.
13. Teardown — EVERY exit path, including failure and stop-incomplete.
    Skip the exact-run_id removals only for run ids never captured;
    then instead record `sbx ls | grep -E 'gentar-s5-(alpha|beta)-'`
    verbatim and remove nothing you cannot name exactly:
    ```
    cd <A> && docker compose ps && docker compose down -v --remove-orphans
    cd <B> && docker compose ps && docker compose down -v --remove-orphans
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx rm --force <RUN_ID_A>; sbx rm --force <RUN_ID_B>; rm -rf /tmp/gentar-workspaces/<RUN_ID_A> /tmp/gentar-workspaces/<RUN_ID_B>; sbx ls | grep -E "gentar-s5-(alpha|beta)-" || echo own-sandboxes-clean'
    rm -rf <B>
    ```
    Substitute the captured run ids literally (exact-run_id scope —
    never a wildcard, never a foreign sandbox). Both `docker compose
    ps` listings go in the run record. Record teardown as done.

## Verdict

- PASS: steps 8 and 9 (both exit 0, correct run_id shapes), 10 (both
  projects' containers + two volumes), 11 (own >= 1 / foreign = 0 /
  this_run = 1 in BOTH arenas), and 12 (both run_ids listed) hold.
- PASS WITH FINDINGS: the expects hold AND something unexpected was
  observed — record it as a named finding.
- FAIL: either smoke nonzero; either arena's containers absent while
  both should be up; any foreign > 0 or this_run = 0 in step 11;
  either run_id missing from `sbx ls`.
- incomplete: any stop-condition hit, timeout, or crash — never FAIL.

## Run record

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = run end,
local time) with the front-matter grammar from the engine's record
procedure: `runbook: /s5-arena-coexist/r3-two-arena-coexist @ <this
branch's runbook commit hash>`, stamp, environment, verdict,
incomplete flag, findings, teardown. Include: the port check (3), both
config greps (6), both smoke outputs and run ids (8, 9), the
docker ps + volume listings (10), both separation rows (11), the full
`sbx ls` listing with foreign sandboxes verbatim (12), and both
teardown `docker compose ps` listings (13).

Two commits on this branch, then push:
1. flip this file's front-matter `status: draft` → `status: frozen`,
   commit `runbook: /s5-arena-coexist/r3-two-arena-coexist frozen
   (first run recorded)`;
2. add the run record, commit `run: /s5/r3 <verdict>`.
Push: `git push origin plato/s5-arena-coexist--r3-two-arena-coexist`.

---
node: /s5-arena-coexist/r2-prefix-identity
scenario: /s5-arena-coexist
status: draft
touches:
  - this worktree's .env (created fresh, then appended: COMPOSE_PROJECT_NAME=plato-s5-arm, GENTAR_CLICKHOUSE_HOST_PORT=18150, GENTAR_OTELCOL_HOST_PORT=14350, GENTAR_NAME_PREFIX=gentar-s5-id)
  - docker compose project plato-s5-arm (host publishes 127.0.0.1:18150 / 127.0.0.1:14350, own ClickHouse volume)
  - GENTAR_NAME_PREFIX injected via `docker compose run -e` for the three invalid-value checks
  - bench-host 10.10.10.52 via ssh user polat, key $HOME/.ssh/id_ed25519 (one sbx sandbox kept alive via GENTAR_KEEP_BENCH=1, removed by EXACT run_id in teardown)
  - out/report-gentar-s5-id-*.md run report (gitignored)
expect:
  - each invalid GENTAR_NAME_PREFIX — 'Bad Value', 'gentar--x', and a 25-char value — makes `docker compose run --rm -e GENTAR_NAME_PREFIX=<value> coordinator ls` exit 2, printing a message that names the shape rule (contains "must be lowercase-with-dashes") and the offending value, with NO Python traceback in the output
  - with GENTAR_NAME_PREFIX=gentar-s5-id in .env, `docker compose run --rm -e GENTAR_KEEP_BENCH=1 coordinator run smoke` exits 0
  - the run_id is gentar-s5-id-<YYYYMMDD>-<HHMMSS>-<hex6> and the report file out/report-<run_id>.md exists
  - every run_id in this stack's own ClickHouse starts with gentar-s5-id- and includes the captured one
  - "`sbx ls` on the bench-host lists a sandbox named EXACTLY the captured run_id (kept alive via GENTAR_KEEP_BENCH=1), distinguishable by prefix from any foreign gentar-* sandbox"
stop-conditions:
  - docker context is not orbstack
  - ssh -o BatchMode=yes polat@10.10.10.52 true fails
  - host port 18150 or 14350 already listening
  - docker compose config does not resolve the publishes to 18150/14350 loopback-only (wiring fault — record the config verbatim)
  - docker compose build coordinator fails
exclusions: "default-port behavior and dashboard fallback (r1's instrument), two-arena coexistence (r3's instrument), the five other gate suites, tart tier, the otel_traces join, workspace-dir naming beyond the one sandbox observed"
---

# r2 — GENTAR_NAME_PREFIX: off-shape refused with exit 2; valid prefix carried everywhere

Proves the scenario's expect 3: the arena's bench-host identity knob
refuses off-shape values at startup as a usage error (exit 2, message
naming the shape rule, never a traceback, never a weird filename
mid-run), and a valid value shows up in the run_id, the sandbox name
on the bench-host, and the report filename. This is the fix for the
d3 drill's attribution-confusion finding: identity must be decidable
from `sbx ls` alone.

## Environment (declared, fixed)

- Docker host: THIS Mac, OrbStack — docker context `orbstack`,
  Engine 29.4.0. All `docker` commands run on this Mac.
- Bench host: 10.10.10.52 (VM 142), ssh user `polat`, key
  `$HOME/.ssh/id_ed25519`, `sbx` installed. SHARED with sibling
  agents: foreign `gentar-*` sandboxes may exist at any moment —
  record them verbatim, never remove or exec into them.
- You touch ONLY the compose project `plato-s5-arm`. Never stop or
  remove any container, volume, or network outside that project name;
  never touch a compose project named plato-s4-* (a sibling agent's).
- Reserved host ports for this runbook: 18150 (ClickHouse), 14350
  (otelcol).
- Prefix under test: `gentar-s5-id` (valid: lowercase-with-dashes,
  11 chars).

## Steps (follow literally; never repair mid-run)

Work from this worktree's root:
`/Users/polat/agent-realm/.worktrees/gentar/claude/plato-s5-r2-prefix`.
`cd` absolute in every shell call.

1. Record starting state:
   `docker context show` — expect `orbstack`, else stop-incomplete.
2. `ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 true` —
   expect exit 0, else stop-incomplete.
3. Verify ports free:
   ```
   lsof -nP -iTCP:18150 -sTCP:LISTEN
   lsof -nP -iTCP:14350 -sTCP:LISTEN
   ```
   Expect no output from both, else stop-incomplete.
4. Create the env file (gitignored) and set the arena's identity:
   ```
   cp .env.example .env
   printf '\n# runbook r2 arena identity\nCOMPOSE_PROJECT_NAME=plato-s5-arm\nGENTAR_CLICKHOUSE_HOST_PORT=18150\nGENTAR_OTELCOL_HOST_PORT=14350\nGENTAR_NAME_PREFIX=gentar-s5-id\n' >> .env
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   ```
5. Port wiring verification (before any build/run):
   ```
   docker compose config | grep -nE '18150|14350|host_ip|published'
   ```
   Expect `published: "18150"` and `published: "14350"`, both with
   `host_ip: 127.0.0.1`. Anything else is a wiring fault —
   stop-incomplete, record the config output verbatim.
6. `docker compose build coordinator` — expect exit 0, else
   stop-incomplete.
7. Invalid prefix checks (expect, first bullet). For EACH of the three
   values below, run the command, record the FULL output and the exit
   code:
   ```
   docker compose run --rm -e GENTAR_NAME_PREFIX='Bad Value' coordinator ls
   docker compose run --rm -e GENTAR_NAME_PREFIX='gentar--x' coordinator ls
   docker compose run --rm -e GENTAR_NAME_PREFIX='aaaaaaaaaaaaaaaaaaaaaaaaa' coordinator ls
   ```
   (the third value is exactly 25 `a` characters). Expected for EACH:
   exit code 2; output contains `must be lowercase-with-dashes` AND
   the offending value; NO `Traceback` in the output. Exit 0, exit 1,
   a traceback, or an exit 2 without the shape-rule message = **FAIL**
   for that value (record which). The first of these calls also boots
   the stack's clickhouse/otelco dependencies — that is expected, not
   a repair.
8. Valid prefix run (expect, remaining bullets). The prefix rides the
   .env (env_file) into the container; GENTAR_KEEP_BENCH=1 keeps the
   sandbox alive for step 11:
   ```
   env -u GENTAR_NAME_PREFIX docker compose run --rm -e GENTAR_KEEP_BENCH=1 coordinator run smoke
   ```
   Expect exit 0; record the full output. Nonzero = **FAIL**.
9. Capture the run id and check the report filename:
   ```
   REPORT=$(ls -t out/report-gentar-s5-id-*.md | head -1)
   RUN_ID=$(basename "$REPORT" | sed -e 's/^report-//' -e 's/\.md$//')
   echo "report=$REPORT run_id=$RUN_ID"
   ```
   Expect `run_id=gentar-s5-id-<YYYYMMDD>-<HHMMSS>-<hex6>` and the
   report file to exist.
10. Spans in THIS stack's ClickHouse carry the prefix:
    ```
    docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
      -q "SELECT DISTINCT run_id FROM gentar.spans ORDER BY run_id"
    ```
    Expect: the captured RUN_ID present, and EVERY listed run_id
    starts with `gentar-s5-id-` (fresh volume; anything else = the
    prefix is not being carried = **FAIL**).
11. Sandbox on the bench-host carries the prefix (expect, last
    bullet):
    ```
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx ls'
    ```
    Record the full listing verbatim. Expect: a sandbox named EXACTLY
    the captured RUN_ID is listed. Foreign `gentar-*` sandboxes
    (sibling agents, default prefix) may also be listed — they are not
    yours; record them, never remove them; their presence is not a
    finding. A missing RUN_ID = **FAIL**.
12. Teardown — EVERY exit path, including failure and stop-incomplete
    (skip the two exact-run_id removals only if no RUN_ID was
    captured; then instead record `sbx ls | grep gentar-s5-id-`
    verbatim and remove nothing you cannot name exactly):
    ```
    docker compose ps
    docker compose down -v --remove-orphans
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx rm --force <RUN_ID>; rm -rf /tmp/gentar-workspaces/<RUN_ID>; sbx ls | grep -E "gentar-s5-id-|gentar-" || echo bench-host-clean'
    ```
    Substitute the captured RUN_ID literally (exact-run_id scope —
    never a wildcard, never another sandbox). `docker compose ps`
    output goes in the run record. Record teardown as done.

## Verdict

- PASS: steps 7 (all three: exit 2 + shape-rule message, no
  traceback), 8, 9, 10, and 11 all hold.
- PASS WITH FINDINGS: the expects hold AND something unexpected was
  observed — record it as a named finding.
- FAIL: any invalid value not refused per spec; smoke nonzero; run_id
  shape wrong; any DB run_id without the prefix; sandbox not listed by
  exact name.
- incomplete: any stop-condition hit, timeout, or crash — never FAIL.

## Run record

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = run end,
local time) with the front-matter grammar from the engine's record
procedure: `runbook: /s5-arena-coexist/r2-prefix-identity @ <this
branch's runbook commit hash>`, stamp, environment, verdict,
incomplete flag, findings, teardown. Include: the three invalid-value
outputs with exit codes (7), the smoke output (8), the captured run_id
(9), the DISTINCT run_id listing (10), the full `sbx ls` listing with
the foreign sandboxes verbatim (11), and the teardown `docker compose
ps` listing (12).

Two commits on this branch, then push:
1. flip this file's front-matter `status: draft` → `status: frozen`,
   commit `runbook: /s5-arena-coexist/r2-prefix-identity frozen (first
   run recorded)`;
2. add the run record, commit `run: /s5/r2 <verdict>`.
Push: `git push origin plato/s5-arena-coexist--r2-prefix-identity`.

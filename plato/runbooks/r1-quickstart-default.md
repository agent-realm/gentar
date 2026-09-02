---
node: /s5-arena-coexist/r1-quickstart-default
scenario: /s5-arena-coexist
status: frozen
touches:
  - this worktree's .env (created fresh via `cp .env.example .env`, gitignored, never edited — the defaults are the thing under test)
  - docker compose project derived from this worktree's directory basename (no COMPOSE_PROJECT_NAME set anywhere — the fresh-quickstart condition)
  - host publishes on the loopback defaults 127.0.0.1:18123 (ClickHouse) and 127.0.0.1:14318 (otelcol)
  - the FOREIGN native clickhouse-server already listening on 127.0.0.1:8123 — read-only: /ping and one auth-failing probe; never reconfigured, stopped, or restarted
  - bench-host 10.10.10.52 via ssh user polat, key $HOME/.ssh/id_ed25519 (sbx; the smoke sandbox is removed by the coordinator itself)
  - out/report-gentar-*.md run report and dashboard/out/r1-host-fallback.html (gitignored artifacts)
  - python3 on this Mac (stdlib-only dashboard render)
expect:
  - "`docker compose config` resolves BOTH publishes loopback-only on the defaults — clickhouse host_ip 127.0.0.1 published 18123 (target 8123), otelcol host_ip 127.0.0.1 published 14318 (target 4318); no publish on host port 8123 or 4318, no 0.0.0.0 host_ip anywhere"
  - "shell-env GENTAR_CLICKHOUSE_HOST_PORT=18999 and GENTAR_OTELCOL_HOST_PORT=14499 change the resolved publishes to 18999 / 14499 (`docker compose config` only — nothing is started on them)"
  - quickstart `docker compose run --rm coordinator run smoke` exits 0
  - "the host port 18123 answers THE ARENA: an HTTP query to http://127.0.0.1:18123 with gentar/gentar returns the run's span count (>= 1)"
  - "8123 still answers the native FOREIGN server: /ping returns `Ok.`, and the identical gentar/gentar query that succeeds on 18123 FAILS authentication on 8123"
  - "dashboard host-side fallback: `python3 dashboard/generate.py` with GENTAR_CLICKHOUSE_URL unset renders an HTML that contains the run_id (default endpoint http://localhost:18123)"
stop-conditions:
  - docker context is not orbstack
  - ssh -o BatchMode=yes polat@10.10.10.52 true fails
  - host port 18123 or 14318 already listening (defaults not actually free on this machine)
  - 127.0.0.1:8123 NOT listening (the foreign native server — this runbook's premise — is absent)
  - docker compose build coordinator fails
  - python3 is absent on this Mac (dashboard render impossible)
exclusions: "GENTAR_NAME_PREFIX validation and two-arena coexistence (r2/r3 instruments), subject suites, tart tier, the other five gate suites, OTLP relay content, otelcol function on 14318 beyond a successful loopback bind, anything reached over non-loopback interfaces"
---

# r1 — fresh quickstart on defaults, beside the native 8123 server

Proves the scenario's expects 1, 2 and 5: a fresh `cp .env.example .env`
quickstart on a machine that ALREADY runs a native clickhouse-server on
127.0.0.1:8123 exits 0, the default host port 18123 answers THE ARENA
(spans reachable host-side) while 8123 keeps answering the native
server; the resolved config is loopback-only on 18123/14318 with both
knobs still overriding; and the dashboard's host-side fallback reaches
the arena on 18123 with no env set.

This is the direct inversion of the d1 drill's silent-shadow finding:
with the old 8123 default, the publish lost the race to the native
server without any error and every host-side consumer read the WRONG
server. Here the arena must be reachable on its own default port with
the native server still alive and unmolested beside it.

## Environment (declared, fixed)

- Docker host: THIS Mac, OrbStack — docker context `orbstack`,
  Engine 29.4.0. All `docker` commands run on this Mac.
- The native clickhouse-server on 127.0.0.1:8123 (foreign, PID not
  yours) is PART OF THE TEST CONDITION. Read-only: `/ping` and one
  authenticated probe. Never stop, restart, or reconfigure it.
- Bench host: 10.10.10.52 (VM 142), ssh user `polat`, key
  `$HOME/.ssh/id_ed25519`, `sbx` installed.
- This Mac runs other, unrelated services and OTHER agents' compose
  projects concurrently. You touch ONLY the compose project derived
  from this worktree's basename. Never stop or remove any container,
  volume, or network outside that project name; never touch a compose
  project named plato-s4-* (a sibling agent's).
- This runbook uses the DEFAULT ports 18123/14318 and sets NO
  COMPOSE_PROJECT_NAME — that is the fresh-quickstart condition under
  test, not an omission.

## Steps (follow literally; never repair mid-run)

Work from this worktree's root:
`/Users/polat/agent-realm/.worktrees/gentar/claude/plato-s5-r1-default`.
`cd` absolute in every shell call.

1. Record starting state:
   `docker context show` — expect `orbstack`, else stop-incomplete.
2. `ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 true` —
   expect exit 0, else stop-incomplete.
3. Port premise:
   ```
   lsof -nP -iTCP:18123 -sTCP:LISTEN
   lsof -nP -iTCP:14318 -sTCP:LISTEN
   lsof -nP -iTCP:8123 -sTCP:LISTEN
   ```
   Expect: no output from the first two (record that), and the third
   LISTS the foreign native server (record the line verbatim). If 8123
   is not listening → stop-incomplete (premise absent). If 18123 or
   14318 is taken → stop-incomplete.
4. Fresh quickstart env — copy, do not edit:
   ```
   cp .env.example .env
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   ```
   Do NOT append port overrides. Do NOT set COMPOSE_PROJECT_NAME.
5. Resolved defaults (expect 2, first half):
   ```
   docker compose config > /tmp/r1-config-defaults.txt
   grep -nE 'name:|host_ip|published|target' /tmp/r1-config-defaults.txt
   ```
   Expect, in the ports sections: clickhouse `host_ip: 127.0.0.1`,
   `target: 8123`, `published: "18123"`; otelcol `host_ip: 127.0.0.1`,
   `target: 4318`, `published: "14318"`. NO publish with host port 8123
   or 4318; NO `host_ip: 0.0.0.0` (or empty host_ip) anywhere. Record
   the resolved project `name:` too. Any violation of this expected
   resolution is a **FAIL** (the product's defaults are wrong — that is
   this scenario's mechanism), with the config excerpt as evidence.
6. Knob override, config-only (expect 2, second half):
   ```
   GENTAR_CLICKHOUSE_HOST_PORT=18999 GENTAR_OTELCOL_HOST_PORT=14499 \
     docker compose config > /tmp/r1-config-override.txt
   grep -nE '18999|14499|18123|14318|host_ip|published' /tmp/r1-config-override.txt
   ```
   Expect: `published: "18999"` and `published: "14499"` resolved
   (still `host_ip: 127.0.0.1`), and 18123/14318 now absent from the
   ports sections. Violation = **FAIL**. Nothing is started on
   18999/14499; the overrides live only in this config invocation.
7. `docker compose build coordinator` — expect exit 0, else
   stop-incomplete.
8. The quickstart run (expect 1):
   ```
   docker compose run --rm coordinator run smoke
   ```
   Expect exit code 0; record the full output (including the `report:`
   line). Nonzero = **FAIL** with the output as evidence — do not
   retry, do not fix.
9. Capture the run id (full, leading `gentar-`):
   ```
   REPORT=$(ls -t out/report-gentar-*.md | head -1)
   RUN_ID=$(basename "$REPORT" | sed -e 's/^report-//' -e 's/\.md$//')
   echo "report=$REPORT run_id=$RUN_ID"
   ```
   Expect `run_id=gentar-<YYYYMMDD>-<HHMMSS>-<hex6>` (default prefix,
   fresh quickstart).
10. THE ARENA answers on 18123 (expect 1, host-side spans):
    ```
    curl -sS --max-time 10 --user gentar:gentar \
      "http://127.0.0.1:18123/" \
      --data-binary "SELECT count() FROM gentar.spans WHERE run_id='$RUN_ID'"
    ```
    Expect: a bare integer >= 1 (record it). curl nonzero exit, an
    HTTP error body, or 0 = **FAIL** (record verbatim).
11. The native server still answers 8123 (expect 1, unshadowed) — both
    probes, record verbatim:
    ```
    curl -sS --max-time 5 "http://127.0.0.1:8123/ping"
    curl -sS --max-time 5 --user gentar:gentar \
      "http://127.0.0.1:8123/" \
      --data-binary "SELECT count() FROM gentar.spans WHERE run_id='$RUN_ID'"
    ```
    Expect: first body `Ok.` (native server alive). Second:
    AUTHENTICATION_FAILED (or any failure — anything EXCEPT returning
    the span count). If 8123 answers the arena's span count, the
    silent-shadow bug is live = **FAIL**.
12. Dashboard host-side fallback (expect 5):
    ```
    env -u GENTAR_CLICKHOUSE_URL -u GENTAR_DASHBOARD_OUT \
      python3 dashboard/generate.py --out dashboard/out/r1-host-fallback.html
    grep -c "$RUN_ID" dashboard/out/r1-host-fallback.html
    ```
    Expect: generator exits 0 (record its `dashboard: ... (N runs, ...)`
    line) and the grep count >= 1. A zero count or generator failure
    (connection refused to localhost:18123) = **FAIL**.
13. Teardown — EVERY exit path, including failure and stop-incomplete:
    ```
    docker compose ps
    docker compose down -v --remove-orphans
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx ls | grep gentar- || echo bench-host-clean'
    ```
    The `docker compose ps` listing goes in the run record (proof you
    only touched your own project). Any `gentar-*` sandbox listed on
    the bench-host may belong to a sibling agent's concurrent run —
    record verbatim, never remove it (the smoke run's own sandbox is
    removed by the coordinator). Record teardown as done.

## Verdict

- PASS: steps 5, 6, 8 (exit 0), 10 (integer >= 1), 11 (`Ok.` + auth
  failure), and 12 (count >= 1) all hold.
- PASS WITH FINDINGS: the expects hold AND something unexpected was
  observed — record it as a named finding.
- FAIL: any expected resolution in 5/6 violated; smoke nonzero; 18123
  not answering the arena's spans; 8123 answering them; dashboard
  render missing the run_id.
- incomplete: any stop-condition hit, timeout, or crash — never FAIL.

## Run record

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = run end,
local time) with the front-matter grammar from the engine's record
procedure: `runbook: /s5-arena-coexist/r1-quickstart-default @ <this
branch's runbook commit hash>`, stamp, environment, verdict,
incomplete flag, findings, teardown. Include: the step-3 lsof lines,
both config greps (5, 6), the smoke output (8), the captured run_id
(9), the 18123 span count (10), both 8123 probes verbatim (11), the
dashboard line + grep count (12), and the teardown `docker compose ps`
listing (13).

Two commits on this branch, then push:
1. flip this file's front-matter `status: draft` → `status: frozen`,
   commit `runbook: /s5-arena-coexist/r1-quickstart-default frozen
   (first run recorded)`;
2. add the run record, commit `run: /s5/r1 <verdict>`.
Push: `git push origin plato/s5-arena-coexist--r1-quickstart-default`.

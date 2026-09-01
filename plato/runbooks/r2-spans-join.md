---
node: /s2-arena-portability/r2-spans-join
scenario: /s2-arena-portability
status: orphan
steer: "Pilot steer (2026-09-02, after RUN-2026-09-02-02_37 FAIL): unambiguous run-id capture — no prefix stripping; bounded export-settle wait before the join SQL; and a `docker compose config` port-verification step covering the 4318 anomaly. Runbook goes orphan, fresh runner re-runs it."
touches:
  - this worktree's .env (created fresh, gitignored)
  - docker compose project plato-s2-r2-spans (own ClickHouse volume, host ports 18131 + 14331)
  - bench-host 10.10.10.52 via ssh user polat, key $HOME/.ssh/id_ed25519 (sbx sandboxes only)
  - out/report-*.md run reports (gitignored)
expect:
  - otlp-selfreport exits 0 from the second Docker host
  - harness spans for that run_id exist in this stack's own ClickHouse
  - one SQL joins harness spans with agent self-report spans on gentar.run_id and returns the run
  - the README quickstart SQL executes verbatim against this stack's ClickHouse
stop-conditions:
  - docker context is not orbstack
  - ssh -o BatchMode=yes polat@10.10.10.52 true fails
  - host port 18131 or 14331 already listening
  - docker compose build coordinator fails
  - docker compose config does not publish 18131 and 14331 as configured (wiring fault — covers the prior run's unexplained 4318 bind)
exclusions: "the other five gate suites (r1's instrument), subject suites, tart tier, dashboard rendering, OTLP over host ports (the relay path is compose-internal), TTL behavior beyond what the join shows"
---

# r2 — spans land in the second host's own ClickHouse; one SQL joins harness + agent

Proves the scenario's expect 3: spans from a second-host run land in
that host's own ClickHouse (the compose stack is self-contained —
nothing reaches the CI runner's telemetry), and the harness↔agent join
holds there. The join returning a row is also the regression check for
the self-report timestamp fix: with monotonic-clock timestamps the
spans landed in the 1970 partition, the 336h TTL reaped them, and this
exact query silently returned zero rows.

STEERED (orphan) after RUN-2026-09-02-02_37 FAILed on a runbook defect:
the runner captured the run id by stripping `report-gentar-` from the
report filename, discarding the `gentar-` prefix the database stores.
This steered text captures the run id unambiguously, waits a bounded
time for otelcol's batch export to settle before the join, and verifies
the port wiring via `docker compose config` before anything runs.

## Environment (declared, fixed)

- Second Docker host: THIS Mac, OrbStack — docker context `orbstack`,
  Engine 29.4.0. All `docker` commands below run on this Mac.
- Bench host: 10.10.10.52 (VM 142), ssh user `polat`, key
  `$HOME/.ssh/id_ed25519`, `sbx` installed.
- This Mac runs other, unrelated services. You touch ONLY the compose
  project `plato-s2-r2-spans`. Never stop or remove any container,
  volume, or network outside that project name.
- Reserved host ports for this runbook: ClickHouse 18131, otelcol 14331
  (distinct from r1's 18130/14330 — parallel runbooks, one host).
  All queries below go through `docker compose exec` on the compose
  network; the host ports exist only so the stack can bind.

## Steps (follow literally; never repair mid-run)

Work from this worktree's root. `cd` absolute in every shell call.

1. Record starting state:
   `docker context show` — expect `orbstack`, else stop-incomplete.
2. `ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 true` —
   expect exit 0, else stop-incomplete.
3. Verify ports free:
   `lsof -nP -iTCP:18131 -sTCP:LISTEN; lsof -nP -iTCP:14331 -sTCP:LISTEN` —
   expect no output from both, else stop-incomplete.
4. Create the local env file (gitignored):
   ```
   cp .env.example .env
   printf '\n# runbook r2 busy-host overrides\nGENTAR_CLICKHOUSE_HOST_PORT=18131\nGENTAR_OTELCOL_HOST_PORT=14331\n' >> .env
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   export COMPOSE_PROJECT_NAME=plato-s2-r2-spans
   ```
5. Port wiring verification (steer addition — run BEFORE any build/run;
   covers the prior run's unexplained 4318 bind):
   ```
   docker compose config | grep -nE '1813[01]|1433[01]|4318'
   ```
   Expect: the resolved config contains `18131` and `14331` as published
   host ports, and NO published host port `4318`. If otelcol resolves to
   a `4318:4318`-style host publish instead of `14331:4318`, that is a
   wiring fault — stop-incomplete, record the config output verbatim.
6. `docker compose build coordinator` — expect exit 0, else
   stop-incomplete.
7. Run the self-report suite once:
   `docker compose run --rm coordinator run otlp-selfreport` —
   expect exit 0. Nonzero is a FAIL with the exit code as evidence.
   Record the full suite output.
8. Capture the run id UNAMBIGUOUSLY (steer rewording — no prefix
   stripping). The report filename is `report-<run_id>.md` where
   `<run_id>` is the FULL id including its leading `gentar-`:

   ```
   REPORT=$(ls -t out/report-gentar-*.md | head -1)
   RUN_ID=$(basename "$REPORT" | sed -e 's/^report-//' -e 's/\.md$//')
   echo "report=$REPORT"
   echo "run_id=$RUN_ID"
   ```

   Expect `run_id=gentar-<YYYYMMDD>-<HHMMSS>-<hex>` (leading `gentar-`
   present). Then confirm against the database — ground truth:

   ```
   docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
     -q "SELECT DISTINCT run_id FROM gentar.spans ORDER BY run_id DESC LIMIT 3"
   ```

   Expect the captured run id to appear in that list. If the newest DB
   run id differs from the captured one, use the DB value, and record
   both verbatim.
9. Harness spans in THIS stack's ClickHouse:
   ```
   docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
     -q "SELECT count() FROM gentar.spans WHERE run_id='<run_id>'"
   ```
   Expect a count >= 1.
10. The join — agent self-report spans (OTLP → otelcol → ClickHouse
    `otel_traces`) against harness spans (`gentar.spans`), joined on the
    `gentar.run_id` resource attribute. otelcol batches exports, so the
    rows can land seconds after the suite exits; the steered runbook
    waits a BOUNDED settle window — poll the join every 10 seconds, up
    to 120 seconds total (12 attempts), stop at first non-empty result:

    ```
    for i in $(seq 1 12); do
      docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
        -q "SELECT ResourceAttributes['gentar.run_id'] AS run_id, count() AS agent_spans FROM gentar.otel_traces WHERE ResourceAttributes['gentar.run_id'] IN (SELECT DISTINCT run_id FROM gentar.spans WHERE scenario = 'otlp-selfreport' AND subject = 'arena') GROUP BY run_id" \
        | tee /tmp/r2-join-attempt-$i.txt
      [ -s /tmp/r2-join-attempt-$i.txt ] && { echo "join-settled-after-attempt=$i"; break; }
      sleep 10
    done
    ```

    Expect exactly one row, its run_id equal to the captured run id,
    agent_spans >= 1, and a `join-settled-after-attempt=N` line. Zero
    rows after all 12 attempts = FAIL (that is the TTL-reap symptom
    this scenario fixed, not an infrastructure fault) — record the last
    attempt's output.
11. README quickstart SQL, verbatim (docs drift guard for the columns
    it names):
    ```
    docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
      -q "SELECT step, status FROM gentar.spans ORDER BY ts_start" | wc -l
    ```
    Expect the clickhouse-client exit code 0 AND a line count >= 1.
12. Teardown (every exit path, including failure):
    ```
    docker compose ps
    docker compose down -v --remove-orphans
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx ls | grep gentar- || echo bench-host-clean'
    ```
    `docker compose ps` output goes in the run record. A `gentar-`
    sandbox listed here may belong to a SIBLING runbook running in
    parallel on the same bench-host (the prior run observed r1's live
    suite sandbox this way) — record it verbatim, never remove it:
    ownership is not decidable from this side. Record teardown as done.

## Verdict

- PASS: steps 7, 9, 10 (one row, matching run id, agent_spans >= 1,
  within the bounded window), and 11 all hold.
- PASS WITH FINDINGS: the expects hold AND something unexpected was
  observed — record it as a named finding.
- FAIL: suite nonzero, harness count 0, join returns no row or a
  non-matching run id after the full bounded window, or the quickstart
  SQL errors.
- incomplete: any stop-condition hit (including the step-5 port-wiring
  fault), timeout, or crash — never FAIL.

## Run record

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = run end,
local time) with the front-matter grammar from the engine's record
procedure: runbook node + commit hash, stamp, environment, verdict,
findings, teardown. Include the captured run id (both filename-derived
and DB-confirmed), the outputs of steps 5, 9, 10 (with
join-settled-after-attempt), and 11, and the teardown `docker compose
ps` listing. Commit on this branch: `run: /s2/r2 <verdict>`. Push the
branch.

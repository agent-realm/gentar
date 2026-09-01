---
node: /s2-arena-portability/r1-second-host-gate
scenario: /s2-arena-portability
status: frozen
touches:
  - this worktree's .env (created fresh, gitignored)
  - docker compose project plato-s2-r1-gate (own ClickHouse volume, host ports 18130 + 14330)
  - bench-host 10.10.10.52 via ssh user polat, key $HOME/.ssh/id_ed25519 (sbx sandboxes only)
  - out/report-*.md run reports (gitignored)
expect:
  - each of the six gate suites exits 0 from the second Docker host
  - six new report files land in out/
  - this stack's own ClickHouse holds spans for all six scenarios
stop-conditions:
  - docker context is not orbstack
  - ssh -o BatchMode=yes polat@10.10.10.52 true fails
  - host port 18130 or 14330 already listening
  - docker compose build coordinator fails
exclusions: "subject suites, tart/macOS tier, agent-smoke, nightly tier, CI wiring, dashboard rendering, reachability of the published host ports from outside this Mac (bind success is all that is tested)"
---

# r1 — second-host gate: the six deterministic suites, exit 0 each

Proves the scenario's expects 1 and 2: from a second Docker host — a
laptop-class machine that is not the CI runner VM — `docker compose run
--rm coordinator run <suite>` exits 0 for every gate suite, against the
same bench-host VM 142 over SSH.

## Environment (declared, fixed)

- Second Docker host: THIS Mac, OrbStack — docker context `orbstack`,
  Engine 29.4.0. All `docker` commands below run on this Mac.
- Bench host: 10.10.10.52 (VM 142), ssh user `polat`, key
  `$HOME/.ssh/id_ed25519`, `sbx` installed.
- This Mac runs other, unrelated services. You touch ONLY the compose
  project `plato-s2-r1-gate`. Never stop or remove any container,
  volume, or network outside that project name.
- Reserved host ports for this runbook: ClickHouse 18130, otelcol 14330.
  (Defaults 8123/4318 are taken by other stacks on this Mac — that is
  the busy-host condition this scenario fixes around.)

## Steps (follow literally; never repair mid-run)

Work from this worktree's root. `cd` absolute in every shell call.

1. Record starting state:
   `docker context show` — expect `orbstack`, else stop-incomplete.
2. `ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 true` —
   expect exit 0, else stop-incomplete.
3. Verify ports free:
   `lsof -nP -iTCP:18130 -sTCP:LISTEN; lsof -nP -iTCP:14330 -sTCP:LISTEN` —
   expect no output from both, else stop-incomplete.
4. Create the local env file (gitignored):
   ```
   cp .env.example .env
   printf '\n# runbook r1 busy-host overrides\nGENTAR_CLICKHOUSE_HOST_PORT=18130\nGENTAR_OTELCOL_HOST_PORT=14330\n' >> .env
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   export COMPOSE_PROJECT_NAME=plato-s2-r1-gate
   ```
5. `docker compose build coordinator` — expect exit 0, else
   stop-incomplete.
6. Count reports before: `ls out/report-*.md 2>/dev/null | wc -l`.
7. Run the six gate suites IN THIS ORDER, one compose run each,
   recording each exit code:
   1. `docker compose run --rm coordinator run smoke`
   2. `docker compose run --rm coordinator run bench-template-verify`
   3. `docker compose run --rm coordinator run otlp-selfreport`
   4. `docker compose run --rm coordinator run budget-sim`
   5. `docker compose run --rm coordinator run scripted-onboarding`
   6. `docker compose run --rm coordinator run scripted-danger`
   Expected result for EACH: exit code 0. A nonzero exit code is a
   FAIL verdict with that suite's name and exit code as the failure
   evidence — do not retry, do not fix.
8. Count reports after: `ls out/report-*.md | wc -l` — expect
   before + 6.
9. Spans landed in THIS stack's own ClickHouse (over the compose
   network, no host port involved):
   ```
   docker compose exec clickhouse clickhouse-client --user gentar --password gentar \
     -q "SELECT scenario, count(DISTINCT run_id) FROM gentar.spans GROUP BY scenario ORDER BY scenario"
   ```
   Expect six rows, one per gate suite name, each count >= 1.
10. Teardown (every exit path, including failure):
    ```
    docker compose ps
    docker compose down -v --remove-orphans
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
      -i "$HOME/.ssh/id_ed25519" polat@10.10.10.52 'sbx ls | grep gentar- || echo bench-host-clean'
    ```
    `docker compose ps` output goes in the run record (proof you only
    touched your own project). Record teardown as done.

## Verdict

- PASS: steps 7 (all six exit 0), 8, and 9 hold.
- PASS WITH FINDINGS: the expects hold AND something unexpected was
  observed — record it as a named finding.
- FAIL: any suite exit nonzero, or expect 8/9 violated.
- incomplete: any stop-condition hit, timeout, or crash — never FAIL.

## Run record

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = run end,
local time) with the front-matter grammar from the engine's record
procedure: runbook node + commit hash, stamp, environment, verdict,
findings, teardown. Include the six exit codes, both report counts, the
step-9 query output, and the teardown `docker compose ps` listing.
Commit on this branch: `run: /s2/r1 <verdict>`. Push the branch.

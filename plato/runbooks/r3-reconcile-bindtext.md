---
node: /s7-docs-truth/r3-reconcile-bindtext
scenario: /s7-docs-truth
status: orphan
touches:
  - "worktree .env (arena: COMPOSE_PROJECT_NAME=gentar-s7r3, GENTAR_NAME_PREFIX=gentar-s7arm, ports 18192/14392)"
  - "shell-exported GENTAR_CLICKHOUSE_HOST_PORT drifts to 18193, 18194, 18195 (invocation-scoped)"
  - "docker compose up -d clickhouse otelcol (setup — never the coordinator service, whose compose default command runs an unbidden smoke)"
  - "docker compose run --rm coordinator ls (drifted and clean), docker compose exec -T clickhouse clickhouse-client (drifted)"
  - "throwaway squatter container s7r3-squatter (nginx:alpine) publishing 127.0.0.1:18195; removed with docker rm -f -v"
  - "flattened copies /tmp/s7r3-readme.flat and /tmp/s7r3-envex.flat (whitespace/comment-prefix canonicalization)"
expect:
  - "drifted `run` (export 18193): exits 0, clickhouse container id CHANGES, `docker port` shows only 127.0.0.1:18193->8123, curl 18193 /ping = Ok., curl 18192 dead"
  - "drifted `exec` (export 18194): exits 0 printing 1 — and does NOT reconcile: clickhouse container id UNCHANGED from the drifted-run container, `docker port` still shows only 18193, curl 18194 refused, curl 18193 still Ok."
  - "clean `run` (no export): clickhouse container id CHANGES, publish back to 18192 only, curl 18192 = Ok."
  - "squatter-held port (export 18195): the drifted `run` FAILS nonzero; its output names the endpoint (matches `clickhouse-1`) and the port 18195 (matches `Bind for 127.0.0.1:18195` or `already allocated`); the output contains neither `.env` nor the string `GENTAR_`"
  - "docs agreement (flattened copies, new wording): README contains '`docker compose run` recreates the running clickhouse onto the drifted port' and '`docker compose exec` does not — it runs inside the already-running container'; .env.example contains '`docker compose run` reconciles and recreates clickhouse onto the drifted' and '`docker compose exec` does not — it runs inside the already-running container'; NEITHER flattened file matches the retired false clause ('`run` or `exec` will recreate' / '`run` and `exec` included')"
stop-conditions:
  - "arena fails to come up healthy before any drift -> incomplete"
  - "any drift step's container id / port / curl observation differs from its expect -> FAIL"
  - "bind-error output names the env file or the knob, or fails to name endpoint+port -> FAIL"
  - "any docs grep (positive or negative) disagrees with the new wording -> FAIL"
exclusions: "no bench, no sandbox, no bench-host use (drifted invocations run `ls` and a SQL SELECT only); does not test the --env-file seam (r2) or the silent-shadow / force-recreate recovery (r4); flattening removes layout only — source files never edited"
steer: "Pilot steer round 2, 2026-09-20 ('Fix docs, re-run r3'): the old r3 runbook expected the OLD (false) wording — 'a drifted docker compose run or exec will recreate the running clickhouse'. The pilot fixed the docs in the scenario branch (plato/s7-docs-truth @ c83dc35: README + .env.example + SCENARIO.md now say drifted `run` recreates, drifted `exec` does not — runs inside the existing container). Rework the agreement check to assert the NEW wording and re-run fresh. Previous run of the pre-steer version: RUN-2026-09-20-00_51-r3-reconcile.md @ 1f90e98, verdict FAIL — the exec half of the old claim was falsified (exec ran in the existing container, nothing recreated); the run-recreates and bind-error clauses were confirmed."
---

# r3 — reconciliation scope and bind-error text (v2, steered)

README scoping rule now claims: "A drifted `docker compose run`
recreates the running clickhouse onto the drifted port; a drifted
`docker compose exec` does not — it runs inside the already-running
container, so nothing is recreated there. The bind error that follows
names the endpoint (`plato-x-clickhouse-1: Bind for 127.0.0.1:18123
failed`) but neither the env file nor the `GENTAR_*_HOST_PORT` knob."

v1 measured the old wording and falsified its exec half; the pilot
corrected the docs (scenario tip c83dc35, merged into this branch).
v2 asserts the corrected claim live, plus docs agreement on the new
wording and absence of the retired one.

## Setup

1. Work in the worktree this runbook lives in. All paths absolute.
2. `cp .env.example .env` then edit `.env` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7r3`
   - `GENTAR_NAME_PREFIX=gentar-s7arm`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18192`
   - `GENTAR_OTELCOL_HOST_PORT=14392`
   - `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`
3. `docker compose build coordinator`.
4. `docker compose up -d clickhouse otelcol` (telemetry only — the
   coordinator service must NOT start: its compose default command is
   `[run, smoke]`, which would run an unbidden bench; the coordinator
   appears only as the one-off `run --rm` invocations below).
   Wait until `curl -sf http://127.0.0.1:18192/ping` prints `Ok.`
   (poll 3s, timeout 120s -> incomplete). Confirm
   `docker compose ps` lists no running coordinator (record listing).
5. Record C0 = `docker compose ps -q clickhouse`; record
   `docker port $(docker compose ps -q clickhouse)` output.

## Do

6. Drifted `run` (shell export, invocation-scoped):

   ```
   GENTAR_CLICKHOUSE_HOST_PORT=18193 docker compose run --rm coordinator ls > /tmp/s7r3-drift-run.log 2>&1; echo "exit=$?"
   ```

   Checks: exit 0 and `smoke` listed in the log; C1 = `docker compose ps -q
   clickhouse` differs from C0; `docker port $(docker compose ps -q
   clickhouse)` shows ONLY `127.0.0.1:18193->8123`; `curl -sf
   http://127.0.0.1:18193/ping` = `Ok.`; `curl -s http://127.0.0.1:18192/ping`
   fails (record the curl exit code).
7. Drifted `exec` — must NOT reconcile:

   ```
   GENTAR_CLICKHOUSE_HOST_PORT=18194 docker compose exec -T clickhouse clickhouse-client --user gentar --password gentar -q "SELECT 1" > /tmp/s7r3-drift-exec.log 2>&1; echo "exit=$?"
   ```

   Checks: exit 0, log prints `1` (it ran inside the existing container);
   C2 = `docker compose ps -q clickhouse` is IDENTICAL to C1; `docker
   port ...` still shows ONLY 18193; `curl -s http://127.0.0.1:18194/ping`
   is refused (record exit code); `curl -sf http://127.0.0.1:18193/ping`
   still prints `Ok.`.
8. Clean revert (no exports):

   ```
   docker compose run --rm coordinator ls > /tmp/s7r3-revert.log 2>&1; echo "exit=$?"
   ```

   Checks: exit 0; C3 differs from C2; `docker port ...` shows ONLY
   18192; curl 18192 = `Ok.`.
9. Docs agreement — flattened copies (layout removal only; source
   files never modified):

   ```
   tr '\n' ' ' < README.md | tr -s ' ' > /tmp/s7r3-readme.flat
   sed 's/^#//' .env.example | tr '\n' ' ' | tr -s ' ' > /tmp/s7r3-envex.flat
   ```

   Positive greps (`grep -cF`, each >= 1):
   - /tmp/s7r3-readme.flat: `` `docker compose run` recreates the running clickhouse onto the drifted port `` · `` `docker compose exec` does not — it runs inside the already-running container ``
   - /tmp/s7r3-envex.flat: `` `docker compose run` reconciles and recreates clickhouse onto the drifted `` · `` `docker compose exec` does not — it runs inside the already-running container ``

   Negative greps (`grep -cF`, each 0 — the retired false clause):
   - /tmp/s7r3-readme.flat: `` `run` or `exec` will recreate ``
   - /tmp/s7r3-envex.flat: `` `run` and `exec` included ``

10. Bind-error text. Start the squatter, then run drifted against the
    port it holds:

    ```
    docker run -d --name s7r3-squatter -p 127.0.0.1:18195:80 nginx:alpine
    GENTAR_CLICKHOUSE_HOST_PORT=18195 docker compose run --rm coordinator ls > /tmp/s7r3-bindfail.log 2>&1; echo "exit=$?"
    ```

    Checks on /tmp/s7r3-bindfail.log: exit nonzero; log matches
    `clickhouse-1` (endpoint named); log matches `18195` AND (`Bind for
    127.0.0.1:18195` OR `already allocated`); log does NOT match `\.env`;
    log does NOT match `GENTAR_`. Paste the decisive error lines verbatim
    into the run record.

## Teardown (record as final step)

11. `docker rm -f -v s7r3-squatter`; `docker compose down -v`. Confirm
    `docker ps -a --format '{{.Names}}' | grep gentar-s7r3` is empty and
    `docker compose ls` no longer lists gentar-s7r3.

## Record

12. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>-r3-reconcile.md` with
    front-matter per record.md (runbook node + the steered commit this
    run executed, stamp, environment, verdict, findings, teardown:
    done). Body: the C0/C1/C2/C3 container ids (short), the `docker
    port` output at each step, each curl result, the six docs-grep
    counts, and the verbatim bind-error lines.
13. Commit `run: /s7/r3-reconcile-bindtext <verdict>`. Do NOT change
    the runbook's `status: orphan` — a steered runbook stays orphan.
    Push to origin.

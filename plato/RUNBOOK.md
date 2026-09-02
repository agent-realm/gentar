---
node: /s7-docs-truth/r3-reconcile-bindtext
scenario: /s7-docs-truth
status: draft
touches:
  - "worktree .env (arena: COMPOSE_PROJECT_NAME=gentar-s7r3, GENTAR_NAME_PREFIX=gentar-s7arm, ports 18192/14392)"
  - "shell-exported GENTAR_CLICKHOUSE_HOST_PORT drifts to 18193, 18194, 18195 (invocation-scoped)"
  - "docker compose run --rm coordinator ls (drifted and clean), docker compose exec -T clickhouse clickhouse-client (drifted)"
  - "throwaway squatter container s7r3-squatter (nginx:alpine) publishing 127.0.0.1:18195; removed with docker rm -f -v"
expect:
  - "drifted `run` (export 18193): exits 0, clickhouse container id CHANGES, `docker port` shows only 127.0.0.1:18193->8123, curl 18193 /ping = Ok., curl 18192 dead"
  - "drifted `exec` (export 18194): exits 0 printing 1, clickhouse container id CHANGES again, `docker port` shows only 18194, curl 18194 = Ok., curl 18193 dead"
  - "clean `run` (no export): clickhouse container id CHANGES again, publish back to 18192 only, curl 18192 = Ok."
  - "squatter-held port (export 18195): the drifted `run` FAILS nonzero; its output names the endpoint (matches `clickhouse-1`) and the port 18195 (matches `Bind for 127.0.0.1:18195` or `already allocated`); the output contains neither `.env` nor the string `GENTAR_`"
stop-conditions:
  - "arena fails to come up healthy before any drift -> incomplete"
  - "any drift step's container id / port / curl observation differs from the table -> FAIL"
  - "bind-error output names the env file or the knob, or fails to name endpoint+port -> FAIL"
exclusions: "no bench, no sandbox, no bench-host use (drifted invocations run `ls` and a SQL SELECT only); does not test the --env-file seam (r2) or the silent-shadow / force-recreate recovery (r4)"
---

# r3 — reconciliation scope and bind-error text

README scoping rule claims: "a later compose call without the exports
silently reverts to the file's values and reconciles your containers
against them — and ANY compose invocation reconciles, not just `up`: a
drifted `docker compose run` or `exec` will recreate the running
clickhouse onto the exported port too. The bind error that follows
names the endpoint (`plato-x-clickhouse-1: Bind for 127.0.0.1:18123
failed`) but neither the env file nor the `GENTAR_*_HOST_PORT` knob."

This runbook falsifies or confirms each clause against one live arena.

## Setup

1. Work in the worktree this runbook lives in. All paths absolute.
2. `cp .env.example .env` then edit `.env` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7r3`
   - `GENTAR_NAME_PREFIX=gentar-s7arm`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18192`
   - `GENTAR_OTELCOL_HOST_PORT=14392`
   - `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`
3. `docker compose build coordinator`.
4. `docker compose up -d`, wait until `curl -sf http://127.0.0.1:18192/ping`
   prints `Ok.` (poll 3s, timeout 120s -> incomplete).
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
7. Drifted `exec`:

   ```
   GENTAR_CLICKHOUSE_HOST_PORT=18194 docker compose exec -T clickhouse clickhouse-client --user gentar --password gentar -q "SELECT 1" > /tmp/s7r3-drift-exec.log 2>&1; echo "exit=$?"
   ```

   Checks: exit 0, log prints `1`; C2 = `docker compose ps -q clickhouse`
   differs from C1; `docker port ...` shows ONLY 18194; curl 18194 =
   `Ok.`; curl 18193 fails.
8. Clean revert (no exports):

   ```
   docker compose run --rm coordinator ls > /tmp/s7r3-revert.log 2>&1; echo "exit=$?"
   ```

   Checks: exit 0; C3 differs from C2; `docker port ...` shows ONLY
   18192; curl 18192 = `Ok.`.
9. Bind-error text. Start the squatter, then run drifted against the
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

10. `docker rm -f -v s7r3-squatter`; `docker compose down -v`. Confirm
    `docker ps -a --format '{{.Names}}' | grep -E 's7r3|s7arm'` returns
    nothing of this arena's making (the bench-host is untouched this
    run) and `docker compose ls` no longer lists gentar-s7r3.

## Record

11. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>-r3-reconcile.md` with
    front-matter per record.md. Body: the C0/C1/C2/C3 container ids
    (short), the `docker port` output at each step, each curl result,
    and the verbatim bind-error lines.
12. Commit `run: /s7/r3-reconcile-bindtext <verdict>`, flip RUNBOOK.md
    `status: draft` -> `status: frozen`, commit
    `runbook: /s7-docs-truth/r3-reconcile-bindtext frozen (first run recorded)`.
    Push both to origin.

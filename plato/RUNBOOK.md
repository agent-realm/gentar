---
node: /s7-docs-truth/r4-shadow-recovery
scenario: /s7-docs-truth
status: frozen
touches:
  - "worktree .env (arena: COMPOSE_PROJECT_NAME=gentar-s7r4, GENTAR_NAME_PREFIX=gentar-s7arm, clickhouse knob pinned to 18197, otelcol 14396)"
  - "native loopback listener on 18197: python3 -m http.server 18197 --bind 127.0.0.1 (killed at teardown)"
  - "throwaway squatter container s7r4-squatter (nginx:alpine) publishing 127.0.0.1:18197; removed with docker rm -f -v"
  - "docker compose up -d clickhouse, docker port, curl /ping, docker compose up -d --force-recreate clickhouse"
expect:
  - "case A (native listener holds 18197): `up -d clickhouse` exits 0 with NO error, container reaches healthy, `docker port` LISTS the 18197 mapping, yet curl http://127.0.0.1:18197/ping does NOT return Ok. — it answers the native python server (HTTP status 404), while the same container's compose-network /ping does return Ok."
  - "case B step 1 (squatter container holds 18197): `up -d clickhouse` FAILS nonzero naming endpoint and port"
  - "case B step 2 (squatter removed, plain `up -d clickhouse`): exits 0, container reaches healthy, but `docker port <clickhouse>` output is EMPTY and curl 18197/ping is refused — the inert publish"
  - "case B step 3 (`up -d clickhouse --force-recreate`): `docker port` lists 127.0.0.1:18197->8123 and curl 18197/ping returns Ok."
stop-conditions:
  - "case A `up -d` errors loudly instead of the documented silent loss -> FAIL (README falsified for this host)"
  - "case B step 2 shows a working publish without --force-recreate -> FAIL (README falsified)"
  - "any container fails to reach healthy within 120s where the expect says healthy -> incomplete"
exclusions: "no bench, no sandbox, no bench-host use; coordinator image never built or run (clickhouse service only); the reconciliation scope and --env-file seam are r3/r2"
---

# r4 — busy-host field notes: silent shadow on a knob-targeted port, inert publish, --force-recreate recovery

README busy-host section claims two recovery notes: "if a port knob you
set points at an occupied port, the same silent loss applies — verify
with `curl http://127.0.0.1:<port>/ping` before relying on the publish;
and after a bind failure, removing the squatter and running plain
`docker compose up -d` can leave the container Up/healthy with the
publish silently *absent* (`docker port <container>` empty) — recreate
with `docker compose up -d --force-recreate <service>` to restore it."

Docker host here is OrbStack — the host the silent-loss behavior is
documented for. All commands run in this runbook's worktree.

## Setup

1. `cp .env.example .env` then edit `.env` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7r4`
   - `GENTAR_NAME_PREFIX=gentar-s7arm`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18197`
   - `GENTAR_OTELCOL_HOST_PORT=14396`
   - `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`

## Case A — knob at a port a native listener holds (silent shadow)

2. Start the native listener and prove it answers:

   ```
   nohup python3 -m http.server 18197 --bind 127.0.0.1 >/tmp/s7r4-native.log 2>&1 & echo $! > /tmp/s7r4-native.pid
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18197/ping
   ```

   (expect 404 from python). Record the PID.
3. `docker compose up -d clickhouse > /tmp/s7r4-a-up.log 2>&1; echo "exit=$?"`
   — expect exit 0 and NO error text in the log.
4. Wait for healthy: poll `docker inspect --format '{{.State.Health.Status}}'
   $(docker compose ps -q clickhouse)` until `healthy` (3s interval,
   120s timeout -> incomplete).
5. Record `docker port $(docker compose ps -q clickhouse)` — expect the
   18197 mapping listed.
6. Host side: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18197/ping`
   — expect 404 (the native server answers, NOT clickhouse's `Ok.`).
   Also `curl -s http://127.0.0.1:18197/ping | head -c 40` to capture the
   python error page as evidence.
7. Container side: `docker compose exec -T clickhouse wget -qO- http://localhost:8123/ping`
   — expect `Ok.` (the server itself is fine; the loss is host-side).
8. Case A teardown: `kill $(cat /tmp/s7r4-native.pid)`;
   `docker compose down -v`.

## Case B — bind failure, inert publish, force-recreate recovery

9. Squatter container takes the knob port:

   ```
   docker run -d --name s7r4-squatter -p 127.0.0.1:18197:80 nginx:alpine
   docker compose up -d clickhouse > /tmp/s7r4-b-bindfail.log 2>&1; echo "exit=$?"
   ```

   Expect nonzero exit; log names the endpoint (`clickhouse-1`) and port
   (`18197`, `Bind` or `already allocated`). Paste the lines into the run
   record.
10. Remove the squatter: `docker rm -f -v s7r4-squatter`.
11. Plain `up -d` (the README's trap):

    ```
    docker compose up -d clickhouse > /tmp/s7r4-b-plainup.log 2>&1; echo "exit=$?"
    ```

    Expect exit 0, container reaches healthy (poll as step 4), but
    `docker port $(docker compose ps -q clickhouse)` prints NOTHING
    (empty), and `curl -s http://127.0.0.1:18197/ping` fails (record
    exit code). Record `docker port` output verbatim (or its emptiness).
12. Recovery: `docker compose up -d clickhouse --force-recreate`. Expect
    `docker port $(docker compose ps -q clickhouse)` lists
    `127.0.0.1:18197->8123` and `curl -sf http://127.0.0.1:18197/ping`
    prints `Ok.`.

## Teardown (record as final step)

13. `docker compose down -v`; ensure the native listener is dead
    (`kill $(cat /tmp/s7r4-native.pid) 2>/dev/null || true`; verify port
    18197 closed via `lsof -nP -iTCP:18197 -sTCP:LISTEN` empty);
    ensure squatter gone (`docker ps -a --format '{{.Names}}' | grep
    s7r4-squatter` empty); `docker compose ls` no longer lists
    gentar-s7r4.

## Record

14. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>-r4-shadow.md` with
    front-matter per record.md. Body: per case the compose exit code,
    container health, `docker port` output, curl codes/bodies, and the
    verbatim bind-error lines.
15. Commit `run: /s7/r4-shadow-recovery <verdict>`, flip RUNBOOK.md
    `status: draft` -> `status: frozen`, commit
    `runbook: /s7-docs-truth/r4-shadow-recovery frozen (first run recorded)`.
    Push both to origin.

---
node: /s7-docs-truth/r2-envfile-project-seam
scenario: /s7-docs-truth
status: draft
touches:
  - "worktree .env (arena A: COMPOSE_PROJECT_NAME=gentar-s7arm, GENTAR_NAME_PREFIX=gentar-s7arm, ports 18190/14390)"
  - "worktree .env-nbr (arena B: COMPOSE_PROJECT_NAME=gentar-s7nbr, GENTAR_NAME_PREFIX=gentar-s7nbr, ports 18191/14391)"
  - "docker compose up -d (A) ; docker compose --env-file .env-nbr up -d (B)"
  - "docker compose --env-file .env-nbr run --rm coordinator run smoke  (the seam)"
  - "bench-host 10.10.10.52: exactly one sbx sandbox, named <prefix>-<stamp>-<hex>, created and destroyed by the run itself"
  - "ClickHouse queries over compose exec into both arenas"
expect:
  - "both arenas come up healthy; A publishes 127.0.0.1:18190, B publishes 127.0.0.1:18191; both answer curl /ping with Ok."
  - "the seam invocation exits 0 (smoke green) and creates NO third compose project: `docker compose ls` still lists exactly gentar-s7arm and gentar-s7nbr"
  - "the newest file in out/ is report-gentar-s7arm-<stamp>-<hex>.md — the container read the literal .env (arena A's prefix) even though the invocation ran under project gentar-s7nbr"
  - "arena B's gentar.spans contains >= 1 row with run_id LIKE 'gentar-s7arm-%' (sandbox stamped A's prefix, spans written into B's ClickHouse)"
  - "arena A's gentar.spans contains 0 rows with run_id LIKE 'gentar-s7arm-%' (table absent also counts as 0)"
stop-conditions:
  - "either arena fails to come up healthy -> incomplete"
  - "smoke exits nonzero -> FAIL"
  - "the run_id rows land anywhere other than stated -> FAIL"
exclusions: "does not test the port-knob scoping rule or reconciliation (r3), not the silent-shadow/force-recreate notes (r4); B itself never runs a scenario, so no sandbox carries prefix gentar-s7nbr"
---

# r2 — the --env-file seam: project name follows the flag, container env follows the literal .env

README scoping rule claims: "`--env-file` is no escape either: it
drives interpolation AND the project name, while the coordinator
container still reads the literal `.env` — one variable, two values,
no error; a live drill produced a sandbox stamped arena A's prefix
writing into arena B's ClickHouse through exactly this seam."

This runbook reproduces that sentence against two live arenas.

## Setup

1. Work in the worktree this runbook lives in. All paths absolute.
2. `cp .env.example .env` then edit `.env` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7arm`
   - `GENTAR_NAME_PREFIX=gentar-s7arm`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18190`
   - `GENTAR_OTELCOL_HOST_PORT=14390`
   - `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`
3. `cp .env .env-nbr` then edit `.env-nbr` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7nbr`
   - `GENTAR_NAME_PREFIX=gentar-s7nbr`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18191`
   - `GENTAR_OTELCOL_HOST_PORT=14391`
4. Build the coordinator image for both projects:
   - `docker compose build coordinator`
   - `docker compose --env-file .env-nbr build coordinator`

## Do

5. Bring up arena A: `docker compose up -d`, then wait until
   `curl -sf http://127.0.0.1:18190/ping` prints `Ok.` (poll, 3s
   interval, give up at 120s -> incomplete).
6. Bring up arena B: `docker compose --env-file .env-nbr up -d`, then
   wait until `curl -sf http://127.0.0.1:18191/ping` prints `Ok.`.
7. Baseline: `docker compose ls` lists exactly the two projects
   gentar-s7arm and gentar-s7nbr (any other pre-existing project on the
   host is foreign: record its name, never touch it).
8. The seam (run from the arena A checkout, steering the invocation at
   arena B with --env-file while the coordinator container reads the
   literal `.env`):

   ```
   docker compose --env-file .env-nbr run --rm coordinator run smoke; echo "exit=$?"
   ```

   Expect exit 0. This creates one sbx sandbox on 10.10.10.52 whose name
   is the run_id (prefix gentar-s7arm); the scenario destroys it itself.
   Never manually `sbx rm` anything.
9. Project check: `docker compose ls` still lists exactly the same two
   gentar projects (no third project was created by the run).
10. Report check: newest file in `out/` matches
    `report-gentar-s7arm-*.md` (record its exact name).
11. Span attribution — query BOTH arenas over the compose network:

    ```
    docker compose -p gentar-s7nbr exec -T clickhouse clickhouse-client --user gentar --password gentar -q \
      "SELECT count() FROM gentar.spans WHERE run_id LIKE 'gentar-s7arm-%'"
    docker compose -p gentar-s7arm exec -T clickhouse clickhouse-client --user gentar --password gentar -q \
      "SELECT count() FROM gentar.spans WHERE run_id LIKE 'gentar-s7arm-%'"
    ```

    Expect: first >= 1 (B holds the A-stamped run), second 0 (or
    `gentar.spans doesn't exist` — record which; both count as 0).
    Record one sample run_id from B:

    ```
    docker compose -p gentar-s7nbr exec -T clickhouse clickhouse-client --user gentar --password gentar -q \
      "SELECT DISTINCT run_id FROM gentar.spans WHERE run_id LIKE 'gentar-s7arm-%' LIMIT 3"
    ```

## Teardown (record as final step)

12. `docker compose --env-file .env-nbr down -v` then
    `docker compose down -v`. Confirm both gone from `docker compose ls`
    and no containers remain for either prefix
    (`docker ps -a --format '{{.Names}}' | grep -E 's7arm|s7nbr'` empty).
    Do not touch any other compose project or container.

## Record

13. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>-r2-envfile.md` with
    front-matter per record.md (runbook node + commit, stamp,
    environment, verdict, findings, teardown: done). Body: the two
    counts, the sample run_id, the report filename, the project list
    before/after.
14. Commit `run: /s7/r2-envfile-project-seam <verdict>`, flip RUNBOOK.md
    `status: draft` -> `status: frozen`, commit
    `runbook: /s7-docs-truth/r2-envfile-project-seam frozen (first run recorded)`.
    Push both to origin.

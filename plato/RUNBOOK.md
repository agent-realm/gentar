---
node: /s7-docs-truth/r1-prefix-docs-agree
scenario: /s7-docs-truth
status: frozen
touches:
  - "worktree .env (untracked; project gentar-s7r1, ports 18190/14390 never bound)"
  - "docker compose build coordinator; docker compose run --rm --no-deps -e GENTAR_NAME_PREFIX=<case> coordinator ls"
  - "README.md two-arenas section; .env.example prefix block; coordinator/gentar/config.py refusal message"
expect:
  - "every refused case: docker compose run exits 2 and prints one line starting 'error: GENTAR_NAME_PREFIX' that contains 'must START WITH A LETTER' and the case value in quotes"
  - "1gentar refusal message additionally contains 'max 24 chars'"
  - "every accepted case: exit 0 and the listing prints, one suite name per line, including 'smoke'"
  - "README two-arenas section states: starts-with-letter, digits allowed, single dashes only, no underscores, 24 chars max"
  - ".env.example prefix block states the same rule and names gentar-1a legal, 1gentar and gentar--x illegal"
  - "docs boundary shapes and validator verdicts agree on all seven cases of the table below"
stop-conditions:
  - "coordinator image build fails -> incomplete"
  - "a case exits with any code other than the table's expected code -> FAIL"
  - "any doc grep misses -> FAIL"
exclusions: "does not spawn benches, does not touch the bench-host, does not bind any host port (coordinator only, --no-deps), does not test the two-arena or scoping-rule prose (r2/r3 own those)"
---

# r1 — prefix shape: validator, refusal message, and docs agree

README (two-arenas section) and .env.example now state the full prefix
shape, and the refusal message names the leading-letter rule with
legal/illegal examples. This runbook drives every boundary shape
through the real validator (`coordinator ls` refuses at startup, exit 2)
and greps the docs for the same rule.

## Setup

1. Work in the worktree this runbook lives in. All paths absolute.
2. `cp .env.example .env` then edit `.env` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7r1`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18190`
   - `GENTAR_OTELCOL_HOST_PORT=14390`
   - `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`
3. `docker compose build coordinator` (must succeed).

## Do

4. Run each case, capturing combined output and exit code to
   `/tmp/s7r1-<case>.log`:

   ```
   docker compose run --rm --no-deps -e GENTAR_NAME_PREFIX=<case> coordinator ls > /tmp/s7r1-<case>.log 2>&1; echo "exit=$?"
   ```

   | case        | value                        | expect |
   |-------------|------------------------------|--------|
   | leadingdigit| `1gentar`                    | exit 2 |
   | doubledash  | `gentar--x`                  | exit 2 |
   | underscore  | `gentar_x`                   | exit 2 |
   | uppercase   | `Gentar`                     | exit 2 |
   | overlong    | `abcdefghijklmnopqrstuvwxy` (25 chars) | exit 2 |
   | atlimit     | `abcdefghijklmnopqrstuvwx` (24 chars)  | exit 0 |
   | digitafterdash | `gentar-1a`               | exit 0 |

5. For every refused case, the log must contain one line matching
   `^error: GENTAR_NAME_PREFIX '<value>'` and the substring
   `must START WITH A LETTER`; the leadingdigit log must additionally
   contain `max 24 chars` and the literal examples `gentar-1a is legal`
   and `1gentar, gentar--x, Gentar are not`.
6. For every accepted case, the log must contain a line exactly `smoke`
   and end with exit 0.
7. Docs greps (run in the worktree root; each must hit):
   - README.md contains `must START WITH A LETTER`, `digits, and single dashes only`, `no leading digit, no double dash, no underscores`, `24 chars max`
   - .env.example contains `starts with a letter`, `single dashes`, `24 chars max`, `` `gentar-1a` is legal, `1gentar` and `gentar--x` are not ``

## Teardown (record as final step)

8. `docker compose down -v --remove-orphans` (removes nothing but the
   project's network; no services were started). Confirm with
   `docker compose ps -a` that no containers exist for project gentar-s7r1.

## Record

9. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = now, local)
   with front-matter per record.md: runbook `node: /s7-docs-truth/r1-prefix-docs-agree @ <commit>`,
   stamp, environment (docker host name from `docker context show`, compose version),
   verdict, findings (empty on PASS), teardown: done. Body: the seven-row
   case table with observed exit codes, the exact refusal line for
   `1gentar`, doc grep results.
10. Commit `run: /s7/r1-prefix-docs-agree <verdict>`, then flip
    RUNBOOK.md front-matter `status: draft` -> `status: frozen` and commit
    `runbook: /s7-docs-truth/r1-prefix-docs-agree frozen (first run recorded)`.
    Push both to origin.

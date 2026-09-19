---
node: /s7-docs-truth/r1-prefix-docs-agree
scenario: /s7-docs-truth
status: orphan
touches:
  - "worktree .env (untracked; project gentar-s7r1, ports 18190/14390 never bound)"
  - "docker compose build coordinator; docker compose run --rm --no-deps -e GENTAR_NAME_PREFIX=<case> coordinator ls"
  - "README.md two-arenas section; .env.example prefix block; coordinator/gentar/config.py refusal message"
  - "flattened copies /tmp/s7r1-readme.flat and /tmp/s7r1-envex.flat (whitespace/comment-prefix canonicalization)"
expect:
  - "every refused case: docker compose run exits 2 and prints one line starting 'error: GENTAR_NAME_PREFIX' that contains 'must START WITH A LETTER' and the case value in quotes"
  - "1gentar refusal message additionally contains 'max 24 chars'"
  - "every accepted case: exit 0 and the listing prints, one suite name per line, including 'smoke'"
  - "against the flattened README copy, all four fixed-string greps hit: 'must START WITH A LETTER', 'digits, and single dashes only', 'no leading digit, no double dash, no underscores', '24 chars max'"
  - "against the flattened .env.example copy, all four fixed-string greps hit: 'starts with a letter', 'single dashes only', '24 chars max', '`gentar-1a` is legal, `1gentar` and `gentar--x` are not'"
  - "docs boundary shapes and validator verdicts agree on all seven cases of the table below"
stop-conditions:
  - "coordinator image build fails -> incomplete"
  - "a case exits with any code other than the table's expected code -> FAIL"
  - "any flattened-copy grep misses -> FAIL"
exclusions: "does not spawn benches, does not touch the bench-host, does not bind any host port (coordinator only, --no-deps), does not test the two-arena or scoping-rule prose (r2/r3 own those); flattening removes layout only (newlines, indentation, leading '#' comment markers) — it never edits the source files"
steer: "Pilot steer 2026-09-02 ('go'): r1-prefix-docs-agree — the FAIL was wrap-brittle greps. Rework the doc-agreement checks to flatten line-wraps before matching (e.g. collapse whitespace/newlines per file, or grep a canonicalized copy) so clause text matches regardless of where README/.env.example break lines. This is a new runbook version → orphan the old r1 (record FAIL + steer in the orphan commit), re-run fresh. Previous run of the pre-steer version: RUN-2026-09-02-14_43.md, verdict FAIL — 3 of 8 greps missed on line-wrap/comment-prefix artifacts; all seven validator cases and the refusal message PASSED."
---

# r1 — prefix shape: validator, refusal message, and docs agree (v2, steered)

README (two-arenas section) and .env.example state the full prefix
shape, and the refusal message names the leading-letter rule with
legal/illegal examples. v1 proved all seven validator cases and the
message; its doc greps failed only on line-wrap. v2 canonicalizes each
doc to a flattened copy (newlines and indentation collapsed to single
spaces, leading `#` comment markers stripped) before fixed-string
matching — layout may not decide a docs-truth check.

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
7. Docs checks against flattened copies (canonicalization = layout
   removal only; the source files are never modified):

   ```
   tr '\n' ' ' < README.md | tr -s ' ' > /tmp/s7r1-readme.flat
   sed 's/^#//' .env.example | tr '\n' ' ' | tr -s ' ' > /tmp/s7r1-envex.flat
   ```

   Then `grep -cF` each fixed string (expect >= 1 hit each):
   - /tmp/s7r1-readme.flat: `must START WITH A LETTER` · `digits, and single dashes only` · `no leading digit, no double dash, no underscores` · `24 chars max`
   - /tmp/s7r1-envex.flat: `starts with a letter` · `single dashes only` · `24 chars max` · `` `gentar-1a` is legal, `1gentar` and `gentar--x` are not ``

## Teardown (record as final step)

8. `docker compose down -v --remove-orphans` (removes the project's
   network only; no services were started). Confirm with
   `docker compose ps -a` that no containers exist for project gentar-s7r1.

## Record

9. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (timestamp = now, local;
   suffix `-r1v2` if the name would collide) with front-matter per
   record.md: runbook `node: /s7-docs-truth/r1-prefix-docs-agree @ <commit>`
   (the steered commit this run executed), stamp, environment (docker
   context, compose version), verdict, findings (empty on PASS),
   teardown: done. Body: the seven-row case table with observed exit
   codes, the exact refusal line for `1gentar`, the eight grep counts
   against the flattened copies, and confirmation the source files were
   not modified (`git status --short` shows no tracked-file changes).
10. Commit `run: /s7/r1-prefix-docs-agree <verdict>`. Do NOT change the
    runbook's `status: orphan` — a steered runbook stays orphan. Push
    to origin.

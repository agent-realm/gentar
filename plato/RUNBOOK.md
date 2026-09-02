---
node: /s7-docs-truth/r5-unchanged-regression
scenario: /s7-docs-truth
status: draft
touches:
  - "git diff f976be1..HEAD (read-only, in this worktree)"
  - "worktree .env (arena: COMPOSE_PROJECT_NAME=gentar-s7r5, GENTAR_NAME_PREFIX=gentar-s7arm, ports 18198/14398)"
  - "docker compose build coordinator; docker compose run --rm coordinator run smoke; docker compose run --rm coordinator ls"
  - "docker compose exec clickhouse clickhouse-client (quickstart SQL)"
  - "bench-host 10.10.10.52: exactly one sbx sandbox, created and destroyed by the run itself"
expect:
  - "git diff f976be1..HEAD --name-only touches NO file outside {README.md, .env.example, coordinator/gentar/config.py} and plato/**"
  - "the coordinator diff is config.py alone; the changed lines are only the ValueError message text; the lines defining _PREFIX_RE and _PREFIX_MAX are byte-identical between f976be1 and HEAD"
  - "the README diff's every hunk lies inside the busy-host section or the two-arenas section; no hunk touches the scenario inventory or its suite-count line"
  - "docker compose run --rm coordinator ls exits 0; its name set equals {basenames of coordinator/scenarios/*.toml} + {smoke, smoke-fail}; every suite name the README inventory table lists appears in the output"
  - "quickstart block green: docker compose run --rm coordinator run smoke exits 0; newest out/ file matches report-gentar-s7arm-*.md; the quickstart SQL returns rows for that run_id including a run.end row with status pass"
stop-conditions:
  - "image build fails or the arena cannot come up -> incomplete"
  - "any diff-scope check finds a change outside the declared set -> FAIL"
  - "ls set mismatch, missing README suite, smoke nonzero, or no report/span rows -> FAIL"
exclusions: "port defaults 18123/14318 are NOT bound (other arenas own them; the defaults are verified textually in r1's doc greps and by the untouched compose file); subject suites (kommander, memhouse) are not run — the claim under test is suite loading and the subjectless quickstart"
---

# r5 — nothing but the message: code unchanged, suites load, quickstart green

Scenario claim: "No code behavior changes beyond the message string:
all s5 blessed behavior unchanged (16 suites load, quickstart green on
defaults)." The s5 blessed tip is f976be1; this runbook proves the s7
diff is docs + one message string, that every shipped suite still
loads, and that the README quickstart block runs green.

## Setup

1. Work in the worktree this runbook lives in (HEAD = this runbook's
   branch; the diff base f976be1 is the s5 tip).
2. `cp .env.example .env` then edit `.env` to set exactly:
   - `COMPOSE_PROJECT_NAME=gentar-s7r5`
   - `GENTAR_NAME_PREFIX=gentar-s7arm`
   - `GENTAR_CLICKHOUSE_HOST_PORT=18198`
   - `GENTAR_OTELCOL_HOST_PORT=14398`
   - `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`
3. `export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"` (the
   quickstart's own line).

## Do — diff scope (code frozen to message-only)

4. `git diff f976be1..HEAD --name-only` — every listed path must match
   `^plato/` OR be one of `README.md`, `.env.example`,
   `coordinator/gentar/config.py`. Anything else -> FAIL (record the
   path).
5. `git diff f976be1..HEAD --stat -- coordinator/` — expect exactly one
   file, `coordinator/gentar/config.py`. Then:
   - `git show f976be1:coordinator/gentar/config.py | grep -e '_PREFIX_RE = ' -e '_PREFIX_MAX = '` and the same for HEAD — the two
     outputs must be byte-identical (record both).
   - `git diff f976be1..HEAD -- coordinator/gentar/config.py` — every
     changed line (leading +/-) lies inside the `raise ValueError(`
     message continuation of `_check_prefix`; record the diff in the run
     file.
6. README hunk confinement: `git diff f976be1..HEAD --unified=0 -- README.md`
   — every `@@` hunk header's new-file line numbers must fall within
   the busy-host paragraph (starts at the line containing `Busy Docker
   host?`) through the end of the two-arenas section (the line
   containing `through exactly this seam`). Compute those two line
   numbers with `grep -n` on README.md and record them with the hunk
   list. `git diff f976be1..HEAD -- README.md | grep -c 'suites today'`
   must be 0.

## Do — suites load

7. `docker compose build coordinator` (must succeed).
8. `docker compose run --rm coordinator ls > /tmp/s7r5-ls.log 2>&1; echo "exit=$?"`
   — expect exit 0.
9. Compare sets (record both):

   ```
   grep -oE '[a-z0-9-]+\.toml' <(ls coordinator/scenarios/) | sed 's/\.toml//' | sort > /tmp/s7r5-toml.txt
   { cat /tmp/s7r5-toml.txt; printf 'smoke\nsmoke-fail\n'; } | sort -u > /tmp/s7r5-expected.txt
   sort /tmp/s7r5-ls.log > /tmp/s7r5-actual.txt
   diff /tmp/s7r5-expected.txt /tmp/s7r5-actual.txt
   ```

   Expect empty diff. Also: every suite name in the README inventory
   table (the rows of the `| Suite |` table) appears in
   /tmp/s7r5-actual.txt — extract them with
   `grep -oE '^\| \`[a-z0-9-]+\`' README.md` and check each.

## Do — quickstart green

10. `docker compose run --rm coordinator run smoke; echo "exit=$?"` —
    expect exit 0 (one sandbox on 10.10.10.52 named gentar-s7arm-<stamp>-<hex>,
    destroyed by the run itself; never `sbx rm` anything).
11. `ls -t out/ | head -3` — newest file matches `^report-gentar-s7arm-`.
    Record its name; extract the run_id (strip `report-` and `.md`).
12. Quickstart SQL:

    ```
    docker compose exec -T clickhouse clickhouse-client --user gentar --password gentar -q \
      "SELECT step, status FROM gentar.spans WHERE run_id = '<run_id>' ORDER BY ts_start"
    ```

    Expect rows including `bench.create` pass, `bench.exec` pass, and a
    `run.end` row with status `pass`. Paste the rows into the run record.

## Teardown (record as final step)

13. `docker compose down -v`; confirm no containers remain for project
    gentar-s7r5 and `docker compose ls` no longer lists it.

## Record

14. Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>-r5-regression.md` with
    front-matter per record.md. Body: the diff-scope evidence (paths,
    config.py diff, regex/max lines both revs, README hunk lines),
    the ls set comparison, report filename, and the SQL rows.
15. Commit `run: /s7/r5-unchanged-regression <verdict>`, flip RUNBOOK.md
    `status: draft` -> `status: frozen`, commit
    `runbook: /s7-docs-truth/r5-unchanged-regression frozen (first run recorded)`.
    Push both to origin.

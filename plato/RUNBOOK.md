---
node: /s6-scaffold-honest/r1-exit2-net
scenario: /s6-scaffold-honest
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=gentar-s6arm-r1, GENTAR_CLICKHOUSE_HOST_PORT=18181, GENTAR_NAME_PREFIX=gentar-s6arm-r1)"
  - "docker compose build coordinator; docker compose run --rm coordinator ls / run against scratch extra dirs mounted -v <dir>:/extra:ro with -e GENTAR_SCENARIOS_DIR=/extra"
  - "scratch dirs under /tmp/gentar-s6-r1-exit2-net (untracked, torn down)"
expect:
  - "a suite with `bench = \"bogus\"` makes `coordinator ls` exit 2 with `error: /extra/bogus-tier.toml: scenario.bench must be 'sbx' or 'tart', got 'bogus'` — the file, the key, and the legal values, all in one line"
  - "`coordinator run bogus-tier` exits 2 with the SAME named error (`Error:` prefix), and neither output contains `Traceback (most recent call last)`"
  - "a recursion-bomb TOML (20000 nested arrays) makes `ls` exit 2 with a named error carrying `TOML nests too deeply to parse` and the file path, zero traceback matches"
  - "a directory named dirbomb.toml inside the scenarios dir makes `ls` exit 2 with a named error carrying `is a directory, not a scenario file` and the path, zero traceback matches"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18181 or 14381 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No bench-host is contacted and no sandbox is created (all three refusals happen at load time, before any bench exists). The s4 round's renamed-key / malformed-TOML cases are NOT re-probed — this instrument covers only the three NEW exit-2 holes: off-enum bench tier, recursion bomb, *.toml directory. The budget, stub and assert guards are not exercised. No ClickHouse or OTLP content is checked."
---

# r1 — exit-2 net: bogus bench tier, recursion bomb, *.toml directory

Deterministic instrument for the scenario's first and second
expectations: `bench = "bogus"` refuses at `ls` AND at `run` with exit 2
naming the file, key, and legal values; a recursion-bomb TOML and a
directory named `*.toml` both refuse exit 2 with named errors. No
traceback anywhere — the exit-2 net has no holes.

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s6-scaffold-honest--r1-exit2-net`) is the compose project
root. It already carries an untracked `.env` (one arena, one .env). Five
sibling agents own ports 18180/18182/18183/18184/18185/18186 and their
143xx neighbours — never touch them. The compose file hardcodes
otelcol's host publish at 4318, so every compose invocation below
carries a ports override pinning it to 127.0.0.1:14381. Deadline: 30
minutes wall clock from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s6-r1-exit2-net
   rm -rf "$ENV" && mkdir -p "$ENV/extra-tier" "$ENV/extra-bomb" "$ENV/extra-dirbomb"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=gentar-s6arm-r1
   #   GENTAR_CLICKHOUSE_HOST_PORT=18181
   #   GENTAR_NAME_PREFIX=gentar-s6arm-r1
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14381:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18181 -sTCP:LISTEN; lsof -nP -iTCP:14381 -sTCP:LISTEN
   ```

   Expected: `.env` carries the three lines (a missing or different
   COMPOSE_PROJECT_NAME / port / prefix is a stop condition — record
   verbatim); no output from either lsof.

2. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   ```

   Expected: `build-exit=0`.

3. Build the three malformed dirs (one bad artifact each — a dir is
   load_dir-atomic, so one poisoned file must be the only file in its
   dir):

   ```bash
   cat > "$ENV/extra-tier/bogus-tier.toml" <<'TOML'
   [scenario]
   name = "bogus-tier"
   bench = "bogus"

   [oracle]
   steps = ["true"]
   TOML
   python3 - <<'PY'
   import pathlib
   # Recursion bomb: 20000 nested arrays. tomllib is a recursive-descent
   # parser; this crosses the interpreter recursion limit and must surface
   # as a NAMED config error, never a raw RecursionError traceback.
   pathlib.Path("/tmp/gentar-s6-r1-exit2-net/extra-bomb/bomb.toml").write_text(
       "x = " + "[" * 20000 + "]" * 20000 + "\n")
   pathlib.Path("/tmp/gentar-s6-r1-exit2-net/extra-dirbomb/dirbomb.toml").mkdir()
   print("substrate-ok")
   PY
   /bin/ls -la "$ENV/extra-bomb" "$ENV/extra-dirbomb"
   ```

   Expected: prints `substrate-ok`; `extra-bomb/` holds one file
   `bomb.toml`; `extra-dirbomb/dirbomb.toml` is a directory.

4. Bogus tier refuses at LS:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-tier:/extra:ro" \
     coordinator ls >"$ENV/ls-tier.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'scenario.bench' "$ENV/ls-tier.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-tier.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line byte-equal to
   `error: /extra/bogus-tier.toml: scenario.bench must be 'sbx' or 'tart', got 'bogus'`
   (file + key + legal values); `tb-exit=1` (zero traceback matches).

5. Bogus tier refuses at RUN:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-tier:/extra:ro" \
     coordinator run bogus-tier >"$ENV/run-tier.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'scenario.bench' "$ENV/run-tier.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run-tier.txt"; echo "tb-exit=$?"
   ```

   Expected: `run-exit=2`; the grep prints a line carrying
   `/extra/bogus-tier.toml: scenario.bench must be 'sbx' or 'tart', got 'bogus'`;
   `tb-exit=1`.

6. Recursion bomb refuses at LS:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-bomb:/extra:ro" \
     coordinator ls >"$ENV/ls-bomb.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'TOML nests too deeply' "$ENV/ls-bomb.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-bomb.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line carrying
   `/extra/bomb.toml: TOML nests too deeply to parse` (named error with
   the file); `tb-exit=1`.

7. Directory named *.toml refuses at LS:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-dirbomb:/extra:ro" \
     coordinator ls >"$ENV/ls-dir.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'is a directory' "$ENV/ls-dir.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-dir.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line carrying
   `/extra/dirbomb.toml: is a directory, not a scenario file`;
   `tb-exit=1`.

8. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf "$ENV"
   git status --porcelain   # expect no output; .env is ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack + no
bench-host contact) on THIS branch and commit
`run: /s6/r1-exit2-net <verdict>`. Verdicts: PASS / PASS WITH FINDINGS /
FAIL; timeout, crash, or never-ran is `incomplete: true` — never FAIL.
The known OrbStack warning `secrets 'uid', 'gid' and 'mode' are not
supported` is known noise, not a finding. Teardown result goes in the
record's teardown field.

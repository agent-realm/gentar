---
node: /s4-scaffold-hardened/r2-schema-strict
scenario: /s4-scaffold-hardened
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=plato-s4-arm, GENTAR_CLICKHOUSE_HOST_PORT=18140, GENTAR_NAME_PREFIX=gentar-s4)"
  - "docker compose build coordinator; docker compose run --rm coordinator subject init … --dir /out/scaffold"
  - "scratch extra dirs under /tmp mounted -v <dir>:/extra:ro with -e GENTAR_SCENARIOS_DIR=/extra"
  - "docker compose run --rm … coordinator ls / run demo-subject-install against mutated TOML"
  - "out/scaffold/ and scratch dirs (untracked, torn down)"
expect:
  - "a probe key renamed off-schema (`contains` → `substring` in verify.commands[0]) makes `coordinator ls` exit 2 with a named error carrying `unknown key(s) substring in verify.commands[0]` and `legal keys: command, contains`, and zero traceback matches"
  - "`coordinator run demo-subject-install` against the same dir exits 2 with the same named error, zero traceback matches"
  - "a malformed-TOML file in its own extra dir makes `ls` exit 2 with an error carrying `malformed TOML` and the file's path, and `run` exits 2 the same way — zero traceback matches in both"
  - "the UNmutated emitted scaffold in a clean extra dir still loads: `ls` exits 0 and lists demo-subject-install"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18140 or 14340 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No bench-host is contacted and no sandbox is created (off-schema loads fail before any bench exists; the loader needs no bench). The assert-nothing guard is r1's instrument; the plain-TODO stub refusal was s3/r2's. Off-type tables (`verify = \"boom\"`, `steps = 5`), empty-string probes, and the 64-char subject-name cap are covered by the same code path but are NOT separately probed here — the renamed-key and malformed-TOML cases are this instrument's whole scope. No ClickHouse or OTLP content is checked."
---

# r2 — strict schema: a renamed probe key is a named error, never a silent non-assertion

Deterministic instrument for the scenario's second expectation: a probe
key renamed to anything off-schema fails to load with a named error —
`ls` and `run` both exit 2 clean, no traceback — and malformed TOML is
likewise a named error carrying the file, never a traceback.

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s4-scaffold-hardened--r2-schema-strict`) is the compose
project root. It already carries an untracked `.env` (one arena, one
.env) and a sibling agent owns ports 18150/14350 — never touch them. The
compose file hardcodes otelcol's host publish at 4318, so every compose
invocation below carries a ports override pinning it to 127.0.0.1:14340.
Deadline: 30 minutes wall clock from step 1.

## Steps

1. Scratch env dirs and compose wiring:

   ```bash
   ENV=/tmp/gentar-s4-r2-schema-strict
   rm -rf "$ENV" && mkdir -p "$ENV/extra-renamed" "$ENV/extra-malformed" "$ENV/extra-clean"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=plato-s4-arm
   #   GENTAR_CLICKHOUSE_HOST_PORT=18140
   #   GENTAR_NAME_PREFIX=gentar-s4
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14340:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18140 -sTCP:LISTEN; lsof -nP -iTCP:14340 -sTCP:LISTEN
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

3. Emit the scaffold (the mutation substrate):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   ls out/scaffold/
   ```

   Expected: `emit-exit=0`; `out/scaffold/` contains exactly
   `demo-subject-install.toml` and `gentar.yml`.

4. Mutation — renamed probe key (`contains` → `substring`), and the
   malformed-TOML twin, and the clean control copy:

   ```bash
   cp out/scaffold/demo-subject-install.toml "$ENV/extra-renamed/"
   cp out/scaffold/demo-subject-install.toml "$ENV/extra-malformed/"
   cp out/scaffold/demo-subject-install.toml "$ENV/extra-clean/"
   python3 - <<'PY'
   import pathlib
   base = pathlib.Path("/tmp/gentar-s4-r2-schema-strict")

   renamed = base / "extra-renamed/demo-subject-install.toml"
   t = renamed.read_text()
   old = 'contains = "TODO"      # substring its output must carry'
   new = 'substring = "TODO"'
   assert t.count(old) == 1
   t = t.replace(old, new)
   renamed.write_text(t)
   print("renamed-ok")

   mal = base / "extra-malformed/demo-subject-install.toml"
   t = mal.read_text()
   assert t.count("[scenario]") == 1
   t = t.replace("[scenario]", "[scenario", 1)
   mal.write_text(t)
   print("malformed-ok")
   PY
   ```

   Expected: prints `renamed-ok` then `malformed-ok`.

5. Renamed key — `ls` refuses exit 2 with the named error:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-renamed:/extra:ro" \
     coordinator ls >"$ENV/ls-renamed.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'unknown key' "$ENV/ls-renamed.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-renamed.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line containing
   `unknown key(s) substring in verify.commands[0]` and
   `legal keys: command, contains`; `tb-exit=1`.

6. Renamed key — `run` refuses exit 2 the same way:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-renamed:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/run-renamed.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'unknown key' "$ENV/run-renamed.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run-renamed.txt"; echo "tb-exit=$?"
   ```

   Expected: `run-exit=2`; the same named error line as step 5;
   `tb-exit=1`.

7. Malformed TOML — `ls` and `run` refuse exit 2 naming the file:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-malformed:/extra:ro" \
     coordinator ls >"$ENV/ls-malformed.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'malformed TOML' "$ENV/ls-malformed.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-malformed.txt"; echo "tb-ls-exit=$?"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-malformed:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/run-malformed.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'malformed TOML' "$ENV/run-malformed.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run-malformed.txt"; echo "tb-run-exit=$?"
   ```

   Expected: `ls-exit=2` and `run-exit=2`; each malformed-grep prints a
   line containing `malformed TOML` and the path
   `/extra/demo-subject-install.toml`; both tb-exits are `1`.

8. Clean control — the unmutated scaffold still loads (strictness did
   not outlaw a legal key):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-clean:/extra:ro" \
     coordinator ls >"$ENV/ls-clean.txt" 2>&1
   echo "ls-exit=$?"
   grep -c '^demo-subject-install$' "$ENV/ls-clean.txt"
   ```

   Expected: `ls-exit=0`, then `1`.

9. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/scaffold "$ENV"
   git status --porcelain   # expect no output; .env and out/ are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack, no
bench-host contact) on THIS branch and commit
`run: /s4/r2-schema-strict <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

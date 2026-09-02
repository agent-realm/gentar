---
node: /s6-scaffold-honest/r2-vacuous-driver
scenario: /s6-scaffold-honest
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=gentar-s6arm-r2, GENTAR_CLICKHOUSE_HOST_PORT=18182, GENTAR_NAME_PREFIX=gentar-s6arm-r2)"
  - "docker compose build coordinator; docker compose run --rm coordinator ls / run with scratch extra dir mounted -v <dir>:/extra:ro, -e GENTAR_SCENARIOS_DIR=/extra"
  - "bench-host 10.10.10.52: ONE sbx sandbox created and destroyed by the coordinator (prefix gentar-s6arm-r2-); ssh polat@… 'sbx ls' snapshots, own-prefix grep only"
  - "scratch dir under /tmp/gentar-s6-r2-vacuous-driver; out/ run reports (untracked, torn down)"
expect:
  - "a driver suite with `command = \"true\"`, zero turns and zero verify probes still LOADS: `ls` exits 0 and lists `true-driver`"
  - "`run true-driver` refuses exit 2 with the assert-guard message carrying `declares no verify probes and no driven turns` and `refusing before any bench exists`, zero traceback matches, and a fresh report-refused-true-driver-*.md in out/"
  - "the same suite shape with ONE answer turn runs GREEN on the sbx bench: `run true-driver-1turn` exits 0 with `driver ok: 1 turns`"
  - "bench-host `sbx ls` shows zero gentar-s6arm-r2- sandboxes before the run and zero after the coordinator process exits"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "ssh to polat@10.10.10.52 fails at step 2 — environment trouble, incomplete, stop"
  - "host ports 18182 or 14382 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "the green run leaves a gentar-s6arm-r2- sandbox on the bench-host after process exit — record the listing verbatim; attempt exactly one manual 'sbx rm --force <that exact name>' (own-prefix sandbox only — never a foreign name), record the attempt; then verdict FAIL"
  - "wall clock exceeds 45 minutes — record incomplete, run teardown, stop"
exclusions: "Only the driver-shaped vacuous case is probed; the oracle-shaped one (whole verify section deleted) was s4/r1's instrument. The stub guard, budget guard and credential guard are not exercised. The turn mechanics themselves (pick/abort/danger gate) are the scripted suites' business, not this instrument's — one answer turn is the minimum that makes turns the verdict evidence. No ClickHouse or OTLP content is checked."
---

# r2 — vacuous driver: zero turns + zero probes refuses; one turn runs

Deterministic instrument for the scenario's third expectation: a driver
suite with zero turns and zero probes (`command = "true"` — the exact
shape that ran green through the s4 wholesale driver exemption) now
refuses with the assert-guard message, and the same suite with ONE turn
runs green on a real bench. Turns ARE verdict evidence; an empty turns
list is not.

Environment: this Mac, OrbStack docker context `orbstack`. Bench-host
10.10.10.52, ssh user polat, key `$HOME/.ssh/id_ed25519`. Your worktree
(branch `plato/s6-scaffold-honest--r2-vacuous-driver`) is the compose
project root. It already carries an untracked `.env`;
GENTAR_NAME_PREFIX=gentar-s6arm-r2 stamps every sandbox this runbook
creates. Five sibling agents own ports 18180/18181/18183/18184/18185/
18186 and their 143xx neighbours — never touch them, and never touch a
foreign sandbox on the bench-host. The compose file hardcodes otelcol's
host publish at 4318, so every compose invocation below carries a ports
override pinning it to 127.0.0.1:14382. Deadline: 45 minutes wall clock
from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s6-r2-vacuous-driver
   rm -rf "$ENV" && mkdir -p "$ENV/extra"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=gentar-s6arm-r2
   #   GENTAR_CLICKHOUSE_HOST_PORT=18182
   #   GENTAR_NAME_PREFIX=gentar-s6arm-r2
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14382:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18182 -sTCP:LISTEN; lsof -nP -iTCP:14382 -sTCP:LISTEN
   ```

   Expected: `.env` carries the three lines (a missing or different
   COMPOSE_PROJECT_NAME / port / prefix is a stop condition — record
   verbatim); no output from either lsof.

2. Bench-host BEFORE (read-only; foreign sandboxes recorded, never
   touched):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-before.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s6arm-r2-' "$ENV/sbx-before.txt"; echo "before-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `before-grep-exit=1` (zero own-prefix
   sandboxes). Foreign lines, if any, are recorded verbatim in the run
   record — not yours, not findings.

3. Both suites into the extra dir — the SAME shape twice, zero turns
   vs one turn:

   ```bash
   cat > "$ENV/extra/true-driver.toml" <<'TOML'
   [scenario]
   name = "true-driver"

   [driver]
   command = "true"
   TOML
   cat > "$ENV/extra/true-driver-1turn.toml" <<'TOML'
   [scenario]
   name = "true-driver-1turn"

   [driver]
   command = "echo ready-for-turn; read line; echo done-turn"
   turns = [
     { type = "answer", prompt = "ready-for-turn", send = "hello" },
   ]
   TOML
   /bin/ls "$ENV/extra"
   ```

   Expected: exactly `true-driver-1turn.toml` and `true-driver.toml`.

4. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   ```

   Expected: `build-exit=0`.

5. The zero-turn suite LOADS (the guard is a run-time refusal, not a
   load error):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator ls > "$ENV/ls.txt" 2>&1
   echo "ls-exit=$?"
   grep -c '^true-driver$' "$ENV/ls.txt"
   grep -c '^true-driver-1turn$' "$ENV/ls.txt"
   ```

   Expected: `ls-exit=0`, then `1`, then `1`.

6. RUN the zero-turn suite — refuses, exit 2, before any bench exists:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator run true-driver >"$ENV/run-vacuous.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'assert guard' "$ENV/run-vacuous.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run-vacuous.txt"; echo "tb-exit=$?"
   ls -t out/ | head -3
   ```

   Expected: `run-exit=2`; the grep prints a line containing
   `assert guard: scenario 'true-driver' declares no verify probes and no driven turns`
   and the words `refusing before any bench exists`; `tb-exit=1`; a
   fresh `report-refused-true-driver-*.md` appears among the newest
   files in `out/`.

7. Bench-host still clean after the refusal (no sandbox was created):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-mid.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s6arm-r2-' "$ENV/sbx-mid.txt"; echo "mid-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `mid-grep-exit=1`.

8. RUN the one-turn suite — green on a real bench:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator run true-driver-1turn >"$ENV/run-1turn.txt" 2>&1
   echo "run-exit=$?"
   grep -a 'driver ok\|FAIL\|Error:' "$ENV/run-1turn.txt" | head -3
   ls -t out/ | head -2
   ```

   Expected: `run-exit=0`; the grep prints `driver ok: 1 turns`; the
   newest file in `out/` is a `report-gentar-s6arm-r2-*.md`.

9. Bench-host AFTER — the run's sandbox settled before/with process
   exit:

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-after.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s6arm-r2-' "$ENV/sbx-after.txt"; echo "after-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `after-grep-exit=1`.

10. Teardown (every exit path, including after a stop condition):

    ```bash
    docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
    rm -rf out/report-* "$ENV"
    git status --porcelain   # expect no output; .env and out/ are ignored
    ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack +
bench-host 10.10.10.52 sbx tier + one sandbox) on THIS branch and commit
`run: /s6/r2-vacuous-driver <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

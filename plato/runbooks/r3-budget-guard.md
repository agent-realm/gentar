---
node: /s6-scaffold-honest/r3-budget-guard
scenario: /s6-scaffold-honest
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=gentar-s6arm-r3, GENTAR_CLICKHOUSE_HOST_PORT=18183, GENTAR_NAME_PREFIX=gentar-s6arm-r3)"
  - "docker compose build coordinator; docker compose run --rm coordinator ls / run with scratch extra dir mounted -v <dir>:/extra:ro, -e GENTAR_SCENARIOS_DIR=/extra, -e GENTAR_BUDGET_CAP=100"
  - "scratch dirs under /tmp/gentar-s6-r3-budget-guard (untracked, torn down)"
expect:
  - "the suite `tokens = 0, simulate_spend = 500` (one verify probe, so it is not the assert guard that fires) LOADS: `ls` exits 0 and lists `budget-over`"
  - "`run budget-over` with GENTAR_BUDGET_CAP=100 refuses exit 2 with `budget guard: run would spend 500 units, 0 already burned, cap 100`, zero traceback matches, and a fresh report-refused-budget-over-*.md in out/"
  - "`tokens = -5` refuses AT LOAD: `ls` exits 2 with `/extra/budget-neg-tokens.toml: [budget].tokens must be >= 0, got -5`"
  - "`simulate_spend = -1` refuses AT LOAD: `ls` exits 2 with `/extra/budget-neg-spend.toml: [budget].simulate_spend must be >= 0, got -1`"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18183 or 14383 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No bench-host is contacted and no sandbox is created (the refusal happens before any bench exists). The s4 guard's declared-tokens-only behavior is not re-probed; this instrument covers only the s6 additions — simulated spend counts, negatives refuse at load. Positive spend accounting after a PASSING run (budget.spend spans) is not checked. The stub/assert guards are not exercised beyond keeping the suite loadable/runnable. No ClickHouse content is queried directly; the guard's already-burned read is best-effort and reads 0 on a fresh arena."
---

# r3 — budget guard: simulated spend counts, negatives refuse at load

Deterministic instrument for the scenario's fourth expectation: a suite
declaring `tokens = 0` with `simulate_spend = 500` against
`GENTAR_BUDGET_CAP=100` refuses at the budget guard (the s4 guard
counted declared tokens only and ran green recording 500 units over),
and negative budget values refuse at load.

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s6-scaffold-honest--r3-budget-guard`) is the compose
project root. It already carries an untracked `.env`. Five sibling
agents own ports 18180/18181/18182/18184/18185/18186 and their 143xx
neighbours — never touch them. The compose file hardcodes otelcol's
host publish at 4318, so every compose invocation below carries a ports
override pinning it to 127.0.0.1:14383. Deadline: 30 minutes wall clock
from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s6-r3-budget-guard
   rm -rf "$ENV" && mkdir -p "$ENV/extra" "$ENV/extra-neg-tokens" "$ENV/extra-neg-spend"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=gentar-s6arm-r3
   #   GENTAR_CLICKHOUSE_HOST_PORT=18183
   #   GENTAR_NAME_PREFIX=gentar-s6arm-r3
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14383:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18183 -sTCP:LISTEN; lsof -nP -iTCP:14383 -sTCP:LISTEN
   ```

   Expected: `.env` carries the three lines (a missing or different
   COMPOSE_PROJECT_NAME / port / prefix is a stop condition — record
   verbatim); no output from either lsof.

2. The three suites (one per dir — load_dir is dir-atomic, so each
   poisoned file sits alone):

   ```bash
   cat > "$ENV/extra/budget-over.toml" <<'TOML'
   [scenario]
   name = "budget-over"

   [oracle]
   steps = ["true"]

   [budget]
   tokens = 0
   simulate_spend = 500

   [[verify.commands]]
   command = "true"
   TOML
   cat > "$ENV/extra-neg-tokens/budget-neg-tokens.toml" <<'TOML'
   [scenario]
   name = "budget-neg-tokens"

   [oracle]
   steps = ["true"]

   [budget]
   tokens = -5

   [[verify.commands]]
   command = "true"
   TOML
   cat > "$ENV/extra-neg-spend/budget-neg-spend.toml" <<'TOML'
   [scenario]
   name = "budget-neg-spend"

   [oracle]
   steps = ["true"]

   [budget]
   tokens = 0
   simulate_spend = -1

   [[verify.commands]]
   command = "true"
   TOML
   /bin/ls "$ENV/extra" "$ENV/extra-neg-tokens" "$ENV/extra-neg-spend"
   ```

   Expected: each dir holds exactly its one `.toml` file.

3. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   ```

   Expected: `build-exit=0`.

4. The over-cap suite LOADS (the guard is a run-time refusal, not a
   load error):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator ls > "$ENV/ls.txt" 2>&1
   echo "ls-exit=$?"
   grep -c '^budget-over$' "$ENV/ls.txt"
   ```

   Expected: `ls-exit=0`, then `1`.

5. RUN with the cap — refuses at the budget guard, before any bench
   exists:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     -e GENTAR_BUDGET_CAP=100 \
     coordinator run budget-over >"$ENV/run-over.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'budget guard' "$ENV/run-over.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run-over.txt"; echo "tb-exit=$?"
   ls -t out/ | head -3
   ```

   Expected: `run-exit=2`; the grep prints a line byte-equal to
   `Error: budget guard: run would spend 500 units, 0 already burned, cap 100`
   (500 = max(declared 0, simulated 500), not the declared 0 the s4
   guard would have counted); `tb-exit=1`; a fresh
   `report-refused-budget-over-*.md` appears among the newest files in
   `out/`.

6. Negative tokens refuse AT LOAD:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-neg-tokens:/extra:ro" \
     coordinator ls >"$ENV/ls-neg-tokens.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'must be >= 0' "$ENV/ls-neg-tokens.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-neg-tokens.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line byte-equal to
   `error: /extra/budget-neg-tokens.toml: [budget].tokens must be >= 0, got -5`;
   `tb-exit=1`.

7. Negative simulate_spend refuses AT LOAD:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-neg-spend:/extra:ro" \
     coordinator ls >"$ENV/ls-neg-spend.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'must be >= 0' "$ENV/ls-neg-spend.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-neg-spend.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line byte-equal to
   `error: /extra/budget-neg-spend.toml: [budget].simulate_spend must be >= 0, got -1`;
   `tb-exit=1`.

8. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/report-* "$ENV"
   git status --porcelain   # expect no output; .env and out/ are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack + no
bench-host contact) on THIS branch and commit
`run: /s6/r3-budget-guard <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

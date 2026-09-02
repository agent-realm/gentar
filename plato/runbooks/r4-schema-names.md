---
node: /s6-scaffold-honest/r4-schema-names
scenario: /s6-scaffold-honest
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=gentar-s6arm-r4, GENTAR_CLICKHOUSE_HOST_PORT=18184, GENTAR_NAME_PREFIX=gentar-s6arm-r4)"
  - "docker compose build coordinator; docker compose run --rm coordinator ls / run smoke with scratch extra dirs mounted -v <dir>:/extra:ro, -e GENTAR_SCENARIOS_DIR=/extra"
  - "scratch dirs under /tmp/gentar-s6-r4-schema-names (untracked, torn down)"
expect:
  - "`credentials = \"ANTHROPIC_API_KEY\"` (bare string) refuses AT LOAD: `ls` exits 2 with a named error carrying `scenario.credentials must be a LIST of env var names`, `credentials = [\"ANTHROPIC_API_KEY\"]`, and `(got str)`, plus the file path"
  - "`name = \"\"` refuses AT LOAD: `ls` exits 2 with a named error carrying `scenario.name must be a non-empty string (empty names register as ghosts)`"
  - "two files in one dir declaring `name = \"twin\"` refuse AT LOAD: `ls` exits 2 with a named error carrying `duplicate scenario name 'twin' (also declared by /extra/dup-a.toml)` — BOTH files named"
  - "a user `smoke.toml` beside the builtin `smoke` is a LOUD collision: `ls` exits 0 (the dir itself is legal), but `run smoke` exits 2 with `scenario name 'smoke' collides: builtin AND a suite in /extra — rename one`"
  - "zero `Traceback (most recent call last)` matches in every captured output of this runbook"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18184 or 14384 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No bench-host is contacted and no sandbox is created (every refusal happens at load or resolve time, before any bench exists — the collision case refuses before the builtin `smoke` could create one). The s4 schema round (off-type tables, renamed probe keys, empty probes, 64-char name cap) is not re-probed. Off-type LIST entries (credentials = [5]) and the empty-name-when-defaulted case are covered by the same code paths but not separately probed. No ClickHouse or OTLP content is checked."
---

# r4 — schema completion: credentials type, ghost name, duplicates, builtin collision

Deterministic instrument for the scenario's fifth expectation: the four
schema holes the d1-tweaker drill found — a bare-string `credentials`
spelling its letters as env-var names, an empty `name` registering a
ghost suite, duplicate names silently shadowing within a dir, and a user
TOML silently losing to a builtin — are all loud, named, exit-2 errors.

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s6-scaffold-honest--r4-schema-names`) is the compose
project root. It already carries an untracked `.env`. Five sibling
agents own ports 18180/18181/18182/18183/18185/18186 and their 143xx
neighbours — never touch them. The compose file hardcodes otelcol's
host publish at 4318, so every compose invocation below carries a ports
override pinning it to 127.0.0.1:14384. Deadline: 30 minutes wall clock
from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s6-r4-schema-names
   rm -rf "$ENV" && mkdir -p "$ENV/extra-cred" "$ENV/extra-ghost" "$ENV/extra-dup" "$ENV/extra-collide"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=gentar-s6arm-r4
   #   GENTAR_CLICKHOUSE_HOST_PORT=18184
   #   GENTAR_NAME_PREFIX=gentar-s6arm-r4
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14384:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18184 -sTCP:LISTEN; lsof -nP -iTCP:14384 -sTCP:LISTEN
   ```

   Expected: `.env` carries the three lines (a missing or different
   COMPOSE_PROJECT_NAME / port / prefix is a stop condition — record
   verbatim); no output from either lsof.

2. The four substrates (one dir each — load_dir is dir-atomic):

   ```bash
   cat > "$ENV/extra-cred/cred-string.toml" <<'TOML'
   [scenario]
   name = "cred-string"
   credentials = "ANTHROPIC_API_KEY"

   [oracle]
   steps = ["true"]
   TOML
   cat > "$ENV/extra-ghost/ghost.toml" <<'TOML'
   [scenario]
   name = ""

   [oracle]
   steps = ["true"]
   TOML
   cat > "$ENV/extra-dup/dup-a.toml" <<'TOML'
   [scenario]
   name = "twin"

   [oracle]
   steps = ["true"]
   TOML
   cp "$ENV/extra-dup/dup-a.toml" "$ENV/extra-dup/dup-b.toml"
   cat > "$ENV/extra-collide/smoke.toml" <<'TOML'
   [scenario]
   name = "smoke"

   [oracle]
   steps = ["true"]
   TOML
   /bin/ls "$ENV/extra-cred" "$ENV/extra-ghost" "$ENV/extra-dup" "$ENV/extra-collide"
   ```

   Expected: `cred-string.toml`; `ghost.toml`; `dup-a.toml` and
   `dup-b.toml`; `smoke.toml`.

3. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   ```

   Expected: `build-exit=0`.

4. Bare-string credentials refuse AT LOAD:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-cred:/extra:ro" \
     coordinator ls >"$ENV/ls-cred.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'credentials must be a LIST' "$ENV/ls-cred.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-cred.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line containing
   `/extra/cred-string.toml: scenario.credentials must be a LIST of env var names, e.g. credentials = ["ANTHROPIC_API_KEY"] (got str)`
   — file, key, the list form to use, and the offending type; `tb-exit=1`.

5. Empty name refuses AT LOAD (no ghost registered):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-ghost:/extra:ro" \
     coordinator ls >"$ENV/ls-ghost.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'non-empty string' "$ENV/ls-ghost.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-ghost.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line byte-equal to
   `error: /extra/ghost.toml: scenario.name must be a non-empty string (empty names register as ghosts)`;
   `tb-exit=1`.

6. Duplicate names in one dir refuse AT LOAD, naming BOTH files:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-dup:/extra:ro" \
     coordinator ls >"$ENV/ls-dup.txt" 2>&1
   echo "ls-exit=$?"
   grep -m1 'duplicate scenario name' "$ENV/ls-dup.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/ls-dup.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=2`; the grep prints a line byte-equal to
   `error: /extra/dup-b.toml: duplicate scenario name 'twin' (also declared by /extra/dup-a.toml)`
   (sorted glob loads dup-a first; dup-b raises — both paths present);
   `tb-exit=1`.

7. The collision dir itself is LEGAL — `ls` exits 0 and lists `smoke`
   once (the collision is loud at RUN, not at list):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-collide:/extra:ro" \
     coordinator ls >"$ENV/ls-collide.txt" 2>&1
   echo "ls-exit=$?"
   grep -c '^smoke$' "$ENV/ls-collide.txt"
   ```

   Expected: `ls-exit=0`, then `1`.

8. RUN `smoke` with the user suite mounted — LOUD collision, no silent
   builtin precedence, no bench created:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-collide:/extra:ro" \
     coordinator run smoke >"$ENV/run-collide.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'collides' "$ENV/run-collide.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run-collide.txt"; echo "tb-exit=$?"
   ```

   Expected: `run-exit=2`; the grep prints a line containing
   `Error: scenario name 'smoke' collides: builtin AND a suite in /extra — rename one`;
   `tb-exit=1`. (The builtin `smoke` creates no sandbox here — the
   collision refuses in resolve, before any bench exists.)

9. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf "$ENV"
   git status --porcelain   # expect no output; .env is ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack + no
bench-host contact) on THIS branch and commit
`run: /s6/r4-schema-names <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

---
node: /s4-scaffold-hardened/r5-legacy-sixteen
scenario: /s4-scaffold-hardened
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=plato-s4-arm, GENTAR_CLICKHOUSE_HOST_PORT=18140, GENTAR_NAME_PREFIX=gentar-s4)"
  - "docker compose build coordinator; docker compose run --rm coordinator ls (no extra scenarios dir)"
expect:
  - "`coordinator ls` exits 0 and prints exactly 18 lines, byte-for-byte the frozen list below: the 16 existing suites plus the builtins smoke and smoke-fail, sorted"
  - "the strict v1 loader (which constructs every suite in the image's /app/scenarios at load time) rejected none of the 16 — no legal key became illegal"
  - "stderr of the ls invocation carries no error line (compose's own warnings are noise; record them verbatim but they are not findings)"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18140 or 14340 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No suite is RUN (loading is the claim; the 16 suites' verdicts are their owners' business, and running them would contact real bench hosts). No extra scenarios dir is mounted — only the image's baked /app/scenarios is exercised. No bench-host contact, no sandbox. Nothing is emitted with subject init."
---

# r5 — legacy sixteen: the 16 existing suites load unchanged under the strict schema

Deterministic instrument for the scenario's fifth expectation: the 16
existing suites load unchanged — no legal key became illegal when the
schema went strict. `coordinator ls` constructs a TomlScenario for every
TOML in the image's /app/scenarios (the loader validates fully at
construction), so the listing IS the load check.

The frozen expected output, byte-for-byte (18 lines = 16 suites + the
builtins `smoke` and `smoke-fail`, sorted):

```
agent-smoke
bench-template-verify
budget-sim
claude-playbooks-install
claude-playbooks-install-macos
docs-honesty-gentar
docs-honesty-kommander
kommander-install
kommander-task-lock
kommander-update
memhouse-house
memhouse-install
otlp-selfreport
scripted-danger
scripted-onboarding
smoke
smoke-fail
smoke-macos
```

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s4-scaffold-hardened--r5-legacy-sixteen`) is the compose
project root. It already carries an untracked `.env` (one arena, one
.env) and a sibling agent owns ports 18150/14350 — never touch them. The
compose file hardcodes otelcol's host publish at 4318, so every compose
invocation below carries a ports override pinning it to 127.0.0.1:14340.
Deadline: 30 minutes wall clock from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s4-r5-legacy-sixteen
   rm -rf "$ENV" && mkdir -p "$ENV"
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

3. The load check — list every suite the image bakes, no extras:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator ls >"$ENV/ls.txt" 2>"$ENV/ls.err"
   echo "ls-exit=$?"
   wc -l < "$ENV/ls.txt"
   cat > "$ENV/expected.txt" <<'EOF'
agent-smoke
bench-template-verify
budget-sim
claude-playbooks-install
claude-playbooks-install-macos
docs-honesty-gentar
docs-honesty-kommander
kommander-install
kommander-task-lock
kommander-update
memhouse-house
memhouse-install
otlp-selfreport
scripted-danger
scripted-onboarding
smoke
smoke-fail
smoke-macos
EOF
   diff "$ENV/expected.txt" "$ENV/ls.txt"; echo "diff-exit=$?"
   ```

   Expected: `ls-exit=0`; `wc -l` prints `18`; `diff-exit=0` with no
   diff output.

4. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf "$ENV"
   git status --porcelain   # expect no output; .env and out/ are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack, no
bench-host contact) on THIS branch and commit
`run: /s4/r5-legacy-sixteen <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

---
node: /s6-scaffold-honest/r6-legacy-sixteen
scenario: /s6-scaffold-honest
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=gentar-s6arm-r6, GENTAR_CLICKHOUSE_HOST_PORT=18186, GENTAR_NAME_PREFIX=gentar-s6arm-r6)"
  - "docker compose build coordinator; docker compose run --rm coordinator ls (no extra scenarios dir)"
expect:
  - "`coordinator ls` exits 0 and prints exactly 18 lines, byte-for-byte the frozen list below: the 16 existing suites plus the builtins smoke and smoke-fail, sorted"
  - "the s6 loader (bench-tier enum, credentials list, non-empty name, non-negative budget, duplicate-name refusal — all constructed at load time) rejected none of the 16 — no legal key or value became illegal"
  - "the invocation's output carries no `Traceback (most recent call last)` match (compose's own warnings are noise; record them verbatim but they are not findings)"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18186 or 14386 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No suite is RUN (loading is the claim; the 16 suites' verdicts are their owners' business, and running them would contact real bench hosts). No extra scenarios dir is mounted — only the image's baked /app/scenarios is exercised. No bench-host contact, no sandbox, nothing emitted with subject init. No ClickHouse or OTLP content is checked."
---

# r6 — legacy sixteen: the 16 existing suites load unchanged under the s6 loader

Deterministic instrument for the scenario's seventh expectation: the 16
existing suites load unchanged — none of the s6 additions to the loader
(bench-tier enum, credentials-must-be-list, non-empty name, non-negative
budget, duplicate-name refusal — all enforced at TomlScenario
construction, which `ls` performs for every TOML in
/app/scenarios) turned a legal existing suite into an error. The s4
round proved the same for the strict schema; this round re-proves it
for the s6 additions.

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
(branch `plato/s6-scaffold-honest--r6-legacy-sixteen`) is the compose
project root. It already carries an untracked `.env`. Five sibling
agents own ports 18180/18181/18182/18183/18184/18185 and their 143xx
neighbours — never touch them. The compose file hardcodes otelcol's
host publish at 4318, so every compose invocation below carries a ports
override pinning it to 127.0.0.1:14386. Deadline: 30 minutes wall clock
from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s6-r6-legacy-sixteen
   rm -rf "$ENV" && mkdir -p "$ENV"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=gentar-s6arm-r6
   #   GENTAR_CLICKHOUSE_HOST_PORT=18186
   #   GENTAR_NAME_PREFIX=gentar-s6arm-r6
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14386:4318"
   YML
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
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18186 -sTCP:LISTEN; lsof -nP -iTCP:14386 -sTCP:LISTEN
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

3. The load check — `coordinator ls`, no extra scenarios dir, diffed
   against the frozen list:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator ls >"$ENV/ls.txt" 2>&1
   echo "ls-exit=$?"
   diff "$ENV/expected.txt" <(grep -E '^[a-z0-9-]+$' "$ENV/ls.txt"); echo "diff-exit=$?"
   grep -c 'Traceback (most recent call last)' "$ENV/ls.txt"; echo "tb-exit=$?"
   ```

   Expected: `ls-exit=0`; `diff-exit=0` (byte-for-byte, the 18 frozen
   lines — the grep strips compose's own non-scenario noise lines so
   the diff is exact on the listing itself; record any stripped noise
   verbatim); `tb-exit=1`.

4. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf "$ENV"
   git status --porcelain   # expect no output; .env is ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack + no
bench-host contact) on THIS branch and commit
`run: /s6/r6-legacy-sixteen <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

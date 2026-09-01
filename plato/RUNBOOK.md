---
node: /s3-subject-scaffold/r1-emit
scenario: /s3-subject-scaffold
status: frozen
touches:
  - "worktree docker-compose.yml + coordinator image (docker compose build)"
  - "docker compose run --rm coordinator subject init demo-subject --repo https://github.com/x/demo"
  - "out/scaffold/ (untracked emit target) and a scratch env dir under /tmp"
  - "docs/subject-integration.md (read-only extraction of the trigger fence)"
expect:
  - "subject init exits 0 and stdout carries both numbered section markers"
  - "--dir writes demo-subject-install.toml and gentar.yml, byte-identical to the stdout sections"
  - "coordinator ls, given the emitted TOML via GENTAR_SCENARIOS_DIR, lists demo-subject-install AND still lists the builtin smoke"
  - "the emitted trigger section is line-for-line identical to the yaml fence in docs/subject-integration.md"
  - "an off-grammar name (Bad_Name) and a missing --repo each refuse with exit 2"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or any container fails to start for a reason in the runbook's own commands"
  - "host port 18123 or 14318 is already bound before step 1 completes — record as environment trouble (incomplete), do not pick other ports"
  - "wall clock exceeds the deadline — record incomplete, run teardown, stop"
exclusions: "No bench-host is contacted, no sandbox is created, no subject checkout is mounted, no scenario is RUN (the stub refusal and the green run are r2's and r3's instruments). No network beyond Docker Hub image pulls already cached locally."
---

# r1 — emit: generator output, ls acceptance, contract parity

Deterministic instrument for the scenario's first expectation:
`gentar subject init demo-subject --repo https://github.com/x/demo`
emits a TOML that `coordinator ls` accepts and a trigger snippet that
matches the documented dispatch contract line for line.

Environment: this Mac, OrbStack docker context `orbstack`. Your
worktree (branch `plato/s3-subject-scaffold--r1-emit`) is the compose
project root; its directory name makes the compose project distinct
from any sibling. Ports 18123 (ClickHouse host publish) and 14318
(otelcol host publish) are yours; this Mac's 8123 and 4318 are taken
by unrelated local services, which is why the override exists.

## Steps

1. Scratch env dir (keep everything you create under it):

   ```bash
   ENV=/tmp/gentar-s3-r1-emit
   rm -rf "$ENV" && mkdir -p "$ENV"
   cd <YOUR-WORKTREE>
   cp .env.example .env
   printf '\nGENTAR_CLICKHOUSE_HOST_PORT=18123\n' >> .env
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14318:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   ```

   Pre-flight (a bound port here is a stop condition, incomplete):

   ```bash
   lsof -nP -iTCP:18123 -sTCP:LISTEN; lsof -nP -iTCP:14318 -sTCP:LISTEN
   ```

   Expected: no output from either.

2. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   ```

   Expected: exit 0.

3. Emit to stdout:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     > "$ENV/emit.txt" 2>"$ENV/emit.err"
   echo "exit=$?"
   ```

   Expected: `exit=0`. `emit.txt` contains the line
   `# ==== 1/2 scenario: demo-subject-install.toml — carry in the subject repo under gentar/, or PR into gentar/coordinator/scenarios/ ====`
   and the line
   `# ==== 2/2 trigger: .github/workflows/gentar.yml in demo-subject's repo — the documented dispatch contract, line for line ====`.

4. Emit to a directory:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit-dir.txt" 2>&1
   echo "exit=$?"
   ls out/scaffold/
   ```

   Expected: `exit=0`; `out/scaffold/` contains exactly
   `demo-subject-install.toml` and `gentar.yml`.

5. The two emission modes agree. Extract from `emit.txt` the TOML
   section (all lines from the `# Subject: demo-subject` line up to but
   excluding the `# ==== 2/2` marker line) and from
   `out/scaffold/demo-subject-install.toml` the whole file; diff them.
   Expected: identical. (A trailing-newline-only difference is a
   finding, not a pass — record it verbatim.)

6. `coordinator ls` accepts the emitted TOML (own-arena pattern from
   docs/subject-integration.md):

   ```bash
   mkdir -p "$ENV/extra"
   cp out/scaffold/demo-subject-install.toml "$ENV/extra/"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator ls > "$ENV/ls.txt" 2>&1
   echo "exit=$?"
   grep -c '^demo-subject-install$' "$ENV/ls.txt"
   grep -c '^smoke$' "$ENV/ls.txt"
   ```

   Expected: `exit=0`, then `1`, then `1`.

7. Trigger parity, line for line:

   ```bash
   sed -n '/^# .github\/workflows\/gentar.yml in the SUBJECT repo$/,$p' "$ENV/emit.txt" > "$ENV/trigger-emitted.txt"
   awk 'f&&/```/{exit} f{print} /```yaml/{f=1}' docs/subject-integration.md > "$ENV/trigger-documented.txt"
   diff "$ENV/trigger-documented.txt" "$ENV/trigger-emitted.txt"; echo "diff-exit=$?"
   ```

   Expected: `diff-exit=0` and no diff output.

8. Input validation refuses:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init Bad_Name --repo https://github.com/x/demo \
     >"$ENV/badname.txt" 2>&1; echo "badname-exit=$?"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject >"$ENV/norepo.txt" 2>&1; echo "norepo-exit=$?"
   ```

   Expected: `badname-exit=2` with output containing
   `must be lowercase-with-dashes`; `norepo-exit=2`.

9. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/scaffold "$ENV"
   git status --porcelain   # expect no new tracked-file changes; out/ and .env are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (front-matter per the
loop's run grammar, stamp = local now) on THIS branch and commit
`run: /s3/r1-emit <verdict>`. Findings: anything unexpected that did
not break an expect (e.g. a compose warning line that is not the
known OrbStack `secrets uid/gid/mode` warning — that one is known and
not a finding). Teardown result goes in the record's teardown field.

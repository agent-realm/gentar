---
node: /s4-scaffold-hardened/r3-init-refuse
scenario: /s4-scaffold-hardened
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=plato-s4-arm, GENTAR_CLICKHOUSE_HOST_PORT=18140, GENTAR_NAME_PREFIX=gentar-s4)"
  - "docker compose build coordinator"
  - "docker compose run --rm coordinator subject init demo-subject --repo https://github.com/x/demo --dir /out/hold [--force] and --dir /out/fresh"
  - "out/hold/ and out/fresh/ under the worktree's bind-mounted out/ (untracked, torn down)"
expect:
  - "the first `subject init --dir /out/hold` exits 0 and writes demo-subject-install.toml + gentar.yml"
  - "a second `subject init --dir /out/hold` exits 2 with a message containing `--dir already holds scaffold output:`, the path `/out/hold/demo-subject-install.toml`, the path `/out/hold/gentar.yml`, and `--force`, with zero traceback matches"
  - "with gentar.yml removed (only the TOML held), the refusal names `/out/hold/demo-subject-install.toml` and does NOT mention `gentar.yml`"
  - "`--force` on the fully-held dir exits 0 and rewrites both files byte-identical to a fresh emit's copies"
  - "stdout mode (no --dir) still exits 0 with both numbered section markers"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18140 or 14340 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No bench-host is contacted (subject init is a pure generator: no network, no config, no bench). Suite LOADING and RUNNING of the emitted output is r1's/r2's/r4's instrument. The 64-char name cap, the un-creatable --dir path, and name grammar are NOT probed here — only the held-dir refusal and --force overwrite. No ClickHouse or OTLP content is checked."
---

# r3 — no silent overwrite: subject init --dir refuses held output by name, --force overwrites

Deterministic instrument for the scenario's third expectation:
`subject init --dir <held-dir>` exits 2 naming the files it refused to
overwrite; `--force` overwrites.

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s4-scaffold-hardened--r3-init-refuse`) is the compose
project root. It already carries an untracked `.env` (one arena, one
.env) and a sibling agent owns ports 18150/14350 — never touch them. The
compose file hardcodes otelcol's host publish at 4318, so every compose
invocation below carries a ports override pinning it to 127.0.0.1:14340.
Deadline: 30 minutes wall clock from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s4-r3-init-refuse
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

3. First init into a fresh dir — writes both files:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/hold >"$ENV/init1.txt" 2>&1
   echo "init1-exit=$?"
   ls out/hold/
   ```

   Expected: `init1-exit=0`; `out/hold/` contains exactly
   `demo-subject-install.toml` and `gentar.yml`.

4. Second init, same dir — refuses exit 2 naming the files:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/hold >"$ENV/init2.txt" 2>&1
   echo "init2-exit=$?"
   grep -m1 'already holds scaffold output' "$ENV/init2.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/init2.txt"; echo "tb-exit=$?"
   ```

   Expected: `init2-exit=2`; the grep prints a line containing
   `--dir already holds scaffold output:`, the path
   `/out/hold/demo-subject-install.toml`, the path `/out/hold/gentar.yml`,
   and `--force`; `tb-exit=1`.

5. Partial hold — with gentar.yml removed the refusal names ONLY the
   held file:

   ```bash
   rm out/hold/gentar.yml
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/hold >"$ENV/init3.txt" 2>&1
   echo "init3-exit=$?"
   grep -m1 'already holds scaffold output' "$ENV/init3.txt"
   grep -c 'gentar.yml' "$ENV/init3.txt"; echo "yml-exit=$?"
   ```

   Expected: `init3-exit=2`; the refusal line names
   `/out/hold/demo-subject-install.toml`; `yml-exit=1` (the message does
   not mention `gentar.yml`).

6. `--force` overwrites the held dir:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/hold --force >"$ENV/init4.txt" 2>&1
   echo "init4-exit=$?"
   ls out/hold/
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/fresh >"$ENV/init5.txt" 2>&1
   echo "init5-exit=$?"
   diff out/hold/demo-subject-install.toml out/fresh/demo-subject-install.toml; echo "toml-diff-exit=$?"
   diff out/hold/gentar.yml out/fresh/gentar.yml; echo "yml-diff-exit=$?"
   ```

   Expected: `init4-exit=0` with `out/hold/` back to exactly the two
   files; `init5-exit=0`; `toml-diff-exit=0` and `yml-diff-exit=0` with
   no diff output (the forced rewrite is byte-identical to a fresh emit).

7. Stdout mode unbroken:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   grep -c '# ==== 1/2 scenario: demo-subject-install.toml' "$ENV/emit.txt"
   grep -c '# ==== 2/2 trigger: .github/workflows/gentar.yml in demo-subject' "$ENV/emit.txt"
   ```

   Expected: `emit-exit=0`, then `1`, then `1`.

8. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/hold out/fresh "$ENV"
   git status --porcelain   # expect no output; .env and out/ are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack, no
bench-host contact) on THIS branch and commit
`run: /s4/r3-init-refuse <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

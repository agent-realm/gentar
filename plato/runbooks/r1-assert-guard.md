---
node: /s4-scaffold-hardened/r1-assert-guard
scenario: /s4-scaffold-hardened
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=plato-s4-arm, GENTAR_CLICKHOUSE_HOST_PORT=18140, GENTAR_NAME_PREFIX=gentar-s4)"
  - "docker compose build coordinator; docker compose run --rm coordinator subject init … --dir /out/scaffold"
  - "docker compose run --rm -e GENTAR_SCENARIOS_DIR=/extra -v <scratch>:/extra:ro coordinator ls / run demo-subject-install"
  - "bench-host 10.10.10.52 read-only: ssh polat@… 'sbx ls' snapshots, grep 'gentar-s4-' only"
  - "out/scaffold/ and a scratch env dir under /tmp (untracked, torn down)"
expect:
  - "the emitted suite with its whole verify section deleted still LOADS: `coordinator ls` (via GENTAR_SCENARIOS_DIR) exits 0 and lists demo-subject-install beside the builtin smoke"
  - "`coordinator run demo-subject-install` on that suite exits 2 with a line naming `assert guard`, the phrase `asserts nothing`, and `refusing before any bench exists`"
  - "the refusal output contains no Python traceback (zero `Traceback (most recent call last)` matches)"
  - "a refusal report report-refused-demo-subject-install-*.md lands in out/"
  - "bench-host `sbx ls` shows zero sandboxes matching gentar-s4- both before and after (the guard fired before any bench exists)"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "docker compose build fails, or a container fails to start for a reason in this runbook's own commands"
  - "host ports 18140 or 14340 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "ssh to polat@10.10.10.52 fails at step 2 or step 8 — environment trouble, incomplete, stop"
  - "wall clock exceeds 30 minutes — record incomplete, run teardown, stop"
exclusions: "No sandbox is ever created and no subject checkout is mounted (the guard must fire first — that ordering IS the instrument). The stub-TODO refusal (unmutated scaffold) was s3/r2's instrument. Off-schema keys and malformed TOML are r2's. Driver-suite exemption from the assert guard is not tested. No ClickHouse or OTLP content is checked."
---

# r1 — assert guard: a suite whose verify section is deleted cannot fake-green 0/0

Deterministic instrument for the scenario's first expectation: a suite
with its whole `verify` section deleted refuses exit 2 with the
assert-guard message naming "asserts nothing", before any bench exists.

Environment: this Mac, OrbStack docker context `orbstack`. Your worktree
(branch `plato/s4-scaffold-hardened--r1-assert-guard`) is the compose
project root. It already carries an untracked `.env` (one arena, one
.env) and a sibling agent owns ports 18150/14350 — never touch them. The
compose file hardcodes otelcol's host publish at 4318, so every compose
invocation below carries a ports override pinning it to 127.0.0.1:14340.
Deadline: 30 minutes wall clock from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s4-r1-assert-guard
   rm -rf "$ENV" && mkdir -p "$ENV/extra"
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

2. Bench-host BEFORE (read-only; foreign sandboxes are never touched):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-before.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s4-' "$ENV/sbx-before.txt"; echo "before-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `before-grep-exit=1` (zero own-prefix
   sandboxes; whatever foreign lines exist, record them verbatim in the
   run record — they are not yours and not findings).

3. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   ```

   Expected: `build-exit=0`.

4. Emit the scaffold (the runbook's mutation substrate):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   ls out/scaffold/
   ```

   Expected: `emit-exit=0`; `out/scaffold/` contains exactly
   `demo-subject-install.toml` and `gentar.yml`.

5. Build the asserts-nothing suite: delete the whole verify section
   (everything from the first `[[verify` line to end of file):

   ```bash
   cp out/scaffold/demo-subject-install.toml "$ENV/extra/"
   python3 - <<'PY'
   import pathlib
   p = pathlib.Path("/tmp/gentar-s4-r1-assert-guard/extra/demo-subject-install.toml")
   lines = p.read_text().splitlines(keepends=True)
   # Cut at the first LINE-STARTING [[verify table: the header comment
   # also mentions "[[verify.*]] probes", and must survive the cut.
   cut = next(i for i, l in enumerate(lines) if l.startswith("[[verify"))
   t = "".join(lines[:cut]).rstrip() + "\n"
   assert not any(l.startswith("[[verify") for l in t.splitlines())
   assert "[oracle]" in t and "./install.sh" in t
   assert "[budget]" in t
   p.write_text(t)
   print("cut-ok")
   PY
   ```

   Expected: prints `cut-ok`.

6. The mutated suite still LOADS (the guard is a run-time refusal, not a
   load error):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator ls > "$ENV/ls.txt" 2>&1
   echo "ls-exit=$?"
   grep -c '^demo-subject-install$' "$ENV/ls.txt"
   grep -c '^smoke$' "$ENV/ls.txt"
   ```

   Expected: `ls-exit=0`, then `1`, then `1`.

7. RUN refuses, exit 2, before any bench exists:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/run.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'assert guard' "$ENV/run.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/run.txt"; echo "tb-exit=$?"
   ls -t out/ | head -3
   ```

   Expected: `run-exit=2`; the grep prints a line containing
   `assert guard: scenario 'demo-subject-install' declares no verify probes and no driver — it asserts nothing`
   and the words `refusing before any bench exists`; `tb-exit=1` (zero
   traceback matches); a fresh `report-refused-demo-subject-install-*.md`
   appears among the newest files in `out/`.

8. Bench-host AFTER (nothing was created):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-after.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s4-' "$ENV/sbx-after.txt"; echo "after-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `after-grep-exit=1`.

9. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/scaffold "$ENV"
   git status --porcelain   # expect no output; .env and out/ are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack +
bench-host read-only) on THIS branch and commit
`run: /s4/r1-assert-guard <verdict>`. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

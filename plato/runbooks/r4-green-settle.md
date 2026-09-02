---
node: /s4-scaffold-hardened/r4-green-settle
scenario: /s4-scaffold-hardened
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=plato-s4-arm, GENTAR_CLICKHOUSE_HOST_PORT=18140, GENTAR_NAME_PREFIX=gentar-s4)"
  - "plato/scaffold/demo-subject/ (on this branch) staged as a real git checkout under a scratch subjects root"
  - "docker compose build coordinator; docker compose run --rm coordinator subject init … --dir /out/scaffold"
  - "docker compose run --rm -e GENTAR_SCENARIOS_DIR=/extra -v <scratch>:/extra:ro coordinator run demo-subject-install (hand-filled suite)"
  - "bench-host 10.10.10.52: one sbx sandbox created and destroyed by the coordinator; ssh polat@… 'sbx ls' snapshots, own-prefix grep only"
expect:
  - "the emitted suite with stubs hand-filled runs green: exit 0 and `oracle ok: 2/2 assertions passed`"
  - "a run report report-gentar-s4-*.md lands in out/ whose `| sandbox |` row names the run's sandbox (= run id)"
  - "immediately after the coordinator process exits, `sbx ls` on the bench-host shows zero sandboxes matching gentar-s4- — the sandbox settled BEFORE process exit, not after"
  - "the sandbox's exact name (from the report) is absent from that same listing (grep -F, literal)"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "ssh to polat@10.10.10.52 fails at step 2 — environment trouble, incomplete, stop"
  - "host ports 18140 or 14340 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "the run leaves a gentar-s4- sandbox on the bench-host after process exit — record the listing verbatim and the elapsed seconds; attempt exactly one manual 'sbx rm --force <that exact name>' (own-run sandbox only — never a foreign gentar-* name), record the attempt; then verdict FAIL (the expectation is violated)"
  - "wall clock exceeds 45 minutes — record incomplete, run teardown, stop"
exclusions: "Only ONE sandbox is created, by the coordinator, named by the run id; no foreign gentar-* sandbox is ever read beyond the listing, modified, or removed. The stub/assert guards are not exercised (the suite is filled — that is the point of a GREEN run). No dashboard, no ClickHouse queries, no OTLP content is checked. The subject is deliberately trivial — install sophistication is not what this instrument measures."
---

# r4 — teardown settles: a green run's sandbox is gone from sbx ls before the coordinator exits

Deterministic instrument for the scenario's fourth expectation: a green
run's sandbox is gone from `sbx ls` before the coordinator process
exits (the d1-impatient drill saw 30–60s of silent linger past exit 0).

Environment: this Mac, OrbStack docker context `orbstack`. Bench-host
10.10.10.52, ssh user polat, key `$HOME/.ssh/id_ed25519`. Your worktree
(branch `plato/s4-scaffold-hardened--r4-green-settle`) is the compose
project root. It already carries an untracked `.env` (one arena, one
.env); GENTAR_NAME_PREFIX=gentar-s4 stamps every sandbox this runbook
creates. A sibling agent owns ports 18150/14350 and its own
gentar-s5-* sandboxes — never touch them. The compose file hardcodes
otelcol's host publish at 4318, so every compose invocation below
carries a ports override pinning it to 127.0.0.1:14340. Deadline: 45
minutes wall clock from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s4-r4-green-settle
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

2. Bench-host BEFORE (read-only; foreign sandboxes recorded, never
   touched):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-before.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s4-' "$ENV/sbx-before.txt"; echo "before-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `before-grep-exit=1` (zero own-prefix
   sandboxes). Foreign gentar-* lines, if any, are recorded verbatim in
   the run record — not yours, not findings.

3. Stage the trivial subject as a REAL git checkout (it rides this
   branch at `plato/scaffold/demo-subject/`):

   ```bash
   mkdir -p "$ENV/subjects-root"
   cp -R plato/scaffold/demo-subject "$ENV/subjects-root/demo-subject"
   chmod +x "$ENV/subjects-root/demo-subject/install.sh"
   cd "$ENV/subjects-root/demo-subject" && git init -q && git add -A \
     && git -c user.email=demo@subject -c user.name=demo commit -qm "demo-subject trivial checkout" \
     && git log --oneline | head -1
   cd <YOUR-WORKTREE>
   ```

   Expected: one commit line printed.

4. Build + emit:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   ls out/scaffold/
   ```

   Expected: `build-exit=0`, `emit-exit=0`; `out/scaffold/` contains
   exactly `demo-subject-install.toml` and `gentar.yml`.

5. Hand-fill the stubs (exact-value replacements — the subject author's
   two moves):

   ```bash
   cp out/scaffold/demo-subject-install.toml "$ENV/extra/"
   python3 - <<'PY'
   import pathlib
   p = pathlib.Path("/tmp/gentar-s4-r4-green-settle/extra/demo-subject-install.toml")
   t = p.read_text()
   t = t.replace('path = "TODO"', 'path = "~/.demo-subject/state.txt"')
   t = t.replace('# contains = "TODO"    # optional substring the file must carry', 'contains = "installed"')
   t = t.replace('command = "TODO"', 'command = \'cat "$HOME/.demo-subject/state.txt"\'')
   t = t.replace('contains = "TODO"      # substring its output must carry', 'contains = "installed"')
   assert 'path = "TODO"' not in t and 'command = "TODO"' not in t and 'contains = "TODO"' not in t
   p.write_text(t)
   print("filled-ok")
   PY
   ```

   Expected: prints `filled-ok`.

6. RUN the filled suite green with the subject mounted (GENTAR_SUBJECTS_DIR
   must be EXPORTED — compose interpolates it for the subjects bind;
   `-e` alone would not):

   ```bash
   export GENTAR_SUBJECTS_DIR="$ENV/subjects-root"
   date +%s > "$ENV/t-start"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/run.txt" 2>&1
   echo "run-exit=$?"
   date +%s > "$ENV/t-exit"
   grep -a 'oracle ok\|FAIL\|Error:' "$ENV/run.txt" | head -3
   ls -t out/ | head -2
   ```

   Expected: `run-exit=0`; the grep prints
   `oracle ok: 2/2 assertions passed`; the newest file in `out/` is a
   `report-gentar-s4-*.md`.

7. THE measurement — sandbox gone before the process exited. Run this
   immediately; the two ssh round-trips after a local process exit are
   the whole point:

   ```bash
   REPORT=$(ls -t out/report-gentar-s4-*.md | head -1)
   SANDBOX=$(basename "$REPORT" .md | sed 's/^report-//')
   echo "sandbox=$SANDBOX"
   grep -m1 '| sandbox |' "$REPORT"
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-after.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s4-' "$ENV/sbx-after.txt"; echo "own-grep-exit=$?"
   grep -cF "$SANDBOX" "$ENV/sbx-after.txt"; echo "exact-grep-exit=$?"
   date +%s > "$ENV/t-check"; echo "seconds-exit-to-check=$(( $(cat "$ENV/t-check") - $(cat "$ENV/t-exit") ))"
   ```

   Expected: `sandbox=` names the run id (and equals the `| sandbox |`
   row in the report); `ssh-exit=0`; `own-grep-exit=1` (zero own-prefix
   sandboxes listed); `exact-grep-exit=1` (this run's sandbox in
   particular is absent); record the seconds-exit-to-check number
   verbatim. Any gentar-s4- sandbox present here is the stop condition —
   follow it exactly (one manual `sbx rm --force` of THAT name only,
   recorded, then FAIL).

8. Bench-host final confirmation (a second look, seconds later, must
   agree):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-final.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s4-' "$ENV/sbx-final.txt"; echo "final-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `final-grep-exit=1`.

9. Teardown (every exit path, including after a stop condition):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/scaffold "$ENV"
   unset GENTAR_SUBJECTS_DIR
   git status --porcelain   # expect no output; .env and out/ are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack +
bench-host 10.10.10.52) on THIS branch and commit
`run: /s4/r4-green-settle <verdict>`. Record verbatim: the sandbox name,
the before/after/final sbx listings (foreign lines included, marked
foreign), and seconds-exit-to-check. Verdicts: PASS / PASS WITH
FINDINGS / FAIL; timeout, crash, or never-ran is `incomplete: true` —
never FAIL. The known OrbStack warning `secrets 'uid', 'gid' and 'mode'
are not supported` is known noise, not a finding. Teardown result goes
in the record's teardown field.

---
node: /s3-subject-scaffold/r2-stub-refuse
scenario: /s3-subject-scaffold
status: orphan
touches:
  - "worktree docker-compose.yml + coordinator image (docker compose build)"
  - "docker compose run --rm coordinator run demo-subject-install (emitted stub suite via GENTAR_SCENARIOS_DIR)"
  - "read-only ssh polat@10.10.10.52 'sbx ls' snapshots (no sandbox is created by this runbook)"
  - "a scratch env dir under /tmp"
expect:
  - "running the emitted suite as-scaffolded exits 2 with a stub-guard message naming both stub probes and 'refusing before any bench exists'"
  - "the bench-host sandbox list is byte-identical before and after the refusal — no bench exists"
  - "a refusal report report-refused-demo-subject-install-*.md lands in out/"
  - "with the stubs filled, the same command gets PAST the stub guard and exits 1 on subject delivery (no stub message) — guard ordering"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "ssh to polat@10.10.10.52 fails at step 2 — environment trouble, incomplete, stop"
  - "host port 18124 or 14319 already bound before step 1 completes — incomplete, do not pick other ports"
  - "wall clock exceeds the deadline — record incomplete, run teardown, stop"
steer: "Pilot steer 2026-09-02, verbatim: step 5 and step 8 no longer whole-list diff against the shared bench-host — foreign transient sandboxes from other actors are out of this instrument's scope. Both steps now assert only what this runbook owns: no sandbox whose name contains demo-subject exists at either checkpoint."
exclusions: "No sandbox is ever CREATED (the green run is r3's instrument); the bench-host is only read via 'sbx ls'. No subject checkout is mounted. The negative control deliberately fails at subject delivery — that failure is expected, not a bug to repair."
---

# r2 — stub refusal: unfilled verify stubs refuse exit 2 before any bench exists

Deterministic instrument for the scenario's second expectation: the
emitted TOML refuses cleanly (exit 2) before any bench exists when its
verify probes are left as unfilled stubs — an honest scaffold, not a
fake-green one.

Environment: this Mac, OrbStack docker context `orbstack`. Bench-host
10.10.10.52 (VM 142), ssh user polat, key `$HOME/.ssh/id_ed25519`,
BatchMode. Ports 18124 (ClickHouse host publish) and 14319 (otelcol
host publish) are yours; 8123 and 4318 on this Mac are taken by
unrelated local services.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s3-r2-stub-refuse
   rm -rf "$ENV" && mkdir -p "$ENV"
   cd <YOUR-WORKTREE>
   cp .env.example .env
   printf '\nGENTAR_CLICKHOUSE_HOST_PORT=18124\n' >> .env
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14319:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18124 -sTCP:LISTEN; lsof -nP -iTCP:14319 -sTCP:LISTEN
   ```

   Expected: no output from either lsof (else stop condition).

2. Bench-host reachable, snapshot BEFORE:

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-before.txt"
   echo "ssh-exit=$?"
   ```

   Expected: `ssh-exit=0` (content is whatever it is; today typically
   `No sandboxes found.`).

3. Build + emit the scaffold:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   ```

   Expected: both exit 0; `out/scaffold/demo-subject-install.toml` exists.

4. Register the stub suite and RUN it:

   ```bash
   mkdir -p "$ENV/extra"
   cp out/scaffold/demo-subject-install.toml "$ENV/extra/"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/refuse.txt" 2>&1
   echo "run-exit=$?"
   grep -m1 'stub guard' "$ENV/refuse.txt"
   ```

   Expected: `run-exit=2`; the grep prints a line containing
   `stub guard: scenario 'demo-subject-install' has 2 unfilled verify stub(s) (verify.files[0], verify.commands[0])`
   and the words `refusing before any bench exists`.

5. No bench exists — snapshot AFTER (steered: runbook-owned check only):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-after.txt"
   grep -c 'demo-subject' "$ENV/sbx-after.txt"; echo "own-grep-exit=$?"
   ```

   Expected: `own-grep-exit=1` (zero matches — this runbook created no
   sandbox). Foreign transient sandboxes from other actors on the shared
   host are out of scope: record any that appear verbatim as an answer,
   never a verdict.

6. Refusal report exists:

   ```bash
   ls out/ | grep -c '^report-refused-demo-subject-install-.*\.md$'
   ```

   Expected: `1` (or more — count >= 1; record the exact count and
   filenames).

7. Negative control — stubs filled moves PAST the guard. Fill with
   exact-value replacements (this is the instrument, not a repair: the
   scaffold's fill-in move is the subject author's act, done by hand
   here):

   ```bash
   mkdir -p "$ENV/extra-filled"
   cp "$ENV/extra/demo-subject-install.toml" "$ENV/extra-filled/"
   python3 - <<'PY'
   import pathlib
   p = pathlib.Path("/tmp/gentar-s3-r2-stub-refuse/extra-filled/demo-subject-install.toml")
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

   Run it with NO subject mounted (delivery must fail — expected):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra-filled:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/neg.txt" 2>&1
   echo "neg-exit=$?"
   grep -c 'stub guard' "$ENV/neg.txt"; echo "stub-grep-exit=$?"
   grep -m1 'FAIL \[demo-subject-install\]' "$ENV/neg.txt"
   ```

   Expected: `neg-exit=1`; `stub-grep-exit=1` (zero matches — the
   stub guard no longer fires); a `FAIL [demo-subject-install]` line
   whose detail is subject-delivery failure (`local tar of
   /subjects/demo-subject failed` when no subject is mounted).

8. Bench-host still untouched (steered: runbook-owned check only):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-final.txt"
   grep -c 'demo-subject' "$ENV/sbx-final.txt"; echo "own-grep-exit=$?"
   ```

   Expected: `own-grep-exit=1` (zero matches). Same scope rule as step 5.

9. Teardown (every exit path):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/scaffold "$ENV"
   git status --porcelain   # expect no new tracked-file changes; out/ and .env are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` on THIS branch (run
grammar front-matter, stamp = local now) and commit
`run: /s3/r2-stub-refuse <verdict>`. The known OrbStack warning
`secrets 'uid', 'gid' and 'mode' are not supported` is known noise,
not a finding.

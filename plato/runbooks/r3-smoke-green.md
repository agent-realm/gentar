---
node: /s3-subject-scaffold/r3-smoke-green
scenario: /s3-subject-scaffold
status: orphan
touches:
  - "worktree docker-compose.yml + coordinator image (docker compose build)"
  - "plato/scaffold/demo-subject/ (this branch) staged as a real git checkout under a scratch subjects root"
  - "docker compose run --rm coordinator run demo-subject-install (filled emitted suite)"
  - "bench-host 10.10.10.52: one sbx sandbox created and destroyed by the coordinator"
expect:
  - "a trivial real checkout (git-init'd, install.sh) mounts as subject demo-subject"
  - "the emitted suite with stubs hand-filled exits 0 with 'oracle ok: 2/2 assertions passed'"
  - "a run report report-gentar-*.md lands in out/ showing both assertions"
  - "after the run the bench-host sandbox list shows no leftover gentar sandbox"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "ssh to polat@10.10.10.52 fails at step 2 — environment trouble, incomplete, stop"
  - "host port 18125 or 14320 already bound before step 1 completes — incomplete, do not pick other ports"
  - "the run leaves a sandbox on the bench-host after teardown — attempt one manual 'sbx rm --force <name>', record it, then verdict per the expects"
  - "wall clock exceeds the deadline — record incomplete, run teardown, stop"
steer: "Pilot steer 2026-09-02, verbatim: step 7 first grep expects the report's expanded render (report expands ~ to the bench home path /home/agent), and the second grep uses grep -cF (literal, no BRE anchor) for the cat command line."
exclusions: "The stub refusal is r2's instrument (the filled suite here never exercises the guard). No dashboard, no ClickHouse assertions, no OTLP self-report is checked. The subject is deliberately trivial — install sophistication is not what this instrument measures."
---

# r3 — smoke green: a hand-filled emitted suite runs against a trivial real checkout

Deterministic instrument for the scenario's third expectation: an
emitted suite with stubs filled by hand runs green against a trivial
real checkout. The trivial subject lives on THIS branch at
`plato/scaffold/demo-subject/` (two files); the runner stages it as a
real git checkout. The fill is the scaffold's contract: replace the
TODO probe values, touch nothing else.

Environment: this Mac, OrbStack docker context `orbstack`. Bench-host
10.10.10.52 (VM 142), ssh user polat, key `$HOME/.ssh/id_ed25519`.
Ports 18125 (ClickHouse host publish) and 14320 (otelcol host
publish) are yours; 8123 and 4318 on this Mac are taken by unrelated
local services.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s3-r3-smoke-green
   rm -rf "$ENV" && mkdir -p "$ENV/extra"
   cd <YOUR-WORKTREE>
   cp .env.example .env
   printf '\nGENTAR_CLICKHOUSE_HOST_PORT=18125\n' >> .env
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14320:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18125 -sTCP:LISTEN; lsof -nP -iTCP:14320 -sTCP:LISTEN
   ```

   Expected: no output from either lsof (else stop condition).

2. Bench-host reachable, snapshot BEFORE:

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-before.txt"
   echo "ssh-exit=$?"
   ```

   Expected: `ssh-exit=0`.

3. Stage the trivial subject as a REAL git checkout:

   ```bash
   mkdir -p "$ENV/subjects-root"
   cp -R plato/scaffold/demo-subject "$ENV/subjects-root/demo-subject"
   chmod +x "$ENV/subjects-root/demo-subject/install.sh"
   cd "$ENV/subjects-root/demo-subject" && git init -q && git add -A \
     && git -c user.email=demo@subject -c user.name=demo commit -qm "demo-subject trivial checkout" \
     && git log --oneline | head -1
   cd <YOUR-WORKTREE>
   ```

   Expected: one commit line printed; `git status --porcelain` in the
   staged dir is empty.

4. Build + emit:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   ```

   Expected: both exit 0; `out/scaffold/demo-subject-install.toml` exists.

5. Hand-fill the stubs (exact-value replacements — the subject
   author's two moves):

   ```bash
   cp out/scaffold/demo-subject-install.toml "$ENV/extra/"
   python3 - <<'PY'
   import pathlib
   p = pathlib.Path("/tmp/gentar-s3-r3-smoke-green/extra/demo-subject-install.toml")
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

6. RUN the filled suite with the subject mounted (note:
   GENTAR_SUBJECTS_DIR must be EXPORTED — compose interpolates it for
   the subjects bind; `-e` alone would not):

   ```bash
   export GENTAR_SUBJECTS_DIR="$ENV/subjects-root"
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -e GENTAR_SCENARIOS_DIR=/extra -v "$ENV/extra:/extra:ro" \
     coordinator run demo-subject-install >"$ENV/run.txt" 2>&1
   echo "run-exit=$?"
   grep -a 'oracle ok\|FAIL\|Error:' "$ENV/run.txt" | head -3
   ls -t out/ | head -2
   ```

   Expected: `run-exit=0`; the grep prints
   `oracle ok: 2/2 assertions passed`; a fresh `report-gentar-*.md`
   is the newest file in `out/`.

7. The report shows both reality assertions:

   ```bash
   REPORT=$(ls -t out/report-gentar-*.md | head -1)
   grep -c 'file-contains /home/agent/.demo-subject/state.txt' "$REPORT"
   grep -cF 'cat "$HOME/.demo-subject/state.txt"' "$REPORT"
   grep -m1 '^## Verdict\|verdict' "$REPORT" || true
   ```

   Expected: first two greps each count >= 1; record what the verdict
   line prints. (Steered: the report renders `~` expanded to the bench
   home `/home/agent`, and macOS BSD grep anchors `$` inside BRE patterns
   — hence the expanded path and `-cF` literal match.)

8. Bench-host clean (the coordinator destroyed its sandbox):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-after.txt"
   cat "$ENV/sbx-after.txt"
   grep -c 'gentar-' "$ENV/sbx-after.txt"; echo "leftover-exit=$?"
   ```

   Expected: `leftover-exit=1` (zero leftover gentar sandboxes; the
   list may read `No sandboxes found.` or match the before-state).

9. Teardown (every exit path):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
   rm -rf out/scaffold "$ENV"
   git status --porcelain   # expect no new tracked-file changes; out/ and .env are ignored
   ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` on THIS branch (run
grammar front-matter, stamp = local now) and commit
`run: /s3/r3-smoke-green <verdict>`. The known OrbStack warning
`secrets 'uid', 'gid' and 'mode' are not supported` is known noise,
not a finding.

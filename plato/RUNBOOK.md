---
node: /s6-scaffold-honest/r5-init-hint
scenario: /s6-scaffold-honest
status: draft
touches:
  - "worktree .env (pre-placed: COMPOSE_PROJECT_NAME=gentar-s6arm-r5, GENTAR_CLICKHOUSE_HOST_PORT=18185, GENTAR_NAME_PREFIX=gentar-s6arm-r5)"
  - "docker compose build coordinator; docker compose run --rm coordinator subject init … --dir /symdir --force (symlink case) and --dir /out/scaffold (real emit)"
  - "the scaffold's closing hint, executed VERBATIM from the worktree root: docker compose run --rm -v \"$PWD/demo-subject-scaffold\":/extra:ro -e GENTAR_SCENARIOS_DIR=/extra coordinator run demo-subject-install"
  - "bench-host 10.10.10.52: ONE sbx sandbox created and destroyed by the coordinator (prefix gentar-s6arm-r5-); ssh polat@… 'sbx ls' snapshots, own-prefix grep only"
  - "scratch dir /tmp/gentar-s6-r5-init-hint; <worktree>/demo-subject-scaffold/ and out/ (untracked, torn down)"
expect:
  - "`subject init --dir /symdir --force` with a pre-planted symlinked target (demo-subject-install.toml -> an outside sentinel file) exits 2 with `--dir target is a symlink: /symdir/demo-subject-install.toml — refusing to write through it`, zero traceback matches"
  - "the outside sentinel file is byte-identical after the refusal (no scaffold bytes, no truncation), the symlink still stands, and NO gentar.yml appeared in /symdir — writes stayed bounded"
  - "the real emit's closing hint carries the working form verbatim — exactly one line matching `-v \"$PWD/demo-subject-scaffold\":/extra:ro -e GENTAR_SCENARIOS_DIR=/extra coordinator run demo-subject-install` — plus the why-the-old-form-failed note (`never reaches the container`)"
  - "the hint, executed verbatim from the worktree root (only `-f` compose-file overrides added for port hygiene), runs the scaffolded suite — stubs filled by the two documented author moves — GREEN: exit 0, `oracle ok: 2/2 assertions passed`"
  - "bench-host `sbx ls` shows zero gentar-s6arm-r5- sandboxes before the run and zero after the coordinator process exits"
stop-conditions:
  - "any step's actual output does not match its expected output — record the diff verbatim, verdict FAIL, stop"
  - "ssh to polat@10.10.10.52 fails at step 2 — environment trouble, incomplete, stop"
  - "host ports 18185 or 14385 already bound at step 1 — environment trouble: record incomplete, do not pick other ports"
  - "the green run leaves a gentar-s6arm-r5- sandbox on the bench-host after process exit — record the listing verbatim; attempt exactly one manual 'sbx rm --force <that exact name>' (own-prefix sandbox only — never a foreign name), record the attempt; then verdict FAIL"
  - "wall clock exceeds 45 minutes — record incomplete, run teardown, stop"
exclusions: "Only the s6 additions to `subject init` are probed: the symlinked-target refusal and the closing hint's working form. The s4 overwrite/hold behaviors (`--dir` on held output, `--force` byte-identical rewrite, name validation) are not re-probed. The filled probes are deliberately trivial (the demo-subject's own install.sh effects) — install sophistication is not what this instrument measures; the honesty limit (tautology probes pass) is documented in the scaffold, not detected. No ClickHouse or OTLP content is checked."
---

# r5 — bounded writes + a hint that works verbatim

Deterministic instrument for the scenario's sixth expectation:
`subject init --dir X --force` refuses a symlinked target instead of
writing through it (bytes stay outside the declared dir), and the
scaffold's closing hint — mount with `-v`, env with `-e` — followed
verbatim runs the scaffolded suite green on a real bench.

Environment: this Mac, OrbStack docker context `orbstack`. Bench-host
10.10.10.52, ssh user polat, key `$HOME/.ssh/id_ed25519`. Your worktree
(branch `plato/s6-scaffold-honest--r5-init-hint`) is the compose project
root. It already carries an untracked `.env`;
GENTAR_NAME_PREFIX=gentar-s6arm-r5 stamps every sandbox this runbook
creates. Five sibling agents own ports 18180/18181/18182/18183/18184/
18186 and their 143xx neighbours — never touch them, and never touch a
foreign sandbox on the bench-host. The compose file hardcodes otelcol's
host publish at 4318, so every compose invocation below carries a ports
override pinning it to 127.0.0.1:14385. Deadline: 45 minutes wall clock
from step 1.

## Steps

1. Scratch env dir and compose wiring:

   ```bash
   ENV=/tmp/gentar-s6-r5-init-hint
   rm -rf "$ENV" && mkdir -p "$ENV/symdir"
   cd <YOUR-WORKTREE>
   cat .env    # must contain exactly these three lines (pre-placed):
   #   COMPOSE_PROJECT_NAME=gentar-s6arm-r5
   #   GENTAR_CLICKHOUSE_HOST_PORT=18185
   #   GENTAR_NAME_PREFIX=gentar-s6arm-r5
   cat > "$ENV/ports-override.yml" <<'YML'
   services:
     otelcol:
       ports: !override
         - "127.0.0.1:14385:4318"
   YML
   export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"
   lsof -nP -iTCP:18185 -sTCP:LISTEN; lsof -nP -iTCP:14385 -sTCP:LISTEN
   ```

   Expected: `.env` carries the three lines (a missing or different
   COMPOSE_PROJECT_NAME / port / prefix is a stop condition — record
   verbatim); no output from either lsof.

2. Bench-host BEFORE (read-only; foreign sandboxes recorded, never
   touched):

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-before.txt" 2>&1
   echo "ssh-exit=$?"
   grep -c 'gentar-s6arm-r5-' "$ENV/sbx-before.txt"; echo "before-grep-exit=$?"
   ```

   Expected: `ssh-exit=0`, `before-grep-exit=1` (zero own-prefix
   sandboxes). Foreign lines, if any, are recorded verbatim in the run
   record — not yours, not findings.

3. Pre-plant the symlink trap: an outside sentinel file, and the
   scaffold's TOML target as a symlink to it:

   ```bash
   printf 'sentinel-bytes\n' > "$ENV/outside.txt"
   ln -s "$ENV/outside.txt" "$ENV/symdir/demo-subject-install.toml"
   test -L "$ENV/symdir/demo-subject-install.toml" && echo "symlink-ok"
   ```

   Expected: prints `symlink-ok`.

4. Build the coordinator image:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" build coordinator
   echo "build-exit=$?"
   ```

   Expected: `build-exit=0`.

5. `subject init --dir … --force` through the symlink — refuses:

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     -v "$ENV/symdir:/symdir" \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /symdir --force >"$ENV/sym.txt" 2>&1
   echo "sym-exit=$?"
   grep -m1 'symlink' "$ENV/sym.txt"
   grep -c 'Traceback (most recent call last)' "$ENV/sym.txt"; echo "tb-exit=$?"
   ```

   Expected: `sym-exit=2`; the grep prints a line containing
   `error: --dir target is a symlink: /symdir/demo-subject-install.toml — refusing to write through it (bytes would land outside the declared dir)`;
   `tb-exit=1`.

6. Bytes stayed outside — the sentinel is untouched, the symlink
   stands, nothing else appeared:

   ```bash
   cat "$ENV/outside.txt"
   grep -c 'Scaffolded by' "$ENV/outside.txt"; echo "sentinel-grep-exit=$?"
   test -L "$ENV/symdir/demo-subject-install.toml" && echo "still-symlink"
   test ! -e "$ENV/symdir/gentar.yml" && echo "no-gentar-yml"
   /bin/ls -A "$ENV/symdir"
   ```

   Expected: `sentinel-bytes` (byte-identical); `sentinel-grep-exit=1`
   (zero scaffold bytes in it); `still-symlink`; `no-gentar-yml`; the
   ls prints exactly `demo-subject-install.toml`.

7. Real emit (host-visible via the ./out:/out bind):

   ```bash
   docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm \
     coordinator subject init demo-subject --repo https://github.com/x/demo \
     --dir /out/scaffold >"$ENV/emit.txt" 2>&1
   echo "emit-exit=$?"
   /bin/ls out/scaffold/
   grep -cF 'docker compose run --rm -v "$PWD/demo-subject-scaffold":/extra:ro -e GENTAR_SCENARIOS_DIR=/extra coordinator run demo-subject-install' "$ENV/emit.txt"
   grep -m1 'never reaches the container' "$ENV/emit.txt"
   ```

   Expected: `emit-exit=0`; `out/scaffold/` holds exactly
   `demo-subject-install.toml` and `gentar.yml`; the hint-line grep
   prints `1` (the working form, verbatim, exactly once); the note grep
   prints the why-the-old-form-failed line.

8. Stage the scaffold dir exactly where the hint expects it, and fill
   the stubs (the two documented author moves — steps stay verbatim,
   probes get real):

   ```bash
   rm -rf demo-subject-scaffold && cp -R out/scaffold demo-subject-scaffold
   python3 - <<'PY'
   import pathlib
   p = pathlib.Path("demo-subject-scaffold/demo-subject-install.toml")
   t = p.read_text()
   t = t.replace('path = "TODO"', 'path = "~/.demo-subject/state.txt"')
   t = t.replace('# contains = "TODO"    # optional substring the file must carry', 'contains = "installed"')
   t = t.replace('command = "TODO"', 'command = \'cat "$HOME/.demo-subject/state.txt"\'')
   t = t.replace('contains = "TODO"      # substring its output must carry', 'contains = "installed"')
   assert 'path = "TODO"' not in t and 'command = "TODO"' not in t and 'contains = "TODO"' not in t
   assert 'cd "$WORKSPACE_DIR" && ./install.sh' in t   # the scaffold's own step, untouched
   p.write_text(t)
   print("filled-ok")
   PY
   ```

   Expected: prints `filled-ok` (run from the worktree root).

9. Stage the trivial subject as a real checkout (it rides this branch at
   `plato/scaffold/demo-subject/`):

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

10. THE hint, verbatim, from the worktree root. `GENTAR_SUBJECTS_DIR`
    must be EXPORTED — compose interpolates it for the subjects bind;
    the only other change is the `-f` compose-file inserts (port
    hygiene). Record the exact executed line verbatim in the run record:

    ```bash
    export GENTAR_SUBJECTS_DIR="$ENV/subjects-root"
    docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" run --rm -v "$PWD/demo-subject-scaffold":/extra:ro -e GENTAR_SCENARIOS_DIR=/extra coordinator run demo-subject-install >"$ENV/run.txt" 2>&1
    echo "run-exit=$?"
    grep -a 'oracle ok\|FAIL\|Error:' "$ENV/run.txt" | head -3
    ls -t out/ | head -2
    ```

    Expected: `run-exit=0`; the grep prints
    `oracle ok: 2/2 assertions passed`; the newest file in `out/` is a
    `report-gentar-s6arm-r5-*.md`.

11. Bench-host AFTER — the run's sandbox settled before/with process
    exit:

    ```bash
    ssh -o BatchMode=yes -o ConnectTimeout=10 polat@10.10.10.52 'sbx ls' > "$ENV/sbx-after.txt" 2>&1
    echo "ssh-exit=$?"
    grep -c 'gentar-s6arm-r5-' "$ENV/sbx-after.txt"; echo "after-grep-exit=$?"
    ```

    Expected: `ssh-exit=0`, `after-grep-exit=1`.

12. Teardown (every exit path, including after a stop condition):

    ```bash
    unset GENTAR_SUBJECTS_DIR
    docker compose -f docker-compose.yml -f "$ENV/ports-override.yml" down -v --remove-orphans
    rm -rf out/scaffold out/report-* demo-subject-scaffold "$ENV"
    git status --porcelain   # expect no output; .env and out/ are ignored
    ```

## Recording

Write `plato/runs/RUN-<YYYY-MM-DD-HH_MM>.md` (run-grammar front-matter,
stamp = local now, environment field naming this Mac + OrbStack +
bench-host 10.10.10.52 sbx tier + one sandbox) on THIS branch and commit
`run: /s6/r5-init-hint <verdict>`. Verdicts: PASS / PASS WITH FINDINGS /
FAIL; timeout, crash, or never-ran is `incomplete: true` — never FAIL.
The known OrbStack warning `secrets 'uid', 'gid' and 'mode' are not
supported` is known noise, not a finding. Teardown result goes in the
record's teardown field.

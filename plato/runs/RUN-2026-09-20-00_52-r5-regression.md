---
runbook: /s7-docs-truth/r5-unchanged-regression @ ea63a22
stamp: 2026-09-20-00_52
environment: "this Mac, OrbStack (docker context orbstack); bench-host 10.10.10.52 (VM 142); ports 18198/14398; project gentar-s7r5; prefix gentar-s7arm"
verdict: PASS WITH FINDINGS
incomplete: false
findings:
  - "F1 (mechanism, not product): runbook step 8's capture line merges stderr (`> /tmp/s7r5-ls.log 2>&1`), so the literal step-9 diff is non-empty — 19 compose progress lines + the OrbStack secrets warning. The suite NAME set itself matches exactly (18 = 18, filtered diff empty). Recorded verbatim below."
  - "F2 (mechanism, not product): runbook step 9's extraction grep `grep -oE '^\\| \\`[a-z0-9-]+\\`' README.md` also matches 3 rows of a DIFFERENT table (component table: coordinator, telemetry, dashboard), which are not suites and are correctly absent from `ls`. Restricted to the `| Suite |` table (README.md:94-112): all 17 listed suites appear in the ls output, 0 missing."
teardown: done
---

# RUN-2026-09-20-00_52 — /s7-docs-truth/r5-unchanged-regression

Code frozen to message-only: the s7 diff is docs + one ValueError
message string; all 16 subject suites + 2 built-ins load; quickstart
green on the runbook's arena knobs. All steps executed in order,
literally, from a clean worktree on branch
`plato/s7-docs-truth--r5-unchanged-regression`, HEAD ea63a22, base
f976be1 (s5 blessed tip). Known noise observed and ignored (same as
sibling runs): OrbStack warning `secrets 'uid', 'gid' and 'mode' are
not supported` on every `docker compose run`.

## Step-by-step

1. Worktree/branch: `git branch --show-current` →
   `plato/s7-docs-truth--r5-unchanged-regression`, HEAD
   `ea63a2246ef460e9e875b65b54c03a9a3c758d0f`, `git status --short`
   clean before Setup. PASS.
2. `.env` created from `.env.example`, each override key set exactly
   once: `COMPOSE_PROJECT_NAME=gentar-s7r5`,
   `GENTAR_NAME_PREFIX=gentar-s7arm`,
   `GENTAR_CLICKHOUSE_HOST_PORT=18198`,
   `GENTAR_OTELCOL_HOST_PORT=14398`,
   `GENTAR_BENCH_KEY_FILE=/Users/polat/.ssh/id_ed25519`
   (first edit produced duplicate keys — example defaults + appended
   block; corrected to single occurrence of each key before any
   compose call; nothing had run yet).
3. `export GENTAR_BENCH_KEY_FILE="$HOME/.ssh/id_ed25519"` set in the
   shell of every docker-compose invocation (quickstart's own line).

### Diff scope (steps 4-6)

4. `git diff f976be1..HEAD --name-only` — verbatim, complete:
   ```
   .env.example
   README.md
   coordinator/gentar/config.py
   plato/BLESSED.md
   plato/RUNBOOK.md
   plato/SCENARIO.md
   ```
   Filter `^(plato/|README\.md$|\.env\.example$|coordinator/gentar/config\.py$)`
   leaves nothing. PASS.
5. `git diff f976be1..HEAD --stat -- coordinator/`:
   ```
   coordinator/gentar/config.py | 9 +++++----
   1 file changed, 5 insertions(+), 4 deletions(-)
   ```
   Exactly one file, `coordinator/gentar/config.py`.

   Regex/max lines, both revs (byte-identical):
   ```
   --- f976be1 ---
   _PREFIX_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
   _PREFIX_MAX = 24
   --- HEAD ---
   _PREFIX_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
   _PREFIX_MAX = 24
   ```

   `git diff f976be1..HEAD -- coordinator/gentar/config.py`, verbatim
   (full diff — every changed line is a message-continuation line of
   the `raise ValueError(` inside `_check_prefix`, README-confirmed at
   HEAD lines 18-23; no other line touched):
   ```diff
   @@ -16,10 +16,11 @@ _PREFIX_MAX = 24
   -            f"GENTAR_NAME_PREFIX {prefix!r} must be lowercase-with-dashes "
   -            f"(letters/digits/dashes, single dashes only), max "
   -            f"{_PREFIX_MAX} chars — it names sandboxes, workspace dirs, "
   -            f"run ids, and report files")
   +            f"GENTAR_NAME_PREFIX {prefix!r} must START WITH A LETTER, "
   +            f"then lowercase letters/digits/single dashes only (so "
   +            f"gentar-1a is legal; 1gentar, gentar--x, Gentar are not), "
   +            f"max {_PREFIX_MAX} chars — it names sandboxes, workspace "
   +            f"dirs, run ids, and report files")
   ```
   PASS.
6. README hunk confinement. Boundaries by `grep -n` on README.md @ HEAD:
   - `Busy Docker host?` → line **212**
   - `through exactly this seam` → line **264** (end of two-arenas section)

   `git diff f976be1..HEAD --unified=0 -- README.md` hunk headers:
   ```
   @@ -220,0 +221,7 @@
   @@ -237,2 +244,4 @@
   @@ -244,5 +253,12 @@
   ```
   New-file ranges: 221-227, 244-247, 253-264 — all inside [212, 264];
   hunk 3 ends exactly on the boundary line 264.
   `git diff f976be1..HEAD -- README.md | grep -c 'suites today'` → **0**
   (grep exit 1, no match). No hunk touches the scenario inventory or
   its suite-count line. PASS.

### Suites load (steps 7-9)

7. `docker compose build coordinator` → exit 0, image
   `gentar-s7r5-coordinator` built. PASS.
8. `docker compose run --rm coordinator ls` → **exit 0**. Suite-name
   lines, verbatim in output order:
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
   18 names (16 scenario .toml + built-in smoke already among tomls →
   16 toml baselines + smoke + smoke-fail deduped = 18).
9. Set comparison exactly as prescribed:
   `/tmp/s7r5-expected.txt` = 18 lines (toml basenames + smoke +
   smoke-fail, sorted unique); `/tmp/s7r5-actual.txt` = 37 lines
   (sorted full log). The literal `diff` is NON-empty — 19 added lines,
   every one compose orchestration noise from the step-8 capture
   merging stderr (`Network/Volume/Container …` progress + the
   OrbStack secrets warning); NOT suite names (**finding F1**).
   Name-set check: filtering actual to `^[a-z0-9-]+$` lines gives
   18 names; `diff /tmp/s7r5-expected.txt <(names only)` → **empty,
   exit 0**. No suite missing, no extra suite. The name set equals
   {toml basenames} + {smoke, smoke-fail}. PASS (name set).

   README inventory: `| Suite |` table is README.md lines 94-112, 17
   suite rows. The runbook's whole-file extraction grep yields 20 rows
   — the 17 suites plus `coordinator`, `telemetry`, `dashboard`, which
   are rows of a different (component) table and are not suite names
   (**finding F2**). All 17 inventory suites appear in the ls output;
   `comm -23` (README suites missing from actual) → empty, 0 missing.
   PASS.

### Quickstart green (steps 10-12)

10. `docker compose run --rm coordinator run smoke` → **exit 0**:
    ```
    smoke ok: Linux gentar-s7arm-20260919-215130-53cc99 7.0.12 #1 SMP PREEMPT Wed Aug 12 15:53:03 UTC 2026 x86_64 GNU/Linux
    report: /out/report-gentar-s7arm-20260919-215130-53cc99.md
    ```
    Exactly one sandbox on 10.10.10.52, named
    `gentar-s7arm-20260919-215130-53cc99` (prefix shape
    `gentar-s7arm-<stamp>-<hex6>`), destroyed by the run itself —
    post-run read-only `sbx ls` (verbatim, full):
    ```
    SANDBOX                         AGENT   STATUS    PORTS   WORKSPACE
    gentar-20260919-215155-5ab3a0   shell   running           /tmp/gentar-workspaces/gentar-20260919-215155-5ab3a0
    ```
    Only a FOREIGN sandbox (bare `gentar-` prefix = another arena's
    run, 25s after mine, different hex) remains; recorded, left
    untouched per hard-isolation rules. Nothing `sbx rm`'d ever.
11. `ls -t out/ | head -3`:
    ```
    report-gentar-s7arm-20260919-215130-53cc99.md
    ```
    Newest (and only) file matches `^report-gentar-s7arm-`.
    run_id = `gentar-s7arm-20260919-215130-53cc99`. PASS.
12. Quickstart SQL, verbatim rows:
    ```
    scenario	running
    run.start	pass
    bench.create	pass
    bench.exec	pass
    run.end	pass
    scenario	pass
    ```
    `bench.create` pass, `bench.exec` pass, and a `run.end` row with
    status `pass` all present. PASS.

### Teardown (step 13)

13. `docker compose down -v` → exit 0: clickhouse container removed,
    otelcol removed, network `gentar-s7r5_default` removed, volume
    `gentar-s7r5_clickhouse` removed. `docker compose ls -a | grep -i
    s7r5` → no match; `docker ps -a --filter
    label=com.docker.compose.project=gentar-s7r5 -q | wc -l` → **0**.
    No project gentar-s7r5 containers or volumes remain. Bench-host:
    own sandbox already gone (destroyed by the run); foreign
    `gentar-20260919-215155-5ab3a0` never touched. Teardown done.

## Verdict

PASS WITH FINDINGS — all six expects hold: diff scope confined
(paths, config.py message-only with byte-identical regex/max,
README hunks inside [212,264] with zero `suites today` matches), `ls`
exit 0 with the exact expected 18-name set and all 17 README
inventory suites present, smoke exit 0 with report
`report-gentar-s7arm-20260919-215130-53cc99.md` and all quickstart
span rows green including `run.end`/`pass`. The two findings (F1, F2)
are runbook-mechanism imprecisions, not product defects: F1 = the
step-8 capture merges stderr so the literal step-9 diff carries 19
compose-noise lines (name set still exactly equal), F2 = the step-9
extraction grep over-matches a non-suite component table (all actual
suite rows verified present).

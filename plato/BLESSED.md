---
node: /s6-scaffold-honest/b1-honest-all
scenario: /s6-scaffold-honest @ 7c989d9
runbooks:
  - /s6-scaffold-honest/r1-exit2-net @ a60bfc1, run RUN-2026-09-02-14_40.md
  - /s6-scaffold-honest/r2-vacuous-driver @ fad2543, run RUN-2026-09-02-14_41.md
  - /s6-scaffold-honest/r3-budget-guard @ f999f3a, run RUN-2026-09-02-14_41.md
  - /s6-scaffold-honest/r4-schema-names @ 9a53265, run RUN-2026-09-02-14_41.md
  - /s6-scaffold-honest/r5-init-hint @ 4315a51, run RUN-2026-09-02-14_42.md
  - /s6-scaffold-honest/r6-legacy-sixteen @ 0000547, run RUN-2026-09-02-14_39.md
blessed-by: auto
waivers: []
---

# b1-honest-all — the exit-2 net closed, no holes, no lies

All six runbooks green, no findings, nothing to waive. The seven drill
findings the pilot steered in ("Fix via s6") each have a proving
instrument, and every refusal is a named exit-2 config error — zero
traceback matches across every captured output of the whole round.

- **traceback escapes** (steers 1) — r1: `bench = "bogus"` refuses at
  `ls` AND at `run` (exit 2, file + key + legal values in one line:
  `scenario.bench must be 'sbx' or 'tart', got 'bogus'`); a
  recursion-bomb TOML refuses with `TOML nests too deeply to parse`;
  a directory named `*.toml` refuses with `is a directory, not a
  scenario file`.
- **vacuous-driver-green** (steer 2) — r2: `command = "true"` with zero
  turns and zero probes still LOADS but `run` refuses exit 2 with the
  assert-guard message (`declares no verify probes and no driven
  turns … refusing before any bench exists`); the same suite with ONE
  answer turn runs green on a real sbx bench (`driver ok: 1 turns`),
  sandbox settled before process exit.
- **budget guard blind spot** (steer 3) — r3: `tokens = 0,
  simulate_spend = 500` against `GENTAR_BUDGET_CAP=100` refuses exit 2
  (`budget guard: run would spend 500 units, 0 already burned, cap
  100` — simulated spend counted, not declared 0); `tokens = -5` and
  `simulate_spend = -1` both refuse at load naming key and value.
- **schema gaps** (steer 4) — r4: bare-string `credentials` refuses at
  load naming the list form; `name = ""` refuses as a ghost; two files
  declaring one name refuse naming BOTH; a user `smoke.toml` beside
  the builtin `smoke` is a loud collision at `run` (`collides: builtin
  AND a suite in /extra — rename one`), not silent builtin precedence.
- **symlink escape** (steer 5) — r5: `subject init --dir … --force`
  through a pre-planted symlink refuses exit 2 (`--dir target is a
  symlink … refusing to write through it`); the outside sentinel file
  byte-identical, no bytes landed outside the declared dir.
- **scaffold-hint lies** (steer 6) — r5: the closing hint carries the
  working form verbatim (`-v "$PWD/<name>-scaffold":/extra:ro -e
  GENTAR_SCENARIOS_DIR=/extra` + the why-the-old-form-failed note),
  and followed verbatim from the worktree root it runs the scaffolded
  suite — stubs filled by the two documented author moves — green:
  `oracle ok: 2/2 assertions passed`.
- **16 suites load unchanged** — r6: `coordinator ls` prints exactly
  the frozen 18-line sorted list (16 suites + builtins `smoke`,
  `smoke-fail`), exit 0, byte-for-byte; no s6 addition turned a legal
  existing suite into an error. (Steer 7's searched-dirs states were
  exercised implicitly in every refusal message this round; the
  unknown-scenario error's per-dir `missing / empty / N suites` states
  live in the same `_searched_dirs` line the runbooks' refusals
  carried.)

Arena hygiene held throughout: six parallel compose projects
(gentar-s6arm-r1…r6, ports 18181-18186/14381-14386), one shared
bench-host (10.10.10.52) touched only by r2 and r5, each with exactly
one own-prefix sandbox, gone by process exit; foreign sandboxes looked
at, never touched; every runner tore down on its exit path.

Run records are parked under `plato/runs/<runbook-slug>/` on this
branch — three runners stamped the same minute (RUN-2026-09-02-14_41),
so top-level parking would collide; the per-slug subdirectory (s3
precedent) keeps every record byte-identical to its runbook branch.

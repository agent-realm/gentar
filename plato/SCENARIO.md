---
node: /s4-scaffold-hardened
status: approved
snapshot: 1
snapshot-commit: 9f2ee5a
seeds: [gentar-repo, scenario-toml]
hints: [subjects/mounted-checkouts]
steered-from: "/s3-subject-scaffold @ 3b1ff49"
---

# s4 — scaffold hardened: honest under bending

Steered scenario off `/s3-subject-scaffold @ 3b1ff49` (blessed
b1-standard-all). Its drills — d2-tweaker, d3-abuser, d1-impatient —
found the honest-scaffold claim has holes; the pilot's steer (2026-09-02,
answer: "fix") applies them as this scenario's opening commits.

## Steers (pilot's decision, verbatim record)

Pilot chose "fix" from the menu:
- fix all real findings in both scenarios (this one = the scaffold holes)
- delights recorded, not actioned

Findings driven in, with the drill + reproduction of record:

1. **fake-green 0/0** — verify probes commented out / section deleted →
   `oracle ok: 0/0 assertions passed`, exit 0, PASS report (d2, d3).
2. **fake-green stub bypass** — probe key renamed (`substring = "TODO"`)
   → guard silent, run green (d2); root cause: unknown keys silently
   ignored, guard greps literal TODO on known keys only.
3. **off-type TOML tracebacks** — `verify = "boom"`, `steps = 5`,
   malformed TOML → raw traceback exit 1, bypassing the designed exit-2
   path (d3, d2).
4. **writes-outside / silent overwrite** — `subject init --dir`
   overwrites pre-existing `gentar.yml` + TOML, exit 0 (d3); plus
   tracebacks on `--dir` at an existing file, un-creatable path, and a
   301-char name (d3).
5. **sandbox linger** — green run leaves live `gentar-` sandboxes on
   the bench-host 30–60s after exit 0, teardown silent (d1).
6. **confusing-first-contact** — `run <unknown>` dead end: no pointer
   to GENTAR_SCENARIOS_DIR or how a scaffolded suite becomes runnable
   (d1).

## Mechanism

Same generator, hardened contract — the scaffold's honesty now holds
under a bending user:

- **Assert guard** — an oracle scenario with zero verify probes and no
  driver "asserts nothing": `run` refuses exit 2 before any bench
  exists (`assert guard: … 0/0 assertions is not a pass`). Driver
  suites exempt (the driver's outcome is the verdict).
- **Strict schema** — every table type-checked, every key outside the
  schema a named ScenarioError (key + legal keys), empty-string probes
  rejected ("an empty probe asserts nothing"), malformed TOML a
  ScenarioError with file + decoder position. Config errors are exit 2,
  never tracebacks — a renamed probe key can no longer silently
  un-assert.
- **No silent overwrite** — `subject init --dir` refuses existing
  scaffold output unless `--force`; every filesystem failure is a clean
  usage error naming the path; names capped at 64 chars.
- **Teardown settles** — `rm` waits (bounded 60s) for the sandbox to
  leave the listing before the coordinator exits; still-listed warns.
- **Dead ends point somewhere** — unknown-scenario error names the
  searched dirs and the GENTAR_SCENARIOS_DIR knob; the scaffold's
  closing hint explains how to run a suite before it lands in a repo.

## What a runbook will be able to expect

- A suite with its whole `verify` section deleted refuses exit 2 with
  the assert-guard message naming "asserts nothing".
- A probe key renamed to anything off-schema fails to load with a named
  error — `ls` and `run` both exit 2 clean, no traceback.
- `subject init --dir <held-dir>` exits 2 naming the files it refused
  to overwrite; `--force` overwrites.
- A green run's sandbox is gone from `sbx ls` before the coordinator
  process exits.
- The 16 existing suites load unchanged (no legal key became illegal).

## Deliberately left out

Deferred-ideal topics stay parked (deferral register). The delights
stay recorded, unactioned. No new probe vocabulary — `contains` /
`substring` unification would change the emitted scaffold contract
beyond the steer's scope.

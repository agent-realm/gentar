# grill — record-informed priming for engine-plato

Targets **engine-plato**'s interview (stages 1–3: intent, ideals, seeds, hints).
Use when a repository with a real record enters plato: the interview should read
the record's answers back for a ruling, not ask the pilot to dictate from
memory what is already written down.

## Procedure

**A — review, read-only.** Read the record: README, design docs, build plans,
ADRs, recent history, open TODO markers, `DEVLOOPER.md`'s survey and context.
Draft, with every record-derived item citing its source (file or commit):

- **intent** — 2–4 lines, in the record's own words where they exist;
- **ideals** — 3 to 5 candidates, prose, vague on purpose: no numeric targets,
  no tolerances (plato's rule — precision the pilot never gave is not
  manufactured);
- **seeds** — platforms and premises scenarios will stand on; the repository
  itself is usually the first;
- **hints** — capabilities of those seeds, filed by concern, with known hazards;
- **deferral candidates** — topics the record shows were parked.

**B — grill.** One item at a time: propose it, cite its source, and let the
pilot rule — accept / reword / strike / replace. The pilot's words land
verbatim. Items the pilot volunteers are added. Ask an open-ended question only
where the record is silent. Contradictions between record and pilot are written
down as tensions, not resolved. Continue until the **pilot** says settled.

**C — conclude.** Write `PRIMED.md`: front-matter (`target-engine:
engine-plato`, `primed: YYYY-MM-DD-HH_MM`), then `## Intent`, `## Ideals`,
`## Seeds`, `## Hints`, `## Deferrals`, each item marked `confirmed` or
`unconfirmed`, each with its source or the pilot's ruling. Commit to `root`:
`prime: grill concluded`. Hand off:

```
devlooper › prime › done › PRIMED.md on root, <n> confirmed / <m> unconfirmed
next › pilot: claude DEVLOOPER.md
```

engine-plato's interview then loads `PRIMED.md`, and stages 1–3 become
read-back and gap-filling instead of a blank page; the settle (stage 4) stays
the pilot's.

## Failure

Pilot unavailable or declines the grill → write the stage-A drafts as
`PRIMED.md` with everything `unconfirmed`, say so, and stop. The interview
treats unconfirmed items as proposals, never answers.

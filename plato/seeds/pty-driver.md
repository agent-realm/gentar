---
seed: pty-driver
confirmed-by: grill 2026-08-31
---

# pty-driver

The coordinator impersonates a human at the bench pty — pexpect over
ssh -tt ... sbx exec -t; gauntlet policies ported (picker navigation by last
cursor line, danger gate, auto-approve ordinary prompts). Driver transport:
one interface, two implementations (sbx exec -t Linux / ssh tart).

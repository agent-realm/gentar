---
hint: driver/pty-mechanics
confirmed-by: grill 2026-08-31
seed: pty-driver
---

# pty-mechanics

Capability: pexpect pty driver with ported gauntlet policies — picker
navigation, danger gate, auto-approve; scripted turns (answer / pick /
confirm / expect) proven by scripted-onboarding in the gate.

Hazards: transcript is a raw stream; the picker cursor is the LAST cursor
line; ICRNL delivers Enter as \n through the ssh-pty chain; a picker render
race was fixed with settle-wait in pick_option — new call sites must keep
the settle.

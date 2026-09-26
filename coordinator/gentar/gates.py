"""The driver's safety patterns — a leaf module, like keys.py.

The danger gate and the approval pattern are read by the pty driver, the
scripted turns, the goal pilot's offer, and bin/judge-eval on a bare host.
pty_driver imports pexpect at module top; keeping these here means the
host-side tools never need it to know what the gate is.
"""

import re

# Ported verbatim from gauntlet drive.sh DRIVE_DANGER_RE.
DANGER_RE = re.compile(
    r"rm -rf /($|[^a-zA-Z])|mkfs\.|dd .*of=/dev/(sd|nvme|vd)"
    r"|:\(\)\{.*:\|:.*\};:|shutdown |poweroff|systemctl (poweroff|reboot)"
    r"|iptables -F|> */dev/(sd|nvme|vd)"
)
APPROVAL_RE = re.compile(
    r"do you want to (proceed|make this edit)|requires approval|allow this command",
    re.IGNORECASE,
)

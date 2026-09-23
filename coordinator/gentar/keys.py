"""Named keys a `key` driver turn may send — the vocabulary, and nothing else.

A leaf module on purpose. The scenario parser validates `key` turns against
this set, and it used to import it from pty_driver — which imports pexpect
at module top. So on an adopter's host without pexpect, any suite with a
`key` turn failed to LOAD in dryrun.py: the cheap local check broke on the
one dependency it has no use for. The driver and the parser both read the
vocabulary from here; only the driver needs pexpect.
"""

KEYS = {"enter": "\r", "escape": "\x1b", "down": "\x1b[B", "up": "\x1b[A",
        "ctrl-c": "\x03"}

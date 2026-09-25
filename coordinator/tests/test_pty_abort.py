"""After the danger gate fires, the driver never types into the pty again.

scripted-danger failed on the v0.6.1 tag run: abort() sent its ctrl-c, the
host was loaded, and close() then sent `exit` + Enter — which answered the
still-live dangerous prompt (the script wrote its evidence file). The gate
had refused; its teardown approved.
"""

import unittest
from unittest import mock

from gentar.pty_driver import PtyDriver


class Child:
    def __init__(self):
        self.sent = []

    def sendline(self, s=""):
        self.sent.append(("line", s))

    def send(self, s):
        self.sent.append(("raw", s))

    def expect(self, *a, **k):
        return 0

    def close(self, force=False):
        self.sent.append(("close", force))


class AbortNeverTypesTest(unittest.TestCase):

    def driver(self):
        d = PtyDriver(bench=mock.MagicMock(), sandbox="sb")
        d.child = Child()
        return d

    def test_close_after_abort_sends_no_input(self):
        d = self.driver()
        child = d.child
        with mock.patch("gentar.pty_driver.time.sleep"):
            d.abort("danger")
        before = list(child.sent)
        d.close()
        after = child.sent[len(before):]
        self.assertEqual([s for s in after if s[0] != "close"], [], after)
        self.assertIn(("close", True), after)

    def test_a_normal_close_still_exits_the_shell(self):
        d = self.driver()
        child = d.child
        d.close()
        self.assertEqual(child.sent[0], ("line", "exit"))


if __name__ == "__main__":
    unittest.main()

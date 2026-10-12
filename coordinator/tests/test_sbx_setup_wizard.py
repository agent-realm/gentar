"""A fresh bench account's sbx setup wizard is named in the failure.

2026-10-12 (the first gate on a new bench host): the first interactive sbx
session of a fresh bench account shows sbx's one-time first-run wizard and
waits for a key, so the scenario's prompt never appeared and the failure
said only that. The driver now recognises the wizard in its transcript and
says what to do.
"""

import unittest

from gentar.scripted import SBX_SETUP_HINT, TurnFailure, _not_seen

# The screen as the 2026-10-12 report recorded it (escape codes trimmed).
WIZARD = ("sbx setup — detected configuration\n\n"
          "We found configuration on your host that Docker Sandboxes can reuse.\n"
          "Would you like to import the selected secrets, skills, and MCP servers?\n"
          "[T] details · [enter] accept & import · [q] continue without importing\n")


class _Driver:
    def __init__(self, transcript):
        self.transcript = transcript


class SbxSetupWizardTest(unittest.TestCase):

    def test_the_wizard_is_named_with_the_fix(self):
        err = _not_seen(_Driver("\x1b[?25l" + WIZARD), "turn 0: prompt 'pilot name' never appeared")
        self.assertIsInstance(err, TurnFailure)
        self.assertTrue(str(err).startswith("turn 0: prompt 'pilot name' never appeared -- "))
        self.assertIn(SBX_SETUP_HINT, str(err))
        self.assertIn("`sbx setup` once and press q", str(err))

    def test_any_other_transcript_keeps_the_plain_message(self):
        for transcript in ("", "pilot name? ", "Install for Ada in fast mode? (y/n): ", None):
            with self.subTest(transcript=transcript):
                err = _not_seen(_Driver(transcript), "turn 1: pattern 'x' never appeared")
                self.assertEqual(str(err), "turn 1: pattern 'x' never appeared")

    def test_a_driver_without_a_transcript_is_fine(self):
        self.assertEqual(str(_not_seen(object(), "m")), "m")


if __name__ == "__main__":
    unittest.main()

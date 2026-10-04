"""Pickers without numbers (cockpit, 2026-10-01).

pick_option only recognised `❯ N.` cursor lines, so Claude Code 2.1.283's
API-key and trust dialogs ("❯ No, exit" / "Yes, I trust this folder") never
matched: an optional pick was skipped without a word, a required one failed
"not reachable". Now an unnumbered `❯ <text>` cursor counts when the label
being picked is in the option block, the input prompt does not, a list that
wraps fails fast, and a skipped optional pick is said in the report.
"""

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import pty_driver, scripted
from gentar.report import RunReport
from gentar.toml_scenario import TomlScenario


class MenuDriver(pty_driver.PtyDriver):
    """A screen that follows the keys: `options`, cursor on `pos`."""

    def __init__(self, options, numbered=False, header="Do you trust the files in this folder?",
                 pos=0):
        super().__init__(bench=None, sandbox="s")
        self.options, self.numbered, self.header, self.pos = options, numbered, header, pos
        self.keys = []

    def screen(self):
        rows = [self.header, ""]
        for i, o in enumerate(self.options):
            text = f"{i + 1}. {o}" if self.numbered else o
            rows.append(("❯ " if i == self.pos else "  ") + text)
        return "\n".join(rows)

    def send_key(self, key):
        self.keys.append(key)
        if key == "down":
            self.pos = (self.pos + 1) % len(self.options)


def fast():
    return mock.patch.object(pty_driver.time, "sleep", lambda s: None)


class PickTest(unittest.TestCase):

    def test_an_unnumbered_dialog_is_picked(self):
        d = MenuDriver(["No, exit", "Yes, I trust this folder"])
        with fast():
            self.assertTrue(d.pick_option("Yes, I trust"))
        self.assertEqual(d.keys, ["down", "enter"])

    def test_the_cursor_already_on_it(self):
        d = MenuDriver(["No (recommended)", "Yes"], header="Use this API key?")
        with fast():
            self.assertTrue(d.pick_option("^\\s*❯\\s*No"))
        self.assertEqual(d.keys, ["enter"])

    def test_numbered_pickers_still_work(self):
        d = MenuDriver(["Dark mode", "Light mode"], numbered=True)
        with fast():
            self.assertTrue(d.pick_option("Light"))
        self.assertEqual(d.keys, ["down", "enter"])

    def test_a_label_not_in_the_list_fails_without_cycling(self):
        d = MenuDriver(["No, exit", "Yes, I trust this folder"])
        with fast(), mock.patch.object(pty_driver, "picker_visible", return_value=True):
            self.assertFalse(d.pick_option("Maybe", max_tries=8))
        self.assertEqual(d.keys.count("enter"), 0)
        self.assertLessEqual(d.keys.count("down"), 2)        # wrapped once, stopped

    def test_the_input_prompt_is_not_a_picker(self):
        label = re.compile("Yes", re.IGNORECASE)
        self.assertFalse(pty_driver.picker_visible("Welcome\n\n❯ \n", label))
        self.assertFalse(pty_driver.picker_visible("❯ write a haiku\n", label))
        self.assertTrue(pty_driver.picker_visible("❯ No, exit\n  Yes, I trust\n", label))


class SkippedPickTest(unittest.TestCase):

    def test_a_skipped_optional_pick_is_in_the_report(self):
        f = Path(tempfile.mkdtemp()) / "s.toml"
        f.write_text('[scenario]\nname = "s"\n[driver]\ncommand = "x"\n'
                     '[[driver.turns]]\ntype = "pick"\nlabel = "Yes"\noptional = true\n')
        sc = TomlScenario(f)

        class NoPicker(MenuDriver):
            def __init__(self, bench, run_id, **k):
                super().__init__(["unused"])

            def start(self, *a, **k):
                pass

            def screen(self):
                return "plain output, no picker"

            def wait_done(self, s):
                return True

            def close(self):
                pass

        report = RunReport(scenario="s", run_id="r")
        spans = mock.Mock()
        spans.redactor.scrub = lambda t: t
        with mock.patch.object(scripted, "PtyDriver", NoPicker), fast():
            scripted.run_turns(sc, None, "r", spans, report=report)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("optional pick /Yes/ skipped", report.warnings[0])


if __name__ == "__main__":
    unittest.main()

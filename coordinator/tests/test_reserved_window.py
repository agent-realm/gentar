"""bin/reserved-window: gentar's nightly stays out of other arenas' slots.

GitHub started gentar's 00:17 cron at 05:14Z on 2026-09-27, inside cockpit's
04:17 nightly slot on the shared bench-host. The start time is what counts,
so the nightly job waits on a check of it.
"""

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "reserved-window"
WORKFLOW = ROOT / ".github" / "workflows" / "gentar.yml"


def run(t, windows=None):
    env = dict(os.environ)
    env.pop("GENTAR_RESERVED_UTC", None)
    if windows is not None:
        env["GENTAR_RESERVED_UTC"] = windows
    return subprocess.run(["/bin/bash", str(SCRIPT), t], env=env,
                          capture_output=True, text=True).returncode


@unittest.skipUnless(SCRIPT.exists(), "needs a checkout (bin/ is not in the image)")
class ReservedWindowTest(unittest.TestCase):

    def test_the_default_windows_are_the_adopters_nightly_slots(self):
        inside = ["02:00", "02:17", "03:29", "04:00", "04:17", "05:14", "05:29"]
        clear = ["00:17", "01:59", "03:30", "03:59", "05:30", "12:00", "23:59"]
        for t in inside:
            self.assertEqual(run(t), 0, t)       # the 2026-09-27 05:14Z start included
        for t in clear:
            self.assertEqual(run(t), 1, t)

    def test_a_window_across_midnight(self):
        self.assertEqual(run("23:30", "23:00-01:00"), 0)
        self.assertEqual(run("00:59", "23:00-01:00"), 0)
        self.assertEqual(run("01:00", "23:00-01:00"), 1)

    def test_no_windows_means_always_clear(self):
        self.assertEqual(run("02:17", ""), 1)

    def test_bad_input_is_an_error_not_a_skip(self):
        for t, w in (("25:00", None), ("2:17", None), ("02:17", "02:00-3:30"),
                     ("02:17", "02:00"), ("02:17", "x-y")):
            self.assertEqual(run(t, w), 2, (t, w))

    def test_the_nightly_job_waits_on_the_check(self):
        text = WORKFLOW.read_text()
        job = text[text.index("\n  nightly:\n"):]
        job = job[:job.index("\n  dispatch:")] if "\n  dispatch:" in job else job
        self.assertIn("needs: nightly-window", job)
        self.assertIn("needs.nightly-window.outputs.clear == 'true'", job)
        check = text[text.index("\n  nightly-window:\n"):text.index("\n  nightly:\n")]
        self.assertIn("bin/reserved-window", check)
        # on the self-hosted runner: GitHub-hosted minutes may be exhausted
        self.assertRegex(check, re.compile(r"runs-on: \[self-hosted, gentar-bench\]"))


if __name__ == "__main__":
    unittest.main()

"""gentar's own CI never pastes the bench key into a step script.

AK47, 2026-10-08: the runner writes each step's script to _work/_temp on the
self-hosted gentar-bench-142, and a cancelled job can leave it there. With
`echo "${{ secrets.GENTAR_BENCH_KEY }}" > file` the key sat inside that
script. Now the key arrives through env, is written under umask 077 with
printf, and the always() teardown removes the key file.
"""

import re
import unittest
from pathlib import Path

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "gentar.yml"


@unittest.skipUnless(WF.exists(), "the workflow is not in this build context")
class BenchKeyTest(unittest.TestCase):

    def setUp(self):
        self.text = WF.read_text()

    def test_the_key_is_never_templated_into_a_script(self):
        self.assertNotIn('echo "${{ secrets.GENTAR_BENCH_KEY', self.text)
        for block in re.findall(r"run: \|\n((?:          .*\n|\n)+)", self.text):
            self.assertNotIn("secrets.GENTAR_BENCH_KEY", block)

    def test_three_jobs_take_it_through_env_and_write_it_private(self):
        self.assertEqual(self.text.count("BENCH_KEY: ${{ secrets.GENTAR_BENCH_KEY }}"), 3)
        self.assertEqual(self.text.count("printf '%s\\n' \"$BENCH_KEY\" > /tmp/gentar_ci_bench_key"), 3)
        for m in re.finditer(r"printf '%s\\n' \"\$BENCH_KEY\"", self.text):
            before = self.text[:m.start()].rsplit("run: |", 1)[1]
            self.assertIn("umask 077", before)

    def test_every_teardown_removes_the_key_always(self):
        # each teardown step: from its name line to the next step or job
        teardowns = re.findall(r"      - name: teardown\n((?:        .*\n|\n)+)", self.text)
        self.assertEqual(len(teardowns), 3)
        for t in teardowns:
            self.assertIn("if: always()", t)
            self.assertIn("rm -f /tmp/gentar_ci_bench_key", t)


if __name__ == "__main__":
    unittest.main()

"""A suite only a bench can prove says so, and the dry-run reports it.

memhouse's adoption (2026-10-04, review by memhouse-f7): memhouse-house
deploys a ClickHouse through the bench's Docker. The bench-free dry-run
cannot, ran its verify commands without the house, and turned every
memhouse pull request red. `[scenario] bench_only = "<why>"` makes the
dry-run report it UNVERIFIED with that reason; phase 1 accepts that, a
plain dry-run does not, and the arena runs it as any other suite.
"""

import tempfile
import unittest
from pathlib import Path

from gentar.toml_scenario import ScenarioError, TomlScenario

from tests.test_dryrun_fidelity import KIT, _ScratchAdoption

HEAVY = """[scenario]
name = "heavy"
subject = "fid"
bench_only = "deploys a ClickHouse through the bench's Docker"
[oracle]
steps = ["touch \\"$HOME/ran\\""]
[[verify.commands]]
command = "test -f \\"$HOME/ran\\" && echo ran"
contains = "ran"
"""


class ParserTest(unittest.TestCase):

    def write(self, body):
        p = Path(tempfile.mkdtemp()) / "s.toml"
        p.write_text(body)
        return p

    def test_a_reason_is_kept(self):
        self.assertEqual(TomlScenario(self.write(HEAVY)).bench_only,
                         "deploys a ClickHouse through the bench's Docker")

    def test_absent_means_not_bench_only(self):
        self.assertEqual(TomlScenario(self.write(HEAVY.replace(
            'bench_only = "deploys a ClickHouse through the bench\'s Docker"\n', ""))).bench_only, "")

    def test_an_empty_or_non_string_reason_is_refused(self):
        for bad in ('bench_only = ""', 'bench_only = "  "', "bench_only = true"):
            with self.subTest(bad=bad):
                body = HEAVY.replace(
                    'bench_only = "deploys a ClickHouse through the bench\'s Docker"', bad)
                with self.assertRaises(ScenarioError):
                    TomlScenario(self.write(body))


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class DryrunBenchOnlyTest(_ScratchAdoption):

    def setUp(self):
        super().setUp()
        (self.repo / "gentar" / "scenarios" / "heavy.toml").write_text(HEAVY)
        self.suite("light", ["true"])
        (self.repo / "gentar" / "hooks.py").write_text(
            "import os\nSKIP_STEP_SUBSTR = ()\n"
            "def prepare(env):\n"
            "    open(os.environ['PREPARE_LOG'], 'a').write('prepared\\n')\n")

    def test_reported_unverified_with_its_reason_and_not_run(self):
        r = self.dryrun()
        self.assertEqual(r.returncode, 1, r.stdout)          # not proven
        self.assertIn("heavy.toml: UNVERIFIED (bench only: deploys a ClickHouse "
                      "through the bench's Docker)", r.stdout)
        self.assertIn("light.toml: ALL PASS", r.stdout)
        self.assertEqual(self.prepared_for(), 1)              # light only: heavy never prepared

    def test_phase_one_accepts_it(self):
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")        # what --check sets
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("UNVERIFIED (bench only:", r.stdout)

    def test_a_host_with_what_it_needs_can_run_it(self):
        r = self.dryrun(GENTAR_DRYRUN_BENCH_ONLY="run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("heavy.toml: ALL PASS", r.stdout)

    def test_a_failing_light_suite_still_fails_phase_one(self):
        self.suite("broken", ["false"])
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("broken.toml", r.stdout)


if __name__ == "__main__":
    unittest.main()

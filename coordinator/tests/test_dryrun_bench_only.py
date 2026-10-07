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


    def test_a_bench_only_suite_with_another_schema_error_fails_unprepared(self):
        # Codex on #68: a later schema error made the suite look not
        # bench-only, so prepare() ran for it. Now: never prepared, and a
        # FAILURE (not UNVERIFIED) even under phase 1.
        broken = HEAVY.replace('[[verify.commands]]\ncommand = "test -f \\"$HOME/ran\\" && echo ran"\n',
                               '[[verify.commands]]\n')                  # a command entry without `command`
        self.assertNotEqual(broken, HEAVY)
        (self.repo / "gentar" / "scenarios" / "heavy.toml").write_text(broken)
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("heavy.toml: FAILURE (bench only, but the scenario does not parse", r.stdout)
        self.assertNotIn("heavy.toml: UNVERIFIED", r.stdout)
        self.assertEqual(self.prepared_for(), 1)              # light only

    def test_an_empty_reason_fails_unprepared(self):
        (self.repo / "gentar" / "scenarios" / "heavy.toml").write_text(
            HEAVY.replace('bench_only = "deploys a ClickHouse through the bench\'s Docker"', 'bench_only = ""'))
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("heavy.toml: FAILURE (bench only", r.stdout)
        self.assertEqual(self.prepared_for(), 1)

    def test_a_whitespace_reason_fails_unprepared(self):
        (self.repo / "gentar" / "scenarios" / "heavy.toml").write_text(
            HEAVY.replace('bench_only = "deploys a ClickHouse through the bench\'s Docker"', 'bench_only = "   "'))
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("heavy.toml: FAILURE (bench only", r.stdout)
        self.assertNotIn("heavy.toml: UNVERIFIED", r.stdout)
        self.assertEqual(self.prepared_for(), 1)

    def test_a_suite_that_is_not_toml_is_never_prepared(self):
        # agy on #68: a syntax error hid the marker, and prepare() ran.
        (self.repo / "gentar" / "scenarios" / "heavy.toml").write_text(
            HEAVY.replace('steps = [', 'steps = [ "unclosed'))
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("heavy.toml: FAILURE (does not parse", r.stdout)
        self.assertIn("light.toml: ALL PASS", r.stdout)     # the sweep went on
        self.assertEqual(self.prepared_for(), 1)              # light only

    def test_a_scenario_array_is_never_prepared(self):
        (self.repo / "gentar" / "scenarios" / "heavy.toml").write_text(
            HEAVY.replace("[scenario]", "[[scenario]]", 1))
        r = self.dryrun(GENTAR_DRYRUN_UNVERIFIED="ok")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("heavy.toml: FAILURE (does not parse", r.stdout)
        self.assertIn("light.toml: ALL PASS", r.stdout)     # the sweep went on
        self.assertEqual(self.prepared_for(), 1)

if __name__ == "__main__":
    unittest.main()

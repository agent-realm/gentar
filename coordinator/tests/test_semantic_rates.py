"""Rates over N runs, and soft judgments — step 2b of the semantic design.

A judged suite may declare [semantic] runs / pass_rate_min: its verdict is
passes/N against the minimum, each run on a fresh bench, a refusal still 2.
A [[verify.judge]] check is reported only: after reality has passed, it can
flag a run, never fail it, and never rescue one.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.oracle import _soft_judgments
from gentar.report import RunReport
from gentar.toml_scenario import ScenarioError, TomlScenario


def rate(outcomes, runs=5, rate_min=0.8):
    seq = list(outcomes)
    calls = []

    def fake_run(name, cfg):
        calls.append(1)
        return seq.pop(0)
    with mock.patch.object(coord, "_run", side_effect=fake_run), \
            mock.patch.object(coord, "Spans"), \
            mock.patch("builtins.print"):
        rc = coord._run_rate("s", mock.MagicMock(name_prefix="t"), runs, rate_min)
    return rc, len(calls)


class RateTest(unittest.TestCase):

    def test_four_of_five_meets_point_eight(self):
        self.assertEqual(rate([0, 1, 0, 0, 0]), (0, 5))

    def test_it_stops_once_the_minimum_is_out_of_reach(self):
        self.assertEqual(rate([1, 1, 0, 0, 0]), (1, 2))       # 3 left can make at most 3/5

    def test_a_refusal_is_a_refusal_at_once(self):
        self.assertEqual(rate([2, 0, 0, 0, 0]), (2, 1))

    def test_a_rate_of_one_needs_every_run(self):
        self.assertEqual(rate([0, 0, 1], runs=3, rate_min=1.0), (1, 3))


class ReviewTest(unittest.TestCase):
    """agy review of #50."""

    def test_two_of_three_meets_point_six_six(self):
        self.assertEqual(rate([0, 1, 0], runs=3, rate_min=0.66), (0, 3))
        self.assertEqual(rate([0, 1, 0], runs=3, rate_min=0.67), (1, 2))   # exact: needs 3/3

    def test_a_quarantined_judged_suite_is_skipped_once_not_passed_n_times(self):
        cfg = mock.MagicMock(quarantine={"g"})
        sc = mock.MagicMock(semantic_runs=5, pass_rate_min=0.8)
        with mock.patch.object(coord, "_resolve", return_value=(None, sc)):
            self.assertEqual(coord._rate_plan("g", cfg), (1, 1.0))

    def test_any_judge_error_in_a_soft_check_is_reported_never_raised(self):
        class Broken:
            def noul(self, *a, **k):
                raise ValueError("bad JSON from the service")
        class One:
            name, judge_checks = "s", [{"question": "Q?"}]
        report = RunReport(scenario="s", run_id="r")
        self.assertEqual(_soft_judgments(One, Broken(), "scr", mock.MagicMock(), "s", "r", report), 1)
        self.assertEqual(report.soft[0]["status"], "unavailable")


class CodexReviewTest(unittest.TestCase):
    """Codex review of #50."""

    def test_the_whole_rate_budget_is_checked_before_any_bench(self):
        cfg = mock.MagicMock(budget_cap=250, name_prefix="t")
        sc = mock.MagicMock(budget_tokens=100)
        ran = []
        with mock.patch.object(coord, "_resolve", return_value=(None, sc)), \
                mock.patch.object(coord, "_spent_so_far", return_value=0), \
                mock.patch.object(coord, "Spans"), \
                mock.patch.object(coord, "_run", side_effect=lambda *a: ran.append(1) or 0), \
                mock.patch("builtins.print"):
            self.assertEqual(coord._run_rate("s", cfg, 3, 1.0), 2)   # 3 x 100 > 250
        self.assertEqual(ran, [])                                     # no bench ever

    def test_soft_outcomes_use_valid_span_statuses(self):
        class Sc:
            name, judge_checks = "s", [{"question": "Q1?"}, {"question": "Q2?"}]
        spans = mock.MagicMock()
        _soft_judgments(Sc, Judge([0.5, None]), "scr", spans, "sub", "r", None)
        statuses = [c.args[4] for c in spans.emit.call_args_list]
        self.assertEqual(statuses, ["skip", "error"])       # the Enum's values only
        self.assertEqual([c.kwargs["attrs"]["soft"] for c in spans.emit.call_args_list],
                         ["undecided", "unavailable"])

    def test_run_sh_recognises_every_judged_spelling(self):
        import subprocess
        root = Path(__file__).resolve().parents[2]
        run_sh = root / "subject-template" / "gentar" / "run.sh"
        if not run_sh.exists():
            self.skipTest("the kit is not in the image build context")
        text = run_sh.read_text()
        fn = text[text.index("judged() {"):text.index("\n}\n", text.index("judged() {")) + 3]
        yes = ['goal = "G"', '"goal" = "G"', '[driver.turns."judge"]', '[["verify"."judge"]]',
               '[[verify.judge]]', 'verify.judge = []', 'driver.goal = "G"', '  judge = { q = 1 }']
        no = ["goalie = 1", "# goal = x", "[[verify.commands]]", "judgement = 1", "subgoal = 1"]
        with tempfile.TemporaryDirectory() as d:
            for line, want in [(l, True) for l in yes] + [(l, False) for l in no]:
                f = Path(d) / "s.toml"
                f.write_text(line + "\n")
                r = subprocess.run(["/bin/bash", "-c", fn + f'judged "{f}"'], capture_output=True)
                self.assertEqual(r.returncode == 0, want, line)


class Judge:
    def __init__(self, ps):
        self.ps = list(ps)

    def noul(self, screen, q, **k):
        from gentar.judge import JudgeUnavailable
        p = self.ps.pop(0)
        if p is None:
            raise JudgeUnavailable("TypeSafe HTTP 503")
        return p


class Sc:
    name = "s"
    judge_checks = [{"question": "Q1?"}, {"question": "Q2?"}, {"question": "Q3?"}, {"question": "Q4?"}]


class SoftTest(unittest.TestCase):

    def test_soft_results_are_reported_and_counted_never_raised(self):
        report = RunReport(scenario="s", run_id="r")
        flagged = _soft_judgments(Sc, Judge([0.95, 0.1, 0.5, None]), "final screen",
                                  mock.MagicMock(), "sub", "r", report)
        self.assertEqual(flagged, 3)
        self.assertEqual([s["status"] for s in report.soft],
                         ["pass", "fail", "undecided", "unavailable"])
        self.assertIn("Soft judgments (reported only", report.markdown())

    def test_no_checks_no_calls(self):
        class NoChecks:
            name, judge_checks = "s", []
        self.assertEqual(_soft_judgments(NoChecks, None, "", None, "s", "r", None), 0)


BASE = """
[scenario]
data = "synthetic"
{extra}
"""


def load(text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.toml"
        p.write_text(text)
        return TomlScenario(p)


class SchemaTest(unittest.TestCase):

    def test_rates_are_for_judged_suites_only(self):
        with self.assertRaises(ScenarioError):
            load('[scenario]\n[oracle]\nsteps = ["true"]\n[semantic]\nruns = 5\n')

    def test_a_judged_suite_may_declare_a_rate(self):
        s = load('[scenario]\ndata = "synthetic"\n[semantic]\nruns = 5\npass_rate_min = 0.8\n'
                 '[driver]\ncommand = "d"\n[[driver.turns]]\ntype = "expect"\n'
                 '[driver.turns.judge]\nquestion = "Q?"\n')
        self.assertEqual((s.semantic_runs, s.pass_rate_min), (5, 0.8))

    def test_a_soft_judge_needs_a_driver_and_makes_the_suite_judged(self):
        with self.assertRaises(ScenarioError):
            load('[scenario]\ndata = "synthetic"\n[oracle]\nsteps = ["true"]\n'
                 '[[verify.judge]]\nquestion = "Q?"\n')
        s = load('[scenario]\ndata = "synthetic"\n[driver]\ncommand = "d"\n'
                 '[[verify.judge]]\nquestion = "Q?"\n')
        self.assertTrue(s.uses_judge)

    def test_bad_rate_values_are_refused(self):
        judged = ('[driver]\ncommand = "d"\n[[driver.turns]]\ntype = "expect"\n'
                  '[driver.turns.judge]\nquestion = "Q?"\n')
        for sem in ("runs = 0", "runs = 21", "pass_rate_min = 0", "pass_rate_min = 1.5"):
            with self.assertRaises(ScenarioError, msg=sem):
                load(f'[scenario]\ndata = "synthetic"\n[semantic]\n{sem}\n' + judged)


if __name__ == "__main__":
    unittest.main()

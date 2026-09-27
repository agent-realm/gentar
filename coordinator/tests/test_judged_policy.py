"""Judged suites in the kit: phase 2 only, synthetic, measured by fixtures.

A judged (semantic) turn sends a screen to a judge, and a probability is
not a PR gate: plan() never picks one in phase 1, even when a PR names it,
and lint refuses one in the floor, one without data = "synthetic", and one
without 3+ yes and 3+ no fixture screens per judged turn.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "subject-template" / "gentar" / "plan.py"

JUDGED = """
[scenario]
name = "{name}"
{data}
[driver]
command = "demo"
[[driver.turns]]
type = "expect"
[driver.turns.judge]
question = "Does `screen` ask to delete beta?"
"""
PLAIN = '[scenario]\nname = "fast"\n[oracle]\nsteps = ["true"]\n'


def load_plan(tmp):
    spec = importlib.util.spec_from_file_location("gentar_plan_judged", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.HERE = tmp
    mod.SCENARIOS = tmp / "scenarios"
    mod.FIXTURES = tmp / "judge-fixtures"
    return mod


def policy(mod, floor):
    return {**{k: dict(v) for k, v in mod.SCHEMA.items()},
            "phase1": {**mod.SCHEMA["phase1"], "bench": "declared", "floor": floor}}


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class JudgedPolicyTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scenarios").mkdir()
        (self.tmp / "scenarios" / "fast.toml").write_text(PLAIN)
        (self.tmp / "scenarios" / "semantic.toml").write_text(
            JUDGED.format(name="semantic", data='data = "synthetic"'))
        self.mod = load_plan(self.tmp)

    def fixtures(self, yes=3, no=3):
        for label, n in (("yes", yes), ("no", no)):
            d = self.tmp / "judge-fixtures" / "semantic" / "0" / label
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                (d / f"s{i}.txt").write_text("screen")

    def test_a_pr_never_runs_a_judged_suite(self):
        env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "o/r",
               "PR_HEAD_REPO": "o/r", "PR_BODY": "gentar: semantic fast"}
        res = self.mod.plan(env, policy(self.mod, ["fast"]))
        self.assertEqual(res["suites"], ["fast"])
        self.assertIn("left for phase 2", res["reason"])

    def test_without_a_policy_a_pr_still_never_runs_a_judged_suite(self):
        env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "o/r",
               "PR_HEAD_REPO": "o/r", "PR_BODY": "gentar: semantic fast"}
        res = self.mod.plan(env, None)
        self.assertEqual(res["suites"], ["fast"])
        self.assertIn("left for phase 2", res["reason"])

    def test_run_sh_refuses_a_judged_suite_on_a_pull_request(self):
        # the invariant is enforced where suites run, whatever picked them
        import os, shutil, subprocess
        repo = self.tmp / "repo"
        shutil.copytree(ROOT / "subject-template" / "gentar", repo / "gentar")
        first = repo / "gentar" / "scenarios" / "first-suite.toml"
        first.write_text(first.read_text().replace('"REPLACE-ME"', '"judgedpr"'))
        (repo / "gentar" / "scenarios" / "semantic.toml").write_text(
            '[scenario]\nname = "semantic"\ndata = "synthetic"\nsubject = "judgedpr"\n'
            '[driver]\ncommand = "d"\n"goal" = "G"\n[[driver.actions]]\nid = "a"\n'
            'key = "down"\nwhen = "w"\n')          # a QUOTED key (Codex)
        # No engine to stage: if the guard is ever missing, the run fails fast
        # at staging instead of building an arena on this machine.
        for event in ("pull_request", "pull_request_target"):     # both carry PR code
            env = dict(os.environ, GITHUB_EVENT_NAME=event, GENTAR_DIR=str(self.tmp / "no-engine"),
                       GENTAR_REPO_URL=str(self.tmp / "no-such-engine"))
            r = subprocess.run(["/bin/bash", "gentar/run.sh", "semantic"], cwd=repo, env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2, (event, r.stdout + r.stderr))
            self.assertIn("never run on a pull request", r.stderr)

    def test_a_main_push_floor_never_runs_a_judged_suite(self):
        env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}
        res = self.mod.plan(env, policy(self.mod, ["semantic"]))
        self.assertEqual(res["suites"], [])

    def test_lint_refuses_a_judged_floor_and_missing_fixtures(self):
        self.fixtures(yes=3, no=1)
        problems = "\n".join(self.mod.lint(policy(self.mod, ["semantic"]), self.tmp / "none"))
        self.assertIn("run in phase 2 only", problems)
        self.assertIn("1 no fixture(s)", problems)
        self.assertNotIn("yes fixture(s)", problems)

    def test_lint_refuses_a_judged_suite_not_declared_synthetic(self):
        (self.tmp / "scenarios" / "semantic.toml").write_text(JUDGED.format(name="semantic", data=""))
        self.fixtures()
        problems = "\n".join(self.mod.lint(policy(self.mod, []), self.tmp / "none"))
        self.assertIn('data = "synthetic"', problems)

    def test_a_goal_pilot_is_judged_and_needs_goal_fixtures(self):
        (self.tmp / "scenarios" / "pilot.toml").write_text(
            '[scenario]\nname = "pilot"\ndata = "synthetic"\n[driver]\ncommand = "d"\n'
            'goal = "G"\n[[driver.actions]]\nid = "a"\nkey = "down"\nwhen = "w"\n')
        self.assertIn("pilot", self.mod.judged_suites())
        env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "o/r",
               "PR_HEAD_REPO": "o/r", "PR_BODY": "gentar: pilot fast"}
        self.assertEqual(self.mod.plan(env, policy(self.mod, []))["suites"], ["fast"])
        problems = "\n".join(self.mod.lint(policy(self.mod, []), self.tmp / "none"))
        self.assertIn("its goal pilot needs", problems)
        for a, n in (("a", 2), ("done", 1)):
            d = self.tmp / "judge-fixtures" / "pilot" / "goal" / a
            d.mkdir(parents=True)
            for i in range(n):
                (d / f"s{i}.txt").write_text("screen")
        problems = "\n".join(self.mod.lint(policy(self.mod, []), self.tmp / "none"))
        self.assertNotIn("its goal pilot needs", problems)

    def test_a_measured_synthetic_phase2_suite_is_clean(self):
        self.fixtures()
        problems = [p for p in self.mod.lint(policy(self.mod, ["fast"]), self.tmp / "none")
                    if "semantic" in p]
        self.assertEqual(problems, [])


class EngineScenariosTest(unittest.TestCase):
    """The engine's own judged scenarios obey the same rules."""

    def test_engine_judged_scenarios_are_measured_and_off_the_gate(self):
        from gentar.toml_scenario import load_dir
        scen = ROOT / "coordinator" / "scenarios"
        if not scen.exists():
            self.skipTest("scenarios/ is not in the image build context")
        wf = (ROOT / ".github" / "workflows" / "gentar.yml")
        gate = wf.read_text() if wf.exists() else ""
        for s in load_dir(scen).values():
            if not s.uses_judge:
                continue
            self.assertEqual(s.data, "synthetic", s.name)
            self.assertNotIn(f'"{s.name}"', gate.split("ALL=")[1].split("\n")[0] if "ALL=" in gate else "")
            for i, t in enumerate(s.turns):
                if "judge" in t:
                    for label in ("yes", "no"):
                        n = len(list((scen / "judge-fixtures" / s.name / str(i) / label).glob("*.txt")))
                        self.assertGreaterEqual(n, 3, f"{s.name} turn {i} {label}")


if __name__ == "__main__":
    unittest.main()

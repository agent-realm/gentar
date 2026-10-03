"""Kit fixes queued after v0.9.0 (claude-playbooks-ac, 2026-09-30).

1. A workflow_dispatch ON a tag ref is a dispatch: it used to hit the
   release rule and plan nothing, so a drift run of a release read
   "success" with the arena skipped (and a dispatch naming suites was
   swallowed the same way). Tag rules are for tag pushes.
2. A sweep that skips judged suites for want of TYPESAFE_API_KEY says so
   once more at the end, and as an Actions warning, since a green phase 2
   may not have run them.
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
PLAN = KIT / "plan.py"

POLICY = """
[phase1]
floor = ["fast"]
[phase2]
on = ["dispatch", "arena", "rc"]
"""


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_091", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class DispatchOnTagTest(unittest.TestCase):

    def setUp(self):
        self.p = load_plan()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scenarios").mkdir()
        for s in ("fast", "slow"):
            (self.tmp / "scenarios" / f"{s}.toml").write_text(f'[scenario]\nname = "{s}"\n')
        self.p.SCENARIOS = self.tmp / "scenarios"
        (self.tmp / "policy.toml").write_text(POLICY)
        self.pol = self.p.load_policy(self.tmp / "policy.toml")

    def plan(self, pol=None, **env):
        base = {"GITHUB_REPOSITORY": "o/r", "DEFAULT_BRANCH": "main"}
        base.update(env)
        return self.p.plan(base, pol or self.pol)

    def test_a_dispatch_on_a_release_tag_is_phase_2(self):
        r = self.plan(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/tags/v3.24.0")
        self.assertEqual(r["bench"], "phase2")

    def test_a_dispatch_naming_suites_on_a_tag_runs_those(self):
        r = self.plan(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/tags/v3.24.0",
                      SCENARIO_INPUT="slow")
        self.assertEqual((r["bench"], r["suites"]), ("targeted", ["slow"]))

    def test_dispatch_not_a_trigger_still_plans_nothing(self):
        (self.tmp / "policy.toml").write_text(POLICY.replace('"dispatch", ', ""))
        pol = self.p.load_policy(self.tmp / "policy.toml")
        r = self.plan(pol, GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/tags/v3.24.0")
        self.assertEqual(r["bench"], "none")

    def test_the_tag_push_itself_is_unchanged(self):
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/v3.24.0")
        self.assertEqual(r["bench"], "none")
        self.assertIn("release-gate.sh", r["reason"])
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/v3.24.0-rc1")
        self.assertEqual(r["bench"], "phase2")


@unittest.skipUnless((KIT / "run.sh").exists(), "the kit is not in the image build context")
class SweepSummaryTest(unittest.TestCase):

    def sweep(self, **env):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        shutil.copytree(KIT, repo / "gentar")
        shutil.rmtree(repo / "gentar" / "scenarios")
        (repo / "gentar" / "scenarios").mkdir()
        (repo / "gentar" / "policy.toml").unlink(missing_ok=True)
        base = '[scenario]\nsubject = "x"\n'
        (repo / "gentar" / "scenarios" / "plain.toml").write_text(
            base + '[oracle]\nsteps = ["true"]\n')
        (repo / "gentar" / "scenarios" / "judged.toml").write_text(
            base + 'data = "synthetic"\n[driver]\ncommand = "bash"\n'
            '[[driver.turns]]\ntype = "expect"\njudge = { question = "q?", p_min = 0.8, hold = 2 }\n')
        e = dict(os.environ, GENTAR_REPO_URL=str(tmp / "no-engine"), **env)
        for k in ("TYPESAFE_API_KEY", "GITHUB_EVENT_NAME", "CI"):
            e.pop(k, None)
        e.update(env)
        return subprocess.run(["/bin/bash", "gentar/run.sh", "--sweep"], cwd=repo, env=e,
                              capture_output=True, text=True)

    def test_skipped_judged_suites_are_summarised(self):
        r = self.sweep()
        self.assertIn("sweep summary: 1 judged suite(s) skipped, TYPESAFE_API_KEY is not set: "
                      "judged", r.stderr)
        self.assertIn("sweep: plain", r.stderr)
        self.assertNotIn("::warning", r.stdout)

    def test_in_actions_it_is_a_warning_annotation(self):
        r = self.sweep(GITHUB_ACTIONS="true")
        self.assertIn("::warning title=judged suites skipped::1 judged suite(s) skipped", r.stdout)

    def test_no_summary_when_nothing_judged_was_skipped(self):
        r = self.sweep(TYPESAFE_API_KEY="set-for-the-test")
        self.assertNotIn("sweep summary", r.stderr)


if __name__ == "__main__":
    unittest.main()

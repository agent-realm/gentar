"""GENTAR_CI_RUNNER: the kit's plan and checks jobs on a self-hosted runner.

agent-realm ran out of GitHub-hosted minutes (September 2026) and every
subject there stopped at `plan` (ubuntu-latest). The variable moves the two
bench-free jobs to a runner the subject names, without touching the bench job
and without letting a fork's code or the checks reach the `arena` runner.
"""

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "subject-template" / "gentar" / "plan.py"
WORKFLOW = ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml"

POLICY = """
[phase1]
checks = true
bench = "declared"
floor = ["fast"]
"""
SELF = '["self-hosted", "linux-ci"]'


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_ci", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class CiRunnerTest(unittest.TestCase):

    def setUp(self):
        self.p = load_plan()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scenarios").mkdir()
        (self.tmp / "scenarios" / "fast.toml").write_text('[scenario]\nname = "fast"\nsubject = "x"\n')
        self.p.SCENARIOS = self.tmp / "scenarios"

    def policy(self, text=POLICY):
        f = self.tmp / "policy.toml"
        f.write_text(text)
        return self.p.load_policy(f)

    def plan(self, runner=None, policy="default", **env):
        base = {"GITHUB_REPOSITORY": "o/r", "DEFAULT_BRANCH": "main",
                "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}
        if runner is not None:
            base["GENTAR_CI_RUNNER"] = runner
        base.update(env)
        return self.p.plan(base, self.policy() if policy == "default" else policy)

    def test_unset_is_github_hosted_as_before(self):
        r = self.plan()
        self.assertEqual((r["os"], r["runner"]), (["ubuntu-latest"], "github-hosted"))

    def test_set_runs_the_checks_there_and_says_so(self):
        r = self.plan(SELF)
        self.assertEqual(r["os"], ["self-hosted+linux-ci"])
        self.assertEqual(r["runner"], '["self-hosted", "linux-ci"]')
        self.assertTrue(r["checks"])
        self.assertEqual(r["bench"], "targeted")          # the bench job is unaffected
        self.assertEqual(self.plan('"linux-ci"')["os"], ["linux-ci"])

    def test_malformed_values_are_refused(self):
        for bad in ("linux-ci", "[]", "[1]", '{"a": 1}', '["a b"]', '["x;rm"]', "null", "3"):
            with self.subTest(bad=bad), self.assertRaises(self.p.Refuse):
                self.plan(bad)

    def test_the_bench_runner_is_never_named(self):
        # any case, any label containing it: runner labels match case-
        # insensitively, so `Arena` is the bench runner (Codex)
        for bad in ('["self-hosted", "arena"]', '"arena"', '["self-hosted", "Arena"]',
                    '"ARENA"', '["arena-ci"]'):
            with self.subTest(bad=bad), self.assertRaisesRegex(self.p.Refuse, "arena"):
                self.plan(bad)

    def test_macos_checks_with_a_self_hosted_runner_are_refused(self):
        pol = self.policy(POLICY + 'os = ["ubuntu-latest", "macos-latest"]\n')
        with self.assertRaisesRegex(self.p.Refuse, "macos-latest"):
            self.plan(SELF, policy=pol)
        self.assertEqual(self.plan(policy=pol)["os"], ["ubuntu-latest", "macos-latest"])

    def test_a_fork_pr_runs_nothing_on_a_self_hosted_runner(self):
        fork = dict(GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/1/merge",
                    PR_HEAD_REPO="stranger/r")
        r = self.plan(SELF, **fork)
        self.assertEqual((r["checks"], r["bench"]), (False, "none"))
        self.assertTrue(self.plan(**fork)["checks"])       # hosted: checks as before
        r = self.plan(SELF, policy=None, **fork)            # also without a policy.toml
        self.assertEqual((r["checks"], r["bench"]), (False, "none"))

    def test_the_runner_line_is_emitted(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.p.emit(self.plan(SELF))
        self.assertIn('runner=["self-hosted", "linux-ci"]\n', buf.getvalue())


@unittest.skipUnless(WORKFLOW.exists(), "the kit is not in the image build context")
class WorkflowTest(unittest.TestCase):
    """The workflow text, which --check keeps byte-identical in every subject."""

    def job(self, name):
        text = WORKFLOW.read_text()
        start = text.index(f"\n  {name}:\n")
        nxt = re.search(r"\n  [a-z][a-z0-9_-]*:\n", text[start + 1:])
        return text[start:start + 1 + nxt.start()] if nxt else text[start:]

    def test_plan_and_checks_read_the_variable(self):
        self.assertIn("runs-on: ${{ vars.GENTAR_CI_RUNNER && fromJSON(vars.GENTAR_CI_RUNNER)"
                      " || 'ubuntu-latest' }}", self.job("plan"))
        self.assertIn("runs-on: ${{ vars.GENTAR_CI_RUNNER && fromJSON(vars.GENTAR_CI_RUNNER)"
                      " || matrix.os }}", self.job("checks"))
        self.assertIn("GENTAR_CI_RUNNER: ${{ vars.GENTAR_CI_RUNNER }}", self.job("plan"))

    def test_an_arena_label_is_refused_before_any_job_is_scheduled(self):
        # runs-on would start plan ON the bench runner, running the PR's
        # plan.py there before plan.py could refuse (Codex)
        guard = "contains(vars.GENTAR_CI_RUNNER, 'arena')"
        refused = self.job("ci-runner-refused")
        self.assertIn(f"if: ${{{{ {guard} }}}}", refused)
        self.assertIn("exit 2", refused)
        self.assertNotIn("GENTAR_CI_RUNNER)", refused.split("runs-on:")[1].split("\n")[0])
        self.assertIn(f"!{guard}", self.job("plan"))
        self.assertIn(f"!{guard}", self.job("checks"))

    def test_the_bench_stays_on_arena(self):
        bench = self.job("bench")
        self.assertIn("runs-on: [self-hosted, arena]", bench)
        self.assertNotIn("GENTAR_CI_RUNNER", bench)

    def test_plan_is_skipped_for_a_fork_when_self_hosted(self):
        plan = self.job("plan")
        cond = plan[plan.index("    if:"):plan.index("    outputs:")]
        for part in ("!vars.GENTAR_CI_RUNNER", "github.event_name != 'pull_request'",
                     "github.event.pull_request.head.repo.full_name == github.repository"):
            self.assertIn(part, cond)

    def test_the_host_changing_step_is_hosted_only(self):
        checks = self.job("checks")
        step = checks[checks.index("- name: make the runner bench-like"):]
        step = step[:step.index("run: |")]
        self.assertIn("if: runner.environment == 'github-hosted'", step)


if __name__ == "__main__":
    unittest.main()

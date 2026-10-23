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

    def test_a_bench_runner_with_its_own_label_is_never_named(self):
        # agentmux's bench runner carries `agentmux-lab`, not `arena`
        for bad in ('["self-hosted", "agentmux-lab"]', '["self-hosted", "AgentMux-Lab"]',
                    '"agentmux-lab-ci"'):
            with self.subTest(bad=bad), self.assertRaisesRegex(self.p.Refuse, "agentmux-lab"):
                self.plan(bad, GENTAR_BENCH_LABEL="agentmux-lab")
        with self.assertRaisesRegex(self.p.Refuse, "'arena'"):     # arena stays refused
            self.plan('["self-hosted", "arena"]', GENTAR_BENCH_LABEL="agentmux-lab")
        self.assertEqual(self.plan(SELF, GENTAR_BENCH_LABEL="agentmux-lab")["runner"],
                         '["self-hosted", "linux-ci"]')
        with self.assertRaisesRegex(self.p.Refuse, "GENTAR_BENCH_LABEL must be one"):
            self.plan(SELF, GENTAR_BENCH_LABEL="a b")

    def test_a_json_escape_is_refused(self):
        # runs-on decodes, the guard reads raw text: "\u0061rena" named the
        # bench runner past both (Codex on #98). No label needs an escape,
        # so any backslash is refused, even in a harmless label.
        for bad in ('["self-hosted", "agentmux\\u002dlab"]', '"\\u0061rena"',
                    '["self-hosted", "linux\\u002dci"]'):
            with self.subTest(bad=bad), self.assertRaisesRegex(self.p.Refuse, "JSON escape"):
                self.plan(bad, GENTAR_BENCH_LABEL="agentmux-lab")

    def test_default_labels_alone_are_refused(self):
        # every self-hosted runner carries them, the bench runner included (SB03)
        for bad in ('["self-hosted", "linux"]', '"self-hosted"', '["self-hosted", "Linux", "X64"]',
                    '["linux", "arm64"]'):
            with self.subTest(bad=bad), self.assertRaisesRegex(self.p.Refuse, "default runner labels"):
                self.plan(bad)
        for good in (SELF, '["self-hosted", "linux", "ci-box"]', '"ubuntu-24.04"'):
            with self.subTest(good=good):
                self.plan(good)

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

    GUARD = ("contains(vars.GENTAR_CI_RUNNER, 'arena') || contains(vars.GENTAR_CI_RUNNER, '\\') || "
             "(vars.GENTAR_BENCH_LABEL != '' && contains(vars.GENTAR_CI_RUNNER, vars.GENTAR_BENCH_LABEL))")

    def test_the_bench_label_is_refused_before_any_job_is_scheduled(self):
        # runs-on would start plan ON the bench runner, running the PR's
        # plan.py there before plan.py could refuse (Codex). `arena`, and the
        # label GENTAR_BENCH_LABEL names (agentmux-lab), in all three places.
        # The `!= ''` matters: contains(x, '') is true for every x. The
        # backslash: runs-on decodes JSON escapes this raw check cannot see.
        refused = self.job("ci-runner-refused")
        self.assertIn(f"if: ${{{{ {self.GUARD} }}}}", refused)
        self.assertIn("exit 2", refused)
        self.assertNotIn("GENTAR_CI_RUNNER)", refused.split("runs-on:")[1].split("\n")[0])
        self.assertIn(f"!({self.GUARD})", self.job("plan"))
        self.assertIn(f"!({self.GUARD})", self.job("checks"))
        self.assertIn("GENTAR_BENCH_LABEL: ${{ vars.GENTAR_BENCH_LABEL }}", self.job("plan"))

    def test_the_bench_runs_on_arena_or_the_bench_label(self):
        bench = self.job("bench")
        self.assertIn("runs-on: [self-hosted, \"${{ vars.GENTAR_BENCH_LABEL || 'arena' }}\"]", bench)
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

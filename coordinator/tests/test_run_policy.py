"""The run policy: which suites run when, decided once (subject-template/gentar/plan.py).

The pilot's policy: phase 1 on every PR and main push, phase 2 (the full
regression) only on dispatch, the `arena` tag, or a release candidate; a
release is gated on a green phase 2 of its commit. These tests pin the
planner to that, and to its safety rules: a fork's PR never gets a bench,
a bad name in a PR body is refused before a bench is spent, and an unknown
policy key is refused rather than silently defaulted.

The kit lives outside the coordinator image's build context, so inside
`docker build` these skip; they run from a checkout.
"""

import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "subject-template" / "gentar" / "plan.py"
WORKFLOW = ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml"


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


POLICY = """
[phase1]
checks = true
bench = "declared"
floor = ["fast"]
setup = { go = "1.21" }
[phase2]
on = ["dispatch", "arena", "rc"]
"""


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class PlanTest(unittest.TestCase):

    def setUp(self):
        self.p = load_plan()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scenarios").mkdir()
        for s in ("fast", "slow", "auth"):
            (self.tmp / "scenarios" / f"{s}.toml").write_text(
                f'[scenario]\nname = "{s}"\nsubject = "x"\n')
        self.p.SCENARIOS = self.tmp / "scenarios"

    def policy(self, text=POLICY):
        f = self.tmp / "policy.toml"
        f.write_text(text)
        return self.p.load_policy(f)

    def plan(self, policy="default", **env):
        pol = self.policy() if policy == "default" else policy
        base = {"GITHUB_REPOSITORY": "o/r", "DEFAULT_BRANCH": "main"}
        base.update(env)
        return self.p.plan(base, pol)

    def pr(self, body="", fork=False, **kw):
        return self.plan(GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/1/merge",
                         PR_HEAD_REPO="stranger/r" if fork else "o/r", PR_BODY=body, **kw)

    # --- phase 1 ---------------------------------------------------------

    def test_pr_with_bench_off_is_checks_only(self):
        r = self.pr(policy=self.policy(POLICY.replace('"declared"', '"off"')),
                    body="gentar: slow")
        self.assertTrue(r["checks"])
        self.assertEqual(r["bench"], "none")

    def test_pr_declared_runs_floor_plus_what_it_names(self):
        r = self.pr(body="Fixes the login.\n\ngentar: auth fast\n")
        self.assertEqual((r["bench"], r["suites"]), ("targeted", ["fast", "auth"]))
        self.assertTrue(r["checks"])

    def test_a_fork_pr_never_gets_a_bench_whatever_the_policy(self):
        r = self.pr(body="gentar: slow", fork=True)
        self.assertEqual(r["bench"], "none")
        self.assertTrue(r["checks"])          # bench-free checks still run

    def test_a_pr_body_cannot_name_a_missing_or_hostile_suite(self):
        for body in ("gentar: nope", "gentar: x;rm", "gentar: $(id)"):
            with self.subTest(body=body), self.assertRaises(self.p.Refuse):
                self.pr(body=body)

    def test_main_push_is_phase_1_checks_plus_floor(self):
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main")
        self.assertEqual((r["checks"], r["bench"], r["suites"]), (True, "targeted", ["fast"]))

    def test_main_push_with_no_floor_puts_nothing_on_the_bench(self):
        pol = self.policy(POLICY.replace('floor = ["fast"]', "floor = []"))
        r = self.plan(pol, GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main")
        self.assertEqual((r["checks"], r["bench"]), (True, "none"))

    def test_the_default_branch_is_the_repos_not_always_main(self):
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/trunk",
                      DEFAULT_BRANCH="trunk")
        self.assertEqual(r["bench"], "targeted")
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main",
                      DEFAULT_BRANCH="trunk")
        self.assertEqual(r["bench"], "none")

    # --- phase 2 and targeted -------------------------------------------

    def test_arena_tag_is_phase_2(self):
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/arena")
        self.assertEqual(r["bench"], "phase2")
        self.assertFalse(r["checks"])

    def test_release_candidate_is_phase_2_and_a_release_runs_nothing(self):
        rc = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/v1.4.0-rc1")
        self.assertEqual(rc["bench"], "phase2")
        rel = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/v1.4.0")
        self.assertEqual(rel["bench"], "none")
        self.assertIn("release-gate", rel["reason"])

    def test_phase_2_triggers_are_the_policys(self):
        pol = self.policy(POLICY.replace('on = ["dispatch", "arena", "rc"]', 'on = ["dispatch"]'))
        for ref in ("refs/tags/arena", "refs/tags/v2.0.0-rc3"):
            with self.subTest(ref=ref):
                self.assertEqual(self.plan(pol, GITHUB_EVENT_NAME="push",
                                           GITHUB_REF=ref)["bench"], "none")
        self.assertEqual(self.plan(pol, GITHUB_EVENT_NAME="workflow_dispatch",
                                   GITHUB_REF="refs/heads/main")["bench"], "phase2")

    def test_keyword_tag_is_targeted_never_phase_2(self):
        r = self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/arena-slow")
        self.assertEqual((r["bench"], r["suites"]), ("targeted", ["slow"]))
        with self.assertRaises(self.p.Refuse):
            self.plan(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/arena-missing")

    def test_dispatch_naming_suites_is_targeted(self):
        r = self.plan(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/heads/main",
                      SCENARIO_INPUT="slow auth")
        self.assertEqual((r["bench"], r["suites"]), ("targeted", ["slow", "auth"]))

    def test_other_branches_and_events_run_nothing(self):
        self.assertEqual(self.plan(GITHUB_EVENT_NAME="push",
                                   GITHUB_REF="refs/heads/feature")["bench"], "none")
        self.assertEqual(self.plan(GITHUB_EVENT_NAME="schedule",
                                   GITHUB_REF="refs/heads/main")["bench"], "none")

    # --- no policy: the 0.3.x kit, unchanged ------------------------------

    def test_without_a_policy_the_03_behaviour_holds(self):
        cases = [
            (dict(GITHUB_EVENT_NAME="pull_request", PR_HEAD_REPO="o/r",
                  GITHUB_REF="refs/pull/1/merge"), "phase2", []),
            (dict(GITHUB_EVENT_NAME="pull_request", PR_HEAD_REPO="o/r",
                  GITHUB_REF="refs/pull/1/merge", PR_BODY="gentar: slow",
                  GENTAR_FLOOR="fast"), "targeted", ["fast", "slow"]),
            (dict(GITHUB_EVENT_NAME="pull_request", PR_HEAD_REPO="x/r",
                  GITHUB_REF="refs/pull/1/merge"), "none", []),
            (dict(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main"), "phase2", []),
            (dict(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/feature"), "none", []),
            (dict(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/v1.0.0"), "phase2", []),
            (dict(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/tags/arena-auth"),
             "targeted", ["auth"]),
        ]
        for env, bench, suites in cases:
            with self.subTest(env=env):
                r = self.plan(None, **env)
                self.assertEqual((r["bench"], r["suites"]), (bench, suites))
                self.assertFalse(r["checks"])

    # --- the policy file itself -------------------------------------------

    def test_a_typo_is_refused_not_defaulted(self):
        bad = [
            POLICY.replace("bench =", "benh ="),                        # unknown key
            POLICY + "\n[phase3]\n",                                    # unknown table
            POLICY.replace('"declared"', '"yes"'),                      # bad value
            POLICY.replace('go = "1.21"', 'rust = "1.80"'),             # unknown tool
            POLICY.replace('floor = ["fast"]', 'floor = ["gone"]'),     # missing suite
            POLICY.replace('"rc"]', '"nightly"]'),                      # unknown trigger
            POLICY + "max_age_days = -1\n",                             # negative
            POLICY.replace("checks = true", 'checks = "yes"'),         # not a bool
        ]
        for text in bad:
            with self.subTest(text=text[-40:]), self.assertRaises(self.p.Refuse):
                self.policy(text)

    def test_check_os_defaults_to_ubuntu_and_takes_macos(self):
        self.assertEqual(self.pr()["os"], ["ubuntu-latest"])
        pol = self.policy(POLICY.replace('setup = { go = "1.21" }',
                                         'setup = { go = "1.21" }\nos = ["ubuntu-latest", "macos-latest"]'))
        self.assertEqual(self.pr(policy=pol)["os"], ["ubuntu-latest", "macos-latest"])

    def test_check_os_must_be_github_hosted(self):
        # the checks job runs PR code: a self-hosted label here would put it
        # on the runner the bench job guards
        for bad in ('["self-hosted"]', '["arena"]', '["windows-latest"]', "[]"):
            with self.subTest(os=bad), self.assertRaises(self.p.Refuse):
                self.policy(POLICY.replace('setup = { go = "1.21" }',
                                           f'setup = {{ go = "1.21" }}\nos = {bad}'))

    def test_setup_reaches_the_plan(self):
        r = self.pr()
        self.assertEqual(r["setup"], {"go": "1.21"})

    def test_emit_writes_github_output(self):
        out = self.tmp / "gh_output"
        os.environ["GITHUB_OUTPUT"] = str(out)
        try:
            with redirect_stdout(io.StringIO()):
                self.p.emit(self.pr(body="gentar: auth"))
        finally:
            del os.environ["GITHUB_OUTPUT"]
        lines = dict(l.split("=", 1) for l in out.read_text().splitlines())
        self.assertEqual(lines["bench"], "targeted")
        self.assertEqual(lines["suites"], "fast auth")
        self.assertEqual(lines["checks"], "true")
        self.assertEqual(lines["setup_go"], "1.21")
        self.assertEqual(lines["setup_node"], "")
        self.assertEqual(json.loads(lines["os"]), ["ubuntu-latest"])

    # --- lint -------------------------------------------------------------

    def test_lint_flags_a_flat_endpoint_pair_and_not_a_nested_one(self):
        (self.tmp / "scenarios" / "auth.toml").write_text(
            '[scenario]\nname = "auth"\n'
            'credentials = ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]\n')
        self.p.HERE = self.tmp
        problems = self.p.lint(self.policy(), self.tmp / "no-engine")
        self.assertEqual(len(problems), 1)
        self.assertIn("auth.toml", problems[0])
        (self.tmp / "scenarios" / "auth.toml").write_text(
            '[scenario]\nname = "auth"\n'
            'credentials = ["ANTHROPIC_API_KEY", ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]]\n')
        self.assertEqual(self.p.lint(self.policy(), self.tmp / "no-engine"), [])

    def test_lint_reports_kit_drift_unless_allowed(self):
        repo = self.tmp / "repo"
        (repo / "gentar").mkdir(parents=True)
        engine = self.tmp / "engine"
        (engine / "subject-template" / "gentar").mkdir(parents=True)
        (engine / "subject-template" / "gentar" / "run.sh").write_text("kit\n")
        (repo / "gentar" / "run.sh").write_text("edited\n")
        self.p.HERE = repo / "gentar"
        with redirect_stdout(io.StringIO()):
            problems = self.p.lint(self.policy(), engine)
        self.assertTrue(any("gentar/run.sh" in p for p in problems), problems)
        allowed = self.policy(POLICY + '\n[check]\nallow_drift = ["gentar/run.sh"]\n')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.p.lint(allowed, engine), [])
        (repo / "gentar" / "run.sh").write_text("kit\n")
        self.assertEqual(self.p.lint(self.policy(), engine), [])

    def test_lint_allows_the_optional_kit_files_to_be_absent(self):
        # a central-dispatch subject has no own-arena workflow; a repo that
        # never releases has no release gate. Required ones still fail.
        repo = self.tmp / "repo2"
        (repo / "gentar").mkdir(parents=True)
        engine = self.tmp / "engine2"
        for f in ("gentar/run.sh", "gentar/release-gate.sh"):
            (engine / "subject-template" / f).parent.mkdir(parents=True, exist_ok=True)
            (engine / "subject-template" / f).write_text("kit\n")
        (engine / "subject-template/.github/workflows").mkdir(parents=True)
        (engine / "subject-template/.github/workflows/gentar-arena.yml").write_text("kit\n")
        (repo / "gentar" / "run.sh").write_text("kit\n")
        self.p.HERE = repo / "gentar"
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.p.lint(self.policy(), engine), [])
        self.assertIn("not present", out.getvalue())
        (repo / "gentar" / "run.sh").unlink()
        with redirect_stdout(io.StringIO()):
            problems = self.p.lint(self.policy(), engine)
        self.assertTrue(any("gentar/run.sh: missing" in p for p in problems), problems)


@unittest.skipUnless(WORKFLOW.exists(), "the kit is not in the image build context")
class WorkflowInvariantTest(unittest.TestCase):
    """PR code reaches the self-hosted runner only through the plan, and
    never from a fork. Checked on the kit's workflow text, which --check
    then holds every adopter to byte for byte."""

    def jobs(self):
        text = WORKFLOW.read_text()
        body = text.split("\njobs:\n", 1)[1]
        out, name = {}, None
        for line in body.splitlines():
            if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
                name = line.strip()[:-1]
                out[name] = ""
            elif name:
                out[name] += line + "\n"
        return out

    def test_only_the_bench_job_names_a_self_hosted_runner_and_it_is_gated(self):
        # Literally: plan and checks reach a self-hosted runner only through
        # GENTAR_CI_RUNNER (plan.py refuses the `arena` label in it), and a
        # fork's PR skips plan when that is set (test_ci_runner).
        jobs = self.jobs()
        literal = [j for j, t in jobs.items() if re.search(r"runs-on: \[self-hosted", t)]
        self.assertEqual(literal, ["bench"])
        self.assertEqual([j for j, t in jobs.items() if "arena]" in t and "runs-on" in t], ["bench"])
        bench = jobs["bench"]
        self.assertIn("needs: plan", bench)
        self.assertIn("needs.plan.outputs.bench != 'none'", bench)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", bench)

    def test_plan_and_checks_are_github_hosted_unless_the_variable_says(self):
        # unset: plan on ubuntu-latest, checks on the policy's [phase1] os,
        # which plan.py restricts to GitHub-hosted labels (PlanTest covers it)
        jobs = self.jobs()
        self.assertIn("|| 'ubuntu-latest' }}", jobs["plan"])
        self.assertIn("|| matrix.os }}", jobs["checks"])
        self.assertIn("os: ${{ fromJSON(needs.plan.outputs.os) }}", jobs["checks"])
        for j in ("plan", "checks"):
            runs_on = re.search(r"runs-on: (.*)", jobs[j]).group(1)
            self.assertEqual(re.sub(r"\|\| .*", "", runs_on).strip(),
                             "${{ vars.GENTAR_CI_RUNNER && fromJSON(vars.GENTAR_CI_RUNNER)")

    def test_pushes_to_any_branch_reach_the_planner(self):
        # the default branch is the repo's (main, master, trunk); only the
        # planner knows it, so the trigger must not hard-code `main`
        text = WORKFLOW.read_text()
        self.assertIn("branches: ['**']", text)
        self.assertNotIn("branches: [main]", text)

    def test_only_pull_requests_share_a_concurrency_group(self):
        # a shared group evicts the PENDING run when a newer one queues:
        # repository-wide it dropped keyword and phase 2 runs (claude-
        # playbooks); per-ref it still dropped a phase 2 dispatched on main
        # behind the next main push (Codex). Only a PR's pushes may replace
        # each other; everything else gets a group of its own.
        text = WORKFLOW.read_text()
        self.assertIn("group: gentar-arena-${{ github.event_name == 'pull_request' "
                      "&& github.ref || github.run_id }}", text)
        self.assertNotIn("group: gentar-arena-${{ github.ref }}", text)


if __name__ == "__main__":
    unittest.main()

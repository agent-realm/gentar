"""[secrets] route: a subject's own secrets reach its suites BY NAME.

2026-10-08 (AK47 via agent-realm-lead, for cockpit's
AGENT_KOMMANDER_READ_KEY_B64): the kit's workflow named every secret it
passes, so a subject needing one more had to edit a kit file and lose
byte-identity. Now the adopter declares names in policy.toml; the bench
job looks each one up by name in a fixed slot (never toJSON(secrets));
run.sh clears the slots at once, gives each value its declared name, and
forwards a name only to suites that declare it. Values are never printed.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
PLAN = KIT / "plan.py"
RUN = KIT / "run.sh"
WORKFLOW = ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml"

SECRET = "s3cr3t-value-7f1d"          # must never appear in any output


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_route", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def kit_repo(policy, scenarios):
    """A throwaway subject repo holding the kit, a policy and scenarios."""
    tmp = Path(tempfile.mkdtemp())
    repo = tmp / "repo"
    shutil.copytree(KIT, repo / "gentar")
    shutil.rmtree(repo / "gentar" / "scenarios")
    (repo / "gentar" / "scenarios").mkdir()
    (repo / "gentar" / "policy.toml").write_text(policy)
    for name, body in scenarios.items():
        (repo / "gentar" / "scenarios" / f"{name}.toml").write_text(
            '[scenario]\nsubject = "x"\n' + body + '[oracle]\nsteps = ["true"]\n')
    return tmp, repo


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class RouteNamesTest(unittest.TestCase):

    def setUp(self):
        self.plan = load_plan()

    def names(self, route):
        return self.plan.route_names({"secrets": {"route": route}})

    def refused(self, route):
        with self.assertRaises(self.plan.Refuse):
            self.names(route)

    def test_declared_names_in_order(self):
        self.assertEqual(self.names(["SUBJECT_KEY", "OTHER_B64"]), ["SUBJECT_KEY", "OTHER_B64"])

    def test_absent_is_empty(self):
        self.assertEqual(self.plan.route_names(None), [])
        self.assertEqual(self.plan.route_names({"secrets": {"route": []}}), [])

    def test_no_more_names_than_slots(self):
        self.assertEqual(self.plan.ROUTE_SLOTS, 8)
        self.names([f"K{i}" for i in range(8)])
        self.refused([f"K{i}" for i in range(9)])

    def test_bad_names_are_refused(self):
        for bad in ("lower", "1LEADING", "HAS-DASH", "SPACE IN", "", "X;Y"):
            with self.subTest(name=bad):
                self.refused([bad])

    def test_reserved_names_are_refused(self):
        # the kit's own, GitHub's and the runner's, and names that steer the
        # arena's shell, loader, git, ssh, docker or python
        for bad in ("BENCH_SSH_KEY", "GENTAR_ROUTE_1", "GENTAR_BENCH_KEY", "GITHUB_TOKEN",
                    "ACTIONS_RUNTIME_TOKEN", "RUNNER_TEMP", "ANTHROPIC_API_KEY",
                    "TYPESAFE_API_KEY", "PATH", "HOME", "IFS", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
                    "BASH_ENV", "DOCKER_HOST", "GIT_SSH_COMMAND", "SSH_AUTH_SOCK",
                    "PYTHONPATH", "NODE_OPTIONS", "OTEL_EXPORTER_OTLP_ENDPOINT"):
            with self.subTest(name=bad):
                self.refused([bad])

    def test_duplicates_and_non_lists_are_refused(self):
        self.refused(["A_KEY", "A_KEY"])
        self.refused("A_KEY")
        self.refused([["A_KEY"]])

    def test_the_policy_loader_validates_the_route(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        good, bad = tmp / "good.toml", tmp / "bad.toml"
        good.write_text('[secrets]\nroute = ["SUBJECT_KEY"]\n')
        bad.write_text('[secrets]\nroute = ["GITHUB_TOKEN"]\n')
        self.assertEqual(self.plan.load_policy(good)["secrets"]["route"], ["SUBJECT_KEY"])
        with self.assertRaises(self.plan.Refuse):
            self.plan.load_policy(bad)
        typo = tmp / "typo.toml"
        typo.write_text('[secrets]\nroutes = ["SUBJECT_KEY"]\n')
        with self.assertRaises(self.plan.Refuse):
            self.plan.load_policy(typo)

    def test_the_template_policy_routes_nothing(self):
        self.assertEqual(self.plan.load_policy(KIT / "policy.toml")["secrets"]["route"], [])


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class PlanOutputTest(unittest.TestCase):

    def emit(self, policy):
        tmp, repo = kit_repo(policy, {"s1": 'credentials = ["SUBJECT_KEY"]\n'})
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
        env.update(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REF="refs/heads/main",
                   GITHUB_REPOSITORY="o/r", DEFAULT_BRANCH="main")
        r = subprocess.run(["python3", "gentar/plan.py", "plan"], cwd=repo, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(l.split("=", 1) for l in r.stdout.splitlines())

    def test_every_slot_is_an_output_named_or_empty(self):
        out = self.emit('[secrets]\nroute = ["SUBJECT_KEY", "OTHER_KEY"]\n')
        self.assertEqual(out["route"], "SUBJECT_KEY OTHER_KEY")
        self.assertEqual(out["route_1"], "SUBJECT_KEY")
        self.assertEqual(out["route_2"], "OTHER_KEY")
        for i in range(3, 9):
            self.assertEqual(out[f"route_{i}"], "")
        self.assertNotIn("route_9", out)

    def test_no_route_is_eight_empty_slots(self):
        out = self.emit('[phase2]\non = ["dispatch"]\n')
        self.assertEqual(out["route"], "")
        self.assertEqual([out[f"route_{i}"] for i in range(1, 9)], [""] * 8)

    def test_route_command_prints_names_only(self):
        tmp, repo = kit_repo('[secrets]\nroute = ["SUBJECT_KEY", "OTHER_KEY"]\n', {})
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = subprocess.run(["python3", "gentar/plan.py", "route"], cwd=repo,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "SUBJECT_KEY\nOTHER_KEY\n")


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class RouteLintTest(unittest.TestCase):

    def lint(self, policy, scenarios):
        tmp, repo = kit_repo(policy, scenarios)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        r = subprocess.run(["python3", "gentar/plan.py", "lint", str(tmp / "no-engine")],
                           cwd=repo, capture_output=True, text=True)
        return r.returncode, r.stderr

    def test_a_route_no_suite_declares_is_a_problem(self):
        rc, err = self.lint('[secrets]\nroute = ["NOBODY_KEY"]\n',
                            {"s1": 'credentials = ["SUBJECT_KEY"]\n'})
        self.assertEqual(rc, 1)
        self.assertIn("[secrets] route has NOBODY_KEY, but no suite declares it", err)

    def test_declared_as_credential_group_or_pass_env_is_clean(self):
        rc, err = self.lint('[secrets]\nroute = ["IN_GROUP", "PASSED"]\n',
                            {"s1": 'credentials = [["IN_GROUP", "SOME_URL"]]\n',
                             "s2": 'pass_env = ["PASSED"]\n'})
        self.assertEqual(rc, 0, err)


def workflow_steps():
    """{job: [step text, ...]} from the workflow text (no PyYAML)."""
    from tests.test_kit_keys import steps_by_job
    return steps_by_job()


@unittest.skipUnless(WORKFLOW.exists(), "the kit is not in the image build context")
class WorkflowSlotsTest(unittest.TestCase):

    def test_the_plan_job_outputs_every_slot(self):
        text = WORKFLOW.read_text()
        for i in range(1, 9):
            self.assertIn(f"      route_{i}: ${{{{ steps.plan.outputs.route_{i} }}}}\n", text)

    def test_the_run_step_looks_up_each_slot_by_its_declared_name(self):
        run = [s for s in workflow_steps()["bench"] if s.startswith("name: run suites")]
        self.assertEqual(len(run), 1)
        slots = re.findall(r"GENTAR_ROUTE_(\d+): \$\{\{ (.*?) \}\}", run[0])
        self.assertEqual([int(n) for n, _ in slots], list(range(1, 9)))
        for n, expr in slots:
            with self.subTest(slot=n):
                self.assertEqual(expr, f"needs.plan.outputs.route_{n} && "
                                       f"secrets[needs.plan.outputs.route_{n}] || ''")

    def test_slots_reach_no_other_step(self):
        for job, steps in workflow_steps().items():
            for s in steps:
                if s.startswith("name: run suites"):
                    continue
                with self.subTest(job=job, step=s.splitlines()[0]):
                    self.assertNotIn("GENTAR_ROUTE_", s)

    def test_the_whole_secret_set_is_never_handed_over(self):
        self.assertNotRegex(WORKFLOW.read_text(), r"toJSON\(\s*secrets\s*\)")

    def test_run_sh_has_as_many_slots(self):
        self.assertIn("ROUTE_SLOTS=8\n", RUN.read_text())


@unittest.skipUnless(RUN.exists(), "the kit is not in the image build context")
class RunShRouteTest(unittest.TestCase):

    POLICY = '[secrets]\nroute = ["SUBJECT_KEY", "OTHER_KEY"]\n'
    SCENARIOS = {"needs-key": 'credentials = ["SUBJECT_KEY"]\n', "plain": ""}

    def run_sh(self, *args, **env):
        tmp, repo = kit_repo(self.POLICY, self.SCENARIOS)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        e = {k: v for k, v in os.environ.items()
             if not k.startswith("GENTAR_ROUTE_")
             and k not in ("SUBJECT_KEY", "OTHER_KEY", "GITHUB_EVENT_NAME", "CI",
                           "GITHUB_ACTIONS", "TYPESAFE_API_KEY")}
        e.update(GENTAR_REPO_URL=str(tmp / "no-engine"), **env)
        r = subprocess.run(["/bin/bash", "gentar/run.sh", *args], cwd=repo, env=e,
                           capture_output=True, text=True)
        self.assertNotIn(SECRET, r.stdout + r.stderr, "a routed value was printed")
        return r

    def test_route_reports_names_and_state_never_values(self):
        r = self.run_sh("--route", GENTAR_ROUTE_1=SECRET)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("secret route: SUBJECT_KEY set, declared by: needs-key", r.stdout)
        self.assertIn("secret route: OTHER_KEY missing, declared by: no suite", r.stdout)

    def test_slots_are_cleared_and_names_not_exported(self):
        # A routed value is a variable of run.sh only, until a suite that
        # declares it is about to start; the slot itself is gone at once.
        r = self.run_sh("--route", GENTAR_ROUTE_1=SECRET)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("still in the environment", r.stderr)
        self.assertNotIn("(in the environment)", r.stdout)

    def test_a_value_in_an_unnamed_slot_is_dropped_by_number(self):
        r = self.run_sh("--route", GENTAR_ROUTE_5=SECRET)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("slot 5 holds a value but [secrets] route names no secret for it", r.stderr)

    def test_no_route_says_none(self):
        self.POLICY = '[phase2]\non = ["dispatch"]\n'
        r = self.run_sh("--route")
        self.assertIn("secret route: none", r.stdout)

    def test_a_sweep_sees_the_routed_credential(self):
        # The suite needing SUBJECT_KEY is picked only because the routed
        # value reached the sweep's credential check (the run then stops at
        # the missing engine, which is beside the point).
        r = self.run_sh("--sweep", GENTAR_ROUTE_1=SECRET)
        self.assertIn("sweep: needs-key plain", r.stderr)
        r = self.run_sh("--sweep")
        self.assertIn("skipping needs-key — no credential group of it is fully set", r.stderr)

    def test_routed_names_are_redacted_and_exported_only_when_declared(self):
        text = RUN.read_text()
        export = text[text.index("# Routed secrets ([secrets] route) leave this shell"):
                      text.index("FORWARD=()")]
        self.assertIn('grep -qx "$_n"', export)       # only names a suite declares
        self.assertIn('export "$_n"', export)
        self.assertEqual(text.count('export "$_n"'), 1, "exported somewhere else too")
        self.assertIn('REDACT_NAMES="$REDACT_NAMES $_n"', text)


if __name__ == "__main__":
    unittest.main()

"""The arena mirror: a PUBLIC repository's phase 2 runs in a private mirror.

2026-10-08 (D5, the pilot's "fix it"; root's design for claude-playbooks):
a public repository must have no self-hosted job at all, since a fork can
bring its own workflow to any runner registered there. The kit ships:

- [arena] bench = "mirror" in policy.toml, and a public variant of the
  workflow (plan + checks, GitHub-hosted) that --check holds it to;
- subject-template/mirror/arena/: the mirror's own workflow and
  verify-ref.sh (tests in test_verify_ref.py), whose bench job is the kit's
  bench job, checked out at the VERIFIED public commit;
- gentar/mirror.sh dispatch <sha>: runs the mirror, waits, and posts the
  commit status arena/phase2, which release-gate.sh reads with
  [phase2] evidence = "status".
"""

import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
PLAN = KIT / "plan.py"
KIT_WF = ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml"
PUBLIC_WF = ROOT / "subject-template" / "mirror" / "public" / ".github" / "workflows" / "gentar-arena.yml"
MIRROR_WF = ROOT / "subject-template" / "mirror" / "arena" / ".github" / "workflows" / "arena.yml"
MIRROR_SH = KIT / "mirror.sh"
GATE = KIT / "release-gate.sh"
SHA = "b" * 40

MIRROR_POLICY = """
[phase2]
evidence = "status"
[arena]
bench = "mirror"
mirror = "owner/repo-arena"
"""


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_mirror", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def jobs_of(path):
    """{job: (header lines, [step text, ...])} from a workflow (no PyYAML)."""
    out, job, in_jobs = {}, None, False
    for line in path.read_text().splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            job = m.group(1)
            out[job] = ([], [])
            in_steps, cur = False, None
            continue
        if job is None:
            continue
        if line.rstrip() == "    steps:":
            in_steps = True
            continue
        if not in_steps:
            out[job][0].append(line)
            continue
        if line.strip().startswith("#"):
            continue
        if line.startswith("      - "):
            cur = [line.strip()]
            out[job][1].append(cur)
        elif cur is not None and line.strip():
            cur.append(line.strip())
    return {j: (h, ["\n".join(s) for s in ss]) for j, (h, ss) in out.items()}


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class MirrorPolicyTest(unittest.TestCase):

    def setUp(self):
        self.plan = load_plan()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def load(self, text):
        p = self.tmp / "policy.toml"
        p.write_text(text)
        return self.plan.load_policy(p)

    def refused(self, text, words):
        with self.assertRaises(self.plan.Refuse) as cm:
            self.load(text)
        self.assertIn(words, str(cm.exception))

    def test_defaults_are_the_self_hosted_arena(self):
        p = self.load("[phase2]\non = [\"dispatch\"]\n")
        self.assertEqual(p["arena"], {"bench": "self-hosted", "mirror": ""})
        self.assertEqual(p["phase2"]["evidence"], "job")
        self.assertFalse(self.plan.mirror_mode(p))

    def test_mirror_mode_loads(self):
        p = self.load(MIRROR_POLICY)
        self.assertTrue(self.plan.mirror_mode(p))

    def test_mirror_mode_needs_its_mirror(self):
        self.refused("[phase2]\nevidence = \"status\"\n[arena]\nbench = \"mirror\"\n",
                     'needs [arena] mirror = "owner/name"')
        self.refused(MIRROR_POLICY.replace("owner/repo-arena", "not a repo"), "owner/name")

    def test_mirror_mode_has_no_bench_here(self):
        self.refused(MIRROR_POLICY + "[phase1]\nbench = \"declared\"\n", "no bench runner")
        (self.tmp / "s").mkdir()
        self.plan.SCENARIOS = self.tmp / "s"
        (self.tmp / "s" / "fast.toml").write_text("[scenario]\n")
        self.refused(MIRROR_POLICY + "[phase1]\nfloor = [\"fast\"]\n", "no bench runner")

    def test_mirror_mode_gates_releases_on_the_status(self):
        self.refused(MIRROR_POLICY.replace('evidence = "status"', ""),
                     'set [phase2] evidence = "status"')
        p = self.load(MIRROR_POLICY.replace('evidence = "status"', "release_gate = false"))
        self.assertEqual(p["phase2"]["evidence"], "job")

    def test_bad_values_are_refused(self):
        self.refused('[arena]\nbench = "cloud"\n', "[arena] bench must be")
        self.refused('[phase2]\nevidence = "artifact"\n', "[phase2] evidence must be")
        self.refused('[arena]\nbenhc = "mirror"\n', "unknown key")

    def test_drift_is_checked_against_the_public_variant(self):
        self.assertEqual(self.plan.kit_files(self.load(MIRROR_POLICY))[".github/workflows/gentar-arena.yml"],
                         "subject-template/mirror/public/.github/workflows/gentar-arena.yml")
        self.assertEqual(self.plan.kit_files(None)[".github/workflows/gentar-arena.yml"],
                         "subject-template/.github/workflows/gentar-arena.yml")
        self.assertIn("gentar/mirror.sh", self.plan.OPTIONAL_KIT_FILES)

    def plan_for(self, policy_text, **env):
        policy = self.load(policy_text)
        base = {"GITHUB_REPOSITORY": "owner/repo", "DEFAULT_BRANCH": "main"}
        return self.plan.plan({**base, **env}, policy)

    def test_nothing_here_reaches_a_bench(self):
        for env in ({"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main"},
                    {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/tags/arena"},
                    {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/tags/v1.0.0-rc1"},
                    {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"},
                    {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/1/merge",
                     "PR_HEAD_REPO": "owner/repo"}):
            with self.subTest(**env):
                res = self.plan_for(MIRROR_POLICY, **env)
                self.assertEqual(res["bench"], "none")
                self.assertEqual(res["suites"], [])
        res = self.plan_for(MIRROR_POLICY, GITHUB_EVENT_NAME="workflow_dispatch",
                            GITHUB_REF="refs/heads/main")
        self.assertIn("private mirror owner/repo-arena", res["reason"])

    def test_phase_1_checks_still_run(self):
        res = self.plan_for(MIRROR_POLICY, GITHUB_EVENT_NAME="pull_request",
                            GITHUB_REF="refs/pull/1/merge", PR_HEAD_REPO="owner/repo")
        self.assertTrue(res["checks"])

    def test_a_self_hosted_ci_runner_is_refused(self):
        with self.assertRaises(self.plan.Refuse):
            self.plan_for(MIRROR_POLICY, GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main",
                          GENTAR_CI_RUNNER='["self-hosted", "linux-ci"]')

    def test_config_commands(self):
        repo = self.tmp / "repo"
        shutil.copytree(KIT, repo / "gentar")
        (repo / "gentar" / "policy.toml").write_text(MIRROR_POLICY)
        run = lambda c: subprocess.run(["python3", "gentar/plan.py", c], cwd=repo,
                                       capture_output=True, text=True).stdout
        self.assertIn("evidence=status\n", run("gate-config"))
        self.assertEqual(run("arena-config"), "bench=mirror\nmirror=owner/repo-arena\n")


@unittest.skipUnless((ROOT / "examples" / "09-public-repo-mirror").exists(),
                     "examples/ is not in the image build context")
class ExampleNineTest(unittest.TestCase):

    def test_its_policy_is_a_clean_mirror_adoption(self):
        ex = ROOT / "examples" / "09-public-repo-mirror" / "gentar"
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        shutil.copytree(KIT, repo / "gentar")
        shutil.rmtree(repo / "gentar" / "scenarios")
        shutil.copytree(ex / "scenarios", repo / "gentar" / "scenarios")
        shutil.copy(ex / "policy.toml", repo / "gentar" / "policy.toml")
        r = subprocess.run(["python3", "gentar/plan.py", "lint", str(tmp / "no-engine")],
                           cwd=repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["python3", "gentar/plan.py", "arena-config"], cwd=repo,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout, "bench=mirror\nmirror=example-org/example-arena\n")


@unittest.skipUnless(PUBLIC_WF.exists(), "the kit is not in the image build context")
class PublicWorkflowTest(unittest.TestCase):

    def test_no_job_can_land_on_a_self_hosted_runner(self):
        jobs = jobs_of(PUBLIC_WF)
        self.assertEqual(sorted(jobs), ["checks", "plan"])
        for job, (head, _) in jobs.items():
            runs_on = [l.strip() for l in head if l.strip().startswith("runs-on:")]
            with self.subTest(job=job):
                self.assertEqual(len(runs_on), 1)
                self.assertIn(runs_on[0], ("runs-on: ubuntu-latest", "runs-on: ${{ matrix.os }}"))
        text = PUBLIC_WF.read_text()
        self.assertNotRegex(text, r"runs-on:.*(self-hosted|arena|GENTAR_CI_RUNNER)")

    def test_its_steps_are_the_default_workflows_own(self):
        kit, pub = jobs_of(KIT_WF), jobs_of(PUBLIC_WF)
        for job in ("plan", "checks"):
            with self.subTest(job=job):
                self.assertEqual(pub[job][1], kit[job][1])

    def test_no_secret_beyond_the_checks_own(self):
        secrets = set(re.findall(r"secrets\.([A-Z0-9_]+)", PUBLIC_WF.read_text()))
        self.assertEqual(secrets, {"GENTAR_CLONE_KEY"})


@unittest.skipUnless(MIRROR_WF.exists(), "the kit is not in the image build context")
class MirrorWorkflowTest(unittest.TestCase):

    def setUp(self):
        self.text = MIRROR_WF.read_text()
        self.jobs = jobs_of(MIRROR_WF)

    def test_it_runs_only_when_asked_or_scheduled(self):
        on = self.text[self.text.index("\non:"):self.text.index("\npermissions:")]
        self.assertIn("workflow_dispatch:", on)
        self.assertIn("schedule:", on)
        for trig in ("pull_request", "push:", "workflow_run", "repository_dispatch"):
            self.assertNotIn(trig, on)

    def test_the_commit_is_verified_on_a_hosted_runner_first(self):
        head, steps = self.jobs["plan"]
        self.assertIn("    runs-on: ubuntu-latest", head)
        self.assertTrue(steps[0].startswith("- uses: actions/checkout@v4"))
        self.assertIn("path: mirror", steps[0])
        self.assertNotIn("repository:", steps[0])          # the mirror itself
        self.assertIn("bash mirror/verify-ref.sh $flag", steps[1])
        self.assertIn("ref: ${{ steps.verify.outputs.sha }}", steps[2])

    def test_the_mirror_checkout_finds_verify_ref(self):
        self.assertTrue((MIRROR_WF.parents[2] / "verify-ref.sh").is_file())

    def test_branch_heads_come_only_from_the_mirrors_variable(self):
        self.assertIn("ALLOW: ${{ vars.GENTAR_ALLOW_BRANCH_HEADS }}", self.text)
        self.assertEqual(self.text.count("GENTAR_ALLOW_BRANCH_HEADS }}"), 1)
        self.assertIn('[ "$ALLOW" = true ] && flag=--allow-branch-heads', self.text)

    def test_an_input_sha_reaches_only_the_verifier(self):
        uses = [l for l in self.text.splitlines() if "inputs.sha" in l and not l.strip().startswith("#")]
        self.assertEqual([l.strip() for l in uses],
                         ["run-name: arena ${{ inputs.sha || 'default branch' }} ${{ inputs.request }}",
                          "SHA: ${{ inputs.sha }}"])
        _, steps = self.jobs["plan"]
        self.assertIn("SHA: ${{ inputs.sha }}", steps[1])

    def test_the_bench_job_is_the_kits_at_the_verified_commit(self):
        kit_steps = jobs_of(KIT_WF)["bench"][1]
        head, steps = self.jobs["bench"]
        self.assertIn("    runs-on: [self-hosted, arena]", head)
        self.assertIn("    needs: plan", head)
        checkout = [s for s in steps if s.startswith("- uses: actions/checkout@v4")]
        self.assertEqual(len(checkout), 1)
        self.assertIn("ref: ${{ needs.plan.outputs.sha }}", checkout[0])
        self.assertIn("repository: ${{ vars.GENTAR_PUBLIC_REPO }}", checkout[0])
        self.assertIn("persist-credentials: false", checkout[0])
        i = steps.index(checkout[0])
        self.assertTrue(steps[i + 1].startswith("- name: the verified commit, and only it"))
        rest = steps[:i] + steps[i + 2:]
        kit_rest = [s for s in kit_steps if not s.startswith("- uses: actions/checkout@v4")]
        self.assertEqual(rest[:len(kit_rest)], kit_rest)
        extra = rest[len(kit_rest):]
        self.assertEqual(len(extra), 2)
        self.assertTrue(all("needs.plan.outputs.bench == 'phase2'" in s for s in extra))

    def test_the_status_posts_only_for_phase_2_with_the_token(self):
        head, steps = self.jobs["status"]
        self.assertIn("needs.plan.outputs.bench == 'phase2'", "\n".join(head))
        self.assertIn("    runs-on: ubuntu-latest", head)
        self.assertIn("STATUS_TOKEN: ${{ secrets.GENTAR_STATUS_TOKEN }}", steps[0])
        self.assertIn('GH_TOKEN="$STATUS_TOKEN" gh api -X POST', steps[0])
        self.assertIn("context=arena/phase2", steps[0])

    def test_routes_are_the_mirrors_allowlist_narrowed_by_the_commit(self):
        _, steps = self.jobs["plan"]
        self.assertIn('python3 ../mirror/route.py gentar/policy.toml "$ROUTE_ALLOW"', steps[3])
        self.assertIn("ROUTE_ALLOW: ${{ vars.GENTAR_ROUTE_ALLOW }}", steps[3])
        self.assertIn("working-directory: subject", steps[3])
        self.assertEqual(self.text.count("GENTAR_ROUTE_ALLOW }}"), 1)
        for i in range(1, 9):
            self.assertIn(f"route_{i}: ${{{{ steps.plan.outputs.route_{i} }}}}", self.text)

    def test_the_plan_job_runs_none_of_the_public_trees_code(self):
        _, steps = self.jobs["plan"]
        for s in steps:
            with self.subTest(step=s.splitlines()[0]):
                self.assertNotRegex(s, r"(python3|bash|sh) gentar/|\./gentar/|gentar/(run|mirror)\.sh|plan\.py")


ROUTE_PY = ROOT / "subject-template" / "mirror" / "arena" / "route.py"


@unittest.skipUnless(ROUTE_PY.exists(), "the kit is not in the image build context")
class MirrorRouteTest(unittest.TestCase):
    """The mirror's GENTAR_ROUTE_ALLOW is the upper bound; a commit's
    policy can only narrow it (AK47, required before v0.10.0)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def route(self, policy, allow):
        f = self.tmp / "policy.toml"
        if policy is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(policy)
        out = self.tmp / "gh-output"
        out.unlink(missing_ok=True)
        r = subprocess.run([sys.executable, str(ROUTE_PY), str(f), allow], capture_output=True,
                           text=True, env={**os.environ, "GITHUB_OUTPUT": str(out)})
        slots = dict(l.split("=", 1) for l in r.stdout.splitlines())
        return r, slots, (out.read_text() if out.exists() else "")

    def test_only_names_both_sides_name_and_positions_hold(self):
        r, slots, out = self.route('[secrets]\nroute = ["A_KEY", "EXTRA_KEY", "C_KEY"]\n', "A_KEY C_KEY OTHER")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([slots[f"route_{i}"] for i in range(1, 9)],
                         ["A_KEY", "", "C_KEY", "", "", "", "", ""])
        self.assertEqual(out, r.stdout)
        self.assertIn("not routed: EXTRA_KEY", r.stderr)

    def test_an_empty_allowlist_routes_nothing(self):
        r, slots, _ = self.route('[secrets]\nroute = ["A_KEY"]\n', "")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(set(slots.values()), {""})
        self.assertIn("not routed: A_KEY", r.stderr)

    def test_no_policy_routes_nothing(self):
        r, slots, _ = self.route(None, "A_KEY")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(slots), 8)
        self.assertEqual(set(slots.values()), {""})

    def test_the_allowlist_never_hands_out_the_arenas_own(self):
        for bad in ("BENCH_SSH_KEY", "GENTAR_STATUS_TOKEN", "GITHUB_TOKEN", "lower", "A;B"):
            with self.subTest(name=bad):
                r, _, _ = self.route('[secrets]\nroute = ["A_KEY"]\n', f"A_KEY {bad}")
                self.assertEqual(r.returncode, 2)

    def test_a_malformed_commit_policy_is_refused(self):
        for bad in ('[secrets]\nroute = "A_KEY"\n', '[secrets\n', 'secrets = "none"\n',
                    'secrets = ["A_KEY"]\n',
                    '[secrets]\nroute = [%s]\n' % ", ".join(f'"K{i}"' for i in range(9))):
            with self.subTest(policy=bad):
                r, _, _ = self.route(bad, "A_KEY")
                self.assertEqual(r.returncode, 2)

    def test_a_branch_that_widens_its_own_route_gets_nothing_for_it(self):
        # End to end with branch heads admitted: a collaborator's branch adds
        # a secret name to its policy. verify-ref admits the branch; the
        # mirror's allowlist does not name the secret; so its slot is empty,
        # the refusal names it, and run.sh at that commit reports it missing.
        from tests.test_verify_ref import VERIFY, git
        srv, w = str(self.tmp / "srv.git"), str(self.tmp / "w")
        git("init", "-q", "--bare", srv)
        git("-C", srv, "symbolic-ref", "HEAD", "refs/heads/main")
        git("init", "-q", w)
        git("-C", w, "checkout", "-q", "-b", "main")
        shutil.copytree(KIT, Path(w) / "gentar", dirs_exist_ok=True)
        shutil.rmtree(Path(w) / "gentar" / "scenarios")
        (Path(w) / "gentar" / "scenarios").mkdir()
        (Path(w) / "gentar" / "scenarios" / "s.toml").write_text(
            '[scenario]\nsubject = "x"\npass_env = ["SUBJECT_KEY", "MIRROR_SECRET"]\n'
            '[oracle]\nsteps = ["true"]\n')
        (Path(w) / "gentar" / "policy.toml").write_text('[secrets]\nroute = ["SUBJECT_KEY"]\n')
        git("-C", w, "add", "-A")
        git("-C", w, "commit", "-q", "-m", "main")
        git("-C", w, "push", "-q", srv, "main")
        git("-C", w, "checkout", "-q", "-b", "widen")
        (Path(w) / "gentar" / "policy.toml").write_text(
            '[secrets]\nroute = ["SUBJECT_KEY", "MIRROR_SECRET"]\n')
        git("-C", w, "commit", "-q", "-am", "route one more")
        git("-C", w, "push", "-q", srv, "widen")
        sha = git("-C", w, "rev-parse", "HEAD")

        v = subprocess.run(["/bin/bash", str(VERIFY), "--allow-branch-heads", srv, sha],
                           capture_output=True, text=True)
        self.assertEqual(v.returncode, 0, v.stderr)          # the branch IS admitted
        r = subprocess.run([sys.executable, str(ROUTE_PY), f"{w}/gentar/policy.toml", "SUBJECT_KEY"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        slots = dict(l.split("=", 1) for l in r.stdout.splitlines())
        self.assertEqual((slots["route_1"], slots["route_2"]), ("SUBJECT_KEY", ""))
        self.assertEqual(r.stderr.strip(), "route: not allowed by this mirror "
                         "(GENTAR_ROUTE_ALLOW), so not routed: MIRROR_SECRET")
        # The workflow fills a slot only for a name it was given: slot 2 empty.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GENTAR_ROUTE_") and k not in ("SUBJECT_KEY", "MIRROR_SECRET")}
        env.update(GENTAR_ROUTE_1="value-one", GENTAR_REPO_URL=str(self.tmp / "no-engine"))
        rr = subprocess.run(["/bin/bash", "gentar/run.sh", "--route"], cwd=w, env=env,
                            capture_output=True, text=True)
        self.assertEqual(rr.returncode, 0, rr.stderr)
        self.assertIn("secret route: SUBJECT_KEY set", rr.stdout)
        self.assertIn("secret route: MIRROR_SECRET missing", rr.stdout)
        self.assertNotIn("value-one", rr.stdout + rr.stderr)


FAKE_GH = r"""#!/usr/bin/env bash
# a fake gh: records every call; answers from fixtures through real jq
printf '%s\n' "$*" >> "$FIX/calls"
case "$1 $2" in
  "repo view") echo "owner/repo" ;;
  "workflow run") : ;;
  "run list") jq -r "$(for a; do [ "$p" = --jq ] && printf '%s' "$a"; p=$a; done)" "$FIX/runs.json" ;;
  "run watch") exit "${WATCH_RC:-0}" ;;
  "run view") echo "${CONCLUSION:-success} https://github.com/owner/repo-arena/actions/runs/77" ;;
  api*)
    if [ "$2" = -X ]; then exit 0; fi
    case "$2" in
      */commits/*/status) jq -r "$4" "$FIX/status.json" ;;
      *) exit 1 ;;
    esac ;;
  *) exit 64 ;;
esac
"""


def iso(days_ago):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


@unittest.skipUnless(MIRROR_SH.exists() and shutil.which("jq"),
                     "needs the kit (not in the image build context) and jq")
class MirrorDispatchTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        shutil.copytree(KIT, self.repo / "gentar")
        (self.repo / "gentar" / "policy.toml").write_text(MIRROR_POLICY)
        self.fix = self.tmp / "fix"
        self.fix.mkdir()
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "gh").write_text(FAKE_GH)
        (self.tmp / "bin" / "gh").chmod(0o755)

    def run_sh(self, *args, title=None, **env):
        (self.fix / "runs.json").write_text(json.dumps(
            [{"databaseId": 77, "displayTitle": title}] if title else []))
        e = {**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
             "FIX": str(self.fix), **env}
        e.pop("GENTAR_PUBLIC_REPO", None)
        return subprocess.run(["/bin/bash", "gentar/mirror.sh", *args], cwd=self.repo, env=e,
                              capture_output=True, text=True)

    def calls(self):
        f = self.fix / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def test_a_green_phase_2_posts_success(self):
        r = self.run_with_match()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        post = [c for c in self.calls() if c.startswith("api -X POST")]
        self.assertEqual(len(post), 1)
        self.assertIn(f"repos/owner/repo/statuses/{SHA}", post[0])
        self.assertIn("state=success", post[0])
        self.assertIn("context=arena/phase2", post[0])
        self.assertIn("target_url=https://github.com/owner/repo-arena/actions/runs/77", post[0])
        run = [c for c in self.calls() if c.startswith("workflow run")][0]
        self.assertIn("-R owner/repo-arena", run)
        self.assertIn(f"sha={SHA}", run)

    def test_a_red_phase_2_posts_failure_and_fails(self):
        r = self.run_with_match(CONCLUSION="failure", WATCH_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("state=failure", [c for c in self.calls() if c.startswith("api -X POST")][0])

    def test_a_cancelled_run_posts_error(self):
        r = self.run_with_match(CONCLUSION="cancelled", WATCH_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("state=error", [c for c in self.calls() if c.startswith("api -X POST")][0])

    def test_a_targeted_run_posts_nothing(self):
        r = self.run_with_match("smoke")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("api -X POST")], [])
        self.assertIn("scenario=smoke", [c for c in self.calls() if c.startswith("workflow run")][0])

    def run_with_match(self, *suites, **env):
        """Dispatch with a fake run list that matches only THIS request id."""
        script = (self.repo / "gentar" / "mirror.sh").read_text()
        pinned = "gentar-test-request"
        (self.repo / "gentar" / "mirror.sh").write_text(
            script.replace('REQ="gentar-$(date +%s)-$$-${RANDOM:-0}"', f'REQ="{pinned}"', 1))
        self.assertIn(pinned, (self.repo / "gentar" / "mirror.sh").read_text())
        return self.run_sh("dispatch", SHA, *suites, title=f"arena {SHA} {pinned}", **env)

    def test_another_dispatchers_run_is_never_taken(self):
        script = (self.repo / "gentar" / "mirror.sh").read_text()
        (self.repo / "gentar" / "mirror.sh").write_text(
            script.replace('REQ="gentar-$(date +%s)-$$-${RANDOM:-0}"', 'REQ="mine"', 1)
                  .replace("seq 1 30", "seq 1 1").replace("sleep 2", ":"))
        r = self.run_sh("dispatch", SHA, title=f"arena {SHA} someone-else")
        self.assertEqual(r.returncode, 2)
        self.assertIn("did not appear", r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("api -X POST")], [])

    def test_usage_and_policy_refusals(self):
        self.assertEqual(self.run_sh("dispatch", SHA[:12]).returncode, 2)
        self.assertEqual(self.run_sh("dispatch", SHA, "bad;suite").returncode, 2)
        self.assertEqual(self.run_sh("launch", SHA).returncode, 2)
        (self.repo / "gentar" / "policy.toml").write_text("[phase2]\non = [\"dispatch\"]\n")
        r = self.run_sh("dispatch", SHA)
        self.assertEqual(r.returncode, 2)
        self.assertIn('no [arena] bench = "mirror"', r.stderr)
        self.assertEqual(self.calls(), [])

    def test_status_reads_the_latest_arena_phase2(self):
        (self.fix / "status.json").write_text(json.dumps({"statuses": [
            {"context": "ci", "state": "failure", "updated_at": iso(0), "target_url": "x"},
            {"context": "arena/phase2", "state": "success", "updated_at": iso(0),
             "target_url": "https://mirror/run/1"}]}))
        r = self.run_sh("status", SHA)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("arena/phase2: success", r.stdout)


@unittest.skipUnless(GATE.exists() and shutil.which("jq"),
                     "needs the kit (not in the image build context) and jq")
class StatusEvidenceGateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        g = self.tmp / "gentar"
        g.mkdir()
        (g / "scenarios").mkdir()
        shutil.copy(GATE, g / "release-gate.sh")
        shutil.copy(PLAN, g / "plan.py")
        self.fix = self.tmp / "fix"
        self.fix.mkdir()
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "gh").write_text(FAKE_GH)
        (self.tmp / "bin" / "gh").chmod(0o755)
        self.policy(MIRROR_POLICY)

    def policy(self, text):
        (self.tmp / "gentar" / "policy.toml").write_text(text)

    def statuses(self, *entries):
        (self.fix / "status.json").write_text(json.dumps({"statuses": [
            {"context": c, "state": s, "updated_at": iso(age),
             "target_url": url or "https://github.com/owner/repo-arena/actions/runs/9"}
            for c, s, age, *rest in entries for url in [rest[0] if rest else None]]}))

    def gate(self):
        e = {**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
             "FIX": str(self.fix), "GITHUB_REPOSITORY": "owner/repo"}
        return subprocess.run(["/bin/bash", "gentar/release-gate.sh", SHA], cwd=self.tmp, env=e,
                              capture_output=True, text=True)

    def test_a_success_status_releases(self):
        self.statuses(("ci", "failure", 0), ("arena/phase2", "success", 1))
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("arena/phase2 success, 1 day(s) ago: "
                      "https://github.com/owner/repo-arena/actions/runs/9", r.stdout)

    def test_a_status_not_linking_the_mirror_proves_nothing(self):
        for url in ("https://example.com/ci/1", "https://github.com/owner/repo-arena-evil/actions/runs/9",
                    "https://github.com/other/repo-arena/actions/runs/9", "-"):
            with self.subTest(url=url):
                self.statuses(("arena/phase2", "success", 0, url))
                r = self.gate()
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("not a run of the arena mirror owner/repo-arena", r.stderr)
        self.statuses(("arena/phase2", "success", 0, "https://github.com/Owner/Repo-Arena/actions/runs/9"))
        self.assertEqual(self.gate().returncode, 0)

    def test_anything_else_refuses_and_says_what(self):
        for entries, words in (((("arena/phase2", "failure", 0),), "arena/phase2 is failure"),
                               ((("arena/phase2", "error", 0),), "arena/phase2 is error"),
                               ((("arena/phase2", "pending", 0),), "still pending"),
                               ((("ci", "success", 0),), "no arena/phase2 status")):
            with self.subTest(words=words):
                self.statuses(*entries)
                r = self.gate()
                self.assertEqual(r.returncode, 1)
                self.assertIn(words, r.stderr)
                self.assertIn("gentar/mirror.sh dispatch", r.stderr)

    def test_a_stale_success_is_refused_under_max_age(self):
        self.policy(MIRROR_POLICY.replace('evidence = "status"', 'evidence = "status"\nmax_age_days = 7'))
        self.statuses(("arena/phase2", "success", 8))
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("8 day(s) ago (max_age_days = 7)", r.stderr)

    def test_the_api_failing_is_not_a_pass(self):
        (self.fix / "status.json").unlink(missing_ok=True)
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not read the commit statuses", r.stderr)

    def test_a_disabled_gate_reports_without_refusing(self):
        self.policy(MIRROR_POLICY.replace('evidence = "status"', 'evidence = "status"\nrelease_gate = false'))
        self.statuses(("arena/phase2", "failure", 0))
        r = self.gate()
        self.assertEqual(r.returncode, 0)
        self.assertIn("NOT refusing", r.stdout)

    def test_job_evidence_is_unchanged_by_default(self):
        self.policy("[phase2]\non = [\"dispatch\"]\n")
        r = self.gate()                       # no runs fixture: the job path, not statuses
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not list gentar-arena.yml runs", r.stderr)


if __name__ == "__main__":
    unittest.main()

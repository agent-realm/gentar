"""gentar/release-gate.sh: a release ships only after a green phase 2 of its commit.

The gate asks the GitHub API for `arena / phase2` jobs on the exact sha.
Here `gh` is a fake on PATH that runs the script's own --jq filter with
real `jq` over JSON fixtures shaped like the API's answers, so the filters
are tested along with the shell around them.

What must hold: a targeted run never counts; a cancelled or evicted phase 2
is NAMED, not just "not found"; max_age_days refuses a stale pass; and
release_gate = false reports without refusing.
"""

import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "subject-template" / "gentar"
GATE = KIT / "release-gate.sh"
SHA = "a" * 40

FAKE_GH = """#!/usr/bin/env bash
# gh api <path> --jq <filter>
[ "$1" = api ] || exit 64
path=$2; filter=$4
case "$path" in
  */actions/workflows/gentar-arena.yml/runs*) f="$FIX/runs.json" ;;
  */actions/runs/*/jobs*) id=${path#*/actions/runs/}; id=${id%%/*}; f="$FIX/jobs-$id.json" ;;
  *) exit 1 ;;
esac
[ -f "$f" ] || exit 1
jq -r "$filter" "$f"
"""


def iso(days_ago):
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


@unittest.skipUnless(GATE.exists() and shutil.which("jq"),
                     "needs the kit (not in the image build context) and jq")
class ReleaseGateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        g = self.tmp / "gentar"
        g.mkdir()
        (g / "scenarios").mkdir()
        shutil.copy(GATE, g / "release-gate.sh")
        shutil.copy(KIT / "plan.py", g / "plan.py")
        self.fix = self.tmp / "fix"
        self.fix.mkdir()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(FAKE_GH)
        (bindir / "gh").chmod(0o755)
        self.bindir = bindir
        self.runs([])

    def policy(self, text):
        (self.tmp / "gentar" / "policy.toml").write_text(text)

    def runs(self, runs):
        (self.fix / "runs.json").write_text(json.dumps({"workflow_runs": [
            {"id": r[0], "status": "completed", "conclusion": r[1],
             "event": r[2], "head_branch": r[3]} for r in runs]}))

    def jobs(self, run_id, jobs):
        (self.fix / f"jobs-{run_id}.json").write_text(json.dumps({"jobs": [
            {"name": n, "conclusion": c, "completed_at": iso(age) if age is not None else None,
             "started_at": iso(age) if age is not None else None}
            for n, c, age in jobs]}))

    def gate(self, sha=SHA):
        env = {"PATH": f"{self.bindir}:{os.environ['PATH']}", "FIX": str(self.fix),
               "GITHUB_REPOSITORY": "o/r", "HOME": os.environ.get("HOME", "/tmp")}
        return subprocess.run([str(self.tmp / "gentar" / "release-gate.sh"), sha],
                              env=env, capture_output=True, text=True)

    def test_a_green_phase_2_on_the_commit_passes(self):
        self.runs([(11, "success", "push", "arena")])
        self.jobs(11, [("arena / phase2", "success", 1)])
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("run 11", r.stdout)

    def test_no_phase_2_refuses(self):
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no successful 'arena / phase2'", r.stderr)

    def test_a_targeted_run_never_counts(self):
        self.runs([(12, "success", "push", "arena-fast")])
        self.jobs(12, [("arena / targeted", "success", 0)])
        self.assertEqual(self.gate().returncode, 1)

    def test_a_failed_phase_2_refuses_and_says_so(self):
        self.runs([(13, "failure", "push", "arena")])
        self.jobs(13, [("arena / phase2", "failure", 0)])
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("phase 2 in run 13: failure", r.stderr)

    def test_an_evicted_run_is_named(self):
        # GitHub cancels a PENDING run in a concurrency group when a newer
        # one queues: 0 jobs, conclusion cancelled (claude-playbooks, observed)
        self.runs([(14, "cancelled", "push", "v2.0.0-rc1")])
        self.jobs(14, [])
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("run 14", r.stderr)
        self.assertIn("cancelled before a phase 2 job ran", r.stderr)

    def test_one_green_among_failures_passes_and_reports_the_rest(self):
        self.runs([(15, "cancelled", "push", "arena"), (16, "success", "workflow_dispatch", "main")])
        self.jobs(15, [("arena / phase2", "cancelled", 2)])
        self.jobs(16, [("plan", "success", 0), ("arena / phase2", "success", 0)])
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("run 16", r.stdout)
        self.assertIn("phase 2 in run 15: cancelled", r.stdout)

    def test_max_age_refuses_a_stale_pass(self):
        self.policy("[phase2]\nmax_age_days = 7\n")
        self.runs([(17, "success", "push", "arena")])
        self.jobs(17, [("arena / phase2", "success", 30)])
        r = self.gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("30 day(s) ago (max_age_days = 7)", r.stderr)
        self.jobs(17, [("arena / phase2", "success", 3)])
        self.assertEqual(self.gate().returncode, 0)

    def test_max_age_is_not_rounded_down(self):
        # 7 days and 23 hours is older than 7 days
        self.policy("[phase2]\nmax_age_days = 7\n")
        self.runs([(18, "success", "push", "arena")])
        self.jobs(18, [("arena / phase2", "success", 7 + 23 / 24)])
        self.assertEqual(self.gate().returncode, 1)
        self.jobs(18, [("arena / phase2", "success", 6.9)])
        self.assertEqual(self.gate().returncode, 0)

    def test_gate_off_passes_even_when_the_api_cannot_answer(self):
        self.policy("[phase2]\nrelease_gate = false\n")
        (self.fix / "runs.json").unlink()      # the fake gh now fails
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOT refusing", r.stdout)

    def test_gate_on_refuses_when_the_api_cannot_answer(self):
        (self.fix / "runs.json").unlink()
        self.assertEqual(self.gate().returncode, 1)

    def test_gate_off_reports_but_does_not_refuse(self):
        self.policy("[phase2]\nrelease_gate = false\n")
        r = self.gate()
        self.assertEqual(r.returncode, 0)
        self.assertIn("NOT refusing", r.stdout)

    def test_a_short_or_bad_sha_is_a_usage_error(self):
        for sha in ("abc123", "", "z" * 40, SHA + ";id"):
            with self.subTest(sha=sha):
                self.assertEqual(self.gate(sha).returncode, 2)


if __name__ == "__main__":
    unittest.main()

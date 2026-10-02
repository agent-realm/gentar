"""[stage] git = true: history into the bench, no credential with it.

The own-repo move (2026-10-03) needs it: kommander-update and
agent-profile-smoke clone from $WORKSPACE_DIR/.git, and the kit strips .git
because on CI it holds the job's auth header. stage-git builds a fresh .git
by a local clone: history and tags, a new config, no remote.
"""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "subject-template" / "gentar" / "plan.py"
SECRET = "ghp_SECRETVALUE1234567890"


def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_stage", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(PLAN.exists(), "the kit is not in the image build context")
class StageGitTest(unittest.TestCase):

    def setUp(self):
        self.p = load_plan()
        self.tmp = Path(tempfile.mkdtemp())
        r = self.repo = self.tmp / "repo"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        (r / "f").write_text("1\n")
        git(r, "add", "f")
        git(r, "commit", "-qm", "one")
        git(r, "tag", "v1.0.0")
        (r / "f").write_text("2\n")
        git(r, "commit", "-qam", "two")
        # what actions/checkout leaves behind, and a credentialed remote
        git(r, "config", "http.https://github.com/.extraheader", f"AUTHORIZATION: basic {SECRET}")
        git(r, "remote", "add", "origin", f"https://x-access-token:{SECRET}@github.com/o/r")
        # the staged copy: the working tree, with an uncommitted change
        self.dest = self.tmp / "staged"
        self.dest.mkdir()
        (self.dest / "f").write_text("3-uncommitted\n")

    def test_history_and_tags_arrive_without_credentials(self):
        self.p.stage_git(str(self.repo), str(self.dest))
        self.assertEqual(git(self.dest, "tag"), "v1.0.0")
        self.assertEqual(git(self.dest, "log", "--format=%s"), "two\none")
        self.assertEqual(git(self.dest, "remote"), "")
        config = (self.dest / ".git" / "config").read_text()
        self.assertNotIn(SECRET, config)
        self.assertNotIn("extraheader", config.lower())
        self.assertNotIn(str(self.repo), config)          # no host path either
        # the copy's files are untouched: the uncommitted change survives
        self.assertEqual((self.dest / "f").read_text(), "3-uncommitted\n")
        self.assertIn("f", git(self.dest, "status", "--porcelain"))

    def test_the_engine_guard_finds_nothing_in_the_result(self):
        self.p.stage_git(str(self.repo), str(self.dest))
        from gentar.coordinator import subject_credential_problems
        self.assertEqual(subject_credential_problems(str(self.dest)), [])

    def test_a_clone_of_the_staged_history_works_as_the_suites_use_it(self):
        self.p.stage_git(str(self.repo), str(self.dest))
        out = self.tmp / "old"
        subprocess.run(["git", "clone", "-q", "-b", "v1.0.0", str(self.dest / ".git"), str(out)],
                       check=True, capture_output=True)
        self.assertEqual((out / "f").read_text(), "1\n")

    def test_a_shallow_source_refuses(self):
        shallow = self.tmp / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{self.repo}", str(shallow)],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(self.p.Refuse, "shallow"):
            self.p.stage_git(str(shallow), str(self.dest))

    def test_the_policy_switch(self):
        f = self.tmp / "policy.toml"
        f.write_text("[stage]\ngit = true\n")
        self.assertTrue(self.p.load_policy(f)["stage"]["git"])
        f.write_text('[stage]\ngit = "yes"\n')
        with self.assertRaises(self.p.Refuse):
            self.p.load_policy(f)
        f.write_text("[phase1]\nchecks = true\n")
        self.assertFalse(self.p.load_policy(f)["stage"]["git"])   # off by default

    def test_run_sh_calls_it_after_the_copy(self):
        run = (ROOT / "subject-template" / "gentar" / "run.sh").read_text()
        copy = run.index('-cf - .) | tar -xf - -C "subjects/$SUBJECT"')
        call = run.index('plan.py" stage-git "$REPO" "subjects/$SUBJECT"')
        self.assertGreater(call, copy)


if __name__ == "__main__":
    unittest.main()

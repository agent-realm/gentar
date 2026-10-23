"""A subject stays inside the subjects root, and only git's files reach a bench.

Two findings of the ground-up review (2026-10-19):

C3: the engine joined the scenario's `subject` onto the subjects root
unchecked, so a direct run of a scenario with `subject = "../run/secrets"`
shipped the coordinator's bench key (/run/secrets/bench_ssh_key) into a
bench. The kit's run.sh name check stopped it there; the engine did not.

C2: the kit staged the subject by tarring the whole working tree, so a
gitignored .env, .npmrc or .netrc reached the bench, and the engine's
credential scan of a subject's .git skipped .git/logs, where `git pull <url
with a token>` writes the token.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar import oracle
from gentar.config import Config

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
PLAN = KIT / "plan.py"
SECRET = "s3cr3t-staging-0123456789"


class _Refused(Exception):
    """make_bench was reached: the run was NOT refused."""


def _scenario(d, subject):
    (Path(d) / "s.toml").write_text(
        f'[scenario]\nname = "s"\nsubject = "{subject}"\n[oracle]\nsteps = ["true"]\n')


class SubjectContainmentTest(unittest.TestCase):
    """C3: refused (exit 2, a report) before any bench exists."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "subjects"
        self.root.mkdir()
        self.scen = self.tmp / "scen"
        self.scen.mkdir()
        self.out = self.tmp / "out"
        self.out.mkdir()
        # What C3 reached: a key file next to the subjects root.
        (self.tmp / "run" / "secrets").mkdir(parents=True)
        (self.tmp / "run" / "secrets" / "bench_ssh_key").write_text(SECRET)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_subject(self, subject):
        _scenario(self.scen, subject)
        env = {"GENTAR_SCENARIOS_DIR": str(self.scen), "GENTAR_SUBJECTS_ROOT": str(self.root),
               "GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u",
               "GENTAR_REPORT_DIR": str(self.out)}
        printed = []
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config()
            with mock.patch.object(coord, "make_bench", side_effect=_Refused), \
                 mock.patch.object(coord, "Spans"), \
                 mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
                rc = coord._run("s", cfg)
        return rc, "\n".join(printed)

    def assert_refused(self, subject):
        rc, out = self.run_subject(subject)        # _Refused escapes if a bench was asked for
        self.assertEqual(rc, 2, out)
        self.assertIn("subject guard", out)
        self.assertNotIn(SECRET, out)
        reports = [p.read_text() for p in self.out.glob("report-*.md")]
        self.assertEqual(len(reports), 1)
        self.assertIn("REFUSE", reports[0])

    def test_a_parent_path_is_refused(self):
        self.assert_refused("../run/secrets")

    def test_a_relative_climb_is_refused(self):
        self.assert_refused("../x")

    def test_a_nested_path_is_refused(self):
        (self.root / "a" / "b").mkdir(parents=True)
        self.assert_refused("a/b")

    def test_dot_dot_is_refused(self):
        self.assert_refused("..")

    def test_a_hidden_name_is_refused(self):
        (self.root / ".hidden").mkdir()
        self.assert_refused(".hidden")

    def test_an_option_shaped_name_is_refused(self):
        (self.root / "-x").mkdir()
        self.assert_refused("-x")

    def test_an_empty_name_is_refused(self):
        self.assert_refused("")

    def test_a_symlink_out_of_the_root_is_refused(self):
        (self.root / "out").symlink_to(self.tmp / "run" / "secrets")
        self.assert_refused("out")

    def test_a_normal_name_reaches_the_bench(self):
        # Control: the guard must not refuse a real subject.
        (self.root / "my-repo_1.0").mkdir()
        with self.assertRaises(_Refused):
            self.run_subject("my-repo_1.0")

    def test_a_symlink_inside_the_root_reaches_the_bench(self):
        # Control: a link that stays inside the root is still a subject.
        (self.root / "real").mkdir()
        (self.root / "alias").symlink_to(self.root / "real")
        with self.assertRaises(_Refused):
            self.run_subject("alias")


class OraclePushTest(unittest.TestCase):
    """The oracle resolves the subject the same way: a caller that skipped
    the coordinator's guard still cannot push a path out of the root."""

    def test_the_push_refuses_a_path_out_of_the_root(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "subjects").mkdir()
        cfg = mock.Mock(subjects_root=str(tmp / "subjects"), otlp_endpoint="")
        scenario = mock.Mock(subject="../run/secrets", agent="shell", template=None,
                             steps=[], driver_command=None, name="s")
        bench = mock.Mock(push_before_create=True)
        bench.workspace.return_value = "/ws/r"
        with self.assertRaises(Exception) as caught:
            oracle.run_oracle(scenario, bench, "r", mock.MagicMock(), cfg, subject="s")
        bench.push_dir.assert_not_called()
        bench.create.assert_not_called()
        self.assertIsInstance(caught.exception, ValueError)


def _git_subject(reflogs):
    d = Path(tempfile.mkdtemp()) / "subj"
    (d / ".git").mkdir(parents=True)
    (d / ".git" / "config").write_text('[remote "origin"]\n\turl = https://github.com/o/r\n')
    for rel, body in reflogs.items():
        (d / ".git" / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / ".git" / rel).write_text(body)
    return d


Z = "0" * 40
PULL = f"{Z} {'1' * 40} T <t@t> 1700000000 +0000\tpull https://u:{SECRET}@github.com/o/r main: Fast-forward\n"
CLONE = f"{Z} {'1' * 40} T <t@t> 1700000000 +0000\tclone: from /home/u/src/r\n"


class ReflogScanTest(unittest.TestCase):
    """C2's second half: .git/logs is scanned like .git/config."""

    def test_a_credential_in_a_reflog_is_found_by_name_only(self):
        for rel in ("logs/HEAD", "logs/refs/heads/main", "modules/lib/logs/HEAD",
                    "worktrees/w/logs/HEAD"):
            with self.subTest(rel=rel):
                why = coord.subject_credential_problems(str(_git_subject({rel: CLONE + PULL})))
                self.assertTrue(any(rel in w and "reflog" in w for w in why), why)
                self.assertNotIn(SECRET, " ".join(why))

    def test_a_clean_reflog_passes(self):
        # Control: a local clone's reflog names a path, not a credential.
        d = _git_subject({"logs/HEAD": CLONE, "logs/refs/heads/main": CLONE})
        self.assertEqual(coord.subject_credential_problems(str(d)), [])

    def test_the_guard_refuses_it_before_any_bench(self):
        d = _git_subject({"logs/HEAD": PULL})
        sc = mock.Mock(subject="subj", credentials=[], bench="", uses_judge=False,
                       budget_tokens=0, driver_command=None, warnings=[])
        env = {"GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u", "GENTAR_REPORT_DIR": "",
               "GENTAR_SUBJECTS_ROOT": str(d.parent)}
        printed = []
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config()
            with mock.patch.object(coord, "_resolve", return_value=(lambda *a, **k: "", sc)), \
                 mock.patch.object(coord, "make_bench", side_effect=_Refused), \
                 mock.patch.object(coord, "Spans"), \
                 mock.patch("builtins.print", side_effect=printed.append):
                rc = coord._run("s", cfg)
        out = "\n".join(map(str, printed))
        self.assertEqual(rc, 2, out)
        self.assertIn("reflog", out)
        self.assertNotIn(SECRET, out)


# -- the kit: what stage-tree copies into subjects/<name> ---------------------

def load_plan():
    spec = importlib.util.spec_from_file_location("gentar_plan_staging", PLAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], capture_output=True, text=True, check=True).stdout


def files_under(d):
    return sorted(str(p.relative_to(d)) for p in Path(d).rglob("*")
                  if p.is_file() or p.is_symlink())


@unittest.skipUnless(PLAN.exists() and shutil.which("git"), "the kit (or git) is not here")
class StageTreeTest(unittest.TestCase):

    def setUp(self):
        self.p = load_plan()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dest = self.tmp / "staged"
        self.dest.mkdir()

    def git_repo(self):
        r = self.tmp / "repo"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        (r / ".gitignore").write_text(".env\n.npmrc\n.netrc\nbuild/\n")
        (r / "src").mkdir()
        (r / "src" / "app.py").write_text("print(1)\n")
        (r / "run.sh").write_text("#!/bin/sh\n")
        (r / "run.sh").chmod(0o755)
        (r / "link").symlink_to("src/app.py")
        (r / "gone.txt").write_text("deleted below\n")
        git(r, "add", ".")
        git(r, "commit", "-qm", "one")
        (r / "gone.txt").unlink()                       # tracked, deleted on disk
        (r / "notes.txt").write_text("untracked, not ignored\n")
        for name in (".env", ".npmrc", ".netrc"):
            (r / name).write_text(f"TOKEN={SECRET}\n")
        (r / "build").mkdir()
        (r / "build" / "out.bin").write_text("artifact\n")
        # The kit's own state, NOT ignored here: excluded by name anyway.
        (r / "gentar" / ".arena").mkdir(parents=True)
        (r / "gentar" / ".arena" / ".env").write_text(f"KEY={SECRET}\n")
        (r / "gentar" / "reports").mkdir()
        (r / "gentar" / "reports" / "report-x.md").write_text("old\n")
        (r / "gentar" / "scenarios").mkdir()
        (r / "gentar" / "scenarios" / "s.toml").write_text("[scenario]\n")
        return r

    def test_a_git_subject_stages_what_git_would_ship(self):
        r = self.git_repo()
        self.assertIn("git would ship", self.p.stage_tree(str(r), str(self.dest)))
        self.assertEqual(files_under(self.dest),
                         [".gitignore", "gentar/scenarios/s.toml", "link", "notes.txt",
                          "run.sh", "src/app.py"])
        self.assertTrue((self.dest / "link").is_symlink())
        self.assertEqual(os.readlink(self.dest / "link"), "src/app.py")
        self.assertTrue(os.access(self.dest / "run.sh", os.X_OK))
        for p in self.dest.rglob("*"):
            if p.is_file() and not p.is_symlink():
                self.assertNotIn(SECRET, p.read_text())

    def test_a_nested_repository_ships_through_its_own_git(self):
        r = self.git_repo()
        n = r / "vendor" / "lib"
        n.mkdir(parents=True)
        git(n, "init", "-q", "-b", "main")
        (n / ".gitignore").write_text("secret.txt\n")
        (n / "lib.py").write_text("x = 1\n")
        (n / "secret.txt").write_text(SECRET)
        self.p.stage_tree(str(r), str(self.dest))
        staged = files_under(self.dest)
        self.assertIn("vendor/lib/lib.py", staged)
        self.assertIn("vendor/lib/.gitignore", staged)
        self.assertNotIn("vendor/lib/secret.txt", staged)
        self.assertFalse((self.dest / "vendor" / "lib" / ".git").exists())

    def test_a_git_dir_git_cannot_read_is_refused_not_copied_whole(self):
        r = self.tmp / "broken"
        r.mkdir()
        (r / ".git").write_text("gitdir: /nonexistent/.git/worktrees/x\n")
        (r / ".env").write_text(SECRET)
        with self.assertRaises(self.p.Refuse):
            self.p.stage_tree(str(r), str(self.dest))
        self.assertFalse((self.dest / ".env").exists())

    def test_a_non_git_subject_is_copied_whole_as_before(self):
        # Control: no .git, so today's tar copy, byte for byte the same set.
        r = self.tmp / "plain"
        (r / "gentar" / ".arena").mkdir(parents=True)
        (r / "gentar" / ".arena" / "k").write_text("x")
        (r / "gentar" / "reports").mkdir()
        (r / "gentar" / "reports" / "r.md").write_text("x")
        (r / ".env").write_text("x")
        (r / "a.txt").write_text("x")
        before = self.tmp / "before"
        before.mkdir()
        subprocess.run(f"(cd '{r}' && tar --exclude=./.git --exclude=./gentar/.arena "
                       f"--exclude=./gentar/reports -cf - .) | tar -xf - -C '{before}'",
                       shell=True, check=True)
        self.assertIn("whole tree", self.p.stage_tree(str(r), str(self.dest)))
        self.assertEqual(files_under(self.dest), files_under(before))
        self.assertIn(".env", files_under(self.dest))

    def test_run_sh_stages_through_it(self):
        # (test_stage_git checks it runs before stage-git)
        run = (KIT / "run.sh").read_text()
        self.assertIn('python3 "$HERE/plan.py" stage-tree "$REPO" "subjects/$SUBJECT"\n', run)
        self.assertNotIn("-cf - .) | tar -xf -", run)       # the whole-tree copy is gone


@unittest.skipUnless(PLAN.exists() and shutil.which("git"), "the kit (or git) is not here")
class DryrunStagesTheSameTest(unittest.TestCase):
    """The dry-run stages its workspace as the bench gets it, or a suite
    that reads an ignored local file passes here and fails there."""

    def test_an_ignored_file_is_not_in_the_dryrun_workspace(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = tmp / "repo"
        (repo / "gentar" / "scenarios").mkdir(parents=True)
        for f in ("dryrun.py", "plan.py"):
            shutil.copy(KIT / f, repo / "gentar" / f)
        (repo / "gentar" / "scenarios" / "s.toml").write_text(
            '[scenario]\nname = "s"\nsubject = "fid"\n[oracle]\n'
            'steps = ["test ! -e .env", "test -e notes.txt", "test -e app.py"]\n'
            '[[verify.commands]]\ncommand = "true"\n')
        (repo / ".gitignore").write_text(".env\n")
        (repo / "app.py").write_text("x\n")
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "one")
        (repo / ".env").write_text(f"TOKEN={SECRET}\n")
        (repo / "notes.txt").write_text("untracked\n")
        e = dict(os.environ, GENTAR_ENGINE=str(ROOT / "coordinator"),
                 GENTAR_DRYRUN_SYSTEM_DIRS=str(tmp / "nonexistent"))
        r = subprocess.run([sys.executable, "gentar/dryrun.py"], cwd=repo, env=e,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn(SECRET, r.stdout + r.stderr)


@unittest.skipUnless((Path(__file__).resolve().parents[2] / "subject-template" / "gentar" / "run.sh").exists(),
                     "the kit is not in the image build context")
class KitNameCheckTest(unittest.TestCase):
    """The kit refuses what the engine refuses, before staging anything."""

    def test_a_leading_dot_or_dash_is_refused_by_the_kit(self):
        import shutil, subprocess
        kit = Path(__file__).resolve().parents[2] / "subject-template" / "gentar"
        for name in (".hidden", "..", "-x"):
            with self.subTest(name=name):
                tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
                shutil.copytree(kit, tmp / "repo" / "gentar")
                sc = tmp / "repo" / "gentar" / "scenarios"
                shutil.rmtree(sc)
                sc.mkdir()
                (sc / "s.toml").write_text(f'[scenario]\nsubject = "{name}"\n[oracle]\nsteps = ["true"]\n')
                env = {k: v for k, v in os.environ.items() if not k.startswith(("GENTAR_", "GITHUB_"))}
                env["GENTAR_REPO_URL"] = str(tmp / "no-engine")
                r = subprocess.run(["/bin/bash", "gentar/run.sh", "s"], cwd=tmp / "repo", env=env,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("bad subject name", r.stderr)
                self.assertFalse((tmp / "repo" / "subjects").exists() and any((tmp / "repo" / "subjects").iterdir()))


if __name__ == "__main__":
    unittest.main()

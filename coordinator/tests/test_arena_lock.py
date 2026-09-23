"""The kit's host lock: one arena per subject per Docker host, and runs WAIT.

GitHub's concurrency groups cancel a pending run when a newer one queues,
so the kit serialises on the host instead (run.sh's arena_lock). With runs
now waiting on each other, `--down` — which a cancelled job's teardown
calls — must never stop an arena another live run holds; it may clear a
lock whose holder is gone.

Driven through the real run.sh in a scratch adoption, with `docker` as a
fake that logs what it was asked to stop. Whichever lock this host
gives run.sh is the one tested: flock where it exists (Linux runners), the
mkdir lock otherwise (stock macOS).
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "subject-template"
RUN = KIT / "gentar" / "run.sh"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_LOG"
case "$1" in ps) echo cid123 ;; esac
exit 0
"""


@unittest.skipUnless(RUN.exists(), "the kit is not in the image build context")
class ArenaLockTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        repo = self.tmp / "repo"
        shutil.copytree(KIT / "gentar", repo / "gentar")
        toml = repo / "gentar" / "scenarios" / "first-suite.toml"
        toml.write_text(toml.read_text().replace('"REPLACE-ME"', '"lockrepo"'))
        self.repo = repo
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        (self.bindir / "docker").write_text(FAKE_DOCKER)
        (self.bindir / "docker").chmod(0o755)
        self.lockdir = self.tmp / "locks"
        self.lockdir.mkdir()
        self.root = self.lockdir / "gentar-locks"      # run.sh's shared lock root
        self.root.mkdir(mode=0o777)
        os.chmod(self.root, 0o777)
        self.log = self.tmp / "docker.log"
        self.log.touch()
        self.holder = None

    def tearDown(self):
        if self.holder:
            self.holder.kill()
            self.holder.wait()

    def path(self):
        return f"{self.bindir}:/usr/bin:/bin:/usr/sbin:/sbin"

    @property
    def flock(self):
        return shutil.which("flock", path=self.path())

    def down(self):
        env = {"PATH": self.path(), "DOCKER_LOG": str(self.log),
               "GENTAR_LOCK_DIR": str(self.lockdir), "HOME": str(self.tmp)}
        return subprocess.run(["/bin/bash", "gentar/run.sh", "--down"], cwd=self.repo,
                              env=env, capture_output=True, text=True)

    def hold_live(self):
        """Another run holding the lock, the way run.sh would."""
        base = self.root / "gentar-arena-lockrepo.lock"
        if self.flock:
            base.touch()
            self.holder = subprocess.Popen([self.flock, str(base), "sleep", "60"])
            for _ in range(50):                      # until flock holds it
                if subprocess.run([self.flock, "-n", str(base), "true"]).returncode:
                    break
                __import__("time").sleep(0.1)
            (self.root / "gentar-arena-lockrepo.lock.holder").write_text(
                f"pid {self.holder.pid} on host since now\n")
            return base
        self.holder = subprocess.Popen(["sleep", "60"])
        d = Path(str(base) + ".d")
        d.mkdir()
        (d / "holder").write_text(f"pid {self.holder.pid} on host since now\n")
        return d

    def hold_stale(self):
        """A lock whose holder is gone."""
        dead = subprocess.Popen(["true"])
        dead.wait()
        base = self.root / "gentar-arena-lockrepo.lock"
        if self.flock:                 # flock dies with its holder; a note may remain
            base.touch()
            (self.root / "gentar-arena-lockrepo.lock.holder").write_text(
                f"pid {dead.pid} on host since then\n")
            return None
        d = Path(str(base) + ".d")
        d.mkdir()
        (d / "holder").write_text(f"pid {dead.pid} on host since then\n")
        return d

    def stopped(self):
        return "docker stop" in self.log.read_text()

    def test_down_leaves_a_live_holders_arena_alone(self):
        held = self.hold_live()
        r = self.down()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("in use by another run", r.stdout)
        self.assertIn(f"pid {self.holder.pid}", r.stdout)
        self.assertFalse(self.stopped(), "stopped another run's arena")
        self.assertTrue(held.exists(), "removed a live holder's lock")

    def test_down_clears_a_stale_lock_and_tears_down(self):
        d = self.hold_stale()
        r = self.down()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("torn down", r.stdout)
        self.assertTrue(self.stopped())
        if d is not None:
            self.assertFalse(d.exists(), "left the lock behind after tearing down")

    def test_down_with_no_lock_tears_down(self):
        r = self.down()
        self.assertIn("torn down", r.stdout)
        self.assertTrue(self.stopped())
        self.assertFalse((self.root / "gentar-arena-lockrepo.lock.d").exists())

    def test_the_lock_root_is_shared_and_not_sticky(self):
        # a fresh host: run.sh makes the root itself, world-writable and
        # without the sticky bit, so any runner user can clear a dead
        # run's lock (in sticky /tmp only the lock's owner could)
        os.rmdir(self.root)
        self.down()
        mode = self.root.stat().st_mode & 0o7777
        self.assertEqual(mode & 0o777, 0o777, oct(mode))
        self.assertFalse(mode & 0o1000, "lock root is sticky")

    @unittest.skipIf(shutil.which("flock", path="/usr/bin:/bin:/usr/sbin:/sbin"),
                     "the mkdir lock is the macOS fallback")
    def test_an_unremovable_stale_lock_is_named_not_hung_on(self):
        d = self.hold_stale()
        os.chmod(d, 0o555)                   # holder file cannot be deleted
        try:
            r = self.down()
        finally:
            os.chmod(d, 0o755)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cannot be removed", r.stderr)
        self.assertIn("rm -rf", r.stderr)
        self.assertIn("not torn down", r.stdout)
        self.assertFalse(self.stopped())

    def test_a_symlinked_lock_root_is_refused(self):
        # a local user pre-creating the shared root as a link would redirect
        # where this user writes (claude-playbooks)
        os.rmdir(self.root)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        os.symlink(elsewhere, self.root)
        r = self.down()
        self.assertIn("arena lock refused", r.stderr)
        self.assertIn("not torn down", r.stdout)
        self.assertFalse(self.stopped())
        self.assertEqual(list(elsewhere.iterdir()), [], "wrote through the link")

    def test_a_planted_holder_link_is_replaced_not_followed(self):
        victim = self.tmp / "victim"
        victim.write_text("precious\n")
        os.symlink(victim, self.root / "gentar-arena-lockrepo.lock.holder")
        self.down()
        self.assertEqual(victim.read_text(), "precious\n", "clobbered through a planted link")


if __name__ == "__main__":
    unittest.main()

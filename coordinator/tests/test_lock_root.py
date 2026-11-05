"""Where the arena lock lives: it belongs to the Docker daemon.

On rootless Docker each account has a daemon of its own, so its lock is
private. On rootful Docker, or when this cannot tell, accounts may share the
daemon and must share the lock: a wrong "rootless" would split a shared
daemon's locks and let two arenas collide. An explicit GENTAR_LOCK_DIR wins.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.test_staging_lock import Holder, wait_until

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
RUN = KIT / "run.sh"
ARENA = ROOT / "bin" / "arena"

ROOTLESS = '["name=seccomp,profile=builtin","name=rootless"]'
ROOTLESS_OPTS = '["name=rootless,foo=bar","name=seccomp"]'
ROOTFUL = '["name=seccomp,profile=builtin","name=cgroupns"]'


def block(script):
    text = script.read_text()
    return text[text.index("# --- lock root"):text.index("# --- end lock root")]


@unittest.skipUnless(RUN.exists() and ARENA.exists(), "the kit and bin/ are not in the image build context")
class LockRootTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "docker.log"
        self.me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()

    def fake_docker(self, body):
        d = self.bin / "docker"
        d.write_text(f'#!/bin/sh\necho "$*" >> "{self.log}"\n{body}\n')
        d.chmod(0o755)

    def choose(self, script=RUN, **env):
        """Run the script's own functions: prints the root and whether it is private."""
        code = f'set -euo pipefail\n{block(script)}\nlock_root_choose\necho "$LOCK_ROOT $LOCK_PRIVATE"\n'
        e = {"PATH": f"{self.bin}:/usr/bin:/bin", **env}
        r = subprocess.run(["/bin/bash", "-c", code], env=e, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def test_the_kit_and_bin_arena_decide_the_same_way(self):
        self.assertEqual(block(RUN), block(ARENA))

    def test_rootless_is_private_to_the_account(self):
        for answer in (ROOTLESS, ROOTLESS_OPTS):
            with self.subTest(answer=answer):
                self.fake_docker(f"echo '{answer}'")
                self.assertEqual(self.choose(), [f"/tmp/gentar-locks-{self.me}", "1"])

    def test_rootful_shares_the_lock(self):
        self.fake_docker(f"echo '{ROOTFUL}'")
        self.assertEqual(self.choose(), ["/tmp/gentar-locks", "0"])

    def test_anything_but_a_clear_answer_falls_back_to_shared(self):
        # A misdetection must never split a shared daemon's locks.
        for body in ("exit 1",                                      # daemon down, or no permission
                     f"echo '{ROOTLESS}'; exit 1",                  # an answer, but it failed
                     "echo",                                        # nothing
                     "echo 'rootless, probably'",                   # not the format
                     'echo \'name=rootless\'',                      # not an array
                     'echo \'["name=rootless-ish"]\'',              # another name
                     'echo \'["xname=rootless"]\'',                 # another name
                     'echo \'["name=seccomp,x=name=rootless"]\'',   # a value, not the name
                     'echo \'["name=rootless"\''):                  # cut short
            with self.subTest(body=body):
                self.fake_docker(body)
                self.assertEqual(self.choose(), ["/tmp/gentar-locks", "0"])

    def test_no_docker_falls_back_to_shared(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        for tool in ("id",):
            found = shutil.which(tool)
            (bare / tool).symlink_to(found)
        code = f'set -euo pipefail\n{block(RUN)}\nlock_root_choose\necho "$LOCK_ROOT $LOCK_PRIVATE"\n'
        r = subprocess.run(["/bin/bash", "-c", code], env={"PATH": str(bare)},
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ["/tmp/gentar-locks", "0"], r.stderr)

    @unittest.skipUnless(shutil.which("timeout"), "no timeout on this host")
    def test_a_hung_daemon_falls_back_to_shared(self):
        self.fake_docker("exec sleep 30")
        self.assertEqual(self.choose(), ["/tmp/gentar-locks", "0"])

    def test_an_explicit_dir_wins_and_asks_docker_nothing(self):
        self.fake_docker(f"echo '{ROOTLESS}'")
        self.assertEqual(self.choose(GENTAR_LOCK_DIR="/some/dir"), ["/some/dir/gentar-locks", "0"])
        self.assertFalse(self.log.exists())
        self.assertEqual(self.choose(GENTAR_LOCK_DIR=""), [f"/tmp/gentar-locks-{self.me}", "1"])

    def functions(self, root, private, call):
        code = (f'{block(RUN)}\nLOCK_ROOT={root}\nLOCK_PRIVATE={private}\n{call}\n')
        return subprocess.run(["/bin/bash", "-c", code], capture_output=True, text=True)

    def test_a_private_root_is_made_owner_only_and_a_shared_one_is_not(self):
        private = self.tmp / "private"
        self.functions(private, 1, "lock_root_make")
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
        shared = self.tmp / "shared"
        self.functions(shared, 0, "lock_root_make")
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o777)

    def test_a_private_root_of_ours_is_tightened(self):
        d = self.tmp / "wide"
        d.mkdir(mode=0o777)
        os.chmod(d, 0o777)
        self.assertEqual(self.functions(d, 1, "lock_root_is_mine").returncode, 0)
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)

    def test_a_shared_root_is_left_as_it_is(self):
        d = self.tmp / "wide"
        d.mkdir(mode=0o777)
        os.chmod(d, 0o777)
        self.assertEqual(self.functions(d, 0, "lock_root_is_mine").returncode, 0)
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o777)

    @unittest.skipIf(os.geteuid() == 0, "root owns nothing it cannot take")
    def test_a_private_root_another_account_made_is_refused(self):
        # /tmp is anyone's. /usr stands in for a directory someone else owns.
        self.assertNotEqual(self.functions("/usr", 1, "lock_root_is_mine").returncode, 0)

    def test_both_scripts_refuse_a_root_that_is_not_theirs(self):
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn("if ! lock_root_is_mine; then", text)
                self.assertIn("belongs to another user", text)


@unittest.skipUnless(RUN.exists(), "the kit is not in the image build context")
class RunShUsesThePrivateRootTest(unittest.TestCase):
    """The real run.sh, on a rootless daemon, with a user name no one has."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user = f"gentartest{uuid.uuid4().hex[:10]}"
        self.root = Path(f"/tmp/gentar-locks-{self.user}")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = self.tmp / "repo"
        shutil.copytree(KIT, self.repo / "gentar")
        sc = self.repo / "gentar" / "scenarios"
        shutil.rmtree(sc)
        sc.mkdir()
        (sc / "s.toml").write_text('[scenario]\nsubject = "lockrepo"\n[oracle]\nsteps = ["true"]\n')
        (self.repo / "gentar" / "policy.toml").unlink(missing_ok=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "docker").write_text(f"#!/bin/sh\necho '{ROOTLESS}'\n")
        (self.bin / "docker").chmod(0o755)
        (self.bin / "id").write_text(f'#!/bin/sh\n[ "$1" = -un ] && {{ echo {self.user}; exit 0; }}\nexec /usr/bin/id "$@"\n')
        (self.bin / "id").chmod(0o755)

    def start(self):
        env = dict(os.environ, GENTAR_REPO_URL=str(self.tmp / "no-engine"),
                   PATH=f"{self.bin}:{os.path.dirname(sys.executable)}:{os.environ['PATH']}")
        for k in ("GITHUB_EVENT_NAME", "CI", "GITHUB_ACTIONS", "GENTAR_DIR", "GENTAR_SUBJECT",
                  "GENTAR_LOCK_DIR"):
            env.pop(k, None)
        self.err = self.tmp / "err.txt"
        out = open(self.err, "w")
        self.addCleanup(out.close)
        p = subprocess.Popen(["/bin/bash", "gentar/run.sh", "--stage-engine"], cwd=self.repo, env=env,
                             stdout=subprocess.DEVNULL, stderr=out)
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        return p

    def test_a_run_waits_on_a_lock_in_the_private_root(self):
        self.root.mkdir(mode=0o755)                    # wider than it should be: it gets tightened
        os.chmod(self.root, 0o755)
        holder = Holder(self.root / "gentar-arena-lockrepo").hold()
        self.addCleanup(holder.release)
        p = self.start()
        self.assertTrue(wait_until(lambda: "waiting" in self.err.read_text(), 30), self.err.read_text())
        self.assertIsNone(p.poll(), self.err.read_text())
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        holder.release()
        p.wait(timeout=60)
        self.assertIn("no-engine", self.err.read_text())   # ... at the clone, after the lock

    def test_a_first_run_makes_the_private_root(self):
        p = self.start()
        p.wait(timeout=120)
        self.assertTrue(self.root.is_dir(), self.err.read_text())
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()

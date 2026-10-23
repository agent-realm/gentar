"""One invocation, one snapshot: concurrent runs wait before they touch
anything a running arena reads (ground-up review 2026-10-19, B3).

- SB05: the kit's run.sh fetched a new engine into gentar/.arena and
  replaced subjects/<subject> BEFORE taking the host lock, so a run waiting
  behind another changed both under the suites the other was still running.
  The lock is now taken before the first of those writes, by the run path
  and by --stage-engine (which --check calls).
- S2-2: two `bin/arena run` calls in one checkout share a compose project,
  and the second's teardown stopped the first's coordinator. bin/arena now
  takes a host lock keyed by the project before it builds, and `down`
  leaves a live run's arena alone.
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "subject-template" / "gentar"
ARENA = ROOT / "bin" / "arena"


def wait_until(pred, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


class Holder:
    """Another run holding a lock, the way run.sh and bin/arena hold one:
    flock on <base>.lock where the host has flock, else <base>.lock.d with a
    holder note."""

    def __init__(self, base: Path):
        self.base = base
        self.flock = shutil.which("flock")
        self.proc = None

    def hold(self):
        lock = Path(str(self.base) + ".lock")
        if self.flock:
            lock.touch()
            # Its own process group: flock's `sleep` child inherits the
            # locked descriptor, so killing flock alone left the lock held
            # (CI, Linux, on #97); release() kills the whole group.
            self.proc = subprocess.Popen([self.flock, str(lock), "sleep", "120"],
                                         start_new_session=True)
            assert wait_until(lambda: subprocess.run([self.flock, "-n", str(lock), "true"])
                              .returncode != 0)
            Path(str(lock) + ".holder").write_text(f"pid {self.proc.pid} on host since now\n")
        else:
            self.proc = subprocess.Popen(["sleep", "120"])
            d = Path(str(lock) + ".d")
            d.mkdir()
            (d / "holder").write_text(f"pid {self.proc.pid} on host since now\n")
        return self

    def release(self):
        if self.proc and self.proc.poll() is None:
            if self.flock:
                os.killpg(self.proc.pid, signal.SIGKILL)
            else:
                self.proc.kill()
            self.proc.wait()
        d = Path(str(self.base) + ".lock.d")
        if not self.flock and d.exists():
            shutil.rmtree(d)                     # a dead holder's dir, as a stale one

    def free(self):
        """True when nobody holds the lock."""
        lock = Path(str(self.base) + ".lock")
        if self.flock:
            return subprocess.run([self.flock, "-n", str(lock), "true"]).returncode == 0
        return not Path(str(lock) + ".d").exists()


@unittest.skipUnless((KIT / "run.sh").exists() and shutil.which("bash"),
                     "the kit is not in the image build context")
class KitTakesTheLockBeforeStagingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        shutil.copytree(KIT, self.repo / "gentar")
        sc = self.repo / "gentar" / "scenarios"
        shutil.rmtree(sc)
        sc.mkdir()
        (sc / "s.toml").write_text('[scenario]\nsubject = "lockrepo"\n[oracle]\nsteps = ["true"]\n')
        (self.repo / "gentar" / "policy.toml").unlink(missing_ok=True)
        self.locks = self.tmp / "locks"
        self.locks.mkdir()
        (self.locks / "gentar-locks").mkdir(mode=0o777)
        os.chmod(self.locks / "gentar-locks", 0o777)
        self.holder = Holder(self.locks / "gentar-locks" / "gentar-arena-lockrepo").hold()
        self.addCleanup(self.holder.release)

    def start(self, *args):
        env = dict(os.environ, GENTAR_LOCK_DIR=str(self.locks),
                   GENTAR_REPO_URL=str(self.tmp / "no-engine"),
                   PATH=f"{os.path.dirname(sys.executable)}:{os.environ['PATH']}")
        for k in ("GITHUB_EVENT_NAME", "CI", "GITHUB_ACTIONS", "GENTAR_DIR", "GENTAR_SUBJECT"):
            env.pop(k, None)
        self.err = self.tmp / "err.txt"
        out = open(self.err, "w")
        self.addCleanup(out.close)
        p = subprocess.Popen(["/bin/bash", "gentar/run.sh", *args], cwd=self.repo, env=env,
                             stdout=subprocess.DEVNULL, stderr=out)
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        return p

    def waits_then_goes(self, *args):
        engine = self.repo / "gentar" / ".arena"
        p = self.start(*args)
        self.assertTrue(wait_until(lambda: "waiting" in self.err.read_text()),
                        self.err.read_text())
        time.sleep(1)
        self.assertIsNone(p.poll(), "did not wait for the lock: " + self.err.read_text())
        self.assertFalse(engine.exists(), "touched the engine checkout before the lock")
        self.holder.release()
        p.wait(timeout=60)
        self.assertNotEqual(p.returncode, 0)             # no engine to clone: it fails
        self.assertIn("no-engine", self.err.read_text())  # ... at the clone, after the lock
        self.assertTrue(self.holder.free(), "left the lock held after exiting")

    def test_a_run_waits_before_the_engine_and_the_subject(self):
        self.waits_then_goes("s")

    def test_stage_engine_waits_too(self):
        self.waits_then_goes("--stage-engine")

    def test_check_waits_too(self):
        self.waits_then_goes("--check")

    def test_check_takes_the_lock_before_its_child_and_marks_itself(self):
        # the hold through lint and the dry-run, which a test without an
        # engine cannot reach: --check locks first, then starts the child
        text = (KIT / "run.sh").read_text()
        block = text[text.index('if [ "$CHECK_ONLY" = 1 ]; then'):]
        block = block[:block.index("\nfi\n")]
        lock = block.index("arena_lock wait || exit 2")
        self.assertLess(lock, block.index("export GENTAR_LOCK_HOLDER_PID=$$"))
        self.assertLess(block.index("export GENTAR_LOCK_HOLDER_PID=$$"),
                        block.index('"$HERE/$(basename "$0")" --stage-engine'))

    def test_check_holds_the_lock_and_its_own_child_does_not_wait_on_it(self):
        # agy on #97: --check now holds the lock through lint and the
        # dry-run; its child --stage-engine must not wait on its parent
        self.holder.release()
        p = self.start("--check")
        try:
            p.wait(timeout=60)                 # a deadlock would hang here
        except subprocess.TimeoutExpired:
            self.fail("--check deadlocked on its own --stage-engine: " + self.err.read_text())
        self.assertNotEqual(p.returncode, 0)                  # no engine to clone
        self.assertNotIn("waiting", self.err.read_text())
        self.assertIn("no-engine", self.err.read_text())
        self.assertTrue(self.holder.free(), "left the lock held after exiting")


def lock_functions():
    src = ARENA.read_text()
    i = src.index("project_name() {")
    return src[i:src.index("\n_torn_down=0", i)]


@unittest.skipUnless(ARENA.exists() and shutil.which("bash"),
                     "bin/arena is not in the image build context")
class BinArenaLockTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "gentar-locks").mkdir(mode=0o777)
        self.base = self.tmp / "gentar-locks" / "gentar-project-proj-x"

    def sh(self, body):
        script = ('compose() { echo \'{"name": "proj-x", "services": {}}\'; }\n'
                  + lock_functions() + "\n" + body)
        return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True,
                              env=dict(os.environ, GENTAR_LOCK_DIR=str(self.tmp)), timeout=30)

    def test_free_then_held_then_free(self):
        r = self.sh('arena_lock try; echo "rc=$?"; cat "$(_lock_base).lock.holder" '
                    '"$(_lock_base).lock.d/holder" 2>/dev/null; arena_unlock; echo done')
        self.assertIn("rc=0", r.stdout, r.stderr)
        self.assertIn("pid ", r.stdout)
        self.assertTrue(Holder(self.base).free())

    def test_a_live_holder_is_waited_for(self):
        h = Holder(self.base).hold()
        self.addCleanup(h.release)
        r = self.sh('arena_lock try; echo "rc=$?"')
        self.assertIn("rc=1", r.stdout, r.stderr)

    def test_a_dead_holders_lock_dir_is_taken(self):
        if shutil.which("flock"):
            self.skipTest("flock releases with its holder; the dir path is the fallback")
        dead = subprocess.Popen(["true"])
        dead.wait()
        d = Path(str(self.base) + ".lock.d")
        d.mkdir()
        (d / "holder").write_text(f"pid {dead.pid} on host since then\n")
        r = self.sh('arena_lock try; echo "rc=$?"')
        self.assertIn("rc=0", r.stdout, r.stderr)

    def test_a_symlinked_lock_root_is_refused(self):
        shutil.rmtree(self.tmp / "gentar-locks")
        (self.tmp / "elsewhere").mkdir()
        (self.tmp / "gentar-locks").symlink_to(self.tmp / "elsewhere")
        r = self.sh('arena_lock try; echo "rc=$?"')
        self.assertIn("rc=2", r.stdout)
        self.assertIn("symlink", r.stderr)

    def test_down_leaves_a_live_run_alone(self):
        h = Holder(self.base).hold()
        self.addCleanup(h.release)
        src = ARENA.read_text()
        i = src.index("cmd_down() {")
        down = src[i:src.index("\n}\n", i) + 3]
        r = self.sh('down_all() { echo DOWN_ALL; }\n' + down + "cmd_down")
        self.assertIn("left alone", r.stdout, r.stderr)
        self.assertNotIn("DOWN_ALL", r.stdout)

    def test_down_leaves_the_arena_when_the_lock_cannot_be_checked(self):
        # agy on #97: it used to tear down regardless
        shutil.rmtree(self.tmp / "gentar-locks")
        (self.tmp / "elsewhere").mkdir()
        (self.tmp / "gentar-locks").symlink_to(self.tmp / "elsewhere")
        src = ARENA.read_text()
        i = src.index("cmd_down() {")
        down = src[i:src.index("\n}\n", i) + 3]
        r = self.sh('down_all() { echo DOWN_ALL; }\n' + down + "cmd_down")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not torn down", r.stderr)
        self.assertNotIn("DOWN_ALL", r.stdout)

    def test_every_command_that_tears_down_locks_first(self):
        src = ARENA.read_text()
        for fn in ("cmd_run", "cmd_dashboard", "cmd_ls"):
            with self.subTest(fn=fn):
                body = src[src.index(f"{fn}() {{"):]
                body = body[:body.index("\n}\n")]
                self.assertIn("arena_lock wait", body)
                self.assertLess(body.index("arena_lock wait"), body.index("arm_traps"))
        td = src[src.index("teardown() {"):]
        td = td[:td.index("\n}\n")]
        self.assertEqual(td.count("arena_unlock"), 2)    # kept up, and torn down


if __name__ == "__main__":
    unittest.main()

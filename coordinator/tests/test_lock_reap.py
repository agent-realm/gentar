"""A dead holder's lock is reclaimed by one waiter only (#100).

In the no-flock fallback (stock macOS), a waiter that finds the lock
directory's holder dead removes the directory and takes the lock itself. Two
waiters could both read the dead holder's note before either removed it; the
second then removed the lock the first had just taken, and both ran. Now a
reclaim takes a reap mutex, re-reads the note under it, and removes the
directory only if the note is still the one judged dead.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "subject-template" / "gentar" / "run.sh"
ARENA = ROOT / "bin" / "arena"
SYSTEM = "/usr/bin:/bin:/usr/sbin:/sbin"
# What the fallback path calls, linked into a PATH without flock, so that the
# fallback runs on Linux too.
TOOLS = ("awk", "cat", "chmod", "date", "dirname", "find", "head", "hostname", "id",
         "mkdir", "mktemp", "mv", "rm", "rmdir", "sleep")


def section(script, start, end):
    text = script.read_text()
    return text[text.index(start):text.index(end)]


def reap_block(script):
    return section(script, "# --- lock reap", "# --- end lock reap")


def lock_code(script):
    """The script's lock code, from the lock root through arena_unlock."""
    text = script.read_text()
    start = text.index("# --- lock root")
    unlock = text.index("arena_unlock() {")
    return text[start:text.index("\n}\n", unlock) + 3]


@unittest.skipUnless(RUN.exists() and ARENA.exists(), "the kit and bin/ are not in the image build context")
class LockReapTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.d = self.tmp / "x.lock.d"
        self.m = self.tmp / "x.lock.d.reap"

    def reap(self, seen, script=RUN, path=SYSTEM, quiet=True, **env):
        """_lock_reap called as the lock loops call it, on the left of `||`."""
        code = f'set -euo pipefail\n{reap_block(script)}\nrc=0; _lock_reap "$1" "$2" || rc=$?; echo "$rc"\n'
        r = subprocess.run(["/bin/bash", "-c", code, "reap", str(self.d), seen],
                           env={"PATH": path, **env}, capture_output=True, text=True)
        if quiet:
            self.assertEqual(r.stderr, "")
            return int(r.stdout.strip())
        return int(r.stdout.strip()), r.stderr

    def test_the_note_is_read_and_the_lock_removed_under_the_mutex(self):
        # A reaper that read the note, or released the mutex, outside the
        # critical section would reopen #100.
        bindir = self.tmp / "bin"
        bindir.mkdir()
        log = self.tmp / "under.log"
        head, rm = shutil.which("head", path=SYSTEM), shutil.which("rm", path=SYSTEM)
        (bindir / "head").write_text(
            f'#!/bin/sh\nif [ -d "$M" ]; then echo head-held; else echo head-free; fi >> "$LOG"\n'
            f'exec {head} "$@"\n')
        (bindir / "rm").write_text(
            '#!/bin/sh\nfor a; do [ "$a" = "$D" ] || continue\n'
            '  if [ -d "$M" ]; then echo rm-held; else echo rm-free; fi >> "$LOG"; done\n'
            f'exec {rm} "$@"\n')
        for tool in ("head", "rm"):
            (bindir / tool).chmod(0o755)
        note = self.dead_lock()
        rc = self.reap(note, path=f"{bindir}:{SYSTEM}",
                       M=str(self.m), D=str(self.d), LOG=str(log))
        self.assertEqual(rc, 0)
        self.assertEqual(log.read_text().split(), ["head-held", "rm-held"])

    def test_a_fresh_lock_with_no_note_is_left_alone_whatever_was_seen(self):
        # Another waiter took it a moment ago and has not yet written its note.
        self.d.mkdir()
        self.assertEqual(self.reap("pid 999999 on host since then"), 1)
        self.assertTrue(self.d.is_dir())

    def test_an_old_lock_that_now_has_a_note_is_left_alone(self):
        # Seen with no note; since then another waiter took it and wrote one.
        self.dead_lock("pid 4242 on host since now")
        self.age(self.d)
        self.assertEqual(self.reap(""), 1)
        self.assertTrue(self.d.is_dir())

    @unittest.skipIf(os.geteuid() == 0, "root can remove anything")
    def test_a_stale_mutex_that_cannot_be_removed_says_so(self):
        note = self.dead_lock()
        self.m.mkdir()
        stuck = self.m / "stuck"
        stuck.mkdir()
        (stuck / "f").write_text("x")
        os.chmod(stuck, 0o555)
        self.addCleanup(os.chmod, stuck, 0o755)
        self.age(self.m)
        rc, err = self.reap(note, quiet=False)
        self.assertEqual(rc, 2)
        self.assertIn("stale reap mutex", err)
        self.assertIn("remove it: rm -rf", err)
        self.assertTrue(self.d.is_dir())

    def dead_lock(self, note="pid 999999 on host since then"):
        self.d.mkdir()
        (self.d / "holder").write_text(note + "\n")
        return note

    def age(self, p, seconds=120):
        t = time.time() - seconds
        os.utime(p, (t, t), follow_symlinks=False)

    def test_the_kit_and_bin_arena_hold_the_same_reap_block(self):
        self.assertEqual(reap_block(RUN), reap_block(ARENA))

    def test_both_lock_loops_reclaim_through_it(self):
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn('_lock_reap "$d" "$note" || rrc=$?', text)
                self.assertNotIn('rm -rf "$d" 2>/dev/null && continue', text)

    def test_every_caller_runs_the_lock_with_errexit_off_as_the_tests_do(self):
        # bash turns errexit off inside a function on the left of `||`. The
        # tests call arena_lock and _lock_reap that way; so must every caller.
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                calls = [line for line in script.read_text().splitlines()
                         if re.search(r"\barena_lock (wait|try)\b", line)]
                self.assertGreaterEqual(len(calls), 2)
                for line in calls:
                    self.assertIn("||", line, line.strip())

    def test_a_dead_holders_lock_is_removed_when_its_note_is_unchanged(self):
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                note = self.dead_lock()
                self.assertEqual(self.reap(note, script), 0)
                self.assertFalse(self.d.exists())
                self.assertFalse(self.m.exists())

    def test_a_lock_whose_note_changed_is_left_alone(self):
        # Another waiter reclaimed it first and holds it now.
        self.dead_lock("pid 4242 on host since now")
        self.assertEqual(self.reap("pid 999999 on host since then"), 1)
        self.assertEqual((self.d / "holder").read_text(), "pid 4242 on host since now\n")
        self.assertFalse(self.m.exists())

    def test_a_fresh_lock_with_no_note_yet_is_left_alone(self):
        # Another waiter has just made it and not yet written its note.
        self.d.mkdir()
        self.assertEqual(self.reap(""), 1)
        self.assertTrue(self.d.is_dir())

    def test_an_old_lock_with_no_note_is_removed(self):
        self.d.mkdir()
        self.age(self.d)
        self.assertEqual(self.reap(""), 0)
        self.assertFalse(self.d.exists())

    def test_a_held_reap_mutex_means_wait(self):
        note = self.dead_lock()
        self.m.mkdir()
        self.assertEqual(self.reap(note), 1)
        self.assertTrue(self.d.is_dir())
        self.assertTrue(self.m.is_dir(), "removed another waiter's live mutex")

    def test_a_reap_mutex_left_over_a_minute_is_cleared(self):
        note = self.dead_lock()
        self.m.mkdir()
        self.age(self.m)
        self.assertEqual(self.reap(note), 1)          # cleared; the next look reclaims
        self.assertFalse(self.m.exists())
        self.assertTrue(self.d.is_dir())
        self.assertEqual(self.reap(note), 0)
        self.assertFalse(self.d.exists())

    @unittest.skipIf(os.geteuid() == 0, "root can write anywhere")
    def test_a_lock_root_we_cannot_write_says_so(self):
        # No mutex can be made there, and none is there to wait for: "busy"
        # would loop forever (found in review of #118).
        note = self.dead_lock()
        os.chmod(self.tmp, 0o555)
        self.addCleanup(os.chmod, self.tmp, 0o755)
        self.assertEqual(self.reap(note), 2)
        self.assertTrue(self.d.is_dir())

    @unittest.skipIf(os.geteuid() == 0, "root can remove anything")
    def test_a_lock_that_cannot_be_removed_says_so_and_frees_the_mutex(self):
        note = self.dead_lock()
        os.chmod(self.d, 0o555)
        self.addCleanup(os.chmod, self.d, 0o755)
        self.assertEqual(self.reap(note), 2)
        self.assertFalse(self.m.exists())


@unittest.skipUnless(RUN.exists() and ARENA.exists(), "the kit and bin/ are not in the image build context")
class TwoWaitersOnOneDeadHolderTest(unittest.TestCase):
    """#100's interleaving, forced: B reads the dead note first, A reclaims and
    takes the lock, then B acts on its earlier read. B must not take A's lock."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for tool in TOOLS:
            found = shutil.which(tool, path=SYSTEM)
            if found:
                (self.bin / tool).symlink_to(found)
        # ps is asked only about a pid that kill -0 found gone. B's ps pauses
        # until A holds the lock: B has read the dead note, and acts on it late.
        (self.bin / "ps").write_text(
            '#!/bin/sh\n'
            'if [ "${WAITER:-}" = B ]; then\n'
            '  : > "$T/b-judged"\n'
            '  i=0; while [ ! -e "$T/a-holds" ] && [ $i -lt 200 ]; do sleep 0.05; i=$((i+1)); done\n'
            'fi\n'
            'exit 1\n')
        (self.bin / "ps").chmod(0o755)
        self.assertIsNone(shutil.which("flock", path=str(self.bin)))
        self.locks = self.tmp / "locks"
        self.locks.mkdir()
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.dead_note = f"pid {dead.pid} on host since then"

    def waiter(self, script, name, then, mode="try"):
        code = (f'set -euo pipefail\nSUBJECT=reap\nproject_name() {{ echo reap; }}\n'
                f'{lock_code(script)}\n'
                f'rc=0; arena_lock {mode} || rc=$?\necho "$rc" > "$T/{name}-rc"\n{then}\n')
        env = {"PATH": str(self.bin), "T": str(self.tmp), "WAITER": name,
               "GENTAR_LOCK_DIR": str(self.locks), "LOCK_PROJECT": "reap"}
        return subprocess.Popen(["/bin/bash", "-c", code], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def wait_for(self, path, seconds=10):
        end = time.time() + seconds
        while not path.exists():
            self.assertLess(time.time(), end, f"timed out waiting for {path.name}")
            time.sleep(0.02)

    def test_the_second_waiter_does_not_take_the_lock_the_first_reclaimed(self):
        for script, base in ((RUN, "gentar-arena-reap"), (ARENA, "gentar-project-reap")):
            with self.subTest(script=script.name):
                for f in ("b-judged", "a-holds", "b-done", "A-rc", "B-rc"):
                    (self.tmp / f).unlink(missing_ok=True)
                root = self.locks / "gentar-locks"
                root.mkdir(exist_ok=True)
                d = root / f"{base}.lock.d"
                shutil.rmtree(d, ignore_errors=True)
                d.mkdir()
                (d / "holder").write_text(self.dead_note + "\n")

                b = self.waiter(script, "B", "")
                self.wait_for(self.tmp / "b-judged")
                # A holds the lock until B has acted on its stale read.
                a = self.waiter(script, "A",
                                ': > "$T/a-holds"; i=0; '
                                'while [ ! -e "$T/B-rc" ] && [ $i -lt 200 ]; do sleep 0.05; i=$((i+1)); done')
                b_out = self.finish(b)
                a_out = self.finish(a)
                self.assertEqual((self.tmp / "A-rc").read_text().strip(), "0", a_out)
                self.assertEqual((self.tmp / "B-rc").read_text().strip(), "1",
                                 f"B took the lock A had reclaimed: {b_out}")
                self.assertIn(f"pid {a.pid} ", (d / "holder").read_text())

    def finish(self, proc, seconds=30):
        """The waiter's output; kill it and fail if it is still waiting."""
        try:
            return proc.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            self.fail(f"still waiting after {seconds}s")

    def dead_lock_in(self, base):
        root = self.locks / "gentar-locks"
        root.mkdir(exist_ok=True)
        d = root / f"{base}.lock.d"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        (d / "holder").write_text(self.dead_note + "\n")
        (self.tmp / "C-rc").unlink(missing_ok=True)
        return root, d

    @unittest.skipIf(os.geteuid() == 0, "root can write anywhere")
    def test_a_lock_root_we_cannot_write_is_named_not_waited_on(self):
        # What main said before the reap mutex, and must still say: the
        # stale lock cannot be removed by this user, and how to remove it.
        for script, base in ((RUN, "gentar-arena-reap"), (ARENA, "gentar-project-reap")):
            with self.subTest(script=script.name):
                root, d = self.dead_lock_in(base)
                os.chmod(root, 0o555)
                try:
                    c = self.waiter(script, "C", "", mode="wait")
                    out, err = self.finish(c)
                finally:
                    os.chmod(root, 0o755)
                self.assertEqual((self.tmp / "C-rc").read_text().strip(), "2", err)
                self.assertIn("cannot be removed by", err)
                self.assertTrue(d.is_dir())

    @unittest.skipIf(os.geteuid() == 0, "root can remove anything")
    def test_an_unremovable_stale_lock_is_named_by_the_loop(self):
        for script, base in ((RUN, "gentar-arena-reap"), (ARENA, "gentar-project-reap")):
            with self.subTest(script=script.name):
                root, d = self.dead_lock_in(base)
                os.chmod(d, 0o555)                    # its note cannot be deleted
                try:
                    c = self.waiter(script, "C", "", mode="wait")
                    out, err = self.finish(c)
                finally:
                    os.chmod(d, 0o755)
                self.assertEqual((self.tmp / "C-rc").read_text().strip(), "2", err)
                self.assertIn("cannot be removed by", err)

    def test_wait_waits_for_the_reclaimer_and_then_takes_the_lock(self):
        for script, base in ((RUN, "gentar-arena-reap"), (ARENA, "gentar-project-reap")):
            with self.subTest(script=script.name):
                for f in ("b-judged", "a-holds", "A-rc", "B-rc"):
                    (self.tmp / f).unlink(missing_ok=True)
                root, d = self.dead_lock_in(base)
                b = self.waiter(script, "B", "", mode="wait")
                self.wait_for(self.tmp / "b-judged")
                a = self.waiter(script, "A", ': > "$T/a-holds"; sleep 2; arena_unlock')
                a_out = self.finish(a)
                b_out = self.finish(b)
                self.assertEqual((self.tmp / "A-rc").read_text().strip(), "0", a_out)
                self.assertEqual((self.tmp / "B-rc").read_text().strip(), "0", b_out)
                self.assertIn("in use", b_out[1])
                self.assertIn(f"pid {b.pid} ", (d / "holder").read_text())

    def test_try_returns_at_once_while_another_waiter_reaps(self):
        for script, base in ((RUN, "gentar-arena-reap"), (ARENA, "gentar-project-reap")):
            with self.subTest(script=script.name):
                root, d = self.dead_lock_in(base)
                m = root / f"{base}.lock.d.reap"
                m.mkdir(exist_ok=True)
                try:
                    c = self.waiter(script, "C", "")
                    out, err = self.finish(c)
                finally:
                    m.rmdir()
                self.assertEqual((self.tmp / "C-rc").read_text().strip(), "1", err)
                self.assertTrue(d.is_dir())


if __name__ == "__main__":
    unittest.main()

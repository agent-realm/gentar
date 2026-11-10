"""In local mode the workspace root must be this account's own.

Each bench's workspace, the subject's code with it, lives under
GENTAR_BENCH_WORKSPACE_ROOT (default /tmp/gentar-workspaces), and compose binds
that root into the arena. The kit's run.sh and bin/arena made it with a bare
`mkdir -p`: on a host with several accounts the first one to run made it 0755,
readable by the others, and an account that made the path first, or a symlink
there, had the arena use its directory. Now a symlink or a directory another
user owns is refused (exit 2), a new root is made 0700, and one of ours is
kept at 0700. The default path stays, so a host's existing 0700 rule passes.
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "subject-template" / "gentar" / "run.sh"
ARENA = ROOT / "bin" / "arena"

CALL = 'workspace_root_own "$GENTAR_BENCH_WORKSPACE_ROOT" || exit 2'


def block(script):
    text = script.read_text()
    return text[text.index("# --- workspace root"):text.index("# --- end workspace root")]


@unittest.skipUnless(RUN.exists() and ARENA.exists(), "the kit and bin/ are not in the image build context")
class WorkspaceRootOwnerTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def own(self, root, script=RUN, path=None):
        """Run the script's own function on ROOT; returns the process."""
        code = f'set -euo pipefail\n{block(script)}\nworkspace_root_own "$1"\n'
        env = {"PATH": path or "/usr/bin:/bin"}
        return subprocess.run(["/bin/bash", "-c", code, "own", str(root)], env=env,
                              capture_output=True, text=True)

    def mode(self, p):
        return stat.S_IMODE(p.stat().st_mode)

    def test_the_kit_and_bin_arena_hold_the_same_block(self):
        self.assertEqual(block(RUN), block(ARENA))

    def test_both_scripts_call_it_instead_of_a_bare_mkdir(self):
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn(CALL, text)
                self.assertNotIn('mkdir -p "$GENTAR_BENCH_WORKSPACE_ROOT"', text)
                self.assertIn('GENTAR_BENCH_WORKSPACE_ROOT:-/tmp/gentar-workspaces', text)

    def test_a_new_root_is_made_owner_only(self):
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                root = self.tmp / script.name / "parent" / "ws"
                r = self.own(root, script)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(root.is_dir())
                self.assertEqual(self.mode(root), 0o700)

    def test_a_provisioned_0700_root_of_ours_passes_unchanged(self):
        # What a host's tmpfiles rule (`d <root> 0700 <account> <account> -`,
        # as bin/bench-host-provision writes it) leaves for a run: it passes,
        # and keeps its mode and its benches.
        for script in (RUN, ARENA):
            with self.subTest(script=script.name):
                root = self.tmp / f"provisioned-{script.name}"
                root.mkdir(mode=0o700)
                os.chmod(root, 0o700)
                (root / "bench-1").mkdir()
                before = root.stat()
                r = self.own(root, script)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr, "")
                self.assertEqual(self.mode(root), 0o700)
                self.assertEqual(root.stat().st_ino, before.st_ino)
                self.assertTrue((root / "bench-1").is_dir())

    def test_a_root_of_ours_is_kept_and_tightened(self):
        root = self.tmp / "ws"
        root.mkdir(mode=0o755)
        os.chmod(root, 0o755)                   # what a bare `mkdir -p` under umask 022 made
        (root / "bench-1").mkdir()
        r = self.own(root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mode(root), 0o700)
        self.assertTrue((root / "bench-1").is_dir())

    def test_a_symlink_is_refused_and_left_alone(self):
        theirs = self.tmp / "theirs"
        theirs.mkdir(mode=0o755)
        os.chmod(theirs, 0o755)
        root = self.tmp / "ws"
        root.symlink_to(theirs)
        r = self.own(root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("workspace root refused", r.stderr)
        self.assertTrue(root.is_symlink())
        self.assertEqual(self.mode(theirs), 0o755)

    def test_a_dangling_symlink_is_refused_and_nothing_is_made_through_it(self):
        target = self.tmp / "not-yet"
        root = self.tmp / "ws"
        root.symlink_to(target)
        r = self.own(root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(target.exists())

    def test_a_symlink_given_with_a_trailing_slash_or_a_dot_is_refused_and_left_alone(self):
        # `[ -L "link/" ]` reads through the link, and -d/-O then test its
        # target: a root given that way passed and was bound through the link.
        theirs = self.tmp / "theirs"
        theirs.mkdir(mode=0o755)
        os.chmod(theirs, 0o755)
        link = self.tmp / "ws"
        link.symlink_to(theirs)
        for script in (RUN, ARENA):
            for given in (f"{link}/", f"{link}//", f"{link}/.", f"{self.tmp}/./ws",
                          f"{self.tmp}/sub/../ws", "/"):
                with self.subTest(script=script.name, given=given):
                    r = self.own(given, script)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("ends in / or holds a . or .. component", r.stderr)
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(self.mode(theirs), 0o755)

    @unittest.skipIf(os.geteuid() == 0, "root owns nothing it cannot take")
    def test_a_directory_another_user_owns_is_refused(self):
        # /usr stands in for a directory someone else owns. The refusal comes
        # before chmod, so nothing is attempted on it.
        r = self.own("/usr")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("workspace root refused", r.stderr)

    def test_a_file_is_refused(self):
        root = self.tmp / "ws"
        root.write_text("not a directory")
        r = self.own(root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_a_relative_path_is_refused_and_nothing_is_made(self):
        code = f'set -euo pipefail\n{block(RUN)}\nworkspace_root_own "$1"\n'
        r = subprocess.run(["/bin/bash", "-c", code, "own", "rel/ws"], cwd=self.tmp,
                           env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("not an absolute path", r.stderr)
        self.assertFalse((self.tmp / "rel").exists())

    def test_a_new_root_is_owner_only_from_its_mkdir_not_only_after_chmod(self):
        # With chmod made a no-op, the mode is mkdir's own: no window in which a
        # new root is readable by other accounts.
        (self.bin / "chmod").write_text("#!/bin/sh\nexit 0\n")
        (self.bin / "chmod").chmod(0o755)
        root = self.tmp / "ws"
        r = self.own(root, path=f"{self.bin}:/usr/bin:/bin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mode(root), 0o700)

    def test_a_root_that_is_still_missing_after_mkdir_is_refused(self):
        # A mkdir that makes nothing (on a host: a race lost to another account):
        # the check after it decides, never the mkdir's own status.
        (self.bin / "mkdir").write_text("#!/bin/sh\nexit 0\n")
        (self.bin / "mkdir").chmod(0o755)
        r = self.own(self.tmp / "ws", path=f"{self.bin}:/usr/bin:/bin")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

"""bench-template/build.sh works the way its header says to run it.

The header said `ssh bench-host 'sh -s' < bench-template/build.sh`, and the
script read `$(cat VERSION)` from the bench-host's working directory, where
no VERSION exists: under `set -e` it stopped there (ground-up review B4).
The pin now travels as the first argument. Driven against a stub `sbx`
that only logs its arguments, so nothing is built.
"""

import os
import pwd
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "bench-template" / "build.sh"
PIN = (ROOT / "bench-template" / "VERSION").read_text().strip() if BUILD.exists() else ""

SBX_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$SBX_LOG"
# `create --name gentar-tpl-build shell WS`: record what the builder would mount
[ "$1" = create ] && ls -ld "$5" | cut -c1-10 >> "$SBX_LOG"
[ "$1" = "${SBX_FAIL:-}" ] && exit 1
exit 0
"""

# Stands in for rm where a broken check could otherwise delete what is not ours.
RM_STUB = """#!/bin/sh
printf 'rm %s\\n' "$*" >> "$SBX_LOG"
exit 1
"""

# An rm that reports success and removes nothing: only `mkdir` without -p can
# then stop a build from using a workspace that is still there.
RM_NOOP_STUB = """#!/bin/sh
exit 0
"""

# The host's rm, logged under its own tag (sbx's own `rm` subcommand is logged too).
RM_LOGGING_STUB = """#!/bin/sh
printf 'host-rm %s\\n' "$*" >> "$SBX_LOG"
exec /bin/rm "$@"
"""


@unittest.skipUnless(BUILD.exists(), "bench-template/ is not in the image build context")
class BenchTemplateBuildTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "sbx").write_text(SBX_STUB)
        (bindir / "sbx").chmod(0o755)
        self.log = self.tmp / "sbx.log"
        self.env = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", SBX_LOG=str(self.log),
                        GENTAR_TEMPLATE_WS=str(self.tmp / "ws"))
        self.home = self.tmp / "home"          # a bench-host cwd: no VERSION here
        self.home.mkdir()

    def piped(self, *args):
        """`ssh bench-host sh -s -- ARGS < bench-template/build.sh`, minus ssh."""
        with open(BUILD) as script:
            return subprocess.run(["sh", "-s", "--", *args], stdin=script, cwd=self.home,
                                  env=self.env, capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_the_documented_pipe_builds_the_pinned_version(self):
        self.assertIn('sh -s -- "$(cat bench-template/VERSION)" < bench-template/build.sh',
                      BUILD.read_text())
        r = self.piped(PIN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"@anthropic-ai/claude-code@{PIN}", self.calls())
        self.assertIn("template save gentar-tpl-build gentar-bench-v1", self.calls())

    def test_piped_without_the_pin_refuses_before_any_sbx_call(self):
        r = self.piped()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("pass it as the first argument", r.stderr)
        self.assertEqual(self.calls(), "")

    def test_a_copy_of_the_directory_reads_its_version_file(self):
        copy = self.tmp / "bench-template"
        shutil.copytree(BUILD.parent, copy)
        r = subprocess.run(["sh", "build.sh"], cwd=copy, env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"@anthropic-ai/claude-code@{PIN}", self.calls())

    def test_a_hostile_version_is_refused(self):
        r = self.piped("1.0; touch /tmp/x")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.calls(), "")


@unittest.skipUnless(BUILD.exists(), "bench-template/ is not in the image build context")
class BuilderWorkspaceIsTheAccountsOwnTest(unittest.TestCase):
    """The builder mounts its workspace into the builder sandbox. On a host with
    several bench accounts, a shared default in /tmp could be made first by
    another account, or be its symlink, and the template would then be built
    from that account's directory. The default is per user, private, and a
    workspace that is not the account's own is refused before any sbx call."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        (self.bindir / "sbx").write_text(SBX_STUB)
        (self.bindir / "sbx").chmod(0o755)
        self.log = self.tmp / "sbx.log"
        self.env = dict(os.environ, PATH=f"{self.bindir}:/usr/bin:/bin", SBX_LOG=str(self.log),
                        TMPDIR=str(self.tmp))
        self.env.pop("GENTAR_TEMPLATE_WS", None)
        self.default_ws = self.tmp / f"gentar-template-build-{pwd.getpwuid(os.geteuid()).pw_name}"

    def build(self, **env):
        with open(BUILD) as script:
            return subprocess.run(["sh", "-s", "--", PIN], stdin=script, cwd=self.tmp,
                                  env=dict(self.env, **env), capture_output=True, text=True,
                                  timeout=60)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_the_default_workspace_is_per_user_private_and_removed(self):
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"create --name gentar-tpl-build shell {self.default_ws}\ndrwx------",
                      self.calls())
        self.assertFalse(self.default_ws.exists())
        self.assertNotIn("/tmp/gentar-template-build\n", self.calls())

    def test_a_stale_workspace_of_ours_is_emptied_and_made_private(self):
        ws = self.tmp / "ws"
        ws.mkdir(mode=0o755)
        os.chmod(ws, 0o755)
        (ws / "stale").write_text("from an earlier build")
        r = self.build(GENTAR_TEMPLATE_WS=str(ws))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"shell {ws}\ndrwx------", self.calls())
        self.assertFalse(ws.exists())

    def test_a_symlink_at_the_default_path_is_refused_before_any_sbx_call(self):
        theirs = self.tmp / "theirs"
        theirs.mkdir()
        (theirs / ".npmrc").write_text("registry=http://example-host/\n")
        self.default_ws.symlink_to(theirs)
        r = self.build()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("builder workspace refused", r.stderr)
        self.assertEqual(self.calls(), "")
        self.assertTrue(self.default_ws.is_symlink())
        self.assertTrue((theirs / ".npmrc").exists())

    @unittest.skipIf(os.geteuid() == 0, "root owns nothing it cannot take")
    def test_a_workspace_another_user_owns_is_refused_and_left_alone(self):
        # /usr stands in for a directory someone else owns; rm is a stub that
        # deletes nothing, in case the check ever lets it through.
        (self.bindir / "rm").write_text(RM_STUB)
        (self.bindir / "rm").chmod(0o755)
        r = self.build(GENTAR_TEMPLATE_WS="/usr")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("builder workspace refused", r.stderr)
        self.assertEqual(self.calls(), "")

    def test_a_workspace_still_there_after_rm_stops_the_build_before_any_sbx_call(self):
        # The workspace is made without -p: if it is still there after rm (here an
        # rm that removes nothing; on a host, a path re-made in between), the
        # build stops instead of mounting it.
        (self.bindir / "rm").write_text(RM_NOOP_STUB)
        (self.bindir / "rm").chmod(0o755)
        self.default_ws.mkdir()
        (self.default_ws / "planted").write_text("not cleared")
        r = self.build()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls(), "")

    def test_an_absent_workspace_is_not_removed_before_it_is_made(self):
        # Absent at the check, so there is nothing of ours to clear: no rm runs
        # before the build makes it (rm on a path another account made in
        # between would empty what it could inside it).
        (self.bindir / "rm").write_text(RM_LOGGING_STUB)
        (self.bindir / "rm").chmod(0o755)
        r = self.build()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        first = self.calls().splitlines()[0]
        self.assertFalse(first.startswith("host-rm "), self.calls())
        self.assertIn(f"host-rm -rf {self.default_ws}", self.calls())   # the EXIT trap's
        self.assertFalse(self.default_ws.exists())

    def test_a_symlink_given_with_a_trailing_slash_is_refused_and_its_target_kept(self):
        # `rm -rf "link/"` goes through the link: a build given a symlink to a
        # directory of ours as `<link>/` removed that directory. rm is a stub
        # here, so a broken check deletes nothing.
        (self.bindir / "rm").write_text(RM_STUB)
        (self.bindir / "rm").chmod(0o755)
        ours = self.tmp / "ours"
        ours.mkdir()
        (ours / "keep").write_text("not the builder's")
        link = self.tmp / "ws"
        link.symlink_to(ours)
        for given in (f"{link}/", f"{link}/.", f"{link}/..", f"{self.tmp}/./ws",
                      f"{self.tmp}/x/../ws", ".", ".."):
            with self.subTest(given=given):
                r = self.build(GENTAR_TEMPLATE_WS=given)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("ends in / or holds a . or .. component", r.stderr)
                self.assertEqual(self.calls(), "")          # no sbx call, no rm
                self.assertTrue(link.is_symlink())
                self.assertTrue((ours / "keep").exists())

    def test_a_failed_build_still_removes_the_workspace(self):
        r = self.build(SBX_FAIL="exec")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"shell {self.default_ws}", self.calls())
        self.assertNotIn("template save", self.calls())
        self.assertFalse(self.default_ws.exists())


if __name__ == "__main__":
    unittest.main()

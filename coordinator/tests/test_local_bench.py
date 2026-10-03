"""Local bench mode: GENTAR_BENCH_HOST=local, no ssh, no bench key.

The pilot (2026-10-03): adopting gentar should need a runner on an arf VM and
nothing else. When that runner IS the bench host, the arena calls sbx
directly; proven on VM 151 first (the sbx CLI in a container, with the
host's binary, state and config mounted, created a bench, exec'd in it with
a pty, shared the workspace both ways, and removed it).
"""

import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar.benchhost import SbxBenchHost
from gentar.config import Config
from gentar.redaction import scrubber

ROOT = Path(__file__).resolve().parents[2]


def cfg(**env):
    base = {"GENTAR_BENCH_HOST": "local", "GENTAR_REPORT_DIR": ""}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config()


class LocalHostTest(unittest.TestCase):

    def test_commands_run_here_through_sh(self):
        h = SbxBenchHost(cfg())
        self.assertTrue(h.local)
        self.assertEqual(h._ssh_base(), ["sh", "-c"])
        out = h._run(["printf", "%s|%s", "a b", "c'd"]).stdout
        self.assertEqual(out, "a b|c'd")                 # the same quoting as over ssh

    def test_a_remote_host_still_uses_ssh(self):
        h = SbxBenchHost(cfg(GENTAR_BENCH_HOST="10.10.10.52", GENTAR_BENCH_USER="polat"))
        self.assertFalse(h.local)
        self.assertEqual(h._ssh_base()[0], "ssh")

    def test_push_dir_extracts_locally(self):
        src = Path(tempfile.mkdtemp())
        (src / "sub").mkdir()
        (src / "sub" / "f.txt").write_text("hello\n")
        dest = Path(tempfile.mkdtemp()) / "ws"
        SbxBenchHost(cfg()).push_dir(str(src), str(dest))
        self.assertEqual((dest / "sub" / "f.txt").read_text(), "hello\n")

    def test_the_pty_is_the_coordinators_own(self):
        argv = SbxBenchHost(cfg()).pty_spawn_args("box1", 120, 40, {"K": "v w"}, "claude")
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertNotIn("-tt", argv)
        self.assertIn("exec -t box1", argv[2])
        self.assertIn("'K=v w'", argv[2])

    def test_no_user_is_needed(self):
        self.assertEqual(cfg().missing_bench_env("sbx"), [])
        self.assertEqual(cfg(GENTAR_BENCH_HOST="h.example.org").missing_bench_env("sbx"),
                         ["GENTAR_BENCH_USER"])


class RedactionTest(unittest.TestCase):

    def test_the_mode_word_is_not_scrubbed(self):
        s = scrubber([("GENTAR_BENCH_HOST", "local")])
        self.assertEqual(s("bench: local (this runner's host)"), "bench: local (this runner's host)")

    def test_a_real_host_still_is(self):
        s = scrubber([("GENTAR_BENCH_HOST", "bench7.example.org")])
        self.assertNotIn("bench7.example.org", s("ssh polat@bench7.example.org"))


class WiringTest(unittest.TestCase):

    def test_the_overlay_mounts_what_sbx_needs_at_the_same_paths(self):
        f = ROOT / "compose.local-bench.yml"
        if not f.exists():
            self.skipTest("not in this build context")
        t = f.read_text()
        for part in ("/usr/bin/sbx:ro", "/.local/state/sandboxes:${GENTAR_LOCAL_HOME}/.local/state/sandboxes",
                     "/.config/sandboxes:", "/.config/com.docker.sandboxes:",
                     'user: "${GENTAR_LOCAL_UID:?'):
            self.assertIn(part, t)

    def test_the_kit_layers_it_and_needs_no_key(self):
        run = ROOT / "subject-template" / "gentar" / "run.sh"
        wf = ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml"
        if not run.exists():
            self.skipTest("the kit is not in this build context")
        r = run.read_text()
        self.assertIn("ARENA_FILES+=(-f compose.local-bench.yml)", r)
        self.assertIn('GENTAR_BENCH_KEY_FILE=/dev/null', r)
        self.assertIn('[ "${GENTAR_BENCH_HOST:-}" = local ] && return 0', r)
        w = wf.read_text()
        self.assertEqual(w.count("secrets.GENTAR_BENCH_HOST || vars.GENTAR_BENCH_HOST"), 3)
        self.assertIn('if [ "$GENTAR_BENCH_HOST" = local ]; then', w)

    def test_bin_arena_layers_it(self):
        a = (ROOT / "bin" / "arena")
        if not a.exists():
            self.skipTest("not in this build context")
        t = a.read_text()
        self.assertIn("extra+=(-f compose.local-bench.yml)", t)
        self.assertIn("local_bench && return 0", t)


if __name__ == "__main__":
    unittest.main()

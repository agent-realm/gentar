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


HAVE_CHECKOUT = (ROOT / "bin" / "bench-reap").exists() and (ROOT / "subject-template").exists()


class ReviewFixesTest(unittest.TestCase):
    """The fallback review of #64 (Antigravity, gemini-3.8-flash-high)."""

    def test_stray_spaces_never_fall_back_to_ssh(self):
        for v in ("local ", " local", "local\n"):
            c = cfg(GENTAR_BENCH_HOST=v)
            self.assertEqual(c.bench_host, "local", repr(v))
            self.assertTrue(SbxBenchHost(c).local)
            self.assertEqual(c.missing_bench_env("sbx"), [])

    @unittest.skipUnless(HAVE_CHECKOUT, "bin/ and the kit are not in the image build context")
    def test_bench_reap_works_in_local_mode(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp())
        ws = tmp / "ws"
        (ws / "g1-20261003-065126-6868cf").mkdir(parents=True)      # a stranded workspace
        log = tmp / "sbx.log"
        fake = tmp / "sbx"
        fake.write_text("#!/bin/sh\n"
                        f"echo \"$*\" >> {log}\n"
                        'case "$1" in ls) echo \'{"sandboxes":[{"name":"g1-20261003-065041-19538d"},'
                        '{"name":"someone-else"}]}\' ;; esac\n')
        fake.chmod(0o755)
        env = {"PATH": os.environ["PATH"], "HOME": str(tmp), "GENTAR_BENCH_HOST": "local",
               "GENTAR_NAME_PREFIX": "g1", "GENTAR_SBX_BIN": str(fake),
               "GENTAR_BENCH_WORKSPACE_ROOT": str(ws), "GENTAR_ENGINE_DIR": str(tmp)}
        r = subprocess.run(["/bin/bash", str(ROOT / "bin" / "bench-reap")], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reaped sandbox: g1-20261003-065041-19538d", r.stdout)
        self.assertIn("reaped workspace: g1-20261003-065126-6868cf", r.stdout)
        self.assertIn("rm g1-20261003-065041-19538d --force", log.read_text())
        self.assertNotIn("someone-else", log.read_text().replace("ls --json", ""))
        self.assertFalse((ws / "g1-20261003-065126-6868cf").exists())

    @unittest.skipUnless(HAVE_CHECKOUT, "bin/ and the kit are not in the image build context")
    def test_the_kit_reads_the_arena_env_and_refuses_missing_sbx_state(self):
        r = (ROOT / "subject-template" / "gentar" / "run.sh").read_text()
        self.assertIn('elif [ -f "$ARENA/.env" ]; then sed -n \'s/^GENTAR_BENCH_HOST=//p\' "$ARENA/.env"', r)
        self.assertIn("run sbx login as this user first", r)
        self.assertIn('GENTAR_LOCAL_SBX_BIN=$(readlink -f "$SBX_PATH"', r)

    @unittest.skipUnless(HAVE_CHECKOUT, "bin/ and the kit are not in the image build context")
    def test_the_workflow_still_stages_the_clone_key_in_local_mode(self):
        w = (ROOT / "subject-template" / ".github" / "workflows" / "gentar-arena.yml").read_text()
        step = w[w.index("- name: stage bench access"):w.index("- name: run suites")]
        self.assertNotIn("exit 0", step)
        self.assertLess(step.index('printf \'%s\\n\' "$BENCH_KEY"'), step.index('if [ -n "$CLONE_KEY" ]'))
        self.assertLess(step.index("          fi\n          if [ -n \"$CLONE_KEY\" ]"), len(step))


class KeyringLoginTest(unittest.TestCase):
    """VM 142, 2026-10-03: sbx 0.39 kept its Docker login in gnome-keyring.
    sbx in the coordinator (no session bus) read files only, so every bench
    failed at PREPARE IMAGE, and the 400-character head cut hid the reason."""

    def test_an_error_keeps_the_reason_at_the_end(self):
        from gentar.benchhost import clip
        out = ("── RESOLVE SETUP\n" + "   resolving configuration…\n" * 30 +
               "── PREPARE IMAGE\n   → pull docker/sandbox-templates:shell-docker\n"
               "ERROR: encode registry auth: no default account profile set: secret not found")
        c = clip(out)
        self.assertIn("RESOLVE SETUP", c)
        self.assertIn("no default account profile set: secret not found", c)
        self.assertLess(len(c), 530)
        self.assertEqual(clip("short"), "short")

    @unittest.skipUnless(HAVE_CHECKOUT, "bin/ and the kit are not in the image build context")
    def test_the_kit_and_bin_arena_refuse_a_keyring_only_login(self):
        auth = "/.config/com.docker.sandboxes/com.docker.sandboxes-auth/sandboxes-auth"
        for f in (ROOT / "subject-template" / "gentar" / "run.sh", ROOT / "bin" / "arena"):
            t = f.read_text()
            self.assertIn(auth, t, f)
            self.assertIn('ls "$SBX_AUTH" 2>/dev/null | grep -q .', t, f)
            self.assertIn("sbx-file-login", t, f)

    @unittest.skipUnless(HAVE_CHECKOUT, "bin/ and the kit are not in the image build context")
    def test_sbx_file_login_runs_login_without_a_session_bus(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp())
        home = tmp / "home"
        for d in (".local/state/sandboxes", ".config/sandboxes", ".config/com.docker.sandboxes"):
            (home / d).mkdir(parents=True)
        bindir = tmp / "bin"
        bindir.mkdir()
        log = tmp / "docker.args"
        (bindir / "sbx").write_text("#!/bin/sh\nexit 0\n")
        (bindir / "docker").write_text(f'#!/bin/sh\nfor a in "$@"; do echo "$a"; done > {log}\n')
        for f in ("sbx", "docker"):
            (bindir / f).chmod(0o755)
        env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(home),
               "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
        r = subprocess.run(["/bin/bash", str(ROOT / "bin" / "sbx-file-login"),
                            "--username", "u", "--password-stdin"],
                           env=env, input="", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        args = log.read_text().splitlines()
        self.assertEqual(args[-6:-4], ["alpine:3", "sbx"])
        self.assertEqual(args[-4:], ["login", "--username", "u", "--password-stdin"])
        self.assertIn(f"{home}/.config/com.docker.sandboxes:{home}/.config/com.docker.sandboxes", args)
        joined = " ".join(args)
        self.assertNotIn("DBUS", joined)
        self.assertNotIn("/run/user", joined)
        self.assertNotIn("-t", args)                      # stdin is not a terminal here

    @unittest.skipUnless(HAVE_CHECKOUT, "bin/ and the kit are not in the image build context")
    def test_sbx_file_login_refuses_missing_state(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp())
        bindir = tmp / "bin"
        bindir.mkdir()
        (bindir / "sbx").write_text("#!/bin/sh\nexit 0\n")
        (bindir / "sbx").chmod(0o755)
        r = subprocess.run(["/bin/bash", str(ROOT / "bin" / "sbx-file-login")],
                           env={"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp)},
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing or not owned", r.stderr)


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
        self.assertIn('[ "${LOCAL_BENCH:-0}" = 1 ] && return 0', r)
        w = wf.read_text()
        self.assertEqual(w.count("secrets.GENTAR_BENCH_HOST || vars.GENTAR_BENCH_HOST"), 3)
        self.assertIn('''if [ "$(printf '%s' "$GENTAR_BENCH_HOST" | tr -d '[:space:]')" = local ]; then''', w)

    def test_bin_arena_layers_it(self):
        a = (ROOT / "bin" / "arena")
        if not a.exists():
            self.skipTest("not in this build context")
        t = a.read_text()
        self.assertIn("extra+=(-f compose.local-bench.yml)", t)
        self.assertIn("local_bench && return 0", t)


if __name__ == "__main__":
    unittest.main()

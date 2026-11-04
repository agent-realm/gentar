"""An sbx bench-host with stored secrets is refused before any bench exists.

Every sbx sandbox carries `proxy-managed` placeholders for the common
provider keys, and sbx's credential proxy swaps in a real value for any
service with a stored secret. So one `sbx secret set` on a shared host
would hand that key to every suite there, whatever credential group the
engine forwarded (claude-playbooks, measured on a bench host: placeholders
present, no secrets stored — safe by host state only). The engine now
checks, and refuses with exit 2 unless GENTAR_SBX_SECRETS=allow.

The check itself must see only what sbx needs to find its store: with a
provider key in its environment, sbx 0.39 answers with an import note in
place of "No secrets found", and on the local tier the coordinator's
environment, forwarded keys included, was the one it got.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator as coord
from gentar.benchhost import SBX_CHECK_ENV, SbxBenchHost, clean_env_line
from gentar.config import Config


def cfg_with(**env) -> Config:
    base = {"GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u",
            "GENTAR_REPORT_DIR": ""}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config()


def host_answering(cfg, stdout="", rc=0):
    host = SbxBenchHost(cfg)
    calls = []

    def fake_run(cmd, timeout=300, strict=True, clean_env=False):
        calls.append(cmd)
        host.clean_env = clean_env
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")
    host._run = fake_run
    return host, calls


class SbxPreflightTest(unittest.TestCase):

    def test_no_secrets_is_a_go(self):
        host, calls = host_answering(cfg_with(), "No secrets found. Run 'sbx secret set --help'\n")
        self.assertEqual(host.preflight(), [])
        self.assertEqual(calls, [["sbx", "secret", "ls"]])
        self.assertTrue(host.clean_env)

    def test_stored_secrets_refuse_and_never_echo_the_listing(self):
        listing = "SCOPE    SERVICE\n(global) anthropic\n(global) github\n"
        host, _ = host_answering(cfg_with(), listing)
        problems = host.preflight()
        self.assertEqual(len(problems), 1)
        self.assertIn("stored sbx secrets", problems[0])
        self.assertIn("GENTAR_SBX_SECRETS=allow", problems[0])
        self.assertNotIn("anthropic", problems[0])   # a count, not the listing

    def test_an_unanswerable_check_refuses(self):
        host, _ = host_answering(cfg_with(), "unknown command \"secret\"", rc=1)
        self.assertIn("could not check", host.preflight()[0])

    def test_allow_skips_the_check_entirely(self):
        host, calls = host_answering(cfg_with(GENTAR_SBX_SECRETS="allow"), "anything")
        self.assertEqual(host.preflight(), [])
        self.assertEqual(calls, [])


# A stand-in for sbx 0.39's `secret ls`, as measured on a bench host: no HOME
# is a panic, the store is found through XDG_CONFIG_HOME or else HOME, and a
# provider key in the environment adds an import note, which is all it
# prints when nothing is stored. It records the environment it got next to
# itself: env -i leaves it no variable to say where.
FAKE_SBX = r"""#!/bin/sh
env > "$(dirname "$0")/seen-env"
[ "$1 $2" = "secret ls" ] || { echo "unexpected: $*" >&2; exit 64; }
[ -n "${HOME:-}" ] || { echo 'panic: $HOME is not defined' >&2; exit 2; }
store="${XDG_CONFIG_HOME:-$HOME/.config}/sandboxes/stored"
if [ -s "$store" ]; then
  printf 'SCOPE      SERVICE\n'; cat "$store"
elif [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "No secrets found. Run 'sbx secret set --help' to see available services."
fi
[ -z "${ANTHROPIC_API_KEY:-}" ] || printf '\nNote: 1 additional environment variable found. Run `sbx setup` to review and import.\n'
"""

SYNTHETIC = {"ANTHROPIC_API_KEY": "sk-ant-synthetic-0000", "OPENAI_API_KEY": "sk-synthetic-0000",
             "GH_TOKEN": "ghp_synthetic0000", "GENTAR_SUBJECT": "example-subject"}


class CleanEnvironmentTest(unittest.TestCase):
    """The real local-tier path (sh -c) with the stand-in first on PATH."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "sbx").write_text(FAKE_SBX)
        (self.bin / "sbx").chmod(0o755)
        self.home = self.tmp / "home"
        self.home.mkdir()

    def env(self, **extra):
        return {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), **extra}

    def preflight(self, env, **cfg_env):
        with mock.patch.dict(os.environ, env, clear=True):
            host = SbxBenchHost(cfg_with(GENTAR_BENCH_HOST="local", **cfg_env))
            return host.preflight()

    def seen(self) -> dict[str, str]:
        lines = (self.bin / "seen-env").read_text().splitlines()
        return dict(l.split("=", 1) for l in lines if "=" in l)

    @staticmethod
    def store(base: Path, *services):
        (base / "sandboxes").mkdir(parents=True)
        (base / "sandboxes" / "stored").write_text("".join(f"(global)   {s}\n" for s in services))

    def test_a_forwarded_provider_key_is_no_refusal(self):
        self.assertEqual(self.preflight(self.env(**SYNTHETIC)), [])
        seen = self.seen()
        self.assertEqual(seen["HOME"], str(self.home))
        shell_own = {"PWD", "OLDPWD", "SHLVL", "_"}          # what sh itself exports
        self.assertLessEqual(set(seen) - shell_own, set(SBX_CHECK_ENV))
        for value in SYNTHETIC.values():
            self.assertNotIn(value, (self.bin / "seen-env").read_text())

    def test_the_stand_in_refuses_that_run_without_the_clean_environment(self):
        # what every suite of such a run met: the note, counted as a listing
        with mock.patch.dict(os.environ, self.env(**SYNTHETIC), clear=True):
            host = SbxBenchHost(cfg_with(GENTAR_BENCH_HOST="local"))
            out = host._run(["sbx", "secret", "ls"], strict=False).stdout
        self.assertIn("Note: 1 additional environment variable found", out)

    def test_a_stored_secret_is_still_refused(self):
        self.store(self.home / ".config", "example-service")
        for env in (self.env(), self.env(**SYNTHETIC)):
            with self.subTest(provider_key="ANTHROPIC_API_KEY" in env):
                problems = self.preflight(env)
                self.assertEqual(len(problems), 1)
                self.assertIn("stored sbx secrets (2 line(s)", problems[0])
                self.assertNotIn("example-service", problems[0])   # a count, not the listing

    def test_a_store_under_xdg_config_home_is_still_found(self):
        xdg = self.tmp / "xdg config"
        self.store(xdg, "example-service")
        problems = self.preflight(self.env(XDG_CONFIG_HOME=str(xdg), **SYNTHETIC))
        self.assertIn("stored sbx secrets", problems[0])
        self.assertEqual(self.seen()["XDG_CONFIG_HOME"], str(xdg))

    def test_an_unset_name_stays_unset_and_odd_values_pass_whole(self):
        odd = self.tmp / "a home with 'quotes' and $dollars"
        odd.mkdir()
        self.store(odd / ".config", "example-service")
        problems = self.preflight(self.env(HOME=str(odd)))
        self.assertIn("stored sbx secrets", problems[0])
        seen = self.seen()
        self.assertEqual(seen["HOME"], str(odd))
        self.assertNotIn("XDG_CONFIG_HOME", seen)

    def test_no_home_fails_closed(self):
        env = self.env()
        del env["HOME"]
        problems = self.preflight(env)
        self.assertIn("could not check", problems[0])

    def test_the_ssh_tier_sends_a_line_that_cleans_the_remote_environment(self):
        host = SbxBenchHost(cfg_with())
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, stdout="No secrets found.\n", stderr="")) as run:
            self.assertEqual(host.preflight(), [])
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "ssh")
        self.assertEqual(argv[-1], clean_env_line("sbx secret ls"))
        # the same line, run by each POSIX shell at hand as a login shell would
        for sh in ("/bin/sh", "/bin/dash", "/bin/bash"):
            if not Path(sh).exists():
                continue
            with self.subTest(shell=sh):
                (self.bin / "seen-env").unlink(missing_ok=True)
                r = subprocess.run([sh, "-c", argv[-1]], env=self.env(**SYNTHETIC),
                                   capture_output=True, text=True)
                self.assertEqual(r.stdout.strip().split(".")[0], "No secrets found", r.stderr)
                self.assertNotIn("ANTHROPIC_API_KEY", self.seen())


class CoordinatorRefusesOnPreflightTest(unittest.TestCase):

    def test_a_failed_preflight_is_exit_2_and_no_bench(self):
        bench = mock.Mock()
        bench.preflight.return_value = ["the bench-host has stored sbx secrets"]
        printed = []
        with mock.patch.object(coord, "make_bench", return_value=bench), \
             mock.patch.object(coord, "Spans"), \
             mock.patch("builtins.print", side_effect=printed.append):
            rc = coord.run("smoke", cfg_with())
        self.assertEqual(rc, 2)
        bench.create.assert_not_called()
        self.assertIn("stored sbx secrets", "\n".join(map(str, printed)))


if __name__ == "__main__":
    unittest.main()

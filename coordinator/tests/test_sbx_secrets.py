"""An sbx bench-host with stored secrets is refused before any bench exists.

Every sbx sandbox carries `proxy-managed` placeholders for the common
provider keys, and sbx's credential proxy swaps in a real value for any
service with a stored secret. So one `sbx secret set` on a shared host
would hand that key to every suite there, whatever credential group the
engine forwarded (claude-playbooks, measured on arena-142: placeholders
present, no secrets stored — safe by host state only). The engine now
checks, and refuses with exit 2 unless GENTAR_SBX_SECRETS=allow.
"""

import os
import subprocess
import unittest
from unittest import mock

from gentar import coordinator as coord
from gentar.benchhost import SbxBenchHost
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

    def fake_run(cmd, timeout=300, strict=True):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")
    host._run = fake_run
    return host, calls


class SbxPreflightTest(unittest.TestCase):

    def test_no_secrets_is_a_go(self):
        host, calls = host_answering(cfg_with(), "No secrets found. Run 'sbx secret set --help'\n")
        self.assertEqual(host.preflight(), [])
        self.assertEqual(calls, [["sbx", "secret", "ls"]])

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

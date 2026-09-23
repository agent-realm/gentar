"""bin/bench-reap removes the sandboxes ONE CI job created, and nothing else.

A cancelled CI job never reaches the coordinator's own `sbx rm`, so its
sandbox stayed on a bench-host shared with every other arena; teardown only
reported it. bench-reap removes by the job's GENTAR_NAME_PREFIX. The danger
is the opposite failure — reaping a live bench that belongs to another run —
so most of these tests are about what it must NOT match.

The bench-host is a fake `ssh` on PATH: it answers `sbx ls --json` from a
fixture and logs every other remote command instead of running it.

bin/ sits outside the coordinator image's build context, so inside
`docker build` these skip; they run from a checkout.
"""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REAP = Path(__file__).resolve().parents[2] / "bin" / "bench-reap"

PREFIX = "gentar-gh123-a1-arena0"
MINE = f"{PREFIX}-20260923-101010-abcdef"
NOT_MINE = [
    "gentar-gh1234-a1-arena0-20260923-101010-abcdef",   # longer run id
    "gentar-gh123-a2-arena0-20260923-101010-abcdef",    # another attempt
    "gentar-gh123-a1-arena01-20260923-101010-abcdef",   # another job index
    f"{PREFIX}-20260923-101010-abcdef-extra",           # not new_run_id's shape
    f"{PREFIX}-debug",                                  # starts with prefix only
    f"x{MINE}",                                         # prefix not at start
    "gentar-20260923-101010-abcdef",                    # a default-prefix run
]

FAKE_SSH = """#!/usr/bin/env bash
# last argument is the remote command
cmd="${@: -1}"
case "$cmd" in
  *" ls --json") [ -n "$FAIL_LS" ] && exit 255; cat "$LISTING" ;;
  *) printf '%s\\n' "$cmd" >> "$LOG" ;;
esac
"""


@unittest.skipUnless(REAP.exists(), "bin/ is not in the image build context")
class BenchReapTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        ssh = self.tmp / "ssh"
        ssh.write_text(FAKE_SSH)
        ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
        self.listing = self.tmp / "ls.json"
        self.log = self.tmp / "remote.log"
        self.log.touch()
        self.sandboxes([MINE] + NOT_MINE)

    def sandboxes(self, names):
        self.listing.write_text(json.dumps(
            {"sandboxes": [{"name": n, "status": "running"} for n in names]}))

    def reap(self, *args, **env):
        base = {"PATH": f"{self.tmp}:{os.environ['PATH']}",
                "LISTING": str(self.listing), "LOG": str(self.log),
                "GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u",
                "GENTAR_NAME_PREFIX": PREFIX}
        base.update(env)
        return subprocess.run([str(REAP), *args], env=base,
                              capture_output=True, text=True)

    def removed(self):
        return self.log.read_text().splitlines()

    def test_removes_exactly_its_own_sandbox_and_workspace(self):
        r = self.reap()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.removed(), [
            f"sbx rm {MINE} --force && rm -rf /tmp/gentar-workspaces/{MINE}"])

    def test_never_matches_a_neighbour(self):
        self.sandboxes(NOT_MINE)
        r = self.reap()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.removed(), [], "reaped a sandbox it did not create")
        self.assertIn("no sandboxes", r.stdout)

    def test_list_removes_nothing(self):
        r = self.reap("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), f"would reap: {MINE}")
        self.assertEqual(self.removed(), [])

    def test_refuses_without_a_prefix(self):
        for prefix in ("", "gentar"):
            with self.subTest(prefix=prefix):
                r = self.reap(GENTAR_NAME_PREFIX=prefix)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(self.removed(), [])

    def test_refuses_a_prefix_that_is_not_a_plain_name(self):
        # the prefix is spliced into a regex and a remote command
        for prefix in ("gentar.*", "a b", "x;rm -rf /", "-gh1"):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.reap(GENTAR_NAME_PREFIX=prefix).returncode, 2)
        self.assertEqual(self.removed(), [])

    def test_refuses_without_a_bench_host(self):
        self.assertEqual(self.reap(GENTAR_BENCH_HOST="").returncode, 2)

    def test_an_unreachable_bench_host_is_a_failure_not_a_clean_bill(self):
        r = self.reap(FAIL_LS="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.removed(), [])


if __name__ == "__main__":
    unittest.main()

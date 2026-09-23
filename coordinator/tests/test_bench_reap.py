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

PREFIX = "g1001-123-a1-arena0"          # g<repository_id>-<run_id>-a<attempt>-<job><index>
MINE = f"{PREFIX}-20260923-101010-abcdef"
NOT_MINE = [
    "g10011-123-a1-arena0-20260923-101010-abcdef",      # another repository
    "g1001-1234-a1-arena0-20260923-101010-abcdef",      # longer run id
    "g1001-123-a2-arena0-20260923-101010-abcdef",       # another attempt
    "g1001-123-a1-arena01-20260923-101010-abcdef",      # another job index
    f"{PREFIX}-20260923-101010-abcdef-extra",           # not new_run_id's shape
    f"{PREFIX}-debug",                                  # starts with prefix only
    f"x{MINE}",                                         # prefix not at start
    "gentar-20260923-101010-abcdef",                    # a default-prefix run
]

# `docker compose config --format json`: answers from $COMPOSE_JSON when a
# test sets it, otherwise fails like a host without compose.
FAKE_DOCKER = """#!/usr/bin/env bash
[ -n "$COMPOSE_JSON" ] || exit 1
cat "$COMPOSE_JSON"
"""


def compose_config(env, key_file=None):
    """The pretty-printed shape `docker compose config --format json` emits."""
    doc = {"services": {"coordinator": {"environment": env}}}
    if key_file:
        doc["secrets"] = {"bench_ssh_key": {"name": "x", "file": key_file}}
    return json.dumps(doc, indent=2)


FAKE_SSH = """#!/usr/bin/env bash
# last argument is the remote command
cmd="${@: -1}"
case "$cmd" in
  *" ls --json") [ -n "$FAIL_LS" ] && exit 255; cat "$LISTING" ;;
  "ls -1 "*) cat "$WORKSPACES" ;;
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
        docker = self.tmp / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        self.compose = self.tmp / "compose.json"   # absent unless a test writes it
        self.listing = self.tmp / "ls.json"
        self.workspaces = self.tmp / "ws.txt"
        self.workspaces.write_text("")
        self.log = self.tmp / "remote.log"
        self.log.touch()
        self.sandboxes([MINE] + NOT_MINE)

    def sandboxes(self, names):
        self.listing.write_text(json.dumps(
            {"sandboxes": [{"name": n, "status": "running"} for n in names]}))

    def reap(self, *args, **env):
        base = {"PATH": f"{self.tmp}:{os.environ['PATH']}",
                "LISTING": str(self.listing), "LOG": str(self.log),
                "WORKSPACES": str(self.workspaces),
                "COMPOSE_JSON": "",
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
        self.assertEqual(r.stdout.strip(), f"would reap sandbox: {MINE}")
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

    def test_refuses_a_prefix_no_sandbox_could_carry(self):
        # sbx caps names at 64 and the run id appends 23
        self.assertEqual(self.reap(GENTAR_NAME_PREFIX="p" * 42).returncode, 2)
        self.assertEqual(self.reap("--list", GENTAR_NAME_PREFIX="p" * 41).returncode, 0)

    def test_reaps_a_workspace_whose_sandbox_was_never_created(self):
        # sbx pushes the workspace BEFORE `sbx create`; a job cancelled in
        # between leaves a workspace and no sandbox. Neighbours' stay.
        orphan = f"{PREFIX}-20260923-111111-0a0b0c"
        self.sandboxes([])
        self.workspaces.write_text("\n".join([orphan] + NOT_MINE) + "\n")
        r = self.reap()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.removed(), [f"rm -rf /tmp/gentar-workspaces/{orphan}"])

    def test_bench_settings_are_what_compose_resolved_for_the_coordinator(self):
        # compose applies the arena's .env, interpolation, comments and
        # relative paths; the reaper must reach the host the run reached
        self.compose.write_text(compose_config({
            "GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u",
            "GENTAR_BENCH_WORKSPACE_ROOT": "/srv/ws"}))
        r = self.reap(COMPOSE_JSON=str(self.compose),
                      GENTAR_BENCH_HOST="", GENTAR_BENCH_USER="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.removed(), [
            f"sbx rm {MINE} --force && rm -rf /srv/ws/{MINE}"])

    def test_compose_wins_over_the_shell(self):
        # an env_file-only value reaches the coordinator whatever the shell
        # holds, so that is the value the sandbox was created with
        self.compose.write_text(compose_config({
            "GENTAR_BENCH_WORKSPACE_ROOT": "/srv/ws"}))
        r = self.reap(COMPOSE_JSON=str(self.compose),
                      GENTAR_BENCH_WORKSPACE_ROOT="/tmp/other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.removed(), [
            f"sbx rm {MINE} --force && rm -rf /srv/ws/{MINE}"])

    def test_without_compose_the_shell_is_used(self):
        r = self.reap(GENTAR_BENCH_WORKSPACE_ROOT="/tmp/other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.removed(), [
            f"sbx rm {MINE} --force && rm -rf /tmp/other/{MINE}"])

    def test_the_key_is_the_secret_path_compose_resolved(self):
        self.compose.write_text(compose_config(
            {"GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u"},
            key_file="/abs/keys/bench_key"))
        spy = self.tmp / "ssh"
        spy.write_text(FAKE_SSH.replace('cmd="${@: -1}"',
                                        'cmd="${@: -1}"; printf "%s\\n" "$*" >> "$LOG.argv"'))
        r = self.reap(COMPOSE_JSON=str(self.compose), GENTAR_BENCH_KEY_FILE="/wrong")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = (self.tmp / "remote.log.argv").read_text()
        self.assertIn("-i /abs/keys/bench_key", argv)
        self.assertNotIn("/wrong", argv)

    def test_an_unreachable_bench_host_is_a_failure_not_a_clean_bill(self):
        r = self.reap(FAIL_LS="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.removed(), [])


if __name__ == "__main__":
    unittest.main()

"""bin/bench-host-provision: refusals happen before any change.

2026-10-11 (the move to a new bench host; adopted from the operator's build
script): the script provisions an isolated bench account with rootless
Docker. Anything it will not do is refused (exit 2) before the first sudo,
and the account it builds never joins a privileged group. Its proofs and its
real run are on the host; here, the refusals and the invariants.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "bench-host-provision"


@unittest.skipUnless(SCRIPT.exists(), "bin/ is not in the image build context")
class BenchHostProvisionTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls"
        for name in ("sudo", "apt-get", "curl", "useradd", "systemctl"):
            (self.bin / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.calls}"\nexit 1\n')
            (self.bin / name).chmod(0o755)
        self.noble = self.tmp / "os-release-noble"
        self.noble.write_text('NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n')

    def run_script(self, os_release=None, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("GENTAR_", "SBX_"))}
        e.update(PATH=f"{self.bin}:{os.environ['PATH']}",
                 GENTAR_OS_RELEASE=str(os_release or self.noble), **env)
        return subprocess.run(["/bin/bash", str(SCRIPT)], env=e, capture_output=True, text=True,
                              timeout=60)

    def assert_refused_untouched(self, r, words):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(words, r.stderr)
        self.assertFalse(self.calls.exists(), self.calls.read_text() if self.calls.exists() else "")

    def test_anything_but_ubuntu_24_04_is_refused_first(self):
        for text in ('ID=debian\nVERSION_ID="13"\n', 'ID=ubuntu\nVERSION_ID="22.04"\n', ""):
            with self.subTest(os=text):
                f = self.tmp / "os-release"
                f.write_text(text)
                self.assert_refused_untouched(self.run_script(f), "Ubuntu 24.04 only")

    def test_os_release_is_read_not_sourced(self):
        f = self.tmp / "os-release-evil"
        marker = self.tmp / "sourced"
        f.write_text(f'ID=ubuntu\nVERSION_ID="24.04"\ntouch {marker}\n')
        self.run_script(f, GENTAR_BENCH_UID="x")          # refused on the uid, after reading
        self.assertFalse(marker.exists())

    def test_bad_parameters_are_refused_first(self):
        for env, words in (({"GENTAR_BENCH_ACCOUNT": "arena;id"}, "bad GENTAR_BENCH_ACCOUNT"),
                           ({"GENTAR_BENCH_ACCOUNT": "1arena"}, "bad GENTAR_BENCH_ACCOUNT"),
                           ({"GENTAR_BENCH_UID": "10a1"}, "bad GENTAR_BENCH_UID"),
                           ({"GENTAR_BENCH_WORKSPACE_ROOT": "tmp/ws"}, "must be an absolute path"),
                           ({"GENTAR_BENCH_WORKSPACE_ROOT": "/tmp/w s"}, "bad GENTAR_BENCH_WORKSPACE_ROOT"),
                           ({"GENTAR_DOCKER_POOL": "10.0.0.0/16; rm"}, "bad GENTAR_DOCKER_POOL"),
                           ({"SBX_VERSION": "0.39$(id)"}, "bad SBX_VERSION")):
            with self.subTest(**env):
                self.assert_refused_untouched(self.run_script(**env), words)

    def test_it_is_never_run_as_the_bench_account(self):
        me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", me):
            self.skipTest("this user's name is not a valid account name for the check")
        self.assert_refused_untouched(self.run_script(GENTAR_BENCH_ACCOUNT=me), "not as " + me)

    def test_the_account_joins_no_privileged_group(self):
        text = SCRIPT.read_text()
        adds = [l for l in text.splitlines() if "useradd" in l and not l.lstrip().startswith("#")]
        self.assertEqual(len(adds), 1)
        self.assertIn("-G kvm ", adds[0])
        for group in ("docker", "sudo", "adm", "lxd", "wheel"):
            self.assertNotRegex(adds[0], rf"-G[^-]*\b{group}\b")
        self.assertNotRegex(text, r"usermod\s+-a?G")

    def test_no_secret_value_and_the_keyring_password_is_never_shown(self):
        text = SCRIPT.read_text()
        for pattern in (r"ghp_[A-Za-z0-9]", r"github_pat_", r"dckr_pat_", r"\bsk-[A-Za-z0-9]{8}",
                        r"BEGIN [A-Z ]*PRIVATE KEY"):
            self.assertNotRegex(text, pattern)
        code = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
        shown = [l for l in code if ".keyring-pass" in l and re.search(r"\b(cat|echo|printf|head|tail|less)\b", l)
                 and "< $HOME/.keyring-pass" not in l and "> ~/.keyring-pass" not in l]
        self.assertEqual(shown, [])


if __name__ == "__main__":
    unittest.main()

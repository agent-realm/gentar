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
        # Every parameter valid, so the script reaches the file, reads it, and
        # refuses on the OS -- without ever executing the line in it.
        f = self.tmp / "os-release-evil"
        marker = self.tmp / "sourced"
        f.write_text(f'ID=ubuntu\nVERSION_ID="22.04"\ntouch {marker}\n')
        self.assert_refused_untouched(self.run_script(f), "Ubuntu 24.04 only")
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

    def test_the_workspace_root_must_be_a_dedicated_directory(self):
        # systemd-tmpfiles' `d` line re-owns an existing directory: /tmp or
        # /etc here would be handed to the bench account.
        for root, words in (("/tmp", "two levels deep at least"), ("/etc", "two levels deep at least"),
                            ("/", "two levels deep at least"), ("/tmp/", "two levels deep at least"),
                            ("/tmp/../etc", "must not contain . or .."),
                            ("/tmp/./gentar", "must not contain . or ..")):
            with self.subTest(root=root):
                self.assert_refused_untouched(self.run_script(GENTAR_BENCH_WORKSPACE_ROOT=root), words)

    def test_an_existing_root_must_already_be_the_accounts(self):
        mine = self.tmp / "taken" / "ws"
        mine.mkdir(parents=True)
        self.assert_refused_untouched(
            self.run_script(GENTAR_BENCH_WORKSPACE_ROOT=str(mine), GENTAR_BENCH_ACCOUNT="gentarbenchx"),
            "not gentarbenchx")
        link = self.tmp / "taken" / "link"
        link.symlink_to(mine)
        self.assert_refused_untouched(
            self.run_script(GENTAR_BENCH_WORKSPACE_ROOT=str(link)), "is a symlink")
        # owned by the account (a re-run): the root check passes, and the
        # next refusal is the one about the account itself
        me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        if re.fullmatch(r"[a-z][a-z0-9_-]*", me):
            r = self.run_script(GENTAR_BENCH_WORKSPACE_ROOT=str(mine), GENTAR_BENCH_ACCOUNT=me)
            self.assert_refused_untouched(r, "not as " + me)

    def proof(self, *cmd_and_want):
        """Run the script's own p() with a sudo that just runs the command."""
        text = SCRIPT.read_text()
        func = text[text.index("# --- proofs"):text.index("# --- end proofs")]
        (self.bin / "sudo").write_text('#!/bin/sh\nshift 3\nexec "$@"\n')     # drop `-u ACCOUNT -H`
        label, want, *cmd = cmd_and_want
        script = func + '\nACCOUNT=arena\np "$@"\necho "fails=$fails"\n'
        e = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        r = subprocess.run(["/bin/bash", "-c", script, "proof", label, want, *cmd], env=e,
                           capture_output=True, text=True)
        return r.stdout

    def test_a_proof_counts_only_the_expected_refusal(self):
        out = self.proof("allowed", "permission denied", "true")
        self.assertIn("FAIL (allowed): allowed", out)
        self.assertIn("fails=1", out)
        out = self.proof("refused", "permission denied", "sh", "-c", "echo 'x: Permission denied' >&2; exit 1")
        self.assertIn("REFUSED: refused", out)
        self.assertIn("fails=0", out)
        out = self.proof("absent", "permission denied", "ls", str(self.tmp / "no-such-dir"))
        self.assertIn("INCONCLUSIVE: absent failed for another reason", out)
        self.assertIn("fails=1", out)

    def test_a_failed_proof_fails_the_run(self):
        text = SCRIPT.read_text()
        tail = text[text.index("# --- end proofs"):]
        self.assertIn('if [ "$fails" -gt 0 ]; then', tail)
        self.assertIn("exit 1", tail[tail.index('if [ "$fails" -gt 0 ]; then'):])
        self.assertIn("1 a proof failed", text)

    def test_the_docker_key_is_checked_before_it_is_trusted(self):
        text = SCRIPT.read_text()
        self.assertIn("DOCKER_KEY_FPR=9DC858229FC7DD38854AE2D88D81803C0EBFCD88", text)
        check = text.index('[ "$fpr" = "$DOCKER_KEY_FPR" ] || refuse')
        self.assertLess(check, text.index("/etc/apt/keyrings/docker.asc"))
        self.assertNotIn("| sudo tee /etc/apt/keyrings/docker.asc", text)

    def test_the_rootful_daemon_is_masked(self):
        self.assertIn("sudo systemctl mask docker.service docker.socket", SCRIPT.read_text())

    def fake_account(self, uid=None, groups="", uid_owner=""):
        """`id` and `getent` stubs: account gentarbenchx exists with uid/groups."""
        (self.bin / "id").write_text(f"""#!/bin/sh
case "$*" in
  "-un"|"-u") exec /usr/bin/id "$@" ;;
  "gentarbenchx") [ -n "{uid or ''}" ] || exit 1; echo "uid={uid}" ;;
  "-u gentarbenchx") [ -n "{uid or ''}" ] || exit 1; echo "{uid}" ;;
  "-nG gentarbenchx") echo "{groups}" ;;
  *) exec /usr/bin/id "$@" ;;
esac
""")
        (self.bin / "getent").write_text(f"""#!/bin/sh
[ -n "{uid_owner}" ] && [ "$1" = passwd ] && [ "$2" = 1001 ] && echo "{uid_owner}:x:1001:1001::/home/{uid_owner}:/bin/sh" && exit 0
exit 2
""")
        for f in ("id", "getent"):
            (self.bin / f).chmod(0o755)

    def test_an_existing_account_with_another_uid_is_refused_first(self):
        self.fake_account(uid="1002", groups="gentarbenchx kvm")
        self.assert_refused_untouched(self.run_script(GENTAR_BENCH_ACCOUNT="gentarbenchx"),
                                      "gentarbenchx exists with uid 1002, not 1001")

    def test_an_existing_account_in_any_other_group_is_refused_first(self):
        # An allow list: own group + kvm only. disk (raw block devices) is
        # root; an arbitrary group is refused too.
        for g in ("docker", "sudo", "adm", "lxd", "wheel", "disk", "shadow", "foo"):
            with self.subTest(group=g):
                self.fake_account(uid="1001", groups=f"gentarbenchx kvm {g}")
                r = self.run_script(GENTAR_BENCH_ACCOUNT="gentarbenchx")
                self.assert_refused_untouched(r, "other groups than its own and kvm: " + g)

    def test_an_existing_account_with_the_layouts_groups_passes_the_preflight(self):
        self.fake_account(uid="1001", groups="gentarbenchx kvm")
        r = self.run_script(GENTAR_BENCH_ACCOUNT="gentarbenchx")
        # past every refusal: the first change (a stubbed, failing sudo) is reached
        self.assertNotEqual(r.returncode, 2, r.stderr)
        self.assertTrue(self.calls.exists())
        self.assertNotIn("other groups", r.stderr)

    def test_a_uid_held_by_another_account_is_refused_first(self):
        self.fake_account(uid=None, uid_owner="someoneelse")
        self.assert_refused_untouched(self.run_script(GENTAR_BENCH_ACCOUNT="gentarbenchx"),
                                      "uid 1001 is taken by someoneelse")

    def test_a_held_sbx_is_released_before_the_versioned_install(self):
        text = SCRIPT.read_text()
        unhold = text.index("sudo apt-mark unhold docker-sbx")
        install = text.index('"docker-sbx=${SBX_VERSION}"')
        hold = text.index("sudo apt-mark hold docker-sbx")
        self.assertLess(unhold, install)
        self.assertLess(install, hold)

    def test_it_is_never_run_as_the_bench_account(self):
        me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", me):
            self.skipTest("this user's name is not a valid account name for the check")
        self.assert_refused_untouched(self.run_script(GENTAR_BENCH_ACCOUNT=me), "not as " + me)

    def test_the_final_proof_uses_the_same_allow_list(self):
        text = SCRIPT.read_text()
        tail = text[text.index("# --- end proofs"):]
        self.assertIn("extra=$(extra_groups)", tail)
        self.assertIn('FAIL (groups other than $ACCOUNT and kvm)', tail)

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

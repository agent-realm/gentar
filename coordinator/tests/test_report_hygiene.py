"""After v0.10.0: the report directory is never opened to everyone (D4), and
the documented default bench account is not scrubbed (the redacted subject).

D4 (ground-up review, 2026-10-19): every report write ran
`chmod 0777` on the report dir, a host bind, so any account on the host could
plant or delete reports. It existed so the host user could clean what root
wrote; reports now go to the dir's owner on the open descriptor, and a dir
root had to create itself goes to the owner of the dir it sits in.

The redacted subject (gate on #80's merge, 2026-10-22): v0.10.0 scrubs the
whole report and every exported span with the bench identity, and the
default bench account `arena` is also the default subject, so every report
and span read «redacted:GENTAR_BENCH_USER» for a name the docs publish.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar.config import Config
from gentar.redaction import scrubber
from gentar.report import RunReport
from gentar.spans import Redactor


def fake_stat(uids):
    """os.stat with st_uid replaced for the given paths."""
    real = os.stat

    def _stat(p, *a, **k):
        st = real(p, *a, **k)
        uid = uids.get(os.fspath(p))
        if uid is None:
            return st
        fields = list(st[:10])
        fields[4] = uid
        return os.stat_result(fields)
    return _stat


class ReportDirModeTest(unittest.TestCase):

    def test_an_existing_dir_keeps_its_mode(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir(mode=0o750)
            os.chmod(out, 0o750)
            RunReport(scenario="s", run_id="r1").write(out)
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o750)

    def test_a_new_dir_is_not_world_writable(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "new" / "out"
            RunReport(scenario="s", run_id="r1").write(out)
            self.assertFalse(stat.S_IMODE(out.stat().st_mode) & 0o002)
            self.assertEqual(stat.S_IMODE((out / "report-r1.md").stat().st_mode), 0o600)


class RootOwnershipTest(unittest.TestCase):
    """As root in a container: who gets the dir and the report."""

    def write_as_root(self, out, uids):
        calls = []

        def fchown(fd, uid, gid):
            # a chown of the dir itself changes what a later stat sees
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                uids[str(out)] = uid
            calls.append(uid)
        with mock.patch("os.geteuid", return_value=0), \
             mock.patch("os.stat", side_effect=fake_stat(uids)), \
             mock.patch("os.fchown", side_effect=fchown):
            RunReport(scenario="s", run_id="r1").write(out)
        return calls

    def test_a_dir_root_created_goes_to_its_parents_owner_and_so_does_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            calls = self.write_as_root(out, {str(out): 0, d: 4242})
            self.assertEqual(calls, [4242, 4242])        # the dir, then the report

    def test_an_existing_root_dir_is_left_to_root(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            self.assertEqual(self.write_as_root(out, {str(out): 0, d: 4242}), [])

    def test_a_users_dir_gets_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            self.assertEqual(self.write_as_root(out, {str(out): 4242}), [4242])

    def test_a_symlinked_new_dir_is_not_followed(self):
        # created as a symlink between the check and the chown: O_NOFOLLOW
        # refuses it, and nothing is handed over
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as elsewhere:
            out = Path(d) / "out"
            real_mkdir = Path.mkdir

            def mkdir_as_symlink(self, *a, **k):
                if self == out:
                    os.symlink(elsewhere, out)
                    return
                return real_mkdir(self, *a, **k)
            with mock.patch.object(Path, "mkdir", mkdir_as_symlink):
                calls = self.write_as_root(out, {str(out): 0, d: 4242})
            self.assertNotIn(4242, calls)


class DefaultBenchAccountTest(unittest.TestCase):

    def cfg(self, user):
        env = {"GENTAR_BENCH_HOST": "bench.example.org", "GENTAR_BENCH_USER": user,
               "GENTAR_REPORT_DIR": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            return Config()

    def test_the_default_account_is_not_scrubbed(self):
        scrub = Redactor(self.cfg("arena")).scrub
        self.assertEqual(scrub("| subject | `arena` |"), "| subject | `arena` |")
        # the host is still scrubbed, with the account next to it
        self.assertEqual(scrub("ssh arena@bench.example.org"), "ssh arena@«redacted:GENTAR_BENCH_HOST»")

    def test_any_other_account_still_is(self):
        scrub = Redactor(self.cfg("ci-runner")).scrub
        self.assertEqual(scrub("ssh ci-runner@host"), "ssh «redacted:GENTAR_BENCH_USER»@host")

    def test_only_that_pairing_is_exempt(self):
        # "arena" as another setting's value, or another default, is not
        scrub = scrubber([("GENTAR_TART_USER", "arena")])
        self.assertEqual(scrub("user arena"), "user «redacted:GENTAR_TART_USER»")

    def test_a_report_keeps_its_subject(self):
        report = RunReport(scenario="s", run_id="r1", subject="arena")
        report.scrub = Redactor(self.cfg("arena")).scrub
        with tempfile.TemporaryDirectory() as d:
            text = report.write(d).read_text()
        self.assertIn("| subject | `arena` |", text)


if __name__ == "__main__":
    unittest.main()

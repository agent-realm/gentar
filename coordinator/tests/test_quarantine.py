"""A quarantined suite did not run, and is never a pass (ground-up review A4).

Quarantine keeps a known flake from turning a sweep red, so it exits 0. It
used to write no report: a direct caller saw a silent 0 with nothing to
read, and the kit, for which every terminal outcome writes a report, read
the missing report as broken reporting and failed the suite (rc 1). The
same suite now gets the same outcome both ways: exit 0, a report and a
span that say skip, and a kit summary line naming it as not run.
"""

import contextlib
import io
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gentar import coordinator
from gentar.config import Config
from gentar.report import RunReport

KIT_RUN = Path(__file__).resolve().parents[2] / "subject-template" / "gentar" / "run.sh"


def cfg_with(**env):
    base = {"GENTAR_BENCH_HOST": "bench.internal.example", "GENTAR_BENCH_USER": "benchuser",
            "GENTAR_REPORT_DIR": ""}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config()


class QuarantinedRunTest(unittest.TestCase):

    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.cfg = cfg_with(GENTAR_QUARANTINE="flaky", GENTAR_REPORT_DIR=str(self.out))

    def run_flaky(self):
        printed = io.StringIO()
        with mock.patch("gentar.spans.clickhouse_connect.get_client",
                        side_effect=Exception("no clickhouse")), \
                mock.patch.object(coordinator.Spans, "emit", autospec=True) as emit, \
                contextlib.redirect_stdout(printed):
            rc = coordinator.run("flaky", self.cfg)
        return rc, printed.getvalue(), emit

    def test_a_direct_run_exits_0_and_writes_one_skip_report(self):
        rc, _, _ = self.run_flaky()
        self.assertEqual(rc, 0)
        reports = list(self.out.glob("report-*.md"))
        self.assertEqual(len(reports), 1, reports)
        text = reports[0].read_text()
        self.assertEqual(text.splitlines()[0], "# gentar report — flaky: SKIP")
        self.assertIn("| verdict | `skip (exit 0)` |", text)
        self.assertIn("not run", text)
        self.assertNotIn("PASS", text)

    def test_what_it_prints_says_quarantined_never_pass(self):
        _, printed, _ = self.run_flaky()
        self.assertIn("QUARANTINED [flaky]: not run", printed)
        self.assertNotIn("PASS", printed)

    def test_the_span_says_skip_and_shares_the_reports_run_id(self):
        _, _, emit = self.run_flaky()
        self.assertEqual(emit.call_count, 1)
        _, subject, run_id, scenario, step, status = emit.call_args.args[:6]
        self.assertEqual((scenario, step, status), ("flaky", "run", "skip"))
        self.assertEqual(emit.call_args.kwargs["attrs"], {"quarantined": "true"})
        self.assertTrue((self.out / f"report-{run_id}.md").exists(), list(self.out.iterdir()))


@unittest.skipUnless(KIT_RUN.exists(), "the kit is not in the image build context")
class KitReadsTheSkipTest(unittest.TestCase):
    """The kit reads a report's verdict row, the engine's own format."""

    def report_verdict(self, path):
        fn = re.search(r"^report_verdict\(\) \{\n.*?^\}\n", KIT_RUN.read_text(), re.S | re.M)
        self.assertIsNotNone(fn, "run.sh has no report_verdict function")
        r = subprocess.run(["/bin/bash", "-c", fn.group(0) + 'report_verdict "$1"', "_", str(path)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_every_verdict_the_engine_writes_is_read_back(self):
        # the summary repeats a verdict row: the table's own row comes first
        d = Path(tempfile.mkdtemp())
        for verdict, code in (("pass", 0), ("fail", 1), ("refuse", 2), ("skip", 0)):
            with self.subTest(verdict=verdict):
                report = RunReport(scenario="s", run_id=f"r-{verdict}",
                                   summary="| verdict | `pass (exit 0)` |")
                report.mark(verdict, code)
                self.assertEqual(self.report_verdict(report.write(d)), verdict)

    def test_a_quarantined_suite_is_named_as_not_run_and_never_fails_the_run(self):
        run = KIT_RUN.read_text()
        self.assertIn('[ "$(report_verdict "$f")" = skip ] && skipped=1', run)
        self.assertIn('elif [ "$skipped" = 1 ] && [ "$rc" -eq 0 ]; then\n'
                      '    quarantined="$quarantined $s"', run)
        self.assertIn("suite(s) quarantined, not run:", run)
        self.assertIn("::warning title=quarantined suites not run::", run)


if __name__ == "__main__":
    unittest.main()

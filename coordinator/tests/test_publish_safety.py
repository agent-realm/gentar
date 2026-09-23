"""What a run publishes is safe on a PUBLIC repository.

A public repo's CI artifacts are downloadable by any logged-in GitHub user,
and GitHub masks secrets in logs, not in artifacts. bin/redact replaces the
values of the bench-host identity and of every declared credential in a
run's reports and dashboard; the dashboard shows an agent transcript only
by its length (claude-playbooks' acceptance for the per-run dashboard).
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REDACT = ROOT / "bin" / "redact"
GENERATE = ROOT / "dashboard" / "generate.py"


@unittest.skipUnless(REDACT.exists(), "bin/ is not in the image build context")
class RedactTest(unittest.TestCase):

    def run_redact(self, text, **env):
        f = Path(tempfile.mkdtemp()) / "report.md"
        f.write_text(text)
        e = {"PATH": os.environ["PATH"], **env}
        r = subprocess.run([sys.executable, str(REDACT), str(f)], env=e,
                           capture_output=True, text=True)
        return r, f.read_text()

    def test_named_values_are_replaced_by_their_name(self):
        r, out = self.run_redact(
            "ssh: connect to host 10.10.10.52 port 22 as polat\nkey sk-abc123xyz\n",
            GENTAR_REDACT_NAMES="GENTAR_BENCH_HOST GENTAR_BENCH_USER ANTHROPIC_AUTH_TOKEN",
            GENTAR_BENCH_HOST="10.10.10.52", GENTAR_BENCH_USER="polat",
            ANTHROPIC_AUTH_TOKEN="sk-abc123xyz")
        self.assertEqual(r.returncode, 0, r.stderr)
        for secret in ("10.10.10.52", "polat", "sk-abc123xyz"):
            self.assertNotIn(secret, out)
        self.assertIn("«redacted:GENTAR_BENCH_HOST»", out)
        self.assertIn("«redacted:ANTHROPIC_AUTH_TOKEN»", out)

    def test_a_value_containing_another_is_replaced_whole(self):
        _, out = self.run_redact("token=abcd-efgh",
                                 GENTAR_REDACT_NAMES="SHORT LONG",
                                 SHORT="abcd", LONG="abcd-efgh")
        self.assertEqual(out, "token=«redacted:LONG»")

    def test_unset_and_tiny_values_are_left_alone(self):
        _, out = self.run_redact("user u on host", GENTAR_REDACT_NAMES="A B",
                                 A="u")
        self.assertEqual(out, "user u on host")

    def test_no_files_is_a_usage_error(self):
        r = subprocess.run([sys.executable, str(REDACT)], capture_output=True)
        self.assertEqual(r.returncode, 2)


@unittest.skipUnless(GENERATE.exists(), "dashboard/ is not in the image build context")
class DashboardHidesTranscriptsTest(unittest.TestCase):

    def test_an_agent_transcript_is_shown_only_by_its_length(self):
        spec = importlib.util.spec_from_file_location("gen", GENERATE)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        events = [
            {"subject": "s", "run_id": "r", "scenario": "a", "step": "driver.transcript",
             "status": "ok", "ts_start": "", "ts_end": "", "duration_ms": 1,
             "detail": "SECRET SCREEN CONTENT the agent typed", "span_id": "1"},
            {"subject": "s", "run_id": "r", "scenario": "a", "step": "step.0",
             "status": "ok", "ts_start": "", "ts_end": "", "duration_ms": 1,
             "detail": "$ echo hi\nhi", "span_id": "2"},
        ]
        html = gen.render([{"subject": "s", "run_id": "r", "started": "", "last_event": "",
                            "scenarios": 1, "n_pass": 1, "n_fail": 0, "n_running": 0,
                            "n_skip": 0, "n_error": 0}],
                          [], gen.public_events(events), [], "gentar", False)
        self.assertNotIn("SECRET SCREEN CONTENT", html)
        self.assertIn("agent transcript, 37 chars", html)
        self.assertIn("echo hi", html)          # command output stays, as in the report


if __name__ == "__main__":
    unittest.main()

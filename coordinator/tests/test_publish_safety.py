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
        e = {"PATH": os.environ["PATH"], "GENTAR_ENGINE_DIR": tempfile.mkdtemp(), **env}
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

    def test_every_encoding_of_a_value_is_redacted(self):
        # the dashboard embeds data as JSON; a value with a backslash, a
        # quote, a newline or non-ASCII text appears escaped (agy review)
        import html as _html, json as _json
        v = 'k\\ey"with\nodd\u00e9-chars'
        text = "\n".join([v, _json.dumps(v)[1:-1], _json.dumps(v, ensure_ascii=False)[1:-1],
                          _html.escape(v), _html.escape(_json.dumps(v)[1:-1])])
        r, out = self.run_redact(text, GENTAR_REDACT_NAMES="TOKEN", TOKEN=v)
        self.assertEqual(r.returncode, 0, r.stderr)
        for form in (v, _json.dumps(v)[1:-1], _json.dumps(v, ensure_ascii=False)[1:-1],
                     _html.escape(v)):
            self.assertNotIn(form, out)
        self.assertEqual(out.count("«redacted:TOKEN»"), 5, out)

    def test_a_truncated_value_loses_its_surviving_head(self):
        # a report's command column cuts a value; the head must not survive
        # (claude-playbooks, scanning its public artifacts)
        v = "sk-ant-api03-ABCDEFGHIJKLMNOP"
        r, out = self.run_redact("| `ANTHROPIC_AUTH_TOKEN=sk-ant-api03-ABC` |",
                                 GENTAR_REDACT_NAMES="ANTHROPIC_AUTH_TOKEN",
                                 ANTHROPIC_AUTH_TOKEN=v)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("sk-ant-api03-ABC", out)
        self.assertIn("«redacted:ANTHROPIC_AUTH_TOKEN»`", out)

    def test_a_value_containing_another_is_replaced_whole(self):
        _, out = self.run_redact("token=abcd-efgh",
                                 GENTAR_REDACT_NAMES="SHORT LONG",
                                 SHORT="abcd", LONG="abcd-efgh")
        self.assertEqual(out, "token=«redacted:LONG»")

    def test_unset_and_tiny_values_are_left_alone(self):
        _, out = self.run_redact("user u on host", GENTAR_REDACT_NAMES="A B",
                                 A="u")
        self.assertEqual(out, "user u on host")

    def test_a_value_only_compose_resolved_is_redacted_too(self):
        # the bench-host set only in the arena's .env reaches the run via
        # compose, never this process's environment (agy review)
        import json, stat
        bindir = Path(tempfile.mkdtemp())
        doc = {"services": {"coordinator": {"environment": {
            "GENTAR_BENCH_HOST": "bench.internal.example"}}}}
        (bindir / "docker").write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(doc) + "\nJ\n")
        (bindir / "docker").chmod(0o755)
        r, out = self.run_redact(
            "ssh: Could not resolve hostname bench.internal.example",
            GENTAR_REDACT_NAMES="GENTAR_BENCH_HOST",
            PATH=f"{bindir}:{os.environ['PATH']}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("bench.internal.example", out)
        self.assertIn("«redacted:GENTAR_BENCH_HOST»", out)

    def test_without_compose_an_unknown_name_refuses(self):
        # compose could not say, and a named variable is not in the env:
        # it may hold a value the run used (set only in .env) — refuse
        r, out = self.run_redact("host h1.example", GENTAR_REDACT_NAMES="GENTAR_BENCH_HOST",
                                 PATH="/usr/bin:/bin")          # no docker here
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(out, "host h1.example")               # untouched, not "clean"

    def test_without_compose_names_all_in_the_env_still_redact(self):
        r, out = self.run_redact("host h1.example", GENTAR_REDACT_NAMES="GENTAR_BENCH_HOST",
                                 GENTAR_BENCH_HOST="h1.example", PATH="/usr/bin:/bin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, "host «redacted:GENTAR_BENCH_HOST»")

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


    def test_only_this_invocations_runs_are_fetched(self):
        # a kept arena still holds earlier runs, whose credentials the
        # publisher cannot redact (agy review)
        spec = importlib.util.spec_from_file_location("gen", GENERATE)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        seen = []
        gen.ch_query = lambda url, user, pw, sql: seen.append(sql) or []
        gen.fetch("http://x", "u", "p", "gentar", 500, since=1700000000)
        self.assertIn("toUnixTimestamp(run_started) >= 1700000000", seen[0])

    def test_the_grid_hides_a_transcript_that_was_the_last_step(self):
        spec = importlib.util.spec_from_file_location("gen", GENERATE)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        grid = [{"subject": "s", "run_id": "r", "scenario": "a", "status": "fail",
                 "current_step": "driver.transcript", "last_duration_ms": 1,
                 "last_detail": "SECRET SCREEN CONTENT", "run_started": "", "last_event": ""}]
        html = gen.render([], gen.public_grid(grid), [], [], "gentar", False)
        self.assertNotIn("SECRET SCREEN CONTENT", html)
        self.assertIn("agent transcript, 21 chars", html)


if __name__ == "__main__":
    unittest.main()

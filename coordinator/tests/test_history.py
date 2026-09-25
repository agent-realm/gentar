"""What reaches the shared history store: redacted rows, no transcript text.

The history ClickHouse is shared by every arena and read by dashboards, so a
row is scrubbed before it leaves the coordinator — the bench-host settings
and the run's declared credentials, in every encoding and any 8+ char
prefix — and a driver transcript keeps only its length. Off without a URL;
a failed write never raises.
"""

import json
import os
import unittest
from unittest import mock

from gentar import coordinator as coord
from gentar.config import Config
from gentar.report import RunReport
from gentar.spans import CI_COLUMNS, COLUMNS, Spans

TOKEN = "tok-9f8e7d6c5b4a-secret"


def cfg_with(**env):
    base = {"GENTAR_BENCH_HOST": "bench.internal.example", "GENTAR_BENCH_USER": "benchuser",
            "GENTAR_HISTORY_URL": "http://history:8123", "GENTAR_HISTORY_PASSWORD": "w-pass-1234",
            "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42", "GENTAR_REPORT_DIR": ""}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config()


class FakeClient:
    def __init__(self):
        self.rows = []

    def insert(self, table, rows, column_names):
        self.rows += [dict(zip(column_names, r), _table=table) for r in rows]


def spans_with_history(cfg):
    fake = FakeClient()
    with mock.patch("gentar.spans.clickhouse_connect.get_client",
                    side_effect=[fake, Exception("no arena clickhouse")]):
        s = Spans(cfg)
    return s, fake


class HistoryWriteTest(unittest.TestCase):

    def test_rows_are_scrubbed_and_carry_ci_identity(self):
        s, fake = spans_with_history(cfg_with())
        s.history.redact_values([("ANTHROPIC_AUTH_TOKEN", TOKEN)])
        s.emit("sub", "run1", "suite", "step.0", "fail",
               attrs={"cmd": f"curl -H 'x: {TOKEN}'"},
               detail=f"ssh benchuser@bench.internal.example: {TOKEN[:14]}")
        (row,) = fake.rows
        blob = json.dumps(row, default=str)
        for secret in (TOKEN, TOKEN[:14], "bench.internal.example", "benchuser"):
            self.assertNotIn(secret, blob)
        self.assertIn("«redacted:ANTHROPIC_AUTH_TOKEN»", row["detail"])
        self.assertEqual(row["ci_repo"], "o/r")
        self.assertEqual(row["ci_run_id"], "42")
        self.assertEqual(set(row) - {"_table"}, set(COLUMNS + CI_COLUMNS))

    def test_every_text_column_is_scrubbed_including_ci(self):
        s, fake = spans_with_history(cfg_with(GITHUB_REF=f"refs/heads/{TOKEN}"))
        s.history.redact_values([("ANTHROPIC_AUTH_TOKEN", TOKEN)])
        s.emit("sub", "run1", f"suite-{TOKEN}", "step.0")
        blob = json.dumps(fake.rows, default=str)
        self.assertNotIn(TOKEN, blob)

    def test_a_transcript_step_keeps_only_its_length(self):
        s, fake = spans_with_history(cfg_with())
        s.emit("sub", "run1", "suite", "driver.transcript", detail="the agent typed THIS")
        self.assertNotIn("THIS", fake.rows[0]["detail"])
        self.assertIn("20 chars", fake.rows[0]["detail"])

    def test_no_url_means_no_history(self):
        with mock.patch("gentar.spans.clickhouse_connect.get_client",
                        side_effect=Exception("no arena")) as gc:
            s = Spans(cfg_with(GENTAR_HISTORY_URL=""))
        self.assertIsNone(s.history.client)
        s.emit("sub", "run1", "suite", "step.0")          # no error
        self.assertEqual(gc.call_count, 1)                 # only the arena was tried

    def test_a_failed_write_never_raises(self):
        s, fake = spans_with_history(cfg_with())
        fake.insert = mock.Mock(side_effect=RuntimeError("down"))
        s.emit("sub", "run1", "suite", "step.0")
        s.emit("sub", "run1", "suite", "step.1")
        self.assertEqual(s.history.failed, 2)


class CollectAgentStatsTest(unittest.TestCase):

    def test_numbers_reach_the_report_and_history_text_does_not(self):
        transcript = "\n".join(json.dumps(x) for x in [
            {"type": "assistant", "timestamp": "2026-09-24T10:00:00Z",
             "message": {"id": "m1", "model": "claude-sonnet-5",
                         "usage": {"input_tokens": 10, "output_tokens": 3},
                         "content": [{"type": "text", "text": f"key {TOKEN}"}]}}])
        bench = mock.Mock()
        bench.exec.side_effect = [(0, "/home/u/.claude/projects/x/s.jsonl\n"), (0, transcript)]
        s, fake = spans_with_history(cfg_with())
        report = RunReport(scenario="suite", run_id="run1")
        coord._collect_agent_stats(bench, "run1", s, "sub", "suite", report)
        self.assertEqual(report.agent_stats["turns"], 1)
        self.assertEqual(report.agent_stats["input_tokens"], 10)
        self.assertIn("## Agent (from its session transcript", report.markdown())
        blob = json.dumps(fake.rows, default=str)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(TOKEN, report.markdown())
        self.assertEqual({r["_table"] for r in fake.rows}, {"gentar_history.agent_turns", "gentar_history.spans"})

    def test_no_transcript_no_section(self):
        bench = mock.Mock()
        bench.exec.return_value = (0, "")
        s, _ = spans_with_history(cfg_with())
        report = RunReport(scenario="suite", run_id="run1")
        coord._collect_agent_stats(bench, "run1", s, "sub", "suite", report)
        self.assertEqual(report.agent_stats, {})
        self.assertNotIn("## Agent", report.markdown())


if __name__ == "__main__":
    unittest.main()

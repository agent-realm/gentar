"""A run leaves the arena as one OTLP trace, scrubbed, agent as numbers only.

The coordinator sends every finished span to the ARENA's collector, which
keeps a local copy and forwards to the adopting repo's declared destination
(ClickStack). What leaves must be what a report would show — declared
credentials and bench-host settings scrubbed, an agent transcript only as a
length — and it must never change a verdict.
"""

import json
import os
import pathlib
import re
import unittest
from unittest import mock

from gentar.agentstats import extract
from gentar.config import Config
from gentar.spans import Spans, agent_rows, trace_id

TOKEN = "tok-9f8e7d6c5b4a-secret"


def cfg_with(**env):
    base = {"GENTAR_BENCH_HOST": "bench.internal.example", "GENTAR_BENCH_USER": "benchuser",
            "GENTAR_OTLP_SCRUBBED_ENDPOINT": "http://otelcol:14318", "GITHUB_REPOSITORY": "o/r",
            "GITHUB_RUN_ID": "42", "GENTAR_ENGINE_SHA": "abc123", "GENTAR_REPORT_DIR": ""}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config()


def spans(cfg):
    with mock.patch("gentar.spans.clickhouse_connect.get_client",
                    side_effect=Exception("no clickhouse")):
        return Spans(cfg)


class Sent:
    def __init__(self):
        self.bodies = []

    def __call__(self, req, timeout=10):
        self.bodies.append((req.full_url, json.loads(req.data)))
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"{}"
        return resp


def all_spans(body):
    return [(rs["resource"], sp) for rs in body["resourceSpans"]
            for ss in rs["scopeSpans"] for sp in ss["spans"]]


class TraceShapeTest(unittest.TestCase):

    def run_one(self, s):
        s.history.redact_values([("ANTHROPIC_AUTH_TOKEN", TOKEN)])
        root = s.step_start("sub", "run1", "suite", "scenario", attrs={"bench_kind": "sbx"})
        s.emit("sub", "run1", "suite", "oracle.step.0", "fail",
               detail=f"$ curl -H 'x: {TOKEN}' benchuser@bench.internal.example\n401")
        s.emit("sub", "run1", "suite", "driver.transcript", detail="the agent typed THIS")
        s.step_end("sub", "run1", "suite", root, "scenario", "fail", 1_000, t1_ms=4_000)
        sent = Sent()
        with mock.patch("urllib.request.urlopen", sent):
            s.otlp.flush()
        return root, sent

    def test_one_trace_rooted_at_the_scenario(self):
        root, sent = self.run_one(spans(cfg_with()))
        (url, body), = sent.bodies
        self.assertEqual(url, "http://otelcol:14318/v1/traces")
        got = all_spans(body)
        by = {sp["name"]: sp for _, sp in got}
        self.assertEqual(by["scenario"]["spanId"], root)
        self.assertNotIn("parentSpanId", by["scenario"])
        self.assertEqual(by["oracle.step.0"]["parentSpanId"], root)
        self.assertEqual({sp["traceId"] for _, sp in got}, {trace_id("sub", "run1")})
        self.assertEqual(by["scenario"]["status"]["code"], 2)          # fail -> ERROR
        self.assertEqual(int(by["scenario"]["endTimeUnixNano"]) -
                         int(by["scenario"]["startTimeUnixNano"]), 3_000_000_000)

    def test_resource_names_the_subject_and_the_ci_run(self):
        _, sent = self.run_one(spans(cfg_with()))
        res = {a["key"]: a["value"] for a in sent.bodies[0][1]["resourceSpans"][0]
               ["resource"]["attributes"]}
        self.assertEqual(res["service.name"]["stringValue"], "sub")
        self.assertEqual(res["gentar.ci_repo"]["stringValue"], "o/r")
        self.assertEqual(res["gentar.ci_run_id"]["stringValue"], "42")

    def test_nothing_secret_and_no_transcript_leaves(self):
        _, sent = self.run_one(spans(cfg_with()))
        blob = json.dumps(sent.bodies, ensure_ascii=False)
        for secret in (TOKEN, TOKEN[:14], "bench.internal.example", "benchuser", "THIS"):
            self.assertNotIn(secret, blob)
        self.assertIn("«redacted:ANTHROPIC_AUTH_TOKEN»", blob)
        self.assertIn("agent transcript, 20 chars", blob)

    def test_running_rows_are_not_exported_twice(self):
        _, sent = self.run_one(spans(cfg_with()))
        names = [sp["name"] for _, sp in all_spans(sent.bodies[0][1])]
        self.assertEqual(names.count("scenario"), 1)

    def test_no_endpoint_no_export(self):
        s = spans(cfg_with(GENTAR_OTLP_SCRUBBED_ENDPOINT=""))
        s.emit("sub", "run1", "suite", "step.0")
        self.assertEqual(s.otlp.buf, {})

    def test_a_failed_export_never_raises(self):
        s = spans(cfg_with())
        s.emit("sub", "run1", "suite", "step.0")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            s.otlp.flush()
        self.assertTrue(s.otlp.failed)



class RelayTest(unittest.TestCase):
    """A bench's self-report leaves only through the scrubbed door."""

    def report(self, **span):
        sp = {"traceId": "ab" * 16, "spanId": "cd" * 8, "name": "agent.selfreport",
              "startTimeUnixNano": "10000000000", "endTimeUnixNano": "11000000000",
              "attributes": [{"key": "cmd", "value": {"stringValue":
                              f"curl -H 'x: {TOKEN}' benchuser@bench.internal.example"}}]}
        sp.update(span)
        return json.dumps({"resourceSpans": [{"resource": {"attributes": []},
                                              "scopeSpans": [{"spans": [sp]}]}]})

    def relay(self, cfg, raw):
        s = spans(cfg)
        s.history.redact_values([("ANTHROPIC_AUTH_TOKEN", TOKEN)])
        root = s.step_start("sub", "run1", "suite", "scenario")
        sent = Sent()
        with mock.patch("urllib.request.urlopen", sent):
            s.otlp.relay("sub", "run1", raw)
        return root, sent

    def test_scrubbed_joined_to_the_run_and_named(self):
        root, sent = self.relay(cfg_with(), self.report())
        (url, body), = sent.bodies
        self.assertEqual(url, "http://otelcol:14318/v1/traces")
        blob = json.dumps(body, ensure_ascii=False)
        for secret in (TOKEN, TOKEN[:14], "bench.internal.example", "benchuser"):
            self.assertNotIn(secret, blob)
        (res, sp), = all_spans(body)
        self.assertEqual(sp["traceId"], trace_id("sub", "run1"))
        self.assertEqual(sp["parentSpanId"], root)
        keys = {a["key"]: a["value"] for a in res["attributes"]}
        self.assertEqual(keys["service.name"], {"stringValue": "sub"})
        self.assertEqual(keys["gentar.run_id"], {"stringValue": "run1"})

    def test_its_own_service_and_parents_are_kept(self):
        raw = json.loads(self.report(parentSpanId="ef" * 8))
        raw["resourceSpans"][0]["resource"]["attributes"] = [
            {"key": "service.name", "value": {"stringValue": "claude-code"}}]
        _, sent = self.relay(cfg_with(), json.dumps(raw))
        (res, sp), = all_spans(sent.bodies[0][1])
        self.assertEqual(sp["parentSpanId"], "ef" * 8)
        names = [a["value"] for a in res["attributes"] if a["key"] == "service.name"]
        self.assertEqual(names, [{"stringValue": "claude-code"}])

    def test_no_destination_nothing_relayed(self):
        _, sent = self.relay(cfg_with(GENTAR_OTLP_SCRUBBED_ENDPOINT=""), self.report())
        self.assertEqual(sent.bodies, [])

    def test_what_does_not_parse_stays_local(self):
        for raw in ("not json", "[1, 2]", '{"resourceLogs": []}', TOKEN):
            _, sent = self.relay(cfg_with(), raw)
            self.assertEqual(sent.bodies, [], raw)


class ExportConfigTest(unittest.TestCase):
    """The destination is fed by the scrubbed receiver and nothing else."""

    def test_no_export_pipeline_reads_the_raw_receiver(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        text = (root / "otelcol" / "export.yaml").read_text()
        pipelines = text.split("pipelines:", 1)[1]
        receivers = re.findall(r"receivers:\s*\[([^\]]*)\]", pipelines)
        self.assertTrue(receivers)
        for group in receivers:
            self.assertEqual([r.strip() for r in group.split(",")], ["otlp/scrubbed"])
        compose = (root / "compose.export.yml").read_text()
        self.assertNotIn("14318:", compose)       # the scrubbed door is never published
        self.assertIn("GENTAR_OTLP_SCRUBBED_ENDPOINT: http://otelcol:14318", compose)

class AgentSpansTest(unittest.TestCase):

    def test_session_turns_and_tools_become_a_numbers_only_tree(self):
        lines = [
            {"type": "assistant", "timestamp": "2026-09-25T10:00:00Z",
             "message": {"id": "m1", "model": "claude-sonnet-5",
                         "usage": {"input_tokens": 100, "output_tokens": 20},
                         "content": [{"type": "text", "text": f"key {TOKEN}"},
                                     {"type": "tool_use", "id": "t1", "name": "Bash",
                                      "input": {"command": TOKEN}}]}},
            {"type": "user", "timestamp": "2026-09-25T10:00:03Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": TOKEN}]}},
        ]
        turns, tools, _ = extract(["\n".join(json.dumps(x) for x in lines)])
        s = spans(cfg_with())
        root = s.step_start("sub", "run1", "suite", "scenario")
        agent_rows(s, "sub", "run1", "suite", turns, tools)
        sent = Sent()
        with mock.patch("urllib.request.urlopen", sent):
            s.otlp.flush()
        by = {sp["name"]: sp for _, sp in all_spans(sent.bodies[0][1])}
        self.assertEqual(by["agent.session"]["parentSpanId"], root)
        self.assertEqual(by["agent.turn"]["parentSpanId"], by["agent.session"]["spanId"])
        self.assertEqual(by["agent.tool"]["parentSpanId"], by["agent.turn"]["spanId"])
        self.assertEqual(int(by["agent.tool"]["endTimeUnixNano"]) -
                         int(by["agent.tool"]["startTimeUnixNano"]), 3_000_000_000)
        attrs = {a["key"]: a["value"] for a in by["agent.turn"]["attributes"]}
        self.assertEqual(attrs["gentar.agent.input_tokens"], {"intValue": "100"})
        self.assertEqual(attrs["gentar.agent.model"], {"stringValue": "claude-sonnet-5"})
        self.assertNotIn(TOKEN, json.dumps(sent.bodies))


    def test_no_agent_span_outlives_its_session(self):
        # agentstats never yields this (a tool starts at its turn's message),
        # but the tree must hold for any rows: an unfinished tool starting
        # after every recorded end still ends inside its session.
        s_ = 1_000_000_000
        turns = [{"session": 0, "turn": 0, "model": "claude", "input_tokens": 1,
                  "output_tokens": 1, "cache_read_tokens": 0, "cache_creation_tokens": 0,
                  "tool_calls": 1, "start_ns": 100 * s_, "end_ns": 102 * s_}]
        tools = [{"session": 0, "tool": "Bash", "duration_ms": None, "is_error": False,
                  "completed": False, "turn": 0, "start_ns": 105 * s_, "end_ns": 0}]
        s = spans(cfg_with())
        s.step_start("sub", "run1", "suite", "scenario")
        agent_rows(s, "sub", "run1", "suite", turns, tools)
        sent = Sent()
        with mock.patch("urllib.request.urlopen", sent):
            s.otlp.flush()
        got = [sp for _, sp in all_spans(sent.bodies[0][1])]
        session, = [sp for sp in got if sp["name"] == "agent.session"]
        for child in got:
            if child["name"] in ("agent.turn", "agent.tool"):
                self.assertLessEqual(int(child["endTimeUnixNano"]),
                                     int(session["endTimeUnixNano"]), child["name"])

if __name__ == "__main__":
    unittest.main()

"""otlp-selfreport proves delivery, not a file (ground-up review A8, SC05).

The suite checked only that the bench's OTLP drop file was non-empty: a
collector that rejected the body, or a span ClickHouse never kept (its
timestamp read as 1970, review S2-1), still passed. With
`[verify] self_report = true` the coordinator relays the file before the
verdict and waits for the span to join the run's harness spans on run_id.
"""

import http.server
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gentar import selfreport
from gentar.toml_scenario import ScenarioError, TomlScenario

ROOT = Path(__file__).resolve().parents[2]
# coordinator/scenarios in a checkout, /app/scenarios in the image
SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "otlp-selfreport.toml"
BODY = '{"resourceSpans": []}'


class Bench:
    def __init__(self, body=BODY):
        self.body = body

    def exec(self, run_id, command, timeout=300, env=None):
        return (0, self.body) if self.body else (1, "")


class Client:
    """ClickHouse stand-in: answers the join with the counts given, in turn."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.queries = []

    def query(self, sql, parameters=None):
        self.queries.append((sql, parameters))
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return SimpleNamespace(result_rows=[(a,)])


def spans(client=None):
    return SimpleNamespace(client=client, otlp=mock.MagicMock(), emit=mock.MagicMock())


class Collector(http.server.BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        Collector.got.append((self.path, self.rfile.read(int(self.headers["content-length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class RelayTest(unittest.TestCase):

    def setUp(self):
        selfreport.RELAYED.clear()
        self.addCleanup(selfreport.RELAYED.clear)
        Collector.got = []
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), Collector)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.cfg = SimpleNamespace(otlp_endpoint=f"http://127.0.0.1:{self.srv.server_port}",
                                   clickhouse_db="gentar")

    def test_the_file_reaches_the_collector_once(self):
        s = spans()
        ok, detail = selfreport.relay(Bench(), "r1", s, self.cfg, "arena", "otlp")
        self.assertTrue(ok, detail)
        self.assertEqual(Collector.got, [("/v1/traces", BODY.encode())])
        self.assertIn("r1", selfreport.RELAYED)
        s.otlp.relay.assert_called_once_with("arena", "r1", BODY)
        self.assertEqual(selfreport.relay(Bench(), "r1", s, self.cfg, "arena", "otlp"),
                         (True, "already relayed"))
        self.assertEqual(len(Collector.got), 1)

    def test_no_file_no_endpoint_or_a_dead_collector_fail(self):
        ok, detail = selfreport.relay(Bench(""), "r2", spans(), self.cfg, "arena", "otlp")
        self.assertEqual((ok, detail), (False, f"no self-report at {selfreport.DROP}"))
        ok, detail = selfreport.relay(Bench(), "r3", spans(),
                                      SimpleNamespace(otlp_endpoint=""), "arena", "otlp")
        self.assertFalse(ok)
        self.assertIn("no OTLP endpoint", detail)
        dead = SimpleNamespace(otlp_endpoint="http://127.0.0.1:1")
        ok, detail = selfreport.relay(Bench(), "r4", spans(), dead, "arena", "otlp")
        self.assertFalse(ok)
        self.assertIn("relay to http://127.0.0.1:1 failed", detail)

    def test_a_failed_send_is_never_resent_by_the_runs_own_relay(self):
        # Codex on #99: the scrubbed export left before the POST failed, and
        # the run's `finally` relay sent it again
        from gentar import coordinator
        s = spans()
        dead = SimpleNamespace(otlp_endpoint="http://127.0.0.1:1")
        ok, _ = selfreport.relay(Bench(), "r6", s, dead, "arena", "otlp")
        self.assertFalse(ok)
        self.assertIn("r6", selfreport.RELAYED)
        coordinator._relay_agent_spans(Bench(), "r6", s, dead, "arena", "otlp")
        s.otlp.relay.assert_called_once_with("arena", "r6", BODY)

    def test_check_does_not_query_when_the_relay_failed(self):
        c = Client(1)
        r = selfreport.check(Bench(""), "r5", spans(c), self.cfg, "arena", "otlp")
        self.assertEqual((r.name, r.ok), (selfreport.CHECK, False))
        self.assertEqual(c.queries, [])


class JoinTest(unittest.TestCase):

    cfg = SimpleNamespace(clickhouse_db="gentar")

    def run_join(self, client, deadline=10):
        t = [0.0]
        return selfreport.joined(spans(client), self.cfg, "run-x", deadline,
                                 sleep=lambda s: t.__setitem__(0, t[0] + s),
                                 clock=lambda: t[0])

    def test_a_span_that_joins_passes(self):
        c = Client(0, 0, 2)
        ok, detail = self.run_join(c)
        self.assertTrue(ok, detail)
        self.assertIn("2 agent span(s) joined", detail)
        self.assertEqual(len(c.queries), 3)
        sql, params = c.queries[0]
        self.assertEqual(params, {"run_id": "run-x"})        # bound, never pasted in
        self.assertNotIn("run-x", sql)
        self.assertIn("gentar.otel_traces", sql)
        self.assertIn("gentar.spans", sql)
        self.assertIn("ResourceAttributes['gentar.run_id'] = s.run_id", sql)

    def test_no_span_by_the_deadline_fails(self):
        ok, detail = self.run_join(Client(0))
        self.assertFalse(ok)
        self.assertIn("after 10s (no agent span yet)", detail)

    def test_a_failing_query_is_retried_and_named(self):
        ok, _ = self.run_join(Client(RuntimeError("no table otel_traces"), 1))
        self.assertTrue(ok)
        ok, detail = self.run_join(Client(RuntimeError("no table otel_traces")))
        self.assertFalse(ok)
        self.assertIn("query failed: RuntimeError: no table otel_traces", detail)

    def test_an_empty_run_id_is_never_joined(self):
        c = Client(5)
        ok, detail = selfreport.joined(spans(c), self.cfg, "")
        self.assertEqual((ok, detail), (False, "no run id: the join cannot be checked"))
        self.assertEqual(c.queries, [])

    def test_no_client_fails(self):
        ok, detail = selfreport.joined(spans(None), self.cfg, "r")
        self.assertEqual((ok, detail), (False, "no ClickHouse client: the join cannot be checked"))


class WiringTest(unittest.TestCase):

    def test_the_runs_own_relay_skips_a_relayed_run(self):
        from gentar import coordinator
        selfreport.RELAYED.add("r9")
        bench = mock.MagicMock()
        coordinator._relay_agent_spans(bench, "r9", spans(), SimpleNamespace(), "arena", "x")
        bench.exec.assert_not_called()
        self.assertNotIn("r9", selfreport.RELAYED)

    def test_the_key_is_a_boolean(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.toml"
            f.write_text('[scenario]\nname = "s"\n[oracle]\nsteps = ["true"]\n[verify]\nself_report = "yes"\n')
            with self.assertRaisesRegex(ScenarioError, "verify.self_report must be true or false"):
                TomlScenario(f)
            f.write_text('[scenario]\nname = "s"\n[oracle]\nsteps = ["true"]\n')
            self.assertFalse(TomlScenario(f).self_report)

    def test_run_oracle_appends_the_check(self):
        from gentar import oracle
        sc = TomlScenario(SCENARIO)
        bench = mock.MagicMock(push_before_create=True)
        bench.workspace.return_value = "/w"
        bench.exec.return_value = (0, "/home/arena\nselfreport-nonempty\n")
        cfg = SimpleNamespace(otlp_endpoint="http://otelcol:4318", clickhouse_db="gentar")
        with mock.patch.object(oracle, "_step"), \
             mock.patch("gentar.selfreport.check",
                        return_value=selfreport.AssertResult(selfreport.CHECK, False, "x")) as chk:
            with self.assertRaisesRegex(AssertionError, "otlp-join run_id: x"):
                oracle.run_oracle(sc, bench, "r", spans(), cfg)
        chk.assert_called_once()

    def test_the_suite_proves_the_join_with_an_epoch_timestamp(self):
        sc = TomlScenario(SCENARIO)
        self.assertTrue(sc.self_report)
        step = sc.steps[0]
        self.assertNotIn("process.hrtime.bigint()", step)
        self.assertIn("BigInt(Date.now()) * 1000000n", step)


KIT = ROOT / "subject-template" / "gentar"


@unittest.skipUnless(KIT.exists(), "the kit is not in the image build context")
class DryRunTest(unittest.TestCase):
    """The kit's dry-run has no ClickHouse: a self-report suite is UNVERIFIED
    there, never a pass, whatever its other checks say."""

    def test_a_self_report_suite_is_unverified_not_a_pass(self):
        import os
        import shutil
        import subprocess
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        shutil.copytree(KIT, repo / "gentar")
        sc = repo / "gentar" / "scenarios"
        shutil.rmtree(sc)
        sc.mkdir()
        (sc / "s.toml").write_text('[scenario]\nsubject = "x"\n[oracle]\nsteps = ["true"]\n'
                                   '[verify]\nself_report = true\n'
                                   '[[verify.commands]]\ncommand = "true"\n')
        env = dict(os.environ, GENTAR_ENGINE=str(ROOT / "coordinator"), TMPDIR=str(tmp))
        env.pop("GENTAR_DRYRUN_UNVERIFIED", None)
        run = lambda **e: subprocess.run(["python3", "gentar/dryrun.py", "gentar/scenarios/s.toml"],
                                         cwd=repo, env={**env, **e}, capture_output=True, text=True)
        r = run()
        self.assertIn("s.toml: UNVERIFIED (the self-report join needs the arena)", r.stdout,
                      r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(run(GENTAR_DRYRUN_UNVERIFIED="ok").returncode, 0)   # as --check runs it


if __name__ == "__main__":
    unittest.main()

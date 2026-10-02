"""A driller run end to end, bench and model faked: the [driller] table, one
session (gentar/driller_run.py), N sessions (coordinator._run_drill), and the
guard that refuses before any bench exists.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from gentar import coordinator as coord
from gentar import driller as d
from gentar import driller_run
from gentar.benchhost import SbxBenchHost
from gentar.config import Config
from gentar.toml_scenario import ScenarioError, TomlScenario

HEAD = '[scenario]\nname = "wh"\nsubject = "demo"\ndata = "synthetic"\n'
DRILLER = '[driller]\nhat = "white-hat"\nruns = 3\nhelp = ["tool"]\n'
DENY = [{"id": "default-deny-all", "applies_to": "all", "resource_type": "network",
         "decision": "deny", "resources": ["**"], "status": "active"}]
CHECKS = [{"allowed": False, "context": "global", "target": c} for c in d.CANARIES]


def load(text):
    f = Path(tempfile.mkdtemp()) / "wh.toml"
    f.write_text(text)
    return TomlScenario(f)


class TableTest(unittest.TestCase):

    def test_a_driller_needs_no_steps_and_gets_defaults(self):
        sc = load(HEAD + DRILLER)
        self.assertEqual(sc.driller["hat"], "white-hat")
        self.assertEqual((sc.driller["runs"], sc.driller["allow"], sc.driller["command"]),
                         (3, [], "bash -l"))

    def test_refusals(self):
        cases = {
            "not synthetic": HEAD.replace('data = "synthetic"\n', "") + DRILLER,
            "with a driver": HEAD + DRILLER + '[driver]\ncommand = "bash"\n',
            "unknown key": HEAD + DRILLER + 'target = "x"\n',
            "unknown hat": HEAD + DRILLER.replace("white-hat", "black-hat"),
            "runs 0": HEAD + DRILLER.replace("runs = 3", "runs = 0"),
            "runs 21": HEAD + DRILLER.replace("runs = 3", "runs = 21"),
            "runs bool": HEAD + DRILLER.replace("runs = 3", "runs = true"),
            "wildcard": HEAD + DRILLER + 'allow = ["*.npmjs.org"]\n',
            "ip": HEAD + DRILLER + 'allow = ["10.10.10.52:22"]\n',
            "help newline": HEAD + DRILLER.replace('["tool"]', '["tool\\nrm x"]'),
            "arena credential": HEAD.replace('data =', 'credentials = ["GENTAR_OSB_API_KEY"]\ndata =')
                                + DRILLER,
        }
        for why, text in cases.items():
            with self.subTest(why=why), self.assertRaises(ScenarioError):
                load(text)


class ModelChoiceTest(unittest.TestCase):
    """Each repo, each driller, picks its own model; the arena keeps the
    route and may restrict the choice (pilot, 2026-10-02)."""

    ARENA = {"GENTAR_DRILLER_MODEL_URL": "http://tr0:20128/v1", "GENTAR_DRILLER_MODEL": "glm/glm-5.3",
             "GENTAR_DRILLER_MODEL_KEY": "k", "TYPESAFE_API_KEY": "judge", "BENCH_SSH_KEY": "b"}

    def test_the_scenario_picks_the_model(self):
        sc = load(HEAD + DRILLER + 'model = "cc/claude-sonnet-5"\n')
        self.assertEqual(sc.driller["model"], "cc/claude-sonnet-5")
        env = d.model_env(self.ARENA, sc.driller["model"])
        self.assertEqual(env["GENTAR_DRILLER_MODEL"], "cc/claude-sonnet-5")
        self.assertEqual(set(env), {"GENTAR_DRILLER_MODEL_URL", "GENTAR_DRILLER_MODEL",
                                    "GENTAR_DRILLER_MODEL_KEY"})      # nothing else leaks in

    def test_without_one_the_arena_default_is_used(self):
        sc = load(HEAD + DRILLER)
        self.assertEqual(sc.driller["model"], "")
        self.assertEqual(d.model_env(self.ARENA, "")["GENTAR_DRILLER_MODEL"], "glm/glm-5.3")
        self.assertEqual(d.model_problems(self.ARENA, "glm/glm-5.3"), [])

    def test_no_model_anywhere_refuses(self):
        env = dict(self.ARENA, GENTAR_DRILLER_MODEL="")
        why = d.start_refusals(env, DENY, [], [], CHECKS, model="")
        self.assertTrue(any("no driller model" in w for w in why))

    def test_the_arena_allowlist_is_the_operators_say(self):
        env = dict(self.ARENA, GENTAR_DRILLER_MODELS="cc/claude-sonnet-5, glm/glm-5.3")
        self.assertEqual(d.model_problems(env, "cc/claude-sonnet-5"), [])
        self.assertIn("not one this arena allows", d.model_problems(env, "deepseek/deepseek-v4-pro")[0])

    def test_a_malformed_model_is_refused_at_load(self):
        for bad in ('model = "a b"', 'model = 3', 'model = "$(id)"', 'model = "/x"'):
            with self.subTest(bad=bad), self.assertRaises(ScenarioError):
                load(HEAD + DRILLER + bad + "\n")


class FakeBench:
    def __init__(self, rules=None, log=None, after=None):
        self.rules = DENY if rules is None else rules
        self.log = log or {"blocked_hosts": [], "allowed_hosts": []}
        self.after = after
        self.allowed = []
        self.snaps = 0

    def policy_state(self, canaries):
        return self.rules, [c for c in CHECKS if c["target"] in canaries]

    def allow_for(self, sandbox, argv):
        self.allowed.append(argv)

    def policy_log(self, sandbox):
        return json.dumps(self.log)

    def snapshot(self):
        self.snaps += 1
        if self.snaps > 1 and self.after is not None:
            return self.after
        return {"sandboxes": {"other"}, "templates": {"t:1:abc"}}

    def workspace(self, run_id):
        return f"/w/{run_id}"

    def exec(self, run_id, cmd, timeout=300, env=None):
        return 0, "Tool README\n" if cmd.startswith("cat ") else "usage: tool\n"


class FakeDriver:
    def __init__(self):
        self.transcript = "$ ls -l ~/.tool/token\r\n-rw-r--r-- 1 u u 41 token\r\n"
        self.started = None
        self.sent = []

    def start(self, command, env=None):
        self.started = (command, env)

    def screen(self):
        return "$ "

    def send_text(self, s):
        self.sent.append(s)

    def send_key(self, k):
        self.sent.append(k)

    def abort(self, why):
        pass

    def close(self):
        pass


class FakeModel:
    calls = input_tokens = 0

    def next(self, *a):
        self.calls += 1
        return NS(kind=NS(value="DONE"), text=None, enter=None, key=None, why="enough")

    def notes(self, *a):
        return "the token file is world readable: -rw-r--r-- 1 u u 41 token"


def finding(ev):
    return NS(category=NS(value="FILE_PERMISSIONS"), severity=NS(value="HIGH"), title="t",
              evidence=ev, reproduce="ls -l ~/.tool/token", confidence=0.9)


def spans():
    s = mock.Mock()
    s.redactor.scrub = lambda t: t
    return s


class SessionTest(unittest.TestCase):

    def run_session(self, bench, sc=None, extracted=None):
        sc = sc or load(HEAD + DRILLER)
        drv = FakeDriver()
        report = NS(transcript="", driller=None)
        with mock.patch.object(d, "extract", return_value=extracted or []):
            try:
                out = driller_run.session(sc, bench, "box1", spans(), "demo", report=report,
                                          driver_factory=lambda: drv,
                                          model_factory=FakeModel, env={})
            except driller_run.BoundaryBreach as exc:
                return None, report, drv, exc
        return out, report, drv, None

    def test_a_clean_session_reports_supported_findings_only(self):
        found = [finding("-rw-r--r-- 1 u u 41 token"), finding("-rw-rw-rw- /etc/shadow")]
        out, report, drv, err = self.run_session(FakeBench(), extracted=found)
        self.assertIsNone(err)
        self.assertEqual(len(report.driller["findings"]), 1)
        self.assertEqual(report.driller["dropped"], 1)
        self.assertIn("1 supported finding(s), 1 dropped", out)
        self.assertEqual(drv.started[0], "bash -l")

    def test_no_allowlist_means_no_rule_is_added(self):
        bench = FakeBench()
        self.run_session(bench)
        self.assertEqual(bench.allowed, [])
        bench = FakeBench()
        self.run_session(bench, sc=load(HEAD + DRILLER + 'allow = ["registry.npmjs.org:443"]\n'))
        self.assertEqual(bench.allowed[0][-1], "registry.npmjs.org:443")

    def test_a_kit_rule_refuses_before_the_driller_types(self):
        kit = {"id": "k", "applies_to": "sandbox:box1", "resource_type": "network",
               "decision": "allow", "resources": ["proxy.golang.org"], "status": "active",
               "origin": "kit"}
        out, report, drv, err = self.run_session(FakeBench(rules=DENY + [kit]))
        self.assertIsInstance(err, driller_run.BoundaryBreach)
        self.assertIsNone(drv.started)                  # never started

    def test_an_allowed_connection_off_the_list_fails_the_session(self):
        log = {"blocked_hosts": [], "allowed_hosts": [
            {"host": "evil.example:443", "vm_name": "box1", "proxy_type": "forward"}]}
        out, report, drv, err = self.run_session(FakeBench(log=log))
        self.assertIsInstance(err, driller_run.BoundaryBreach)
        self.assertIn("evil.example:443", str(err))
        self.assertTrue(report.driller["breaches"])     # recorded before failing

    def test_a_change_outside_the_bench_fails_the_session(self):
        after = {"sandboxes": {"other", "box1", "sneaky"}, "templates": {"t:1:abc"}}
        out, report, drv, err = self.run_session(FakeBench(after=after))
        self.assertIn("sneaky appeared", str(err))

    def test_blocked_attempts_are_findings_not_failures(self):
        log = {"blocked_hosts": [{"host": "10.10.10.1:22", "vm_name": "box1"}],
               "allowed_hosts": []}
        out, report, drv, err = self.run_session(FakeBench(log=log))
        self.assertIsNone(err)
        self.assertIn("1 blocked attempt(s)", out)


class RunDrillTest(unittest.TestCase):

    def drive(self, rcs):
        sc = load(HEAD + DRILLER)
        calls = []

        def fake_run(name, cfg):
            i = len(calls)
            calls.append(i)
            driller_run.SINK.append((name, {"findings": [finding("-rw-r--r-- 1 u u 41 token")],
                                            "audit": d.Audit()}))
            return rcs[i]
        with mock.patch.object(coord, "_resolve", return_value=(None, sc)), \
             mock.patch.object(coord, "_run", side_effect=fake_run), \
             mock.patch.object(coord, "Spans"), mock.patch("builtins.print"):
            rc = coord.run("wh", Config())
        return rc, calls

    def test_n_sessions_then_a_ranked_summary(self):
        rc, calls = self.drive([0, 0, 0])
        self.assertEqual((rc, len(calls)), (0, 3))

    def test_a_breach_stops_at_once(self):
        rc, calls = self.drive([0, 1, 0])
        self.assertEqual((rc, len(calls)), (1, 2))

    def test_a_refusal_is_2(self):
        rc, calls = self.drive([2, 0, 0])
        self.assertEqual((rc, len(calls)), (2, 1))


class GuardTest(unittest.TestCase):

    def cfg(self, **env):
        base = {"GENTAR_BENCH_HOST": "bench.test", "GENTAR_BENCH_USER": "u",
                "GENTAR_REPORT_DIR": "", "GENTAR_DRILLER_MODEL_URL": "http://tr0:20128/v1",
                "GENTAR_DRILLER_MODEL": "m"}
        base.update(env)
        return base

    def guard(self, bench, **env):
        sc = load(HEAD + DRILLER)
        with mock.patch.dict(os.environ, self.cfg(**env), clear=True):
            cfg = Config()
            with mock.patch.object(coord, "_resolve", return_value=(lambda *a, **k: "", sc)), \
                 mock.patch.object(coord, "make_bench", return_value=bench), \
                 mock.patch.object(coord, "Spans"), \
                 mock.patch("builtins.print"):
                return coord._run("wh", cfg)

    def sbx(self, rules_json, check_allowed):
        host = SbxBenchHost(Config())
        host.preflight = lambda: []

        def fake_run(cmd, timeout=300, strict=True):
            if cmd[1:3] == ["policy", "ls"]:
                out = json.dumps(rules_json)
            elif cmd[1:3] == ["policy", "check"]:
                out = json.dumps({"allowed": check_allowed, "context": "global", "target": cmd[4]})
            else:
                out = ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        host._run = fake_run
        host.create = mock.Mock()
        return host

    def test_the_shared_allow_all_host_is_refused_before_any_bench(self):
        allow_all = {"rules": [{"id": "default-allow-all", "applies_to": "all",
                                "resource_type": "network", "decision": "allow",
                                "resources": ["**"], "status": "active"}]}
        bench = self.sbx(allow_all, True)
        self.assertEqual(self.guard(bench), 2)
        bench.create.assert_not_called()

    def test_boundary_api_key_refuses_before_any_bench(self):
        bench = self.sbx({"rules": DENY}, False)
        self.assertEqual(self.guard(bench, BOUNDARY_API_KEY=""), 2)
        bench.create.assert_not_called()

    def test_a_non_sbx_tier_is_refused(self):
        bench = mock.Mock(spec=["preflight", "create", "rm", "template_digest"])
        bench.preflight.return_value = []
        self.assertEqual(self.guard(bench), 2)
        bench.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()

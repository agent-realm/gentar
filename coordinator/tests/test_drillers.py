"""Drillers, the bench-free core (gentar/driller.py).

The boundary must hold whatever the driller does, so each layer that can be
decided from data is tested from data: the refusals before any bench, the
sbx policy log audit after the run, and the evidence rule for findings. The
sbx shapes below are copied from sbx 0.39 on VM 142 (read-only probe,
2026-09-27).
"""

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from gentar import driller as d

HERE = Path(__file__).resolve().parent.parent          # coordinator/

INSPECT_ALLOW_ALL = """Policy:      local-policy
Policy ID:   local-policy
Source:      local
Applies to:  all
Status:      active

Rules in this policy:
DECISION   RESOURCE   TYPE               RULE   STATUS
allow      **         network            -      active
allow      **         filesystem:read    -      active
allow      **         filesystem:write   -      active

Rule IDs:
RULE   RULE_ID                      EDITABLE   ACTION
-      default-allow-all            yes        sbx policy rm network --id default-allow-all
"""

INSPECT_DENY_DEFAULT = INSPECT_ALLOW_ALL.replace(
    "allow      **         network            -      active\n", "")

SB = "g1-driller-white-hat-0"
ENV = {"GENTAR_DRILLER_MODEL_URL": "http://tr0:20128/v1", "GENTAR_DRILLER_MODEL": "m"}


def log(blocked=(), allowed=()):
    def e(host, vm=SB, ptype="transparent"):
        return {"host": host, "vm_name": vm, "proxy_type": ptype, "rule": "",
                "since": "2026-09-27T13:21:06Z", "last_seen": "2026-09-27T13:21:06Z",
                "count_since": 1}
    return json.dumps({"blocked_hosts": [e(*x) if isinstance(x, tuple) else e(x) for x in blocked],
                       "allowed_hosts": [e(*x) if isinstance(x, tuple) else e(x) for x in allowed]})


def finding(cat="FILE_PERMISSIONS", sev="HIGH", ev="-rw-r--r-- 1 u u 41 token", title="t"):
    return NS(category=NS(value=cat), severity=NS(value=sev), evidence=ev, title=title,
              reproduce="ls -l token", confidence=0.9)


class RefusalsTest(unittest.TestCase):

    def test_the_shared_allow_all_host_is_refused(self):
        # VM 142 today: a sandbox cannot be narrowed below a global `allow **`
        rules = d.parse_policy_inspect(INSPECT_ALLOW_ALL)
        self.assertTrue(d.host_allows_all(rules))
        why = d.start_refusals(ENV, rules, [], [])
        self.assertTrue(any("deny-by-default bench host" in w for w in why), why)

    def test_a_deny_by_default_host_with_a_clean_brief_goes(self):
        rules = d.parse_policy_inspect(INSPECT_DENY_DEFAULT)
        self.assertFalse(d.host_allows_all(rules))
        self.assertEqual(d.start_refusals(ENV, rules, ["registry.npmjs.org:443"], ["DEMO_TOKEN"]), [])

    def test_boundary_api_key_refuses_whatever_its_value(self):
        for v in ("x", ""):
            why = d.start_refusals(dict(ENV, BOUNDARY_API_KEY=v), [], [], [])
            self.assertTrue(any("BOUNDARY_API_KEY" in w for w in why))
        with self.assertRaises(d.DrillerRefusal):
            d.extract("hat", "notes", "t", env={"BOUNDARY_API_KEY": ""}, raw="[]")

    def test_arena_keys_never_reach_a_driller_bench(self):
        for name in ("TYPESAFE_API_KEY", "BENCH_SSH_KEY", "GENTAR_DRILLER_MODEL_KEY"):
            why = d.start_refusals(ENV, [], [], [name])
            self.assertTrue(any(name in w for w in why), name)

    def test_the_model_route_must_be_set(self):
        why = d.start_refusals({}, [], [], [])
        self.assertEqual(sum("GENTAR_DRILLER_MODEL" in w for w in why), 2)

    def test_allowlist_entries(self):
        ok = ["registry.npmjs.org", "registry.npmjs.org:443", "*.npmjs.org", "tr0:20128"]
        bad = ["**", "*", "*.org", "10.10.10.52", "10.10.10.52:22", "::1", "a b",
               "http://x.org", "x.org/path", "*.*.org", "x.org:99999999"]
        for e in ok:
            self.assertIsNone(d.allow_problems(e), e)
        for e in bad:
            self.assertIsNotNone(d.allow_problems(e), e)

    def test_no_allowlist_means_no_network_rule_at_all(self):
        # the model is called by the coordinator; the bench needs no route
        self.assertIsNone(d.policy_argv(SB, []))
        self.assertEqual(d.policy_argv(SB, ["b.org", "a.org:443"]),
                         ["sbx", "policy", "allow", "network", "--sandbox", SB, "a.org:443,b.org"])


class AuditTest(unittest.TestCase):

    def test_a_blocked_attempt_is_a_finding_not_a_failure(self):
        a = d.audit(log(blocked=["10.10.10.1:22"]), SB, [])
        self.assertEqual([e["host"] for e in a.denied], ["10.10.10.1:22"])
        self.assertEqual(d.verdict(a, []), (0, []))

    def test_an_allowed_host_off_the_allowlist_fails_the_run(self):
        a = d.audit(log(allowed=["evil.example:443", "registry.npmjs.org:443"]), SB,
                    ["registry.npmjs.org:443"])
        code, why = d.verdict(a, [])
        self.assertEqual(code, 1)
        self.assertEqual(len(why), 1)
        self.assertIn("evil.example:443", why[0])

    def test_with_no_allowlist_any_allowed_connection_is_a_breach(self):
        a = d.audit(log(allowed=[("proxy.golang.org:443", SB, "forward-bypass")]), SB, [])
        self.assertEqual(d.verdict(a, [])[0], 1)

    def test_other_sandboxes_entries_are_ignored(self):
        a = d.audit(log(allowed=[("anything:443", "someone-else")]), SB, [])
        self.assertEqual((a.breaches, a.allowed, a.denied), ([], [], []))

    def test_host_matching(self):
        allow = ["a.org", "b.org:443", "*.c.org"]
        cases = {"a.org:80": True, "a.org:443": True, "b.org:443": True, "b.org:80": False,
                 "x.c.org:443": True, "c.org:443": False, "xa.org:80": False,
                 "a.org.evil:80": False, "evilc.org:443": False}
        for host, want in cases.items():
            self.assertEqual(d.host_allowed(host, allow), want, host)

    def test_a_change_outside_the_bench_fails_the_run(self):
        before = {"sandboxes": {"other"}, "templates": {"t1"}}
        after = {"sandboxes": {"other", SB, "sneaky"}, "templates": set()}
        out = d.outside_changes(before, after, {SB})
        self.assertEqual(out, ["sandboxes: sneaky appeared", "templates: t1 disappeared"])
        self.assertEqual(d.verdict(d.Audit(), out)[0], 1)


class FindingsTest(unittest.TestCase):

    TRANSCRIPT = "$ ls -l ~/.tool/token\r\n\x1b[0m-rw-r--r--  1 u u 41 token\r\n$ "

    def test_evidence_must_be_on_the_screen(self):
        real = finding()
        made_up = finding(ev="-rw-rw-rw- 1 root root 9 /etc/shadow")
        empty = finding(ev="")
        kept, dropped = d.supported([real, made_up, empty], self.TRANSCRIPT)
        self.assertEqual(kept, [real])
        self.assertEqual(dropped, [made_up, empty])

    def test_frequency_counts_runs_not_mentions(self):
        runs = [[finding(), finding()],                      # one run, said twice
                [finding(ev="-rw-r--r-- 1 u u 57 token")],   # sizes differ: same finding
                [finding(cat="UNSAFE_DEFAULT", ev="debug=true", sev="LOW")],
                []]
        cl = d.cluster(runs)
        self.assertEqual([(c.category, c.runs) for c in cl],
                         [("FILE_PERMISSIONS", 2), ("UNSAFE_DEFAULT", 1)])
        text = d.render(cl, 4, [d.audit(log(blocked=["x.org:443"]), SB, [])])
        self.assertIn("**2/4** HIGH FILE_PERMISSIONS", text)
        self.assertIn("**1/4** (single run) LOW UNSAFE_DEFAULT", text)
        self.assertIn("Blocked attempts (the wall held): x.org:443", text)

    def test_the_report_is_scrubbed(self):
        f = finding(ev="token=sk-SECRETVALUE123")
        text = d.render(d.cluster([[f]]), 1, [], scrub=lambda s: s.replace("sk-SECRETVALUE123", "[redacted]"))
        self.assertNotIn("SECRETVALUE", text)

    def test_the_order_is_deterministic(self):
        runs = [[finding(cat=c, ev=c.lower(), sev="LOW")] for c in ("B_CAT", "A_CAT")]
        self.assertEqual([c.category for c in d.cluster(runs)], ["A_CAT", "B_CAT"])


try:
    import baml_py  # noqa: F401
    HAVE_BAML = True
except ModuleNotFoundError:
    HAVE_BAML = False


@unittest.skipUnless(HAVE_BAML, "baml-py not installed (it is in the image)")
class BamlTest(unittest.TestCase):
    """The typed-findings parser, offline: BAML parses a model's answer
    without calling any model, so messy output is tested without a network."""

    def test_messy_model_output_parses_into_typed_findings(self):
        raw = ('Sure! Here are the findings:\n```json\n[{"category": "file_permissions", '
               '"severity": "High", "title": "token world readable", "evidence": '
               '"-rw-r--r-- 1 u u 41 token", "reproduce": "ls -l ~/.tool/token", '
               '"confidence": "0.9",}]\n```')
        out = d.extract("white hat", "", "", env={}, raw=raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].category.value, "FILE_PERMISSIONS")
        self.assertEqual(out[0].severity.value, "HIGH")
        self.assertAlmostEqual(out[0].confidence, 0.9)

    def test_nonsense_is_no_findings_not_an_invented_one(self):
        for raw in ("no idea", '[{"category": "NUKE", "severity": "LOW"}]'):
            self.assertEqual(d.extract("h", "", "", env={}, raw=raw), [])


class PinTest(unittest.TestCase):

    def test_the_generator_pin_equals_the_requirements_pin(self):
        gen = (HERE / "baml_src" / "generators.baml").read_text()
        req = (HERE / "requirements.txt").read_text()
        g = re.search(r'version "([^"]+)"', gen).group(1)
        r = re.search(r"^baml-py==(\S+)$", req, re.M).group(1)
        self.assertEqual(g, r)
        client = (HERE / "gentar" / "baml_client" / "__init__.py").read_text()
        self.assertIn(f'"{g}"', client)            # the committed client matches too

    def test_the_model_is_addressed_only_by_environment(self):
        src = (HERE / "baml_src" / "drillers.baml").read_text()
        self.assertNotIn("boundaryml.com", src)
        for key in ("base_url", "model", "api_key"):
            self.assertRegex(src, rf"\n\s*{key} env\.GENTAR_DRILLER_MODEL")


if __name__ == "__main__":
    unittest.main()

"""Install-identity guard: the engine must REFUSE, not fall back.

gentar ships no bench-host of its own. Before this guard the config
carried the author's own VM as a default, so an adopter with no `.env`
silently SSHed to a stranger's machine. The rule is now: a value that
can only be the install's has no default, and a run that selects a tier
missing one is refused (exit 2) BEFORE any bench is created — the same
class of refusal as the credential and budget guards.

These tests own both halves: which vars each tier requires
(Config.missing_bench_env) and that the refusal is an exit-2 verdict
naming the vars (coordinator.run), with no bench constructed.
"""

import os
import unittest
from unittest import mock

from gentar import coordinator as coord
from gentar.config import BENCH_REQUIREMENTS, Config


def cfg_with(**env) -> Config:
    """A Config built from exactly `env` — nothing inherited from the
    ambient environment, so a configured dev box can't mask a missing
    default."""
    with mock.patch.dict(os.environ, env, clear=True):
        return Config()


class NoPersonalDefaultsTest(unittest.TestCase):
    """The regression that started this: no install's own machines in
    the source. A default here would make the guard unreachable."""

    def test_bench_host_and_user_have_no_default(self):
        cfg = cfg_with()
        self.assertEqual(cfg.bench_host, "")
        self.assertEqual(cfg.bench_user, "")

    def test_tart_host_and_user_have_no_default(self):
        cfg = cfg_with()
        self.assertEqual(cfg.tart_host, "")
        self.assertEqual(cfg.tart_user, "")

    def test_generic_defaults_are_kept(self):
        # Genericness is fine — only personal is not. These carry no
        # install identity, so removing them would be churn.
        cfg = cfg_with()
        self.assertEqual(cfg.bench_key, "~/.ssh/id_ed25519")
        self.assertEqual(cfg.bench_kind, "sbx")
        self.assertEqual(cfg.osb_server, "http://127.0.0.1:8080")


class MissingBenchEnvTest(unittest.TestCase):
    def test_sbx_unconfigured_names_both_vars_in_order(self):
        self.assertEqual(cfg_with().missing_bench_env("sbx"),
                         ["GENTAR_BENCH_HOST", "GENTAR_BENCH_USER"])

    def test_sbx_half_configured_names_only_the_missing_one(self):
        cfg = cfg_with(GENTAR_BENCH_HOST="bench.example.internal")
        self.assertEqual(cfg.missing_bench_env("sbx"), ["GENTAR_BENCH_USER"])

    def test_sbx_configured_is_clean(self):
        cfg = cfg_with(GENTAR_BENCH_HOST="bench.example.internal",
                       GENTAR_BENCH_USER="bench")
        self.assertEqual(cfg.missing_bench_env("sbx"), [])

    def test_whitespace_only_counts_as_missing(self):
        # An env var set to blanks is a misconfiguration, not a value;
        # ssh would take "  @host" and fail obscurely later.
        cfg = cfg_with(GENTAR_BENCH_HOST="   ", GENTAR_BENCH_USER="bench")
        self.assertEqual(cfg.missing_bench_env("sbx"), ["GENTAR_BENCH_HOST"])

    def test_empty_kind_falls_back_to_install_default(self):
        self.assertEqual(cfg_with().missing_bench_env(),
                         ["GENTAR_BENCH_HOST", "GENTAR_BENCH_USER"])

    def test_tart_required_only_for_tart(self):
        cfg = cfg_with(GENTAR_BENCH_HOST="bench.example.internal",
                       GENTAR_BENCH_USER="bench")
        # The whole point of checking per-run: an sbx-only install is
        # not made to configure a tier it never selects.
        self.assertEqual(cfg.missing_bench_env("sbx"), [])
        self.assertEqual(cfg.missing_bench_env("tart"),
                         ["GENTAR_TART_HOST", "GENTAR_TART_USER"])

    def test_osb_needs_nothing_from_this_guard(self):
        # Its server address defaults to localhost: generic, and wrong
        # for nobody in particular.
        self.assertEqual(cfg_with().missing_bench_env("osb"), [])

    def test_daytona_needs_its_api_key(self):
        self.assertEqual(cfg_with().missing_bench_env("daytona"),
                         ["GENTAR_DAYTONA_API_KEY"])
        cfg = cfg_with(GENTAR_DAYTONA_API_KEY="k")
        self.assertEqual(cfg.missing_bench_env("daytona"), [])

    def test_unknown_kind_is_refused_here_not_by_make_bench(self):
        # Deferring to make_bench was wrong: reaching it means the
        # refusal path was skipped, so a typo in a scenario's `bench =`
        # surfaced as a BenchHostError traceback with exit 1 — a TEST
        # FAILURE verdict for a misconfigured run, and the wrong exit
        # code for the contract (config errors are exit 2, before any
        # bench exists).
        missing = cfg_with().missing_bench_env("nope")
        self.assertEqual(len(missing), 1)
        self.assertIn("nope", missing[0])
        # The message names the tiers that DO exist, so the typo is
        # obvious without reading the source.
        for known in ("sbx", "tart", "osb", "daytona"):
            self.assertIn(known, missing[0])

    def test_every_tier_make_bench_knows_has_a_policy(self):
        # A fifth tier added without an entry here would silently get
        # the old fall-back behaviour back.
        self.assertEqual(set(BENCH_REQUIREMENTS),
                         {"sbx", "tart", "osb", "daytona"})


class RefusalTest(unittest.TestCase):
    """The verdict: exit 2, the vars named, and no bench created."""

    def run_smoke(self, cfg, scenario="smoke"):
        """coordinator.run with the bench factory booby-trapped: the
        guard must return before anything tries to build a bench."""
        printed = []
        with mock.patch.object(coord, "make_bench",
                               side_effect=AssertionError(
                                   "bench created despite refusal")), \
             mock.patch.object(coord, "Spans"), \
             mock.patch("builtins.print", side_effect=printed.append):
            rc = coord.run(scenario, cfg)
        return rc, "\n".join(str(p) for p in printed)

    def test_unset_refuses_with_exit_2(self):
        rc, out = self.run_smoke(cfg_with(GENTAR_REPORT_DIR=""))
        self.assertEqual(rc, 2)

    def test_refusal_names_both_missing_vars(self):
        _, out = self.run_smoke(cfg_with(GENTAR_REPORT_DIR=""))
        self.assertIn("GENTAR_BENCH_HOST", out)
        self.assertIn("GENTAR_BENCH_USER", out)

    def test_refusal_points_at_the_template(self):
        _, out = self.run_smoke(cfg_with(GENTAR_REPORT_DIR=""))
        self.assertIn(".env.example", out)

    def test_refusal_names_only_what_is_missing(self):
        cfg = cfg_with(GENTAR_BENCH_HOST="bench.example.internal",
                       GENTAR_REPORT_DIR="")
        _, out = self.run_smoke(cfg)
        self.assertIn("GENTAR_BENCH_USER", out)
        self.assertNotIn("GENTAR_BENCH_HOST", out)

    def test_configured_reaches_the_bench_factory(self):
        # The other half of "refuse, not fall back": once configured,
        # the guard is transparent. make_bench raising IS the proof the
        # run got past the guard.
        cfg = cfg_with(GENTAR_BENCH_HOST="bench.example.internal",
                       GENTAR_BENCH_USER="bench", GENTAR_REPORT_DIR="")
        with self.assertRaises(AssertionError) as caught:
            self.run_smoke(cfg)
        self.assertIn("bench created despite refusal", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class RefusalPathCoverageTest(unittest.TestCase):
    """The refusal SURFACE, not one guard.

    Three release-blocking defects shipped past a fully green board
    (7/7 local, 6/6 CI) because no gate suite ever takes a refusal
    path: an unknown bench tier crashed with a traceback and exit 1
    instead of refusing, agent suites could not run at all because the
    wrapper forwarded no credentials, and a missing key file aborted
    the script silently. Every one is exit-2 territory, and none of it
    was executed by anything that gates a release.

    A green board that never exercises the failure modes is a board
    that cannot see them. These cases run the real coordinator.run for
    each refusal, with the bench factory booby-trapped so 'refused
    before any bench exists' is asserted rather than assumed.
    """

    def run_refusing(self, cfg, scenario):
        printed = []
        with mock.patch.object(coord, "make_bench",
                               side_effect=AssertionError(
                                   "bench created despite refusal")), \
             mock.patch.object(coord, "Spans"), \
             mock.patch("builtins.print", side_effect=printed.append):
            rc = coord.run(scenario, cfg)
        return rc, "\n".join(str(p) for p in printed)

    def configured(self, **extra):
        """A fully configured sbx install — so anything refused here is
        refused for the reason under test, not for a missing host."""
        env = {"GENTAR_BENCH_HOST": "bench.example.internal",
               "GENTAR_BENCH_USER": "bench", "GENTAR_REPORT_DIR": ""}
        env.update(extra)
        return cfg_with(**env)

    def test_unknown_tier_refuses_instead_of_crashing(self):
        # Was: BenchHostError traceback, exit 1 — a TEST FAILURE verdict
        # for a typo in `bench =`, and the wrong code for the contract.
        cfg = self.configured(GENTAR_BENCH_KIND="typo-tier")
        rc, out = self.run_refusing(cfg, "smoke")
        self.assertEqual(rc, 2)
        self.assertIn("typo-tier", out)

    def test_unknown_tier_names_the_tiers_that_exist(self):
        cfg = self.configured(GENTAR_BENCH_KIND="typo-tier")
        _, out = self.run_refusing(cfg, "smoke")
        for known in BENCH_REQUIREMENTS:
            self.assertIn(known, out)

    def test_unknown_scenario_refuses(self):
        # The other name-level refusal: an unknown suite must not spend
        # a bench discovering it does not exist.
        rc, _ = self.run_refusing(self.configured(), "no-such-suite")
        self.assertEqual(rc, 2)

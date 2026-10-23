"""Suites that can fail (ground-up review A8): each runs its real command text
in /bin/sh against fakes, and a broken subject turns it red.

- SC03: memhouse-house's counts accepted any HTTP error body holding a "3",
  and its steps and `stats` check exited with `tail`'s status;
  memhouse-install read a failing `--print-sql` as "no-use", a pass.
- SC07: kommander-update seeded nothing and checked only that data/tasks and
  data/todos existed, so an update that emptied them passed.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from gentar.asserts import check_commands
from gentar.toml_scenario import TomlScenario

# coordinator/scenarios in a checkout, /app/scenarios in the image
SCEN = Path(__file__).resolve().parents[1] / "scenarios"

FAKE_CURL = """#!/bin/sh
case "$FAKE_CURL" in
  error) echo "Code: 516. DB::Exception: Authentication failed. (version 24.3.3)"; exit 22 ;;
  three) echo 3 ;;
  thirteen) echo 13 ;;
  user) id -un ;;
esac
"""
FAKE_MEMHOUSE = """#!/bin/sh
[ "$FAKE_MEMHOUSE" = fail ] && { echo "memhouse: cannot reach the house"; exit 1; }
case "$1 $2" in
  "install --print-sql")
    [ "$FAKE_MEMHOUSE" = use ] && echo "USE memory;"
    echo "CREATE TABLE IF NOT EXISTS memory.sessions (user_id String MATERIALIZED currentUser())" ;;
  *) echo "memhouse ok" ;;
esac
"""
FAKE_NPM = """#!/bin/sh
[ "$FAKE_NPM" = fail ] && { echo "npm ERR! 404"; exit 1; }
echo "added 1 package"
"""


class Shell:
    """A bench whose commands run in /bin/sh, as a real bench runs them."""

    def __init__(self, env):
        self.env = env

    def exec(self, sandbox, command, timeout=300, env=None):
        r = subprocess.run(["/bin/sh", "-c", command], env={**self.env, **(env or {})},
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr


class SuiteTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for name, text in (("curl", FAKE_CURL), ("memhouse", FAKE_MEMHOUSE), ("npm", FAKE_NPM)):
            (bindir / name).write_text(text)
            (bindir / name).chmod(0o755)
        self.home = self.tmp / "home"
        (self.home / ".memhouse").mkdir(parents=True)
        (self.home / ".memhouse" / "env").write_text(
            "MEMHOUSE_URL=http://127.0.0.1:1\nMEMHOUSE_DB=memory\n"
            "MEMHOUSE_USER=u\nMEMHOUSE_PASSWORD=p\n")
        self.env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(self.home),
                    "WORKSPACE_DIR": str(self.tmp / "ws")}

    def ok(self, command, contains=None, **env):
        [r] = check_commands(Shell({**self.env, **env}), "s",
                             [{"command": command, "contains": contains}])
        return r.ok

    def step(self, command, **env):
        return Shell({**self.env, **env}).exec("s", command)[0]


class MemhouseHouseTest(SuiteTest):

    def setUp(self):
        super().setUp()
        self.sc = TomlScenario(SCEN / "memhouse-house.toml")

    def count_checks(self):
        return [c for c in self.sc.commands if "count()" in c["command"]]

    def test_a_count_needs_an_http_success_and_exactly_three(self):
        checks = self.count_checks()
        self.assertEqual(len(checks), 2)
        for c in checks:
            with self.subTest(check=c["contains"]):
                self.assertTrue(self.ok(c["command"], c["contains"], FAKE_CURL="three"))
                self.assertFalse(self.ok(c["command"], c["contains"], FAKE_CURL="error"))
                self.assertFalse(self.ok(c["command"], c["contains"], FAKE_CURL="thirteen"))

    def test_the_user_check_needs_an_http_success(self):
        [c] = [c for c in self.sc.commands if "currentUser()" in c["command"]
               and "count()" not in c["command"]]
        self.assertTrue(self.ok(c["command"], c["contains"], FAKE_CURL="user"))
        self.assertFalse(self.ok(c["command"], c["contains"], FAKE_CURL="error"))

    def test_a_failing_producer_fails_its_step_or_check(self):
        for i, s in enumerate(self.sc.steps):
            with self.subTest(step=i):
                self.assertEqual(self.step(s), 0)
                self.assertNotEqual(self.step(s, FAKE_NPM="fail", FAKE_MEMHOUSE="fail"), 0)
        [stats] = [c for c in self.sc.commands if "memhouse stats" in c["command"]]
        self.assertTrue(self.ok(stats["command"]))
        self.assertFalse(self.ok(stats["command"], FAKE_MEMHOUSE="fail"))


class MemhouseInstallTest(SuiteTest):

    def test_a_failing_print_sql_is_a_failure_not_no_use(self):
        sc = TomlScenario(SCEN / "memhouse-install.toml")
        [c] = [c for c in sc.commands if "^USE " in c["command"]]
        self.assertTrue(self.ok(c["command"], c["contains"]))
        self.assertFalse(self.ok(c["command"], c["contains"], FAKE_MEMHOUSE="use"))
        self.assertFalse(self.ok(c["command"], c["contains"], FAKE_MEMHOUSE="fail"))
        self.assertNotEqual(self.step(sc.steps[0], FAKE_NPM="fail"), 0)


class KommanderUpdateTest(SuiteTest):
    """The seed step and the survival check, around an update that keeps
    everything, then around updates that lose one thing each."""

    def setUp(self):
        super().setUp()
        sc = TomlScenario(SCEN / "kommander-update.toml")
        self.seed = next(s for s in sc.steps if "gentar-seed" in s)
        [self.check] = [c for c in sc.commands if c.get("contains") == "data-survived"]
        self.kp = self.home / "kp-old"
        (self.kp / "data" / "tasks").mkdir(parents=True)
        (self.kp / "settings.json").write_text('{\n  "hooks": {}\n}\n')
        self.assertEqual(self.step(self.seed, GENTAR_RUN_ID="run-7"), 0)

    def survived(self):
        return self.ok(self.check["command"], self.check["contains"])

    def test_an_update_that_keeps_everything_passes(self):
        self.assertTrue(self.survived())
        import json
        self.assertEqual(json.loads((self.kp / "settings.json").read_text()),
                         {"gentarSeed": "run-7", "hooks": {}})

    def test_an_update_that_loses_anything_fails(self):
        losses = {
            "emptied task": lambda: (self.kp / "data/tasks/gentar-seed/TASK.md").write_text(""),
            "lost todo": lambda: (self.kp / "data/todos/gentar-seed.md").unlink(),
            "reset settings": lambda: (self.kp / "settings.json").write_text('{"hooks": {}}\n'),
            "recreated data/": lambda: (shutil.rmtree(self.kp / "data"),
                                        (self.kp / "data/tasks").mkdir(parents=True),
                                        (self.kp / "data/todos").mkdir()),
        }
        for what, lose in losses.items():
            with self.subTest(loss=what):
                self.setUp()
                lose()
                self.assertFalse(self.survived())

    def test_the_seed_refuses_a_settings_file_it_cannot_extend(self):
        (self.kp / "settings.json").write_text('[]\n')
        self.assertNotEqual(self.step(self.seed, GENTAR_RUN_ID="run-8"), 0)


if __name__ == "__main__":
    unittest.main()

"""GENTAR_BENCH_WORKSPACE_ROOT reaches the coordinator in SSH mode too.

2026-10-09 (D5, via agent-realm-lead): docker-compose.yml forwarded the
workspace root only in local mode (compose.local-bench.yml). In SSH mode the
coordinator always used config.py's default while bin/bench-reap followed
the caller's shell, so an arena whose bench user has its own root made its
workspaces in the shared one. The compose default is config.py's, behind
`:-`, because config._opt treats an EMPTY value as set.

Checked through `docker compose config`, i.e. compose's own interpolation,
with the caller's environment and an empty .env.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DEFAULT = "/tmp/gentar-workspaces"


def _compose_available():
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    return r.returncode == 0


@unittest.skipUnless(COMPOSE.exists() and _compose_available(),
                     "needs docker-compose.yml and the docker compose CLI (no daemon)")
class WorkspaceRootTest(unittest.TestCase):

    def coordinator_env(self, **env):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "empty.env").write_text("")
        e = {k: v for k, v in os.environ.items() if not k.startswith("GENTAR_")}
        e.update(GENTAR_BENCH_KEY_FILE=os.devnull, **env)
        r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "--env-file", str(tmp / "empty.env"),
                            "config", "--format", "json"], capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["services"]["coordinator"]["environment"]

    def test_a_custom_root_reaches_the_coordinator_in_ssh_mode(self):
        env = self.coordinator_env(GENTAR_BENCH_HOST="bench.example", GENTAR_BENCH_USER="arena",
                                   GENTAR_BENCH_WORKSPACE_ROOT="/tmp/gentar-workspaces-arena")
        self.assertEqual(env["GENTAR_BENCH_WORKSPACE_ROOT"], "/tmp/gentar-workspaces-arena")

    def test_unset_and_empty_fall_back_to_the_default(self):
        self.assertEqual(self.coordinator_env()["GENTAR_BENCH_WORKSPACE_ROOT"], DEFAULT)
        self.assertEqual(self.coordinator_env(GENTAR_BENCH_WORKSPACE_ROOT="")["GENTAR_BENCH_WORKSPACE_ROOT"],
                         DEFAULT)


class WorkspaceRootDefaultsAgreeTest(unittest.TestCase):
    """The compose default, config.py's and bin/bench-reap's are one value."""

    def test_one_default_everywhere(self):
        text = COMPOSE.read_text()
        self.assertIn(f"GENTAR_BENCH_WORKSPACE_ROOT: ${{GENTAR_BENCH_WORKSPACE_ROOT:-{DEFAULT}}}", text)
        config = (ROOT / "coordinator" / "gentar" / "config.py").read_text()
        self.assertIn(f'"GENTAR_BENCH_WORKSPACE_ROOT", "{DEFAULT}"', config)
        reap = ROOT / "bin" / "bench-reap"
        if reap.exists():
            self.assertIn(f"${{GENTAR_BENCH_WORKSPACE_ROOT:-{DEFAULT}}}", reap.read_text())


if __name__ == "__main__":
    unittest.main()

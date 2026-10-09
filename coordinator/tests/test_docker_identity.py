"""Local bench mode on rootless Docker: one daemon, and a uid it decides.

2026-10-09 (D5 step 6; AK47's conditions, root's decision W2(a)):

- rootless Docker: the local coordinator runs as 0:0, which there IS the
  host user (the user's own uid maps to a subordinate uid owning nothing);
- rootful Docker: as the user (id -u / id -g), as before; never 0:0, so
  local mode AS root on rootful Docker is refused;
- cannot tell (`docker info` fails, times out, or says something
  unparseable): refused. Nothing in the environment can force 0:0.
- the same daemon throughout: the rootless check, every later docker call
  (DOCKER_HOST exported), and the socket mounted into a container
  (GENTAR_DOCKER_SOCK) all resolve to one endpoint; a pinned socket that is
  not it is refused.

bin/docker-identity decides; bin/arena and the kit's run.sh only read it.
Fakes: `docker` (context inspect, info, compose) and `id` on PATH.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IDENT = ROOT / "bin" / "docker-identity"
ARENA = ROOT / "bin" / "arena"
KIT_RUN = ROOT / "subject-template" / "gentar" / "run.sh"

ROOTLESS = '["name=seccomp,profile=builtin","name=rootless","name=cgroupns"]'
ROOTFUL = '["name=apparmor","name=seccomp,profile=builtin","name=cgroupns"]'
USER_SOCK = "/run/user/1001/docker.sock"

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FIX/docker.calls"
case "$1 $2" in
  "context inspect")
    [ -n "${FAKE_CONTEXT_HOST:-}" ] || exit 1
    echo "$FAKE_CONTEXT_HOST"; exit 0 ;;
esac
if [ "$1" = -H ] && [ "$3" = info ]; then
  case "${FAKE_INFO_MODE:-print}" in
    fail) exit 1 ;;
    sleep) sleep 30; exit 0 ;;
    print) printf '%s\n' "$FAKE_INFO"; exit 0 ;;
  esac
fi
if [ "$1" = compose ]; then
  echo "compose uid=${GENTAR_LOCAL_UID:-} gid=${GENTAR_LOCAL_GID:-} sock=${GENTAR_DOCKER_SOCK:-} host=${DOCKER_HOST:-}" >> "$FIX/compose.env"
fi
exit 0
"""

FAKE_ID = r"""#!/bin/sh
case "$1" in
  -u) echo "${FAKE_UID:-1000}" ;;
  -g) echo "${FAKE_GID:-1000}" ;;
  -un) echo arena ;;
  *) exec /usr/bin/id "$@" ;;
esac
"""


class Fakes:
    def __init__(self, tmp):
        self.tmp = tmp
        self.fix = tmp / "fix"
        self.fix.mkdir()
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for name, body in (("docker", FAKE_DOCKER), ("id", FAKE_ID), ("sbx", "#!/bin/sh\nexit 0\n")):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("GENTAR_", "DOCKER_", "FAKE_"))}
        e.update(PATH=f"{self.bin}:{os.environ['PATH']}", FIX=str(self.fix))
        e.update(extra)
        return e

    def calls(self, name):
        f = self.fix / name
        return f.read_text().splitlines() if f.exists() else []


@unittest.skipUnless(IDENT.exists(), "bin/ is not in the image build context")
class DockerIdentityTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.f = Fakes(self.tmp)

    def ident(self, *args, **env):
        r = subprocess.run(["/bin/bash", str(IDENT), *args], env=self.f.env(**env),
                           capture_output=True, text=True, timeout=60)
        out = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        return r, out

    def refused(self, words, *args, **env):
        r, out = self.ident(*args, **env)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("uid", out)
        self.assertIn(words, r.stderr)
        return r

    # 1. rootless: 0:0, and the socket is the daemon's own
    def test_rootless_runs_as_root_of_its_own_daemon(self):
        r, out = self.ident("--local", DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO=ROOTLESS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, {"host": f"unix://{USER_SOCK}", "sock": USER_SOCK,
                               "rootless": "yes", "uid": "0", "gid": "0"})
        self.assertIn(f"-H unix://{USER_SOCK} info --format {{{{json .SecurityOptions}}}}",
                      self.f.calls("docker.calls"))

    def test_rootless_through_the_current_context(self):
        r, out = self.ident("--local", FAKE_CONTEXT_HOST=f"unix://{USER_SOCK}", FAKE_INFO=ROOTLESS)
        self.assertEqual((r.returncode, out["sock"], out["uid"]), (0, USER_SOCK, "0"))

    # 2. rootful: today's uid, never 0:0
    def test_rootful_is_the_users_own_uid(self):
        r, out = self.ident("--local", FAKE_CONTEXT_HOST="unix:///var/run/docker.sock",
                            FAKE_INFO=ROOTFUL, FAKE_UID="1001", FAKE_GID="1001")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out, {"host": "unix:///var/run/docker.sock", "sock": "/var/run/docker.sock",
                               "rootless": "no", "uid": "1001", "gid": "1001"})

    def test_rootful_never_yields_0_0(self):
        # as root on rootful Docker: refused, not 0:0
        self.refused("would run the coordinator as real root", "--local",
                     FAKE_CONTEXT_HOST="unix:///var/run/docker.sock", FAKE_INFO=ROOTFUL, FAKE_UID="0")
        # an empty option list is rootful too
        r, out = self.ident("--local", FAKE_CONTEXT_HOST="unix:///var/run/docker.sock", FAKE_INFO="[]")
        self.assertEqual((r.returncode, out["uid"]), (0, "1000"))

    def test_only_an_exact_name_rootless_counts(self):
        for info in ('["name=rootless2"]', '["name=rootlessx,foo"]', '["xname=rootless"]',
                     '["name=seccomp,name=rootless"]', '["rootless"]', '["name=Rootless"]'):
            with self.subTest(info=info):
                r, out = self.ident("--local", DOCKER_HOST="unix:///var/run/docker.sock", FAKE_INFO=info)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual((out["rootless"], out["uid"]), ("no", "1000"))
        r, out = self.ident("--local", DOCKER_HOST=f"unix://{USER_SOCK}",
                            FAKE_INFO='["name=seccomp,profile=builtin", "name=rootless"]')
        self.assertEqual(out["uid"], "0")                    # spacing is fine

    def test_nothing_in_the_environment_forces_0_0(self):
        r, out = self.ident("--local", DOCKER_HOST="unix:///var/run/docker.sock", FAKE_INFO=ROOTFUL,
                            GENTAR_LOCAL_UID="0", GENTAR_LOCAL_GID="0", GENTAR_ROOTLESS="yes",
                            GENTAR_DOCKER_ROOTLESS="1", DOCKER_ROOTLESS="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((out["rootless"], out["uid"], out["gid"]), ("no", "1000", "1000"))
        r, _ = self.ident("--local", "--rootless", DOCKER_HOST="unix:///var/run/docker.sock",
                          FAKE_INFO=ROOTFUL)
        self.assertEqual(r.returncode, 2)                    # no flag either

    # 3. cannot tell: refused
    def test_docker_info_failing_refuses(self):
        self.refused("'docker info' failed or timed out", "--local",
                     DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO_MODE="fail")

    @unittest.skipUnless(shutil.which("timeout"), "needs coreutils timeout (any Linux runner)")
    def test_docker_info_hanging_refuses(self):
        self.refused("'docker info' failed or timed out", "--local", DOCKER_HOST=f"unix://{USER_SOCK}",
                     FAKE_INFO_MODE="sleep", GENTAR_DOCKER_INFO_TIMEOUT="1")

    def test_unparseable_output_refuses(self):
        for info in ("", "rootless", "[name=rootless]", '["name=rootless"', '"name=rootless"]',
                     'map[name:rootless]', '["name=rootless",]x'):
            with self.subTest(info=info):
                self.refused("unexpected 'docker info' output", "--local",
                             DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO=info)

    def test_a_daemon_that_is_not_a_unix_socket_refuses_local_mode(self):
        self.refused("needs a unix-socket Docker daemon", "--local", DOCKER_HOST="tcp://10.0.0.1:2375")
        self.refused("needs a unix-socket Docker daemon", "--local")      # no context either

    # the same daemon
    def test_a_pinned_socket_must_be_the_checked_daemon(self):
        self.refused("is not the daemon this run uses", "--local", DOCKER_HOST=f"unix://{USER_SOCK}",
                     GENTAR_DOCKER_SOCK="/var/run/docker.sock", FAKE_INFO=ROOTLESS)
        self.refused("is not the daemon this run uses", DOCKER_HOST=f"unix://{USER_SOCK}",
                     GENTAR_DOCKER_SOCK="/var/run/docker.sock")
        r, out = self.ident("--local", DOCKER_HOST=f"unix://{USER_SOCK}",
                            GENTAR_DOCKER_SOCK=USER_SOCK, FAKE_INFO=ROOTLESS)
        self.assertEqual((r.returncode, out["uid"]), (0, "0"))

    def test_outside_local_mode_the_rootful_default_is_unchanged(self):
        r, out = self.ident(FAKE_CONTEXT_HOST="unix:///var/run/docker.sock")
        self.assertEqual((r.returncode, out), (0, {"host": "unix:///var/run/docker.sock",
                                                   "sock": "/var/run/docker.sock"}))
        r, out = self.ident(DOCKER_HOST="tcp://10.0.0.1:2375")
        self.assertEqual((r.returncode, out), (0, {"sock": "/var/run/docker.sock"}))
        self.assertFalse([c for c in self.f.calls("docker.calls") if " info " in f" {c} "])


@unittest.skipUnless(ARENA.exists() and IDENT.exists(), "bin/ is not in the image build context")
class ArenaWrapperTest(unittest.TestCase):
    """bin/arena hands docker compose what docker-identity decided."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.f = Fakes(self.tmp)
        self.home = self.tmp / "home"
        for d in (".local/state/sandboxes", ".config/sandboxes", ".config/com.docker.sandboxes"):
            (self.home / d).mkdir(parents=True)

    def arena_down(self, **env):
        e = self.f.env(HOME=str(self.home), GENTAR_BENCH_HOST="local", GENTAR_SBX_AUTH_CHECK="off",
                       GENTAR_BENCH_WORKSPACE_ROOT=str(self.tmp / "ws"), **env)
        r = subprocess.run(["/bin/bash", str(ARENA), "down"], env=e, capture_output=True, text=True,
                           timeout=60)
        return r, self.f.calls("compose.env")

    def test_rootless_reaches_compose_as_0_0_on_the_user_socket(self):
        r, envs = self.arena_down(DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO=ROOTLESS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(envs)
        for line in envs:
            self.assertEqual(line, f"compose uid=0 gid=0 sock={USER_SOCK} host=unix://{USER_SOCK}")

    def test_rootful_reaches_compose_as_the_user_whatever_the_caller_set(self):
        r, envs = self.arena_down(FAKE_CONTEXT_HOST="unix:///var/run/docker.sock", FAKE_INFO=ROOTFUL,
                                  GENTAR_LOCAL_UID="0", GENTAR_LOCAL_GID="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(envs)
        for line in envs:
            self.assertEqual(line, "compose uid=1000 gid=1000 sock=/var/run/docker.sock "
                                   "host=unix:///var/run/docker.sock")

    def test_cannot_tell_refuses_before_any_compose(self):
        r, envs = self.arena_down(DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO_MODE="fail")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(envs, [])
        self.assertIn("will not guess", r.stderr)


@unittest.skipUnless(KIT_RUN.exists(), "the kit is not in the image build context")
class KitRunShTest(unittest.TestCase):
    """The kit's run.sh reads the same script, from the staged engine."""

    def test_the_kit_takes_the_uid_and_socket_from_the_engines_script(self):
        text = KIT_RUN.read_text()
        self.assertNotIn("GENTAR_LOCAL_UID=$(id -u)", text)
        self.assertIn('ident=$("$ARENA/bin/docker-identity" --local) || exit 2', text)
        self.assertIn('GENTAR_LOCAL_UID=$(ident_get uid); GENTAR_LOCAL_GID=$(ident_get gid)', text)
        self.assertIn('export GENTAR_DOCKER_SOCK; GENTAR_DOCKER_SOCK=$(ident_get sock)', text)
        self.assertIn("needs an engine with bin/docker-identity", text)
        block = text[text.index("One Docker daemon for the whole run"):text.index("# Telemetry destination")]
        code = [l for l in block.splitlines() if not l.lstrip().startswith("#")]
        self.assertFalse([l for l in code if "eval" in l.split()], code)

    def test_the_compose_files_mount_the_resolved_socket(self):
        for f in ("docker-compose.yml", "compose.rm.yml"):
            text = (ROOT / f).read_text()
            with self.subTest(file=f):
                self.assertIn("${GENTAR_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock", text)
                self.assertNotIn("- /var/run/docker.sock:/var/run/docker.sock", text)


RUN_DOCKER = r"""#!/usr/bin/env bash
# a fake docker for the kit's run path: identity answers, services up and
# healthy, and a coordinator run that records what compose was handed
printf '%s\n' "$*" >> "$FIX/docker.calls"
case "$1 $2" in
  "context inspect") [ -n "${FAKE_CONTEXT_HOST:-}" ] || exit 1; echo "$FAKE_CONTEXT_HOST"; exit 0 ;;
esac
if [ "$1" = -H ] && [ "$3" = info ]; then
  [ "${FAKE_INFO_MODE:-print}" = fail ] && exit 1
  printf '%s\n' "$FAKE_INFO"; exit 0
fi
case "$1" in ps) echo cid1; exit 0 ;; inspect) echo healthy; exit 0 ;; esac
args=" $* "
case "$args" in
  *" compose "*" run "*" coordinator run "*)
    echo "coordinator uid=${GENTAR_LOCAL_UID:-} gid=${GENTAR_LOCAL_GID:-} sock=${GENTAR_DOCKER_SOCK:-} host=${DOCKER_HOST:-}" >> "$FIX/compose.env"
    mkdir -p out; sleep 1; echo 'Reproduce: `x`' > "out/report-x-$$.md"; exit 0 ;;
  *" compose "*" run "*" dashboard "*) exit 1 ;;
esac
exit 0
"""


@unittest.skipUnless(KIT_RUN.exists() and IDENT.exists() and shutil.which("git"),
                     "the kit and bin/ are not in the image build context")
class KitRunPathTest(unittest.TestCase):
    """The kit's run.sh in local mode, on its real path to the coordinator."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.f = Fakes(self.tmp)
        (self.f.bin / "docker").write_text(RUN_DOCKER)
        eng = self.tmp / "engine"
        (eng / "bin").mkdir(parents=True)
        shutil.copy(IDENT, eng / "bin" / "docker-identity")
        shutil.copy(ROOT / "compose.local-bench.yml", eng / "compose.local-bench.yml")
        (eng / ".env.example").write_text("")
        (eng / "bin" / "redact").write_text("#!/bin/sh\nexit 0\n")
        for x in ("docker-identity", "redact"):
            (eng / "bin" / x).chmod(0o755)
        g = lambda *a: subprocess.run(["git", "-C", str(eng), *a], check=True, capture_output=True,
                                      env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        g("init", "-q", "-b", "main"); g("add", "-A"); g("commit", "-q", "-m", "engine")
        self.engine = eng
        self.home = self.tmp / "home"
        for d in (".local/state/sandboxes", ".config/sandboxes", ".config/com.docker.sandboxes"):
            (self.home / d).mkdir(parents=True)
        self.repo = self.tmp / "repo"
        shutil.copytree(KIT_RUN.parent, self.repo / "gentar")
        shutil.rmtree(self.repo / "gentar" / "scenarios")
        (self.repo / "gentar" / "scenarios").mkdir()
        (self.repo / "gentar" / "scenarios" / "s.toml").write_text(
            '[scenario]\nsubject = "x"\n[oracle]\nsteps = ["true"]\n')
        (self.repo / "gentar" / "policy.toml").unlink(missing_ok=True)

    def run_sh(self, **env):
        e = self.f.env(HOME=str(self.home), GENTAR_BENCH_HOST="local", GENTAR_SBX_AUTH_CHECK="off",
                       GENTAR_REPO_URL=str(self.engine), GENTAR_REF="main",
                       GENTAR_LOCK_DIR=str(self.tmp), GENTAR_BENCH_WORKSPACE_ROOT=str(self.tmp / "ws"),
                       **env)
        r = subprocess.run(["/bin/bash", "gentar/run.sh", "s"], cwd=self.repo, env=e,
                           capture_output=True, text=True, timeout=120)
        return r, self.f.calls("compose.env")

    def test_rootless(self):
        r, envs = self.run_sh(DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO=ROOTLESS)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertEqual(envs, [f"coordinator uid=0 gid=0 sock={USER_SOCK} host=unix://{USER_SOCK}"])

    def test_rootful_whatever_the_caller_set(self):
        r, envs = self.run_sh(FAKE_CONTEXT_HOST="unix:///var/run/docker.sock", FAKE_INFO=ROOTFUL,
                              GENTAR_LOCAL_UID="0", GENTAR_LOCAL_GID="0")
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertEqual(envs, ["coordinator uid=1000 gid=1000 sock=/var/run/docker.sock "
                                "host=unix:///var/run/docker.sock"])

    def test_cannot_tell_refuses_before_the_coordinator(self):
        r, envs = self.run_sh(DOCKER_HOST=f"unix://{USER_SOCK}", FAKE_INFO_MODE="fail")
        self.assertEqual(r.returncode, 2, r.stderr[-1500:])
        self.assertEqual(envs, [])
        self.assertIn("will not guess", r.stderr)

    def test_an_engine_without_the_script_refuses_local_mode(self):
        subprocess.run(["git", "-C", str(self.engine), "rm", "-q", "bin/docker-identity"], check=True)
        subprocess.run(["git", "-C", str(self.engine), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", "old engine"], check=True)
        r, envs = self.run_sh(FAKE_CONTEXT_HOST="unix:///var/run/docker.sock", FAKE_INFO=ROOTFUL)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(envs, [])
        self.assertIn("needs an engine with bin/docker-identity", r.stderr)


if __name__ == "__main__":
    unittest.main()

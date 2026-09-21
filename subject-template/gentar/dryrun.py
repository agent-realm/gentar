#!/usr/bin/env python3
"""Run an own-arena scenario locally, without a bench.

    gentar/dryrun.py gentar/scenarios/first-suite.toml
    gentar/dryrun.py gentar/scenarios/*.toml        # sweep
    gentar/dryrun.py                                # every suite

Why this exists: a scenario is shell, and shell in TOML is three levels of
quoting deep. The arena is the only thing that ever runs these, at the cost
of a bench VM and several minutes per suite -- so a missing quote cost a
full round trip to find. This executes the same steps, the same driver turns
and the same assertions in a scratch HOME, in about a second, and fails the
same way.

What it is NOT: a bench. There is no sandbox, no template, no network policy,
no real agent. It proves the shell and the assertions; the arena still proves
the isolation. Suites declaring `credentials` are skipped -- they need a real
agent and a real key.

Two adaptations live at the top of the file (the only edits most subjects
need):

  prepare(env)      called once before the sweep; build your CLI or stage
                    fixtures into the scratch HOME here
  SKIP_STEP_SUBSTR  substrings of [oracle].steps that prepare() already
                    covered locally (e.g. "docker build"), skipped verbatim

One difference from the bench has bitten before, so expect more of its kind:
the scratch HOME always has a stub `claude` on PATH, and a default bench has
none. A suite that depends on an agent EXISTING must put the stub on PATH
itself rather than inherit it from this harness.

Genericized from the reference subject (claude-playbooks/gentar).
"""
import os, pty, re, select, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Engine resolution order: an explicit override, the same pinned clone
# run.sh makes (gentar/.arena — run run.sh once and this stays on the
# pinned engine), then a plain checkout of agent-realm/gentar.
_engine_env = os.environ.get("GENTAR_ENGINE")
_here = Path(__file__).resolve().parent
_CANDIDATES = [_here / ".arena/coordinator",
               Path.home() / "agent-realm/gentar/coordinator"]
ENGINE = (Path(_engine_env) if _engine_env
          else next((c for c in _CANDIDATES if c.exists()), _CANDIDATES[1]))
if not ENGINE.exists():
    sys.exit(f"gentar engine not found at {ENGINE} "
             "(run gentar/run.sh once, or set GENTAR_ENGINE, "
             "or clone agent-realm/gentar)")
sys.path.insert(0, str(ENGINE))

# tomllib is 3.11+. Stock macOS ships 3.9, so rather than fail on the default
# interpreter, re-exec under the first newer one on PATH.
if sys.version_info < (3, 11):
    for candidate in ("python3.14", "python3.13", "python3.12", "python3.11"):
        if shutil.which(candidate):
            os.execvp(candidate, [candidate, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit(f"needs python 3.11+ for tomllib; this is {sys.version.split()[0]} "
             "and no newer python3.1x was found on PATH")

from gentar.toml_scenario import TomlScenario

# Steps whose substring appears here are skipped verbatim (prepare()
# already did the equivalent locally). Example: ("docker build",).
SKIP_STEP_SUBSTR = ()


def prepare(env: dict) -> None:
    """Build/stage whatever the suites need; runs once per sweep.

    The default subject needs nothing. If your scenarios assume a built
    binary or generated fixtures, do it here (REPO is the checkout;
    env["HOME"] is the scratch pilot home the steps will run under).
    """
    return None


def scratch_home() -> str:
    home = tempfile.mkdtemp(prefix="dryrun-home-")
    bindir = Path(home, ".local/bin")
    bindir.mkdir(parents=True)
    # The bench template ships a real claude; here a stub stands in.
    # Scenarios needing to observe what a launch handed it install
    # their own.
    (bindir / "claude").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(bindir / "claude", 0o755)
    return home


def stage_subject(home: str) -> None:
    """Copy the repo into the scratch home, as the bench does.

    In the arena, oracle pushes the staged subject INTO the bench
    workspace, so $WORKSPACE_DIR contains the checkout at its root and
    steps can write alongside it without dirtying anything real. The
    same must hold here or a suite that passes locally and fails in the
    bench (or worse, the reverse) is a harness lie. .git, the engine
    clone and old reports stay out — dead weight on the bench too.
    """
    def skip(directory, contents):
        d = Path(directory)
        if d == REPO:
            return [".git"]
        if d == REPO / "gentar":
            return [c for c in contents if c in (".arena", "reports")]
        return []
    shutil.copytree(REPO, home, dirs_exist_ok=True, symlinks=True,
                    ignore=skip)


def run_one(path: Path, env: dict, home: str) -> int:
    sc = TomlScenario(path)
    if sc.credentials:
        print(f"{path.name}: SKIPPED (declares credentials; needs a real agent)")
        return 0
    fails, log = 0, []
    sh = lambda c: subprocess.run(["sh", "-c", c], env=env, cwd=home,
                                  capture_output=True, text=True)

    for i, step in enumerate(sc.steps):
        if any(s in step for s in SKIP_STEP_SUBSTR):
            continue
        r = sh(step)
        if r.returncode:
            fails += 1
            log.append(f"  step {i} EXIT {r.returncode}\n    {step[:160]}\n    {(r.stderr or r.stdout).strip()[:300]}")

    if sc.driver_command:
        fails += drive(sc, env, home, log)

    for f in sc.files:
        p = f["path"].replace("~", home, 1) if f["path"].startswith("~") else f["path"]
        if not os.path.lexists(p):
            fails += 1
            log.append(f"  file MISSING {f['path']}")

    for i, c in enumerate(sc.commands):
        r = sh(c["command"])
        ok = r.returncode == 0 and c.get("contains", "") in (r.stdout + r.stderr)
        if not ok:
            fails += 1
            want = f"  (wanted {c['contains']!r})" if "contains" in c else ""
            log.append(f"  verify {i} FAIL{want}\n    {c['command'][:180]}\n    {(r.stdout + r.stderr).strip()[:300] or '(no output)'}")

    print(f"{path.name}: {'ALL PASS' if not fails else f'{fails} FAILURES'}")
    for line in log:
        print(line)
    if fails:
        print(f"  (home kept for inspection: {home})")
    return fails


def drive(sc, env, home, log) -> int:
    """Replay [driver].turns over a pty, as gentar/scripted.py does."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(home)
        os.execvpe("sh", ["sh", "-c", sc.driver_command], env)
    buf, fails = "", 0

    def pump(pattern, timeout):
        nonlocal buf
        rx, end = re.compile(pattern, re.IGNORECASE), time.time() + timeout
        while time.time() < end:
            if rx.search(buf):
                return True
            if select.select([fd], [], [], 0.4)[0]:
                try:
                    chunk = os.read(fd, 4096).decode(errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
        return bool(rx.search(buf))

    for i, t in enumerate(sc.turns):
        kind = t["type"]
        if kind == "answer":
            ok = pump(t["prompt"], t.get("timeout", 60))
            if ok:
                os.write(fd, (t.get("send", "") + "\n").encode())
                buf = ""   # consumed, so the next turn matches a fresh prompt
            if not ok:
                log.append(f"  turn {i} answer /{t['prompt']}/: prompt never appeared")
        elif kind == "expect":
            ok = pump(t["pattern"], t.get("timeout", 60))
            if not ok:
                log.append(f"  turn {i} expect /{t['pattern']}/: pattern never appeared")
        else:
            ok = True
            log.append(f"  turn {i}: type {kind!r} not replayed locally (arena only)")
        if not ok:
            fails += 1
    try:
        while select.select([fd], [], [], 1.0)[0]:
            if not os.read(fd, 4096):
                break
    except OSError:
        pass
    os.waitpid(pid, 0)
    return fails


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]] or sorted((REPO / "gentar/scenarios").glob("*.toml"))
    home = scratch_home()
    stage_subject(home)
    env = dict(os.environ, HOME=home, WORKSPACE_DIR=home,
               PATH=f"{home}/.local/bin:" + os.environ["PATH"])
    prepare(env)
    return 1 if sum(run_one(p, env, home) for p in paths) else 0


if __name__ == "__main__":
    sys.exit(main())

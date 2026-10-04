"""Bench hosts — where scenarios run. Four implementations behind one
interface (decisions of record, gentar TASK.md 2026-08-18, 2026-09-04,
2026-09-15):

- ``SbxBenchHost``: sbx sandboxes on a Linux bench-host (the default
  tier). The coordinator drives sbx over ssh; each bench is a per-run
  sandbox with the workspace bind-mounted in.
- ``TartBenchHost``: tart VMs on an Apple-Silicon Mac host (the macOS
  tier). ``tart clone`` from a local template VM, headless ``tart run``,
  commands over ssh into the guest — jumping through the tart host,
  because the guest's vmnet subnet is only routed on the Mac itself.
  The tart VM *is* the bench; nothing nests inside it.
- ``OpenSandboxBenchHost``: OpenSandbox containers behind an
  opensandbox-server (the docker-runtime lifecycle server). Fourth wall
  between arena and substrate: the server owns container lifecycle and
  its execd daemon owns exec/files/pty, so this host is the python SDK
  as transport (the osb CLI drops real exit codes — `exit 7` reads 1)
  and gentar's osb_pty_bridge as the pty transport (execd's /pty
  WebSocket behind its per-sandbox host port).
- ``DaytonaBenchHost``: Daytona cloud sandboxes (daytona.io). Lifecycle
  via the daytona SDK; command/pty transport is ssh with a per-sandbox
  expiring token as the username (``ssh <token>@ssh.app.daytona.io``) —
  the same ssh shape as tart, so exec/push/pty reuse that pattern. The
  bench is an image ref (tag or digest, no ``latest``); sandboxes are
  named ``gentar-<name>`` for ``exists``.

Interface every runner (oracle, scripted, pty driver) codes against:
create / exec / push_dir / rm / exists / workspace / template_digest /
pty_spawn_args. ``make_bench(cfg, kind)`` is the factory.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from gentar.config import Config


class BenchHostError(RuntimeError):
    pass


# Credential SHAPES, masked in bench-host output before it becomes an error.
# The run's redaction is value-based (it masks what the run knows), and the
# host's sbx login is in no variable the run knows; an error text reaches the
# CI log, the report artifact and the spans, so a token sbx ever printed
# would go everywhere. Shapes, not values: a false positive costs a word.
_Q = r"""["']"""     # either quote: JSON and Python reprs both reach error text
_TOKEN_KEYS = (r"access_token|refresh_token|id_token|identity_?token|registry_?token|"
               r"token|auth|password|passwd|secret|client_secret|api_?key|authorization|"
               r"x-registry-auth")
_TOKEN_SHAPES = [
    # "key": "value" / 'key': 'value' (JSON, Python dicts; escaped quotes kept inside)
    (re.compile(rf"(?i)({_Q}(?:{_TOKEN_KEYS}){_Q}\s*:\s*)(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"), "field"),
    # header lines: Authorization / Proxy-Authorization / X-Registry-Auth, any scheme
    (re.compile(r"(?i)\b((?:proxy-)?authorization|x-registry-auth)(\s*[:=]\s*)[^\"'\r\n]+"), "header"),
    # key=value in URLs, query strings, env dumps
    (re.compile(rf"(?i)\b((?:{_TOKEN_KEYS})=)[^&\s\"']+"), "kv"),
    # user:password@ in a URL
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+@"), "url"),
    (re.compile(r"\bdckr_(?:pat|oat)_[A-Za-z0-9_-]{8,}"), "docker-token"),
    # JWT (3 parts) and JWE (5 parts); a payload can be as short as "e30" ({})
    (re.compile(r"\beyJ[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]{2,}){1,4}"), "jwt"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "github-token"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), "scheme"),
    # legacy Docker Hub access tokens are bare UUIDs; a UUID in an error costs a word
    (re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "uuid"),
]


def mask_token_shapes(text: str) -> str:
    for rx, kind in _TOKEN_SHAPES:
        if kind == "field":
            text = rx.sub(lambda m: f'{m.group(1)}"[redacted]"', text)
        elif kind == "header":
            text = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted:authorization]", text)
        elif kind in ("kv", "url"):
            text = rx.sub(lambda m: f"{m.group(1)}[redacted]" + ("@" if kind == "url" else ""), text)
        elif kind == "scheme":
            text = rx.sub(lambda m: f"{m.group(1)} [redacted:authorization]", text)
        else:
            text = rx.sub(f"[redacted:{kind}]", text)
    return text


def clip(text: str, head: int = 120, tail: int = 400) -> str:
    """Shorten command output for an error message, keeping both ends, with
    credential shapes masked. sbx prints its progress first and the reason
    last ("ERROR: ..."), so a head-only cut hid every create failure behind
    "PREPARE IMAGE"."""
    text = mask_token_shapes(text.strip())
    if len(text) <= head + tail + 5:
        return text
    return f"{text[:head]} … {text[-tail:]}"


class BenchHost:
    """Base: the interface, plus shared ssh-argv policy. Subclasses decide
    what "a bench" is and how commands reach it."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # Subject delivery vs bench creation order (the oracle honors this):
    # True = populate the workspace before the bench exists (sbx: the
    # workspace is a host dir that create bind-mounts — touching the
    # mount root after create breaks sbx's sandbox); False = the bench
    # must exist first (tart: the workspace lives inside the VM).
    push_before_create = True

    def _ssh_argv(self, user: str, host: str, jump: str = "") -> list[str]:
        """Batch-mode ssh argv with the install's key/known-hosts policy."""
        cmd = [
            "ssh",
            "-i", self.cfg.bench_key,
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.cfg.bench_known_hosts}",
            "-o", "ConnectTimeout=15",
        ]
        if jump:
            cmd += ["-J", jump]
        cmd.append(f"{user}@{host}")
        return cmd

    def _ssh_run(self, argv: list[str], remote: str, timeout: int = 300,
                 strict: bool = True) -> subprocess.CompletedProcess:
        """ssh argv + one remote shell line. Transport errors (rc=255 +
        ssh in stderr) raise even when strict=False — a dead bench is
        never a test result."""
        proc = subprocess.run(
            argv + [remote], capture_output=True, text=True, timeout=timeout)
        transport_error = (proc.returncode == 255
                           and "ssh" in proc.stderr.lower())
        if transport_error:
            raise BenchHostError(
                f"ssh transport error: {clip(proc.stderr)}")
        if strict and proc.returncode != 0:
            raise BenchHostError(
                f"remote failed rc={proc.returncode}: "
                f"{clip(proc.stdout + proc.stderr)}")
        return proc

    # -- interface (subclass responsibility) -------------------------------

    def preflight(self) -> list[str]:
        """Reasons this host must not be given a bench right now, checked
        before any is created (the caller refuses with exit 2). Empty =
        go. A tier with nothing to check inherits this."""
        return []

    def workspace(self, name: str) -> str:
        raise NotImplementedError

    def create(self, name: str, agent: str = "shell",
               template: str | None = None) -> None:
        raise NotImplementedError

    def template_digest(self, tag: str) -> str:
        return ""

    # stderr of the last exec(): exec returns stdout alone (assertions match
    # on it), but a FAILED step's cause is usually on stderr, and a report
    # that shows only the command and rc=1 cannot explain a red suite.
    last_stderr: str = ""

    def exec(self, name: str, command: str, timeout: int = 300,
             env: dict[str, str] | None = None) -> tuple[int, str]:
        raise NotImplementedError

    def push_dir(self, local_dir: str, remote_dir: str) -> None:
        raise NotImplementedError

    def rm(self, name: str) -> None:
        raise NotImplementedError

    def exists(self, name: str) -> bool:
        raise NotImplementedError

    def pty_spawn_args(self, sandbox: str, columns: int, lines: int,
                       env: dict[str, str], command: str) -> list[str]:
        """Full pexpect argv for an interactive pty session inside the
        bench. The pty driver stays transport-agnostic; each host knows
        how to reach a tty."""
        raise NotImplementedError


def _env_exports(env: dict[str, str] | None) -> str:
    return "".join(
        f"export {k}={shlex.quote(v)}; " for k, v in (env or {}).items())


def _sq(s: str) -> str:
    """Single-quote for a remote shell word."""
    return "'" + s.replace("'", "'\\''") + "'"


class SbxBenchHost(BenchHost):
    """sbx sandboxes on a Linux bench-host (GENTAR_BENCH_HOST).

    sbx CLI shape (v0.39.0): `create [flags] AGENT PATH`, `exec [flags]
    SANDBOX COMMAND [ARG...]` (docker-exec semantics), `rm --force`."""

    @property
    def local(self) -> bool:
        """GENTAR_BENCH_HOST=local: the arena runs ON the bench host (a
        runner on the same VM), so sbx is called directly: no ssh, no
        bench key. The coordinator container gets the host's sbx binary,
        its state and config dirs and the workspace root mounted at the
        same paths, and runs as the host user (compose.local-bench.yml)."""
        return self.cfg.bench_host == "local"

    def _ssh_base(self) -> list[str]:
        # Local: every `ssh host '<line>'` becomes `sh -c '<line>'`, the same
        # quoting and semantics without the transport.
        if self.local:
            return ["sh", "-c"]
        return self._ssh_argv(self.cfg.bench_user, self.cfg.bench_host,
                              jump=self.cfg.bench_jump)

    def _run(self, remote_cmd: list[str], timeout: int = 300,
             strict: bool = True) -> subprocess.CompletedProcess:
        # ssh flattens argv with shell word-splitting on the remote side,
        # so quote every word; sbx flags with values stay one word each.
        remote = " ".join(shlex.quote(w) for w in remote_cmd)
        return self._ssh_run(self._ssh_base(), remote,
                             timeout=timeout, strict=strict)

    def workspace(self, name: str) -> str:
        return f"{self.cfg.bench_workspace_root}/{name}"

    def preflight(self) -> list[str]:
        """No stored sbx secrets on the bench-host, unless allowed.

        Every sbx sandbox carries `proxy-managed` placeholders for the
        common provider keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, …) and a
        format-shaped GH_TOKEN; sbx's credential proxy swaps a real value
        in for any service with a stored secret. So one `sbx secret set`
        on a shared bench-host would hand that key to EVERY suite of every
        arena there, whatever credential group the engine forwarded — the
        guarantee that only the winning group reaches a bench would hold
        by host state, not by construction (claude-playbooks, measured on
        arena-142). sbx 0.39 cannot create a sandbox with the proxy's
        injection off, so the engine refuses instead.

        GENTAR_SBX_SECRETS=allow is for an arena that uses sbx secrets as
        its credential mechanism on purpose. Only a count is reported,
        never the listing."""
        if self.cfg.sbx_secrets == "allow":
            return []
        proc = self._run([self.cfg.sbx_bin, "secret", "ls"], timeout=60,
                         strict=False)
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0:
            return [f"could not check for stored sbx secrets on "
                    f"{self.cfg.bench_host} (`sbx secret ls` exited "
                    f"{proc.returncode}); set GENTAR_SBX_SECRETS=allow to "
                    f"run without the check"]
        if out.startswith("No secrets found"):
            return []
        n = len([l for l in out.splitlines() if l.strip()])
        return [f"the bench-host {self.cfg.bench_host} has stored sbx "
                f"secrets ({n} line(s) in `sbx secret ls`): sbx's credential "
                f"proxy would resolve every sandbox's `proxy-managed` "
                f"placeholders to them, whatever credentials this run "
                f"forwards. Remove them (`sbx secret rm`), or set "
                f"GENTAR_SBX_SECRETS=allow if this arena uses sbx secrets "
                f"on purpose"]

    def create(self, name: str, agent: str = "shell",
               template: str | None = None) -> None:
        self._run(["mkdir", "-p", self.workspace(name)])
        cmd = [self.cfg.sbx_bin, "create", "--name", name]
        if template:
            cmd += ["-t", template]
        cmd += [agent, self.workspace(name)]
        self._run(cmd, timeout=600)

    def template_digest(self, tag: str) -> str:
        """IMAGE ID of a template (provenance: which image a bench came
        from). Empty string if absent."""
        proc = self._run([self.cfg.sbx_bin, "template", "ls"], timeout=60)
        for line in proc.stdout.splitlines():
            if tag in line:
                parts = line.split()
                return parts[2] if len(parts) > 2 else ""
        return ""

    def exec(self, name: str, command: str, timeout: int = 300,
             env: dict[str, str] | None = None) -> tuple[int, str]:
        """Run a command in the sandbox via `sh -lc`. Returns (exit_code,
        stdout) — a nonzero command exit is a RESULT, not an error; only
        ssh transport failures raise. `env` is exported ahead of the
        command (run id / OTLP endpoint injection for agent self-report).
        """
        proc = self._run(
            [self.cfg.sbx_bin, "exec", name, "sh", "-lc",
             _env_exports(env) + command],
            timeout=timeout,
            strict=False,
        )
        self.last_stderr = proc.stderr or ""
        return proc.returncode, proc.stdout

    def push_dir(self, local_dir: str, remote_dir: str) -> None:
        """Ship a local directory into the bench-host via tar over SSH.
        Subjects travel this way — mounted into sandboxes, never baked."""
        remote = f"mkdir -p {remote_dir} && tar -C {remote_dir} -xzf -"
        proc = subprocess.run(
            ["tar", "-C", local_dir, "-czf", "-", "."],
            stdout=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise BenchHostError(f"local tar of {local_dir} failed")
        ssh = subprocess.run(
            self._ssh_base() + [remote],
            input=proc.stdout,
            capture_output=True,
            timeout=600,
        )
        if ssh.returncode != 0:
            raise BenchHostError(
                f"push to {remote_dir} failed: {clip(ssh.stderr.decode())}")

    def rm(self, name: str) -> None:
        # Never raises: teardown must not mask the real verdict.
        try:
            self._run([self.cfg.sbx_bin, "rm", name, "--force"], timeout=120)
            self._run(["rm", "-rf", self.workspace(name)], timeout=60)
        except (BenchHostError, subprocess.TimeoutExpired) as exc:
            print(f"warn: sandbox {name} teardown failed: {exc}")

    def exists(self, name: str) -> bool:
        proc = self._run([self.cfg.sbx_bin, "ls", "--json"], timeout=60)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise BenchHostError(f"sbx ls --json not parseable: {exc}") from exc
        sandboxes = data["sandboxes"] if isinstance(data, dict) else data
        return any(s.get("name") == name for s in sandboxes)

    def pty_spawn_args(self, sandbox: str, columns: int, lines: int,
                       env: dict[str, str], command: str) -> list[str]:
        # Local: the pty is the coordinator's own (pexpect), so no -tt.
        ssh = ["sh", "-c"] if self.local else self._ssh_base() + ["-tt", "--"]
        # Extra env (credential transport, tier 1) is quoted per
        # assignment — a value with spaces/metachars stays one word.
        remote = " ".join([
            self.cfg.sbx_bin, "exec", "-t", sandbox,
            "env", f"COLUMNS={columns}", f"LINES={lines}",
            *([shlex.quote(f"{k}={v}") for k, v in (env or {}).items()]),
            "bash", "-c", _sq(command)])
        return ssh + [remote]


class TartBenchHost(BenchHost):
    """tart VMs on an Apple-Silicon Mac host. The tart host runs the CLI;
    each bench is a clone of a local template VM. The template must carry:
    sshd on, the coordinator pubkey authorized for `tart_vm_user`, agent
    CLIs pre-installed. tart has no digests for local VMs, so
    template_digest is the empty string (the template NAME still lands
    in spans)."""

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        self._vm_ips: dict[str, str] = {}   # sandbox name -> guest ip

    push_before_create = False   # workspace lives inside the VM

    # -- tart host (control plane) -----------------------------------------

    def _tart(self, args: list[str], timeout: int = 300,
              strict: bool = True) -> subprocess.CompletedProcess:
        return self._ssh_run(
            self._ssh_argv(self.cfg.tart_user, self.cfg.tart_host),
            " ".join(shlex.quote(w) for w in [self.cfg.tart_bin, *args]),
            timeout=timeout, strict=strict)

    def _vm_ssh(self, name: str) -> list[str]:
        """Batch ssh into the guest, jumping through the tart host — the
        vmnet subnet is only routed there, so this works from any
        coordinator location. Guest host keys change with every clone.
        ProxyCommand (two ssh processes), not -J: Debian's in-process
        stdio forward mishandles this combo from inside containers
        (empirically; ProxyCommand is the portable form)."""
        if name not in self._vm_ips:
            raise BenchHostError(
                f"no live tart VM named {name!r} — create() it first")
        hop = " ".join([
            "ssh", "-i", self.cfg.bench_key, "-o", "BatchMode=yes",
            "-o", "UserKnownHostsFile=" + self.cfg.bench_known_hosts,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15",
            "-W", "%h:%p", f"{self.cfg.tart_user}@{self.cfg.tart_host}"])
        return [
            "ssh", "-i", self.cfg.bench_key, "-o", "BatchMode=yes",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15",
            f"-o ProxyCommand={hop}",
            f"{self.cfg.tart_vm_user}@{self._vm_ips[name]}",
        ]

    # -- interface -----------------------------------------------------------

    def workspace(self, name: str) -> str:
        return f"/Users/{self.cfg.tart_vm_user}/gentar-workspaces/{name}"

    def create(self, name: str, agent: str = "shell",
               template: str | None = None) -> None:
        if not template:
            raise BenchHostError(
                "tart benches need an explicit template (a local VM name, "
                "e.g. gentar-bench-macos-v1) — there is no base shell VM")
        self._tart(["clone", template, name], timeout=900)
        # Headless run: detach on the tart host so the VM outlives the
        # ssh session that started it.
        self._ssh_run(
            self._ssh_argv(self.cfg.tart_user, self.cfg.tart_host),
            f"nohup {self.cfg.tart_bin} run --no-graphics {shlex.quote(name)} "
            f">/tmp/tart-{shlex.quote(name)}.log 2>&1 &",
            timeout=30)
        proc = self._tart(["ip", name, "--wait", "300"], timeout=330)
        ip = proc.stdout.strip().splitlines()
        if not ip:
            raise BenchHostError(f"tart ip returned nothing for {name}")
        self._vm_ips[name] = ip[-1]

    def exec(self, name: str, command: str, timeout: int = 300,
             env: dict[str, str] | None = None) -> tuple[int, str]:
        # WORKSPACE_DIR: sbx sets it inside sandboxes; scenarios rely on
        # it, so the tart tier injects it explicitly.
        merged = {"WORKSPACE_DIR": self.workspace(name), **(env or {})}
        proc = self._ssh_run(
            self._vm_ssh(name),
            _env_exports(merged) + command,
            timeout=timeout, strict=False)
        self.last_stderr = proc.stderr or ""
        return proc.returncode, proc.stdout

    def push_dir(self, local_dir: str, remote_dir: str) -> None:
        """Ship a local directory into the guest via tar over ssh. The
        remote_dir is a workspace path; the VM name is its last segment
        (the only push target today)."""
        name = remote_dir.rstrip("/").split("/")[-1]
        if name not in self._vm_ips:
            raise BenchHostError(
                f"no live tart VM maps to workspace {remote_dir!r}")
        remote = f"mkdir -p {remote_dir} && tar -C {remote_dir} -xzf -"
        # COPYFILE_DISABLE: host-run coordinators use macOS bsdtar, which
        # otherwise stores AppleDouble ._* metadata files in the stream
        # (GNU tar in the container ignores the var, bsdtar honors it).
        proc = subprocess.run(
            ["tar", "-C", local_dir, "-czf", "-", "."],
            stdout=subprocess.PIPE,
            env={**os.environ, "COPYFILE_DISABLE": "1"},
        )
        if proc.returncode != 0:
            raise BenchHostError(f"local tar of {local_dir} failed")
        ssh = subprocess.run(
            self._vm_ssh(name) + [remote],
            input=proc.stdout,
            capture_output=True,
            timeout=600,
        )
        if ssh.returncode != 0:
            raise BenchHostError(
                f"push to {remote_dir} failed: {clip(ssh.stderr.decode())}")

    def rm(self, name: str) -> None:
        # Never raises: teardown must not mask the real verdict.
        try:
            self._tart(["stop", name], timeout=120, strict=False)
            self._tart(["delete", name], timeout=120)
        except (BenchHostError, subprocess.TimeoutExpired) as exc:
            print(f"warn: tart VM {name} teardown failed: {exc}")

    def exists(self, name: str) -> bool:
        proc = self._tart(["list"], timeout=60)
        # Columns: <source> <name> <disk> <size> <accessed> <state> —
        # the name is field 2 (state, not name, is last).
        return any(len(fields) > 1 and fields[1] == name
                   for fields in (line.split()
                                  for line in proc.stdout.splitlines()))

    def pty_spawn_args(self, sandbox: str, columns: int, lines: int,
                       env: dict[str, str], command: str) -> list[str]:
        merged = {"WORKSPACE_DIR": self.workspace(sandbox), **env}
        remote = " ".join([
            "env", f"COLUMNS={columns}", f"LINES={lines}",
            *([shlex.quote(f"{k}={v}") for k, v in merged.items()]),
            "sh", "-c", _sq(command)])
        return self._vm_ssh(sandbox) + ["-tt", remote]


class OpenSandboxBenchHost(BenchHost):
    """OpenSandbox containers behind an opensandbox-server (docker
    runtime). The server runs wherever the sandbox containers should run
    (a lab VM, the CI host, or a compose sidecar); this host talks to it
    with the python SDK. A bench is one container image — a scenario's
    ``template`` is an image ref; sandbox identity rides on the
    ``gentar.name`` metadata key (server ids are UUIDs).

    execd (the in-sandbox daemon) serves everything: commands (with real
    exit codes and env injection), files, and the PTY WebSocket that
    osb_pty_bridge attaches to from the pty driver."""

    push_before_create = False   # workspace lives inside the sandbox

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        self._sandboxes: dict[str, object] = {}
        # Lazy import: the osb tier is opt-in, and the SDK import cost
        # should not land on sbx/tart runs.
        from opensandbox.config import ConnectionConfigSync
        url = urlparse(cfg.osb_server)
        kwargs = {"domain": url.netloc,
                  "protocol": "https" if url.scheme == "https" else "http",
                  "use_server_proxy": cfg.osb_server_proxy}
        if cfg.osb_api_key:
            kwargs["api_key"] = cfg.osb_api_key
        self._conn = ConnectionConfigSync(**kwargs)

    def _get(self, name: str):
        if name not in self._sandboxes:
            raise BenchHostError(f"no live osb sandbox named {name!r} "
                                 "— create() it first")
        return self._sandboxes[name]

    # -- interface -----------------------------------------------------------

    def workspace(self, name: str) -> str:
        return f"/root/workspaces/{name}"

    def create(self, name: str, agent: str = "shell",
               template: str | None = None) -> None:
        from opensandbox.sync import SandboxSync
        try:
            sandbox = SandboxSync.create(
                template or self.cfg.osb_template,
                timeout=timedelta(hours=4),
                metadata={"gentar.name": name},
                connection_config=self._conn)
        except Exception as exc:
            raise BenchHostError(f"osb create {name!r} failed: {exc}") from exc
        self._sandboxes[name] = sandbox
        # execd validates that a run's working directory exists — unlike
        # ssh tiers, which tolerate a missing cd target. Subjectless
        # scenarios never push, so the workspace is made here, always.
        execution = sandbox.commands.run(
            f"mkdir -p {shlex.quote(self.workspace(name))}")
        if execution.exit_code not in (0, None):
            raise BenchHostError(
                f"osb workspace mkdir failed rc={execution.exit_code}")

    def exec(self, name: str, command: str, timeout: int = 300,
             env: dict[str, str] | None = None) -> tuple[int, str]:
        from opensandbox.models.execd import RunCommandOpts
        merged = {"WORKSPACE_DIR": self.workspace(name), **(env or {})}
        execution = self._get(name).commands.run(
            command,
            opts=RunCommandOpts(
                working_directory=self.workspace(name),
                timeout=timedelta(seconds=timeout),
                envs=merged))
        rc = execution.exit_code if execution.exit_code is not None else 1
        return rc, execution.text

    def push_dir(self, local_dir: str, remote_dir: str) -> None:
        """Ship a local directory in as tar: execd's file API is
        single-file, so pack locally, write the tarball, untar inside."""
        sandbox = self._get(remote_dir.rstrip("/").split("/")[-1])
        payload = f"{remote_dir}/.gentar-payload.tgz"
        with tempfile.NamedTemporaryFile(suffix=".tgz") as tmp:
            proc = subprocess.run(
                ["tar", "-C", local_dir, "-czf", tmp.name, "."],
                capture_output=True,
                env={**os.environ, "COPYFILE_DISABLE": "1"})
            if proc.returncode != 0:
                raise BenchHostError(f"local tar of {local_dir} failed")
            with open(tmp.name, "rb") as data:
                sandbox.files.write_file(payload, data)
        rc, _ = self.exec(remote_dir.rstrip("/").split("/")[-1],
                          f"mkdir -p {shlex.quote(remote_dir)} && "
                          f"tar -xzf {shlex.quote(payload)} -C "
                          f"{shlex.quote(remote_dir)} && "
                          f"rm -f {shlex.quote(payload)}")
        if rc != 0:
            raise BenchHostError(f"untar into {remote_dir} failed rc={rc}")

    def rm(self, name: str) -> None:
        # Never raises: teardown must not mask the real verdict.
        sandbox = self._sandboxes.pop(name, None)
        if sandbox is None:
            return
        try:
            sandbox.destroy()
        except Exception as exc:
            print(f"warn: osb sandbox {name} teardown failed: {exc}")

    def exists(self, name: str) -> bool:
        from opensandbox.models.sandboxes import SandboxFilter
        from opensandbox.sync import SandboxManagerSync
        manager = SandboxManagerSync.create(connection_config=self._conn)
        infos = manager.list_sandbox_infos(
            SandboxFilter(metadata={"gentar.name": name}))
        return bool(infos.sandbox_infos)

    def pty_spawn_args(self, sandbox: str, columns: int, lines: int,
                       env: dict[str, str], command: str) -> list[str]:
        endpoint = self._get(sandbox).get_endpoint(44772)
        base = f"http://{endpoint.endpoint}"
        merged = {"WORKSPACE_DIR": self.workspace(sandbox), **env}
        # Same shape as the other tiers' remote command — the bridge sends
        # it as the pty session's first line, then relays.
        remote = " ".join([
            "cd", self.workspace(sandbox), "&&", "env",
            f"COLUMNS={columns}", f"LINES={lines}",
            *([shlex.quote(f"{k}={v}") for k, v in merged.items()]),
            "bash", "-c", _sq(command)])
        bridge = str(Path(__file__).with_name("osb_pty_bridge.py"))
        return [sys.executable, "-u", bridge, base, remote]


class DaytonaBenchHost(BenchHost):
    """Daytona cloud sandboxes (daytona.io). The SDK owns the lifecycle
    (create from an image ref / delete / list); everything interactive is
    ssh — the SDK mints a per-sandbox expiring token that doubles as the
    ssh username against a fixed gateway host, so exec/push/pty are the
    tart pattern verbatim (batch ssh, tar over ssh stdin, ssh -tt), minus
    the key file and the ProxyCommand hop. Benches run as root; the
    workspace is minted at create like osb (nothing validates it remotely,
    but every command's cwd assumption does)."""

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        if not cfg.daytona_api_key:
            raise BenchHostError(
                "daytona benches need GENTAR_DAYTONA_API_KEY (daytona.io "
                "personal API key)")
        self._sandboxes: dict[str, tuple[object, str]] = {}  # name -> (sb, token)

    push_before_create = False   # workspace lives inside the sandbox

    def _client(self):
        from daytona import Daytona, DaytonaConfig
        return Daytona(DaytonaConfig(api_key=self.cfg.daytona_api_key))

    def _sb_ssh(self, name: str) -> list[str]:
        """Batch ssh into the sandbox — token as username, no key file.
        The gateway's host key is stable but tokens are ephemeral
        identities, so no known-hosts bookkeeping (same policy as tart
        guest keys)."""
        if name not in self._sandboxes:
            raise BenchHostError(
                f"no live daytona sandbox named {name!r} — create() it first")
        _, token = self._sandboxes[name]
        return [
            "ssh", "-o", "BatchMode=yes",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15",
            f"{token}@{self.cfg.daytona_ssh_host}",
        ]

    # -- interface -----------------------------------------------------------

    def workspace(self, name: str) -> str:
        return f"/root/workspaces/{name}"

    def create(self, name: str, agent: str = "shell",
               template: str | None = None) -> None:
        from daytona import CreateSandboxFromImageParams
        try:
            sb = self._client().create(CreateSandboxFromImageParams(
                name=f"gentar-{name}",
                image=template or self.cfg.daytona_image,
                # Idle-stop after 15 min: a wedged run must not burn
                # cloud budget overnight; the coordinator's own rm is the
                # normal teardown.
                auto_stop_interval=15,
            ))
        except Exception as exc:
            raise BenchHostError(f"daytona create failed: {exc}") from exc
        ssh = sb.create_ssh_access(expires_in_minutes=120)
        self._sandboxes[name] = (sb, ssh.token)
        r = sb.process.exec(
            f"mkdir -p {shlex.quote(self.workspace(name))}", timeout=60)
        if r.exit_code not in (0, None):
            raise BenchHostError(
                f"daytona workspace mkdir failed (exit {r.exit_code})")

    def exec(self, name: str, command: str, timeout: int = 300,
             env: dict[str, str] | None = None) -> tuple[int, str]:
        merged = {"WORKSPACE_DIR": self.workspace(name), **(env or {})}
        proc = self._ssh_run(
            self._sb_ssh(name),
            _env_exports(merged) + command,
            timeout=timeout, strict=False)
        self.last_stderr = proc.stderr or ""
        return proc.returncode, proc.stdout

    def push_dir(self, local_dir: str, remote_dir: str) -> None:
        """Tar over ssh stdin — the tart pattern. remote_dir's last
        segment names the sandbox."""
        name = remote_dir.rstrip("/").split("/")[-1]
        if name not in self._sandboxes:
            raise BenchHostError(
                f"no live daytona sandbox maps to workspace {remote_dir!r}")
        remote = f"mkdir -p {remote_dir} && tar -C {remote_dir} -xzf -"
        proc = subprocess.run(
            ["tar", "-C", local_dir, "-czf", "-", "."],
            stdout=subprocess.PIPE,
            env={**os.environ, "COPYFILE_DISABLE": "1"},
        )
        if proc.returncode != 0:
            raise BenchHostError(f"local tar of {local_dir} failed")
        ssh = subprocess.run(
            self._sb_ssh(name) + [remote],
            input=proc.stdout,
            capture_output=True,
            timeout=600,
        )
        if ssh.returncode != 0:
            raise BenchHostError(
                f"push to {remote_dir} failed: {clip(ssh.stderr.decode())}")

    def rm(self, name: str) -> None:
        # Never raises: teardown must not mask the real verdict.
        entry = self._sandboxes.pop(name, None)
        if not entry:
            return
        try:
            entry[0].delete()
        except Exception as exc:
            print(f"warn: daytona sandbox {name} teardown failed: {exc}")

    def exists(self, name: str) -> bool:
        try:
            return any(sb.name == f"gentar-{name}"
                       for sb in self._client().list())
        except Exception:
            return False

    def pty_spawn_args(self, sandbox: str, columns: int, lines: int,
                       env: dict[str, str], command: str) -> list[str]:
        merged = {"WORKSPACE_DIR": self.workspace(sandbox), **env}
        remote = " ".join([
            "cd", self.workspace(sandbox), "&&", "env",
            f"COLUMNS={columns}", f"LINES={lines}",
            *([shlex.quote(f"{k}={v}") for k, v in merged.items()]),
            "sh", "-c", _sq(command)])
        return self._sb_ssh(sandbox) + ["-tt", remote]


def make_bench(cfg: Config, kind: str = "") -> BenchHost:
    kind = kind or cfg.bench_kind
    if kind == "sbx":
        return SbxBenchHost(cfg)
    if kind == "tart":
        return TartBenchHost(cfg)
    if kind == "osb":
        return OpenSandboxBenchHost(cfg)
    if kind == "daytona":
        return DaytonaBenchHost(cfg)
    raise BenchHostError(
        f"unknown bench kind {kind!r} (known: sbx, tart, osb, daytona)")

"""Bench hosts — where scenarios run. Two implementations behind one
interface (decision of record, gentar TASK.md 2026-08-18):

- ``SbxBenchHost``: sbx sandboxes on a Linux bench-host (the default
  tier). The coordinator drives sbx over ssh; each bench is a per-run
  sandbox with the workspace bind-mounted in.
- ``TartBenchHost``: tart VMs on an Apple-Silicon Mac host (the macOS
  tier). ``tart clone`` from a local template VM, headless ``tart run``,
  commands over ssh into the guest — jumping through the tart host,
  because the guest's vmnet subnet is only routed on the Mac itself.
  The tart VM *is* the bench; nothing nests inside it.

Interface every runner (oracle, scripted, pty driver) codes against:
create / exec / push_dir / rm / exists / workspace / template_digest /
pty_spawn_args. ``make_bench(cfg, kind)`` is the factory.
"""

import json
import shlex
import subprocess

from gentar.config import Config


class BenchHostError(RuntimeError):
    pass


class BenchHost:
    """Base: the interface, plus shared ssh-argv policy. Subclasses decide
    what "a bench" is and how commands reach it."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

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
                f"ssh transport error: {proc.stderr.strip()[:400]}")
        if strict and proc.returncode != 0:
            raise BenchHostError(
                f"remote failed rc={proc.returncode}: "
                f"{(proc.stdout + proc.stderr).strip()[:400]}")
        return proc

    # -- interface (subclass responsibility) -------------------------------

    def workspace(self, name: str) -> str:
        raise NotImplementedError

    def create(self, name: str, agent: str = "shell",
               template: str | None = None) -> None:
        raise NotImplementedError

    def template_digest(self, tag: str) -> str:
        return ""

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
    """sbx sandboxes on a Linux bench-host (VM 142 today).

    sbx CLI shape (v0.39.0): `create [flags] AGENT PATH`, `exec [flags]
    SANDBOX COMMAND [ARG...]` (docker-exec semantics), `rm --force`."""

    def _ssh_base(self) -> list[str]:
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
                f"push to {remote_dir} failed: {ssh.stderr.decode()[:400]}")

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
        ssh = self._ssh_base() + ["-tt", "--"]
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
        coordinator location. Guest host keys change with every clone."""
        if name not in self._vm_ips:
            raise BenchHostError(
                f"no live tart VM named {name!r} — create() it first")
        return [
            "ssh", "-i", self.cfg.bench_key, "-o", "BatchMode=yes",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=15",
            "-J", f"{self.cfg.tart_user}@{self.cfg.tart_host}",
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
        proc = self._ssh_run(
            self._vm_ssh(name),
            _env_exports(env) + command,
            timeout=timeout, strict=False)
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
        proc = subprocess.run(
            ["tar", "-C", local_dir, "-czf", "-", "."],
            stdout=subprocess.PIPE,
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
                f"push to {remote_dir} failed: {ssh.stderr.decode()[:400]}")

    def rm(self, name: str) -> None:
        # Never raises: teardown must not mask the real verdict.
        try:
            self._tart(["stop", name], timeout=120, strict=False)
            self._tart(["delete", "--force", name], timeout=120)
        except (BenchHostError, subprocess.TimeoutExpired) as exc:
            print(f"warn: tart VM {name} teardown failed: {exc}")

    def exists(self, name: str) -> bool:
        proc = self._tart(["list"], timeout=60)
        return any(line.split()[-1:] == [name]
                   for line in proc.stdout.splitlines())

    def pty_spawn_args(self, sandbox: str, columns: int, lines: int,
                       env: dict[str, str], command: str) -> list[str]:
        remote = " ".join([
            "env", f"COLUMNS={columns}", f"LINES={lines}",
            *([shlex.quote(f"{k}={v}") for k, v in (env or {}).items()]),
            "sh", "-c", _sq(command)])
        return self._vm_ssh(sandbox) + ["-tt", remote]


def make_bench(cfg: Config, kind: str = "") -> BenchHost:
    kind = kind or cfg.bench_kind
    if kind == "sbx":
        return SbxBenchHost(cfg)
    if kind == "tart":
        return TartBenchHost(cfg)
    raise BenchHostError(f"unknown bench kind {kind!r} (known: sbx, tart)")

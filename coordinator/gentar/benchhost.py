"""Bench-host client: SSH to a host running `sbx` and drive sandbox
lifecycle. Phase 1 covers the smoke loop (create / exec / rm); the pty
driver (phase 3) layers on the same exec path.

sbx CLI shape (v0.38.0): `create [flags] AGENT PATH`, `exec [flags]
SANDBOX COMMAND [ARG...]` (docker-exec semantics), `rm --force`.
"""

import json
import shlex
import subprocess

from gentar.config import Config


class BenchHostError(RuntimeError):
    pass


class BenchHost:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # -- transport -------------------------------------------------------

    def _ssh_base(self) -> list[str]:
        cmd = [
            "ssh",
            "-i", self.cfg.bench_key,
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.cfg.bench_known_hosts}",
            "-o", "ConnectTimeout=15",
        ]
        if self.cfg.bench_jump:
            cmd += ["-J", self.cfg.bench_jump]
        cmd.append(f"{self.cfg.bench_user}@{self.cfg.bench_host}")
        return cmd

    def _run(self, remote_cmd: list[str], timeout: int = 300,
             strict: bool = True) -> subprocess.CompletedProcess:
        # ssh flattens argv with shell word-splitting on the remote side,
        # so quote every word; sbx flags with values stay one word each.
        remote = " ".join(shlex.quote(w) for w in remote_cmd)
        proc = subprocess.run(
            self._ssh_base() + [remote],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # ssh itself exits 255 on transport errors; anything else is the
        # remote command's own exit code.
        transport_error = proc.returncode == 255 and "ssh" in proc.stderr.lower()
        if strict and (proc.returncode != 0 or transport_error):
            raise BenchHostError(
                f"remote {remote_cmd[0]} failed rc={proc.returncode}: "
                f"{proc.stderr.strip()[:400]}"
            )
        if transport_error:
            raise BenchHostError(
                f"ssh to bench-host failed: {proc.stderr.strip()[:400]}")
        return proc

    # -- sbx lifecycle ---------------------------------------------------

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

    def exec(self, name: str, command: str, timeout: int = 300) -> tuple[int, str]:
        """Run a command in the sandbox via `sh -lc`. Returns (exit_code,
        stdout) — a nonzero command exit is a RESULT, not an error; only
        ssh transport failures raise."""
        proc = self._run(
            [self.cfg.sbx_bin, "exec", name, "sh", "-lc", command],
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

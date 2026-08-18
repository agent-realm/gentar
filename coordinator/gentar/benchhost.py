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

    def _run(self, remote_cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        # ssh flattens argv with shell word-splitting on the remote side,
        # so quote every word; sbx flags with values stay one word each.
        remote = " ".join(shlex.quote(w) for w in remote_cmd)
        proc = subprocess.run(
            self._ssh_base() + [remote],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise BenchHostError(
                f"remote {remote_cmd[0]} failed rc={proc.returncode}: "
                f"{proc.stderr.strip()[:400]}"
            )
        return proc

    # -- sbx lifecycle ---------------------------------------------------

    def workspace(self, name: str) -> str:
        return f"{self.cfg.bench_workspace_root}/{name}"

    def create(self, name: str, agent: str = "shell") -> None:
        self._run(["mkdir", "-p", self.workspace(name)])
        self._run(
            [self.cfg.sbx_bin, "create", "--name", name, agent, self.workspace(name)],
            timeout=600,
        )

    def exec(self, name: str, command: str, timeout: int = 300) -> tuple[int, str]:
        """Run a command in the sandbox via `sh -lc`. Returns (exit_code, stdout)."""
        proc = self._run(
            [self.cfg.sbx_bin, "exec", name, "sh", "-lc", command],
            timeout=timeout,
        )
        return proc.returncode, proc.stdout

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

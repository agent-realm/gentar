"""The human-simulation driver — pexpect over `ssh -tt … sbx exec -t`,
replacing gauntlet's tmux/send-keys transport with a direct pty. Policies
port verbatim from agent-gauntlet/lib/drive.sh (itself from the herdr
incident 2026-07-13):

- Approve ordinary permission prompts ("Do you want to proceed?" /
  "requires approval" / "allow this command") with Enter —
- UNLESS the visible text matches the danger regex, then ABORT
  (Esc, C-c, C-c) — a hard safety gate, not a soft failure.
- Navigate pickers by reading the "❯ N. label" cursor line, never by
  blind-typing an option number.
"""

import re
import shlex
import time

import pexpect

from gentar.benchhost import BenchHost

# Ported verbatim from gauntlet drive.sh DRIVE_DANGER_RE.
DANGER_RE = re.compile(
    r"rm -rf /($|[^a-zA-Z])|mkfs\.|dd .*of=/dev/(sd|nvme|vd)"
    r"|:\(\)\{.*:\|:.*\};:|shutdown |poweroff|systemctl (poweroff|reboot)"
    r"|iptables -F|> */dev/(sd|nvme|vd)"
)
APPROVAL_RE = re.compile(
    r"do you want to (proceed|make this edit)|requires approval|allow this command",
    re.IGNORECASE,
)
PICKER_CURSOR_RE = re.compile(r"^\s*❯\s*[0-9]+\.", re.MULTILINE)
SPINNER_RE = re.compile(r"^[✻✽✢·✳✶]", re.MULTILINE)


class DriverAbort(RuntimeError):
    """The danger gate fired — the run fails loudly and safely."""


class PtyDriver:
    def __init__(self, bench: BenchHost, sandbox: str, columns: int = 220,
                 lines: int = 50) -> None:
        self.bench = bench
        self.sandbox = sandbox
        self.columns, self.lines = columns, lines
        self.child = None
        self.transcript = ""   # full evidence; spans carry the tail

    # -- lifecycle -------------------------------------------------------

    def start(self, command: str, env: dict[str, str] | None = None) -> None:
        ssh = self.bench._ssh_base() + ["-tt", "--"]
        # Extra env (credential transport, tier 1) is quoted per
        # assignment — a value with spaces/metachars stays one word.
        remote = " ".join([
            self.bench.cfg.sbx_bin, "exec", "-t", self.sandbox,
            "env", f"COLUMNS={self.columns}", f"LINES={self.lines}",
            *([shlex.quote(f"{k}={v}") for k, v in (env or {}).items()]),
            "bash", "-c", _sq(command),
        ])
        self.child = pexpect.spawn(ssh[0], ssh[1:] + [remote],
                                   encoding="utf-8", codec_errors="replace",
                                   dimensions=(self.lines, self.columns),
                                   timeout=1)
        self.child.logfile_read = _TranscriptTap(self)

    def close(self) -> None:
        if self.child is not None:
            try:
                self.child.sendline("exit")
                self.child.expect(pexpect.EOF, timeout=5)
            except Exception:
                pass
            try:
                self.child.close(force=True)
            except Exception:
                pass
            self.child = None

    # -- primitives ------------------------------------------------------

    def _pump(self) -> None:
        """Drain the pty into the transcript. pexpect only reads inside
        expect(); polling loops must pump explicitly or the kernel buffer
        fills and the screen never updates."""
        while self.child is not None:
            try:
                data = self.child.read_nonblocking(size=65536, timeout=0)
                if not data:
                    break
            except pexpect.TIMEOUT:
                break
            except (pexpect.EOF, ValueError, OSError):
                break

    def screen(self) -> str:
        """Visible screen approximation: last `lines` lines of transcript."""
        self._pump()
        return "\n".join(self.transcript.splitlines()[-self.lines:])

    def send_line(self, text: str) -> None:
        self.child.sendline(text)

    def send_key(self, key: str) -> None:  # "enter", "escape", "down", "ctrl-c"
        self.child.send(_KEYS[key])

    def abort(self, why: str) -> None:
        print(f"DRIVE ABORT: {why}")
        for key, delay in (("escape", 1.0), ("ctrl-c", 1.0), ("ctrl-c", 0.5)):
            try:
                self.send_key(key)
            except Exception:
                pass
            time.sleep(delay)

    # -- policies (ported) -----------------------------------------------

    def drive_until(self, pattern: str, max_seconds: int = 90) -> bool:
        """Poll for pattern (case-insensitive regex) while approving
        ordinary prompts. Danger text aborts the whole run."""
        want = re.compile(pattern, re.IGNORECASE)
        waited = 0.0
        while waited < max_seconds:
            scr = self.screen()
            if want.search(scr):
                return True
            if APPROVAL_RE.search(scr):
                if DANGER_RE.search(scr):
                    self.abort("live agent asked to run a command matching the danger gate")
                    raise DriverAbort("danger gate: " + _tail(scr, 300))
                self.send_key("enter"); time.sleep(2); waited += 2; continue
            time.sleep(3); waited += 3
        return False

    def wait_done(self, max_seconds: int = 300) -> bool:
        """Wait for the driver COMMAND to finish (ssh EOF when the
        remote bash exits). Headless agents print nothing until they
        are done — wait_idle would return early and race the verify
        step against work still in flight."""
        if self.child is None:
            return True
        try:
            self.child.expect(pexpect.EOF, timeout=max_seconds)
            self._pump()
            return True
        except pexpect.TIMEOUT:
            return False

    def wait_idle(self, max_seconds: int = 60) -> bool:
        prev, waited = None, 0.0
        while waited < max_seconds:
            cur = self.screen()
            if (not SPINNER_RE.search(cur)) and cur == prev and cur.strip():
                return True
            prev = cur
            time.sleep(3); waited += 3
        return False

    def pick_option(self, label_pattern: str, max_tries: int = 8) -> bool:
        """Navigate the picker DOWN until the ❯ cursor line matches
        label_pattern, then Enter. False if no picker is visible."""
        label = re.compile(label_pattern, re.IGNORECASE)
        if not PICKER_CURSOR_RE.search(self.screen()):
            return False
        for _ in range(max_tries):
            # The transcript is a raw stream, not a rendered pane (gauntlet
            # had tmux capture-pane); in-place redraws stack blocks, so the
            # CURRENT cursor is the LAST ❯ line, not the first.
            cursor = next((ln for ln in reversed(self.screen().splitlines())
                           if ln.lstrip().startswith("❯")), "")
            if label.search(cursor):
                self.send_key("enter")
                return True
            self.send_key("down")
            time.sleep(1)
        return False


class _TranscriptTap:
    def __init__(self, driver: PtyDriver) -> None:
        self.driver = driver

    def write(self, data) -> None:
        if isinstance(data, str):
            self.driver.transcript += data

    def flush(self) -> None:
        pass


_KEYS = {"enter": "\r", "escape": "\x1b", "down": "\x1b[B", "up": "\x1b[A",
         "ctrl-c": "\x03"}


def _sq(s: str) -> str:
    """Single-quote for the remote shell word."""
    return "'" + s.replace("'", "'\\''") + "'"


def _tail(s: str, n: int) -> str:
    return s[-n:].replace("\n", " ⏎ ")

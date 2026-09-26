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
import time

import pexpect

from gentar.benchhost import BenchHost

from gentar.gates import APPROVAL_RE, DANGER_RE  # noqa: E402,F401  (re-exported)
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
        self.aborted = False   # the danger gate fired: never type again

    # -- lifecycle -------------------------------------------------------

    def start(self, command: str, env: dict[str, str] | None = None) -> None:
        # The host builds the transport (sbx: ssh→`sbx exec -t`; tart:
        # ssh jump→guest); the driver only drives the pty it gets back.
        argv = self.bench.pty_spawn_args(
            self.sandbox, self.columns, self.lines, env or {}, command)
        self.child = pexpect.spawn(argv[0], argv[1:],
                                   encoding="utf-8", codec_errors="replace",
                                   dimensions=(self.lines, self.columns),
                                   timeout=1)
        self.child.logfile_read = _TranscriptTap(self)

    def close(self) -> None:
        if self.child is not None:
            # After the danger gate fired, the dangerous prompt may still be
            # live (abort()'s ctrl-c not yet delivered on a loaded host), and
            # `exit` + Enter would ANSWER it — the gate refused, then its own
            # teardown typed into the prompt (scripted-danger, v0.6.1 tag
            # run). So after an abort: no input at all; wait for EOF, then
            # force-close (which hangs up the transport).
            try:
                if not self.aborted:
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
        """Visible screen approximation: a cell-model render (see
        _render) over a transcript window spanning MANY frames — the
        diff-rendered TUI re-sends only changed cells per frame, so a
        short window shows a screen with holes in it."""
        self._pump()
        rendered = _render(self.transcript[-400000:], self.lines)
        return "\n".join(rendered.splitlines()[-self.lines:])

    def send_line(self, text: str) -> None:
        self.child.sendline(text)

    def send_text(self, text: str) -> None:
        """Literal text, no newline — a goal pilot's declared `send`."""
        self.child.send(text)

    def send_key(self, key: str) -> None:  # "enter", "escape", "down", "ctrl-c"
        self.child.send(_KEYS[key])

    def send_keys(self, keys: list[str], delay: float = 0.5) -> None:
        """A key sequence with pacing — interactive TUIs read single keys,
        and shortcuts like claude-code's exit need two C-c INSIDE its
        ~1s window; a bare double-send races it (proven live, probe 3/4:
        1.5s apart never exits, 0.4s apart does)."""
        for key in keys:
            self.send_key(key)
            time.sleep(delay)

    def abort(self, why: str) -> None:
        print(f"DRIVE ABORT: {why}")
        self.aborted = True
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

    def pick_option(self, label_pattern: str, max_tries: int = 8,
                    settle: float = 10.0) -> bool:
        """Navigate the picker DOWN until the ❯ cursor line matches
        label_pattern, then Enter. False if no picker is visible —
        but only after `settle` seconds: the picker render races the
        turn that triggered it (the answer keystroke travels a
        multi-hop pty chain; the redraw lands noticeably later)."""
        label = re.compile(label_pattern, re.IGNORECASE)
        waited = 0.0
        while waited < settle:
            if PICKER_CURSOR_RE.search(self.screen()):
                break
            time.sleep(0.5)
            waited += 0.5
        else:
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


# The vocabulary lives in a leaf module so the scenario parser can validate
# `key` turns without importing pexpect (see gentar/keys.py).
from gentar.keys import KEYS as _KEYS  # noqa: E402


def _render(raw: str, height: int = 0) -> str:
    """Terminal-screen reconstruction from a raw pty byte stream.
    claude-code's TUI is a DIFF renderer: each frame re-sends only the
    cells that changed since the last one, positioning runs with
    absolute-column and relative cursor moves — so a single frame's
    bytes omit everything that stayed on screen (proven live, probe 5:
    "Press Enter…" arrived as "Press Ente\\x1b[13G to continue…"; the
    "r" was simply never re-sent), and word gaps are cursor jumps, not
    space bytes. The only faithful screen is a cell model: replay the
    stream's cursor moves and writes into a (row, col) buffer, honor
    the clears, read the buffer back. Covers exactly the ops the TUI
    emits — CHA/CUP/VPA, CUU/CUD/CUF/CUB, EL, ED, CR/LF/BS; SGR and
    everything else drops.

    With `height` the buffer is a SCROLLING viewport: an LF on the
    last row scrolls (top row lost) instead of growing the model.
    After a scroll, absolute addressing (CUP/VPA row N) means viewport
    row N, not history row N — an unbounded model parks those writes
    above the visible window, so anchored turns (`after`, pickers)
    time out on a sufficiently chatty session (PR #26 review).
    height=0 keeps the unbounded model: whole history, no scroll."""
    rows: list[dict[int, str]] = [{}]
    r = c = offset = 0        # cursor is viewport-relative; offset = top

    def _row(idx: int) -> dict[int, str]:
        while len(rows) <= idx:
            rows.append({})
        return rows[idx]

    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\x1b":
            nxt = raw[i + 1] if i + 1 < n else ""
            if nxt == "[":                       # CSI
                j = i + 2
                while j < n and raw[j] not in "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz~":
                    j += 1
                if j >= n:
                    break                        # escape cut at chunk edge
                body, final = raw[i + 2:j], raw[j]
                nums = [int(p) if p.isdigit() else 1
                        for p in body.lstrip("?").split(";")]
                def p(k: int, d: int = 1) -> int:
                    return nums[k] if k < len(nums) and nums[k] else d
                if final == "A":                 r = max(0, r - p(0))
                elif final == "B" or final == "e": r += p(0)
                elif final == "C" or final == "a": c += p(0)
                elif final == "D":               c = max(0, c - p(0))
                elif final == "G" or final == "`": c = max(0, p(0) - 1)
                elif final == "d":               r = max(0, p(0) - 1)
                elif final in ("H", "f"):
                    r = max(0, p(0) - 1)
                    c = max(0, p(1) - 1)
                if height and r > height - 1:    # no rows below the
                    r = height - 1               # viewport on a real screen
                if final == "K":                 # EL — clear in row
                    mode = nums[0] if body.isdigit() and nums[0] in (1, 2) else 0
                    cells = _row(r + offset)
                    if mode == 0:
                        rows[r + offset] = {k: v for k, v in cells.items() if k < c}
                    elif mode == 1:
                        rows[r + offset] = {k: v for k, v in cells.items() if k > c}
                    else:
                        rows[r + offset] = {}
                elif final == "J":               # ED — clear the viewport
                    mode = nums[0] if body.isdigit() and nums[0] in (1, 2) else 0
                    top = offset if height else 0
                    bottom = offset + height if height else len(rows)
                    if mode == 2:
                        rows[:] = [{} if top <= idx < bottom else rw
                                   for idx, rw in enumerate(rows)]
                    elif mode == 0:
                        for rr in range(r + offset + 1, bottom):
                            if rr < len(rows):
                                rows[rr] = {}
                        rows[r + offset] = {k: v for k, v in _row(r + offset).items() if k < c}
                    elif mode == 1:
                        for rr in range(top, r + offset):
                            if rr < len(rows):
                                rows[rr] = {}
                        rows[r + offset] = {k: v for k, v in _row(r + offset).items() if k > c}
                i = j + 1
                continue
            if nxt == "]":                       # OSC — drop to BEL/ST
                j = raw.find("\x07", i)
                k = raw.find("\x1b\\", i)
                # ST is TWO bytes (ESC + \): land past BOTH, or the \
                # itself renders as a visible cell and shifts every
                # column after it (PR #26 review).
                ends = [x for x in (j, k + 2 if k != -1 else -1) if x != -1]
                i = min(ends) if ends else n
                continue
            i += 2                               # other 2-byte escapes
            continue
        if ch == "\n":
            if height and r >= height - 1:
                offset += 1                      # viewport scrolls; the
            else:                                # cursor stays on the
                r += 1                           # last row
            c = 0
        elif ch == "\r":
            c = 0
        elif ch == "\b":
            c = max(0, c - 1)
        elif ch == "\t":
            c += 8 - (c % 8)
        elif ch >= " ":                          # printable only
            _row(r + offset)[c] = ch
            c += 1
        i += 1
    # Pad the viewport to height: a trailing LF scrolls a blank row in,
    # and the storage list (grown lazily by writes) may not have it.
    visible = ([_row(idx) for idx in range(offset, offset + height)]
               if height else rows)
    out = []
    for cells in visible:
        if not cells:
            out.append("")
            continue
        width = max(cells)
        out.append("".join(cells.get(k, " ") for k in range(width + 1)))
    # Viewport mode keeps blank trailing rows (a real screen has them);
    # unbounded mode trims them (it renders history, not a screen).
    if height:
        return "\n".join(out)
    return "\n".join(out).rstrip("\n")


def _tail(s: str, n: int) -> str:
    return s[-n:].replace("\n", " ⏎ ")

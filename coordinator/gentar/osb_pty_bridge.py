"""Relay a local pty to an OpenSandbox execd PTY WebSocket.

Spawned by OpenSandboxBenchHost.pty_spawn_args as the pexpect child: the
driver drives this process's pty exactly as it drives `ssh -tt`, and this
process relays bytes to the real pty inside the sandbox (execd's /pty
WebSocket). The remote pty echoes; the local pty is set raw so nothing
echoes twice and control keys (arrows, C-c) travel as bytes to the remote
side — same shape as the ssh transports.

Framing (execd PTY protocol): stdin travels as binary frames prefixed
0x00; stdout arrives as frames prefixed 0x01; JSON text frames carry
control (resize/signal) and lifecycle (connected/exit). Enter inside the
remote pty is CR, but pexpect's sendline newline is translated by the
remote line discipline (ICRNL) — the driver needs no changes.

Usage: python -u osb_pty_bridge.py <execd-base-url> <command>
Exits with the remote shell's exit code when it exits.
"""

import fcntl
import json
import os
import select
import struct
import sys
import termios
import threading
import time
import tty
import urllib.request

from websockets.sync.client import connect

def _pty_size() -> tuple[int, int] | None:
    try:
        packed = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols = struct.unpack("HHHH", packed)[:2]
        return cols or 220, rows or 50
    except OSError:
        return None


def main() -> None:
    base, command = sys.argv[1].rstrip("/"), sys.argv[2]

    req = urllib.request.Request(
        f"{base}/pty", data=json.dumps({"cwd": "/root"}).encode(),
        headers={"Content-Type": "application/json"})
    session = json.load(urllib.request.urlopen(req, timeout=30))["session_id"]

    ws = connect(base.replace("http://", "ws://", 1) + f"/pty/{session}/ws",
                 close_timeout=2)
    frame = ws.recv()
    if not (isinstance(frame, str) and '"role":"holder"' in frame.replace(" ", "")):
        ws.close()
        raise SystemExit(f"unexpected first frame: {frame[:120]}")

    size = _pty_size()
    if size:
        ws.send(json.dumps({"type": "resize", "cols": size[0], "rows": size[1]}))

    exited = threading.Event()
    exit_code = [1]

    def relay_output() -> None:
        """WS frames → local stdout; the exit frame ends the process."""
        sent_command = False
        while True:
            try:
                frame = ws.recv(timeout=30)
            except Exception:
                exited.set()
                return
            if isinstance(frame, bytes):
                if frame[:1] == b"\x01":
                    payload = frame[1:]
                    os.write(1, payload)
                    # The shell is up once its prompt arrived — send the
                    # session command exactly once, then stay a pure relay.
                    if not sent_command:
                        sent_command = True
                        ws.send(b"\x00" + command.encode() + b"\r")
            elif isinstance(frame, str):
                msg = json.loads(frame)
                if msg.get("type") == "exit":
                    exit_code[0] = int(msg.get("exit_code") or 0)
                    exited.set()
                    return

    threading.Thread(target=relay_output, daemon=True).start()

    # Local pty → WS stdin. Raw mode: no local echo (the remote pty echoes),
    # no canonical buffering (arrow keys and C-c must not wait for Enter).
    if os.isatty(0):
        tty.setraw(0)
    while not exited.is_set():
        readable, _, _ = select.select([0], [], [], 0.2)
        if not readable:
            continue
        chunk = os.read(0, 65536)
        if not chunk:
            break   # driver closed stdin; the shell may still be talking
        try:
            ws.send(b"\x00" + chunk)
        except Exception:
            break
    exited.set()
    time.sleep(0.1)   # let the last stdout frames drain
    try:
        ws.close()
    except Exception:
        pass
    raise SystemExit(exit_code[0])


if __name__ == "__main__":
    main()

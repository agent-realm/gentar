"""Typed judgments of a bench screen — the only code that calls TypeSafe.

A semantic turn asks a narrow question about what is on the screen ("does
it ask to confirm deleting beta-sandbox?") and gets a calibrated
probability back, instead of a regex that breaks when the wording changes.
The verdict of a run is still reality's ([[verify.*]]); a judgment only
decides when a turn has seen what it waits for.

What may leave the arena (pilot, 2026-09-26), enforced here and in the
coordinator's guard before any bench exists:

  - only scenarios that declare `[scenario] data = "synthetic"`;
  - only the CURRENT screen — never the transcript, history or files —
    after the run's Redactor has scrubbed it;
  - the audit span keeps the sha256 and length of what was sent, the
    question, the probabilities, the model that answered and the tokens:
    never the screen text.

TypeSafe facts this leans on (docs.typesafe.ai, 2026-09-26, and a probe):
Noul answers are stable across identical requests, Choice answers are not
on an ambiguous screen — so a turn needs the same confident answer on
consecutive polls (`hold`) before it acts. The model is pinned; the
response's model id is recorded. Raw HTTP, not the SDK: the SDK's debug
logging writes request bodies, and its gateway base URLs are other egress
paths.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
KEY_NAME = "TYPESAFE_API_KEY"
SYNTHETIC = "synthetic"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[@-_]")
_BOX = re.compile(r"[─-╿▀-▟]+")      # box drawing, blocks
_BLANKS = re.compile(r"\n{3,}")


class JudgeRefused(RuntimeError):
    """A judgment was not allowed to leave the arena."""


class JudgeUnavailable(RuntimeError):
    """The service did not answer (after retries) or the budget is spent."""


def prepare_screen(screen: str, lines: int = 40) -> str:
    """What a judge sees: the last `lines` rows of the rendered screen, ANSI
    and box-drawing stripped, blank runs collapsed. Less irrelevant state
    means better answers (TypeSafe's own guidance on context rot)."""
    text = _ANSI.sub("", screen or "")
    text = _BOX.sub(" ", text)
    rows = [r.rstrip() for r in text.splitlines()]
    # The rendered screen is full height, with the content on top and blank
    # rows below it: "the last N rows" must mean the last N CONTENT rows,
    # or the judge is sent an empty screen (found on the first live run).
    while rows and not rows[-1]:
        rows.pop()
    text = "\n".join(rows[-lines:]).strip("\n")
    return _BLANKS.sub("\n\n", text)


class Judge:
    """One per run. Refuses unless the scenario is synthetic and a key is set."""

    def __init__(self, scenario, key: str, scrub, spans, subject: str,
                 run_id: str, *, max_calls: int = 200,
                 max_input_tokens: int = 500_000, lines: int = 40,
                 url: str = API_URL, model: str = MODEL,
                 post=None, sleep=time.sleep) -> None:
        if getattr(scenario, "data", "") != SYNTHETIC:
            raise JudgeRefused(
                f"scenario {scenario.name!r} is not declared synthetic "
                f"([scenario] data = \"synthetic\") — no screen may leave the arena")
        if not key:
            raise JudgeRefused(f"{KEY_NAME} is not set")
        self.scenario, self.key, self.scrub = scenario, key, scrub
        self.spans, self.subject, self.run_id = spans, subject, run_id
        self.max_calls, self.max_input_tokens, self.lines = max_calls, max_input_tokens, lines
        self.url, self.model = url, model
        self._post = post or self._http_post
        self._sleep = sleep
        self.calls = 0
        self.input_tokens = 0

    # -- transport ---------------------------------------------------------

    def _http_post(self, body: bytes) -> tuple[dict, dict]:
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), dict(resp.headers)

    def _send(self, body: bytes) -> tuple[dict, dict]:
        last = None
        for attempt in range(3):
            try:
                return self._post(body)
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (408, 429, 500, 502, 503, 504, 529):
                    raise JudgeUnavailable(f"TypeSafe HTTP {exc.code}") from None
                wait = exc.headers.get("retry-after") if exc.headers else None
                try:
                    delay = min(float(wait), 10.0) if wait else 0.5 * 2 ** attempt
                except ValueError:
                    delay = 0.5 * 2 ** attempt
                self._sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                self._sleep(0.5 * 2 ** attempt)
        raise JudgeUnavailable(f"TypeSafe unreachable: {type(last).__name__}")

    # -- questions ---------------------------------------------------------

    def noul(self, screen: str, question: str, *, true: str = "", false: str = "",
             turn: str = "") -> float:
        """P(yes) for a yes/no question about the current screen."""
        q = {"type": "noul", "instructions": question}
        if true or false:
            q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v}
        answer = self._ask(screen, {"q": q}, turn)["q"]
        return float(answer["noul"])

    def _ask(self, screen: str, questions: dict, turn: str) -> dict:
        if self.calls >= self.max_calls or self.input_tokens >= self.max_input_tokens:
            raise JudgeUnavailable(
                f"judge budget spent ({self.calls} calls, {self.input_tokens} input tokens; "
                f"caps {self.max_calls} / {self.max_input_tokens})")
        state = self.scrub(prepare_screen(screen, self.lines))
        if not state.strip():
            # Nothing rendered yet: no screen can be a yes, and asking about
            # an empty one only spends a call (the first live run did).
            return {qid: {"type": q["type"], "noul": 0.0} for qid, q in questions.items()}
        body = json.dumps({"state": {"screen": state}, "model": self.model,
                           "questions": questions}).encode()
        t0 = time.monotonic()
        out, headers = self._send(body)
        ms = int((time.monotonic() - t0) * 1000)
        self.calls += 1
        tokens = int((out.get("usage") or {}).get("input_tokens") or 0)
        self.input_tokens += tokens
        answers = out.get("answers") or {}
        audit = {
            "judge.sent_sha256": hashlib.sha256(state.encode()).hexdigest(),
            "judge.sent_chars": len(state),
            "judge.model": str(out.get("model") or ""),
            "judge.input_tokens": tokens,
            "judge.latency_ms": ms,
            "judge.request_id": str((headers or {}).get("x-typesafe-request-id", "")),
            "judge.turn": turn,
        }
        for qid, q in questions.items():
            audit[f"judge.{qid}.question"] = str(q.get("instructions", ""))[:500]
            a = answers.get(qid) or {}
            if "noul" in a:
                audit[f"judge.{qid}.p_yes"] = str(round(float(a["noul"]), 4))
            if "probabilities" in a:
                audit[f"judge.{qid}.probabilities"] = json.dumps(a["probabilities"], sort_keys=True)
                audit[f"judge.{qid}.confidence"] = str(a.get("confidence", ""))
        self.spans.emit(self.subject, self.run_id, self.scenario.name, "judge.call",
                        attrs={k: str(v) for k, v in audit.items()})
        missing = [q for q in questions if q not in answers]
        if missing:
            raise JudgeUnavailable(f"TypeSafe answered without {missing}")
        return answers

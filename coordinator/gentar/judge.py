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


def egress_allowed(scenario, backend) -> bool:
    """May this backend see this scenario's screens? The pilot's rule B
    (2026-09-26): only a scenario declared synthetic, whatever the backend.
    An in-house backend (egress == "in-house", e.g. a model on the pilot's
    own router) could one day be allowed more — that is a pilot decision,
    and this function is the only place it would change."""
    return getattr(scenario, "data", "") == SYNTHETIC


class TypeSafeBackend:
    """TypeSafe System One over raw HTTP. Calibrated probabilities (the
    thresholds in a judged turn mean something); external egress."""

    name = "typesafe"
    calibrated = True
    egress = "external"

    def __init__(self, key: str, *, url: str = API_URL, model: str = MODEL,
                 post=None, sleep=time.sleep) -> None:
        if not key:
            raise JudgeRefused(f"{KEY_NAME} is not set")
        self.key, self.url, self.model = key, url, model
        self._post = post or self._http_post
        self._sleep = sleep

    def _http_post(self, body: bytes) -> tuple[dict, dict]:
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), dict(resp.headers)

    def ask(self, state: str, questions: dict, attempt) -> dict:
        """-> {answers, model, input_tokens, request_id}. `attempt()` is
        called before EVERY HTTP attempt (the caller's cap may refuse it)."""
        body = json.dumps({"state": {"screen": state}, "model": self.model,
                           "questions": questions}).encode()
        last = None
        for n in range(3):
            attempt()
            try:
                out, headers = self._post(body)
                return {"answers": out.get("answers") or {},
                        "model": str(out.get("model") or ""),
                        "input_tokens": int((out.get("usage") or {}).get("input_tokens") or 0),
                        "request_id": str((headers or {}).get("x-typesafe-request-id", ""))}
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in (408, 429, 500, 502, 503, 504, 529):
                    raise JudgeUnavailable(f"TypeSafe HTTP {exc.code}") from None
                wait = exc.headers.get("retry-after") if exc.headers else None
                try:
                    delay = min(float(wait), 10.0) if wait else 0.5 * 2 ** n
                except ValueError:
                    delay = 0.5 * 2 ** n
                self._sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                self._sleep(0.5 * 2 ** n)
        raise JudgeUnavailable(f"TypeSafe unreachable: {type(last).__name__}")


class Judge:
    """One per run: the POLICY around a backend — who may send (rule B),
    what is sent (the scrubbed current screen), how much (caps), and what is
    kept (a hash-only audit). The backend only transports. A backend
    without calibrated probabilities is refused here: every current use is
    a threshold that decides (p_min, p_act, hold)."""

    def __init__(self, scenario, key: str, scrub, spans, subject: str,
                 run_id: str, *, backend=None, max_calls: int = 200,
                 max_input_tokens: int = 500_000, lines: int = 40,
                 url: str = API_URL, model: str = MODEL,
                 post=None, sleep=time.sleep) -> None:
        if getattr(scenario, "data", "") != SYNTHETIC:
            raise JudgeRefused(
                f"scenario {scenario.name!r} is not declared synthetic "
                f"([scenario] data = \"synthetic\") — no screen may leave the arena")
        self.backend = backend or TypeSafeBackend(key, url=url, model=model,
                                                  post=post, sleep=sleep)
        if not egress_allowed(scenario, self.backend):
            raise JudgeRefused(f"{self.backend.name} may not judge {scenario.name!r}")
        if not self.backend.calibrated:
            raise JudgeRefused(
                f"judge backend {self.backend.name!r} has no calibrated probabilities — "
                f"it cannot decide a threshold (p_min, p_act, hold)")
        self.scenario, self.scrub = scenario, scrub
        self.spans, self.subject, self.run_id = spans, subject, run_id
        # The egress rule's ceiling, whatever the caller passed.
        self.max_calls, self.max_input_tokens = max_calls, max_input_tokens
        self.lines = min(max(int(lines), 1), 40)
        self.calls = 0
        self.input_tokens = 0

    def _attempt(self) -> None:
        # EVERY attempt counts against the cap: a retried or timed-out
        # request may have been processed (and billed) remotely.
        if self.calls >= self.max_calls:
            raise JudgeUnavailable(f"judge budget spent ({self.calls} calls; cap {self.max_calls})")
        self.calls += 1

    # -- questions ---------------------------------------------------------

    def noul(self, screen: str, question: str, *, true: str = "", false: str = "",
             turn: str = "") -> float:
        """P(yes) for a yes/no question about the current screen."""
        q = {"type": "noul", "instructions": question}
        if true or false:
            q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v}
        answer = self._ask(screen, {"q": q}, turn)["q"]
        return float(answer["noul"])

    def choose(self, screen: str, instructions: str, options: dict, *,
               turn: str = "") -> tuple[str, dict, float]:
        """One option of a CLOSED set (id -> description): the judge's pick,
        the probability of every option, and its confidence. It can only
        pick what it is offered — it never writes."""
        q = {"type": "choice", "instructions": instructions, "criteria": dict(options)}
        a = self._ask(screen, {"q": q}, turn)["q"]
        probs = {k: float(v) for k, v in (a.get("probabilities") or {}).items()}
        return str(a.get("choice", "")), probs, float(a.get("confidence") or 0.0)

    def _ask(self, screen: str, questions: dict, turn: str) -> dict:
        if self.calls >= self.max_calls or self.input_tokens >= self.max_input_tokens:
            raise JudgeUnavailable(
                f"judge budget spent ({self.calls} calls, {self.input_tokens} input tokens; "
                f"caps {self.max_calls} / {self.max_input_tokens})")
        # Scrubbed twice: on the raw screen (a value whole before any row is
        # dropped or whitespace trimmed) and on what is sent (a value that
        # only lines up once ANSI codes are stripped). The hash is of the
        # second — exactly the bytes that leave.
        state = self.scrub(prepare_screen(self.scrub(screen or ""), self.lines))
        if not state.strip():
            # Nothing rendered yet: no screen can be a yes (or a pick), and
            # asking about an empty one only spends a call.
            return {qid: ({"type": "noul", "noul": 0.0} if q["type"] == "noul"
                          else {"type": q["type"], "choice": "", "probabilities": {},
                                "confidence": 0.0})
                    for qid, q in questions.items()}
        t0 = time.monotonic()
        out = self.backend.ask(state, questions, self._attempt)
        ms = int((time.monotonic() - t0) * 1000)
        self.input_tokens += out["input_tokens"]
        answers = out["answers"]
        audit = {
            "judge.backend": self.backend.name,
            "judge.egress": self.backend.egress,
            "judge.sent_sha256": hashlib.sha256(state.encode()).hexdigest(),
            "judge.sent_chars": len(state),
            "judge.model": out["model"],
            "judge.input_tokens": out["input_tokens"],
            "judge.latency_ms": ms,
            "judge.request_id": out["request_id"],
            "judge.turn": turn,
        }
        for qid, q in questions.items():
            audit[f"judge.{qid}.question"] = str(q.get("instructions", ""))[:500]
            a = answers.get(qid) or {}
            if "noul" in a:
                audit[f"judge.{qid}.p_yes"] = str(round(float(a["noul"]), 4))
            if "choice" in a:
                audit[f"judge.{qid}.choice"] = str(a["choice"])
            if "probabilities" in a:
                audit[f"judge.{qid}.probabilities"] = json.dumps(a["probabilities"], sort_keys=True)
                audit[f"judge.{qid}.confidence"] = str(a.get("confidence", ""))
        self.spans.emit(self.subject, self.run_id, self.scenario.name, "judge.call",
                        attrs={k: str(v) for k, v in audit.items()})
        missing = [q for q in questions if q not in answers]
        if missing:
            raise JudgeUnavailable(f"{self.backend.name} answered without {missing}")
        return answers

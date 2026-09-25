"""Span writer — gauntlet schema ported (phase 5).

run = trace, step = span, straight into ClickHouse; no OTel SDK in the
harness (gauntlet policy). Inserts are best-effort: telemetry never
fails a test.

Shape ported from agent-gauntlet lib/events.sh:
- subject is a first-class column (scenario names are subject-local);
- a long step is TWO rows sharing span_id — `running` when it opens,
  terminal (pass/fail/skip/error) when it ends — so a live dashboard
  sees in-flight steps; argMax(ts_start) picks the terminal row;
- trace_id is sha256(subject \\0 run_id)[:32]: stable, derived, never
  stored — the run_id stays human-readable, the hex form exists so rows
  export as real OTel spans without a migration;
- ORDER BY (subject, scenario, ts_start, run_id): subject-leading, so
  per-component queries read contiguous parts.
"""

import contextlib
import contextvars
import datetime
import hashlib
import json
import secrets
import uuid

import clickhouse_connect

from gentar.config import Config

COLUMNS = [
    "subject", "run_id", "trace_id", "span_id", "parent_span",
    "scenario", "step", "status", "ts_start", "ts_end", "duration_ms",
    "attrs", "detail",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS {db}.spans (
    subject      LowCardinality(String),
    run_id       String,
    trace_id     String,
    span_id      String,
    parent_span  String,
    scenario     LowCardinality(String),
    step         LowCardinality(String),
    status       Enum8('running'=0,'pass'=1,'fail'=2,'skip'=3,'error'=4),
    ts_start     DateTime64(9),
    ts_end       Nullable(DateTime64(9)),
    duration_ms  Nullable(UInt64),
    attrs        String,
    detail       String
) ENGINE = MergeTree
ORDER BY (subject, scenario, ts_start, run_id)
"""

LATEST_VIEW = """
CREATE VIEW IF NOT EXISTS {db}.latest_scenario_status AS
SELECT
    subject,
    run_id,
    scenario,
    argMax(status, ts_start)      AS status,
    argMax(step, ts_start)        AS current_step,
    argMax(duration_ms, ts_start) AS last_duration_ms,
    argMax(detail, ts_start)      AS last_detail,
    min(ts_start)                 AS run_started,
    max(ts_start)                 AS last_event
FROM {db}.spans
GROUP BY subject, run_id, scenario
"""


AGENT_TURN_COLUMNS = ["subject", "run_id", "scenario", "session", "turn", "model",
                      "input_tokens", "output_tokens", "cache_read_tokens",
                      "cache_creation_tokens", "tool_calls"]
AGENT_TOOL_COLUMNS = ["subject", "run_id", "scenario", "session", "tool",
                      "duration_ms", "is_error", "completed"]

AGENT_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS {db}.agent_turns (
    subject LowCardinality(String), run_id String, scenario LowCardinality(String),
    session UInt16, turn UInt32, model LowCardinality(String),
    input_tokens UInt64, output_tokens UInt64, cache_read_tokens UInt64,
    cache_creation_tokens UInt64, tool_calls UInt32{extra}
) ENGINE = MergeTree ORDER BY (subject, scenario, run_id, session, turn)""",
    """CREATE TABLE IF NOT EXISTS {db}.agent_tools (
    subject LowCardinality(String), run_id String, scenario LowCardinality(String),
    session UInt16, tool LowCardinality(String), duration_ms Nullable(UInt64),
    is_error Bool, completed Bool{extra}
) ENGINE = MergeTree ORDER BY (subject, scenario, run_id, session)""",
]

# History rows carry where the run came from; the arena's own tables do not
# need it (one arena = one run).
CI_COLUMNS = ["ci_repo", "ci_run_id", "ci_run_attempt", "ci_ref", "ci_sha",
              "ci_event", "engine"]
CI_EXTRA = "".join(f",\n    {c} LowCardinality(String)" for c in CI_COLUMNS)

# Steps whose detail is an agent's screen — never stored in history.
PRIVATE_DETAIL_STEPS = {"driver.transcript"}


def trace_id(subject: str, run_id: str) -> str:
    """Stable OTel-shaped trace id for (subject, run_id) — hashed over
    both because the shared table permits run_id reuse across subjects."""
    digest = hashlib.sha256(f"{subject}\x00{run_id}".encode()).hexdigest()
    return digest[:32]


def _now_ms() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)


class History:
    """The persistent store every arena also writes to (GENTAR_HISTORY_URL).

    Write-only identity; the schema is the deployment's (history/), never
    created from here. Every row is scrubbed first — the bench-host
    settings and the run's declared credentials, in every encoding and any
    8+ char prefix — and a transcript step keeps only its length: the
    store is shared across subjects and read by dashboards. Best-effort:
    a failure is counted and said once, never raised."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = None
        self.failed = 0
        from gentar.redaction import scrubber
        self._scrub = scrubber([])
        self._base_secrets = [(n, v) for n, v in (
            ("GENTAR_BENCH_HOST", cfg.bench_host), ("GENTAR_BENCH_USER", cfg.bench_user),
            ("GENTAR_BENCH_JUMP", cfg.bench_jump), ("GENTAR_TART_HOST", cfg.tart_host),
            ("GENTAR_TART_USER", cfg.tart_user),
            ("GENTAR_HISTORY_PASSWORD", cfg.history_password)) if v]
        self._scrub = scrubber(self._base_secrets)
        if not cfg.history_url:
            return
        try:
            self.client = clickhouse_connect.get_client(
                dsn=cfg.history_url, username=cfg.history_user,
                password=cfg.history_password, database=cfg.history_db,
                connect_timeout=5, send_receive_timeout=10)
        except Exception as exc:
            print(f"warn: history store unavailable — this run is not kept: "
                  f"{type(exc).__name__}")
            self.client = None
        self.ci = [cfg.ci.get(c) or ("local" if c == "ci_repo" else "")
                   for c in CI_COLUMNS[:-1]] + [cfg.engine_sha]

    def redact_values(self, named_values) -> None:
        """Add the run's credential values (name, value) to what is scrubbed."""
        from gentar.redaction import scrubber
        self._scrub = scrubber(self._base_secrets + [(n, v) for n, v in named_values if v])

    def scrub(self, text: str) -> str:
        return self._scrub(text)

    def insert(self, table: str, columns: list, rows: list) -> None:
        if self.client is None or not rows:
            return
        # Every text column, not only detail/attrs: names and CI metadata
        # come from files and environments too (agy review). Numbers pass.
        clean = [[self.scrub(v) if isinstance(v, str) else v for v in r + self.ci]
                 for r in rows]
        try:
            self.client.insert(f"{self.cfg.history_db}.{table}",
                               clean,
                               column_names=columns + CI_COLUMNS)
        except Exception as exc:
            self.failed += len(rows)
            if self.failed == len(rows):          # say it once per run
                print(f"warn: history write failed (the run is unaffected): "
                      f"{type(exc).__name__}")


_OTLP_STATUS = {"pass": 1, "fail": 2, "error": 2}      # OK, ERROR; else UNSET


def _kv(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


# The exporters made inside the current `exporting()` block — per context,
# so one run (or thread, or test) never flushes another's.
_OPEN: contextvars.ContextVar = contextvars.ContextVar("gentar_otlp_open", default=None)


@contextlib.contextmanager
def exporting():
    """Flush every exporter made inside the block when it exits, however it
    exits. The coordinator's run() wraps EVERY terminal path in it
    (refusals and quarantine included), so a run that never reached a bench
    still leaves its trace — and a flush can never replace the verdict."""
    opened: list = []
    token = _OPEN.set(opened)
    try:
        yield
    finally:
        _OPEN.reset(token)
        for o in opened:
            try:
                o.flush()
            except Exception:
                pass


class Otlp:
    """Every finished span, as OTLP/HTTP JSON, to the ARENA's collector.

    Only when the adopting repo declared a telemetry destination
    (GENTAR_OTLP_EXPORT, compose.export.yml): spans go to that collector's
    `otlp/scrubbed` receiver, the only input its export pipeline reads. So
    this class never talks to anything outside the arena; the destination
    and its key live only in the collector.

    One trace per run: the `scenario` span is the root, every other span of
    the run hangs under it, and the agent's session -> turns -> tool calls
    come from its transcript as numbers only. Text is the history scrubber's
    (declared credentials, bench-host settings, every encoding, 8+ char
    prefixes) and a transcript step keeps only its length. Buffered, flushed
    at the end of the run; best-effort — never the verdict.
    """

    def __init__(self, cfg: Config, scrub) -> None:
        self.cfg = cfg
        self.scrub = scrub
        self.buf: dict = {}          # subject -> [span, ...]
        self.roots: dict = {}        # (subject, run_id) -> root span id
        self.failed = False
        # A refusal has no run id yet: its span is a one-span trace of its own.
        self.loose_trace = secrets.token_hex(16)
        opened = _OPEN.get()
        if opened is not None:
            opened.append(self)

    def root(self, subject, run_id, span_id):
        self.roots[(subject, run_id)] = span_id

    def span(self, subject, run_id, scenario, span_id, parent, name, status,
             start_ns, end_ns, attrs=None, detail="") -> None:
        if not self.cfg.otlp_scrubbed_endpoint:
            return
        if not parent and name != "scenario":
            parent = self.roots.get((subject, run_id), "")
        text = (f"(agent transcript, {len(detail or '')} chars — not exported)"
                if name in PRIVATE_DETAIL_STEPS else self.scrub(detail or ""))
        a = [_kv("gentar.run_id", run_id), _kv("gentar.scenario", scenario),
             _kv("gentar.status", status)]
        for k, v in sorted((attrs or {}).items()):
            a.append(_kv(f"gentar.{k}", self.scrub(v) if isinstance(v, str) else v))
        if text:
            a.append(_kv("gentar.detail", text))
        sp = {"traceId": trace_id(subject, run_id) if run_id else self.loose_trace,
              "spanId": span_id,
              "name": name, "kind": 1,
              "startTimeUnixNano": str(start_ns), "endTimeUnixNano": str(end_ns),
              "attributes": a,
              "status": {"code": _OTLP_STATUS.get(status, 0)}}
        if parent:
            sp["parentSpanId"] = parent
        if sp["status"]["code"] == 2 and text:
            sp["status"]["message"] = text[:200]
        self.buf.setdefault(subject, []).append(sp)
        if sum(len(v) for v in self.buf.values()) >= 200:
            self.flush()

    def resource(self, subject) -> list:
        ci = [(c, self.cfg.ci.get(c) or ("local" if c == "ci_repo" else ""))
              for c in CI_COLUMNS[:-1]]
        return ([_kv("service.name", subject), _kv("gentar.engine", self.cfg.engine_sha)]
                + [_kv(f"gentar.{c}", self.scrub(v)) for c, v in ci if v])

    def payload(self) -> dict:
        return {"resourceSpans": [{
            "resource": {"attributes": self.resource(subject)},
            "scopeSpans": [{"scope": {"name": "gentar"}, "spans": spans}]}
            for subject, spans in self.buf.items() if spans]}

    def flush(self) -> None:
        if not self.buf or not self.cfg.otlp_scrubbed_endpoint:
            return
        try:
            body = json.dumps(self.payload()).encode()
        except Exception:
            body = None
        self.buf = {}
        if body is not None:
            self._post(body)

    def relay(self, subject, run_id, raw: str) -> None:
        """A bench's self-report (OTLP/HTTP JSON), through the scrubbed door.

        The raw file still goes to the collector's local-only receiver; this
        copy is the one that may leave. It must parse as OTLP JSON (anything
        else stays local), and then every decoded string — keys and values —
        is scrubbed: scrubbing the text before parsing would miss a value
        written with JSON escapes, which parsing turns back into the value. Its spans join the run's
        trace (parentless ones under the scenario root) and its resource
        names the subject when it named no service. Best-effort.
        """
        if not self.cfg.otlp_scrubbed_endpoint or not (raw or "").strip():
            return
        try:
            doc = self._scrub_tree(json.loads(raw))
            groups = doc.get("resourceSpans") if isinstance(doc, dict) else None
            if not isinstance(groups, list):
                return
            tid, root = trace_id(subject, run_id), self.roots.get((subject, run_id), "")
            ours = {a["key"]: a for a in self.resource(subject)}
            for rs in groups:
                attrs = rs.setdefault("resource", {}).setdefault("attributes", [])
                have = {a.get("key") for a in attrs if isinstance(a, dict)}
                attrs.extend(a for k, a in ours.items() if k not in have)
                if "gentar.run_id" not in have:
                    attrs.append(_kv("gentar.run_id", run_id))
                for ss in rs.get("scopeSpans") or []:
                    for sp in ss.get("spans") or []:
                        sp["traceId"] = tid
                        if not sp.get("parentSpanId") and root:
                            sp["parentSpanId"] = root
            body = json.dumps({"resourceSpans": groups}).encode()
        except Exception:
            return
        self._post(body)

    def _scrub_tree(self, node):
        if isinstance(node, str):
            return self.scrub(node)
        if isinstance(node, list):
            return [self._scrub_tree(x) for x in node]
        if isinstance(node, dict):
            return {self.scrub(k): self._scrub_tree(v) for k, v in node.items()}
        return node

    def _post(self, body: bytes) -> None:
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self.cfg.otlp_scrubbed_endpoint.rstrip('/')}/v1/traces", data=body,
                method="POST", headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as exc:
            if not self.failed:
                print(f"warn: OTLP export to the arena collector failed "
                      f"(the run is unaffected): {type(exc).__name__}")
            self.failed = True


class Spans:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.history = History(cfg)
        self.otlp = Otlp(cfg, self.history.scrub)
        self.client = None
        try:
            self.client = clickhouse_connect.get_client(
                dsn=cfg.clickhouse_url,
                username=cfg.clickhouse_user,
                password=cfg.clickhouse_password,
            )
            self._ensure_schema()
        except Exception as exc:
            # Telemetry never fails a test (gauntlet policy, ported):
            # degrade to no-op spans rather than aborting the run.
            print(f"warn: telemetry unavailable — spans will not be recorded: {exc}")
            self.client = None

    def _ensure_schema(self) -> None:
        db = self.cfg.clickhouse_db
        # A phase-1..4 table has the old minimal shape; IF NOT EXISTS
        # would keep it and every insert would fail forever. Dev-stage
        # arena: detect the stale shape and drop it (history is
        # disposable), else create idempotently.
        existing = self.client.query(
            f"SELECT name FROM system.columns "
            f"WHERE database='{db}' AND table='spans' ORDER BY position"
        ).result_columns
        names = list(existing[0]) if existing else []
        if names and names != COLUMNS:
            print("warn: spans table has a stale shape — recreating "
                  "(old run history dropped)")
            self.client.command(f"DROP TABLE IF EXISTS {db}.spans")
        self.client.command(SCHEMA.format(db=db))
        # View: NOT OR REPLACE (gauntlet note — replace forces a
        # DROP-holding tmp table); a definition change is an admin
        # migration.
        try:
            self.client.command(LATEST_VIEW.format(db=db))
        except Exception as exc:
            print(f"warn: latest_scenario_status view not created: {exc}")
        for ddl in AGENT_SCHEMA:
            self.client.command(ddl.format(db=db, extra=""))

    def ensure_schema(self) -> None:
        pass  # ensured at client setup; kept for call-site stability

    # -- write paths -----------------------------------------------------

    def _insert(self, subject: str, run_id: str, span_id: str, parent: str,
                scenario: str, step: str, status: str, t0_ms: int,
                t1_ms: int | None, duration_ms: int | None,
                attrs: dict | None, detail: str) -> None:
        def ts(ms: int) -> datetime.datetime:
            base = datetime.datetime.fromtimestamp(
                ms / 1000.0, tz=datetime.timezone.utc)
            # 9 decimals: column is DateTime64(9) because OTel timestamps
            # are nanoseconds; harness measures milliseconds, so the last
            # six digits are honest zeros (gauntlet note, ported).
            return base.replace(microsecond=(ms % 1000) * 1000)
        row = [
            subject, run_id, trace_id(subject, run_id), span_id, parent,
            scenario, step, status, ts(t0_ms),
            ts(t1_ms) if t1_ms is not None else None,
            duration_ms,
            json.dumps(attrs or {}, sort_keys=True),
            detail,
        ]
        if status != "running":        # a finished span: export it once
            end_ns = (t1_ms if t1_ms is not None else t0_ms) * 1_000_000
            start_ns = end_ns - (duration_ms or 0) * 1_000_000
            self.otlp.span(subject, run_id, scenario, span_id, parent, step,
                           status, start_ns, end_ns, attrs, detail)
        h = self.history
        hdetail = (f"(agent transcript, {len(detail or '')} chars — not kept)"
                   if step in PRIVATE_DETAIL_STEPS else h.scrub(detail))
        h.insert("spans", COLUMNS, [row[:11] + [h.scrub(row[11]), hdetail]])
        if self.client is None:
            return
        try:
            self.client.insert(
                f"{self.cfg.clickhouse_db}.spans", [row],
                column_names=COLUMNS,
            )
        except Exception as exc:  # best-effort, never fails a test
            print(f"warn: span {step} not recorded: {exc}")

    def step_start(self, subject: str, run_id: str, scenario: str,
                   step: str, parent: str = "",
                   attrs: dict | None = None) -> str:
        """Open a two-row span; returns its span_id."""
        span_id = secrets.token_hex(8)
        if step == "scenario" and not parent:
            self.otlp.root(subject, run_id, span_id)
        self._insert(subject, run_id, span_id, parent, scenario, step,
                     "running", _now_ms(), None, None, attrs, "")
        return span_id

    def step_end(self, subject: str, run_id: str, scenario: str,
                 span_id: str, step: str, status: str, t0_ms: int,
                 t1_ms: int | None = None, parent: str = "",
                 attrs: dict | None = None, detail: str = "") -> None:
        t1_ms = t1_ms if t1_ms is not None else _now_ms()
        duration = max(0, t1_ms - t0_ms)
        self._insert(subject, run_id, span_id, parent, scenario, step,
                     status, t1_ms, t1_ms, duration, attrs, detail)

    def emit(self, subject: str, run_id: str, scenario: str, step: str,
             status: str = "pass", attrs: dict | None = None,
             detail: str = "") -> None:
        """Instant single-row span (terminal from birth) — asserts,
        transcripts, one-shot events."""
        now = _now_ms()
        self._insert(subject, run_id, secrets.token_hex(8), "", scenario,
                     step, status, now, now, 0, attrs, detail)


def _agent_spans(spans: "Spans", subject, run_id, scenario, turns, tools) -> None:
    """The agent's session -> turns -> tool calls as OTLP spans under the
    run's root, with real timestamps. Numbers and labels only (agentstats
    guarantees it); nothing to scrub."""
    o = spans.otlp
    for session in sorted({t["session"] for t in turns}):
        ts = [t for t in turns if t["session"] == session]
        us = [u for u in tools if u["session"] == session]
        # A turn lasts until its tools' results arrive, not only until its
        # last assistant message — else a tool span outlives its parent.
        tool_end: dict = {}
        for u in us:
            if u.get("end_ns") and u.get("turn") is not None:
                tool_end[u["turn"]] = max(tool_end.get(u["turn"], 0), u["end_ns"])
        ts = [dict(t, end_ns=max(t.get("end_ns") or 0,
                                 tool_end.get(t["turn"], 0) if t.get("turn") is not None else 0))
              for t in ts]
        starts = [x["start_ns"] for x in ts + us if x.get("start_ns")]
        ends = [x["end_ns"] for x in ts + us if x.get("end_ns")]
        if not starts:
            continue
        sid = secrets.token_hex(8)
        o.span(subject, run_id, scenario, sid, "", "agent.session", "pass",
               min(starts), max(ends + starts),
               attrs={"agent.turns": len(ts), "agent.tool_calls": len(us),
                      "agent.input_tokens": sum(t["input_tokens"] for t in ts),
                      "agent.output_tokens": sum(t["output_tokens"] for t in ts)})
        turn_ids = {}
        for t in ts:
            tid = turn_ids[t["turn"]] = secrets.token_hex(8)
            o.span(subject, run_id, scenario, tid, sid, "agent.turn", "pass",
                   t["start_ns"], t["end_ns"] or t["start_ns"],
                   attrs={"agent.model": t["model"],
                          "agent.input_tokens": t["input_tokens"],
                          "agent.output_tokens": t["output_tokens"],
                          "agent.cache_read_tokens": t["cache_read_tokens"],
                          "agent.cache_creation_tokens": t["cache_creation_tokens"],
                          "agent.tool_calls": t["tool_calls"]})
        for u in us:
            if not u.get("start_ns"):
                continue
            o.span(subject, run_id, scenario, secrets.token_hex(8),
                   turn_ids.get(u.get("turn"), sid), "agent.tool",
                   "error" if u["is_error"] else "pass",
                   u["start_ns"], u["end_ns"] or u["start_ns"],
                   attrs={"agent.tool": u["tool"], "agent.completed": u["completed"]})


def agent_rows(spans: "Spans", subject: str, run_id: str, scenario: str,
               turns: list, tools: list) -> None:
    """agentstats rows into the arena's tables and history. Numbers and
    labels only — by construction of agentstats, so nothing to scrub."""
    t_rows = [[subject, run_id, scenario, t["session"], t["turn"], t["model"],
               t["input_tokens"], t["output_tokens"], t["cache_read_tokens"],
               t["cache_creation_tokens"], t["tool_calls"]] for t in turns]
    u_rows = [[subject, run_id, scenario, t["session"], t["tool"],
               t["duration_ms"], t["is_error"], t["completed"]] for t in tools]
    _agent_spans(spans, subject, run_id, scenario, turns, tools)
    for table, cols, rows in (("agent_turns", AGENT_TURN_COLUMNS, t_rows),
                              ("agent_tools", AGENT_TOOL_COLUMNS, u_rows)):
        if not rows:
            continue
        spans.history.insert(table, cols, rows)
        if spans.client is not None:
            try:
                spans.client.insert(f"{spans.cfg.clickhouse_db}.{table}", rows,
                                    column_names=cols)
            except Exception as exc:
                print(f"warn: {table} not recorded: {type(exc).__name__}")


def new_run_id(prefix: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"

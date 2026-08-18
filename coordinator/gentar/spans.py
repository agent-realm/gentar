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


def trace_id(subject: str, run_id: str) -> str:
    """Stable OTel-shaped trace id for (subject, run_id) — hashed over
    both because the shared table permits run_id reuse across subjects."""
    digest = hashlib.sha256(f"{subject}\x00{run_id}".encode()).hexdigest()
    return digest[:32]


def _now_ms() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)


class Spans:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
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

    def ensure_schema(self) -> None:
        pass  # ensured at client setup; kept for call-site stability

    # -- write paths -----------------------------------------------------

    def _insert(self, subject: str, run_id: str, span_id: str, parent: str,
                scenario: str, step: str, status: str, t0_ms: int,
                t1_ms: int | None, duration_ms: int | None,
                attrs: dict | None, detail: str) -> None:
        if self.client is None:
            return
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


def new_run_id(prefix: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"

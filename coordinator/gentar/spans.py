"""Span writer — run = trace, step = span, straight into ClickHouse.
No OTel SDK in the harness (gauntlet policy, ported). Inserts are
best-effort: telemetry never fails a test.

Schema is phase-1 minimal but keyed like the gauntlet shape (run_id,
ts, name, attrs) so the phase-5 port (18 provenance fields,
subject-leading sort) is an ALTER, not a rewrite.
"""

import datetime
import uuid

import clickhouse_connect

from gentar.config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS {db}.spans (
    ts        DateTime64(9, 'UTC') DEFAULT now64(9),
    run_id    String,
    span_name String,
    status    LowCardinality(String) DEFAULT 'ok',
    attrs     Map(String, String),
    body      String DEFAULT ''
) ENGINE = MergeTree
ORDER BY (run_id, ts)
"""


class Spans:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = clickhouse_connect.get_client(
            dsn=cfg.clickhouse_url,
            username=cfg.clickhouse_user,
            password=cfg.clickhouse_password,
        )

    def ensure_schema(self) -> None:
        self.client.command(SCHEMA.format(db=self.cfg.clickhouse_db))

    def emit(self, run_id: str, name: str, status: str = "ok",
             attrs: dict[str, str] | None = None, body: str = "") -> None:
        try:
            self.client.insert(
                f"{self.cfg.clickhouse_db}.spans",
                [[
                    datetime.datetime.now(datetime.timezone.utc),
                    run_id,
                    name,
                    status,
                    {str(k): str(v) for k, v in (attrs or {}).items()},
                    body,
                ]],
                column_names=["ts", "run_id", "span_name", "status", "attrs", "body"],
            )
        except Exception as exc:  # best-effort, never fails a test
            print(f"warn: span {name} not recorded: {exc}")


def new_run_id(prefix: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"

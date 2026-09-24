-- gentar history schema. Applied by deploy.sh as gentar_admin; idempotent.
-- Mirrors the arena's spans/agent tables plus where each run came from.
CREATE DATABASE IF NOT EXISTS gentar_history;

CREATE TABLE IF NOT EXISTS gentar_history.spans (
    subject LowCardinality(String), run_id String, trace_id String,
    span_id String, parent_span String, scenario LowCardinality(String),
    step LowCardinality(String),
    status Enum8('running'=0,'pass'=1,'fail'=2,'skip'=3,'error'=4),
    ts_start DateTime64(9), ts_end Nullable(DateTime64(9)),
    duration_ms Nullable(UInt64), attrs String, detail String,
    ci_repo LowCardinality(String), ci_run_id LowCardinality(String),
    ci_run_attempt LowCardinality(String), ci_ref LowCardinality(String),
    ci_sha LowCardinality(String), ci_event LowCardinality(String),
    engine LowCardinality(String)
) ENGINE = MergeTree ORDER BY (subject, scenario, ts_start, run_id);

CREATE TABLE IF NOT EXISTS gentar_history.agent_turns (
    subject LowCardinality(String), run_id String, scenario LowCardinality(String),
    session UInt16, turn UInt32, model LowCardinality(String),
    input_tokens UInt64, output_tokens UInt64, cache_read_tokens UInt64,
    cache_creation_tokens UInt64, tool_calls UInt32,
    ci_repo LowCardinality(String), ci_run_id LowCardinality(String),
    ci_run_attempt LowCardinality(String), ci_ref LowCardinality(String),
    ci_sha LowCardinality(String), ci_event LowCardinality(String),
    engine LowCardinality(String)
) ENGINE = MergeTree ORDER BY (subject, scenario, run_id, session, turn);

CREATE TABLE IF NOT EXISTS gentar_history.agent_tools (
    subject LowCardinality(String), run_id String, scenario LowCardinality(String),
    session UInt16, tool LowCardinality(String), duration_ms Nullable(UInt64),
    is_error Bool, completed Bool,
    ci_repo LowCardinality(String), ci_run_id LowCardinality(String),
    ci_run_attempt LowCardinality(String), ci_ref LowCardinality(String),
    ci_sha LowCardinality(String), ci_event LowCardinality(String),
    engine LowCardinality(String)
) ENGINE = MergeTree ORDER BY (subject, scenario, run_id, session);

CREATE VIEW IF NOT EXISTS gentar_history.latest_scenario_status AS
SELECT subject, run_id, scenario,
       argMax(status, ts_start) AS status, argMax(step, ts_start) AS current_step,
       argMax(duration_ms, ts_start) AS last_duration_ms,
       argMax(detail, ts_start) AS last_detail,
       min(ts_start) AS run_started, max(ts_start) AS last_event,
       any(ci_repo) AS ci_repo, any(ci_run_id) AS ci_run_id, any(ci_ref) AS ci_ref
FROM gentar_history.spans GROUP BY subject, run_id, scenario;

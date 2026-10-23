# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ramazan Polat
"""Agent self-report: the bench's OTLP drop file, relayed to otelcol, and,
for a scenario that asks (`[verify] self_report = true`), proven to land.

Software inside a bench writes an OTLP/HTTP-JSON body to
$WORKSPACE_DIR/gentar-otlp.json; the coordinator relays it to otelcol, which
writes otel_traces in the arena's ClickHouse, where one SQL joins it with the
harness spans on gentar.run_id. For every other scenario the relay stays
best-effort (coordinator._relay_agent_spans). otlp-selfreport used to check
only that the file was non-empty, so a collector that rejected the body, or a
span ClickHouse never kept, still passed (ground-up review A8, SC05).
"""

import time
import urllib.request

from gentar.asserts import AssertResult

DROP = "$WORKSPACE_DIR/gentar-otlp.json"
CHECK = "otlp-join run_id"
DEADLINE = 30                     # seconds for the span to be queryable
POLL = 2

# Run ids whose drop file this module has SENT, whatever came of it: the
# run's own best-effort relay (in its `finally`) skips them, so neither the
# scrubbed export nor the collector gets a span twice. Marked before the
# sends, not after a success: a POST that failed or timed out may still
# have been accepted, and the export copy has left already (Codex on #99).
RELAYED: set[str] = set()


def relay(bench, run_id: str, spans, cfg, subject: str, name: str) -> tuple[bool, str]:
    """Send the drop file to otelcol once. (ok, detail)."""
    if run_id in RELAYED:
        return True, "already relayed"
    if not cfg.otlp_endpoint:
        return False, "no OTLP endpoint configured (otelcol is not part of this arena)"
    rc, out = bench.exec(run_id, f"cat \"{DROP}\" 2>/dev/null")
    if rc != 0 or not out.strip():
        return False, f"no self-report at {DROP}"
    RELAYED.add(run_id)                              # attempted: never resent
    spans.otlp.relay(subject, run_id, out)           # the scrubbed export door
    try:
        req = urllib.request.Request(f"{cfg.otlp_endpoint}/v1/traces", data=out.encode(),
                                     method="POST",
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:                          # noqa: BLE001
        return False, f"relay to {cfg.otlp_endpoint} failed: {exc}"
    spans.emit(subject, run_id, name, "otlp.relay", "pass",
               attrs={"endpoint": cfg.otlp_endpoint},
               detail=f"relayed {len(out)} bytes of agent self-report")
    return True, f"relayed {len(out)} bytes"


def join_sql(db: str) -> str:
    """Agent spans in otel_traces joined to this run's harness spans."""
    return ("SELECT count() FROM (SELECT DISTINCT t.SpanId "
            f"FROM {db}.otel_traces AS t INNER JOIN "
            f"(SELECT DISTINCT run_id FROM {db}.spans WHERE run_id = {{run_id:String}}) AS s "
            "ON t.ResourceAttributes['gentar.run_id'] = s.run_id)")


def joined(spans, cfg, run_id: str, deadline: float = DEADLINE,
           sleep=time.sleep, clock=time.monotonic) -> tuple[bool, str]:
    """Poll until the join finds a span or the deadline passes. (ok, detail)."""
    if spans.client is None:
        return False, "no ClickHouse client: the join cannot be checked"
    if not run_id:
        # an empty run id would join every trace that carries none (agy)
        return False, "no run id: the join cannot be checked"
    end, last = clock() + deadline, ""
    while True:
        try:
            n = int(spans.client.query(join_sql(cfg.clickhouse_db),
                                       parameters={"run_id": run_id}).result_rows[0][0])
            if n > 0:
                return True, f"{n} agent span(s) joined the run's harness spans on run_id"
            last = "no agent span yet"
        except Exception as exc:                      # noqa: BLE001
            last = f"query failed: {type(exc).__name__}: {exc}"[:300]
        if clock() >= end:
            return False, (f"no agent span of run {run_id} in otel_traces joined its "
                           f"harness spans after {deadline:g}s ({last})")
        sleep(POLL)


def check(bench, run_id: str, spans, cfg, subject: str, name: str,
          deadline: float = DEADLINE, sleep=time.sleep) -> AssertResult:
    ok, detail = relay(bench, run_id, spans, cfg, subject, name)
    if ok:
        ok, detail = joined(spans, cfg, run_id, deadline, sleep)
    return AssertResult(CHECK, ok, detail)

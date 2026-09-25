#!/usr/bin/env python3
"""dashboard/generate.py — render gentar telemetry into ONE self-contained
HTML dashboard. Stdlib-only (urllib for HTTP). Ported from agent-gauntlet
dashboard/generate.py; endpoint resolution swapped for gentar's env config
(the arena's ClickHouse is a compose service, not a tunnel).

Usage:
    docker compose run --rm dashboard
    python3 dashboard/generate.py --runs 20 --out ~/dash.html
    python3 dashboard/generate.py --watch
"""
import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request

# /out is the compose service's mount. Run on a host (a kept arena, the
# kit's printed command) there is no /out and a non-root user cannot make
# one, so fall back to dashboard/out/ beside this script (gitignored).
DEFAULT_OUT = ("/out/dashboard.html"
               if os.path.isdir("/out") and os.access("/out", os.W_OK)
               else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "out", "dashboard.html"))

# Status palette (dataviz skill, references/palette.md -- fixed, never
# themed). pass=good, fail/error=critical-ish, running=warning, skip=neutral.
STATUS_COLOR = {
    "pass": "#0ca30c",
    "running": "#fab219",
    "fail": "#d03b3b",
    "error": "#ec835a",
    "skip": "#8a8a86",
}
STATUS_DARK_TEXT = {"pass": "#ffffff", "running": "#141400", "fail": "#ffffff", "error": "#141400", "skip": "#ffffff"}


def resolve_ch():
    # An explicit URL wins. Otherwise follow the arena's host binding: an
    # adopter that moved it aside (GENTAR_CLICKHOUSE_HOST_PORT=8126, as the
    # kit workflow suggests) would else read 8123 -- and on a host where
    # another arena holds 8123, render THAT arena's runs. (claude-playbooks.)
    port = os.environ.get("GENTAR_CLICKHOUSE_HOST_PORT") or "8123"
    url = os.environ.get("GENTAR_CLICKHOUSE_URL") or f"http://localhost:{port}"
    user = os.environ.get("GENTAR_CLICKHOUSE_USER", "gentar")
    pw = os.environ.get("GENTAR_CLICKHOUSE_PASSWORD", "gentar")
    db = os.environ.get("GENTAR_CLICKHOUSE_DB", "gentar")
    return url, user, pw, db


def ch_query(url, user, pw, sql):
    req = urllib.request.Request(url + "/", data=(sql + "\nFORMAT JSON").encode("utf-8"))
    if user or pw:
        import base64
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # ClickHouse answers an unknown table with HTTP 404 (code 60). A
        # dashboard started with the arena races the coordinator's schema
        # creation; that is a wait, not a failure.
        detail = e.read().decode("utf-8", "replace")
        if e.code == 404 and ("UNKNOWN_TABLE" in detail or "Code: 60" in detail):
            print("generate.py: waiting for the arena to create its tables", file=sys.stderr)
        else:
            print(f"generate.py: WARNING: query failed: {e}: {detail[:200]}", file=sys.stderr)
        return []
    except urllib.error.URLError as e:
        print(f"generate.py: WARNING: query failed: {e}", file=sys.stderr)
        return []
    try:
        return json.loads(body).get("data", [])
    except json.JSONDecodeError:
        print(f"generate.py: WARNING: non-JSON response: {body[:200]}", file=sys.stderr)
        return []


def _sql_str(v):
    """A ClickHouse string literal. Apostrophes are escaped, not deleted
    (gauntlet note: deleting silently failed to match identifiers)."""
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def fetch(url, user, pw, db, n_runs, since=0):
    # A run is identified by (subject, run_id), never run_id alone --
    # the pair is carried as two fields, never joined into one string.
    runs = ch_query(url, user, pw, f"""
        SELECT subject, run_id,
               min(run_started) AS started,
               max(last_event) AS last_event,
               count() AS scenarios,
               countIf(status='pass') AS n_pass,
               countIf(status='fail') AS n_fail,
               countIf(status='running') AS n_running,
               countIf(status='skip') AS n_skip,
               countIf(status='error') AS n_error
        FROM {db}.latest_scenario_status
        WHERE toUnixTimestamp(run_started) >= {int(since)}
        GROUP BY subject, run_id
        ORDER BY last_event DESC
        LIMIT {int(n_runs)}
    """)
    if not runs:
        return runs, [], [], []
    pairs = ",".join(
        "(" + _sql_str(r["subject"]) + "," + _sql_str(r["run_id"]) + ")" for r in runs
    )
    grid = ch_query(url, user, pw, f"""
        SELECT subject, run_id,
               scenario, status, current_step, last_duration_ms, last_detail,
               run_started, last_event
        FROM {db}.latest_scenario_status
        WHERE (subject, run_id) IN ({pairs})
        ORDER BY subject, run_id, scenario
    """)
    events = ch_query(url, user, pw, f"""
        SELECT subject, run_id,
               scenario, step, status, ts_start, ts_end, duration_ms, detail, span_id
        FROM {db}.spans
        WHERE (subject, run_id) IN ({pairs})
        ORDER BY subject, run_id, scenario, ts_start
    """)
    # Agent numbers, derived by the coordinator from the agent's session
    # transcript (gentar.agentstats) — counts only. Absent tables (an older
    # arena) simply yield none.
    agent = ch_query(url, user, pw, f"""
        SELECT run_id, count() AS turns,
               sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
               sum(cache_read_tokens) AS cache_read_tokens, sum(tool_calls) AS tool_calls
        FROM {db}.agent_turns
        WHERE (subject, run_id) IN ({pairs})
        GROUP BY run_id
    """)
    return runs, grid, events, agent


# Steps whose detail is an agent's screen, not a command's output. The run
# report carries it for the fix loop; the dashboard — which a public repo
# publishes as a CI artifact — shows only that it exists.
PRIVATE_DETAIL_STEPS = {"driver.transcript"}


def _hidden(detail):
    return f"(agent transcript, {len(detail or '')} chars — in the run report, not here)"


def public_events(events):
    """Events fit to publish: transcript details replaced by their length."""
    return [{**e, "detail": _hidden(e.get("detail"))}
            if e.get("step") in PRIVATE_DETAIL_STEPS else e for e in events]


def public_grid(grid):
    """The per-scenario grid shows its latest step's detail; when that step
    is a transcript, the same rule applies (agy review)."""
    return [{**r, "last_detail": _hidden(r.get("last_detail"))}
            if r.get("current_step") in PRIVATE_DETAIL_STEPS else r for r in grid]


def badge(status: str) -> str:
    color = STATUS_COLOR.get(status, "#8a8a86")
    text_color = STATUS_DARK_TEXT.get(status, "#ffffff")
    label = html.escape(status.upper())
    return f'<span class="badge" style="background:{color};color:{text_color}">{label}</span>'


PAGE_TEMPLATE = """<title>gentar dashboard</title>
<style>
  :root {{
    --surface-light: #fcfcfb; --surface-dark: #1a1a19;
    --ink-light: #141410; --ink-dark: #f2f2ee;
    --muted-light: #6b6b64; --muted-dark: #a3a39a;
    --border-light: #e2e2dc; --border-dark: #33332e;
    --surface: var(--surface-light); --ink: var(--ink-light);
    --muted: var(--muted-light); --border: var(--border-light);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --surface: var(--surface-dark); --ink: var(--ink-dark); --muted: var(--muted-dark); --border: var(--border-dark); }}
  }}
  :root[data-theme="dark"] {{ --surface: var(--surface-dark); --ink: var(--ink-dark); --muted: var(--muted-dark); --border: var(--border-dark); }}
  :root[data-theme="light"] {{ --surface: var(--surface-light); --ink: var(--ink-light); --muted: var(--muted-light); --border: var(--border-light); }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--surface); color: var(--ink); font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-size: 12px; margin-bottom: 20px; }}
  select {{ font: inherit; background: var(--surface); color: var(--ink); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; }}
  .toolbar {{ display: flex; gap: 12px; align-items: center; margin-bottom: 18px; flex-wrap: wrap; }}
  .totals {{ display: flex; gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }}
  .stat {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; min-width: 90px; }}
  .stat .n {{ font-size: 20px; font-weight: 600; }}
  .stat .l {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  table {{ width: 100%; border-collapse: collapse; overflow-x: auto; display: block; }}
  thead, tbody {{ display: table; width: 100%; table-layout: fixed; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 600; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: .02em; }}
  .scenario-row {{ cursor: pointer; }}
  .scenario-row:hover {{ background: color-mix(in srgb, var(--ink) 4%, transparent); }}
  .detail {{ color: var(--muted); font-size: 12px; max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .timeline {{ display: none; background: color-mix(in srgb, var(--ink) 3%, transparent); }}
  .timeline.open {{ display: table-row; }}
  .timeline td {{ padding: 12px 10px 16px 28px; }}
  .tl-step {{ display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12.5px; }}
  .tl-step .name {{ min-width: 160px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .tl-step .dur {{ color: var(--muted); min-width: 70px; }}
  .container {{ overflow-x: auto; }}
  .empty {{ color: var(--muted); padding: 20px 0; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: color-mix(in srgb, var(--ink) 6%, transparent); padding: 1px 5px; border-radius: 4px; }}
</style>
<h1>gentar -- {title}</h1>
<div class="sub">{db} on {where} -- generated {generated_at}{watch_note}</div>

  <h2 style="font-size:15px;margin:22px 0 8px">Runs</h2>
</div>

<div class="toolbar">
  <label for="run-select">Run:</label>
  <select id="run-select" onchange="renderRun(this.value)"></select>
</div>

<div class="totals" id="totals"></div>

<div class="container">
  <table>
    <thead><tr><th style="width:26%">Scenario</th><th style="width:10%">Status</th><th style="width:10%">Duration</th><th style="width:16%">Current step</th><th>Last detail</th></tr></thead>
    <tbody id="grid-body"></tbody>
  </table>
</div>
<div class="empty" id="empty-note" style="display:none">No runs found yet -- the coordinator writes telemetry as scenarios execute.</div>

<script>
const RUNS = {runs_json};
const GRID = {grid_json};
const EVENTS = {events_json};
const AGENT = {agent_json};

// Everything below comes from runs — command output included — and this
// page can be a PUBLIC artifact that someone opens: text goes in escaped.
function esc(s) {{
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}}

function fmtDur(ms) {{
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return ms + "ms";
  return (ms / 1000).toFixed(1) + "s";
}}
function statusColor(s) {{
  return {{pass:"#0ca30c",running:"#fab219",fail:"#d03b3b",error:"#ec835a",skip:"#8a8a86"}}[s] || "#8a8a86";
}}
function statusTextColor(s) {{
  return {{pass:"#fff",running:"#141400",fail:"#fff",error:"#141400",skip:"#fff"}}[s] || "#fff";
}}
function badge(s) {{
  return `<span class="badge" style="background:${{statusColor(s)}};color:${{statusTextColor(s)}}">${{esc((s||"?").toUpperCase())}}</span>`;
}}

const select = document.getElementById("run-select");
RUNS.forEach((r, idx) => {{
  const opt = document.createElement("option");
  opt.value = idx;
  opt.textContent = `${{r.subject}} / ${{r.run_id}}  (${{r.scenarios}} scenarios, ${{r.n_pass}} pass / ${{r.n_fail}} fail / ${{r.n_running}} running / ${{r.n_skip}} skip / ${{r.n_error}} error)`;
  select.appendChild(opt);
}});

function renderRun(runIdx) {{
  const run = RUNS[Number(runIdx)];
  const rows = run ? GRID.filter(g => g.subject === run.subject && g.run_id === run.run_id) : [];
  const agent = run ? AGENT.find(a => a.run_id === run.run_id) : null;
  const totals = document.getElementById("totals");
  const empty = document.getElementById("empty-note");
  if (!run) {{ totals.innerHTML = ""; document.getElementById("grid-body").innerHTML = ""; empty.style.display = "block"; return; }}
  empty.style.display = "none";
  const stats = [
    ["scenarios", run.scenarios],
    ["pass", run.n_pass], ["fail", run.n_fail],
    ["running", run.n_running], ["skip", run.n_skip], ["error", run.n_error],
  ];
  if (agent) {{
    stats.push(["agent turns", agent.turns]);
    stats.push(["tokens in", agent.input_tokens], ["tokens out", agent.output_tokens]);
    stats.push(["tool calls", agent.tool_calls]);
  }}
  totals.innerHTML = stats.map(([l, n]) => `<div class="stat"><div class="n">${{n}}</div><div class="l">${{l}}</div></div>`).join("");

  const tbody = document.getElementById("grid-body");
  tbody.innerHTML = "";
  rows.forEach((row, i) => {{
    const tr = document.createElement("tr");
    tr.className = "scenario-row";
    tr.onclick = () => toggleTimeline(i);
    tr.innerHTML = `
      <td>${{esc(row.scenario)}}</td>
      <td>${{badge(row.status)}}</td>
      <td>${{fmtDur(row.last_duration_ms)}}</td>
      <td><code>${{esc(row.current_step || "-")}}</code></td>
      <td class="detail" title="${{esc(row.last_detail)}}">${{esc(row.last_detail)}}</td>`;
    tbody.appendChild(tr);

    const tlTr = document.createElement("tr");
    tlTr.className = "timeline";
    tlTr.id = `tl-${{i}}`;
    const steps = EVENTS.filter(e => e.subject === run.subject && e.run_id === run.run_id && e.scenario === row.scenario);
    const stepsHtml = steps.length
      ? steps.map(s => `<div class="tl-step">${{badge(s.status)}}<span class="name">${{esc(s.step)}}</span><span class="dur">${{fmtDur(s.duration_ms)}}</span><span class="detail" title="${{esc(s.detail)}}">${{esc(s.detail)}}</span></div>`).join("")
      : '<span class="detail">no step events recorded</span>';
    tlTr.innerHTML = `<td colspan="5">${{stepsHtml}}</td>`;
    tbody.appendChild(tlTr);
  }});
}}

function toggleTimeline(i) {{
  document.getElementById(`tl-${{i}}`).classList.toggle("open");
}}

if (RUNS.length > 0) {{
  select.value = "0";
  renderRun(0);
}} else {{
  document.getElementById("empty-note").style.display = "block";
}}
</script>
"""


def _script_json(value) -> str:
    """JSON safe to embed in a <script> block: `</` would end the block and
    let a step's output inject markup into a page someone opens."""
    return json.dumps(value, default=str).replace("</", "<\\/").replace("<!--", "<\\!--")


def render(runs, grid, events, agent, db: str, watch: bool) -> str:
    watch_note = " -- auto-refreshing every 5s" if watch else ""
    return PAGE_TEMPLATE.format(
        title="telemetry",
        where="the arena's ClickHouse",
        db=html.escape(db),
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        watch_note=watch_note,
        runs_json=_script_json(runs),
        grid_json=_script_json(grid),
        events_json=_script_json(events),
        agent_json=_script_json(agent),
    )


def write_html(path: str, body: str, watch: bool):
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    refresh = '<meta http-equiv="refresh" content="5">\n' if watch else ""
    with open(path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><head><meta charset=\"utf-8\">\n" + refresh + body + "</html>")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10, help="how many recent runs to embed (default 10)")
    ap.add_argument("--out", default=os.environ.get("GENTAR_DASHBOARD_OUT", DEFAULT_OUT))
    ap.add_argument("--watch", action="store_true", help="regenerate every 5s (also stamps a <meta refresh>)")
    # A published dashboard shows only its own invocation's runs: a kept
    # arena's ClickHouse still holds earlier ones, whose credentials the
    # publisher does not know to redact (agy review).
    ap.add_argument("--since", type=int, default=0,
                    help="only runs started at or after this Unix time")
    args = ap.parse_args(argv)

    url, user, pw, db = resolve_ch()

    def once():
        runs, grid, events, agent = fetch(url, user, pw, db, args.runs, args.since)
        html_body = render(runs, public_grid(grid), public_events(events), agent, db,
                           args.watch)
        write_html(args.out, html_body, args.watch)
        print(f"dashboard: {args.out}  ({len(runs)} runs, {len(grid)} scenario rows, {len(events)} events, {len(agent)} runs with agent spans)")

    once()
    if args.watch:
        try:
            while True:
                time.sleep(5)
                once()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

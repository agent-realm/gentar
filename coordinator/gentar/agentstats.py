"""Agent numbers from a Claude Code session transcript — numbers and enums only.

The agent inside a bench exports no telemetry of its own (it has no route to
the arena's collector, and nothing turns its OTel on), but Claude Code writes
a session transcript unconditionally: `<config>/projects/<cwd>/<session>.jsonl`.
The coordinator reads those files back from the bench and derives, per run:

  turns    one row per assistant message: model, input / output / cache
           tokens, how many tool calls it made
  tools    one row per tool call: the tool's name class, duration, error
  totals   the sums, for the report

The rule, agreed with the first adopter and pinned by a test that plants a
fake secret in a fixture: NOTHING textual leaves this module. A transcript
is the whole conversation — prompts, reasoning, every tool input and output —
and can hold a credential verbatim (a tool call that prints the environment).
The history store is shared and the dashboard can be a public artifact, so
only numbers and a closed set of labels come out:

  - model ids are kept only when they start with a known model family
    (claude, glm, gpt, gemini, deepseek, …) and stay short, else "other";
  - tool names are kept only from Claude Code's own built-in set; an MCP
    tool (`mcp__server__tool`, whose parts come from a subject's config)
    becomes "mcp", anything else "other".

Transcript text is parsed in memory and dropped; it is never stored,
emitted, printed or written to a report by this module.
"""

import datetime
import json
import re

# Claude Code's built-in tools. A closed set on purpose: a name outside it
# is reported as a class, never verbatim.
BUILTIN_TOOLS = frozenset({
    "Agent", "AskUserQuestion", "Bash", "BashOutput", "Edit", "ExitPlanMode",
    "Glob", "Grep", "KillShell", "LS", "MultiEdit", "NotebookEdit",
    "NotebookRead", "Read", "SlashCommand", "Task", "TodoRead", "TodoWrite",
    "ToolSearch", "WebFetch", "WebSearch", "Write", "Skill", "Monitor",
    "SendMessage", "ListAgents", "TaskStop", "PushNotification",
})
# A model id must LOOK like one: a known family prefix, then a short tail.
# An open pattern would store any token-shaped string a transcript put in
# the model field (agy review) — a hex API key matches [A-Za-z0-9.-]+.
_MODEL = re.compile(
    r"(claude|glm|gpt|o[0-9]|gemini|deepseek|qwen|kimi|llama|mistral|grok|minimax)"
    r"[A-Za-z0-9.\-]{0,40}")


def tool_class(name) -> str:
    if not isinstance(name, str):
        return "other"
    if name in BUILTIN_TOOLS:
        return name
    if name.startswith("mcp__"):
        return "mcp"
    return "other"


def model_label(model) -> str:
    if isinstance(model, str) and _MODEL.fullmatch(model):
        return model
    return "other"


def _ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ns(ts):
    """A datetime as Unix nanoseconds, or 0 when unknown."""
    return int(ts.timestamp() * 1_000_000_000) if ts else 0


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def extract(transcripts):
    """transcripts: iterable of JSONL texts (one per session file).
    Returns (turns, tools, totals) — lists of dicts and a dict, holding
    only numbers and the labels above."""
    turns, tools = [], []
    for session_index, text in enumerate(transcripts):
        # Claude Code writes one line per content block, repeating the
        # message's usage on each: aggregate per message id, last wins.
        messages = {}           # message id -> dict
        order = []
        uses = {}               # tool_use id -> (class, started ts)
        results = {}            # tool_use id -> (finished ts, is_error)
        for line in (text or "").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue
            when = _ts(entry.get("timestamp"))
            content = msg.get("content")
            items = content if isinstance(content, list) else []
            if entry.get("type") == "assistant":
                mid = msg.get("id") or entry.get("uuid") or f"line{len(order)}"
                if mid not in messages:
                    messages[mid] = {"tool_calls": 0, "ts": when, "end": when}
                    order.append(mid)
                m = messages[mid]
                if when and (m["end"] is None or when > m["end"]):
                    m["end"] = when
                m["model"] = model_label(msg.get("model"))
                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                m["input_tokens"] = _int(usage.get("input_tokens"))
                m["output_tokens"] = _int(usage.get("output_tokens"))
                m["cache_read_tokens"] = _int(usage.get("cache_read_input_tokens"))
                m["cache_creation_tokens"] = _int(usage.get("cache_creation_input_tokens"))
                for it in items:
                    if isinstance(it, dict) and it.get("type") == "tool_use":
                        m["tool_calls"] += 1
                        tid = it.get("id")
                        if isinstance(tid, str) and tid not in uses:
                            uses[tid] = (tool_class(it.get("name")), when, len(order) - 1)
            elif entry.get("type") == "user":
                for it in items:
                    if isinstance(it, dict) and it.get("type") == "tool_result":
                        tid = it.get("tool_use_id")
                        if isinstance(tid, str):
                            results[tid] = (when, bool(it.get("is_error")))
        for i, mid in enumerate(order):
            m = messages[mid]
            turns.append({
                "session": session_index, "turn": i,
                "model": m.get("model", "other"),
                "input_tokens": m.get("input_tokens", 0),
                "output_tokens": m.get("output_tokens", 0),
                "cache_read_tokens": m.get("cache_read_tokens", 0),
                "cache_creation_tokens": m.get("cache_creation_tokens", 0),
                "tool_calls": m["tool_calls"],
                # timestamps (Unix ns) so a turn can be a span; numbers only
                "start_ns": _ns(m.get("ts")), "end_ns": _ns(m.get("end")),
            })
        for tid, (cls, started, turn_index) in uses.items():
            finished, is_error = results.get(tid, (None, False))
            duration = None
            if started and finished and finished >= started:
                duration = int((finished - started).total_seconds() * 1000)
            tools.append({"session": session_index, "tool": cls,
                          "duration_ms": duration, "is_error": is_error,
                          "completed": tid in results, "turn": turn_index,
                          "start_ns": _ns(started), "end_ns": _ns(finished)})
    totals = {
        "sessions": len({t["session"] for t in turns}),
        "turns": len(turns),
        "input_tokens": sum(t["input_tokens"] for t in turns),
        "output_tokens": sum(t["output_tokens"] for t in turns),
        "cache_read_tokens": sum(t["cache_read_tokens"] for t in turns),
        "cache_creation_tokens": sum(t["cache_creation_tokens"] for t in turns),
        "tool_calls": len(tools),
        "tool_errors": sum(1 for t in tools if t["is_error"]),
    }
    return turns, tools, totals

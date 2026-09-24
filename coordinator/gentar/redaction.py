"""Replace secret VALUES in text that leaves a run — one implementation.

Used by bin/redact (the kit's published reports and dashboard) and by the
coordinator's history writer (the shared, persistent store). Two lessons
from review are built in:

  - a value appears in more than its raw form: JSON-escaped (ASCII and
    not), HTML-escaped, HTML of JSON — every form is replaced;
  - a value can be CUT: a report's command column or a span's detail cap
    truncates it, and a whole-value match misses the surviving prefix
    (claude-playbooks). Any prefix of 8+ characters of a value is replaced
    too, so a truncated secret loses what survived.

Values shorter than 4 characters are left alone: replacing them would shred
the text and they are not credentials worth that. Longest forms first, so a
value containing another is replaced whole.
"""

import html
import json

MIN_VALUE = 4
MIN_PREFIX = 8


def _forms(value: str):
    raw = [value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]]
    out = set(raw)
    for f in raw:
        out.add(html.escape(f))
        out.add(html.escape(f, quote=False))
    return out


def scrubber(named_values):
    """named_values: iterable of (name, value). Returns scrub(text) -> text."""
    full, prefixes = [], []
    for name, value in named_values:
        if not isinstance(value, str) or len(value) < MIN_VALUE:
            continue
        mark = f"«redacted:{name}»"
        for f in _forms(value):
            if len(f) >= MIN_VALUE:
                full.append((f, mark))
                # every surviving head of a cut value, longest first
                for n in range(len(f) - 1, MIN_PREFIX - 1, -1):
                    prefixes.append((f[:n], mark))
    full.sort(key=lambda p: -len(p[0]))
    prefixes.sort(key=lambda p: -len(p[0]))

    def scrub(text: str) -> str:
        if not text:
            return text
        for f, mark in full:
            if f in text:
                text = text.replace(f, mark)
        for p, mark in prefixes:
            if p in text:
                text = text.replace(p, mark)
        return text
    return scrub

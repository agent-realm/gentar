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

The prefix rule is for CREDENTIALS. A LOCATOR — a host, user, URL or
endpoint setting (by name) whose value is shaped like one — gets every form
of its exact value instead, and a URL also its host:port and host, so the
address cannot survive inside another URL. A URL is a locator only when
it carries nothing credential-shaped: no user:pass@, query, fragment, or
path segment longer than 12 characters. A locator's 8-char heads are
shared with innocent text: `http://1` of an export URL redacted every
http://1… address in a report, and `10.10.10` of a bench host every host on
its subnet (cockpit, reproduced with this scrubber). The trade-off, stated:
a locator cut mid-value keeps its surviving head (a partial address), which
is not a credential. Either test failing — name or shape — means the value
is treated as a credential: the stricter rule is the default.
"""

import html
import json
import re
from urllib.parse import quote, urlsplit

MIN_VALUE = 4
MIN_PREFIX = 8

_MAX_PATH_SEGMENT = 12       # /v1, /api/otlp: fine; a 24-char token segment: not
_LOCATOR_NAME = re.compile(r"_(HOST|USER|URL|ENDPOINT|EXPORT|JUMP)$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$", re.I)
# Host shapes that tokens do not take: an IPv4 address, a LOWERCASE dotted
# name (labels <= 63, last label starts with a letter), or a short lowercase
# single label (a VM name, a unix user). Mixed-case, long single labels and
# anything with other characters are credential-shaped (agy review: a
# sk-ant-... key in a *_USER setting matched the first, looser pattern).
_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"
_DOTTED = r"(?:[a-z0-9-]{1,63}\.)+[a-z][a-z0-9-]{0,62}"
_LABEL = r"[a-z][a-z0-9_-]{0,14}"
_USERPART = r"(?:[a-z_][a-z0-9_.-]{0,31}@)?"
_HOSTLIKE = re.compile(rf"^{_USERPART}(?:{_IPV4}|{_DOTTED}|{_LABEL})(?::\d{{1,5}})?$")
_HOSTNAME = re.compile(rf"^(?:{_IPV4}|{_DOTTED}|{_LABEL})$")


def _locator_parts(name: str, value: str):
    """The exact strings to replace for a locator, or None for a credential."""
    if not _LOCATOR_NAME.search(name or ""):
        return None
    if _URL.match(value):
        try:
            u = urlsplit(value)
            # A URL can CARRY a credential — user:pass@, a ?key= query, a
            # #fragment, or a token as a path segment (webhook URLs). Any of
            # those, and it is a credential: the prefix rule stays.
            if (u.username is not None or u.password is not None or u.query
                    or u.fragment or not u.hostname or not _HOSTNAME.match(u.hostname)
                    or any(len(seg) > _MAX_PATH_SEGMENT for seg in u.path.split("/"))):
                return None
        except ValueError:
            return None
        return {value, value.lower(), u.netloc, u.netloc.lower(), u.hostname}
    if _HOSTLIKE.match(value):
        return {value}
    return None


def _forms(value: str):
    raw = [value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1],
           quote(value, safe=""), quote(value, safe="/:")]      # URL-encoded, too
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
        parts = _locator_parts(name, value)
        if parts is not None:
            for part in parts:
                for f in _forms(part):
                    if len(f) >= MIN_VALUE:
                        full.append((f, mark))
            continue
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

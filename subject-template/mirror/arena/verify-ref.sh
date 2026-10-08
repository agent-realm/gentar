#!/usr/bin/env bash
# verify-ref: may this private arena mirror run phase 2 on this commit?
#
#   verify-ref.sh [--allow-branch-heads] <public-repo-url> [<sha>]
#
# Part of the gentar kit (subject-template/mirror/arena/). Self-contained on
# purpose: it sources nothing, so a mirror can vendor this one file. A
# vendored copy says which gentar tag it came from and its sha256 in a line
# above this header.
#
# A mirror runs a PUBLIC repository's code on a self-hosted runner that
# holds the bench key. Admitting a commit is trusting whoever could write it,
# so only commits reachable from refs the repository's own collaborators
# write are admitted: its default branch and its `v*` tags, plus every
# branch head with --allow-branch-heads (for an adopter that gates pull
# requests on phase 2; off by default). A fork's commits live under
# refs/pull/*, which is never fetched.
#
# The trap this exists for: GitHub serves ANY commit of a fork network by
# sha through the parent repository's URL. So "it fetched" or "it exists"
# proves nothing. This fetches ONLY the refs above, into an empty
# repository, without a partial-clone filter (a promisor remote would
# lazily fetch a missing commit by sha, from that same URL), and then asks
# which of those refs contain the commit.
#
# No sha: the default branch head (a scheduled run). A sha must be the full
# 40 hex characters; an abbreviation could name another commit.
#
# Output: `sha=<sha>` and `via=<ref>` lines on stdout, also appended to
# $GITHUB_OUTPUT when set. Refusals are one line on stderr.
# Exit: 0 admitted · 1 refused · 2 usage, or the repository could not be read.

set -euo pipefail

ALLOW_HEADS=0
if [ "${1:-}" = --allow-branch-heads ]; then ALLOW_HEADS=1; shift; fi
URL=${1:-}
SHA=${2:-}
usage() { echo "usage: verify-ref.sh [--allow-branch-heads] <public-repo-url> [<40-hex sha>]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
case "$URL" in ''|-*) usage ;; esac
case "$SHA" in
  '') ;;
  *[!0-9a-f]*) echo "verify-ref: refusing ${SHA:0:60} -- not a lowercase hex commit sha" >&2; exit 2 ;;
  *) [ "${#SHA}" = 40 ] || { echo "verify-ref: refusing $SHA -- need the full 40-character sha" >&2; exit 2; } ;;
esac

TMP=$(mktemp -d "${TMPDIR:-/tmp}/verify-ref.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
export GIT_TERMINAL_PROMPT=0 GIT_NO_LAZY_FETCH=1
g() { git -C "$TMP" -c protocol.version=2 "$@"; }
git init -q --bare "$TMP"

# The default branch, as the repository itself names it.
head=$(git ls-remote --symref -- "$URL" HEAD 2>/dev/null \
  | sed -n 's|^ref: refs/heads/\([^[:space:]]*\)[[:space:]]*HEAD$|\1|p' | head -1) || head=""
if [ -z "$head" ]; then
  echo "verify-ref: could not read the default branch of $URL" >&2
  exit 2
fi

specs=("+refs/heads/$head:refs/remotes/origin/$head" "+refs/tags/v*:refs/tags/v*")
[ "$ALLOW_HEADS" = 1 ] && specs+=("+refs/heads/*:refs/remotes/origin/*")
if ! g fetch --quiet --no-tags --no-write-fetch-head -- "$URL" "${specs[@]}" 2>"$TMP/fetch.err"; then
  echo "verify-ref: fetching $URL failed: $(head -c 300 "$TMP/fetch.err" | tr '\n' ' ')" >&2
  exit 2
fi

if [ -z "$SHA" ]; then
  SHA=$(g rev-parse --verify -q "refs/remotes/origin/$head^{commit}") || {
    echo "verify-ref: $URL has no commit on its default branch $head" >&2; exit 1; }
fi

allowed="its default branch $head or a v* tag"
[ "$ALLOW_HEADS" = 1 ] && allowed="a branch of it or a v* tag"
refuse() {
  echo "verify-ref: refusing $SHA -- not reachable from $allowed in $URL; nothing runs" >&2
  exit 1
}
# Absent after fetching only those refs = reachable from none of them.
g cat-file -e "$SHA^{commit}" 2>/dev/null || refuse
# Which fetched refs contain it, the default branch first.
via=""
for ref in "refs/remotes/origin/$head" \
           $(g for-each-ref --contains "$SHA" --format='%(refname)' refs/tags/ refs/remotes/origin/); do
  if g merge-base --is-ancestor "$SHA" "$ref^{commit}" 2>/dev/null; then via=$ref; break; fi
done
[ -n "$via" ] || refuse

# Named as the public repository names it: refs/heads/<branch>, refs/tags/<tag>.
case "$via" in refs/remotes/origin/*) via="refs/heads/${via#refs/remotes/origin/}" ;; esac
out="sha=$SHA
via=$via"
printf '%s\n' "$out"
[ -z "${GITHUB_OUTPUT:-}" ] || printf '%s\n' "$out" >> "$GITHUB_OUTPUT"

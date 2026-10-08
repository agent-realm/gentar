#!/usr/bin/env bash
# mirror: run phase 2 in this repository's private arena mirror.
#
#   gentar/mirror.sh dispatch <sha> [suite ...]   # run, wait, report back
#   gentar/mirror.sh status <sha>                 # what arena/phase2 says now
#
# For a PUBLIC repository with [arena] bench = "mirror" in gentar/policy.toml:
# no self-hosted runner serves it, and phase 2 runs in the mirror named by
# [arena] mirror, which pulls this repository and verifies the commit is
# reachable from its default branch or a `v*` tag (or, if the mirror allows
# it, a branch head) before anything runs. Never a fork's commit.
#
# `dispatch` starts the mirror's arena workflow on <sha>, waits for it, and,
# for a full phase 2 (no suites named), posts the commit status
# `arena/phase2` on <sha> here: success or failure, linking the mirror run
# (private: visible to those who can read the mirror). That status is what
# release-gate.sh reads with [phase2] evidence = "status". A targeted run
# (suites named) never posts it. A mirror holding GENTAR_STATUS_TOKEN posts
# the same status itself; posting twice changes nothing.
#
# Needs `gh`, authenticated as someone who can run the mirror's workflows and
# write commit statuses here. GENTAR_PUBLIC_REPO overrides this repository's
# owner/name (default: what `gh repo view` says).
# Exit: 0 green · 1 not green · 2 usage, or the mirror run could not be found.

set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CMD=${1:-}
SHA=${2:-}
usage() { echo "usage: gentar/mirror.sh dispatch <sha> [suite ...] | status <sha>" >&2; exit 2; }
case "$CMD" in dispatch|status) ;; *) usage ;; esac
[ $# -ge 2 ] || usage
shift 2
case "$SHA" in ''|*[!0-9a-f]*) usage ;; esac
[ "${#SHA}" = 40 ] || { echo "mirror: need the full 40-character sha" >&2; exit 2; }
for s in "$@"; do
  case "$s" in ''|*[!A-Za-z0-9._-]*) echo "mirror: not a suite name: $s" >&2; exit 2 ;; esac
done

cfg=$(python3 "$HERE/plan.py" arena-config) || exit 2
MIRROR=$(printf '%s\n' "$cfg" | sed -n 's/^mirror=//p')
if [ "$(printf '%s\n' "$cfg" | sed -n 's/^bench=//p')" != mirror ] || [ -z "$MIRROR" ]; then
  echo "mirror: gentar/policy.toml has no [arena] bench = \"mirror\" with a mirror = \"owner/name\"" >&2
  exit 2
fi
PUBLIC=${GENTAR_PUBLIC_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}
CONTEXT=arena/phase2

if [ "$CMD" = status ]; then
  gh api "repos/$PUBLIC/commits/$SHA/status" \
    --jq ".statuses[] | select(.context == \"$CONTEXT\") | \"\(.state)\t\(.updated_at)\t\(.target_url)\"" \
    | { read -r state when url || { echo "$CONTEXT: none on $SHA"; exit 1; }
        echo "$CONTEXT: $state on $SHA ($when) $url"
        [ "$state" = success ]; }
  exit
fi

# The mirror's run is found by an id carried in its run name, not by "the
# newest run": two dispatchers at once must not each take the other's.
REQ="gentar-$(date +%s)-$$-${RANDOM:-0}"
args=(-f sha="$SHA" -f request="$REQ")
[ $# -eq 0 ] || args+=(-f scenario="$*")
gh workflow run arena.yml -R "$MIRROR" "${args[@]}" >/dev/null
echo "mirror: dispatched $MIRROR arena on $PUBLIC@$SHA${*:+ (suites: $*)}"
id=""
for _ in $(seq 1 30); do
  id=$(gh run list -R "$MIRROR" --workflow arena.yml --event workflow_dispatch --limit 30 \
        --json databaseId,displayTitle \
        --jq ".[] | select(.displayTitle | contains(\"$REQ\")) | .databaseId" | head -1)
  [ -n "$id" ] && break
  sleep 2
done
[ -n "$id" ] || { echo "mirror: the dispatched run did not appear in $MIRROR (request $REQ)" >&2; exit 2; }
gh run watch "$id" -R "$MIRROR" --exit-status >/dev/null 2>&1 || true
read -r concl url < <(gh run view "$id" -R "$MIRROR" --json conclusion,url --jq '"\(.conclusion) \(.url)"')
echo "mirror: run $url -- $concl"

if [ $# -eq 0 ]; then
  case "$concl" in success|failure) state=$concl ;; *) state=error ;; esac
  gh api -X POST "repos/$PUBLIC/statuses/$SHA" -f state="$state" -f context="$CONTEXT" \
    -f target_url="$url" -f description="phase 2: $concl (arena mirror)" >/dev/null
  echo "mirror: posted $CONTEXT = $state on $PUBLIC@$SHA"
fi
[ "$concl" = success ]

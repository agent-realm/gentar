#!/usr/bin/env bash
# Kick this repo's arena: stage the working tree as the subject, run a
# scenario, land the report in gentar/reports/.
#
#   gentar/run.sh <scenario>          # e.g. first-suite
#   GENTAR_REF=main gentar/run.sh …   # pin the arena version
#
# First run: clones gentar into gentar/.arena and copies .env.example
# to .env — edit .env if your bench-host differs from the default.
# Reports: gentar/reports/report-<run_id>.md — on failure, feed one to
# an agent; it states everything needed to fix.
#
# Genericized from the reference subject (claude-playbooks/gentar);
# the only thing to edit below is SUBJECT if your repo's dir name is
# not its basename.
set -euo pipefail

SCENARIO=${1:?usage: gentar/run.sh <scenario> [more scenarios...]}
shift || true
HERE=$(cd "$(dirname "$0")" && pwd)          # <repo>/gentar
REPO=$(dirname "$HERE")
SUBJECT=$(basename "$REPO")   # dir under the subjects root — MUST match
                              # `subject = "…"` in your scenario TOMLs
ARENA=${GENTAR_DIR:-$HERE/.arena}
REF=${GENTAR_REF:-main}

# Refs are branch/tag/SHA only — reject anything hostile before it
# reaches git (the CI workflow passes a dispatch input through here).
case "$REF" in
  ''|*[!A-Za-z0-9._/-]*) echo "bad GENTAR_REF: $REF" >&2; exit 2 ;;
esac

# agent-realm/gentar is private. Anonymous https works from a dev
# machine with a credential helper; a CI runner needs explicit auth.
# GENTAR_CLONE_SSH_KEY (path to a read-only deploy key) switches clone
# and fetch to ssh for the arena git ops. Unset = plain https, as on
# a laptop.
if [ -n "${GENTAR_CLONE_SSH_KEY:-}" ]; then
  CLONE_URL=git@github.com:agent-realm/gentar.git
  export GIT_SSH_COMMAND="ssh -i $GENTAR_CLONE_SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
else
  CLONE_URL=https://github.com/agent-realm/gentar
fi

if [ ! -d "$ARENA" ]; then
  git clone -q "$CLONE_URL" "$ARENA"
fi
# Honor GENTAR_REF on EVERY run: fetch, resolve, detach. A cached
# .arena must never pin the engine to whatever was checked out first.
# Fetching the ref itself covers branches, tags, and bare SHAs (GitHub
# allows want-sha) — but resolves via FETCH_HEAD, NOT the ref name: a
# plain `git fetch origin main` writes FETCH_HEAD only and never moves
# the local branch, so rev-parse main would answer with the stale tip.
if ! git -C "$ARENA" fetch -q --tags origin "$REF"; then
  echo "GENTAR_REF $REF not found in agent-realm/gentar" >&2; exit 2
fi
sha=$(git -C "$ARENA" rev-parse -q --verify FETCH_HEAD^{commit}) || {
  echo "GENTAR_REF $REF not resolvable in agent-realm/gentar" >&2; exit 2
}
git -C "$ARENA" checkout -q --detach "$sha"
cd "$ARENA"
[ -f .env ] || cp .env.example .env

# Stage THIS checkout (working tree, uncommitted changes included) as
# the subject. Plain copy: symlinks don't resolve through the bind.
#
# Three exclusions, each for a reason:
#   gentar/.arena    holds .env and the bench key — secrets must never
#                    ride into a bench the subject's own agent can read
#   gentar/reports   previous verdicts; dead weight
#   .git             a CREDENTIAL on CI. actions/checkout leaves its
#                    auth header in .git/config, so shipping .git hands
#                    the job token to anything running in the bench
#                    (PR #27 review). It is also useless there — a
#                    worktree's .git is a host-absolute pointer file —
#                    which is why .gentar-version is frozen below.
# A subject whose scenarios genuinely need git history must ship it
# deliberately, from a checkout that persists no credentials.
mkdir -p subjects out
rm -rf "subjects/$SUBJECT"
mkdir "subjects/$SUBJECT"
(cd "$REPO" && tar \
  --exclude=./.git --exclude=./gentar/.arena --exclude=./gentar/reports \
  -cf - .) | tar -xf - -C "subjects/$SUBJECT"
# A worktree's .git is a pointer file with a host-absolute path — dead
# on the bench — so `git describe` there finds nothing. Freeze the
# version HERE, where git works; scenarios read it instead of trusting
# the bench's git.
(cd "$REPO" && git describe --tags --always --dirty 2>/dev/null || echo dev) \
  > "subjects/$SUBJECT/.gentar-version"

# Rebuild the coordinator image from the checkout we just detached.
#
# This is the difference between a fresh ENGINE and a fresh CHECKOUT. The
# compose service is `build: ./coordinator`, so `docker compose run` happily
# reuses a cached image -- and on a long-lived self-hosted runner that image
# can be months older than the source above, silently. Symptom when it bit:
# the credential guard refused a run for a variable it was given, because the
# cached image predated the guard becoming "any of these" rather than "all".
# GENTAR_REF was honoured perfectly the whole time; the code that ran was not
# the code that was fetched. gentar's own gate builds before every run for
# this reason.
echo "building the coordinator image from $sha..." >&2
docker compose -p "arena-$SUBJECT" build coordinator

# The coordinator runs in a CONTAINER, so nothing in this script's
# environment reaches it unless it is forwarded. Agent-in-the-loop suites
# declare `credentials`, and the coordinator refuses before creating a bench
# when none of the named variables is present -- which is what happens to a
# correctly-configured run whose variables simply stopped at the container
# boundary. Forward only the ones actually set, so an unset variable stays
# unset inside rather than arriving empty-but-present.
#
# The names are READ FROM THE SCENARIOS about to run, not from a fixed
# list: `credentials` and `pass_env` are arbitrary env var names in the
# schema, so a hardcoded ANTHROPIC_* allowlist silently drops
# OPENAI_API_KEY or any subject's own knob — the coordinator then
# refuses (exit 2) for a variable the caller did set, or quietly runs
# without an optional one (PR #27 review). Parsed with awk rather than a
# TOML library: this must work on a stock runner with no python
# dependency. The two shapes the schema allows are
# `credentials = ["A", ["B", "C"]]` (groups, possibly spanning lines)
# and `pass_env = ["D"]`; tracking bracket depth reads both and stops at
# the array's real end rather than at the first `]` on a later line.
# Commented-out examples are skipped — a `#` line is not a declaration.
#
# GENTAR_BUDGET_CAP is the one fixed addition: it configures the budget
# guard itself, so no scenario declares it.
extract_env_names() {         # files... -> one env var name per line
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*(credentials|pass_env)[[:space:]]*=/ { inarr = 1; depth = 0 }
    inarr {
      line = $0
      while (match(line, /"[A-Za-z_][A-Za-z0-9_]*"/)) {
        print substr(line, RSTART + 1, RLENGTH - 2)
        line = substr(line, RSTART + RLENGTH)
      }
      depth += gsub(/\[/, "[") - gsub(/\]/, "]")
      if (depth <= 0) inarr = 0
    }
  ' "$@"
}
# ${FORWARD[@]+"..."} rather than "${FORWARD[@]}": under `set -u`, bash 3.2
# (still the system bash on macOS) treats an EMPTY array expansion as an
# unbound variable and aborts. Credential-less is the normal case on a dev
# machine, so the plain form would break every local run.
SCENARIO_FILES=()
for s in "$SCENARIO" "$@"; do
  [ -f "$HERE/scenarios/$s.toml" ] && SCENARIO_FILES+=("$HERE/scenarios/$s.toml")
done
declared=$(
  { [ ${#SCENARIO_FILES[@]} -eq 0 ] \
      || extract_env_names ${SCENARIO_FILES[@]+"${SCENARIO_FILES[@]}"}
    echo GENTAR_BUDGET_CAP
  } | sort -u)
FORWARD=()
for var in $declared; do
  [ -n "${!var:-}" ] && FORWARD+=(-e "$var")
done

# Run every requested scenario; report all, fail if any failed.
mkdir -p "$HERE/reports"
status=0
for s in "$SCENARIO" "$@"; do
  # Exit code is the verdict: 0 pass · 1 fail · 2 usage/config refusal.
  MARKER=$(mktemp)
  set +e
  GENTAR_SUBJECTS_DIR="$PWD/subjects" \
    docker compose -p "arena-$SUBJECT" run --rm \
      -e GENTAR_SCENARIOS_DIR=/extra \
      ${FORWARD[@]+"${FORWARD[@]}"} \
      -v "$HERE/scenarios:/extra:ro" \
      coordinator run "$s"
  rc=$?
  set -e
  # Copy every report this run produced into the repo, with a
  # reproduce command that works for own-arena scenarios (the
  # engine's default assumes the central arena's invocation).
  found=0
  while IFS= read -r f; do
    sed "s|^Reproduce: \`.*\`|Reproduce: \`gentar/run.sh $s\`|" "$f" \
      > "$HERE/reports/$(basename "$f")" && found=1
  done < <(find out -name 'report-*.md' -newer "$MARKER" 2>/dev/null)
  rm -f "$MARKER"
  if [ "$found" -ne 1 ]; then
    # Every terminal outcome (pass/fail/refuse) writes one; a missing
    # report means reporting itself broke — fail loudly, don't pass
    # silently without the fix-loop artifact.
    echo "no report written for $s" >&2
    rc=1
  fi
  [ "$rc" -eq 0 ] || status=$rc
done
exit "$status"

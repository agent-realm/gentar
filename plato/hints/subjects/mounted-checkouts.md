---
hint: subjects/mounted-checkouts
confirmed-by: grill 2026-08-31
seed: scenario-toml
---

# mounted-checkouts

Capability: subjects are mounted read-only into the coordinator (subjects
root), never baked into images; subject suites clone from the mount (private
repos via local .git or read-only deploy key). Verified by kommander +
memhouse suites.

Hazards: subjects/ checkouts are untracked + gitignored — they die with
worktree cleanup; re-rsync with BOTH trailing slashes, no symlinks (don't
resolve in container); kommander repo is private — old-release clones from
the subject's local .git, CI clones full-depth for tags; sandbox kernels set
comm from the executable — liveness probes need prctl(PR_SET_NAME) holders.

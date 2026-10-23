# subjects/

Subject checkouts land here (read-only mount into the coordinator;
delivered into benches per-run via the workspace bind-mount — never
baked). Populate by copy (or a clone), e.g.:

    cp -R ~/DEV/kommander-playbook subjects/kommander-playbook

Not by symlink: only this directory is mounted, so inside the
coordinator a link points at a host path that does not exist there.

Or point compose elsewhere: `GENTAR_SUBJECTS_DIR=~/DEV` gives the
coordinator every checkout under it (subject dirs are named in each
scenario's `[scenario].subject`).

# subjects/

Subject checkouts land here (read-only mount into the coordinator;
delivered into benches per-run via the workspace bind-mount — never
baked). Populate by symlink or copy, e.g.:

    ln -s ~/DEV/kommander-playbook subjects/kommander-playbook

Or point compose elsewhere: `GENTAR_SUBJECTS_DIR=~/DEV` gives the
coordinator every checkout under it (subject dirs are named in each
scenario's `[scenario].subject`).

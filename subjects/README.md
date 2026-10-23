# subjects/

Subject checkouts land here (read-only mount into the coordinator;
delivered into benches per-run via the workspace bind-mount — never
baked). Populate by clone or copy, e.g.:

    git clone https://github.com/<org>/kommander-playbook subjects/kommander-playbook

The engine ships `subjects/<name>/` as it stands, `.git` included (it
refuses one whose git config, reflogs or credential store hold a
credential), so stage a clean clone: anything else in the directory,
gitignored files too, reaches the bench. The kit's `gentar/run.sh` stages
only the files git would ship.

`<name>` is the scenario's `[scenario].subject`: one directory name
(letters, digits, dot, dash, underscore; not starting with a dot or a
dash), and the directory must resolve inside this root. A symlink out of
it is refused before any bench exists, so `ln -s ~/DEV/<repo>` does not
work (it never did inside the container: the target is not mounted).

Or point compose elsewhere: `GENTAR_SUBJECTS_DIR=~/DEV` gives the
coordinator every checkout under it.

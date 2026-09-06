#!/bin/bash
# One-command archival from the workstation (WSL) or the Mac: pull the
# campaign's raw records + results home from the cluster and commit them to
# git, so GitHub holds the actual research record (slurm logs, scf outputs,
# evidence snapshots, kappa_L tables) — not only the WORKLOG narrative.
#
# Needs: the 'drac' entry in ~/.ssh/config and this repo clone. Excludes QE
# scratch (tmp/, gitignored anyway) and scripts/ (the cluster clone carries
# local script edits; the committed versions in this repo stay
# authoritative).
#
# Usage: bash thermo_candidates/SrCu2SnS4/phono3py/scripts/fetch_home.sh
set -eu
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
MAT=thermo_candidates/SrCu2SnS4
REMOTE=drac:scratch/Waterloo-prof-Holger

rsync -av --exclude 'tmp/' --exclude 'scripts/' \
    "$REMOTE/$MAT/phono3py/" "$REPO/$MAT/phono3py/"
rsync -av "$REMOTE/$MAT/results/" "$REPO/$MAT/results/"

cd "$REPO"
git add "$MAT/phono3py" "$MAT/results"
if git diff --cached --quiet; then
    echo "[fetch_home] nothing new to commit"
else
    git commit -m "Archive Nibi campaign raw records + results for SrCu2SnS4 (fetch_home.sh)"
    git push
fi
echo "[fetch_home] done"

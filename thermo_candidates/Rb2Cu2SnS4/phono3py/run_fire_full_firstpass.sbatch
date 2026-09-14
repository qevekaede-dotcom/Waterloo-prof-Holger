#!/bin/bash
# One isolated first-pass FIRE continuation from the terminal eight-step pilot geometry.
# Scientific acceptance still requires normal FIRE convergence and a later pristine SCF.
#SBATCH --job-name=Rb-fire-full
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=12:00:00

set -euo pipefail
umask 027

: "${P3_CLUSTER_ENV:?submit with the exact cluster.env path}"
: "${P3_EXPECTED_INPUT_SHA256:?submit with the exact fire-full.in SHA256}"
[[ "$P3_CLUSTER_ENV" == /* && -f "$P3_CLUSTER_ENV" && ! -L "$P3_CLUSTER_ENV" ]]
# shellcheck disable=SC1090
source "$P3_CLUSTER_ENV"
p3_require_compute_node

cd "$SLURM_SUBMIT_DIR"
[[ ! -L fire-full.in && -f fire-full.in ]]
[[ "$(sha256sum fire-full.in | awk '{print $1}')" == "$P3_EXPECTED_INPUT_SHA256" ]]
[[ ! -e fire-full.out && ! -e fire-full.err && ! -e exit_code.txt ]]

p3_load_qe
date -u +%Y-%m-%dT%H:%M:%SZ > started_utc.txt
set +e
srun pw.x -nk 1 -in fire-full.in > fire-full.out 2> fire-full.err
rc=$?
set -e
printf '%s\n' "$rc" > exit_code.txt
date -u +%Y-%m-%dT%H:%M:%SZ > finished_utc.txt
exit "$rc"

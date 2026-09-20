#!/bin/bash
# Independent setting-matched SCF for the converged FIRE terminal geometry.
# Submit only after audit_fire_firstpass.py passes.
#SBATCH --job-name=Rb-pristine
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=02:00:00

set -euo pipefail
umask 027

: "${P3_CLUSTER_ENV:?submit with the exact cluster.env path}"
: "${P3_EXPECTED_INPUT_SHA256:?submit with the exact pristine.in SHA256}"
: "${P3_PRISTINE_DIR:?submit with the exact pristine directory}"
[[ "$P3_CLUSTER_ENV" == /* && -f "$P3_CLUSTER_ENV" && ! -L "$P3_CLUSTER_ENV" ]]
# shellcheck disable=SC1090
source "$P3_CLUSTER_ENV"
p3_require_compute_node

[[ "$P3_PRISTINE_DIR" == /* && -d "$P3_PRISTINE_DIR" && ! -L "$P3_PRISTINE_DIR" ]]
cd "$P3_PRISTINE_DIR"
[[ ! -L pristine.in && -f pristine.in ]]
[[ "$(sha256sum pristine.in | awk '{print $1}')" == "$P3_EXPECTED_INPUT_SHA256" ]]
[[ ! -e pristine.out && ! -e pristine.err && ! -e exit_code.txt && ! -e tmp ]]

p3_load_qe
date -u +%Y-%m-%dT%H:%M:%SZ > started_utc.txt
set +e
srun pw.x -nk 1 -in pristine.in > pristine.out 2> pristine.err
rc=$?
set -e
printf '%s\n' "$rc" > exit_code.txt
date -u +%Y-%m-%dT%H:%M:%SZ > finished_utc.txt
exit "$rc"

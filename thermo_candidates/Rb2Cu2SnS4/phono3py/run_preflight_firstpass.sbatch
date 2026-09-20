#!/bin/bash
# Count-only phono3py displacement preflight; no QE force calculation.
#SBATCH --job-name=Rb-p3-count
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=01:00:00

set -euo pipefail
umask 027

: "${P3_CLUSTER_ENV:?submit with the exact cluster.env path}"
: "${P3_RUN_DIR:?submit with the exact Rb run directory}"
: "${P3_UNITCELL_SHA256:?submit with the accepted pristine input SHA256}"
[[ "$P3_CLUSTER_ENV" == /* && -f "$P3_CLUSTER_ENV" && ! -L "$P3_CLUSTER_ENV" ]]
# shellcheck disable=SC1090
source "$P3_CLUSTER_ENV"
p3_require_compute_node
[[ "$P3_RUN_DIR" == /* && -d "$P3_RUN_DIR" && ! -L "$P3_RUN_DIR" ]]
cd "$P3_RUN_DIR"
[[ "$(sha256sum pristine/pristine.in | awk '{print $1}')" == "$P3_UNITCELL_SHA256" ]]
[[ ! -e preflight ]]
p3_activate_python
python run_preflight_firstpass.py \
  --unitcell pristine/pristine.in \
  --output-dir preflight \
  > preflight.stdout 2> preflight.stderr

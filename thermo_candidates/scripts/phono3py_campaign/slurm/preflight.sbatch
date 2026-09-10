#!/bin/bash
# Compute-node-only phono3py displacement inventory and safety preflight.
# This stage counts candidate supercells and writes auditable plans; the
# public CLI must stop at configured displacement/core-hour caps.
#SBATCH --job-name=p3-preflight
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-p3-preflight-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
p3_begin_attempt preflight
p3_activate_python

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:?}"
export P3_STAGE="preflight"
p3_run_cli preflight

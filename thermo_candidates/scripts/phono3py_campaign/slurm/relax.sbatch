#!/bin/bash
# Fixed-cell, phonon-grade ionic relaxation on a DRAC compute node.
#
# Before submission, run `campaign.py prepare-relax` and export absolute
# CAMPAIGN_CONFIG and RUN_DIR paths.  ATTEMPT_ID must be new for every submit
# or retry.  This job never removes or reuses an earlier attempt directory.
#SBATCH --job-name=p3-relax
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=12:00:00
#SBATCH --output=slurm-p3-relax-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
p3_begin_attempt relax
p3_load_qe
p3_activate_python

export P3_STAGE="relax"
export P3_SLURM_NTASKS="${SLURM_NTASKS:?}"
p3_run_cli run-relax
p3_run_cli finalize-relax

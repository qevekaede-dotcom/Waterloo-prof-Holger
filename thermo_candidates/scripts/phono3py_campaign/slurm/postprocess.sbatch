#!/bin/bash
# fc2/fc3 construction and kappa mesh analysis on a DRAC compute node.  Submit
# only after an afterany collector has preserved the force-array evidence.  The
# public CLI is responsible for the strict health, pristine-force, hash, and
# settings gates before any scientific output.
#SBATCH --job-name=p3-post
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=slurm-p3-post-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
p3_begin_attempt postprocess
p3_activate_python

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:?}"
export P3_STAGE="postprocess"
p3_run_cli postprocess

# Status is read-only and remains useful when the scientific audit finds a
# failed convergence or provenance gate.  Preserve that report, then return
# the audit's nonzero code so Slurm cannot label an unaudited result complete.
audit_rc=0
p3_run_cli audit || audit_rc=$?
p3_run_cli status
if (( audit_rc != 0 )); then
    exit "$audit_rc"
fi

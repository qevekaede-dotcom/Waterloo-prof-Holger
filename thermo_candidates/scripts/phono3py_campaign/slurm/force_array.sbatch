#!/bin/bash
# One immutable QE force calculation per task-map row.
#
# There is intentionally no #SBATCH --array directive.  `prepare-force`
# creates TASK_MAP; the submission layer must derive 0..N-1 from that exact
# file and pass `sbatch --array=0-(N-1)%MAX_IN_FLIGHT`.  Never infer the range
# from directory names and never reuse ATTEMPT_ID for a retry.
#SBATCH --job-name=p3-force
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=12:00:00
#SBATCH --output=slurm-p3-force-%A_%a.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
: "${TASK_MAP:?export TASK_MAP as the immutable task_map.tsv path}"
: "${SLURM_ARRAY_TASK_ID:?submit force_array.sbatch with a dynamic --array range}"
[[ "$SLURM_ARRAY_TASK_ID" =~ ^[0-9]+$ ]] \
    || p3_die "SLURM_ARRAY_TASK_ID is not a non-negative integer"
[[ "$TASK_MAP" == /* ]] || p3_die "TASK_MAP must be an absolute path"
p3_require_file "force task map" "$TASK_MAP"
TASK_MAP="$(cd "$(dirname "$TASK_MAP")" && pwd -P)/$(basename "$TASK_MAP")"
[[ "$TASK_MAP" == "$RUN_DIR"/* ]] \
    || p3_die "TASK_MAP must belong to the selected immutable RUN_DIR"
export TASK_MAP

p3_begin_attempt force "task-$SLURM_ARRAY_TASK_ID"
p3_load_qe
p3_activate_python

export P3_STAGE="force"
export P3_SLURM_NTASKS="${SLURM_NTASKS:?}"
p3_run_cli run-force-task \
    --task-map "$TASK_MAP" \
    --task-id "$SLURM_ARRAY_TASK_ID"

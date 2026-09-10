#!/bin/bash
# Immutable evidence collection.  Submit this with
# `--dependency=afterany:<relax-or-force-job-id>` so failed jobs are captured
# as well as successful jobs.  This script does not rerun or delete anything.
#SBATCH --job-name=p3-collect
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-p3-collect-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
p3_begin_attempt collect
p3_activate_python

# Capture Slurm's authoritative dependency and accounting context.  An
# afterany dependency is set by the submission layer; absence of an exposed
# dependency field is recorded by scontrol rather than treated as a false
# collector failure.
if command -v scontrol >/dev/null 2>&1; then
    scontrol show job --oneliner "$SLURM_JOB_ID" \
        > "$P3_ATTEMPT_DIR/slurm_job.txt" \
        2> "$P3_ATTEMPT_DIR/scontrol.err" || true
fi

export P3_STAGE="collect"
p3_run_cli collect

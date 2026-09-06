#!/bin/bash
# Stage 0 on the cluster: reference benchmark (disp-00001, 90/720 Ry, 3x3x3),
# k-mesh and cutoff force-convergence checks, pristine-supercell residual
# check, and campaign input generation at the decided settings — then stop.
# Reuses scripts/run_campaign.sh unchanged via its STOP_AFTER=stage0 hook;
# the sequential stage-1 loop is replaced by stage1_array.sbatch.
#
# Submit via scripts/slurm/submit_all.sh (it supplies --account and the cwd).
#SBATCH --job-name=p3-stage0
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=12:00:00
#SBATCH --output=slurm_logs/stage0_%j.out

set -u
cd "$SLURM_SUBMIT_DIR"
source scripts/slurm/cluster.env
export QE_NP="$SLURM_NTASKS"
STOP_AFTER=stage0 bash scripts/run_campaign.sh

#!/bin/bash
# Submit the full phono3py campaign as three dependent SLURM jobs:
#   stage0 (checks + input generation) -> stage1 (168-task array) -> stage2
#   (force collection + kappa_L postprocessing).
# stage2 only starts if every stage1 task succeeded (afterok). If some tasks
# fail, stage2 shows DependencyNeverSatisfied: fix and rerun the failed array
# indices, scancel the held stage2 job, and resubmit stage2 alone (see
# DRAC_SETUP.md section 6).
#
# Usage, from the phono3py/ directory on the cluster:
#   bash scripts/slurm/submit_all.sh
set -eu
cd "$(dirname "$0")/../.."
source scripts/slurm/cluster.env
if [ "$ACCOUNT" = "def-CHANGEME" ]; then
    echo "Set ACCOUNT in scripts/slurm/cluster.env first (the def-... string from CCDB)."
    exit 1
fi
mkdir -p slurm_logs

jid0=$(sbatch --parsable --account="$ACCOUNT" scripts/slurm/stage0_checks.sbatch)
echo "stage0 submitted: $jid0"
jid1=$(sbatch --parsable --account="$ACCOUNT" --dependency=afterok:"$jid0" scripts/slurm/stage1_array.sbatch)
echo "stage1 array submitted: $jid1 (depends on $jid0)"
jid2=$(sbatch --parsable --account="$ACCOUNT" --dependency=afterok:"$jid1" scripts/slurm/stage2_post.sbatch)
echo "stage2 submitted: $jid2 (depends on $jid1)"
echo
squeue -u "$USER" -o "%.12i %.12j %.10T %.12M %.6D %R"

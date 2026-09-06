#!/bin/bash
# Stage 2 on the cluster: gate on every displacement being healthy (the
# FAILED.list gate from run_campaign.sh, re-expressed for the array world),
# assemble the timing record, then run scripts/postprocess.py (FORCES_FC3,
# fc2/fc3, q-mesh ladder, kappa_L 300-900 K into ../results/).
#
# Submit via scripts/slurm/submit_all.sh (it supplies --account and the cwd).
#SBATCH --job-name=p3-stage2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=slurm_logs/stage2_%j.out

set -u
cd "$SLURM_SUBMIT_DIR"
source scripts/slurm/cluster.env

# Forensics first: snapshot run states before anything can overwrite them
# (reruns rewrite scf.err/CRASH in place). Snapshots land in slurm_logs/.
bash scripts/slurm/collect_evidence.sh "${SLURM_JOB_ID:-}" || true

source "$P3_VENV/bin/activate"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK"

bad=0
for d in fc_calcs/disp-*/; do
    out="$d/scf.out"
    if ! ( grep -q "JOB DONE" "$out" 2>/dev/null \
        && grep -q "convergence has been achieved" "$out" \
        && grep -q "Forces acting on atoms" "$out" ); then
        echo "UNHEALTHY: $d"
        bad=$((bad+1))
    fi
done
if [ "$bad" -gt 0 ]; then
    echo "$bad unhealthy displacement runs — rerun those array indices before stage 2"
    exit 2
fi

# Timing record for the writeup (separate file from the laptop campaign_log.csv
# because the columns differ: SLURM ntasks instead of kmesh/ecut per row).
echo "run_id,wall_seconds,ntasks,nk,status" > campaign_log_slurm.csv
cat fc_calcs/disp-*/timing.csv >> campaign_log_slurm.csv 2>/dev/null || true

python scripts/postprocess.py

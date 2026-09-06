#!/bin/bash
# Stage 1 as a SLURM job array: one force SCF per array task, 168 tasks total
# (the array range must equal the number of fc_calcs/disp-* directories; edit
# it when porting to another material). Health checks and the nk=1 retry
# mirror scripts/run_campaign.sh stage 1 — that script stays the source of
# truth for campaign semantics; keep the two in sync if either changes.
#
# Submit via scripts/slurm/submit_all.sh (it supplies --account and the cwd).
#SBATCH --job-name=p3-stage1
#SBATCH --array=0-167%32
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=12:00:00
#SBATCH --output=slurm_logs/stage1_%A_%a.out

set -u
cd "$SLURM_SUBMIT_DIR"
source scripts/slurm/cluster.env

mapfile -t DIRS < <(ls -d fc_calcs/disp-*/ | sort)
if [ "$SLURM_ARRAY_TASK_ID" -ge "${#DIRS[@]}" ]; then
    echo "array index $SLURM_ARRAY_TASK_ID beyond ${#DIRS[@]} displacement dirs — nothing to do"
    exit 0
fi
d="${DIRS[$SLURM_ARRAY_TASK_ID]%/}"
id=$(basename "$d" | sed 's/disp-//')

healthy () { # $1=scf.out — same three checks as run_campaign.sh
    grep -q "JOB DONE" "$1" 2>/dev/null \
      && grep -q "convergence has been achieved" "$1" \
      && grep -q "Forces acting on atoms" "$1"
}

run_pw () { # $1=nk
    ( cd "$d" && rm -rf tmp \
      && srun pw.x -nk "$1" -in scf.in > scf.out 2> scf.err )
    rm -rf "$d/tmp"
    healthy "$d/scf.out"
}

if healthy "$d/scf.out"; then
    echo "disp-$id already healthy — skipping"
    exit 0
fi

SECONDS=0
if run_pw "$QE_NK"; then
    echo "$id,$SECONDS,$SLURM_NTASKS,$QE_NK,ok" > "$d/timing.csv"
    exit 0
fi
echo "disp-$id failed, retrying with nk=1"
SECONDS=0
if run_pw 1; then
    echo "$id,$SECONDS,$SLURM_NTASKS,1,ok_retry" > "$d/timing.csv"
    exit 0
fi
echo "$id,$SECONDS,$SLURM_NTASKS,1,FAILED" > "$d/timing.csv"
echo "disp-$id FAILED twice — rerun this array index after diagnosing scf.err"
exit 1

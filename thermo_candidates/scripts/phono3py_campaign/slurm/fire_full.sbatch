#!/bin/bash
# One-shot full FIRE recovery. QE 7.3.1 FIRE markers, not JOB DONE alone,
# are required by fire_recovery.py before this can be a structure acceptance.
#SBATCH --job-name=p3-fire-full
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=12:00:00
set -euo pipefail
umask 027
: "${P3_SLURM_DIR:?}"
source "$P3_SLURM_DIR/cluster.env"
# Deliberate belt-and-braces release boundary: submit.py execute is hard
# locked, and a manually invoked wrapper must fail before an attempt/scratch.
p3_die "FIRE full execution is not released; no execution receipt exists"

#!/bin/bash
# One-shot FIRE pilot.  The immutable gate is deliberately not a structure
# acceptance and its terminal geometry is never a seed for the full run.
#SBATCH --job-name=p3-fire-pilot
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=02:00:00
set -euo pipefail
umask 027
: "${P3_SLURM_DIR:?}"
source "$P3_SLURM_DIR/cluster.env"
# Deliberate belt-and-braces release boundary: submit.py execute is hard
# locked, and a manually invoked wrapper must fail before an attempt/scratch.
p3_die "FIRE pilot execution is not released; no execution receipt exists"

#!/bin/bash
# FC2/FC3 construction and explicit no-NAC RTA q-mesh ladder on Nibi compute.
#SBATCH --job-name=Rb-p3-kappa
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00

set -euo pipefail
umask 027

: "${P3_CLUSTER_ENV:?submit with the exact cluster.env path}"
: "${P3_RUN_DIR:?submit with the exact Rb run directory}"
: "${P3_PRODUCTION_JOB_ID:?submit with the exact completed force-array job ID}"
[[ "$P3_CLUSTER_ENV" == /* && -f "$P3_CLUSTER_ENV" && ! -L "$P3_CLUSTER_ENV" ]]
# shellcheck disable=SC1090
source "$P3_CLUSTER_ENV"
p3_require_compute_node
[[ "$P3_RUN_DIR" == /* && -d "$P3_RUN_DIR" && ! -L "$P3_RUN_DIR" ]]
cd "$P3_RUN_DIR"
[[ "$P3_PRODUCTION_JOB_ID" =~ ^[0-9]+$ ]]
[[ ! -e postprocess ]]
p3_activate_python
"/opt/software/slurm/bin/sacct" -X -j "$P3_PRODUCTION_JOB_ID" \
  --noheader --parsable2 \
  --format=JobIDRaw,JobName,State,ExitCode,Elapsed,Start,End,AllocCPUS,ReqMem,MaxRSS,NodeList \
  > production/sacct.txt
python audit_force_firstpass.py \
  --force-dir production \
  --qe-output-parser qe_output.py \
  --mode production \
  > production/production_audit.json.tmp
mv production/production_audit.json.tmp production/production_audit.json
python run_postprocess_firstpass.py \
  --production-dir production \
  --dataset-dir preflight/M72_cutoff_3p70A \
  --output-dir postprocess \
  > postprocess.stdout 2> postprocess.stderr

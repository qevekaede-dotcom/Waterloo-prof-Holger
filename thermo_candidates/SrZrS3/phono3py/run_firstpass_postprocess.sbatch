#!/bin/bash
# Evidence-first FC2/FC3 construction and no-NAC RTA q-mesh ladder for the
# explicitly authorized, time-bounded SrZrS3 first pass.
#SBATCH --job-name=Sr-p3-firstpass
#SBATCH --partition=cpubase_bycore_b3
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=60G
#SBATCH --time=24:00:00

set -euo pipefail
umask 027

: "${P3_RUN_DIR:?exact SrZrS3 first-pass run directory required}"
: "${P3_SCRIPT_DIR:?exact material-scoped script directory required}"
: "${P3_ATTEMPT_ID:?new postprocess attempt identity required}"
: "${P3_AUDIT_SCRIPT_SHA256:?audit script hash required}"
: "${P3_POSTPROCESS_SCRIPT_SHA256:?postprocess script hash required}"
[[ "${SLURM_JOB_ID:-}" =~ ^[0-9]+$ && -n "${SLURM_JOB_NODELIST:-}" ]]
[[ "$P3_RUN_DIR" == /scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3 ]]
[[ "$P3_SCRIPT_DIR" == "$P3_RUN_DIR/postprocess_tools" && -d "$P3_SCRIPT_DIR" && ! -L "$P3_SCRIPT_DIR" ]]
[[ "$P3_ATTEMPT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]]
[[ "$(sha256sum "$P3_SCRIPT_DIR/audit_firstpass_forces.py" | awk '{print $1}')" == "$P3_AUDIT_SCRIPT_SHA256" ]]
[[ "$(sha256sum "$P3_SCRIPT_DIR/postprocess_firstpass.py" | awk '{print $1}')" == "$P3_POSTPROCESS_SCRIPT_SHA256" ]]

P3_VENV="$HOME/venvs/p3"
[[ -x "$P3_VENV/bin/python" && -x "$P3_VENV/bin/phono3py" && -x "$P3_VENV/bin/phono3py-init" ]]
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:?}"
attempt="$P3_RUN_DIR/postprocess/$P3_ATTEMPT_ID"
[[ ! -e "$attempt" ]]
mkdir -p "$P3_RUN_DIR/postprocess"
mkdir "$attempt"
context="$attempt/context.tsv"
{
  printf 'slurm_job_id\t%s\n' "$SLURM_JOB_ID"
  printf 'slurm_job_account\t%s\n' "${SLURM_JOB_ACCOUNT:-}"
  printf 'slurm_job_partition\t%s\n' "${SLURM_JOB_PARTITION:-}"
  printf 'slurm_job_nodelist\t%s\n' "$SLURM_JOB_NODELIST"
  printf 'slurm_cpus_per_task\t%s\n' "$SLURM_CPUS_PER_TASK"
  printf 'started_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'run_dir\t%s\n' "$P3_RUN_DIR"
  printf 'audit_script_sha256\t%s\n' "$P3_AUDIT_SCRIPT_SHA256"
  printf 'postprocess_script_sha256\t%s\n' "$P3_POSTPROCESS_SCRIPT_SHA256"
  printf 'phono3py_version\t%s\n' \
    "$($P3_VENV/bin/python -c 'import phono3py; print(phono3py.__version__)')"
} > "$context"

/opt/software/slurm/bin/sacct -j 21888373 --starttime 2026-09-13 -X -n -P \
  -o State,ExitCode > "$attempt/sacct-21888373.tsv"
"$P3_VENV/bin/python" "$P3_SCRIPT_DIR/audit_firstpass_forces.py" "$P3_RUN_DIR" \
  --sacct "$attempt/sacct-21888373.tsv" --output "$attempt/force_audit.json" \
  --hashes "$attempt/force_SHA256SUMS" \
  --pilot-attempt "/scratch/yuhansun/phono3py-runs/20260913-sr-count-5733f0c/SrZrS3/slurm_attempts/force/20260914T021218Z-force-1f1dc8ae" \
  --allow-pristine-firstpass-exception \
  --exception-output "$attempt/pristine_firstpass_exception.json" \
  > "$attempt/force_audit.stdout.json"

work="$attempt/work"
"$P3_VENV/bin/python" "$P3_SCRIPT_DIR/postprocess_firstpass.py" "$P3_RUN_DIR" "$work" \
  --phono3py "$P3_VENV/bin/phono3py" --phono3py-init "$P3_VENV/bin/phono3py-init" \
  --force-audit "$attempt/force_audit.json" > "$attempt/postprocess.stdout.json"

date -u +%Y-%m-%dT%H:%M:%SZ > "$attempt/finished_utc.txt"
printf '0\n' > "$attempt/exit_code.txt"
sha256sum "$context" "$attempt/force_audit.json" "$attempt/force_SHA256SUMS" \
  "$attempt/pristine_firstpass_exception.json" \
  "$work/postprocess_result.json" "$work/kappa_mesh_summary.csv" > "$attempt/RESULT_SHA256SUMS"

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
p3_require_compute_node
p3_require_context
: "${P3_FIRE_RECOVERY_SHA256:?FIRE pilot requires the exact backend hash}"
: "${P3_FIRE_LINEAGE_SHA256:?FIRE pilot requires the exact lineage hash}"
: "${P3_FIRE_RELEASE_SHA256:?FIRE pilot requires the exact release-receipt hash}"
: "${P3_GIT_COMMIT:?FIRE pilot requires the exact reviewed git commit}"
: "${P3_FIRE_REQUESTED_WALLTIME_MINUTES:?FIRE pilot requires the exact requested walltime}"
for fire_hash in "$P3_FIRE_RECOVERY_SHA256" "$P3_FIRE_LINEAGE_SHA256" "$P3_FIRE_RELEASE_SHA256"; do
    [[ "$fire_hash" =~ ^[0-9a-f]{64}$ ]] || p3_die "FIRE pilot hash is invalid"
done
[[ "$P3_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] || p3_die "FIRE pilot git commit is invalid"
[[ "$P3_FIRE_REQUESTED_WALLTIME_MINUTES" == "120" ]] || p3_die "FIRE pilot requested walltime drift"
[[ "${SLURM_JOB_ACCOUNT:-}" == "def-kleinke_cpu" ]] || p3_die "FIRE pilot account drift"
[[ "${SLURM_JOB_PARTITION:-}" == "cpubase_bycore_b2" ]] || p3_die "FIRE pilot partition drift"
[[ "${SLURM_JOB_NUM_NODES:-}" == "1" && "${SLURM_NTASKS:-}" == "32" ]] || p3_die "FIRE pilot node/rank drift"
[[ "${SLURM_CPUS_PER_TASK:-1}" == "1" && "${SLURM_MEM_PER_CPU:-}" == "2000" ]] || p3_die "FIRE pilot CPU/memory drift"
[[ -z "${SLURM_TIMELIMIT:-}" || "$SLURM_TIMELIMIT" == "02:00:00" || "$SLURM_TIMELIMIT" == "120" ]] \
    || p3_die "FIRE pilot time-limit drift"
[[ "$("$P3_GIT" -C "$P3_REPO_ROOT" rev-parse HEAD)" == "$P3_GIT_COMMIT" ]] \
    || p3_die "FIRE pilot checkout commit differs from the released lineage"
[[ "$(sha256sum "$FIRE_RECOVERY_CLI" | awk '{print $1}')" == "$P3_FIRE_RECOVERY_SHA256" ]] \
    || p3_die "FIRE recovery backend differs from the submitted workflow"
[[ "$(sha256sum "$RUN_DIR/fire_lineage_receipt.json" | awk '{print $1}')" == "$P3_FIRE_LINEAGE_SHA256" ]] \
    || p3_die "FIRE lineage differs from the submitted request"
[[ "$(sha256sum "$RUN_DIR/fire_pilot_execution_release.json" | awk '{print $1}')" == "$P3_FIRE_RELEASE_SHA256" ]] \
    || p3_die "FIRE pilot release receipt differs from the submitted request"
p3_require_run_directory "slurm_attempts/fire-pilot"
[[ ! -e "$RUN_DIR/slurm_attempts/fire-pilot/$ATTEMPT_ID" ]] \
    || p3_die "FIRE pilot attempt ID has already been consumed"
[[ ! -e "$RUN_DIR/slurm_attempts/fire-pilot/$ATTEMPT_ID/tmp-fire-pilot" ]] \
    || p3_die "FIRE pilot scratch is not fresh"
p3_activate_python
# Full lineage/policy/config/workflow replay occurs before module setup and
# before p3_begin_attempt creates the immutable attempt directory.
if [[ -n "${P3_FIRE_REPLACEMENT_SHA256:-}" ]]; then
    p3_run_fire verify-infrastructure-replacement \
        --config "$CAMPAIGN_CONFIG" --run-dir "$RUN_DIR" \
        --expect-authorization-sha "$P3_FIRE_REPLACEMENT_SHA256" \
        --replacement-attempt-id "$ATTEMPT_ID"
else
    p3_run_fire verify-release --config "$CAMPAIGN_CONFIG" --run-dir "$RUN_DIR"
fi
# The primary is submitted held.  QE is unreachable until submit.py has
# recorded the accepted afterany collector and a successful scontrol release.
fire_submission_dir="$RUN_DIR/submissions/fire-pilot/$ATTEMPT_ID"
for _fire_receipt_wait in $(seq 1 60); do
    [[ -f "$fire_submission_dir/collector_attachment.json" && -f "$fire_submission_dir/primary_release.json" ]] && break
    sleep 1
done
[[ -f "$fire_submission_dir/collector_attachment.json" && -f "$fire_submission_dir/primary_release.json" ]] \
    || p3_die "FIRE pilot release/collector receipts did not become visible"
if [[ -n "${P3_FIRE_REPLACEMENT_SHA256:-}" ]]; then
    p3_run_fire verify-collector-attachment --config "$CAMPAIGN_CONFIG" --run-dir "$RUN_DIR" \
        --primary-attempt-id "$ATTEMPT_ID" --primary-job-id "${SLURM_JOB_ID:?}" \
        --replacement-authorization-sha "$P3_FIRE_REPLACEMENT_SHA256"
else
    p3_run_fire verify-collector-attachment --config "$CAMPAIGN_CONFIG" --run-dir "$RUN_DIR" \
        --primary-attempt-id "$ATTEMPT_ID" --primary-job-id "${SLURM_JOB_ID:?}"
fi
p3_load_qe
p3_begin_attempt fire-pilot
export P3_STAGE="fire-pilot"
export P3_SLURM_NTASKS="${SLURM_NTASKS:?}"
p3_run_fire run --config "$CAMPAIGN_CONFIG" --run-dir "$RUN_DIR" --stage pilot

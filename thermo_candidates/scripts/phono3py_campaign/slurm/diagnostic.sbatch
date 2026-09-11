#!/bin/bash
# One reviewed three-SCF Rb2Cu2SnS4 force-consistency diagnostic.
#
# Allocation settings are deliberately absent here. submit.py must read the
# explicit scheduler.diagnostic_resources policy and pass every resource flag
# to sbatch. This stage never finalizes the diagnostic or releases a polish.
#SBATCH --job-name=p3-diagnostic
#SBATCH --output=slurm-p3-diagnostic-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] \
    || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
: "${P3_DIAGNOSTIC_RESOURCE_SHA256:?submit.py must export the signed diagnostic resource policy}"
: "${P3_DIAGNOSTIC_LINEAGE_SHA256:?submit.py must export the prepared-lineage hash}"
: "${P3_DIAGNOSTIC_BACKEND_SHA256:?submit.py must export the diagnostic backend hash}"
[[ "$P3_DIAGNOSTIC_RESOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || p3_die "diagnostic resource-policy SHA256 is invalid"
[[ "$P3_DIAGNOSTIC_LINEAGE_SHA256" =~ ^[0-9a-f]{64}$ \
    && "$P3_DIAGNOSTIC_BACKEND_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || p3_die "diagnostic lineage/backend SHA256 is invalid"
[[ "$(sha256sum "$RUN_DIR/polish_lineage.json" | awk '{print $1}')" == "$P3_DIAGNOSTIC_LINEAGE_SHA256" ]] \
    || p3_die "prepared polish lineage differs from the submitted request"
[[ "$(sha256sum "$P3_CAMPAIGN_DIR/polish_recovery.py" | awk '{print $1}')" == "$P3_DIAGNOSTIC_BACKEND_SHA256" ]] \
    || p3_die "diagnostic backend differs from the submitted workflow"
[[ ! -e "$RUN_DIR/run_manifest.json" ]] \
    || p3_die "diagnostic is closed after the polish run manifest is released"
# Atomically consume this RUN_DIR's sole diagnostic dispatch before module or
# Python setup. The claim deliberately survives every failure mode, including
# node/module/startup failures before the scientific attempt directory exists.
diagnostic_claim="$RUN_DIR/diagnostic/dispatch_claim"
p3_require_run_directory "diagnostic"
[[ ! -L "$diagnostic_claim" ]] \
    || p3_die "diagnostic dispatch claim path is a symlink"
mkdir "$diagnostic_claim" \
    || p3_die "the single reviewed diagnostic dispatch has already been consumed"
[[ ! -L "$diagnostic_claim" && "$(cd "$diagnostic_claim" && pwd -P)" == "$diagnostic_claim" ]] \
    || p3_die "diagnostic dispatch claim escaped RUN_DIR"
{
    printf 'attempt_id\t%s\n' "$ATTEMPT_ID"
    printf 'slurm_job_id\t%s\n' "${SLURM_JOB_ID:?}"
    printf 'config_sha256\t%s\n' "$P3_EXPECTED_CONFIG_SHA256"
    printf 'lineage_sha256\t%s\n' "$P3_DIAGNOSTIC_LINEAGE_SHA256"
    printf 'resource_sha256\t%s\n' "$P3_DIAGNOSTIC_RESOURCE_SHA256"
    printf 'submit_script_sha256\t%s\n' "$P3_SUBMIT_SCRIPT_SHA256"
    printf 'stage_script_sha256\t%s\n' "$P3_STAGE_SCRIPT_SHA256"
    printf 'cluster_env_sha256\t%s\n' "$P3_CLUSTER_ENV_SHA256"
    printf 'campaign_cli_sha256\t%s\n' "$P3_CAMPAIGN_CLI_SHA256"
    printf 'diagnostic_backend_sha256\t%s\n' "$P3_DIAGNOSTIC_BACKEND_SHA256"
    printf 'claimed_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$diagnostic_claim/context.tsv"
p3_begin_attempt diagnostic
p3_load_qe
p3_activate_python

export P3_STAGE="diagnostic"
export P3_SLURM_NTASKS="${SLURM_NTASKS:?}"
python "$P3_CAMPAIGN_DIR/polish_recovery.py" run-diagnostic \
    --config "$CAMPAIGN_CONFIG" \
    --run-dir "$RUN_DIR" \
    --attempt-id "$ATTEMPT_ID"

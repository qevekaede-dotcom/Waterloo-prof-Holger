#!/bin/bash
# Immutable evidence collection.  Submit this with
# `--dependency=afterany:<diagnostic-relax-or-force-job-id>` so failures are captured
# as well as successful jobs.  This script does not rerun or delete anything.
#SBATCH --job-name=p3-collect
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-p3-collect-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
: "${PRIMARY_STAGE:?submission must export the primary stage}"
: "${PRIMARY_ATTEMPT_ID:?submission must export the primary attempt ID}"
: "${PRIMARY_JOB_ID:?submission must export the primary Slurm job ID}"
[[ "$PRIMARY_STAGE" == "diagnostic" || "$PRIMARY_STAGE" == "relax" || "$PRIMARY_STAGE" == "force" ]] \
    || p3_die "PRIMARY_STAGE must be diagnostic, relax, or force"
[[ "$PRIMARY_ATTEMPT_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]] \
    || p3_die "PRIMARY_ATTEMPT_ID has invalid characters"
[[ "$PRIMARY_ATTEMPT_ID" != "$ATTEMPT_ID" ]] \
    || p3_die "collector and primary attempts must have distinct IDs"
[[ "$PRIMARY_JOB_ID" =~ ^[0-9]+$ ]] \
    || p3_die "PRIMARY_JOB_ID must contain only digits"

EXPECTED_ALLOCATIONS=1
if [[ "$PRIMARY_STAGE" == "diagnostic" ]]; then
    : "${PRIMARY_REQUEST_SHA256:?diagnostic collector requires the primary request hash}"
    : "${PRIMARY_RESULT_SHA256:?diagnostic collector requires the primary response hash}"
    : "${PRIMARY_STAGE_SCRIPT_SHA256:?diagnostic collector requires the primary stage-script hash}"
    for primary_hash in \
        "$PRIMARY_REQUEST_SHA256" \
        "$PRIMARY_RESULT_SHA256" \
        "$PRIMARY_STAGE_SCRIPT_SHA256"; do
        [[ "$primary_hash" =~ ^[0-9a-f]{64}$ ]] \
            || p3_die "diagnostic primary submission hash is invalid"
    done
fi
if [[ "$PRIMARY_STAGE" == "force" ]]; then
    : "${TASK_MAP:?force collector requires the exact immutable task_map.tsv}"
    : "${FORCE_MANIFEST:?force collector requires the exact immutable force_manifest.json}"
    : "${PRIMARY_TASK_MAP_SHA256:?force collector requires the submitted task-map SHA256}"
    : "${PRIMARY_FORCE_MANIFEST_SHA256:?force collector requires the submitted manifest SHA256}"
    [[ "$PRIMARY_TASK_MAP_SHA256" =~ ^[0-9a-f]{64}$ ]] \
        || p3_die "PRIMARY_TASK_MAP_SHA256 is invalid"
    [[ "$PRIMARY_FORCE_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] \
        || p3_die "PRIMARY_FORCE_MANIFEST_SHA256 is invalid"
    [[ "$TASK_MAP" == /* && "$FORCE_MANIFEST" == /* ]] \
        || p3_die "force collection paths must be absolute"
    p3_require_file "force task map" "$TASK_MAP"
    p3_require_file "force manifest" "$FORCE_MANIFEST"
    TASK_MAP="$(cd "$(dirname "$TASK_MAP")" && pwd -P)/$(basename "$TASK_MAP")"
    FORCE_MANIFEST="$(cd "$(dirname "$FORCE_MANIFEST")" && pwd -P)/$(basename "$FORCE_MANIFEST")"
    [[ "$TASK_MAP" == "$RUN_DIR"/* ]] \
        || p3_die "force task map must belong to the selected RUN_DIR"
    [[ "$FORCE_MANIFEST" == "$(dirname "$TASK_MAP")/force_manifest.json" ]] \
        || p3_die "force manifest must be adjacent to the exact task map"
    EXPECTED_ALLOCATIONS="$(awk 'END { print (NR > 0 ? NR - 1 : 0) }' "$TASK_MAP")"
    [[ "$EXPECTED_ALLOCATIONS" =~ ^[1-9][0-9]*$ ]] \
        || p3_die "force task map contains no task rows"
fi
p3_begin_attempt collect
p3_activate_python

# Capture the collector and explicitly named upstream job context.  An
# afterany dependency is set by the submission layer; collection itself must
# still succeed when the upstream state is FAILED, TIMEOUT, or OUT_OF_MEMORY.
if command -v scontrol >/dev/null 2>&1; then
    scontrol show job --oneliner "$SLURM_JOB_ID" \
        > "$P3_ATTEMPT_DIR/slurm_job.txt" \
        2> "$P3_ATTEMPT_DIR/scontrol.err" || true
    scontrol show job --oneliner "$PRIMARY_JOB_ID" \
        > "$P3_ATTEMPT_DIR/primary_slurm_job.txt" \
        2> "$P3_ATTEMPT_DIR/primary_scontrol.err" || true
fi

# Do not summarize sacct in shell.  Preserve every allocation/step row so the
# Python collector and later budget audit can bind JobIDRaw to the exact array
# task and retain MaxRSS from the batch step when Slurm leaves it blank on the
# allocation row.
SACCT_RECORD="$P3_ATTEMPT_DIR/primary_sacct.psv"
SACCT_STATUS="$P3_ATTEMPT_DIR/primary_sacct_exit_code.txt"
SACCT_HEADER='JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS'
SACCT_FORMAT='JobID,JobIDRaw,State,ExitCode,ElapsedRaw,AllocCPUS,MaxRSS'
if [[ "$PRIMARY_STAGE" == "diagnostic" ]]; then
    SACCT_HEADER='JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS|Account|Partition|NNodes|NCPUS|ReqMem|TimelimitRaw'
    SACCT_FORMAT='JobID,JobIDRaw,State,ExitCode,ElapsedRaw,AllocCPUS,MaxRSS,Account,Partition,NNodes,NCPUS,ReqMem,TimelimitRaw'
fi
sacct_rc=127
query_attempt=0
last_record=""
last_error=""
for query_attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    query_label="$(printf '%02d' "$query_attempt")"
    query_record="$P3_ATTEMPT_DIR/primary_sacct-query-$query_label.psv"
    query_error="$P3_ATTEMPT_DIR/primary_sacct-query-$query_label.err"
    printf '%s\n' "$SACCT_HEADER" > "$query_record"
    last_record="$query_record"
    last_error="$query_error"
    if command -v sacct >/dev/null 2>&1; then
        set +e
        LC_ALL=C sacct \
            --jobs "$PRIMARY_JOB_ID" \
            --array \
            --noheader \
            --parsable2 \
            --format="$SACCT_FORMAT" \
            >> "$query_record" \
            2> "$query_error"
        sacct_rc=$?
        set -e
    else
        printf '%s\n' 'sacct command is unavailable' > "$query_error"
        sacct_rc=127
    fi

    observed_allocations=0
    terminal_allocations=0
    if [[ "$sacct_rc" -eq 0 ]]; then
        if [[ "$PRIMARY_STAGE" == "force" ]]; then
            read -r observed_allocations terminal_allocations <<< "$(
                awk -F '|' -v job="$PRIMARY_JOB_ID" \
                    '$1 ~ ("^" job "_[0-9]+$") {
                        count++
                        state = toupper($3)
                        sub(/[ +].*$/, "", state)
                        if (state ~ /^(BOOT_FAIL|CANCELLED|COMPLETED|DEADLINE|FAILED|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|REVOKED|SPECIAL_EXIT|TIMEOUT)$/) terminal++
                    }
                    END { print count + 0, terminal + 0 }' \
                    "$query_record"
            )"
        else
            read -r observed_allocations terminal_allocations <<< "$(
                awk -F '|' -v job="$PRIMARY_JOB_ID" \
                    '$1 == job {
                        count++
                        state = toupper($3)
                        sub(/[ +].*$/, "", state)
                        if (state ~ /^(BOOT_FAIL|CANCELLED|COMPLETED|DEADLINE|FAILED|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|REVOKED|SPECIAL_EXIT|TIMEOUT)$/) terminal++
                    }
                    END { print count + 0, terminal + 0 }' \
                    "$query_record"
            )"
        fi
    fi
    if [[ "$sacct_rc" -eq 0 \
        && "$observed_allocations" -eq "$EXPECTED_ALLOCATIONS" \
        && "$terminal_allocations" -eq "$EXPECTED_ALLOCATIONS" ]]; then
        break
    fi
    if [[ "$sacct_rc" -eq 127 || "$query_attempt" -eq 12 ]]; then
        break
    fi
    sleep 10
done
cp "$last_record" "$SACCT_RECORD"
cp "$last_error" "$P3_ATTEMPT_DIR/primary_sacct.err"
printf '%s\n' "$sacct_rc" > "$SACCT_STATUS"
printf '%s\n' "$query_attempt" > "$P3_ATTEMPT_DIR/primary_sacct_query_count.txt"

collect_args=(
    --primary-stage "$PRIMARY_STAGE"
    --primary-attempt-id "$PRIMARY_ATTEMPT_ID"
    --primary-job-id "$PRIMARY_JOB_ID"
    --scheduler-accounting "$SACCT_RECORD"
    --scheduler-accounting-status "$SACCT_STATUS"
)
if [[ "$PRIMARY_STAGE" == "diagnostic" ]]; then
    collect_args+=(
        --expect-primary-request-sha "$PRIMARY_REQUEST_SHA256"
        --expect-primary-result-sha "$PRIMARY_RESULT_SHA256"
        --expect-primary-stage-script-sha "$PRIMARY_STAGE_SCRIPT_SHA256"
    )
fi
if [[ "$PRIMARY_STAGE" == "force" ]]; then
    collect_args+=(
        --force-manifest "$FORCE_MANIFEST"
        --task-map "$TASK_MAP"
        --expect-force-manifest-sha "$PRIMARY_FORCE_MANIFEST_SHA256"
        --expect-task-map-sha "$PRIMARY_TASK_MAP_SHA256"
    )
fi

export P3_STAGE="collect"
p3_run_cli collect "${collect_args[@]}"

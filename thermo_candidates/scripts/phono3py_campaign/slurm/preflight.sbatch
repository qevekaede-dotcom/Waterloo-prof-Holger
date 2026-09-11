#!/bin/bash
# Compute-node-only phono3py displacement inventory and safety preflight.
# This stage counts candidate supercells and writes auditable plans; the
# public CLI must stop at configured displacement/core-hour caps.
#SBATCH --job-name=p3-preflight
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-p3-preflight-%j.out

set -euo pipefail
umask 027

: "${P3_SLURM_DIR:?submission must export the absolute repository slurm directory}"
[[ "$P3_SLURM_DIR" == /* ]] || { printf 'ERROR: P3_SLURM_DIR must be absolute\n' >&2; exit 2; }
# shellcheck disable=SC1091
source "$P3_SLURM_DIR/cluster.env"
p3_require_compute_node
p3_require_context
candidate_args=()
if [[ -n "${P3_PREFLIGHT_CANDIDATE_IDS:-}" || -n "${P3_PREFLIGHT_CANDIDATE_SHA256:-}" ]]; then
  [[ -n "${P3_PREFLIGHT_CANDIDATE_IDS:-}" && -n "${P3_PREFLIGHT_CANDIDATE_SHA256:-}" ]] \
    || p3_die "preflight candidate ids and SHA256 must be exported together"
  [[ "$P3_PREFLIGHT_CANDIDATE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || p3_die "preflight candidate SHA256 is invalid"
  IFS=':' read -r -a candidate_ids <<< "$P3_PREFLIGHT_CANDIDATE_IDS"
  [[ "${#candidate_ids[@]}" -gt 0 ]] || p3_die "preflight candidate subset is empty"
  for candidate_id in "${candidate_ids[@]}"; do
    [[ "$candidate_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$ ]] \
      || p3_die "preflight candidate id is invalid: $candidate_id"
    candidate_args+=(--candidate-id "$candidate_id")
  done
  candidate_args+=(--expect-candidate-subset-sha "$P3_PREFLIGHT_CANDIDATE_SHA256")
fi
p3_begin_attempt preflight
p3_activate_python

export P3_STAGE="preflight"
p3_run_cli preflight "${candidate_args[@]}"

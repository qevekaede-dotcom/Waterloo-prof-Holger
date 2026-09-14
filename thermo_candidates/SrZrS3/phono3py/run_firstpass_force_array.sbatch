#!/bin/bash
# First-pass SrZrS3 force array. Array bounds/concurrency are supplied by sbatch.
# Task 0 is pristine; tasks 1..787 follow the immutable task_map.tsv.
#SBATCH --job-name=Sr-force-firstpass
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=02:00:00

set -euo pipefail
umask 027

: "${P3_CLUSTER_ENV:?submit with the exact cluster.env path}"
: "${P3_EXPECTED_TASK_MAP_SHA256:?submit with the exact task_map.tsv SHA256}"
[[ "$P3_CLUSTER_ENV" == /* && -f "$P3_CLUSTER_ENV" && ! -L "$P3_CLUSTER_ENV" ]]
# shellcheck disable=SC1090
source "$P3_CLUSTER_ENV"
p3_require_compute_node

cd "$SLURM_SUBMIT_DIR"
[[ ! -L task_map.tsv && -f task_map.tsv ]]
[[ "$(sha256sum task_map.tsv | awk '{print $1}')" == "$P3_EXPECTED_TASK_MAP_SHA256" ]]
[[ "${SLURM_ARRAY_TASK_ID:?}" =~ ^[0-9]+$ ]]

row="$(awk -F '\t' -v id="$SLURM_ARRAY_TASK_ID" 'NR > 1 && $1 == id {print; count++} END {if (count != 1) exit 2}' task_map.tsv)"
IFS=$'\t' read -r task_id displacement_id input_path input_sha256 <<< "$row"
[[ "$task_id" == "$SLURM_ARRAY_TASK_ID" && "$input_path" == "$PWD"/tasks/task-????/scf.in ]]
[[ ! -L "$input_path" && -f "$input_path" ]]
[[ "$(sha256sum "$input_path" | awk '{print $1}')" == "$input_sha256" ]]

task_dir="$(dirname "$input_path")"
cd "$task_dir"
[[ ! -e scf.out && ! -e scf.err && ! -e exit_code.txt ]]
p3_load_qe
date -u +%Y-%m-%dT%H:%M:%SZ > started_utc.txt
set +e
srun pw.x -nk 1 -in scf.in > scf.out 2> scf.err
rc=$?
set -e
printf '%s\n' "$rc" > exit_code.txt
date -u +%Y-%m-%dT%H:%M:%SZ > finished_utc.txt
printf '%s\t%s\n' "$task_id" "$displacement_id" > task_identity.tsv
exit "$rc"

#!/bin/bash
# One immutable Rb2Cu2SnS4 force task selected from a generated task map.
#SBATCH --job-name=Rb-p3-force
#SBATCH --partition=cpubase_bycore_b2
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=2000M
#SBATCH --time=02:00:00

set -euo pipefail
umask 027

: "${P3_CLUSTER_ENV:?submit with the exact cluster.env path}"
: "${P3_TASK_MAP:?submit with the absolute task_map.tsv path}"
: "${P3_TASK_MAP_SHA256:?submit with the exact task-map SHA256}"
: "${SLURM_ARRAY_TASK_ID:?submit as an array derived from task_map.tsv}"
[[ "$P3_CLUSTER_ENV" == /* && -f "$P3_CLUSTER_ENV" && ! -L "$P3_CLUSTER_ENV" ]]
# shellcheck disable=SC1090
source "$P3_CLUSTER_ENV"
p3_require_compute_node
[[ "$P3_TASK_MAP" == /* && -f "$P3_TASK_MAP" && ! -L "$P3_TASK_MAP" ]]
[[ "$(sha256sum "$P3_TASK_MAP" | awk '{print $1}')" == "$P3_TASK_MAP_SHA256" ]]
[[ "$SLURM_ARRAY_TASK_ID" =~ ^[0-9]+$ ]]

row=$(sed -n "$((SLURM_ARRAY_TASK_ID + 2))p" "$P3_TASK_MAP")
[[ -n "$row" ]]
IFS=$'\t' read -r task_index label input_path input_sha expected_atoms <<< "$row"
[[ "$task_index" == "$SLURM_ARRAY_TASK_ID" ]]
[[ "$input_path" == /* && -f "$input_path" && ! -L "$input_path" ]]
[[ "$(sha256sum "$input_path" | awk '{print $1}')" == "$input_sha" ]]
task_dir=$(dirname "$input_path")
cd "$task_dir"
[[ ! -e scf.out && ! -e scf.err && ! -e exit_code.txt && ! -e tmp ]]

p3_load_qe
date -u +%Y-%m-%dT%H:%M:%SZ > started_utc.txt
set +e
srun pw.x -nk 1 -in scf.in > scf.out 2> scf.err
rc=$?
set -e
printf '%s\n' "$rc" > exit_code.txt
date -u +%Y-%m-%dT%H:%M:%SZ > finished_utc.txt
rm -rf tmp
exit "$rc"

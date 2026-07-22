#!/usr/bin/env bash

set -euo pipefail

np="${QE_NP:-8}"
nk="${QE_NK:-2}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
input="$here/00_relax/Rb2Cu2SnS4.relax.in"
output="$here/../logs/Rb2Cu2SnS4.relax.out"

mkdir -p "$here/tmp/relax" "$here/../logs"
if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
  printf 'Skipping completed vc-relax: %s\n' "$output"
  exit 0
fi

printf 'Running vc-relax with %s MPI ranks, %s k-point pools, %s thread ...\n' \
  "$np" "$nk" "$OMP_NUM_THREADS"
cd "$here"
mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"

if ! grep -q 'JOB DONE' "$output"; then
  printf 'QE did not finish cleanly: %s\n' "$output" >&2
  exit 1
fi
printf 'Finished vc-relax: %s\n' "$output"

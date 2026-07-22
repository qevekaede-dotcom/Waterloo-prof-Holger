#!/usr/bin/env bash

set -euo pipefail

np="${QE_NP:-8}"
nk="${QE_NK:-2}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
input="$here/01_scf/SrCu2SnS4.scf.in"
output="$here/../logs/SrCu2SnS4.scf.out"

mkdir -p "$here/tmp/final" "$here/../logs"
if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
  printf 'Skipping completed final SCF: %s\n' "$output"
  exit 0
fi

printf 'Running final SCF with %s MPI ranks, %s k-point pools, %s thread ...\n' \
  "$np" "$nk" "$OMP_NUM_THREADS"
cd "$here"
mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"

if ! grep -q 'JOB DONE' "$output"; then
  printf 'QE did not finish cleanly: %s\n' "$output" >&2
  exit 1
fi
printf 'Finished final SCF: %s\n' "$output"

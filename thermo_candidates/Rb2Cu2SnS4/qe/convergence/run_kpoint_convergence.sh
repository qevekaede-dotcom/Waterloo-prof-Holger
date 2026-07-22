#!/usr/bin/env bash

set -euo pipefail

np="${QE_NP:-4}"
nk="${QE_NK:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here/kpoints"
mkdir -p outputs tmp

for input in inputs/k_*.in; do
  name="$(basename "$input" .in)"
  output="outputs/${name}.out"

  if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
    printf 'Skipping completed %s\n' "$name"
    continue
  fi

  printf 'Running %-10s with %s MPI ranks, %s k-point pools, %s thread ...\n' \
    "$name" "$np" "$nk" "$OMP_NUM_THREADS"
  start="$SECONDS"
  mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"
  if ! grep -q 'JOB DONE' "$output"; then
    printf 'QE did not finish cleanly: %s\n' "$output" >&2
    exit 1
  fi
  printf 'Finished %-10s in %s s\n' "$name" "$((SECONDS - start))"
done

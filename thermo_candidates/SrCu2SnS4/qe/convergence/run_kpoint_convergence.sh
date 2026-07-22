#!/usr/bin/env bash

set -euo pipefail

np="${QE_NP:-4}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here/kpoints"
mkdir -p outputs tmp

meshes=(2x2x1 3x3x2 4x4x2 5x5x3)
for mesh in "${meshes[@]}"; do
  input="inputs/k_${mesh}.in"
  output="outputs/k_${mesh}.out"

  if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
    printf 'Skipping completed k_%s\n' "$mesh"
    continue
  fi

  printf 'Running k_%-7s with %s MPI ranks x %s OpenMP thread ...\n' \
    "$mesh" "$np" "$OMP_NUM_THREADS"
  start="$SECONDS"
  mpirun -np "$np" pw.x -in "$input" > "$output"
  if ! grep -q 'JOB DONE' "$output"; then
    printf 'QE did not finish cleanly: %s\n' "$output" >&2
    exit 1
  fi
  printf 'Finished k_%-7s in %s s\n' "$mesh" "$((SECONDS - start))"
done

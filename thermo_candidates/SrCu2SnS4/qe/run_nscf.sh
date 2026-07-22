#!/usr/bin/env bash

set -euo pipefail

np="${QE_NP:-8}"
nk="${QE_NK:-4}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
input="$here/02_nscf/SrCu2SnS4.nscf.in"
output="$here/../logs/SrCu2SnS4.nscf.out"
scf_xml="$here/tmp/final/SrCu2SnS4.save/data-file-schema.xml"

if [ ! -f "$scf_xml" ]; then
  printf 'Missing final SCF data: %s\n' "$scf_xml" >&2
  exit 1
fi
if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
  printf 'Skipping completed NSCF: %s\n' "$output"
  exit 0
fi

printf 'Running dense NSCF with %s MPI ranks, %s k-point pools, %s thread ...\n' \
  "$np" "$nk" "$OMP_NUM_THREADS"
cd "$here"
mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"

if ! grep -q 'JOB DONE' "$output"; then
  printf 'QE did not finish cleanly: %s\n' "$output" >&2
  exit 1
fi
printf 'Finished dense NSCF: %s\n' "$output"

#!/usr/bin/env bash

set -euo pipefail

np="${QE_NP:-4}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$root"
mkdir -p tmp ../logs

run_pw() {
  local stage="$1"
  local input="$2"
  local output="$3"

  if [ ! -f "$input" ]; then
    printf 'Missing %s input: %s\n' "$stage" "$input"
    return 1
  fi

  printf 'Running %s with %s MPI ranks\n' "$stage" "$np"
  mpirun -np "$np" pw.x -in "$input" > "$output"
}

run_pw relax 00_relax/SrZrS3.relax.in ../logs/SrZrS3.relax.out
run_pw scf 01_scf/SrZrS3.scf.in ../logs/SrZrS3.scf.out
run_pw nscf 02_nscf/SrZrS3.nscf.in ../logs/SrZrS3.nscf.out


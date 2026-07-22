#!/usr/bin/env bash

set -u

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

printf 'Workspace: %s\n' "$root"
printf 'Date: %s\n' "$(date)"

printf '\n== Tool paths ==\n'
for tool in python pw.x mpirun btp2; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '%-8s %s\n' "$tool" "$(command -v "$tool")"
  else
    printf '%-8s not found\n' "$tool"
  fi
done

printf '\n== Pseudopotential directory ==\n'
printf 'QE_PSEUDO_SSSP_PBE_PRECISION: %s\n' "${QE_PSEUDO_SSSP_PBE_PRECISION:-not set}"

if [ -n "${QE_PSEUDO_SSSP_PBE_PRECISION:-}" ]; then
  for pp in \
    Rb_ONCV_PBE-1.0.oncvpsp.upf \
    Sr_pbe_v1.uspp.F.UPF \
    Cu.paw.z_11.ld1.psl.v1.0.0-low.upf \
    Sn_pbe_v1.uspp.F.UPF \
    Zr_pbe_v1.uspp.F.UPF \
    s_pbe_v1.4.uspp.F.UPF
  do
    if [ -f "$QE_PSEUDO_SSSP_PBE_PRECISION/$pp" ]; then
      printf 'found   %s\n' "$pp"
    else
      printf 'missing %s\n' "$pp"
    fi
  done
fi

printf '\n== Candidate folders ==\n'
for candidate in SrCu2SnS4 SrZrS3 Rb2Cu2SnS4; do
  if [ -d "$root/$candidate" ]; then
    printf 'found   %s\n' "$candidate"
  else
    printf 'missing %s\n' "$candidate"
  fi
done


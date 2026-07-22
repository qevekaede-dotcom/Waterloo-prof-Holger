#!/usr/bin/env bash

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

qe_source="qe/tmp/final/SrCu2SnS4.save"
bt2_file="boltztrap2/SrCu2SnS4.bt2"
log_dir="logs"
workers="${BT2_NP:-4}"
doping_levels="-1e21,-5e20,-2e20,-1e20,-5e19,-2e19,-1e19,1e19,2e19,5e19,1e20,2e20,5e20,1e21"
btp2_cmd=(python boltztrap2/btp2_compat.py)

if [ ! -f "$qe_source/data-file-schema.xml" ]; then
  printf 'Missing dense NSCF QE XML: %s/data-file-schema.xml\n' "$qe_source"
  printf 'Run QE SCF and dense NSCF first.\n'
  exit 1
fi

mkdir -p "$log_dir"
if [ ! -f "$bt2_file" ]; then
  "${btp2_cmd[@]}" -n "$workers" -v interpolate -m 5 -o "$bt2_file" "$qe_source" \
    2>&1 | tee "$log_dir/SrCu2SnS4.bt2.interpolate.log"
fi

"${btp2_cmd[@]}" -v integrate "$bt2_file" 300:1000:100 \
  2>&1 | tee "$log_dir/SrCu2SnS4.bt2.integrate.log"
"${btp2_cmd[@]}" -v dope "$bt2_file" 300:1000:100 "$doping_levels" \
  2>&1 | tee "$log_dir/SrCu2SnS4.bt2.dope.log"

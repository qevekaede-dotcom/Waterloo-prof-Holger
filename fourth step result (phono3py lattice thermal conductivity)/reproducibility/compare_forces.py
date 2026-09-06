#!/usr/bin/env python
"""Compare QE force blocks of two pw.x outputs against a threshold.

Usage: compare_forces.py REFERENCE.out CANDIDATE.out THRESHOLD_RY_PER_BOHR

Prints a short report ending in machine-readable lines:
  MAXDIFF=<value>
  RESULT=PASS|FAIL
The campaign driver turns PASS/FAIL into k-mesh / cutoff decisions.
"""

import re
import sys


def read_forces(path):
    forces = []
    with open(path) as f:
        text = f.read()
    block = re.search(
        r"Forces acting on atoms.*?\n(.*?)\n\s*Total force", text, re.S
    )
    if not block:
        sys.exit(f"no force block in {path}")
    for line in block.group(1).splitlines():
        m = re.search(
            r"atom\s+\d+\s+type\s+\d+\s+force =\s+(\S+)\s+(\S+)\s+(\S+)", line
        )
        if m:
            forces.append([float(x) for x in m.groups()])
    if not forces:
        sys.exit(f"force block empty in {path}")
    return forces


def main():
    ref_path, cand_path, thresh = sys.argv[1], sys.argv[2], float(sys.argv[3])
    ref = read_forces(ref_path)
    cand = read_forces(cand_path)
    if len(ref) != len(cand):
        sys.exit(f"atom count mismatch: {len(ref)} vs {len(cand)}")
    max_diff = max(
        abs(a - b) for ra, rc in zip(ref, cand) for a, b in zip(ra, rc)
    )
    max_force = max(abs(c) for row in ref for c in row)
    print(f"# reference: {ref_path}")
    print(f"# candidate: {cand_path}")
    print(f"# atoms: {len(ref)}")
    print(f"# max |F| (reference): {max_force:.3e} Ry/bohr")
    print(f"# max |dF|: {max_diff:.3e} Ry/bohr (threshold {thresh:.1e})")
    print(f"MAXDIFF={max_diff:.3e}")
    print(f"RESULT={'PASS' if max_diff <= thresh else 'FAIL'}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Collect the SrZrS3 k-point test energies into the standard CSV.

Produces kpoint_results.csv with the same columns as the SrCu2SnS4 record:
  mesh,full_kpoints,irreducible_kpoints,total_energy_Ry,delta_meV_per_atom_vs_max
"""

from pathlib import Path
import csv
import re

RY_TO_MEV = 13605.693122994
HERE = Path(__file__).resolve().parent
OUTPUTS = HERE / "kpoints" / "outputs"
NAT = 20


def parse(path: Path):
    text = path.read_text()
    if "JOB DONE" not in text:
        return None
    energy = float(re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)[-1])
    irr = int(re.search(r"number of k points=\s*(\d+)", text).group(1))
    mesh = re.search(r"k_(\d+)x(\d+)x(\d+)", path.stem).groups()
    mesh = tuple(int(n) for n in mesh)
    full = mesh[0] * mesh[1] * mesh[2]
    return full, mesh, irr, energy


def main() -> None:
    rows = sorted(
        (r for r in (parse(p) for p in OUTPUTS.glob("k_*.out")) if r),
        key=lambda r: r[0],
    )
    if not rows:
        raise SystemExit(f"No completed runs found in {OUTPUTS}")
    e_ref = rows[-1][3]  # densest mesh = reference
    out = HERE / "kpoint_results.csv"
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "mesh", "full_kpoints", "irreducible_kpoints",
            "total_energy_Ry", "delta_meV_per_atom_vs_max",
        ])
        for full, mesh, irr, energy in rows:
            delta = abs(energy - e_ref) * RY_TO_MEV / NAT
            writer.writerow([
                "x".join(str(n) for n in mesh), full, irr,
                f"{energy:.8f}", delta,
            ])
    print(f"Wrote {out} ({len(rows)} rows, reference = "
          f"{'x'.join(str(n) for n in rows[-1][1])})")


if __name__ == "__main__":
    main()

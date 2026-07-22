#!/usr/bin/env python3
"""Collect the SrZrS3 cutoff-test energies into the standard CSV.

Produces cutoff_results.csv with the same columns as the SrCu2SnS4 record:
  ecutwfc_Ry,ecutrho_Ry,total_energy_Ry,delta_meV_per_atom_vs_max,pressure_kbar
"""

from pathlib import Path
import csv
import re

RY_TO_MEV = 13605.693122994
HERE = Path(__file__).resolve().parent
OUTPUTS = HERE / "cutoff" / "outputs"
NAT = 20


def parse(path: Path):
    text = path.read_text()
    if "JOB DONE" not in text:
        return None
    energy = float(re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)[-1])
    pressures = re.findall(r"P=\s*([-\d.]+)", text)
    pressure = float(pressures[-1]) if pressures else float("nan")
    cutoff = int(re.search(r"ecut_(\d+)", path.stem).group(1))
    return cutoff, energy, pressure


def main() -> None:
    rows = sorted(
        r for r in (parse(p) for p in OUTPUTS.glob("ecut_*.out")) if r
    )
    if not rows:
        raise SystemExit(f"No completed runs found in {OUTPUTS}")
    e_ref = rows[-1][1]  # highest cutoff = reference
    out = HERE / "cutoff_results.csv"
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "ecutwfc_Ry", "ecutrho_Ry", "total_energy_Ry",
            "delta_meV_per_atom_vs_max", "pressure_kbar",
        ])
        for cutoff, energy, pressure in rows:
            delta = abs(energy - e_ref) * RY_TO_MEV / NAT
            writer.writerow([cutoff, cutoff * 8, f"{energy:.8f}", delta, pressure])
    print(f"Wrote {out} ({len(rows)} rows, reference = {rows[-1][0]} Ry)")


if __name__ == "__main__":
    main()

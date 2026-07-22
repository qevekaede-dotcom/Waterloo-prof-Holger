#!/usr/bin/env python3
"""Summarize QE k-point outputs as energy differences per atom."""

from pathlib import Path
import csv
import re


HERE = Path(__file__).resolve().parent
OUTPUTS = HERE / "kpoints" / "outputs"
RESULTS = HERE / "kpoints" / "kpoint_results.csv"
MESHES = ((2, 2, 1), (3, 3, 2), (4, 4, 2), (5, 5, 3))
ENERGY_RE = re.compile(r"!\s+total energy\s+=\s+([-+0-9.Ee]+)\s+Ry")
KPOINT_RE = re.compile(r"number of k points=\s*(\d+)")
RY_TO_EV = 13.605693122994
NAT = 24


def last_match(pattern: re.Pattern[str], text: str) -> float:
    matches = pattern.findall(text)
    if not matches:
        raise ValueError(f"Could not find {pattern.pattern}")
    return float(matches[-1])


def main() -> None:
    rows = []
    for mesh in MESHES:
        label = "x".join(str(value) for value in mesh)
        output = OUTPUTS / f"k_{label}.out"
        if not output.exists():
            continue
        text = output.read_text(errors="replace")
        if "JOB DONE" not in text:
            continue
        rows.append(
            {
                "mesh": label,
                "full_kpoints": mesh[0] * mesh[1] * mesh[2],
                "irreducible_kpoints": int(last_match(KPOINT_RE, text)),
                "total_energy_Ry": last_match(ENERGY_RE, text),
            }
        )

    if not rows:
        raise SystemExit("No completed k-point outputs found")

    reference = rows[-1]["total_energy_Ry"]
    for row in rows:
        row["delta_meV_per_atom_vs_max"] = (
            (row["total_energy_Ry"] - reference) * RY_TO_EV * 1000 / NAT
        )

    fields = (
        "mesh",
        "full_kpoints",
        "irreducible_kpoints",
        "total_energy_Ry",
        "delta_meV_per_atom_vs_max",
    )
    with RESULTS.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("mesh     irreducible k-points   delta vs max")
    for row in rows:
        print(
            f"{row['mesh']:<8} {row['irreducible_kpoints']:>8}              "
            f"{row['delta_meV_per_atom_vs_max']:>10.4f} meV/atom"
        )
    print(f"Wrote {RESULTS.relative_to(HERE)}")


if __name__ == "__main__":
    main()

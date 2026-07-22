#!/usr/bin/env python3
"""Summarize QE cutoff outputs as energy differences per atom."""

from pathlib import Path
import csv
import re


HERE = Path(__file__).resolve().parent
OUTPUTS = HERE / "cutoff" / "outputs"
RESULTS = HERE / "cutoff" / "cutoff_results.csv"
ENERGY_RE = re.compile(r"!\s+total energy\s+=\s+([-+0-9.Ee]+)\s+Ry")
PRESSURE_RE = re.compile(r"P=\s*([-+0-9.Ee]+)")
RY_TO_EV = 13.605693122994
NAT = 24


def last_match(pattern: re.Pattern[str], text: str) -> float:
    matches = pattern.findall(text)
    if not matches:
        raise ValueError(f"Could not find {pattern.pattern}")
    return float(matches[-1])


def main() -> None:
    rows = []
    outputs = sorted(
        OUTPUTS.glob("ecut_*.out"),
        key=lambda path: int(path.stem.split("_")[1]),
    )
    for output in outputs:
        cutoff = int(output.stem.split("_")[1])
        text = output.read_text(errors="replace")
        if "JOB DONE" not in text:
            continue
        rows.append(
            {
                "ecutwfc_Ry": cutoff,
                "ecutrho_Ry": cutoff * 8,
                "total_energy_Ry": last_match(ENERGY_RE, text),
                "pressure_kbar": last_match(PRESSURE_RE, text),
            }
        )

    if not rows:
        raise SystemExit("No completed cutoff outputs found")

    reference = rows[-1]["total_energy_Ry"]
    for row in rows:
        row["delta_meV_per_atom_vs_max"] = (
            (row["total_energy_Ry"] - reference) * RY_TO_EV * 1000 / NAT
        )

    fields = (
        "ecutwfc_Ry",
        "ecutrho_Ry",
        "total_energy_Ry",
        "delta_meV_per_atom_vs_max",
        "pressure_kbar",
    )
    with RESULTS.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("ecutwfc  delta vs max       pressure")
    for row in rows:
        print(
            f"{row['ecutwfc_Ry']:>4} Ry  "
            f"{row['delta_meV_per_atom_vs_max']:>10.4f} meV/atom  "
            f"{row['pressure_kbar']:>10.3f} kbar"
        )
    print(f"Wrote {RESULTS.relative_to(HERE)}")


if __name__ == "__main__":
    main()

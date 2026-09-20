#!/usr/bin/env python3
"""Generate material-specific count-only Rb2Cu2SnS4 displacement candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import yaml


TOLERANCE_BOHR = 1.88972612462577e-5  # 1e-5 angstrom
AMPLITUDE_BOHR = 0.0566917837388  # 0.03 angstrom
CANDIDATES = (
    ("M72_cutoff_3p70A", (0, 1, 1, 2, 0, 1, 2, 1, 0), 6.991986661115, 72),
    ("M72_cutoff_4p25A", (0, 1, 1, 2, 0, 1, 2, 1, 0), 8.031336029660, 72),
    ("M72_cutoff_5p00A", (0, 1, 1, 2, 0, 1, 2, 1, 0), 9.448630623129, 72),
    ("M108_cutoff_4p25A", (0, 1, 1, 3, 0, 1, 3, 1, 0), 8.031336029660, 108),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lattice_lengths(lattice: list[list[float]]) -> list[float]:
    return [math.sqrt(sum(value * value for value in vector)) for vector in lattice]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unitcell", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to reuse {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    unitcell_hash = sha256(args.unitcell)
    records: list[dict[str, object]] = []

    for name, dim, cutoff, expected_atoms in CANDIDATES:
        candidate = args.output_dir / name
        candidate.mkdir()
        local_unitcell = candidate / "unitcell.in"
        local_unitcell.write_bytes(args.unitcell.read_bytes())
        command = [
            "phono3py-init", "--qe", "-d", "-c", "unitcell.in", "--pa", "P",
            "--tolerance", f"{TOLERANCE_BOHR:.15g}",
            "--amplitude", f"{AMPLITUDE_BOHR:.15g}",
            "--cutoff-pair", f"{cutoff:.15g}", "--dim", *[str(value) for value in dim],
        ]
        completed = subprocess.run(
            command, cwd=candidate, text=True, capture_output=True, check=False
        )
        (candidate / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        (candidate / "stdout.txt").write_text(completed.stdout)
        (candidate / "stderr.txt").write_text(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"{name} failed with exit {completed.returncode}")
        yaml_path = candidate / "phono3py_disp.yaml"
        data = yaml.safe_load(yaml_path.read_text())
        length_unit = data.get("physical_unit", {}).get("length")
        supercell = data.get("supercell", {})
        points = supercell.get("points", [])
        lattice = supercell.get("lattice", [])
        generated = sorted(candidate.glob("supercell-[0-9][0-9][0-9][0-9][0-9].in"))
        if length_unit != "au":
            raise ValueError(f"{name}: expected physical_unit.length=au, got {length_unit!r}")
        if len(points) != expected_atoms:
            raise ValueError(f"{name}: expected {expected_atoms} atoms, got {len(points)}")
        records.append({
            "candidate": name,
            "command": command,
            "supercell_matrix": data.get("supercell_matrix"),
            "cutoff_pair_distance_bohr": cutoff,
            "cutoff_pair_distance_angstrom": cutoff * 0.529177210903,
            "amplitude_bohr": AMPLITUDE_BOHR,
            "amplitude_angstrom": AMPLITUDE_BOHR * 0.529177210903,
            "physical_unit_length": length_unit,
            "supercell_atoms": len(points),
            "supercell_lattice_bohr": lattice,
            "supercell_edge_lengths_bohr": lattice_lengths(lattice),
            "displacement_supercells": len(generated),
            "phono3py_disp_sha256": sha256(yaml_path),
        })

    report = {
        "document_type": "rb_firstpass_displacement_preflight",
        "phono3py_version": "4.4.0",
        "calculator": "qe",
        "unitcell": str(args.unitcell.resolve()),
        "unitcell_sha256": unitcell_hash,
        "symmetry_tolerance_bohr": TOLERANCE_BOHR,
        "symmetry_tolerance_angstrom": TOLERANCE_BOHR * 0.529177210903,
        "candidates": records,
    }
    (args.output_dir / "preflight_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

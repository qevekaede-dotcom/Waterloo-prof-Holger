#!/usr/bin/env python3
"""Audit the time-bounded Rb2Cu2SnS4 FIRE result from raw QE evidence.

The final force is delegated to the campaign's strict qe_output.py parser.
This companion check verifies the required FIRE markers, cell/atom ordering,
terminal-coordinate placement, displacement from the submitted seed, and the
terminal space group.  It prints a machine-readable JSON record and does not
modify the source evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import spglib


FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"


def load_qe_output(path: Path):
    spec = importlib.util.spec_from_file_location("qe_output", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import strict parser from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_input(path: Path) -> tuple[list[str], np.ndarray, np.ndarray]:
    text = path.read_text(errors="strict")
    pos_match = re.search(
        r"^ATOMIC_POSITIONS\s*\(crystal\)\s*$\n(?P<body>(?:.*\n){18})",
        text,
        re.MULTILINE,
    )
    cell_match = re.search(
        r"^CELL_PARAMETERS\s+angstrom\s*$\n(?P<body>(?:.*\n){3})",
        text,
        re.MULTILINE,
    )
    if not pos_match or not cell_match:
        raise ValueError("input lacks the expected crystal positions or angstrom cell")
    labels: list[str] = []
    positions: list[list[float]] = []
    for line in pos_match.group("body").splitlines():
        fields = line.split()
        labels.append(fields[0])
        positions.append([float(value.replace("D", "E")) for value in fields[1:4]])
    cell = np.array(
        [[float(value.replace("D", "E")) for value in line.split()[:3]]
         for line in cell_match.group("body").splitlines()],
        dtype=float,
    )
    return labels, np.array(positions, dtype=float), cell


def parse_final_positions(output: Path) -> tuple[list[str], np.ndarray, int, int]:
    text = output.read_text(errors="replace")
    starts = list(re.finditer(r"^\s*Begin final coordinates\s*$", text, re.MULTILINE))
    ends = list(re.finditer(r"^\s*End final coordinates\s*$", text, re.MULTILINE))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() <= starts[0].end():
        raise ValueError("expected exactly one ordered final-coordinate block")
    block = text[starts[0].end():ends[0].start()]
    pos_match = re.search(
        r"^ATOMIC_POSITIONS\s*\(crystal\)\s*$\n(?P<body>(?:.*\n){18})",
        block,
        re.MULTILINE,
    )
    if not pos_match:
        raise ValueError("final-coordinate block lacks 18 crystal-coordinate rows")
    labels: list[str] = []
    positions: list[list[float]] = []
    for line in pos_match.group("body").splitlines():
        fields = line.split()
        labels.append(fields[0])
        positions.append([float(value.replace("D", "E")) for value in fields[1:4]])
    return labels, np.array(positions, dtype=float), starts[0].start(), ends[0].end()


def minimum_image_shifts(
    initial_frac: np.ndarray, final_frac: np.ndarray, cell: np.ndarray
) -> np.ndarray:
    delta = final_frac - initial_frac
    delta -= np.rint(delta)
    return delta @ cell


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qe-output-parser", type=Path, required=True)
    args = parser.parse_args()

    qe_output = load_qe_output(args.qe_output_parser)
    strict = qe_output.inspect_output(args.output, 18)
    record = qe_output.parse_last_force_block(args.output, 18)
    text = args.output.read_text(errors="replace")
    initial_labels, initial_frac, cell = parse_input(args.input)
    final_labels, final_frac, final_start, final_end = parse_final_positions(args.output)
    shifts = minimum_image_shifts(initial_frac, final_frac, cell)
    shift_norms = np.linalg.norm(shifts, axis=1)

    numbers = {"Rb": 37, "Cu": 29, "Sn": 50, "S": 16}
    symmetry = spglib.get_symmetry_dataset(
        (cell, final_frac, [numbers[label] for label in final_labels]), symprec=1e-6
    )
    if symmetry is None:
        raise ValueError("spglib returned no symmetry dataset at 1e-6 angstrom")

    fire_converged = text.count("FIRE: convergence achieved in") == 1
    fire_ended = text.count("End of FIRE minimization") == 1
    job_done = text.count("JOB DONE.") == 1
    markers_in_order = (
        text.find("FIRE: convergence achieved in")
        < text.find("End of FIRE minimization")
        < final_start
        < final_end
        < text.find("JOB DONE.")
    )
    no_failure = not any(
        marker in text
        for marker in (
            "convergence NOT achieved",
            "Error in routine",
            "Maximum CPU time exceeded",
            "%%%%%%",
        )
    )
    atom_order_unchanged = initial_labels == final_labels
    result = {
        "document_type": "rb_fire_firstpass_audit",
        "input": str(args.input),
        "output": str(args.output),
        "strict_qe_output": strict,
        "fire_convergence_marker": fire_converged,
        "fire_end_marker": fire_ended,
        "job_done_marker": job_done,
        "markers_in_required_order": markers_in_order,
        "no_known_failure_marker": no_failure,
        "atom_count": len(final_labels),
        "atom_order_unchanged": atom_order_unchanged,
        "cell_fixed_by_input": True,
        "cell_vectors_angstrom": cell.tolist(),
        "cell_volume_angstrom3": float(abs(np.linalg.det(cell))),
        "maximum_seed_to_terminal_shift_angstrom": float(shift_norms.max()),
        "rms_seed_to_terminal_shift_angstrom": float(
            math.sqrt(float(np.mean(shift_norms ** 2)))
        ),
        "terminal_max_abs_force_component_ry_bohr": record.max_abs_ry_bohr,
        "terminal_total_force_ry_bohr": record.total_force_ry_bohr,
        "terminal_spacegroup_symbol": symmetry.international,
        "terminal_spacegroup_number": int(symmetry.number),
        "symmetry_tolerance_angstrom": 1e-6,
    }
    result["pass"] = bool(
        strict["healthy"]
        and fire_converged
        and fire_ended
        and job_done
        and markers_in_order
        and no_failure
        and atom_order_unchanged
        and record.max_abs_ry_bohr <= 5e-5
        and shift_norms.max() <= 0.02
        and symmetry.international == "Ibam"
        and int(symmetry.number) == 72
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

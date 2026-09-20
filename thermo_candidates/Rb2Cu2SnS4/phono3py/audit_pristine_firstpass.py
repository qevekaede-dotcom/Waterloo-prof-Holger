#!/usr/bin/env python3
"""Audit the independent pristine SCF and its exact FIRE-geometry lineage."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import spglib


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fire-output", type=Path, required=True)
    parser.add_argument("--pristine-input", type=Path, required=True)
    parser.add_argument("--pristine-output", type=Path, required=True)
    parser.add_argument("--pristine-stderr", type=Path, required=True)
    parser.add_argument("--exit-code", type=Path, required=True)
    parser.add_argument("--fire-audit-script", type=Path, required=True)
    parser.add_argument("--qe-output-parser", type=Path, required=True)
    args = parser.parse_args()

    fire_audit = load_module("audit_fire_firstpass", args.fire_audit_script)
    qe = load_module("qe_output", args.qe_output_parser)
    labels, pristine_frac, cell = fire_audit.parse_input(args.pristine_input)
    fire_labels, fire_frac, _, _ = fire_audit.parse_final_positions(args.fire_output)
    strict = qe.inspect_output(args.pristine_output, 18)
    numbers = {"Rb": 37, "Cu": 29, "Sn": 50, "S": 16}
    symmetry = spglib.get_symmetry_dataset(
        (cell, pristine_frac, [numbers[label] for label in labels]), symprec=1e-6
    )
    if symmetry is None:
        raise ValueError("spglib returned no pristine-input symmetry")
    exact_geometry = labels == fire_labels and bool(np.allclose(pristine_frac, fire_frac, rtol=0, atol=5e-11))
    clean_process = args.exit_code.read_text().strip() == "0" and not args.pristine_stderr.read_text().strip()
    result = {
        "document_type": "rb_pristine_firstpass_audit",
        "strict_qe_output": strict,
        "clean_process_exit_and_stderr": clean_process,
        "atom_count": len(labels),
        "atom_order_matches_FIRE_terminal": labels == fire_labels,
        "coordinates_match_FIRE_terminal": exact_geometry,
        "cell_vectors_angstrom": cell.tolist(),
        "cell_volume_angstrom3": float(abs(np.linalg.det(cell))),
        "spacegroup_symbol": symmetry.international,
        "spacegroup_number": int(symmetry.number),
        "symmetry_tolerance_angstrom": 1e-6,
    }
    result["pass"] = bool(
        strict["healthy"]
        and clean_process
        and exact_geometry
        and strict["max_abs_force_ry_bohr"] <= 5e-5
        and symmetry.international == "Ibam"
        and int(symmetry.number) == 72
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

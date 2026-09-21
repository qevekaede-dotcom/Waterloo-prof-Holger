#!/usr/bin/env python3
"""Exact rational q/supercell commensurability checks.

This module checks only lattice arithmetic. It does not read structures, map
atoms or eigenvectors, generate displacements, fit force constants, or decide
whether a physical calculation is scientifically acceptable.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import re
from typing import Any, Sequence


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_FRACTION_RE = re.compile(r"^[+-]?\d+/[+-]?\d+$")
_DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)$")


def parse_exact_rational(value: str | int) -> tuple[Fraction, dict[str, str]]:
    """Parse an integer, explicit fraction, or finite decimal exactly.

    Binary floats are rejected because their provenance and intended decimal
    spelling have already been lost by the time this function receives them.
    """

    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(
            "q components must be strings or integers; binary floats are not accepted"
        )
    if isinstance(value, int):
        token = str(value)
        kind = "integer"
    elif isinstance(value, str):
        token = value.strip()
        if _INTEGER_RE.fullmatch(token):
            kind = "integer"
        elif _FRACTION_RE.fullmatch(token):
            kind = "explicit_fraction"
        elif _DECIMAL_RE.fullmatch(token):
            kind = "exact_finite_decimal"
        else:
            raise ValueError(
                f"invalid exact rational {value!r}; use an integer, a/b, or a finite decimal"
            )
    else:
        raise ValueError(
            "q components must be strings or integers; use an explicit exact spelling"
        )

    try:
        exact = Fraction(token)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid exact rational {value!r}: {exc}") from exc
    return exact, {
        "input": token,
        "kind": kind,
        "exact_fraction": fraction_text(exact),
    }


def fraction_text(value: Fraction) -> str:
    """Return a stable integer-or-fraction representation."""

    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _validate_matrix(matrix: Sequence[Sequence[int]]) -> list[list[int]]:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValueError("supercell matrix must be a 3x3 nested sequence")
    result: list[list[int]] = []
    for row in matrix:
        checked_row: list[int] = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("every supercell matrix entry must be an integer")
            checked_row.append(value)
        result.append(checked_row)
    if determinant_3x3(result) == 0:
        raise ValueError("supercell matrix must be nonsingular (determinant != 0)")
    return result


def determinant_3x3(matrix: Sequence[Sequence[int]]) -> int:
    """Compute an exact determinant for a 3x3 integer matrix."""

    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def analyze_commensurability(
    q: Sequence[str | int],
    matrix: Sequence[Sequence[int]],
    *,
    purpose: str = "frozen-mode",
    reference_atoms: int | None = None,
    reference_basis_verified: bool = False,
    atom_mapping_verified: bool = False,
    eigenvector_mapping_verified: bool = False,
) -> dict[str, Any]:
    """Return an exact, JSON-serializable commensurability report.

    Convention: reference direct-basis vectors are columns of A, serialized S
    is displayed row by row, and the supercell basis is A_s = A S. Therefore
    the three supercell generators are the columns of S. q must be reduced in
    the reciprocal basis dual to A, and periodicity requires S^T q to be an
    integer vector.
    """

    if len(q) != 3:
        raise ValueError("q must contain exactly three reduced components")
    parsed = [parse_exact_rational(value) for value in q]
    q_exact = [item[0] for item in parsed]
    q_interpretations = [item[1] for item in parsed]
    checked_matrix = _validate_matrix(matrix)
    if purpose not in {"frozen-mode", "ifc-interpolation"}:
        raise ValueError("purpose must be 'frozen-mode' or 'ifc-interpolation'")
    if reference_atoms is not None:
        if isinstance(reference_atoms, bool) or not isinstance(reference_atoms, int):
            raise ValueError("reference_atoms must be a positive integer")
        if reference_atoms <= 0:
            raise ValueError("reference_atoms must be a positive integer")

    determinant = determinant_3x3(checked_matrix)
    multiplier = abs(determinant)
    generators = [
        [checked_matrix[row][column] for row in range(3)]
        for column in range(3)
    ]
    q_dot_t = [
        sum((q_exact[row] * checked_matrix[row][column] for row in range(3)), Fraction())
        for column in range(3)
    ]
    integer_flags = [value.denominator == 1 for value in q_dot_t]
    compatible = all(integer_flags)
    atom_candidate = reference_atoms * multiplier if reference_atoms is not None else None
    basis_and_mappings_verified = (
        reference_basis_verified and atom_mapping_verified and eigenvector_mapping_verified
    )

    if purpose == "frozen-mode":
        criterion_role = (
            "required: every supercell translation must preserve the mode phase"
        )
    else:
        criterion_role = (
            "informational only: an IFC interpolation supercell tests real-space "
            "interaction range and need not contain this q wave as a frozen mode"
        )

    return {
        "schema_version": 1,
        "scope": {
            "calculation": "exact lattice commensurability only",
            "scientific_acceptance": False,
            "displacement_generation": False,
            "force_constants": False,
            "eigenvector_construction": False,
        },
        "convention": {
            "direct_basis": "columns of A",
            "serialized_matrix_layout": "three displayed rows; columns are supercell generators",
            "supercell_relation": "A_super = A_reference * S",
            "q_basis": "reduced coordinates in the reciprocal basis dual to A_reference",
            "phase": "exp(2*pi*i*q_dot_T)",
            "criterion": "transpose(S) * q is integer componentwise",
        },
        "input": {
            "q": q_interpretations,
            "q_exact": [fraction_text(value) for value in q_exact],
            "supercell_matrix_S": checked_matrix,
            "purpose": purpose,
            "reference_atoms": reference_atoms,
        },
        "geometry": {
            "determinant": determinant,
            "atom_multiplier_abs_determinant": multiplier,
            "integer_nonsingular_supercell_geometry": True,
            "supercell_generator_T_columns": generators,
            "conditional_atom_count": {
                "value": atom_candidate,
                "conditions": [
                    "reference_atoms is the atom count of A_reference",
                    "S is applied to that same verified direct basis",
                ],
                "reference_basis_verified": reference_basis_verified,
                "applicable_to_reported_physical_basis": bool(
                    atom_candidate is not None and reference_basis_verified
                ),
            },
        },
        "mathematical_result": {
            "q_dot_T_exact": [fraction_text(value) for value in q_dot_t],
            "q_dot_T_is_integer": integer_flags,
            "q_dot_T_integer_values": [
                value.numerator if value.denominator == 1 else None for value in q_dot_t
            ],
            "commensurate": compatible,
        },
        "purpose_interpretation": {
            "q_commensurability_is_required": purpose == "frozen-mode",
            "criterion_role": criterion_role,
            "matrix_rejected_for_ifc_size_testing_by_this_checker": False,
        },
        "physical_verification": {
            "reference_direct_and_reciprocal_basis_verified": reference_basis_verified,
            "atom_mapping_verified": atom_mapping_verified,
            "eigenvector_mapping_verified": eigenvector_mapping_verified,
            "basis_and_mappings_verified": basis_and_mappings_verified,
            "frozen_mode_preconditions_reported_complete": bool(
                purpose == "frozen-mode" and compatible and basis_and_mappings_verified
            ),
            "scientific_acceptance": False,
            "note": (
                "Verification flags are caller assertions, not findings of this tool. "
                "Even all-true flags plus commensurability do not validate a mode, "
                "structure, displacement amplitude, force settings, or physical stability."
            ),
        },
    }


def _positive_integer(token: str) -> int:
    try:
        value = int(token)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check exact q/supercell lattice commensurability and emit JSON."
    )
    parser.add_argument(
        "--q",
        nargs=3,
        required=True,
        metavar=("Q1", "Q2", "Q3"),
        help="reduced q components as integers, explicit fractions, or finite decimals",
    )
    parser.add_argument(
        "--matrix",
        nargs=9,
        required=True,
        type=int,
        metavar=("S11", "S12", "S13", "S21", "S22", "S23", "S31", "S32", "S33"),
        help="3x3 integer matrix serialized row by row; its columns are supercell generators",
    )
    parser.add_argument(
        "--purpose",
        choices=("frozen-mode", "ifc-interpolation"),
        default="frozen-mode",
    )
    parser.add_argument("--reference-atoms", type=_positive_integer)
    parser.add_argument("--reference-basis-verified", action="store_true")
    parser.add_argument("--atom-mapping-verified", action="store_true")
    parser.add_argument("--eigenvector-mapping-verified", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    matrix = [args.matrix[0:3], args.matrix[3:6], args.matrix[6:9]]
    try:
        report = analyze_commensurability(
            args.q,
            matrix,
            purpose=args.purpose,
            reference_atoms=args.reference_atoms,
            reference_basis_verified=args.reference_basis_verified,
            atom_mapping_verified=args.atom_mapping_verified,
            eigenvector_mapping_verified=args.eigenvector_mapping_verified,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

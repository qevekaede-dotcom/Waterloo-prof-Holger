#!/usr/bin/env python3
"""Regenerate the checked SrZrS3 lattice-arithmetic examples."""

from __future__ import annotations

from pathlib import Path
import json

from q_commensurability import analyze_commensurability


HERE = Path(__file__).resolve().parent
Q = ["0", "2/5", "0"]


def main() -> None:
    cases = {
        "scope_note": (
            "These are exact geometry checks, not evidence that the archived q basis, "
            "atom mapping, or eigenvector mapping has been verified, and not scientific acceptance."
        ),
        "archived_basis_status": "unknown; all example verification flags remain false",
        "cases": {
            "diagonal_1x5x1_frozen_mode_candidate": analyze_commensurability(
                Q,
                [[1, 0, 0], [0, 5, 0], [0, 0, 1]],
                purpose="frozen-mode",
                reference_atoms=20,
            ),
            "existing_2x1x1_ifc_test": analyze_commensurability(
                Q,
                [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
                purpose="ifc-interpolation",
                reference_atoms=20,
            ),
            "proposed_3x2x1_ifc_test": analyze_commensurability(
                Q,
                [[3, 0, 0], [0, 2, 0], [0, 0, 1]],
                purpose="ifc-interpolation",
                reference_atoms=20,
            ),
            "proposed_5x2x1_ifc_test": analyze_commensurability(
                Q,
                [[5, 0, 0], [0, 2, 0], [0, 0, 1]],
                purpose="ifc-interpolation",
                reference_atoms=20,
            ),
            "non_diagonal_commensurate_geometry": analyze_commensurability(
                Q,
                [[1, 1, 0], [0, 5, 0], [0, 0, 1]],
                purpose="frozen-mode",
                reference_atoms=20,
            ),
        },
    }
    output = HERE / "examples" / "srzrs3_cases.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

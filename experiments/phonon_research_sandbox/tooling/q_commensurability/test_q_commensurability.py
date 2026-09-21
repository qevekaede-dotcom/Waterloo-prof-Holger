#!/usr/bin/env python3
"""Focused regression tests for q_commensurability.py."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from q_commensurability import analyze_commensurability, parse_exact_rational  # noqa: E402


Q = ["0", "2/5", "0"]


class CommensurabilityTests(unittest.TestCase):
    def test_1x5x1_is_commensurate_and_conditionally_100_atoms(self) -> None:
        report = analyze_commensurability(
            Q,
            [[1, 0, 0], [0, 5, 0], [0, 0, 1]],
            reference_atoms=20,
            reference_basis_verified=True,
        )
        self.assertEqual(report["mathematical_result"]["q_dot_T_exact"], ["0", "2", "0"])
        self.assertTrue(report["mathematical_result"]["commensurate"])
        self.assertEqual(report["geometry"]["atom_multiplier_abs_determinant"], 5)
        conditional = report["geometry"]["conditional_atom_count"]
        self.assertEqual(conditional["value"], 100)
        self.assertTrue(conditional["applicable_to_reported_physical_basis"])

    def test_archived_basis_unknown_keeps_100_atom_candidate_inapplicable(self) -> None:
        report = analyze_commensurability(
            Q,
            [[1, 0, 0], [0, 5, 0], [0, 0, 1]],
            reference_atoms=20,
        )
        conditional = report["geometry"]["conditional_atom_count"]
        self.assertEqual(conditional["value"], 100)
        self.assertFalse(conditional["reference_basis_verified"])
        self.assertFalse(conditional["applicable_to_reported_physical_basis"])
        self.assertFalse(
            report["physical_verification"]["frozen_mode_preconditions_reported_complete"]
        )

    def test_existing_2x1x1_is_incompatible_for_frozen_q(self) -> None:
        report = analyze_commensurability(Q, [[2, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(report["mathematical_result"]["q_dot_T_exact"], ["0", "2/5", "0"])
        self.assertFalse(report["mathematical_result"]["commensurate"])

    def test_3x2x1_and_5x2x1_are_ifc_geometries_not_frozen_q_cells(self) -> None:
        for first_repeat in (3, 5):
            with self.subTest(first_repeat=first_repeat):
                report = analyze_commensurability(
                    Q,
                    [[first_repeat, 0, 0], [0, 2, 0], [0, 0, 1]],
                    purpose="ifc-interpolation",
                )
                self.assertFalse(report["mathematical_result"]["commensurate"])
                self.assertFalse(
                    report["purpose_interpretation"]["q_commensurability_is_required"]
                )
                self.assertTrue(report["geometry"]["integer_nonsingular_supercell_geometry"])
                self.assertFalse(
                    report["purpose_interpretation"][
                        "matrix_rejected_for_ifc_size_testing_by_this_checker"
                    ]
                )

    def test_non_diagonal_column_generator_convention(self) -> None:
        report = analyze_commensurability(Q, [[1, 1, 0], [0, 5, 0], [0, 0, 1]])
        self.assertEqual(
            report["geometry"]["supercell_generator_T_columns"],
            [[1, 0, 0], [1, 5, 0], [0, 0, 1]],
        )
        self.assertEqual(report["mathematical_result"]["q_dot_T_exact"], ["0", "2", "0"])
        self.assertTrue(report["mathematical_result"]["commensurate"])
        transposed = analyze_commensurability(Q, [[1, 0, 0], [1, 5, 0], [0, 0, 1]])
        self.assertEqual(
            transposed["mathematical_result"]["q_dot_T_exact"], ["2/5", "2", "0"]
        )
        self.assertFalse(transposed["mathematical_result"]["commensurate"])

    def test_negative_determinant_uses_absolute_atom_multiplier(self) -> None:
        report = analyze_commensurability(Q, [[1, 0, 0], [0, 5, 0], [0, 0, -1]])
        self.assertEqual(report["geometry"]["determinant"], -5)
        self.assertEqual(report["geometry"]["atom_multiplier_abs_determinant"], 5)
        self.assertTrue(report["mathematical_result"]["commensurate"])

    def test_decimal_is_reported_as_exact_rational(self) -> None:
        exact, interpretation = parse_exact_rational("0.4")
        self.assertEqual(str(exact), "2/5")
        self.assertEqual(interpretation["kind"], "exact_finite_decimal")
        self.assertEqual(interpretation["exact_fraction"], "2/5")

    def test_binary_float_and_singular_matrix_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "binary floats"):
            analyze_commensurability([0, 0.4, 0], [[1, 0, 0], [0, 5, 0], [0, 0, 1]])
        with self.assertRaisesRegex(ValueError, "nonsingular"):
            analyze_commensurability(Q, [[1, 0, 0], [0, 0, 0], [0, 0, 1]])

    def test_cli_json_never_claims_scientific_acceptance(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(HERE / "q_commensurability.py"),
                "--q",
                "0",
                "0.4",
                "0",
                "--matrix",
                "1",
                "0",
                "0",
                "0",
                "5",
                "0",
                "0",
                "0",
                "1",
                "--reference-atoms",
                "20",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(report["input"]["q_exact"], ["0", "2/5", "0"])
        self.assertFalse(report["scope"]["scientific_acceptance"])
        self.assertFalse(report["physical_verification"]["scientific_acceptance"])


if __name__ == "__main__":
    unittest.main()

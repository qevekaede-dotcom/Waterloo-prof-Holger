"""Pure convergence-policy tests; no HDF5, phono3py or QE execution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[4]
SRCU_SCRIPTS = REPO / "thermo_candidates/SrCu2SnS4/phono3py/scripts"
SHARED = REPO / "thermo_candidates/scripts/phono3py_campaign"
sys.path[:0] = [str(SHARED), str(SRCU_SCRIPTS)]

import postprocess
from postprocess import LegacyGateError, qmesh_step_passes, select_converged_qmesh


TEMPERATURES = list(range(300, 901, 100))


def tensor_rows(scale: float = 1.0) -> list[list[float]]:
    return [[scale * (1.0 + row), scale * (1.2 + row), scale * (1.4 + row)]
            for row in range(len(TEMPERATURES))]


class SrCuQMeshPolicyTests(unittest.TestCase):
    def test_legacy_script_stops_even_if_a_future_dataset_passes_the_data_gate(self) -> None:
        with patch("postprocess.audit_legacy_evidence", return_value={"healthy": True}):
            with self.assertRaises(SystemExit) as raised:
                postprocess.main()
        self.assertIn("legacy FC/kappa execution is retired", str(raised.exception))

    def test_selects_only_after_two_full_tensor_steps_pass(self) -> None:
        first = tensor_rows()
        second = tensor_rows(1.04)
        third = tensor_rows(1.04 * 1.04)
        self.assertTrue(qmesh_step_passes(TEMPERATURES, first, TEMPERATURES, second))
        self.assertEqual(
            select_converged_qmesh([
                ((7, 7, 3), TEMPERATURES, first),
                ((9, 9, 4), TEMPERATURES, second),
                ((11, 11, 5), TEMPERATURES, third),
            ]),
            (11, 11, 5),
        )

    def test_rejects_one_bad_temperature_component_and_never_defaults_to_largest(self) -> None:
        first = tensor_rows()
        second = tensor_rows(1.04)
        second[-1][2] = first[-1][2] * 1.06
        third = tensor_rows(1.04 * 1.04)
        self.assertFalse(qmesh_step_passes(TEMPERATURES, first, TEMPERATURES, second))
        self.assertIsNone(select_converged_qmesh([
            ((7, 7, 3), TEMPERATURES, first),
            ((9, 9, 4), TEMPERATURES, second),
            ((11, 11, 5), TEMPERATURES, third),
        ]))

    def test_final_refinement_failure_invalidates_earlier_two_step_pass(self) -> None:
        ladder = [tensor_rows(scale) for scale in (1.00, 1.01, 1.02, 1.20)]
        self.assertIsNone(select_converged_qmesh([
            ((7, 7, 3), TEMPERATURES, ladder[0]),
            ((9, 9, 4), TEMPERATURES, ladder[1]),
            ((11, 11, 5), TEMPERATURES, ladder[2]),
            ((13, 13, 6), TEMPERATURES, ladder[3]),
        ]))

    def test_requires_exact_full_temperature_grid_and_nonzero_reference(self) -> None:
        with self.assertRaisesRegex(LegacyGateError, "300--900 K"):
            qmesh_step_passes(TEMPERATURES[:-1], tensor_rows()[:-1], TEMPERATURES,
                              tensor_rows())
        zero_reference = tensor_rows()
        zero_reference[0][0] = 0.0
        self.assertFalse(qmesh_step_passes(TEMPERATURES, zero_reference,
                                           TEMPERATURES, tensor_rows()))
        self.assertTrue(qmesh_step_passes(TEMPERATURES, tensor_rows(), TEMPERATURES,
                                          tensor_rows(1.05)))
        self.assertFalse(qmesh_step_passes(TEMPERATURES, tensor_rows(), TEMPERATURES,
                                           tensor_rows(0.95)))


if __name__ == "__main__":
    unittest.main()

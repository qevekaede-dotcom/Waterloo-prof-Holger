"""Read-only regression gates for the preserved SrCu2SnS4 phonon evidence."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
SHARED = REPO / "thermo_candidates/scripts/phono3py_campaign"
SRCU_SCRIPTS = REPO / "thermo_candidates/SrCu2SnS4/phono3py/scripts"
sys.path[:0] = [str(SHARED), str(SRCU_SCRIPTS)]

from postprocess import (
    LegacyGateError,
    _legacy_force_paths,
    audit_legacy_evidence,
    legacy_cutoff_inventory,
)
from qe_output import inspect_force_run, parse_last_force_block


PHONO = REPO / "thermo_candidates/SrCu2SnS4/phono3py"


class SrCuLegacyGateTests(unittest.TestCase):
    def test_pristine_force_is_parseable_but_terminally_unhealthy(self) -> None:
        pristine = PHONO / "checks/pristine"
        self.assertEqual(
            len(parse_last_force_block(pristine / "scf.out", 96).forces_ry_bohr), 96
        )
        report = inspect_force_run(pristine / "scf.out", pristine / "scf.err", 96)
        self.assertFalse(report["healthy"])
        self.assertIn("failure signature: MPI_ABORT", report["errors"])

    def test_historical_inventory_fails_closed_after_auditing_all_runs(self) -> None:
        displaced = _legacy_force_paths(PHONO)[1:]
        terminally_unhealthy = [
            label
            for label, output, stderr, _ in displaced
            if not inspect_force_run(output, stderr, 96)["healthy"]
        ]
        self.assertEqual(len(displaced), 168)
        self.assertEqual(len(terminally_unhealthy), 14)
        with self.assertRaisesRegex(LegacyGateError, "pristine terminal state.*MPI_ABORT") as raised:
            audit_legacy_evidence(PHONO)
        self.assertIn("cutoff_pair_distance must be 4.0 A", str(raised.exception))

    def test_historical_cutoff_is_not_a_corrected_four_angstrom_cutoff(self) -> None:
        inventory = legacy_cutoff_inventory(PHONO / "phono3py_disp.yaml")
        self.assertEqual(inventory["length_unit"], "au")
        self.assertEqual(inventory["cutoff_pair_distance_bohr"], 4.0)
        self.assertEqual(inventory["included_pair_groups"], 24)
        self.assertEqual(inventory["nonzero_included_pair_groups"], 0)
        self.assertAlmostEqual(inventory["shortest_nonzero_pair_distance_bohr"], 4.33833022)


if __name__ == "__main__":
    unittest.main()

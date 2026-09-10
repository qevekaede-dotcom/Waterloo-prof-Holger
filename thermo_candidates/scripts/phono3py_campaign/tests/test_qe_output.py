from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qe_output import QEOutputError, inspect_output, parse_last_force_block


def qe_run(
    forces: list[tuple[float, float, float]],
    *,
    done: bool = True,
    converged: bool = True,
    contributions: bool = False,
) -> str:
    lines = ["Program PWSCF v.7.3.1 starts on 10Sep2026"]
    lines.append(
        "convergence has been achieved in 10 iterations"
        if converged
        else "convergence NOT achieved after 200 iterations"
    )
    lines.extend(["Forces acting on atoms (cartesian axes, Ry/au):", ""])
    for index, force in enumerate(forces, 1):
        lines.append(
            f"atom {index:4d} type  1   force = "
            f"{force[0]: .8f} {force[1]: .8f} {force[2]: .8f}"
        )
    if contributions:
        lines.append("The non-local contrib.  to forces")
        for index in range(1, len(forces) + 1):
            lines.append(
                f"atom {index:4d} type  1   force =  9.0  9.0  9.0"
            )
    lines.extend(["Total force = 0.001 Total SCF correction = 0.000002"])
    if done:
        lines.append("JOB DONE.")
    return "\n".join(lines) + "\n"


class QEOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "scf.out"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_uses_main_force_not_verbose_contribution(self) -> None:
        self.path.write_text(qe_run([(1e-4, -2e-4, 3e-4)], contributions=True))
        record = parse_last_force_block(self.path, expected_atoms=1)
        self.assertEqual(record.forces_ry_bohr, ((1e-4, -2e-4, 3e-4),))
        self.assertTrue(inspect_output(self.path, 1)["healthy"])

    def test_uses_only_last_pwscf_run(self) -> None:
        self.path.write_text(
            qe_run([(9e-4, 0.0, 0.0)]) + qe_run([(2e-4, 0.0, 0.0)])
        )
        self.assertEqual(
            parse_last_force_block(self.path, expected_atoms=1).max_abs_ry_bohr,
            2e-4,
        )

    def test_rejects_nonconverged_or_unfinished_run(self) -> None:
        self.path.write_text(qe_run([(1e-4, 0.0, 0.0)], converged=False, done=False))
        report = inspect_output(self.path, 1)
        self.assertFalse(report["healthy"])
        self.assertIn("missing JOB DONE", report["errors"])
        self.assertIn("missing SCF convergence marker", report["errors"])

    def test_rejects_incomplete_later_force_block(self) -> None:
        self.path.write_text(
            qe_run([(1e-4, 0.0, 0.0)])
            + "Forces acting on atoms (cartesian axes, Ry/au):\n"
            + "atom 1 type 1 force = 0.0 0.0 0.0\n"
        )
        report = inspect_output(self.path, 1)
        self.assertFalse(report["healthy"])
        self.assertIn("incomplete force block follows the selected block", report["errors"])

    def test_rejects_later_nonconverged_scf_after_complete_forces(self) -> None:
        text = qe_run([(1e-4, 0.0, 0.0)]).replace("JOB DONE.\n", "")
        text += "convergence NOT achieved after 300 iterations\nJOB DONE.\n"
        self.path.write_text(text)
        report = inspect_output(self.path, 1)
        self.assertFalse(report["healthy"])
        self.assertIn(
            "non-converged SCF follows the selected force block", report["errors"]
        )

    def test_rejects_wrong_atom_count(self) -> None:
        self.path.write_text(qe_run([(1e-4, 0.0, 0.0)]))
        with self.assertRaises(QEOutputError):
            parse_last_force_block(self.path, expected_atoms=2)


if __name__ == "__main__":
    unittest.main()

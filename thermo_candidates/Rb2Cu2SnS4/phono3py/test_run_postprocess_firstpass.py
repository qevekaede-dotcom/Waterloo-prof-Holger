#!/usr/bin/env python3
"""Focused regressions for Rb first-pass postprocess validation/finalization."""

from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_postprocess_firstpass as postprocess


class ForceConstantScannerTests(unittest.TestCase):
    def write_hdf5(self, path: Path, datasets: dict[str, object]) -> None:
        with h5py.File(path, "w") as handle:
            for name, values in datasets.items():
                handle.create_dataset(name, data=values)

    def test_fc2_and_fc3_use_their_documented_distinct_dataset_names(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fc2 = root / "fc2.hdf5"
            fc3 = root / "fc3.hdf5"
            mapping = np.array([0], dtype=np.int64)
            self.write_hdf5(
                fc2,
                {
                    "force_constants": np.zeros((2, 2, 3, 3)),
                    "p2s_map": mapping,
                },
            )
            self.write_hdf5(
                fc3,
                {
                    "fc3": np.zeros((2, 2, 2, 3, 3, 3)),
                    "p2s_map": mapping,
                    "version": np.bytes_("4.4.0"),
                },
            )

            report2 = postprocess.scan_force_constants(fc2, order=2, expected_atoms=2)
            report3 = postprocess.scan_force_constants(fc3, order=3, expected_atoms=2)

        self.assertEqual(report2["dataset"], "force_constants")
        self.assertEqual(report2["shape"], [2, 2, 3, 3])
        self.assertEqual(report3["dataset"], "fc3")
        self.assertEqual(report3["shape"], [2, 2, 2, 3, 3, 3])
        self.assertIsNone(report2["hdf5_embedded_version"])
        self.assertEqual(report3["hdf5_embedded_version"], "4.4.0")

    def test_scanner_requires_matching_nonempty_p2s_maps(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing-map-fc2.hdf5"
            empty = root / "empty-map-fc2.hdf5"
            fc2 = root / "fc2.hdf5"
            fc3 = root / "fc3.hdf5"
            self.write_hdf5(missing, {"force_constants": np.zeros((2, 2, 3, 3))})
            self.write_hdf5(
                empty,
                {
                    "force_constants": np.zeros((2, 2, 3, 3)),
                    "p2s_map": np.array([], dtype=np.int64),
                },
            )
            self.write_hdf5(
                fc2,
                {
                    "force_constants": np.zeros((2, 2, 3, 3)),
                    "p2s_map": np.array([0], dtype=np.int64),
                },
            )
            self.write_hdf5(
                fc3,
                {
                    "fc3": np.zeros((2, 2, 2, 3, 3, 3)),
                    "p2s_map": np.array([1], dtype=np.int64),
                },
            )

            with self.assertRaisesRegex(ValueError, "lacks required p2s_map"):
                postprocess.scan_force_constants(missing, order=2, expected_atoms=2)
            with self.assertRaisesRegex(ValueError, "invalid or empty p2s_map"):
                postprocess.scan_force_constants(empty, order=2, expected_atoms=2)
            with self.assertRaisesRegex(ValueError, "p2s_map datasets differ"):
                postprocess.scan_force_constant_pair(fc2, fc3, expected_atoms=2)

    def test_scanner_rejects_wrong_ambiguous_or_nonfinite_schema(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            wrong = root / "wrong.hdf5"
            ambiguous = root / "ambiguous.hdf5"
            nonfinite = root / "nonfinite.hdf5"
            self.write_hdf5(wrong, {"force_constants": np.zeros((2, 2, 2, 3, 3, 3))})
            self.write_hdf5(
                ambiguous,
                {
                    "force_constants": np.zeros((2, 2, 3, 3)),
                    "fc3": np.zeros((2, 2, 2, 3, 3, 3)),
                },
            )
            values = np.zeros((2, 2, 3, 3))
            values[1, 1, 2, 2] = np.nan
            self.write_hdf5(
                nonfinite,
                {
                    "force_constants": values,
                    "p2s_map": np.array([0], dtype=np.int64),
                },
            )

            with self.assertRaisesRegex(ValueError, "documented FC3 dataset 'fc3'"):
                postprocess.scan_force_constants(wrong, order=3, expected_atoms=2)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                postprocess.scan_force_constants(ambiguous, order=2, expected_atoms=2)
            with self.assertRaisesRegex(ValueError, "non-finite"):
                postprocess.scan_force_constants(nonfinite, order=2, expected_atoms=2)


class ExistingFinalizationTests(unittest.TestCase):
    def write_command_evidence(
        self, root: Path, name: str, command: list[str], *, exit_code: str = "0\n"
    ) -> None:
        (root / f"{name}.command.json").write_text(json.dumps(command))
        (root / f"{name}.exit_code.txt").write_text(exit_code)
        (root / f"{name}.stdout").write_text("completed\n")
        (root / f"{name}.stderr").write_text("")

    def test_command_evidence_requires_exact_command_and_zero_exit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            command = postprocess.expected_qmesh_command(0, 45.0)
            self.write_command_evidence(root, "stage", command)
            report = postprocess.validate_command_evidence(root, "stage", command)
            self.assertEqual(report["command"], command)

            (root / "stage.command.json").write_text(json.dumps(command + ["--unexpected"]))
            with self.assertRaisesRegex(ValueError, "command mismatch"):
                postprocess.validate_command_evidence(root, "stage", command)
            (root / "stage.command.json").write_text(json.dumps(command))
            (root / "stage.exit_code.txt").write_text("1\n")
            with self.assertRaisesRegex(ValueError, "successful exit"):
                postprocess.validate_command_evidence(root, "stage", command)

    def test_saved_90_to_105_angstrom_stdout_values_fail_the_mesh_gate(self) -> None:
        previous = {
            "conventional_kappa_W_mK": [
                [0.143, 0.139, 0.122, 0.0, 0.0, 0.0],
                [0.073, 0.073, 0.065, 0.0, 0.0, 0.0],
                [0.049, 0.049, 0.043, 0.0, 0.0, 0.0],
            ]
        }
        current = {
            "conventional_kappa_W_mK": [
                [0.147, 0.139, 0.136, 0.0, 0.0, 0.0],
                [0.075, 0.073, 0.071, 0.0, 0.0, 0.0],
                [0.050, 0.049, 0.048, 0.0, 0.0, 0.0],
            ]
        }
        result = postprocess.convergence(previous, current)
        self.assertFalse(result["passed"])
        self.assertGreater(
            result["temperature_changes"][0]["trace_over_3_relative_change"], 0.03
        )
        self.assertGreater(
            max(result["temperature_changes"][0]["diagonal_relative_changes"]), 0.05
        )

    def test_workflow_gate_has_distinct_fail_closed_exit_bits(self) -> None:
        qmesh = postprocess.evaluate_workflow_gate(
            qmesh_converged=False,
            harmonic_stability_pass=True,
            offdiagonal_check_pass=True,
        )
        harmonic = postprocess.evaluate_workflow_gate(
            qmesh_converged=True,
            harmonic_stability_pass=False,
            offdiagonal_check_pass=True,
        )
        offdiagonal = postprocess.evaluate_workflow_gate(
            qmesh_converged=True,
            harmonic_stability_pass=True,
            offdiagonal_check_pass=False,
        )
        combined = postprocess.evaluate_workflow_gate(
            qmesh_converged=False,
            harmonic_stability_pass=False,
            offdiagonal_check_pass=False,
        )
        self.assertEqual(qmesh["exit_code"], 1)
        self.assertEqual(harmonic["exit_code"], 2)
        self.assertEqual(offdiagonal["exit_code"], 4)
        self.assertEqual(combined["exit_code"], 7)
        self.assertFalse(qmesh["pass"])
        self.assertEqual(
            harmonic["failed_gates"], ["harmonic_stability_pass"]
        )

    def test_loaded_supercell_atom_count_must_match_manifest(self) -> None:
        p3 = SimpleNamespace(supercell=[object(), object()])
        self.assertEqual(postprocess.validate_supercell_atom_count(p3, 2), 2)
        with self.assertRaisesRegex(ValueError, "force manifest expects 3"):
            postprocess.validate_supercell_atom_count(p3, 3)

    def test_qmesh_discovery_rejects_noncontiguous_or_unknown_stages(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qmesh_00_45A.command.json").write_text("[]")
            (root / "qmesh_02_75A.command.json").write_text("[]")
            with self.assertRaisesRegex(ValueError, "contiguous"):
                postprocess.discover_qmesh_stage_count(root)

            (root / "qmesh_02_75A.command.json").unlink()
            (root / "qmesh_forged.command.json").write_text("[]")
            with self.assertRaisesRegex(ValueError, "unexpected or ambiguous"):
                postprocess.discover_qmesh_stage_count(root)

    def test_missing_summary_is_created_but_different_existing_summary_is_never_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            postprocess.write_missing_or_verify(path, b"trusted\n")
            postprocess.write_missing_or_verify(path, b"trusted\n")
            self.assertEqual(path.read_bytes(), b"trusted\n")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                postprocess.write_missing_or_verify(path, b"different\n")

    def test_finalize_existing_cli_never_calls_calculation_runner(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production"
            dataset = root / "dataset"
            output = root / "postprocess"
            production.mkdir()
            dataset.mkdir()
            output.mkdir()
            (production / "production_audit.json").write_text('{"pass": true}\n')
            (production / "force_manifest.json").write_text(
                '{"tasks": [{"input": "/run/pristine/scf.in"}, '
                '{"input": "/run/disp/scf.in"}]}\n'
            )
            (dataset / "phono3py_disp.yaml").write_text("dataset\n")
            argv = [
                "run_postprocess_firstpass.py",
                "--production-dir", str(production),
                "--dataset-dir", str(dataset),
                "--output-dir", str(output),
                "--finalize-existing",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(postprocess, "run", side_effect=AssertionError("calculation ran")),
                patch.object(postprocess, "finalize_existing", return_value=0) as finalize,
            ):
                self.assertEqual(postprocess.main(), 0)
            finalize.assert_called_once()

    def test_complete_five_stage_evidence_finalizes_without_claiming_qmesh_convergence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production"
            dataset_dir = root / "dataset"
            output = root / "postprocess"
            production.mkdir()
            dataset_dir.mkdir()
            output.mkdir()
            audit = {"pass": True}
            manifest = {
                "tasks": [
                    {
                        "input": str(root / "production/task-00000-pristine/scf.in"),
                        "expected_atoms": 2,
                        "kmesh": [2, 2, 2],
                    },
                    {"input": str(root / "production/task-00001-disp/scf.in")},
                ]
            }
            (production / "production_audit.json").write_text(json.dumps(audit))
            (production / "force_manifest.json").write_text(json.dumps(manifest))
            (production / "task_map.tsv").write_text("task_id\n0\n1\n")
            (dataset_dir / "phono3py_disp.yaml").write_text("dataset\n")
            (output / "phono3py_disp.yaml").write_text("dataset\n")
            (output / "FORCES_FC3").write_text("forces\n")
            (output / "phono3py.yaml").write_text("summary\n")
            with h5py.File(output / "fc2.hdf5", "w") as handle:
                handle.create_dataset("force_constants", data=np.zeros((2, 2, 3, 3)))
                handle.create_dataset("p2s_map", data=np.array([0], dtype=np.int64))
            with h5py.File(output / "fc3.hdf5", "w") as handle:
                handle.create_dataset("fc3", data=np.zeros((2, 2, 2, 3, 3, 3)))
                handle.create_dataset("p2s_map", data=np.array([0], dtype=np.int64))
            self.write_command_evidence(
                output,
                "collect_forces_fc3",
                postprocess.expected_collect_command(manifest),
            )

            mesh_by_length = {
                length: (index + 2, index + 3, index + 4)
                for index, length in enumerate(postprocess.LENGTH_LADDER_ANGSTROM)
            }
            report_by_length = {}
            for index, length in enumerate(postprocess.LENGTH_LADDER_ANGSTROM):
                name = f"qmesh_{index:02d}_{length:g}A"
                kappa = output / f"kappa-m{index}.hdf5"
                with h5py.File(kappa, "w") as handle:
                    handle.create_dataset("mesh", data=mesh_by_length[length])
                self.write_command_evidence(
                    output, name, postprocess.expected_qmesh_command(index, length)
                )
                (output / f"{name}.stdout").write_text(f'written into "{kappa.name}"\n')
                diagonal = float(index + 1)
                report_by_length[length] = {
                    "mesh_length_angstrom": length,
                    "hdf5": str(kappa.resolve()),
                    "minimum_frequency_THz": 0.1,
                    "maximum_offdiagonal_fraction_of_trace_over_3": 0.0,
                    "conventional_kappa_W_mK": [
                        [diagonal, diagonal, diagonal, 0.0, 0.0, 0.0]
                        for _ in postprocess.TEMPERATURES_K
                    ],
                }

            class FakeGrid:
                def __init__(self, length, **_kwargs):
                    self.D_diag = np.asarray(mesh_by_length[length])

            fake_p3 = SimpleNamespace(
                primitive=SimpleNamespace(cell=np.eye(3)),
                primitive_symmetry=SimpleNamespace(dataset={}),
                supercell=[object(), object()],
            )
            with (
                patch.object(postprocess.phono3py, "load", return_value=fake_p3),
                patch.object(postprocess, "BZGrid", FakeGrid),
                patch.object(
                    postprocess,
                    "hdf_report",
                    side_effect=lambda _path, length, _p3: dict(report_by_length[length]),
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(
                    postprocess.finalize_existing(
                        production, dataset_dir, output, audit, manifest
                    ),
                    1,
                )
                # An identical finalize is idempotent and verifies rather than overwrites.
                self.assertEqual(
                    postprocess.finalize_existing(
                        production, dataset_dir, output, audit, manifest
                    ),
                    1,
                )

            summary = json.loads((output / "kappa_summary.json").read_text())
            self.assertFalse(summary["qmesh_converged"])
            self.assertFalse(summary["first_pass_workflow_gate"]["pass"])
            self.assertEqual(summary["first_pass_workflow_gate"]["exit_code"], 1)
            self.assertEqual(summary["selected_tensor_status"], "rejected_diagnostic_only")
            self.assertEqual(
                summary["csv_output"],
                "kappa_L_first_pass_rejected_diagnostic.csv",
            )
            self.assertFalse((output / "kappa_L_first_pass.csv").exists())
            rejected_csv = output / "kappa_L_first_pass_rejected_diagnostic.csv"
            self.assertTrue(rejected_csv.is_file())
            self.assertTrue(
                rejected_csv.read_text().startswith("status,T_K,")
            )
            self.assertEqual(summary["force_dataset"]["fc2"]["dataset"], "force_constants")
            self.assertEqual(summary["force_dataset"]["fc3"]["dataset"], "fc3")
            self.assertEqual(len(summary["execution_evidence"]["qmesh_stages"]), 5)


if __name__ == "__main__":
    unittest.main()

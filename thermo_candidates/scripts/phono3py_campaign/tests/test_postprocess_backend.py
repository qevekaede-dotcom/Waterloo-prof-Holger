"""Synthetic evidence tests only; no phono3py, HDF5 calculations or jobs."""

import copy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from postprocess_backend import (
    ForceArtifact, PostprocessError, audit_force_artifact, audit_force_product, audit_kappa_payload,
    audit_force_constant_summary,
    canonical_hash, claim_review, conventional_frame, file_hash,
    load_force_artifact, plan_force_collection, qe_settings, qmesh_convergence, rotate_tensor,
    tensor_from_six,
)


INPUT = """&CONTROL
 calculation = 'scf', prefix = 'test', outdir = './tmp',
 pseudo_dir = '/pseudo', tprnfor = .true.
/
&SYSTEM
 ibrav = 0, nat = 2, ntyp = 2, ecutwfc = 80, ecutrho = 640,
 occupations = 'fixed', nosym = .true., noinv = .true.
/
&ELECTRONS
 conv_thr = 1.0d-10
/
&IONS
/
&CELL
/
ATOMIC_SPECIES
S 32.06 S.UPF
Zr 91.22 Zr.UPF
ATOMIC_POSITIONS crystal
S 0 0 0
Zr 0.5 0.5 0.5
K_POINTS automatic
2 2 2 0 0 0
CELL_PARAMETERS angstrom
10 0 0
0 10 0
0 0 10
"""

OUTPUT = """Program PWSCF
 convergence has been achieved in 10 iterations
 Forces acting on atoms (cartesian axes, Ry/au):

 atom 1 type 1 force = 0.000001 0.000000 0.000000
 atom 2 type 2 force = -0.000001 0.000000 0.000000
 Total force = 0.0000014 Total SCF correction = 0.0
 JOB DONE.
"""


class ForceGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "phono3py_disp.yaml"
        self.dataset.write_text("test dataset\n")

    def artifact(self, identifier, text=INPUT, output=OUTPUT, stderr=""):
        directory = self.root / str(identifier)
        directory.mkdir(exist_ok=True)
        paths = [directory / name for name in ("scf.in", "scf.out", "scf.err")]
        for path, content in zip(paths, (text, output, stderr)):
            path.write_text(content)
        manifest = {"input_sha256": file_hash(paths[0]), "output_sha256": file_hash(paths[1]),
                    "stderr_sha256": file_hash(paths[2]), "dataset_sha256": file_hash(self.dataset),
                    "supercell_sha256": "b"*64, "settings_sha256": canonical_hash(qe_settings(text)),
                    "pseudo_sha256": {"S": "a"*64, "Zr": "c"*64}, "atom_order": ["S", "Zr"],
                    "returncode": 0}
        return ForceArtifact(identifier, *map(str, paths), manifest)

    def plan(self, artifacts, kind="fc3", ids=(1, 3), pristine=None):
        return plan_force_collection(kind=kind, dataset_path=str(self.dataset),
                                     dataset_sha256=file_hash(self.dataset), expected_ids=ids,
                                     displaced=artifacts, pristine=pristine or self.artifact(0))

    def test_ordered_cutoff_ids_and_cf2_cf3_flags(self):
        artifacts = [self.artifact(3), self.artifact(1)]
        for kind in ("fc2", "fc3"):
            result = self.plan(artifacts, kind)
            self.assertEqual(result["ordered_ids"], [1, 3])
            self.assertEqual(result["argv"][2], "--cf2" if kind == "fc2" else "--cf3")
            self.assertEqual(result["argv"][3], artifacts[1].output_path)
            self.assertEqual(result["argv"][-2], "--cfz")

    def test_missing_duplicate_and_extra_ids(self):
        one, three = self.artifact(1), self.artifact(3)
        for artifacts in ([one], [one, one, three], [one, three, self.artifact(4)]):
            with self.assertRaisesRegex(PostprocessError, "displacement IDs"):
                self.plan(artifacts)
        with self.assertRaisesRegex(PostprocessError, "numerical file order"):
            self.plan([three, one], ids=(3, 1))

    def test_hash_mutation(self):
        artifact = self.artifact(1)
        Path(artifact.output_path).write_text(OUTPUT + "changed")
        with self.assertRaisesRegex(PostprocessError, "output hash"):
            audit_force_artifact(artifact)

    def test_error_after_forces_and_stderr_abort(self):
        for output, stderr in ((OUTPUT + "Error in routine seqopn", ""), (OUTPUT, "MPI_ABORT invoked")):
            with self.assertRaises(PostprocessError):
                audit_force_artifact(self.artifact(1, output=output, stderr=stderr))

    def test_output_atom_type_order(self):
        swapped = OUTPUT.replace("atom 1 type 1", "atom 1 type 2")
        with self.assertRaisesRegex(PostprocessError, "atom-type order"):
            audit_force_artifact(self.artifact(1, output=swapped))

    def test_settings_pseudos_and_pristine_must_match(self):
        one, three = self.artifact(1), self.artifact(3, INPUT.replace("ecutwfc = 80", "ecutwfc = 90"))
        with self.assertRaisesRegex(PostprocessError, "settings_sha256"):
            self.plan([one, three])
        three = self.artifact(3)
        three.manifest["pseudo_sha256"]["S"] = "e"*64
        with self.assertRaisesRegex(PostprocessError, "pseudo_sha256"):
            self.plan([one, three])
        pristine = self.artifact(0, output=OUTPUT.replace("0.000001", "0.0002"))
        with self.assertRaisesRegex(PostprocessError, "pristine residual"):
            self.plan([one, self.artifact(3)], pristine=pristine)

    def test_runtime_paths_excluded_but_physics_not(self):
        self.assertEqual(qe_settings(INPUT), qe_settings(INPUT.replace("prefix = 'test'", "prefix = 'other'")))
        self.assertNotEqual(qe_settings(INPUT), qe_settings(INPUT.replace("1.0d-10", "1.0d-8")))
        with self.assertRaisesRegex(PostprocessError, "nosym"):
            qe_settings(INPUT.replace("nosym = .true.", "nosym = .false."))

    def test_collected_product_residual_and_excluded_zero_blocks(self):
        pristine = self.artifact(0)
        one = self.artifact(1, output=OUTPUT.replace("0.000001", "0.000003"))
        product = "# File 1\n0.000002 0 0\n-0.000002 0 0\n# excluded pair\n0 0 0\n0 0 0\n"
        args = {"all_dataset_ids": [1, 2], "included": [one], "pristine": pristine}
        self.assertEqual(audit_force_product(product, **args)["excluded_zero_blocks"], 1)
        with self.assertRaisesRegex(PostprocessError, "residual-corrected"):
            audit_force_product(product.replace("0.000002", "0.000003"), **args)
        with self.assertRaisesRegex(PostprocessError, "block/atom count"):
            audit_force_product(product + "0 0 0\n", **args)
        with self.assertRaisesRegex(PostprocessError, "complete numerical 1..N"):
            audit_force_product(product, **{**args, "all_dataset_ids": [1, 3]})


class ForceReceiptAdapterTests(unittest.TestCase):
    """Use force_backend's actual nested receipts and TSV fields, no QE run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "force" / "bundle"
        (self.bundle / "inputs").mkdir(parents=True)
        dataset_dir = self.root / "preflight" / "candidates" / "s__c"
        dataset_dir.mkdir(parents=True)
        self.dataset = dataset_dir / "phono3py_disp.yaml"
        self.dataset.write_text("synthetic dataset; force IDs 1 and 3 included\n")
        supercell = dataset_dir / "supercell.in"
        supercell.write_text("synthetic pristine supercell\n")
        self.selection_sources = {}
        for probe in ("amplitude-probe", "accuracy-probe"):
            probe_dir = self.root / "selection" / probe
            probe_dir.mkdir(parents=True)
            for name in ("phono3py_disp.yaml", "supercell.in"):
                path = probe_dir / name
                path.write_text(f"synthetic {probe} {name}\n")
                self.selection_sources[str(path)] = file_hash(path)
        pseudos = {}
        for label in ("S", "Zr"):
            path = self.root / f"{label}.UPF"
            path.write_text(f"synthetic {label} pseudopotential")
            pseudos[label] = {"file": str(path), "sha256": file_hash(path)}
        fields = ["task_id", "displacement_id", "role", "input_path", "input_sha256"]
        tasks = []
        for task_id, identifier in enumerate((0, 1, 3)):
            path = self.bundle / "inputs" / f"task-{task_id:05d}.in"
            path.write_text(INPUT if identifier == 0 else INPUT.replace("S 0 0 0", "S 0.001 0 0"))
            tasks.append({"task_id": task_id, "displacement_id": identifier,
                          "role": "pristine" if identifier == 0 else "displacement",
                          "input_path": str(path), "input_sha256": file_hash(path),
                          "nat": 2, "atom_labels": ["S", "Zr"], "species_types": [1, 2]})
        task_map = self.bundle / "task_map.tsv"
        with task_map.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: task[key] for key in fields} for task in tasks)
        self.manifest = self.bundle / "force_manifest.json"
        self.dump(self.manifest, {"schema_version": 1, "stage": "force", "mode": "production",
                  "material": "synthetic", "tasks": tasks, "task_count": len(tasks),
                  "task_map_sha256": file_hash(task_map), "pseudopotentials": pseudos,
                  "selection_evidence_sha256": self.selection_sources,
                  "selection_validation": {"evidence_sha256": self.selection_sources},
                  "evidence_sha256": {str(p): file_hash(p) for p in (self.dataset, supercell)}})
        manifest_hash = file_hash(self.manifest)
        self.attempts = []
        for task in tasks:
            attempt = self.root / "attempts" / str(task["task_id"])
            attempt.mkdir(parents=True)
            self.attempts.append(attempt)
            (attempt / "scf.in").write_text(Path(task["input_path"]).read_text())
            (attempt / "scf.out").write_text(OUTPUT)
            (attempt / "scf.err").write_text("")
            command = ["srun", "pw.x", "-nk", "1", "-in", "scf.in"]
            process = {"command": command, "cwd": str(attempt), "started_utc": "synthetic",
                       "finished_utc": "synthetic", "returncode": 0,
                       "stdout_sha256": file_hash(attempt / "scf.out"),
                       "stderr_sha256": file_hash(attempt / "scf.err")}
            self.dump(attempt / "force_claim.json", {"task_id": task["task_id"], "manifest_sha256": manifest_hash})
            self.dump(attempt / "launch.json", {"task": task, "force_manifest_sha256": manifest_hash,
                      "command": command, "created_utc": "synthetic", "job_id": "test"})
            self.dump(attempt / "scf.process.json", process)
            self.dump(attempt / "result.json", {"healthy": True, "task_id": task["task_id"],
                      "displacement_id": task["displacement_id"], "role": task["role"],
                      "health": {"healthy": True}, "process": process,
                      "input_sha256": task["input_sha256"], "output_sha256": process["stdout_sha256"],
                      "force_manifest_sha256": manifest_hash})

    def dump(self, path, value):
        path.write_text(json.dumps(value))

    def mutate(self, path, fn):
        value = json.loads(path.read_text())
        fn(value)
        self.dump(path, value)

    def load(self, task_id=1):
        return load_force_artifact(self.manifest, self.attempts[task_id], task_id)

    def test_backend_receipts_to_ordered_collection(self):
        pristine, one, three = [self.load(i) for i in range(3)]
        plan = plan_force_collection(kind="fc3", dataset_path=str(self.dataset),
                                    dataset_sha256=file_hash(self.dataset), expected_ids=[1, 3],
                                    displaced=[three, one], pristine=pristine)
        self.assertTrue(plan["accepted"])
        self.assertEqual(plan["ordered_ids"], [1, 3])
        self.assertEqual(plan["argv"][3:5], [one.output_path, three.output_path])
        self.assertEqual(one.manifest["force_manifest_sha256"], file_hash(self.manifest))
        self.assertEqual(one.manifest["settings_sha256"], pristine.manifest["settings_sha256"])

    def test_wrong_task_or_displacement_id(self):
        with self.assertRaisesRegex(PostprocessError, "claim task"):
            load_force_artifact(self.manifest, self.attempts[1], 2)
        self.mutate(self.attempts[1] / "result.json", lambda v: v.update(displacement_id=2))
        with self.assertRaisesRegex(PostprocessError, "result task"):
            self.load()

    def test_mutated_raw_and_task_map_are_rejected(self):
        raw = self.attempts[1] / "scf.out"
        raw.write_text(OUTPUT + "altered\n")
        with self.assertRaisesRegex(PostprocessError, "output hash"):
            self.load()
        raw.write_text(OUTPUT)
        path = self.bundle / "task_map.tsv"
        path.write_text(path.read_text() + "extra\n")
        with self.assertRaisesRegex(PostprocessError, "task map hash"):
            self.load()

    def test_nested_process_mismatch_and_failed_exit_are_rejected(self):
        path = self.attempts[1] / "result.json"
        self.mutate(path, lambda v: v["process"].update(returncode=1))
        with self.assertRaisesRegex(PostprocessError, "nested process receipt differs"):
            self.load()
        self.mutate(self.attempts[1] / "scf.process.json", lambda v: v.update(returncode=1))
        with self.assertRaisesRegex(PostprocessError, "did not exit successfully"):
            self.load()

    def test_stderr_hash_and_launch_task_are_checked(self):
        path = self.attempts[1] / "scf.err"
        path.write_text("changed")
        with self.assertRaisesRegex(PostprocessError, "stderr hash"):
            self.load()
        path.write_text("")
        self.mutate(self.attempts[1] / "launch.json", lambda v: v["task"].update(displacement_id=3))
        with self.assertRaisesRegex(PostprocessError, "launch task"):
            self.load()

    def test_missing_dataset_anchor_fails_closed(self):
        self.mutate(self.manifest, lambda v: v["evidence_sha256"].pop(str(self.dataset)))
        with self.assertRaisesRegex(PostprocessError, "exactly one displacement dataset"):
            self.load()

    def test_missing_or_inconsistent_selection_namespace_fails_closed(self):
        original = self.manifest.read_text()
        for mutation in (
                lambda v: v.pop("selection_evidence_sha256"),
                lambda v: v.pop("selection_validation"),
                lambda v: v["selection_validation"].update(evidence_sha256={})):
            with self.subTest(mutation=mutation):
                self.manifest.write_text(original)
                self.mutate(self.manifest, mutation)
                with self.assertRaisesRegex(PostprocessError, "production selection evidence"):
                    self.load()

    def test_mutated_or_missing_selection_source_fails_closed(self):
        source = Path(next(iter(self.selection_sources)))
        source.write_text("altered selection geometry")
        with self.assertRaisesRegex(PostprocessError, "selection source evidence hash"):
            self.load()
        source.unlink()
        with self.assertRaisesRegex(PostprocessError, "missing selection source evidence"):
            self.load()

    def test_source_evidence_pseudo_and_claim_mutation_are_rejected(self):
        original = self.dataset.read_text()
        self.dataset.write_text("altered dataset")
        with self.assertRaisesRegex(PostprocessError, "source evidence hash"):
            self.load()
        self.dataset.write_text(original)
        pseudo = self.root / "S.UPF"
        original = pseudo.read_text()
        pseudo.write_text("altered pseudo")
        with self.assertRaisesRegex(PostprocessError, "pseudopotential hash"):
            self.load()
        pseudo.write_text(original)
        self.mutate(self.attempts[1] / "force_claim.json", lambda v: v.update(manifest_sha256="f" * 64))
        with self.assertRaisesRegex(PostprocessError, "claim task/manifest"):
            self.load()

    def test_relative_paths_and_missing_process_fail_closed(self):
        with self.assertRaisesRegex(PostprocessError, "absolute force manifest"):
            load_force_artifact("force_manifest.json", self.attempts[1], 1)
        self.mutate(self.attempts[1] / "result.json", lambda v: v.pop("process"))
        with self.assertRaisesRegex(PostprocessError, "invalid force receipt chain"):
            self.load()


class TensorTests(unittest.TestCase):
    def test_compact_fc_shape_mapping_units_finite_and_drift(self):
        summary = {"shape": [2, 8, 8, 3, 3, 3], "p2s_map": [0, 4],
                   "sha256": "a"*64, "all_finite": True, "units": "eV angstrom^-3",
                   "acoustic_sum_rule_max_abs": 1e-9, "permutation_max_abs": 1e-9}
        args = {"order": 3, "supercell_atoms": 8, "primitive_atoms": 2,
                "expected_sha256": "a"*64, "acoustic_sum_rule_tolerance": 1e-8,
                "permutation_tolerance": 1e-8}
        self.assertTrue(audit_force_constant_summary(summary, **args)["accepted"])
        for key, value in (("p2s_map", [0, 0]), ("all_finite", False), ("units", "Ry/bohr^3"),
                           ("acoustic_sum_rule_max_abs", 1e-3), ("shape", [2, 8, 3, 3])):
            candidate = dict(summary, **{key: value})
            with self.assertRaises(PostprocessError):
                audit_force_constant_summary(candidate, **args)

    def test_full_tensor_rotation_preserves_trace_and_offdiagonal(self):
        c = math.sqrt(0.5)
        rotation = [[c, c, 0], [-c, c, 0], [0, 0, 1]]
        tensor = tensor_from_six([4, 2, 1, 0, 0, 1])
        result = rotate_tensor(tensor, rotation)
        self.assertAlmostEqual(result[0][0], 4)
        self.assertAlmostEqual(result[1][1], 2)
        self.assertAlmostEqual(result[0][1], -1)
        self.assertAlmostEqual(sum(result[i][i] for i in range(3)), 7)
        with self.assertRaises(PostprocessError):
            tensor_from_six([4, 2, 1])

    def test_frame_uses_geometry_and_rejects_oblique_or_left_handed(self):
        frame = conventional_frame([[0, 2, 0], [-3, 0, 0], [0, 0, 4]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.assertAlmostEqual(frame["rotation_rows"][0][1], 1)
        self.assertAlmostEqual(frame["rotation_rows"][1][0], -1)
        for cell in ([[1, 0, 0], [0.4, 1, 0], [0, 0, 1]], [[1, 0, 0], [0, 1, 0], [0, 0, -1]]):
            with self.assertRaises(PostprocessError):
                conventional_frame(cell, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])


class HDF5GateTests(unittest.TestCase):
    def setUp(self):
        self.config = {"material": {"unitcell_atoms": 1}, "software": {"phono3py_version": "4.4.0"},
                       "nac": {"enabled_for_first_pass": False}, "postprocess": {
                           "temperatures_K": [300, 600, 900], "solver": "phono3py_BTE_RTA",
                           "isotope_scattering": False, "boundary_scattering": False, "explicit_SOC": False,
                           "q_mesh_ladder": [[2, 2, 2], [3, 3, 3], [4, 4, 4], [5, 5, 5]],
                           "harmonic_stability_gate": {"imaginary_frequency_tolerance_THz": -0.1},
                           "q_mesh_acceptance": {"maximum_relative_change_trace_over_3": 0.03,
                                                 "maximum_relative_change_each_diagonal_component": 0.05,
                                                 "consecutive_passing_mesh_steps_required": 2}}}
        self.payload = {"temperature": [300, 600, 900], "kappa": [[1, 2, 3, 0, 0, 0]]*3,
                        "mesh": [2, 2, 2], "frequency": [[-0.001, 1, 2]], "weight": [8], "qpoint": [[0, 0, 0]]}
        self.metadata = {key: "a"*64 for key in ("hdf5_sha256", "fc2_sha256", "fc3_sha256", "dataset_sha256", "settings_sha256")}
        self.metadata.update({"grid_matrix": [[2, 0, 0], [0, 2, 0], [0, 0, 2]], "ladder_index": 0,
                              "solver": "phono3py_BTE_RTA", "nac": False, "isotope_scattering": False,
                              "boundary_scattering": False, "explicit_SOC": False, "phono3py_version": "4.4.0",
                              "units": {"kappa": "W m^-1 K^-1", "frequency": "THz", "temperature": "K"}})

    def audit(self, payload=None, metadata=None, expected=None, rotation=None):
        return audit_kappa_payload(payload or self.payload, metadata or self.metadata,
                                   expected or self.metadata, self.config, rotation)

    def test_valid_sampled_result(self):
        report = self.audit()
        self.assertTrue(report["accepted"])
        self.assertIn("sampled mesh", report["stability_scope"])

    def test_temperature_units_nonfinite_coverage_and_hash_failures(self):
        for key, value in (("temperature", [600, 300, 900]), ("weight", [7]),
                           ("kappa", [[math.nan]*6]*3), ("frequency", [[1, 2]])):
            payload = copy.deepcopy(self.payload)
            payload[key] = value
            with self.assertRaises(PostprocessError):
                self.audit(payload=payload)
        for key, value in (("units", {}), ("fc3_sha256", "b"*64), ("solver", "LBTE")):
            metadata = copy.deepcopy(self.metadata)
            metadata[key] = value
            with self.assertRaises(PostprocessError):
                self.audit(metadata=metadata, expected=self.metadata)

    def test_significant_gamma_imaginary_requires_review_not_exception(self):
        self.payload["frequency"][0][0] = -0.2
        report = self.audit()
        self.assertFalse(report["accepted"])
        self.assertTrue(report["Gamma_exception_requires_review"])

    def test_tensor_psd_and_required_rotation(self):
        self.payload["kappa"] = [[1, 1, 1, 0, 0, 2]]*3
        with self.assertRaisesRegex(PostprocessError, "positive semidefinite"):
            self.audit()
        self.payload["kappa"] = [[1, 1, 1, 0, 0, 0]]*3
        self.config["postprocess"]["q_mesh_acceptance"]["compare_in_rotated_conventional_frame"] = True
        with self.assertRaisesRegex(PostprocessError, "frame required"):
            self.audit()

    def test_grg_requires_recorded_matrix_length_spacing_and_rotation(self):
        post = self.config["postprocess"]
        post["use_grg"] = True
        post["q_mesh_length_ladder"] = [{"mesh_length_cli_bohr": 85.03767560816}]
        post["q_mesh_acceptance"]["compare_in_rotated_conventional_frame"] = True
        post["q_mesh_acceptance"]["investigate_if_max_off_diagonal_fraction_of_trace_over_3_exceeds"] = 0.05
        self.metadata["grid_matrix"] = [[2, 1, 0], [0, 2, 0], [0, 0, 2]]
        self.metadata["mesh_length_cli_bohr"] = 85.03767560816
        self.metadata["reciprocal_spacing_inv_angstrom"] = [0.1, 0.1, 0.1]
        rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assertTrue(self.audit(rotation=rotation)["accepted"])
        self.payload["kappa"] = [[1, 2, 3, 0, 0, 0.2]]*3
        self.assertFalse(self.audit(rotation=rotation)["accepted"])
        del self.metadata["reciprocal_spacing_inv_angstrom"]
        with self.assertRaisesRegex(PostprocessError, "spacing"):
            self.audit(rotation=rotation)

    def reports(self, scales):
        results = []
        for index, scale in enumerate(scales):
            payload, metadata = copy.deepcopy(self.payload), copy.deepcopy(self.metadata)
            mesh = index + 2
            payload["mesh"], payload["weight"] = [mesh]*3, [mesh**3]
            payload["kappa"] = [[scale, 2*scale, 3*scale, 0, 0, 0]]*3
            metadata["ladder_index"] = index
            metadata["grid_matrix"] = [[mesh, 0, 0], [0, mesh, 0], [0, 0, mesh]]
            results.append(self.audit(payload, metadata, metadata))
        return results

    def test_two_consecutive_trailing_steps_required(self):
        policy = self.config["postprocess"]["q_mesh_acceptance"]
        reports = self.reports([1, 1.01, 1.02, 1.4])
        self.assertFalse(qmesh_convergence(reports[:2], policy)["qmesh_converged"])
        self.assertTrue(qmesh_convergence(reports[:3], policy)["qmesh_converged"])
        self.assertFalse(qmesh_convergence(reports, policy)["qmesh_converged"])

    def test_tensor_failure_not_hidden_in_average_and_mixed_data_refused(self):
        policy = self.config["postprocess"]["q_mesh_acceptance"]
        reports = self.reports([1, 1.01, 1.02])
        reports[-1]["tensors_comparison_W_mK"][0][0][0] += 0.2
        reports[-1]["tensors_comparison_W_mK"][0][1][1] -= 0.2
        self.assertFalse(qmesh_convergence(reports, policy)["qmesh_converged"])
        reports[-1]["physics_fingerprint"] = "b"*64
        with self.assertRaises(PostprocessError):
            qmesh_convergence(reports, policy)
        with self.assertRaises(PostprocessError):
            qmesh_convergence(self.reports([1, 1.01, 1.02])[::2], policy)

    def test_claims_require_force_accuracy_and_keep_nac_limit(self):
        args = {"force_gate_passed": True, "hdf5_gate_passed": True, "qmesh_gate_passed": True}
        self.assertEqual(claim_review(**args)["label"], "workflow_or_validation_status_only")
        result = claim_review(**args, force_accuracy_passed=True, amplitude_passed=True)
        self.assertEqual(result["label"], "calculated_first_pass")
        self.assertIn("NAC_sensitivity", result["missing_gates"])
        self.assertFalse(result["final_zT_claim_allowed"])


if __name__ == "__main__":
    unittest.main()

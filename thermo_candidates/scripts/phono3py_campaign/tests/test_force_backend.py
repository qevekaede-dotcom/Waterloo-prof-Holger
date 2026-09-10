"""Synthetic provenance and force-task failure tests; no scientific execution."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import campaign as core
import force_backend as fb


class ForceBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.dataset = self.run / "preflight" / "attempt" / "candidates" / "s__c"
        self.dataset.mkdir(parents=True)
        self.pseudo = self.root / "pseudo"
        self.pseudo.mkdir()
        (self.pseudo / "X.upf").write_text("synthetic pseudopotential, never execute")
        self.config = {
            "material": {"formula": "X", "unitcell_atoms": 2},
            "electronic_model": {"exchange_correlation": "PBE", "explicit_spin_orbit_coupling": False, "occupations": "fixed", "charge_state": 0, "magnetic_order": "nonmagnetic"},
            "pseudopotentials": {"files": {"X": "X.upf"}},
            "production": {"selection_required": True, "automatic_submission_allowed": False},
            "force_and_amplitude_validation": {"selection_required": True},
            "resource_budget": {"selection_required_before_force_submission": True, "approved_total_core_hours_per_material": None,
                "initial_timing_and_noise_batch": {"maximum_new_scf_tasks": 6, "maximum_concurrent_force_tasks_per_material": 2},
                "pilot_batch_maximum_new_scf_tasks": 32, "production_first_batch_maximum_tasks": 32,
                "production_later_batch_maximum_tasks": 64, "maximum_technical_retries_per_task": 1},
            "displacements": {"hard_cap": 5, "supercell_candidates": [{"id": "s", "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "atoms": 2}], "cutoff_candidates": [{"id": "c", "cutoff_pair_distance_angstrom": 4 * core.BOHR_TO_ANGSTROM, "cutoff_pair_distance_cli_bohr": 4.0}]},
        }
        self.spec = {"rationale": "synthetic force noise test", "supercell_id": "s", "cutoff_id": "c", "amplitude_angstrom": 0.06 * core.BOHR_TO_ANGSTROM, "amplitude_bohr": 0.06, "ecutwfc_Ry": 80, "ecutrho_Ry": 640, "conv_thr_Ry": 1e-10, "kmesh": [2, 2, 2], "displacement_ids": [1, 2], "duplicate_displacement_ids": [1,2], "pristine_repetitions":2}
        self.config_path = self.root / "campaign.json"
        self.dump(self.config_path, self.config)
        self.data = {"physical_unit": {"length": "au"}, "supercell_matrix": [[1,0,0],[0,1,0],[0,0,1]], "supercell": {"lattice": [[10,0,0],[0,10,0],[0,0,10]], "points": [{"symbol": "X", "coordinates": [0,0,0]}, {"symbol": "X", "coordinates": [0.5,0.5,0.5]}]}, "displacement_pair_info": {"cutoff_pair_distance": 4.0}, "displacement_pairs": [{"atom": 1, "displacement_id": 1, "displacement": [0.06,0,0], "paired_with": [{"atom": 2, "included": True, "displacement_ids": [2], "displacements": [[0,0.06,0]]}, {"atom": 2, "included": False, "displacement_ids": [3], "displacements": [[0,-0.06,0]]}]}]}
        for pair in self.data["displacement_pairs"][0]["paired_with"]:
            pair["pair_distance"] = 8.660254037844386
        self.dump(self.dataset / "phono3py_disp.yaml", self.data)
        self.fragment("supercell.in", 0, 0.5)
        self.fragment("supercell-00001.in", 0.006, 0.5)
        self.fragment("supercell-00002.in", 0.006, 0.506)
        settings = fb._settings(self.config, "pilot", self.spec)
        self.unitcell = fb._fragment(self.dataset / "supercell.in", settings, self.pseudo)
        (self.dataset / "unitcell.in").write_text(self.unitcell)
        self.accepted = self.run / "relax" / "attempt"
        self.final = self.run / "relax" / "final"
        self.accepted.mkdir(parents=True)
        self.final.mkdir()
        (self.final / "unitcell.in").write_text(self.unitcell)
        self.dump(self.final / "gate.json", {"pass": True, "final_unitcell_sha256": core.sha256_path(self.final / "unitcell.in")})
        for name in ("relax.in", "pristine.in"):
            (self.accepted / name).write_text(self.unitcell)
        for name in ("relax.out", "pristine.out"):
            (self.accepted / name).write_text("synthetic archived evidence")
        execution = {"pseudopotentials": core.pseudopotential_hashes(self.config, self.pseudo)}
        for name, key in (("relax.in", "relax_input_sha256"), ("relax.out", "relax_output_sha256"), ("pristine.in", "pristine_input_sha256"), ("pristine.out", "pristine_output_sha256")):
            execution[key] = core.sha256_path(self.accepted / name)
        self.dump(self.accepted / "execution_manifest.json", execution)
        self.dump(self.accepted / "starting_structure_audit.json", {"synthetic": True})
        self.dump(self.final / "provenance.json", {"accepted_attempt": str(self.accepted), "execution_manifest_sha256": core.sha256_path(self.accepted / "execution_manifest.json"), "starting_structure_audit_sha256": core.sha256_path(self.accepted / "starting_structure_audit.json")})
        self.dump(self.run / "run_manifest.json", {"schema_version": 2, "material": "X", "preflight_policy_sha256": "synthetic-policy",
            "source_qe_input": str(self.accepted / "relax.in"), "source_qe_sha256": core.sha256_path(self.accepted / "relax.in"),
            "source_relax_output": str(self.accepted / "relax.out"), "source_relax_sha256": core.sha256_path(self.accepted / "relax.out"),
            "workflow_files": {"campaign.py": "old-upstream-driver-hash"}})
        self.inventory = self.dataset.parents[1] / "preflight_inventory.json"
        self.refresh_preflight()
        ForceBackendTests.signed_fixture(self)
        # Synthetic fixtures need no repository raw-data files or spglib.
        self.validate = patch.object(core, "validate_config", side_effect=lambda _: (copy.deepcopy(self.config), {})).start()
        self.verify = patch.object(core, "verify_manifest", return_value={}).start()
        patch.object(core, "policy_sha256", return_value="synthetic-policy").start()
        self.addCleanup(patch.stopall)

    def dump(self, path, obj):
        path.write_text(json.dumps(obj))

    def fragment(self, name, first_x, second_y, first_y=0):
        (self.dataset / name).write_text(f"! ibrav = 0, nat = 2, ntyp = 1\nCELL_PARAMETERS bohr\n10 0 0\n0 10 0\n0 0 10\nATOMIC_SPECIES\nX 10 X.upf\nATOMIC_POSITIONS crystal\nX {first_x} {first_y} 0\nX 0.5 {second_y} 0.5\n")

    def refresh_preflight(self):
        result = {"supercell_id": "s", "cutoff_id": "c", "generated_atoms": 2, "within_hard_cap": True, "count_only": False, "yaml_sha256": core.sha256_path(self.dataset / "phono3py_disp.yaml"), "unitcell_sha256": core.sha256_path(self.dataset / "unitcell.in"), "generated_displacement_ids": [1,2]}
        self.dump(self.dataset / "preflight_result.json", result)
        self.dump(self.inventory, {"preflight_policy_sha256": "synthetic-policy", "accepted_unitcell_sha256": result["unitcell_sha256"], "accepted_relax_provenance_sha256": core.sha256_path(self.final / "provenance.json"), "results": [result]})
        if hasattr(self, "signed_sha"):
            ForceBackendTests.signed_fixture(self)

    def signed_fixture(self):
        """Hash-complete adapter fixture; real generator/auditor has its own integration tests."""
        self.dump(self.dataset / "probe_spec.json", {k:self.spec[k] for k in ("supercell_id","cutoff_id","amplitude_angstrom","amplitude_bohr")})
        self.dump(self.dataset / "config.snapshot.json", self.config)
        (self.dataset / "preflight_inventory.json").write_text(self.inventory.read_text())
        roles = {"0":["pristine"]}
        for first in self.data["displacement_pairs"]:
            roles[str(first["displacement_id"])] = [{"kind":"single", "probe_id":"synthetic-single", "sign":"plus"}]
            for pair in first["paired_with"]:
                if pair["included"]:
                    roles.update({str(i):[{"kind":"mixed", "probe_id":"synthetic-mixed", "sign":"pp"}] for i in pair["displacement_ids"]})
        files = [p for p in self.dataset.iterdir() if p.is_file() and p.name != "pilot_dataset_manifest.json"]
        self.dump(self.dataset / "pilot_dataset_manifest.json", {"schema_version":1, "stage":"pilot_geometry_preparation",
            "pilot_only":True, "run_dir":str(self.run.resolve()), "accepted_unitcell_sha256":core.sha256_path(self.final / "unitcell.in"),
            "geometry_plan":{"roles_by_displacement_id":roles}, "files_sha256":{p.name:core.sha256_path(p) for p in files}})
        self.signed_sha = core.sha256_path(self.dataset / "pilot_dataset_manifest.json")

    def prepare(self, **kwargs):
        with patch("pilot_dataset.audit_pilot_dataset", return_value={"healthy":True,"pilot_only":True,
            "generated_displacement_ids":core.analyze_displacement_yaml(self.data)["included_displacement_ids"]}):
            return fb.prepare_force(self.config_path, self.run, preflight_inventory=self.inventory, dataset_dir=self.dataset,
                output_dir=kwargs.pop("output_dir", self.run / "force" / "bundle"), pseudo_dir=self.pseudo, mode=kwargs.pop("mode", "pilot"),
                pilot_spec=kwargs.pop("pilot_spec", self.spec), resource_request=kwargs.pop("resource_request", {"phase": "initial", "mpi_ranks": 32, "walltime_hours": 1, "max_concurrency": 2}),
                pilot_dataset_manifest_sha256=kwargs.pop("pilot_dataset_manifest_sha256", self.signed_sha), **kwargs)

    def test_pilot_dynamic_map_includes_pristine_and_duplicate(self):
        result = self.prepare()
        manifest = core.load_json(Path(result["manifest"]))
        self.assertEqual([t["displacement_id"] for t in manifest["tasks"]], [0,0,1,2,1,2])
        self.assertEqual(manifest["tasks"][0]["role"], "pristine")
        self.assertEqual(manifest["tasks"][2]["input_sha256"], manifest["tasks"][4]["input_sha256"])
        self.assertEqual(manifest["settings"]["kmesh"], [2,2,2])
        self.assertTrue(self.config["production"]["selection_required"])
        self.assertFalse(self.verify.called)  # Older completed upstream code is valid.
        with self.assertRaisesRegex(fb.ForceError, "already exists"):
            self.prepare()

    def test_production_gate_requires_both_selections(self):
        with self.assertRaisesRegex(fb.ForceError, "explicit production"):
            self.prepare(mode="production")

    def test_explicit_production_flags_cannot_override_scientific_eligibility(self):
        self.config["production"] = {"selection_required": False, "automatic_submission_allowed": True,
            "selected_supercell": "s", "selected_cutoff": "c", "selected_fc3_supercell_matrix": self.data["supercell_matrix"],
            "selected_cutoff_pair_distance_angstrom": 4 * core.BOHR_TO_ANGSTROM, "selected_cutoff_pair_distance_cli_bohr": 4.0}
        self.config["force_and_amplitude_validation"] = {"selection_required": False,
            "selected_displacement_distance_angstrom": self.spec["amplitude_angstrom"], "selected_displacement_distance_cli_bohr": 0.06,
            "selected_ecutwfc_Ry": 80, "selected_ecutrho_Ry": 640, "selected_conv_thr_Ry": 1e-10, "selected_k_points": [2,2,2]}
        with self.assertRaisesRegex(fb.ForceError, "selection_eligible"):
            self.prepare(mode="production")
        result = core.load_json(self.dataset / "preflight_result.json")
        result["selection_eligible"] = True
        self.dump(self.dataset / "preflight_result.json", result)
        inventory = core.load_json(self.inventory)
        inventory["results"] = [result]
        self.dump(self.inventory, inventory)
        with self.assertRaisesRegex(fb.ForceError, "actual amplitude/force-accuracy"):
            self.prepare(mode="production")

    def test_sparse_included_ids_are_not_reindexed(self):
        self.data["displacement_pairs"][0]["paired_with"][0]["displacement_ids"] = [3]
        self.data["displacement_pairs"][0]["paired_with"][1]["displacement_ids"] = [2]
        self.dump(self.dataset / "phono3py_disp.yaml", self.data)
        (self.dataset / "supercell-00002.in").rename(self.dataset / "supercell-00003.in")
        self.refresh_preflight()
        result = core.load_json(self.dataset / "preflight_result.json")
        result["generated_displacement_ids"] = [1,3]
        self.dump(self.dataset / "preflight_result.json", result)
        inventory = core.load_json(self.inventory)
        inventory["results"] = [result]
        self.dump(self.inventory, inventory)
        self.signed_fixture()
        prepared = self.prepare(pilot_spec={**self.spec, "displacement_ids": [1,3], "duplicate_displacement_ids": [1,3]})
        manifest = core.load_json(Path(prepared["manifest"]))
        self.assertEqual([t["displacement_id"] for t in manifest["tasks"]], [0,0,1,3,1,3])

    def test_tilted_cell_inverse_maps_row_cartesian_vectors(self):
        cell = [[2,1,3],[1,4,2],[-2,1,5]]
        inv = fb._inverse(cell)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(sum(cell[i][k]*inv[k][j] for k in range(3)), int(i == j))

    def test_no_implicit_pilot(self):
        with self.assertRaisesRegex(fb.ForceError, "explicit specification"):
            self.prepare(pilot_spec=None)

    def test_mutated_accepted_relax_rejected(self):
        (self.accepted / "pristine.out").write_text("changed")
        with self.assertRaisesRegex(fb.ForceError, "altered evidence"):
            self.prepare()

    def test_altered_yaml_hash_rejected(self):
        with (self.dataset / "phono3py_disp.yaml").open("a") as f:
            f.write(" ")
        with self.assertRaisesRegex(fb.ForceError, "altered evidence"):
            self.prepare()

    def test_wrong_yaml_units_and_amplitude_rejected(self):
        for mutation in ("unit", "amplitude"):
            data = copy.deepcopy(self.data)
            if mutation == "unit":
                data["physical_unit"]["length"] = "angstrom"
            else:
                data["displacement_pairs"][0]["displacement"][0] = 0.03
            self.dump(self.dataset / "phono3py_disp.yaml", data)
            self.refresh_preflight()
            with self.assertRaises(fb.ForceError):
                self.prepare()

    def test_excluded_id_cannot_enter_pilot(self):
        spec = {**self.spec, "displacement_ids": [3], "duplicate_displacement_ids": []}
        with self.assertRaisesRegex(fb.ForceError, "absent from audited"):
            self.prepare(pilot_spec=spec)

    def test_fragment_must_match_yaml_geometry(self):
        self.fragment("supercell-00001.in", 0.06, 0.5)
        self.signed_fixture()
        with self.assertRaisesRegex(fb.ForceError, "does not reproduce"):
            self.prepare()

    def test_missing_included_file_rejected(self):
        (self.dataset / "supercell-00002.in").unlink()
        self.signed_fixture()
        with self.assertRaisesRegex(fb.ForceError, "included displacement"):
            self.prepare()

    def test_pseudo_mutation_rejected(self):
        (self.pseudo / "X.upf").write_text("replacement")
        with self.assertRaisesRegex(fb.ForceError, "pseudopotential contents"):
            self.prepare()

    def test_count_only_candidate_rejected(self):
        result = core.load_json(self.dataset / "preflight_result.json")
        result["count_only"] = True
        self.dump(self.dataset / "preflight_result.json", result)
        inv = core.load_json(self.inventory)
        inv["results"] = [result]
        self.dump(self.inventory, inv)
        self.signed_fixture()
        with self.assertRaisesRegex(fb.ForceError, "count-only"):
            self.prepare()

    def test_compute_guard_precedes_all_io(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(fb.ForceError, "SLURM"):
                fb.run_force_task(self.config_path, self.run, task_map=self.run / "missing", task_id=0, attempt_path=self.run / "attempt")

    def fake_process(self, command, cwd, stdout, stderr, *, wrong_type=False):
        stdout.write_text("Program PWSCF\nconvergence has been achieved in 10 iterations\nForces acting on atoms (Ry/au):\n\n atom 1 type 1 force = 0.01 0 0\n atom 2 type " + ("2" if wrong_type else "1") + " force = -0.01 0 0\n\n Total force = 0.02 Total SCF correction = 0.0\nJOB DONE.\n")
        stderr.write_text("")
        report = {
            "command": list(command),
            "cwd": str(cwd),
            "started_utc": "synthetic",
            "finished_utc": "synthetic",
            "returncode": 0,
            "stdout_sha256": core.sha256_path(stdout),
            "stderr_sha256": core.sha256_path(stderr),
        }
        self.dump(stdout.with_name(f"{stdout.stem}.process.json"), report)
        return report

    def test_successful_task_and_immutable_retry(self):
        result = self.prepare()
        args = dict(task_map=Path(result["task_map"]), task_id=1, attempt_path=self.run / "attempts" / "first", compute_guard=lambda: None)
        with patch.object(core, "run_process", side_effect=self.fake_process):
            output = fb.run_force_task(self.config_path, self.run, **args)
            self.assertTrue(output["healthy"])
            with self.assertRaisesRegex(fb.ForceError, "already claimed"):
                fb.run_force_task(self.config_path, self.run, **args)

    def test_species_type_mismatch_preserves_failure(self):
        result = self.prepare()
        attempt = self.run / "attempts" / "badtype"
        with patch.object(core, "run_process", side_effect=lambda *args: self.fake_process(*args, wrong_type=True)):
            with self.assertRaisesRegex(fb.ForceError, "atom-type order"):
                fb.run_force_task(self.config_path, self.run, task_map=Path(result["task_map"]), task_id=1, attempt_path=attempt, compute_guard=lambda: None)
        self.assertTrue((attempt / "failure.json").is_file())
        self.assertTrue((attempt / "scf.out").is_file())

    def test_process_failure_preserves_launch_and_partial_output(self):
        result = self.prepare()
        attempt = self.run / "attempts" / "failed"
        def fail(command, cwd, stdout, stderr):
            stdout.write_text("partial output")
            stderr.write_text("launcher failed")
            raise fb.ForceError("exit 2")
        with patch.object(core, "run_process", side_effect=fail):
            with self.assertRaisesRegex(fb.ForceError, "exit 2"):
                fb.run_force_task(self.config_path, self.run, task_map=Path(result["task_map"]), task_id=0, attempt_path=attempt, compute_guard=lambda: None)
        self.assertTrue((attempt / "launch.json").is_file())
        self.assertTrue((attempt / "failure.json").is_file())
        self.assertEqual((attempt / "scf.out").read_text(), "partial output")

    def test_mutated_input_rejected_before_attempt(self):
        result = self.prepare()
        manifest = core.load_json(Path(result["manifest"]))
        Path(manifest["tasks"][1]["input_path"]).write_text("tampered")
        with self.assertRaisesRegex(fb.ForceError, "altered evidence"):
            fb.run_force_task(self.config_path, self.run, task_map=Path(result["task_map"]), task_id=1, attempt_path=self.run / "bad", compute_guard=lambda: None)
        self.assertFalse((self.run / "bad").exists())

    def test_out_of_range_task_rejected(self):
        result = self.prepare()
        with self.assertRaisesRegex(fb.ForceError, "outside"):
            fb.run_force_task(self.config_path, self.run, task_map=Path(result["task_map"]), task_id=99, attempt_path=self.run / "bad", compute_guard=lambda: None)

    def test_stage_upgrade_consumes_original_evidence_without_old_driver(self):
        with patch.object(core, "verify_manifest", side_effect=AssertionError("old driver hash must not be compared")):
            result = self.prepare()
        self.assertTrue(result["healthy"])
        manifest = core.load_json(Path(result["manifest"]))
        self.assertEqual(manifest["workflow_sha256"][str(Path(core.__file__))], core.sha256_path(Path(core.__file__)))

    def test_explicit_resource_request_required(self):
        with self.assertRaisesRegex(fb.ForceError, "resource_request"):
            self.prepare(resource_request=None)

    def test_initial_pilot_receipt_binds_map_retries_and_concurrency(self):
        result = self.prepare(pilot_spec={**self.spec, "pristine_repetitions": 2})
        receipt = core.load_json(Path(result["budget_receipt"]))
        self.assertEqual(receipt["task_count"], 6)
        self.assertEqual(receipt["maximum_concurrency"], 2)
        self.assertEqual(receipt["reserved_core_hours"], 6*1*32*2)
        self.assertEqual(receipt["task_map_sha256"], core.sha256_path(Path(result["task_map"])))
        self.assertEqual(set(receipt["retry_counts_at_reservation"].values()), {0})

    def test_pilot_requires_explicit_matching_signed_dataset_sha(self):
        for value in (None, "", "not-a-sha", "a"*64):
            with self.subTest(value=value), self.assertRaises(fb.ForceError):
                self.prepare(pilot_dataset_manifest_sha256=value)
        self.assertFalse((self.run / "force/bundle/task_map.tsv").exists())

    def test_signed_dataset_hashes_and_audit_are_frozen_in_force_bundle(self):
        prepared = self.prepare()
        manifest = core.load_json(Path(prepared["manifest"]))
        signed = manifest["signed_pilot_dataset"]
        self.assertEqual(signed["expected_manifest_sha256"], self.signed_sha)
        self.assertTrue(signed["audit_result"]["healthy"])
        self.assertEqual(signed["task_kinds"], {"0":"pristine","1":"single","2":"double"})
        for path,digest in signed["files_sha256"].items():
            self.assertEqual(manifest["evidence_sha256"][path], digest)
        self.assertIn(str(Path(fb.__file__).with_name("pilot_dataset.py")), manifest["workflow_sha256"])

    def test_probe_spec_must_match_selected_amplitude(self):
        spec = {**self.spec,"amplitude_bohr":0.08,"amplitude_angstrom":0.08*core.BOHR_TO_ANGSTROM}
        with self.assertRaisesRegex(fb.ForceError, "probe_spec differs"):
            self.prepare(pilot_spec=spec)

    def test_selected_id_must_have_declared_geometry_role(self):
        path = self.dataset / "pilot_dataset_manifest.json"
        manifest = core.load_json(path)
        manifest["geometry_plan"]["roles_by_displacement_id"]["1"] = []
        self.dump(path, manifest)
        with self.assertRaisesRegex(fb.ForceError, "geometry_plan roles"):
            self.prepare(pilot_dataset_manifest_sha256=core.sha256_path(path))

    def test_initial_requires_exactly_six_and_one_duplicate_of_each_kind(self):
        for updates in ({"pristine_repetitions":1}, {"duplicate_displacement_ids":[1]}, {"duplicate_displacement_ids":[1,1]}):
            with self.subTest(updates=updates), self.assertRaisesRegex(fb.ForceError, "initial pilot requires exactly"):
                self.prepare(pilot_spec={**self.spec, **updates})

    def test_double_role_name_cannot_replace_two_displaced_atoms(self):
        self.data["displacement_pairs"][0]["paired_with"][0]["atom"] = 1
        self.dump(self.dataset / "phono3py_disp.yaml", self.data)
        self.fragment("supercell-00002.in",0.006,0.5,first_y=0.006)
        self.refresh_preflight()
        with self.assertRaisesRegex(fb.ForceError, "geometry does not match"):
            self.prepare()

    def test_production_selection_sources_do_not_pollute_current_dataset_identity(self):
        from postprocess_backend import load_force_artifact, plan_force_collection
        from submit import SubmissionContext, validate_force_bundle, SubmissionError
        self.config["production"] = {"selection_required":False,"automatic_submission_allowed":True,
            "selected_supercell":"s","selected_cutoff":"c","selected_fc3_supercell_matrix":self.data["supercell_matrix"],
            "selected_cutoff_pair_distance_angstrom":4*core.BOHR_TO_ANGSTROM,"selected_cutoff_pair_distance_cli_bohr":4.0}
        self.config["force_and_amplitude_validation"] = {"selection_required":False,
            "selected_displacement_distance_angstrom":self.spec["amplitude_angstrom"],"selected_displacement_distance_cli_bohr":0.06,
            "selected_ecutwfc_Ry":80,"selected_ecutrho_Ry":640,"selected_conv_thr_Ry":1e-10,"selected_k_points":[2,2,2]}
        self.config["resource_budget"].update(approved_total_core_hours_per_material=10000,selection_required_before_force_submission=False)
        self.dump(self.config_path,self.config)
        result = core.load_json(self.dataset / "preflight_result.json")
        result["selection_eligible"] = True
        self.dump(self.dataset / "preflight_result.json",result)
        inventory = core.load_json(self.inventory)
        inventory["results"] = [result]
        self.dump(self.inventory,inventory)
        sources = {}
        for name in ("amplitude-h02","amplitude-h04"):
            folder = self.run / name
            folder.mkdir()
            for filename in ("phono3py_disp.yaml","supercell.in"):
                path = folder / filename
                path.write_text("synthetic independently audited selection source")
                sources[str(path.resolve())] = core.sha256_path(path)
        selection_path = self.run / "selection.json"
        self.dump(selection_path,{"pass":True,"synthetic_adapter_fixture":True})
        sources[str(selection_path)] = core.sha256_path(selection_path)
        selection = {"pass":True,"evidence_sha256":sources,
            "selection_receipt_path":str(selection_path),"selection_receipt_sha256":core.sha256_path(selection_path)}
        measured,_ = self.measured()
        settings = fb._settings(self.config,"production",None)
        for item in measured:
            item["cost_settings_sha256"] = core.canonical_sha256({k:settings[k] for k in fb.COST_SETTING_FIELDS})
        with patch.object(fb,"validate_selection_evidence",return_value=selection), patch.object(fb,"_measurements",return_value=(measured,{})):
            prepared = self.prepare(mode="production",selection_evidence=self.run / "selection.json",
                resource_request={"phase":"production","mpi_ranks":32,"walltime_hours":1,"max_concurrency":2,"displacement_ids":[1,2]})
        manifest_path = Path(prepared["manifest"])
        manifest = core.load_json(manifest_path)
        self.assertEqual(manifest["selection_evidence_sha256"], sources)
        self.assertEqual(len([p for p in manifest["evidence_sha256"] if Path(p).name == "phono3py_disp.yaml"]),1)
        self.assertEqual(len([p for p in manifest["evidence_sha256"] if Path(p).name == "supercell.in"]),1)
        def small_forces(command,cwd,stdout,stderr):
            report = self.fake_process(command,cwd,stdout,stderr)
            stdout.write_text(stdout.read_text().replace("0.01","0.000001").replace("0.02","0.000002"))
            report["stdout_sha256"] = core.sha256_path(stdout)
            self.dump(stdout.with_name("scf.process.json"),report)
            return report
        artifacts = []
        with patch.object(core,"run_process",side_effect=small_forces), patch.object(fb,"validate_selection_evidence",return_value=selection):
            for task_id in range(3):
                attempt = self.run / "production-attempts" / str(task_id)
                fb.run_force_task(self.config_path,self.run,task_map=Path(prepared["task_map"]),task_id=task_id,
                    attempt_path=attempt,compute_guard=lambda:None)
                artifacts.append(load_force_artifact(manifest_path,attempt,task_id))
        plan = plan_force_collection(kind="fc3",dataset_path=str(self.dataset / "phono3py_disp.yaml"),
            dataset_sha256=core.sha256_path(self.dataset / "phono3py_disp.yaml"),expected_ids=[1,2],
            displaced=artifacts[1:],pristine=artifacts[0])
        self.assertEqual(plan["ordered_ids"],[1,2])
        context = SubmissionContext(self.config_path.resolve(),self.run.resolve(),self.config,{},core.sha256_path(self.config_path))
        with patch.object(fb,"validate_selection_evidence",return_value=selection):
            validate_force_bundle(context,Path(prepared["task_map"]))
        # A passing JSON object with self-consistent hashes is not scientific
        # evidence. Real submit/runtime must replay it, not trust the manifest.
        self.dump(selection_path,{"pass":True,"force_accuracy_pass":True,"amplitude_pass":True})
        sources[str(selection_path)] = core.sha256_path(selection_path)
        forged_manifest = core.load_json(manifest_path)
        forged_manifest["selection_evidence_sha256"] = dict(sources)
        forged_manifest["selection_validation"].update(evidence_sha256=dict(sources),
            selection_receipt_sha256=core.sha256_path(selection_path))
        self.dump(manifest_path,forged_manifest)
        with self.assertRaisesRegex(SubmissionError,"selection provenance"):
            validate_force_bundle(context,Path(prepared["task_map"]))
        with self.assertRaises(core.CampaignError):
            fb.run_force_task(self.config_path,self.run,task_map=Path(prepared["task_map"]),task_id=0,
                attempt_path=self.run / "forged-pass-must-not-launch",compute_guard=lambda:None)
        self.assertFalse((self.run / "forged-pass-must-not-launch").exists())
        with patch.object(fb,"validate_selection_evidence",return_value={**selection,"pass":False}):
            with self.assertRaisesRegex(SubmissionError,"differs from raw-evidence replay"):
                validate_force_bundle(context,Path(prepared["task_map"]))
        Path(next(iter(sources))).write_text("tampered selection source")
        with self.assertRaisesRegex(SubmissionError,"selection provenance"):
            validate_force_bundle(context,Path(prepared["task_map"]))
        with self.assertRaisesRegex(fb.ForceError,"altered evidence"):
            fb.run_force_task(self.config_path,self.run,task_map=Path(prepared["task_map"]),task_id=0,
                attempt_path=self.run / "should-not-launch",compute_guard=lambda:None)

    def test_initial_pilot_cannot_be_reset_with_new_bundle_name(self):
        self.prepare()
        with self.assertRaisesRegex(fb.ForceError, "cumulative six"):
            self.prepare(output_dir=self.run / "force" / "second")
        self.assertFalse((self.run / "force/second/task_map.tsv").exists())

    def reserve(self, phase, tasks, name="reserve", **overrides):
        request = {"phase":phase, "mpi_ranks":32, "walltime_hours":1, "max_concurrency":2, **overrides}
        return fb._reserve_budget(self.config, self.run, self.run / name, tasks, "a"*64,
            "production" if phase == "production" else "pilot", request)

    def test_unapproved_production_budget_rejected(self):
        with self.assertRaisesRegex(fb.ForceError, "approved total core-hour"):
            self.reserve("production", 3)

    def test_validation_pilot_requires_timing(self):
        with self.assertRaisesRegex(fb.ForceError, "actual timing"):
            self.reserve("validation", 7)

    def test_timing_reads_real_bound_output_and_scheduler_measurements(self):
        prepared = self.prepare()
        attempt = self.run / "attempts" / "measured"
        with patch.object(core, "run_process", side_effect=self.fake_process), patch.dict(os.environ, {"SLURM_JOB_ID":"456"}):
            fb.run_force_task(self.config_path, self.run, task_map=Path(prepared["task_map"]), task_id=3, attempt_path=attempt, compute_guard=lambda:None)
        accounting = self.run / "accounting.tsv"
        accounting.write_text("JobIDRaw|ElapsedRaw|AllocCPUS|MaxRSS|State\n456|600|32|100M|COMPLETED\n")
        reference = {"sample": {"manifest_path":prepared["manifest"], "manifest_sha256":core.sha256_path(Path(prepared["manifest"])),
            "result_path":str(attempt / "result.json"), "result_sha256":core.sha256_path(attempt / "result.json")},
            "accounting_path":str(accounting), "accounting_sha256":core.sha256_path(accounting), "job_id":"456"}
        measured, hashes = fb._measurements([reference], self.run)
        self.assertEqual(measured[0]["probe_kind"], "double")
        self.assertEqual(measured[0]["scf_iterations"], 10)
        self.assertEqual(measured[0]["raw_max_force"], 0.01)
        self.assertAlmostEqual(measured[0]["core_hours"], 600*32/3600)
        self.assertIn(str(accounting.resolve()), hashes)
        accounting.write_text("JobIDRaw|ElapsedRaw|AllocCPUS|MaxRSS|State\n999|600|32|100M|COMPLETED\n")
        reference.update(job_id="999", accounting_sha256=core.sha256_path(accounting))
        with self.assertRaisesRegex(fb.ForceError, "different launched job"):
            fb._measurements([reference], self.run)

    def test_timings_cannot_substitute_a_cheaper_supercell(self):
        values, hashes = self.measured()
        for item in values:
            item["cost_settings_sha256"] = "different-cost-setting"
        with patch.object(fb, "_measurements", return_value=(values,hashes)):
            with self.assertRaisesRegex(fb.ForceError, "selected supercell"):
                fb._reserve_budget(self.config, self.run, self.run / "badcost", 3, "a"*64, "pilot",
                    {"phase":"validation", "mpi_ranks":32, "walltime_hours":1, "max_concurrency":2},
                    settings=fb._settings(self.config, "pilot", self.spec))

    def measured(self):
        return ([{"mpi_ranks":32, "elapsed_seconds":600, "core_hours":32/6,
            "job_id":str(123+i), "max_rss":"100M", "scf_iterations":10, "raw_max_force":0.01,
            "total_scf_correction":0, "material":"X", "probe_kind":kind}
            for i,kind in enumerate(("pristine","single","double"))], {})

    def test_unbudgeted_validation_cap_is_cumulative_32(self):
        with patch.object(fb, "_measurements", return_value=self.measured()):
            self.reserve("validation", 20, "first")
            with self.assertRaisesRegex(fb.ForceError, "cumulative 32"):
                self.reserve("validation", 13, "second")

    def test_production_batches_first32_then64_and_budget_cannot_be_exceeded(self):
        self.config["resource_budget"]["approved_total_core_hours_per_material"] = 10000
        self.config["resource_budget"]["selection_required_before_force_submission"] = False
        with patch.object(fb, "_measurements", return_value=self.measured()):
            with self.assertRaisesRegex(fb.ForceError, "32 SCFs"):
                self.reserve("production", 33, "too-large")
            first = self.reserve("production", 32, "first")
            self.assertEqual(first["production_batch_number"], 1)
            later = self.reserve("production", 64, "later")
            self.assertEqual(later["production_batch_number"], 2)
            self.assertEqual(later["reserved_core_hours_before"], 32*32*2)
            with self.assertRaisesRegex(fb.ForceError, "64 SCFs"):
                self.reserve("production", 65, "large-later")
            self.config["resource_budget"]["approved_total_core_hours_per_material"] = 6200
            with self.assertRaisesRegex(fb.ForceError, "remaining budget"):
                self.reserve("production", 2, "over-budget")

    def test_concurrency_and_measured_walltime_enforced(self):
        with self.assertRaisesRegex(fb.ForceError, "concurrency at most 2"):
            self.reserve("initial", 3, max_concurrency=3)
        with patch.object(fb, "_measurements", return_value=self.measured()):
            with self.assertRaisesRegex(fb.ForceError, "P90"):
                self.reserve("validation", 3, walltime_hours=0.2)

    def test_selection_receipt_flags_without_raw_samples_rejected(self):
        settings = fb._settings(self.config, "pilot", self.spec)
        path = self.run / "selection.json"
        record = {"schema_version":1, "accepted_unitcell_sha256":core.sha256_path(self.final / "unitcell.in"),
            "selected_settings_sha256":core.canonical_sha256(settings), "preflight_yaml_sha256":core.sha256_path(self.dataset / "phono3py_disp.yaml"),
            "audit_backend_sha256":"a"*64, "pass":True, "force_accuracy_pass":True, "amplitude_pass":True}
        record["analysis_sha256"] = core.canonical_sha256(record)
        self.dump(path, record)
        # Simulate an available matching external audit backend; no fake pass
        # receipt can replace the required healthy raw sample references.
        with patch.object(fb, "_match"), patch(
            "pilot_evidence.replay_selection_receipt",
            return_value={
                "healthy": True,
                "pass": True,
                "analysis_sha256": record["analysis_sha256"],
                "source_sha256": {},
            },
        ):
            with self.assertRaisesRegex(fb.ForceError, "actual force samples"):
                fb.validate_selection_evidence(
                    path,
                    self.config_path,
                    self.config,
                    settings,
                    self.run,
                    self.dataset,
                )

    def test_runtime_budget_receipt_tampering_rejected(self):
        prepared = self.prepare()
        Path(prepared["budget_receipt"]).write_text("{}")
        with self.assertRaisesRegex(fb.ForceError, "altered evidence"):
            fb.run_force_task(self.config_path, self.run, task_map=Path(prepared["task_map"]), task_id=0,
                attempt_path=self.run / "attempt", compute_guard=lambda:None)

    def test_runtime_cannot_start_third_concurrent_task(self):
        prepared = self.prepare()
        manifest = core.load_json(Path(prepared["manifest"]))
        receipt = core.load_json(Path(prepared["budget_receipt"]))
        fb._claim_execution(self.run, manifest, receipt, 0, self.run / "active0", None)
        fb._claim_execution(self.run, manifest, receipt, 1, self.run / "active1", None)
        with self.assertRaisesRegex(fb.ForceError, "concurrency limit"):
            fb._claim_execution(self.run, manifest, receipt, 2, self.run / "active2", None)

    def test_one_technical_retry_requires_raw_scheduler_evidence(self):
        prepared = self.prepare()
        manifest = core.load_json(Path(prepared["manifest"]))
        receipt = core.load_json(Path(prepared["budget_receipt"]))
        with patch.dict(os.environ, {"SLURM_JOB_ID":"123"}):
            fb._claim_execution(self.run, manifest, receipt, 0, self.run / "first", None)
        with self.assertRaisesRegex(fb.ForceError, "scheduler evidence"):
            fb._claim_execution(self.run, manifest, receipt, 0, self.run / "second", None)
        accounting = self.run / "sacct.tsv"
        accounting.write_text("JobIDRaw|State\n123|NODE_FAIL\n")
        evidence = self.run / "technical_failure.json"
        self.dump(evidence, {"accounting_path":str(accounting), "accounting_sha256":core.sha256_path(accounting)})
        retry = fb._claim_execution(self.run, manifest, receipt, 0, self.run / "second", evidence)
        self.assertEqual(retry["technical_retry_count"], 1)
        with self.assertRaisesRegex(fb.ForceError, "one technical retry"):
            fb._claim_execution(self.run, manifest, receipt, 0, self.run / "third", evidence)


if __name__ == "__main__":
    unittest.main()

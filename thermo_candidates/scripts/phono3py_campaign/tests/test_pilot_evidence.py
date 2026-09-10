"""Synthetic original-file/receipt-chain tests. Never execute QE or phono3py."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import campaign as core
import force_backend as fb
import pilot_analysis as pa
import pilot_evidence as pe
import test_force_backend as forces
import test_pilot_dataset as datasets
import test_pilot_analysis as numerical


class PilotEvidenceTests(unittest.TestCase):
    dump = forces.ForceBackendTests.dump
    fragment = forces.ForceBackendTests.fragment
    refresh_preflight = forces.ForceBackendTests.refresh_preflight
    refresh = datasets.PilotDatasetTests.refresh
    fake_process = forces.ForceBackendTests.fake_process

    def setUp(self):
        datasets.PilotDatasetTests.setUp(self)
        result = core.load_json(self.dataset / "preflight_result.json")
        result["selection_eligible"] = True
        self.dump(self.dataset / "preflight_result.json", result)
        inventory = core.load_json(self.inventory)
        inventory["results"] = [result]
        self.dump(self.inventory, inventory)
        self.prepare = lambda spec=None, name="signed": datasets.PilotDatasetTests.prepare(self, spec, name)
        result = self.prepare()
        self.signed = Path(result["dataset_dir"])
        self.dataset_refs = {"h03": {"manifest_path": str(self.signed / "pilot_dataset_manifest.json"),
                                    "manifest_sha256": result["manifest_sha256"]}}
        pilot = {**self.probe, "ecutwfc_Ry":80, "ecutrho_Ry":640, "conv_thr_Ry":1e-10,
                 "kmesh":[2,2,2], "displacement_ids":[1,3], "duplicate_displacement_ids":[1,3], "pristine_repetitions":2}
        self.bundle = fb.prepare_force(self.config_path, self.run,
            preflight_inventory=self.signed / "preflight_inventory.json", dataset_dir=self.signed,
            output_dir=self.run / "force" / "bundle", pseudo_dir=self.pseudo, mode="pilot", pilot_spec=pilot,
            pilot_dataset_manifest_sha256=result["manifest_sha256"],
            resource_request={"phase":"initial", "mpi_ranks":32, "walltime_hours":1, "max_concurrency":2})
        self.force_manifest = Path(self.bundle["manifest"])
        self.sample_refs = {}
        with patch.object(core, "run_process", side_effect=self.fake_process):
            for task_id, name in enumerate(("pristine", "pristine-repeat", "plus", "pp", "repeat", "pp-repeat")):
                attempt = self.run / "attempts" / name
                with patch.dict(os.environ, {"SLURM_JOB_ID":str(500+task_id)}):
                    fb.run_force_task(self.config_path, self.run, task_map=Path(self.bundle["task_map"]),
                                      task_id=task_id, attempt_path=attempt, compute_guard=lambda:None)
                self.sample_refs[name] = {"dataset_id":"h03", "manifest_path":str(self.force_manifest),
                    "manifest_sha256":core.sha256_path(self.force_manifest), "result_path":str(attempt / "result.json"),
                    "result_sha256":core.sha256_path(attempt / "result.json")}

    def audit(self, **kwargs):
        return pe.audit_pilot_samples(self.config_path, self.run, dataset_manifests=self.dataset_refs,
                                       sample_references=self.sample_refs, **kwargs)

    def target(self):
        return {"candidate_dir":str(self.dataset), "inventory_path":str(self.inventory),
                "inventory_sha256":core.sha256_path(self.inventory),
                "yaml_sha256":core.sha256_path(self.dataset / "phono3py_disp.yaml")}

    def test_raw_force_geometry_site_roles_and_independent_duplicates(self):
        report = self.audit()
        self.assertFalse(report["scientific_selection_evaluated"])
        samples = report["audited_samples"]
        self.assertEqual(samples["pristine"]["displacements_bohr"], [[0.0]*3]*2)
        self.assertAlmostEqual(samples["plus"]["displacements_bohr"][0][0], self.probe["amplitude_bohr"])
        self.assertEqual(samples["pp"]["forces_ry_bohr"], [[0.01,0,0],[-0.01,0,0]])
        self.assertEqual(samples["pp"]["pair_shell_id"], "X-X")
        self.assertAlmostEqual(samples["pp"]["pair_distances_bohr"][0], 0.4)
        self.assertEqual(samples["plus"]["atom_order"][0]["site_id"], "site-00001")
        self.assertEqual(samples["plus"]["input_sha256"], samples["repeat"]["input_sha256"])
        self.assertNotEqual(samples["plus"]["independent_run_id"], samples["repeat"]["independent_run_id"])
        self.assertEqual(report["sample_sha256"]["plus"], pa.canonical_sha256(samples["plus"]))

    def test_no_caller_supplied_numerical_claims_or_aliased_execution(self):
        self.sample_refs["plus"]["forces_ry_bohr"] = [[0,0,0]]*2
        with self.assertRaisesRegex(pe.PilotEvidenceError, "paths/hashes only"):
            self.audit()
        del self.sample_refs["plus"]["forces_ry_bohr"]
        self.sample_refs["fake_repeat"] = copy.deepcopy(self.sample_refs["plus"])
        with self.assertRaisesRegex(pe.PilotEvidenceError, "relabeled"):
            self.audit()

    def test_unhealthy_output_and_raw_hash_mutation(self):
        output = self.run / "attempts/plus/scf.out"
        output.write_text(output.read_text() + "Error in routine seqopn\n")
        with self.assertRaisesRegex(pe.PilotEvidenceError, "output hash"):
            self.audit()

    def test_immutable_execution_ledger_required(self):
        attempt = self.run / "attempts/plus"
        launch = core.load_json(attempt / "launch.json")
        launch["budget_execution_claim"]["job_id"] = "999"
        self.dump(attempt / "launch.json", launch)
        with self.assertRaisesRegex(pe.PilotEvidenceError, "claim identity"):
            self.audit()

    def test_rehashed_settings_claim_cannot_override_raw_qe_input(self):
        # Update every ordinary receipt hash to a new force manifest, but leave
        # the raw input at its original physical setting. Independent regeneration
        # must reject this, even though the receipt adapter itself remains healthy.
        manifest = core.load_json(self.force_manifest)
        manifest["settings"]["ecutwfc_Ry"] = 90
        manifest["pilot_spec"]["ecutwfc_Ry"] = 90
        self.dump(self.force_manifest, manifest)
        digest = core.sha256_path(self.force_manifest)
        for reference in self.sample_refs.values():
            reference["manifest_sha256"] = digest
            attempt = Path(reference["result_path"]).parent
            for filename,key in (("force_claim.json","manifest_sha256"),("launch.json","force_manifest_sha256"),
                                 ("result.json","force_manifest_sha256")):
                value = core.load_json(attempt / filename)
                value[key] = digest
                self.dump(attempt / filename, value)
            reference["result_sha256"] = core.sha256_path(attempt / "result.json")
        with self.assertRaisesRegex(pe.PilotEvidenceError, "independently regenerated"):
            self.audit()

    def test_missing_result_manifest_or_dataset_hash_fails_closed(self):
        self.sample_refs["plus"]["result_sha256"] = "0"*64
        with self.assertRaisesRegex(pe.PilotEvidenceError, "altered evidence"):
            self.audit()

    def test_geometry_roles_must_match_one_probe_not_only_arithmetic(self):
        samples = self.audit()["audited_samples"]
        study = {"amplitude_probes":[{"kind":"single", "sets":[{"plus":"plus", "minus":"repeat"}]}]}
        with self.assertRaisesRegex(pe.PilotEvidenceError, "regenerated geometry probe"):
            pe._check_probe_roles(study, samples)

    def test_full_target_must_be_separate_eligible_enumeration(self):
        target = {"candidate_dir":str(self.signed), "inventory_path":str(self.signed / "preflight_inventory.json"),
                  "inventory_sha256":core.sha256_path(self.signed / "preflight_inventory.json"),
                  "yaml_sha256":core.sha256_path(self.signed / "phono3py_disp.yaml")}
        settings = core.load_json(self.force_manifest)["settings"]
        with self.assertRaisesRegex(pe.PilotEvidenceError, "eligible complete full preflight"):
            self.audit(target_preflight=target, selected_settings=settings)

    def test_target_hash_cannot_be_invented(self):
        target = {"candidate_dir":str(self.dataset), "inventory_path":str(self.inventory),
                  "inventory_sha256":core.sha256_path(self.inventory), "yaml_sha256":"0"*64}
        with self.assertRaisesRegex(pe.PilotEvidenceError, "altered evidence"):
            self.audit(target_preflight=target, selected_settings=core.load_json(self.force_manifest)["settings"])

    def test_full_target_lineage_is_independent_of_subset_yaml_hash(self):
        report = self.audit(target_preflight=self.target(), selected_settings=core.load_json(self.force_manifest)["settings"])
        for sample in report["audited_samples"].values():
            self.assertEqual(sample["target_preflight_yaml_sha256"], self.target()["yaml_sha256"])
            self.assertNotEqual(sample["dataset_sha256"], sample["target_preflight_yaml_sha256"])

    def test_parent_mutation_cannot_be_hidden_by_fresh_target_hashes(self):
        value = core.load_json(self.dataset / "preflight_result.json")
        value["extra_claim"] = True
        self.dump(self.dataset / "preflight_result.json", value)
        inventory = core.load_json(self.inventory)
        inventory["results"] = [value]
        self.dump(self.inventory, inventory)
        with self.assertRaisesRegex(pe.PilotEvidenceError, "altered evidence"):
            self.audit(target_preflight=self.target(), selected_settings=core.load_json(self.force_manifest)["settings"])

    def test_replay_rejects_claim_without_original_file_study(self):
        path = self.run / "fake-selection.json"
        self.dump(path, {"raw_audit_backend_sha256":core.sha256_path(Path(pe.__file__)), "pass":True})
        with self.assertRaisesRegex(pe.PilotEvidenceError, "non-replayable"):
            pe.replay_selection_receipt(self.config_path, self.run, path)

    def test_complete_raw_study_replays_and_rehashed_fabricated_pass_is_rejected(self):
        # Complete three-amplitude input coverage, with deliberately constant
        # synthetic forces: the numerical result must remain below resolution.
        policy = numerical.fixture()[2]
        policy["amplitude_pilot"]["representative_species"] = ["X"]
        policy["amplitude_pilot"]["representative_pair_shells"] = ["X-X"]
        policy["basis_and_scf_pilot"]["k_point_candidates"] = [{"mesh":[2,2,2], "role":"reference"}]
        self.config["force_and_amplitude_validation"] = policy
        self.dump(self.config_path, self.config)
        accounting = self.run / "synthetic-accounting.psv"
        accounting.write_text("JobIDRaw|ElapsedRaw|AllocCPUS|MaxRSS|State\n"
            + "".join(f"{500+i}|10|32|10M|COMPLETED\n" for i in range(6)))
        timing = [{"sample":self.sample_refs[name], "accounting_path":str(accounting),
                   "accounting_sha256":core.sha256_path(accounting), "job_id":str(500+i)}
                  for i,name in ((0,"pristine"),(2,"plus"),(3,"pp"))]
        references, manifests, groups = {}, {}, []
        for amplitude in (0.02,0.03,0.04):
            label = str(amplitude)
            spec = {**self.probe, "amplitude_angstrom":amplitude,
                    "amplitude_bohr":amplitude/core.BOHR_TO_ANGSTROM}
            prepared = self.prepare(spec, name="full-"+label)
            folder = Path(prepared["dataset_dir"])
            manifests[label] = {"manifest_path":str(folder / "pilot_dataset_manifest.json"),
                                "manifest_sha256":prepared["manifest_sha256"]}
            pilot = {**spec, "ecutwfc_Ry":80, "ecutrho_Ry":640, "conv_thr_Ry":1e-10,
                     "kmesh":[2,2,2], "displacement_ids":list(range(1,7)), "duplicate_displacement_ids":[1,3]}
            bundle = fb.prepare_force(self.config_path,self.run,preflight_inventory=folder / "preflight_inventory.json",
                dataset_dir=folder,output_dir=self.run / ("force-"+label),pseudo_dir=self.pseudo,mode="pilot",pilot_spec=pilot,
                pilot_dataset_manifest_sha256=prepared["manifest_sha256"],
                resource_request={"phase":"validation","mpi_ranks":32,"walltime_hours":1,"max_concurrency":2,
                                  "timing_evidence":timing})
            manifest_path = Path(bundle["manifest"])
            names = ("pristine","plus","minus","pp","pm","mp","mm","single-repeat","mixed-repeat")
            with patch.object(core,"run_process",side_effect=self.fake_process):
                for task_id,name in enumerate(names):
                    attempt = self.run / "attempts" / (label+"-"+name)
                    with patch.dict(os.environ,{"SLURM_JOB_ID":str(1000+int(amplitude*100)*10+task_id)}):
                        fb.run_force_task(self.config_path,self.run,task_map=Path(bundle["task_map"]),task_id=task_id,
                                          attempt_path=attempt,compute_guard=lambda:None)
                    references[label+"-"+name] = {"dataset_id":label,"manifest_path":str(manifest_path),
                        "manifest_sha256":core.sha256_path(manifest_path),"result_path":str(attempt / "result.json"),
                        "result_sha256":core.sha256_path(attempt / "result.json")}
            groups.append({"h_angstrom":amplitude,"h_bohr":spec["amplitude_bohr"],
                           **{name:label+"-"+name for name in names}})
        selected = core.load_json(self.force_manifest)["settings"]
        study = {"schema_version":1,"rationale":"synthetic constant forces must not pass",
            "dataset_manifests":manifests,"samples":references,"selected_settings":selected,
            "reference_settings":copy.deepcopy(selected),"target_preflight":self.target(),
            "force_comparisons":[{"candidate":"0.03-plus","reference":"0.03-plus",
                "candidate_pristine":"0.03-pristine","reference_pristine":"0.03-pristine",
                "candidate_duplicate":"0.03-single-repeat","reference_duplicate":"0.03-single-repeat"}],
            "amplitude_probes":[{"kind":"single","sets":[{**g,"duplicate":g["single-repeat"]} for g in groups]},
                                {"kind":"mixed","pair_shell_id":"X-X", "sets":[{**g,"duplicate":g["mixed-repeat"]} for g in groups]}]}
        path = self.run / "derived-selection.json"
        written = pe.write_selection_receipt(self.config_path,self.run,study=study,output_path=path)
        self.assertFalse(written["pass"])
        replay = pe.replay_selection_receipt(self.config_path,self.run,path,
                                             expected_receipt_sha256=written["receipt_sha256"])
        self.assertTrue(replay["healthy"])
        self.assertFalse(replay["pass"])
        fabricated = core.load_json(path)
        fabricated["pass"] = True
        fabricated.pop("analysis_sha256")
        fabricated["analysis_sha256"] = pa.canonical_sha256(fabricated)
        self.dump(path,fabricated)
        with self.assertRaisesRegex(pe.PilotEvidenceError,"differs from replay"):
            pe.replay_selection_receipt(self.config_path,self.run,path)


if __name__ == "__main__":
    unittest.main()

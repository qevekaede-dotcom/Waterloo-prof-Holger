"""Synthetic structure/provenance tests only; never execute QE or phono3py."""
import copy
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import campaign as core
import force_backend as fb
import pilot_dataset as pd
import test_force_backend as fixtures

try:
    import spglib as real_spglib
except ImportError:
    real_spglib = None


class PilotDatasetTests(unittest.TestCase):
    dump = fixtures.ForceBackendTests.dump
    fragment = fixtures.ForceBackendTests.fragment
    refresh_preflight = fixtures.ForceBackendTests.refresh_preflight

    def setUp(self):
        fixtures.ForceBackendTests.setUp(self)
        self.config["material"]["expected_spacegroup_number"] = 2
        self.config["software"] = {"phono3py_version": "4.4.0"}
        self.config["symmetry_validation"] = {"strictest_required_matching_symprec_angstrom": 1e-6}
        self.config["tight_relax"] = {"ecutwfc_ry": 80, "ecutrho_ry": 640,
            "conv_thr_ry": 1e-10, "kmesh": [2,2,2], "kmesh_shift": [0,0,0]}
        self.config["displacements"].update(hard_cap=32, amplitude_angstrom=0.03,
            amplitude_bohr=0.03/core.BOHR_TO_ANGSTROM)
        self.config["force_and_amplitude_validation"]["amplitude_pilot"] = {
            "displacement_distance_candidates": [{"displacement_distance_angstrom": h,
                "displacement_distance_cli_bohr": h/core.BOHR_TO_ANGSTROM} for h in (0.02,0.03,0.04)],
            "representative_pair_shells": ["X-X"]}
        self.probe = {"schema_version": 1, "rationale": "synthetic signed boundary probes",
            "supercell_id": "s", "cutoff_id": "c", "amplitude_angstrom": 0.03,
            "amplitude_bohr": 0.03/core.BOHR_TO_ANGSTROM,
            "singles": [{"id": "a", "atom": 1, "direction_cartesian": [1,0,0]}],
            "mixed": [{"id": "ab", "first": {"atom": 1, "direction_cartesian": [1,0,0]},
                "second": {"atom": 2, "direction_cartesian": [0,1,0]}, "pair_shell_id": "X-X"}],
            "coverage": {"site_ids": {"site-00001": "covered"}, "pair_shell_ids": {"X-X": "covered"}}}
        self.data["supercell"] = {"lattice": [[10,0,0],[3,9,0],[2,1,8]],
            "points": [{"symbol": "X", "coordinates": [0.998,0,0]},
                       {"symbol": "X", "coordinates": [0.038,0,0]}]}
        self.data["unit_cell"] = copy.deepcopy(self.data["supercell"])
        h = self.probe["amplitude_bohr"]
        self.data["displacement_pairs"] = [{"atom": 1, "displacement_id": 1,
            "displacement": [h,0,0], "paired_with": [{"atom": 2, "included": True,
                "displacement_ids": [2], "displacements": [[0,h,0]], "pair_distance": 0.4}]}]
        for index, offsets in ((0,[]), (1,[(1,[h,0,0])]), (2,[(1,[h,0,0]),(2,[0,h,0])])):
            name = "supercell.in" if index == 0 else f"supercell-{index:05d}.in"
            (self.dataset/name).write_text(pd._fragment_text(self.data, self.unitcell, offsets))
        self.unitcell = fb._fragment(self.dataset/"supercell.in", pd._settings(self.config, self.probe), self.pseudo)
        for path in (self.dataset/"unitcell.in", self.final/"unitcell.in", self.accepted/"relax.in", self.accepted/"pristine.in"):
            path.write_text(self.unitcell)
        self.dump(self.final/"gate.json", {"pass": True, "final_unitcell_sha256": core.sha256_path(self.final/"unitcell.in")})
        execution = core.load_json(self.accepted/"execution_manifest.json")
        for name,key in (("relax.in","relax_input_sha256"),("pristine.in","pristine_input_sha256")):
            execution[key] = core.sha256_path(self.accepted/name)
        self.dump(self.accepted/"execution_manifest.json", execution)
        provenance = core.load_json(self.final/"provenance.json")
        provenance["execution_manifest_sha256"] = core.sha256_path(self.accepted/"execution_manifest.json")
        self.dump(self.final/"provenance.json", provenance)
        run = core.load_json(self.run/"run_manifest.json")
        run["source_qe_sha256"] = core.sha256_path(self.accepted/"relax.in")
        self.dump(self.run/"run_manifest.json", run)
        self.dump(self.config_path, self.config)
        self.refresh()
        self.fake_spglib = SimpleNamespace(__version__="synthetic-test-double",
            get_symmetry_dataset=lambda cell, symprec: SimpleNamespace(number=2, equivalent_atoms=[0,0]))
        patch.dict(sys.modules, {"spglib": self.fake_spglib}).start()

    def refresh(self):
        self.dump(self.dataset/"phono3py_disp.yaml", self.data)
        self.refresh_preflight()
        inventory = core.load_json(self.inventory)
        inventory["preflight_complete"] = True
        inventory["requested_scope_complete"] = True
        inventory["full_config_preflight_complete"] = True
        self.dump(self.inventory, inventory)

    def prepare(self, spec=None, name="signed"):
        return pd.prepare_pilot_dataset(self.config_path, self.run, candidate_dir=self.dataset,
            preflight_inventory=self.inventory, output_dir=self.run/name, probe_spec=spec or self.probe)

    def test_complete_numeric_ids_mixed_signs_and_force_consumer(self):
        result = self.prepare()
        folder = Path(result["dataset_dir"])
        data = fb._yaml(folder/"phono3py_disp.yaml")
        self.assertEqual([x["displacement_id"] for x in data["displacement_pairs"]], [1,2])
        self.assertEqual(core.analyze_displacement_yaml(data)["included_displacement_ids"], list(range(1,7)))
        roles = result["geometry_plan"]["probes"]
        self.assertEqual(roles[0]["displacement_ids"], {"plus":1,"minus":2})
        self.assertEqual(roles[1]["displacement_ids"], {"pp":3,"pm":4,"mp":5,"mm":6})
        texts,_ = fb._dataset_inputs(folder, pd._settings(self.config, self.probe), self.pseudo, self.config)
        self.assertEqual(sorted(texts), list(range(7)))
        # Cartesian x crossing the periodic boundary is reconstructed with + sign.
        parsed = fb.parse_qe_input(texts[1])
        self.assertLess(parsed.atomic_positions[0].coordinates[0], 0.01)
        self.assertAlmostEqual(roles[1]["pair_distance_bohr"],0.4)
        self.assertFalse(result["geometry_plan"]["scientific_coverage_established"])
        pilot = {**self.probe, "ecutwfc_Ry":80,"ecutrho_Ry":640,"conv_thr_Ry":1e-10,
                 "kmesh":[2,2,2], "displacement_ids":[1,3], "duplicate_displacement_ids":[1,3], "pristine_repetitions":2}
        bundle = fb.prepare_force(self.config_path,self.run,preflight_inventory=folder/"preflight_inventory.json",
            dataset_dir=folder,output_dir=self.run/"forces",pseudo_dir=self.pseudo,mode="pilot",pilot_spec=pilot,
            pilot_dataset_manifest_sha256=result["manifest_sha256"],
            resource_request={"phase":"initial","mpi_ranks":32,"walltime_hours":1,"max_concurrency":2})
        self.assertEqual(bundle["task_count"],6)
        from submit import SubmissionContext, validate_force_bundle
        context = SubmissionContext(config_path=self.config_path.resolve(), run_dir=self.run.resolve(),
            config=self.config, manifest=core.load_json(self.run/"run_manifest.json"), config_sha256=core.sha256_path(self.config_path))
        submitted = validate_force_bundle(context, Path(bundle["task_map"]))
        self.assertEqual(submitted[1],6)
        self.assertEqual(submitted[4]["signed_pilot_dataset"]["expected_manifest_sha256"],result["manifest_sha256"])

    def test_reuses_same_geometry_without_duplicate_yaml_ids(self):
        spec = copy.deepcopy(self.probe)
        spec["singles"].append({**spec["singles"][0],"id":"repeat"})
        spec["mixed"].append({**spec["mixed"][0],"id":"repeat-pair"})
        result = self.prepare(spec)
        self.assertEqual(result["geometry_plan"]["reused_geometry_ids"],list(range(1,7)))

    def test_tilted_cell_search_is_not_fractional_rounding(self):
        cell = [[10,0,0],[9.9,0.1,0],[0,0,10]]
        actual = pd.minimum_image_bohr([0.49,0.49,0],cell)
        self.assertLess(math.hypot(*actual),0.3)
        self.assertGreater(math.hypot(*pd._cart([0.49,0.49,0],cell)),9)
        shifted = pd.minimum_image_bohr([4.49,-2.51,2],cell)
        self.assertTrue(pd._near(actual,shifted))

    def test_hash_tampering_and_wrong_trusted_manifest(self):
        result = self.prepare()
        folder = Path(result["dataset_dir"])
        with self.assertRaisesRegex(pd.PilotDatasetError,"altered evidence"):
            pd.audit_pilot_dataset(folder,expected_manifest_sha256="0"*64)
        with (folder/"supercell-00004.in").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(pd.PilotDatasetError,"altered evidence"):
            pd.audit_pilot_dataset(folder,expected_manifest_sha256=result["manifest_sha256"])

    def test_altered_parent_and_accepted_evidence(self):
        for path in (self.dataset/"phono3py_disp.yaml",self.accepted/"pristine.out",self.inventory):
            old = path.read_text()
            if path == self.inventory:
                result = self.prepare(name="before-parent-mutation")
                path.write_text(old+" ")
                with self.assertRaisesRegex(pd.PilotDatasetError,"altered evidence"):
                    pd.audit_pilot_dataset(result["dataset_dir"],expected_manifest_sha256=result["manifest_sha256"])
            else:
                path.write_text(old+" ")
                with self.assertRaisesRegex(pd.PilotDatasetError,"altered evidence"):
                    self.prepare()
            path.write_text(old)

    def test_targeted_subset_inventory_cannot_seed_pilot_dataset(self):
        inventory = core.load_json(self.inventory)
        inventory["preflight_complete"] = False
        inventory["requested_scope_complete"] = True
        inventory["full_config_preflight_complete"] = False
        self.dump(self.inventory, inventory)
        with self.assertRaisesRegex(
            pd.PilotDatasetError, "full configured base preflight"
        ):
            self.prepare(name="blocked-partial-preflight")

    def test_amplitude_unit_and_direction_fail_closed(self):
        for key,value in (("amplitude_angstrom",0.025),("amplitude_bohr",0.03)):
            spec = copy.deepcopy(self.probe); spec[key] = value
            with self.assertRaisesRegex(pd.PilotDatasetError,"amplitude"):
                self.prepare(spec)
        spec = copy.deepcopy(self.probe)
        spec["singles"][0]["direction_cartesian"] = [2,0,0]
        with self.assertRaisesRegex(pd.PilotDatasetError,"unit vector"):
            self.prepare(spec)
        self.data["physical_unit"]["length"] = "angstrom"; self.refresh()
        with self.assertRaisesRegex(pd.PilotDatasetError,"length"):
            self.prepare()

    def test_wrong_id_and_atom_indices_rejected(self):
        for index in (True,0,3):
            spec = copy.deepcopy(self.probe); spec["singles"][0]["atom"] = index
            with self.assertRaisesRegex(pd.PilotDatasetError,"atom"):
                self.prepare(spec)
        self.data["displacement_pairs"][0]["displacement_id"] = 9; self.refresh()
        with self.assertRaisesRegex(pd.PilotDatasetError,"1..N"):
            self.prepare()

    def test_boolean_and_reordered_schema_ids_rejected(self):
        base = copy.deepcopy(self.data)
        base["displacement_pairs"][0]["displacement_id"] = True
        with self.assertRaisesRegex(pd.PilotDatasetError,"integer"):
            pd.build_pilot_geometry(base,self.unitcell,self.config,self.probe)
        data,_,_ = pd.build_pilot_geometry(self.data,self.unitcell,self.config,self.probe)
        data["displacement_pairs"].reverse()
        with self.assertRaisesRegex(pd.PilotDatasetError,"parser order"):
            pd._type1_inventory(data)

    def test_wrong_mixed_sign_rejected_by_independent_geometry_audit(self):
        result = self.prepare()
        folder = Path(result["dataset_dir"])
        data,_,offsets = pd.build_pilot_geometry(self.data,self.unitcell,self.config,self.probe)
        # Copy pp into pm: even matching labels, cell and atom count cannot pass.
        (folder/"supercell-00004.in").write_text((folder/"supercell-00003.in").read_text())
        with self.assertRaisesRegex(pd.PilotDatasetError,"does not reproduce"):
            pd._audit_geometry(folder,self.config,self.probe,data,offsets)

    def test_reverse_pair_reuses_four_signed_geometries(self):
        spec = copy.deepcopy(self.probe)
        old = spec["mixed"][0]
        spec["mixed"].append({**old,"id":"ba","first":old["second"],"second":old["first"]})
        result = self.prepare(spec)
        first,second = result["geometry_plan"]["probes"][1:]
        self.assertEqual(set(first["displacement_ids"].values()),set(second["displacement_ids"].values()))
        self.assertEqual(first["displacement_ids"]["pm"],second["displacement_ids"]["mp"])

    def test_distinct_atom_pair_cutoff_and_schema(self):
        spec = copy.deepcopy(self.probe); spec["mixed"][0]["second"]["atom"] = 1
        with self.assertRaisesRegex(pd.PilotDatasetError,"different atoms"):
            self.prepare(spec)
        config = copy.deepcopy(self.config)
        config["displacements"]["cutoff_candidates"][0].update(cutoff_pair_distance_cli_bohr=0.3,
            cutoff_pair_distance_angstrom=0.3*core.BOHR_TO_ANGSTROM)
        base = copy.deepcopy(self.data); base["displacement_pair_info"]["cutoff_pair_distance"] = 0.3
        with self.assertRaisesRegex(pd.PilotDatasetError,"outside selected cutoff"):
            pd.build_pilot_geometry(base,self.unitcell,config,self.probe)
        config["software"]["phono3py_version"] = "future"
        with self.assertRaisesRegex(pd.PilotDatasetError,"schema"):
            pd.build_pilot_geometry(base,self.unitcell,config,self.probe)

    def test_site_classes_are_derived_and_coverage_explicit(self):
        self.fake_spglib.get_symmetry_dataset = lambda cell,symprec: SimpleNamespace(number=2,equivalent_atoms=[0,1])
        with self.assertRaisesRegex(pd.PilotDatasetError,"site_ids coverage"):
            self.prepare()
        spec = copy.deepcopy(self.probe); spec["coverage"]["site_ids"]["site-00002"] = "not_covered"
        result = self.prepare(spec)
        self.assertEqual(result["geometry_plan"]["symmetry"]["site_ids"],["site-00001","site-00002"])
        self.assertFalse(result["geometry_plan"]["scientific_coverage_established"])

    def test_same_element_atom_order_and_cell_tampering_detected(self):
        base = copy.deepcopy(self.data)
        base["unit_cell"]["points"].reverse()
        with self.assertRaisesRegex(pd.PilotDatasetError,"order/geometry"):
            pd.build_pilot_geometry(base,self.unitcell,self.config,self.probe)
        base = copy.deepcopy(self.data); base["supercell"]["lattice"][1][0] += 0.1
        with self.assertRaisesRegex(pd.PilotDatasetError,"M transpose"):
            pd.build_pilot_geometry(base,self.unitcell,self.config,self.probe)

    def test_immutable_destination_and_all_three_amplitudes(self):
        for h in (0.02,0.03,0.04):
            spec = {**self.probe,"amplitude_angstrom":h,"amplitude_bohr":h/core.BOHR_TO_ANGSTROM}
            self.prepare(spec,name=str(h))
        self.prepare()
        with self.assertRaisesRegex(pd.PilotDatasetError,"immutable"):
            self.prepare()

    @unittest.skipIf(real_spglib is None, "spglib unavailable; no dependency installation for synthetic tests")
    def test_real_spglib_on_synthetic_structure_when_available(self):
        with patch.dict(sys.modules, {"spglib": real_spglib}):
            inventory = pd.site_inventory(self.data,self.unitcell,self.config)
        self.assertEqual(inventory["equivalent_atoms_0_based"],[0,0])
        self.assertEqual(inventory["spacegroup_number"],2)


if __name__ == "__main__":
    unittest.main()

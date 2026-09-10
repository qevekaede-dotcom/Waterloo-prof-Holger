"""Synthetic analytical fixtures only; these tests are not material results."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_analysis as pa


def fixture(noise=1e-8, linear=-0.1, mixed=0.2):
    config_path = Path(__file__).resolve().parents[3] / "SrZrS3/phono3py/campaign.json"
    policy = copy.deepcopy(json.loads(config_path.read_text())["force_and_amplitude_validation"])
    policy["amplitude_pilot"]["representative_species"] = ["S"]
    policy["amplitude_pilot"]["representative_pair_shells"] = ["S-S"]
    selected = {"ecutwfc_Ry": 60, "ecutrho_Ry": 480, "kmesh": [2, 2, 2], "conv_thr_Ry": 1e-9}
    reference = {"ecutwfc_Ry": 80, "ecutrho_Ry": 640, "kmesh": [3, 3, 3], "conv_thr_Ry": 1e-10}
    digest = pa.canonical_sha256
    samples = {}
    common = {"accepted_unitcell_sha256": digest("cell"), "supercell_sha256": digest("supercell"),
              "dataset_sha256": digest("dataset"), "raw_audit_backend_sha256": digest("raw-file-auditor"),
              "atom_order": [{"atom_id": str(i), "species": "S", "site_id": "S"+str(i)} for i in range(2)]}

    def add(name, displacement, settings=selected, repeat_of=None):
        value = copy.deepcopy(common)
        value.update(settings=copy.deepcopy(settings), displacements_bohr=displacement,
                     independent_run_id=name, output_sha256=digest("output-"+name), pair_shell_id="S-S")
        x, y = displacement[0][0], displacement[1][0]
        residual = 0.004 if settings == selected else 0.007
        force = residual + linear*(x+y) + mixed*x*y
        value["forces_ry_bohr"] = [[force]*3 for _ in range(2)]
        value["input_sha256"] = digest([displacement, settings])
        if repeat_of is not None:
            value["forces_ry_bohr"] = [[v+noise for v in row] for row in samples[repeat_of]["forces_ry_bohr"]]
        samples[name] = value
        return name

    add("pristine", [[0.0]*3 for _ in range(2)])
    add("ref_pristine", [[0.0]*3 for _ in range(2)], reference)
    probes = []
    for label, kind, atom in (("s0", "single", 0), ("s1", "single", 1), ("pair", "mixed", None)):
        probe = {"kind": kind, "pair_shell_id": "S-S", "sets": []}
        for h_a in (0.02, 0.03, 0.04):
            h = h_a/pa.BOHR_TO_ANGSTROM
            group = {"h_angstrom": h_a, "h_bohr": h, "pristine": "pristine"}
            signs = {"plus": (1,), "minus": (-1,)} if kind == "single" else {"pp": (1, 1), "pm": (1, -1), "mp": (-1, 1), "mm": (-1, -1)}
            for role, sign in signs.items():
                displacement = [[0.0]*3 for _ in range(2)]
                if kind == "single":
                    displacement[atom][0] = sign[0]*h
                else:
                    displacement[0][0], displacement[1][0] = sign[0]*h, sign[1]*h
                group[role] = add(f"{label}-{h_a}-{role}", displacement)
            base = group["plus" if kind == "single" else "pp"]
            group["duplicate"] = add(base+"-repeat", copy.deepcopy(samples[base]["displacements_bohr"]), repeat_of=base)
            probe["sets"].append(group)
        probes.append(probe)
    comparisons = []
    for probe in probes[:2]:
        group = probe["sets"][1]
        c = group["plus"]
        r = add(c+"-ref", copy.deepcopy(samples[c]["displacements_bohr"]), reference)
        rd = add(r+"-repeat", copy.deepcopy(samples[r]["displacements_bohr"]), reference, repeat_of=r)
        comparisons.append({"candidate": c, "reference": r, "candidate_duplicate": group["duplicate"],
                            "reference_duplicate": rd, "candidate_pristine": "pristine", "reference_pristine": "ref_pristine"})
    record = {"schema_version": 1, "accepted_unitcell_sha256": common["accepted_unitcell_sha256"],
              "selected_settings_sha256": digest(selected), "preflight_yaml_sha256": common["dataset_sha256"],
              "audit_backend_sha256": digest("numerical-analysis-backend"), "amplitude_probes": probes,
              "force_comparisons": comparisons,
              "samples": {name: {"manifest_path": name+"/manifest.json", "manifest_sha256": digest(name+"manifest"),
                                  "result_path": name+"/result.json", "result_sha256": digest(name+"result")} for name in samples}}
    return record, samples, policy, selected, reference


def analyze(data, expected=None):
    record, samples, policy, selected, reference = data
    return pa.analyze_pilot(record, samples, policy, selected, reference,
                            expected_sample_sha256=expected or {k: pa.canonical_sha256(v) for k, v in samples.items()})


class PilotAnalysisTests(unittest.TestCase):
    def test_analytical_derivatives_units_subtraction_and_binding(self):
        data = fixture()
        before = copy.deepcopy(data)
        result = analyze(data)
        self.assertEqual(data, before)
        self.assertTrue(result["pass"])
        self.assertTrue(result["force_accuracy_pass"])
        self.assertTrue(result["amplitude_pass"])
        self.assertEqual(result["audit_backend_sha256"], data[0]["audit_backend_sha256"])
        self.assertEqual(result["raw_audit_backend_sha256"], data[1]["pristine"]["raw_audit_backend_sha256"])
        self.assertNotEqual(result["audit_backend_sha256"], result["raw_audit_backend_sha256"])
        for probe in result["amplitude_probes"]:
            expected = -0.1 if probe["kind"] == "single" else 0.2
            for group in probe["sets"]:
                for component in group["derivative"]:
                    self.assertAlmostEqual(component, expected, places=12)
                self.assertEqual(group["unit"], "Ry/bohr^2" if probe["kind"] == "single" else "Ry/bohr^3")
                multiplier = math.sqrt(2) if probe["kind"] == "single" else 2
                self.assertAlmostEqual(group["propagated_numerator_noise_ry_bohr"], multiplier*1e-8, places=15)
        self.assertLess(result["force_comparisons"][0]["rms_difference_ry_bohr"], 1e-17)
        claimed = result.pop("analysis_sha256")
        self.assertEqual(claimed, pa.canonical_sha256(result))

    def test_zero_signal_is_below_resolution_not_relative_failure(self):
        result = analyze(fixture(linear=0.0, mixed=0.0))
        self.assertFalse(result["pass"])
        self.assertEqual(result["force_comparisons"][0]["status"], "below_resolution")
        self.assertIsNone(result["force_comparisons"][0]["relative_rms"])
        self.assertEqual(result["amplitude_probes"][0]["adjacent_changes"][0]["status"], "below_resolution")

    def test_full_target_lineage_keeps_original_subset_hashes(self):
        data = fixture()
        target = pa.canonical_sha256("separately audited full target")
        data[0]["preflight_yaml_sha256"] = target
        for sample in data[1].values():
            sample["target_preflight_yaml_sha256"] = target
        result = analyze(data)
        self.assertTrue(result["pass"])
        self.assertNotEqual(next(iter(data[1].values()))["dataset_sha256"], target)
        next(iter(data[1].values()))["target_preflight_yaml_sha256"] = pa.canonical_sha256("different target")
        with self.assertRaisesRegex(pa.PilotError, "lineage"):
            analyze(data)

    def test_partial_target_lineage_is_not_a_legacy_fallback(self):
        data = fixture()
        next(iter(data[1].values()))["target_preflight_yaml_sha256"] = data[0]["preflight_yaml_sha256"]
        with self.assertRaises(pa.PilotError):
            analyze(data)

    def test_large_noise_blocks_all_gates(self):
        result = analyze(fixture(noise=0.01))
        self.assertFalse(result["pass"])
        self.assertFalse(result["force_accuracy_pass"])
        self.assertFalse(result["amplitude_pass"])
        self.assertEqual(result["force_comparisons"][0]["status"], "below_resolution")

    def test_zero_mixed_signal_cannot_pass_fc3_via_nonzero_d1(self):
        result = analyze(fixture(mixed=0.0))
        self.assertTrue(result["amplitude_probes"][0]["pass"])
        self.assertFalse(result["amplitude_probes"][2]["pass"])
        self.assertFalse(result["pass"])

    def test_duplicate_floor_with_zero_measured_noise(self):
        result = analyze(fixture(noise=0.0))
        group = result["amplitude_probes"][0]["sets"][0]
        self.assertEqual(group["duplicate_rms_ry_bohr"], 0.0)
        self.assertGreater(group["propagated_numerator_noise_ry_bohr"], 0.0)

    def test_mutation_after_audit_is_rejected(self):
        data = fixture()
        expected = {k: pa.canonical_sha256(v) for k, v in data[1].items()}
        data[1]["pristine"]["forces_ry_bohr"][0][0] += 0.1
        with self.assertRaisesRegex(pa.PilotError, "hash mismatch"):
            analyze(data, expected)

    def test_missing_fourth_sign_and_role_reuse(self):
        for mode in ("missing", "reuse", "swapped"):
            with self.subTest(mode=mode):
                data = fixture()
                group = data[0]["amplitude_probes"][2]["sets"][0]
                if mode == "missing":
                    del group["mm"]
                elif mode == "reuse":
                    group["mm"] = group["pp"]
                else:
                    group["mm"], group["pp"] = group["pp"], group["mm"]
                with self.assertRaises(pa.PilotError):
                    analyze(data)

    def test_missing_inequivalent_site_and_pair_shell_coverage(self):
        for index in (1, 2):
            data = fixture()
            del data[0]["amplitude_probes"][index]
            self.assertFalse(analyze(data)["pass"])
        data = fixture()
        data[0]["force_comparisons"].pop()
        self.assertFalse(analyze(data)["force_accuracy_pass"])

    def test_unit_settings_atom_order_backend_and_shell_tampering(self):
        for key in ("unit", "settings", "atom_order", "backend", "shell", "duplicate", "nan"):
            with self.subTest(key=key):
                data = fixture()
                group = data[0]["amplitude_probes"][2]["sets"][0]
                sample = data[1][group["pp"]]
                if key == "unit":
                    group["h_bohr"] = group["h_angstrom"]
                elif key == "settings":
                    sample["settings"]["ecutwfc_Ry"] = 5
                elif key == "atom_order":
                    sample["atom_order"].reverse()
                elif key == "backend":
                    sample["raw_audit_backend_sha256"] = "0"*64
                elif key == "shell":
                    sample["pair_shell_id"] = "uncovered-shell"
                elif key == "duplicate":
                    data[1][group["duplicate"]]["independent_run_id"] = sample["independent_run_id"]
                else:
                    sample["forces_ry_bohr"][0][0] = float("nan")
                with self.assertRaises(pa.PilotError):
                    analyze(data)

    def test_relative_boundary_and_noise_resolution_boundary(self):
        self.assertEqual(pa._relative([10.5], [10.0], 1.0, 0.05)["status"], "pass")
        self.assertEqual(pa._relative([10.50001], [10.0], 1.0, 0.05)["status"], "fail")
        self.assertEqual(pa._relative([10.0], [9.99999], 1.0, 0.05)["status"], "below_resolution")
        self.assertIsNone(pa._relative([0.0], [0.0], 0.0, 0.05)["relative_rms"])

    def test_anharmonic_amplitude_change_fails(self):
        data = fixture()
        group = data[0]["amplitude_probes"][0]["sets"][2]
        for role in ("plus", "minus", "duplicate"):
            sample = data[1][group[role]]
            sign = 1 if role != "minus" else -1
            sample["forces_ry_bohr"] = [[x+sign*0.001 for x in row] for row in sample["forces_ry_bohr"]]
        result = analyze(data)
        self.assertFalse(result["amplitude_pass"])
        self.assertEqual(result["amplitude_probes"][0]["adjacent_changes"][1]["status"], "fail")


if __name__ == "__main__":
    unittest.main()

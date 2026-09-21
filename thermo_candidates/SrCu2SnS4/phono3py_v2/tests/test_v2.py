#!/usr/bin/env python3
"""Focused standard-library tests for the v2 safety boundary."""
import hashlib
import json
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
PREPARE = PACKAGE / "scripts/prepare_v2.py"
PREFLIGHT = PACKAGE / "scripts/preflight_v2.py"
AUDIT = PACKAGE / "scripts/audit_pristine_v2.py"
CONFIG = json.loads((PACKAGE / "campaign.json").read_text())
sys.path.insert(0, str(PACKAGE / "scripts"))
sys.path.insert(0, str(PACKAGE.parents[1] / "scripts/phono3py_campaign"))
from dataset_semantics import inspect_dataset
from qe_output import inspect_force_run


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def scf(pseudo_dir="/tmp/pseudos"):
    return f"""&CONTROL\n tprnfor = .true.,\n pseudo_dir = '{pseudo_dir}',\n/\n&SYSTEM\n ecutrho = 720,\n ecutwfc = 90,\n occupations = 'fixed',\n nosym = .true.,\n noinv = .true.,\n ibrav = 0,\n nat = 96,\n ntyp = 4,\n/\n&ELECTRONS\n conv_thr = 1d-09,\n/\nCELL_PARAMETERS bohr\n 1 0 0\n 0 1 0\n 0 0 1\nATOMIC_SPECIES\nSr 1 Sr_pbe_v1.uspp.F.UPF\nCu 1 Cu.paw.z_11.ld1.psl.v1.0.0-low.upf\nSn 1 Sn_pbe_v1.uspp.F.UPF\nS 1 s_pbe_v1.4.uspp.F.UPF\nATOMIC_POSITIONS crystal\n Sr 0 0 0\nK_POINTS automatic\n 3 3 3 0 0 0\n"""


def make_pseudos(root):
    for filename in CONFIG["qe_force_input_contract"]["pseudopotential_files"].values():
        (root / filename).write_text("pseudo\n")


def make_preflight_fixture(root):
    run = root / "run"; (run / "forces/pristine").mkdir(parents=True); pseudos = root / "pseudos"; pseudos.mkdir(); make_pseudos(pseudos)
    files = [run / "forces/pristine/scf.in"]; files[0].write_text(scf(str(pseudos)))
    for i in range(168):
        path = run / f"forces/disp-{i+1:05d}/scf.in"; path.parent.mkdir(); path.write_text(scf(str(pseudos))); files.append(path)
    inputs = run / "inputs"; inputs.mkdir()
    (inputs / "unitcell.in").write_text("unitcell\n"); (inputs / "supercell.in").write_text("supercell\n")
    vectors = [[0.06, 0, 0] for _ in range(167)]
    dataset = {"phono3py": {"version":"4.3.3","calculator":"qe","symmetry_tolerance":0.001}, "physical_unit":{"length":"au"}, "space_group":{"type":"P3_121","number":152}, "supercell_matrix":[[2,0,0],[0,2,0],[0,0,1]], "unit_cell":{"points":[{}]*24}, "supercell":{"points":[{}]*96}, "displacement_pairs":[{"displacement_id":1,"displacement":[0.06,0,0],"paired_with":[{"included":True,"pair_distance":4.0,"displacement_ids":list(range(2,169)),"displacements":vectors},{"included":False,"pair_distance":8.0,"displacement_ids":[169],"displacements":[[0.06,0,0]]}]}]}
    # Use the production semantic path: the validator reads phono3py YAML
    # through PyYAML, rather than relying on JSON being YAML-compatible.
    (inputs / "phono3py_disp.yaml").write_text(yaml.safe_dump(dataset, sort_keys=False))
    for i in range(1,169): (inputs / f"supercell-{i:05d}.in").write_text("fragment\n")
    semantic = inspect_dataset(inputs); (run / "dataset_semantics.json").write_text(json.dumps(semantic, sort_keys=True))
    manifest = {"config_sha256": digest(PACKAGE / "campaign.json"), "source_unitcell_sha256": CONFIG["source_unitcell"]["sha256"],
                "document_type": "srcu_v2_run_manifest", "preparer_sha256": digest(PREPARE),
                "dataset_semantics_validator_sha256": digest(PACKAGE / "scripts/dataset_semantics.py"),
                "pseudo_dir": str(pseudos),
                "pseudopotential_sha256": {name: digest(pseudos / name) for name in CONFIG["qe_force_input_contract"]["pseudopotential_files"].values()},
                "dataset_sha256": {str((inputs / name).relative_to(run)): digest(inputs / name) for name in ("unitcell.in","supercell.in","phono3py_disp.yaml")}, "dataset_semantics_sha256": digest(run / "dataset_semantics.json"),
                "qe_execution_released": False, "slurm_submission_released": False,
                "input_sha256": {str(p.relative_to(run / "forces")): digest(p) for p in files}}
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    stdout, stderr, code = root / "pristine.out", root / "pristine.stderr", root / "pristine.exit_code"
    stdout.write_text(valid_qe_output()); stderr.write_text(""); code.write_text("0\n")
    audited = subprocess.run([sys.executable, str(AUDIT), "--run-dir", str(run), "--qe-output", str(stdout), "--qe-stderr", str(stderr), "--exit-code", str(code),
                             "--expected-manifest-sha256", digest(run / "run_manifest.json")], text=True, capture_output=True)
    if audited.returncode:
        raise RuntimeError(audited.stderr)
    audit_output = json.loads(audited.stdout)
    if audit_output["pristine_health_sha256"] != digest(run / "health/pristine_health.json"):
        raise RuntimeError("audit did not print the final pristine health SHA-256")
    return run, pseudos


def dataset_data(run):
    return yaml.safe_load((run / "inputs/phono3py_disp.yaml").read_text())


def write_dataset(run, data):
    (run / "inputs/phono3py_disp.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def run_preflight(run, expected_manifest_sha256=None, expected_health_sha256=None):
    expected_manifest_sha256 = expected_manifest_sha256 or digest(run / "run_manifest.json")
    expected_health_sha256 = expected_health_sha256 or digest(run / "health/pristine_health.json")
    return subprocess.run([sys.executable, str(PREFLIGHT), "--run-dir", str(run),
                           "--expected-manifest-sha256", expected_manifest_sha256,
                           "--expected-health-sha256", expected_health_sha256], text=True, capture_output=True)


def rebind_pristine_input_hash(run):
    health_path = run / "health/pristine_health.json"
    health = json.loads(health_path.read_text())
    health["input_sha256"] = digest(run / "forces/pristine/scf.in")
    health_path.write_text(json.dumps(health))


def rebind_health_manifest_anchor(run):
    health_path = run / "health/pristine_health.json"
    health = json.loads(health_path.read_text())
    health["manifest_sha256_anchor"] = digest(run / "run_manifest.json")
    health_path.write_text(json.dumps(health))


def valid_qe_output():
    forces = "\n".join(f"atom {i} type 1 force = 0.0 0.0 0.0" for i in range(1, 97))
    return "Program PWSCF\nconvergence has been achieved\nForces acting on atoms\n" + forces + "\nTotal force = 0.0 Total SCF correction = 0.0\nJOB DONE.\n"


class V2Tests(unittest.TestCase):
    def test_dry_run_is_non_mutating_and_uses_local_unitcell_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "new"
            result = subprocess.run([sys.executable, str(PREPARE), "--run-dir", str(run)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(run.exists())
            self.assertIn("7.5589045", result.stdout)
            self.assertIn('"unitcell.in"', result.stdout)
            self.assertNotIn('"inputs/unitcell.in"', result.stdout)

    def test_prepare_rejects_dangling_run_dir_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_link = root / "linked-run"
            run_link.symlink_to(root / "missing-target", target_is_directory=True)
            result = subprocess.run(
                [sys.executable, str(PREPARE), "--run-dir", str(run_link)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("RUN_DIR must not be a symlink", result.stderr)
            self.assertFalse((root / "missing-target").exists())

    def test_generation_rejects_relative_or_symlinked_pseudo_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp); pseudos = tmp_path / "pseudos"; pseudos.mkdir(); make_pseudos(pseudos)
            relative = subprocess.run([sys.executable, str(PREPARE), "--run-dir", str(tmp_path / "run1"), "--generate-displacements", "--pseudo-dir", "pseudos"], text=True, capture_output=True)
            self.assertNotEqual(relative.returncode, 0)
            linked = tmp_path / "linked"; linked.symlink_to(pseudos)
            symlinked = subprocess.run([sys.executable, str(PREPARE), "--run-dir", str(tmp_path / "run2"), "--generate-displacements", "--pseudo-dir", str(linked)], text=True, capture_output=True)
            self.assertNotEqual(symlinked.returncode, 0)
            bad_file = pseudos / next(iter(CONFIG["qe_force_input_contract"]["pseudopotential_files"].values()))
            replacement = tmp_path / "replacement.upf"; replacement.write_text("pseudo\n")
            bad_file.unlink(); bad_file.symlink_to(replacement)
            linked_file = subprocess.run([sys.executable, str(PREPARE), "--run-dir", str(tmp_path / "run3"), "--generate-displacements", "--pseudo-dir", str(pseudos)], text=True, capture_output=True)
            self.assertNotEqual(linked_file.returncode, 0)

    def test_preflight_accepts_uniform_168_and_rejects_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = make_preflight_fixture(Path(tmp))
            self.assertEqual(run_preflight(run).returncode, 0)
            report = json.loads((run / "preflight_report.json").read_text())
            self.assertEqual(report["manifest_sha256_anchor"], digest(run / "run_manifest.json"))
            self.assertEqual(report["pristine_health_sha256_anchor"], digest(run / "health/pristine_health.json"))
            self.assertNotEqual(run_preflight(run).returncode, 0)

    def test_preflight_rejects_tampered_dataset_parser_and_pseudo(self):
        for target in ("dataset", "dataset_validator", "parser", "pseudo"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                run, pseudos = make_preflight_fixture(Path(tmp))
                if target == "dataset":
                    (run / "inputs/phono3py_disp.yaml").write_text("changed\n")
                elif target == "dataset_validator":
                    manifest_path = run / "run_manifest.json"
                    manifest = json.loads(manifest_path.read_text())
                    manifest["dataset_semantics_validator_sha256"] = "0" * 64
                    manifest_path.write_text(json.dumps(manifest))
                    rebind_health_manifest_anchor(run)
                elif target == "parser":
                    health_path = run / "health/pristine_health.json"; health = json.loads(health_path.read_text()); health["parser_sha256"] = "0" * 64; health_path.write_text(json.dumps(health))
                else:
                    (pseudos / "Sr_pbe_v1.uspp.F.UPF").write_text("changed\n")
                result = run_preflight(run)
                self.assertNotEqual(result.returncode, 0)
                if target == "dataset_validator":
                    self.assertIn("validator fingerprint changed", result.stderr)

    def test_preflight_parses_retained_exit_code_not_only_its_claimed_hash(self):
        for recorded_exit_code, expected_error in (
            (0, "exit-code evidence disagrees"),
            (1, "process exit code is not zero"),
        ):
            with self.subTest(recorded_exit_code=recorded_exit_code), tempfile.TemporaryDirectory() as tmp:
                run, _ = make_preflight_fixture(Path(tmp))
                exit_code = run / "health/evidence/pristine.exit_code"
                exit_code.write_text("1\n")
                health_path = run / "health/pristine_health.json"
                health = json.loads(health_path.read_text())
                health["exit_code_sha256"] = digest(exit_code)
                health["exit_code"] = recorded_exit_code
                health_path.write_text(json.dumps(health))
                result = run_preflight(run)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_preflight_rejects_pseudo_rebind_under_original_reviewed_manifest_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, pseudos = make_preflight_fixture(Path(tmp))
            reviewed_anchor = digest(run / "run_manifest.json")
            pseudo = pseudos / "Sr_pbe_v1.uspp.F.UPF"
            pseudo.write_text("mutated pseudo\n")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["pseudopotential_sha256"][pseudo.name] = digest(pseudo)
            manifest_path.write_text(json.dumps(manifest))
            result = run_preflight(run, reviewed_anchor)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed expected anchor", result.stderr)

    def test_manifest_anchor_requires_lowercase_hex(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = make_preflight_fixture(Path(tmp))
            result = run_preflight(run, "A" * 64)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("64 lowercase hexadecimal", result.stderr)

    def test_health_anchor_requires_lowercase_hex(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = make_preflight_fixture(Path(tmp))
            result = run_preflight(run, expected_health_sha256="A" * 64)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("64 lowercase hexadecimal", result.stderr)

    def test_preflight_rejects_rebound_health_under_original_external_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = make_preflight_fixture(Path(tmp))
            original_health_anchor = digest(run / "health/pristine_health.json")
            stdout = run / "health/evidence/pristine.stdout"
            stdout.write_text(stdout.read_text().replace("0.0 0.0 0.0", "0.0 0.0 0.000001", 1))
            health_path = run / "health/pristine_health.json"
            health = json.loads(health_path.read_text())
            health["qe_output_sha256"] = digest(stdout)
            health["parser_report"] = inspect_force_run(
                stdout, run / "health/evidence/pristine.stderr", 96)
            health["healthy"] = health["parser_report"]["healthy"]
            health["errors"] = health["parser_report"]["errors"]
            health_path.write_text(json.dumps(health))
            result = run_preflight(run, expected_health_sha256=original_health_anchor)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("health SHA-256 does not match", result.stderr)

    def test_preflight_rejects_noncanonical_health_evidence_paths_even_with_rebound_anchor(self):
        substitutions = {
            "parent_escape": "../pristine.stdout",
            "alternative_in_run_path": "health/evidence/alternate.stdout",
        }
        for name, replacement in substitutions.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                run, _ = make_preflight_fixture(Path(tmp))
                health_path = run / "health/pristine_health.json"
                health = json.loads(health_path.read_text())
                health["evidence"]["stdout"] = replacement
                health_path.write_text(json.dumps(health))
                result = run_preflight(run, expected_health_sha256=digest(health_path))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must exactly equal the canonical", result.stderr)

    def test_semantic_validator_rejects_contract_mutations_via_pyyaml(self):
        mutations = {
            "wrong_length_unit": lambda data: data["physical_unit"].update(length="angstrom"),
            "wrong_supercell_matrix": lambda data: data.update(supercell_matrix=[[2, 0, 0], [0, 1, 0], [0, 0, 2]]),
            "wrong_amplitude": lambda data: data["displacement_pairs"][0].update(displacement=[0.05, 0, 0]),
            "included_beyond_cutoff": lambda data: data["displacement_pairs"][0]["paired_with"][0].update(pair_distance=7.7),
            "excluded_within_cutoff": lambda data: data["displacement_pairs"][0]["paired_with"][1].update(pair_distance=7.5),
            "displacement_id_fragment_mismatch": lambda data: data["displacement_pairs"][0]["paired_with"][0].update(displacement_ids=list(range(3, 170))),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                run, _ = make_preflight_fixture(Path(tmp))
                data = dataset_data(run); mutate(data); write_dataset(run, data)
                with self.assertRaisesRegex(ValueError, "unit|matrix|amplitude|cutoff|displacement"):
                    inspect_dataset(run / "inputs")

    def test_preflight_rejects_forged_pristine_parser_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = make_preflight_fixture(Path(tmp))
            health_path = run / "health/pristine_health.json"
            health = json.loads(health_path.read_text())
            health["parser_report"] = {"healthy": True, "errors": [], "forged": "replayed"}
            health_path.write_text(json.dumps(health))
            result = run_preflight(run)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("shared-parser replay differs", result.stderr)

    def test_preflight_rejects_symlinked_run_dir_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, _ = make_preflight_fixture(tmp_path)
            linked_run = tmp_path / "linked-run"; linked_run.symlink_to(run, target_is_directory=True)
            self.assertNotEqual(run_preflight(linked_run).returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, _ = make_preflight_fixture(tmp_path)
            stdout = run / "health/evidence/pristine.stdout"
            replacement = tmp_path / "replacement.stdout"; replacement.write_text(stdout.read_text())
            stdout.unlink(); stdout.symlink_to(replacement)
            self.assertNotEqual(run_preflight(run).returncode, 0)

    def test_preflight_rejects_pseudo_dir_and_species_mapping_swaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, pseudos = make_preflight_fixture(Path(tmp))
            wrong_pseudos = Path(tmp) / "other-pseudos"; wrong_pseudos.mkdir(); make_pseudos(wrong_pseudos)
            for path in (run / "forces").glob("*/scf.in"):
                path.write_text(path.read_text().replace(str(pseudos), str(wrong_pseudos)))
            manifest_path = run / "run_manifest.json"; manifest = json.loads(manifest_path.read_text())
            manifest["input_sha256"] = {str(path.relative_to(run / "forces")): digest(path) for path in (run / "forces").glob("*/scf.in")}
            manifest_path.write_text(json.dumps(manifest))
            rebind_pristine_input_hash(run)
            rebind_health_manifest_anchor(run)
            result = run_preflight(run)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pseudo_dir mismatch", result.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = make_preflight_fixture(Path(tmp))
            pristine = run / "forces/pristine/scf.in"
            pristine.write_text(pristine.read_text().replace("Cu 1 Cu.paw.z_11.ld1.psl.v1.0.0-low.upf", "Cu 1 Sr_pbe_v1.uspp.F.UPF"))
            manifest_path = run / "run_manifest.json"; manifest = json.loads(manifest_path.read_text())
            manifest["input_sha256"]["pristine/scf.in"] = digest(pristine)
            manifest_path.write_text(json.dumps(manifest))
            rebind_pristine_input_hash(run)
            rebind_health_manifest_anchor(run)
            result = run_preflight(run)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("element-to-filename mapping mismatch", result.stderr)

    def test_pristine_audit_requires_stderr_exit_and_uses_final_pwscf_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp); run = tmp_path / "run"; (run / "forces/pristine").mkdir(parents=True)
            pristine = run / "forces/pristine/scf.in"
            pristine.write_text(scf())
            (run / "run_manifest.json").write_text(json.dumps({
                "document_type": "srcu_v2_run_manifest",
                "input_sha256": {"pristine/scf.in": digest(pristine)},
            }) + "\n")
            output, stderr, code = tmp_path / "pristine.out", tmp_path / "pristine.stderr", tmp_path / "exit_code.txt"
            output.write_text(valid_qe_output() + "Program PWSCF\nError in routine final failure\n")
            stderr.write_text(""); code.write_text("0\n")
            result = subprocess.run([sys.executable, str(AUDIT), "--run-dir", str(run), "--qe-output", str(output), "--qe-stderr", str(stderr), "--exit-code", str(code),
                                     "--expected-manifest-sha256", digest(run / "run_manifest.json")], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            report = json.loads((run / "health/pristine_health.json").read_text())
            audit_output = json.loads(result.stdout)
            self.assertEqual(audit_output["pristine_health_sha256"], digest(run / "health/pristine_health.json"))
            self.assertFalse(report["healthy"])
            self.assertIn("parser_sha256", report)
            self.assertIn("qe_stderr_sha256", report)

    def test_pristine_audit_rejects_input_changed_after_review_before_writing_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = tmp_path / "run"
            (run / "forces/pristine").mkdir(parents=True)
            pristine = run / "forces/pristine/scf.in"
            pristine.write_text(scf())
            manifest = run / "run_manifest.json"
            manifest.write_text(json.dumps({
                "document_type": "srcu_v2_run_manifest",
                "input_sha256": {"pristine/scf.in": digest(pristine)},
            }) + "\n")
            reviewed_anchor = digest(manifest)
            pristine.write_text(scf().replace("nat = 96", "nat = 1"))
            output = tmp_path / "pristine.out"
            stderr = tmp_path / "pristine.stderr"
            code = tmp_path / "exit_code.txt"
            output.write_text(valid_qe_output())
            stderr.write_text("")
            code.write_text("0\n")
            result = subprocess.run([
                sys.executable, str(AUDIT), "--run-dir", str(run),
                "--qe-output", str(output), "--qe-stderr", str(stderr),
                "--exit-code", str(code),
                "--expected-manifest-sha256", reviewed_anchor,
            ], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fingerprint differs", result.stderr)
            self.assertFalse((run / "health").exists())

    def test_pristine_audit_rejects_health_symlink_before_external_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run = tmp_path / "run"
            (run / "forces/pristine").mkdir(parents=True)
            (run / "forces/pristine/scf.in").write_text(scf())
            (run / "run_manifest.json").write_text("{}\n")
            external = tmp_path / "external"; external.mkdir()
            (run / "health").symlink_to(external, target_is_directory=True)
            output, stderr, code = tmp_path / "pristine.out", tmp_path / "pristine.stderr", tmp_path / "exit_code.txt"
            output.write_text(valid_qe_output()); stderr.write_text(""); code.write_text("0\n")
            result = subprocess.run([sys.executable, str(AUDIT), "--run-dir", str(run), "--qe-output", str(output), "--qe-stderr", str(stderr), "--exit-code", str(code),
                                     "--expected-manifest-sha256", digest(run / "run_manifest.json")], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink is forbidden in audit destination", result.stderr)
            self.assertFalse((external / "evidence").exists())
            self.assertFalse((external / "pristine_health.json").exists())


if __name__ == "__main__":
    unittest.main()

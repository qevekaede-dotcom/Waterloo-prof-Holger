from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as core
import relax_recovery as recovery
from qe_input import AtomicPosition, FinalCoordinates, parse_qe_input, replace_geometry_from_final_coordinates, replace_qe_geometry


CONFIG = core.REPO_ROOT / "thermo_candidates/SrZrS3/phono3py/campaign.json"


class RelaxRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.config = core.load_json(CONFIG)
        self.source = self.root / "source"
        core.command_prepare_relax(CONFIG, self.source)
        self.attempt = self.source / "slurm_attempts/relax/failed-1"
        self.attempt.mkdir(parents=True)
        self.target = self.root / "recovery"
        self.manifest = core.load_json(self.source / core.RUN_MANIFEST)
        self.reference = replace_geometry_from_final_coordinates(
            core.resolve_repo_source(self.config, "source.qe_scf_input").read_text(),
            core.resolve_repo_source(self.config, "source.original_relax_output").read_text(),
            expected_atoms=20, require_cell=True,
        )
        self.pseudo_dir = self.root / "pseudo"
        self.pseudo_dir.mkdir()
        for species, filename in self.config["pseudopotentials"]["files"].items():
            (self.pseudo_dir / filename).write_text(f"fake fixture {species}\n")
        self.pseudos = core.pseudopotential_hashes(self.config, self.pseudo_dir)
        self.relax_input = core.relax_input_for(self.config, self.reference, self.pseudo_dir)
        self.write("starting_unitcell.in", self.reference)
        self.write_json("starting_structure_audit.json", {"pass": True, "standardized": False, "accepted_starting_geometry_sha256": hashlib.sha256(self.reference.encode()).hexdigest()})
        self.write("relax.in", self.relax_input)
        self.write("relax.out", self.output())
        self.write("relax.err", "")
        self.command = ["srun", "pw.x", "-nk", "1", "-in", "relax.in"]
        self.write_json("relax_launch.json", {"command": self.command, "config_sha256": self.manifest["config_sha256"], "structure_policy_sha256": self.manifest["structure_policy_sha256"], "relax_input_sha256": core.sha256_path(self.attempt / "relax.in"), "starting_structure_audit_sha256": core.sha256_path(self.attempt / "starting_structure_audit.json"), "pseudopotentials": self.pseudos})
        self.refresh_process()
        self.write("context.tsv", "\n".join(f"{key}\t{value}" for key, value in {"stage": "relax", "attempt_id": self.attempt.name, "run_dir": str(self.source), "slurm_job_id": "123456", "config_sha256": self.manifest["config_sha256"], "campaign_cli_sha256": core.sha256_path(Path(core.__file__))}.items()) + "\n")
        self.write("exit_code.txt", "2\n")
        self.write("finished_utc.txt", "2026-09-10T09:00:00Z\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, text: str) -> None:
        (self.attempt / name).write_text(text)

    def write_json(self, name: str, value: object) -> None:
        self.write(name, json.dumps(value))

    def refresh_process(self) -> None:
        self.write_json("relax.process.json", {"command": self.command, "cwd": str(self.attempt), "returncode": 0, "stdout_sha256": core.sha256_path(self.attempt / "relax.out"), "stderr_sha256": core.sha256_path(self.attempt / "relax.err")})

    def output(self, *, converged: bool = False, shift: float = 0.0001) -> str:
        parsed = parse_qe_input(self.reference)
        positions = [f"{item.label} {item.coordinates[0] + shift:.12f} {item.coordinates[1]:.12f} {item.coordinates[2]:.12f}" for item in parsed.atomic_positions]
        status = "bfgs converged\nEnd of BFGS Geometry Optimization" if converged else "bfgs failed\nconvergence not achieved"
        return "\n".join(["Program PWSCF v.7.3.1", "convergence has been achieved", "Forces acting on atoms (cartesian axes, Ry/au):", "", *[f"atom {i} type 1 force = 0.00001097 0.00000000 0.00000000" for i in range(1, 21)], "", "Total force = 0.00001 Total SCF correction = 0.00000000", status, "Begin final coordinates", "ATOMIC_POSITIONS (crystal)", *positions, "End final coordinates", "JOB DONE.", ""])

    def prepare(self) -> dict:
        return recovery.prepare_recovery(CONFIG, self.target, source_run_dir=self.source, source_attempt=self.attempt, source_manifest_sha256=core.sha256_path(self.source / core.RUN_MANIFEST), source_output_sha256=core.sha256_path(self.attempt / "relax.out"))

    def load(self) -> tuple[str, dict]:
        return recovery.load_recovery_start(self.config, self.target, core.load_json(self.target / core.RUN_MANIFEST), self.reference, self.pseudos)

    def test_prepares_fresh_run_without_modifying_source_and_replays_seed(self) -> None:
        before = {name: core.sha256_path(self.attempt / name) for name in recovery.SOURCE_FILES}
        result = self.prepare()
        seed, receipt = self.load()
        self.assertTrue(result["healthy"])
        self.assertEqual(receipt["reset_number"], 1)
        self.assertEqual(parse_qe_input(seed).cell_parameters, parse_qe_input(self.reference).cell_parameters)
        self.assertNotEqual(seed, self.reference)
        self.assertEqual(before, {name: core.sha256_path(self.attempt / name) for name in recovery.SOURCE_FILES})
        self.assertFalse((self.target / "relax/final").exists())
        with self.assertRaisesRegex(core.CampaignError, "already exists"):
            self.prepare()

    def test_rejects_output_or_manifest_hash_mismatch_before_writing(self) -> None:
        with self.assertRaisesRegex(core.CampaignError, "output SHA256 mismatch"):
            recovery.prepare_recovery(CONFIG, self.target, source_run_dir=self.source, source_attempt=self.attempt, source_manifest_sha256=core.sha256_path(self.source / core.RUN_MANIFEST), source_output_sha256="0" * 64)
        self.assertFalse(self.target.exists())

    def test_rejects_normal_completion_or_unfinished_wrapper(self) -> None:
        self.write("relax.out", self.output(converged=True))
        self.refresh_process()
        with self.assertRaisesRegex(core.CampaignError, "explicit BFGS nonconvergence"):
            self.prepare()
        self.write("relax.out", self.output())
        self.refresh_process()
        self.write("exit_code.txt", "0\n")
        with self.assertRaisesRegex(core.CampaignError, "terminal failure"):
            self.prepare()

    def test_rejects_stale_process_hash_and_changed_source_settings(self) -> None:
        self.write("relax.out", self.output() + "changed\n")
        with self.assertRaisesRegex(core.CampaignError, "process hash mismatch"):
            self.prepare()
        self.refresh_process()
        self.write("relax.in", self.relax_input.replace("80", "81", 1))
        launch = core.load_json(self.attempt / "relax_launch.json")
        launch["relax_input_sha256"] = core.sha256_path(self.attempt / "relax.in")
        self.write_json("relax_launch.json", launch)
        with self.assertRaisesRegex(core.CampaignError, "exact policy-generated"):
            self.prepare()

    def test_rejects_wrong_cell_atom_order_and_large_shift(self) -> None:
        baseline = self.output()
        self.write("relax.out", baseline.replace("ATOMIC_POSITIONS (crystal)", "CELL_PARAMETERS (angstrom)\n9 0 0\n0 9 0\n0 0 9\n\nATOMIC_POSITIONS (crystal)"))
        self.refresh_process()
        with self.assertRaisesRegex(core.CampaignError, "fixed cell"):
            self.prepare()
        self.write("relax.out", baseline.replace("\nSr ", "\nZr ", 1))
        self.refresh_process()
        with self.assertRaisesRegex(ValueError, "ordering/species"):
            self.prepare()
        self.write("relax.out", self.output(shift=0.1))
        self.refresh_process()
        with self.assertRaisesRegex(core.CampaignError, "position-shift guardrail"):
            self.prepare()

    def test_rejects_pristine_started_and_duplicate_reset(self) -> None:
        self.write("pristine.in", "unexpected")
        with self.assertRaisesRegex(core.CampaignError, "already reached pristine"):
            self.prepare()
        (self.attempt / "pristine.in").unlink()
        manifest = copy.deepcopy(self.manifest)
        manifest["relax_recovery"] = {"receipt": "earlier"}
        (self.source / core.RUN_MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaisesRegex(core.CampaignError, "second automatic BFGS reset"):
            self.prepare()

    def test_revalidates_archive_seed_code_and_pseudopotentials(self) -> None:
        self.prepare()
        copy_path = self.target / "recovery_source/relax.out"
        original = copy_path.read_text()
        copy_path.write_text(original + "changed")
        with self.assertRaisesRegex(core.CampaignError, "source hash mismatch"):
            self.load()
        copy_path.write_text(original)
        altered = copy.deepcopy(self.pseudos)
        altered["Sr"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(core.CampaignError, "pseudopotential content mismatch"):
            recovery.load_recovery_start(self.config, self.target, core.load_json(self.target / core.RUN_MANIFEST), self.reference, altered)
        with patch.object(recovery, "__file__", self.attempt / "relax.in"):
            with self.assertRaisesRegex(core.CampaignError, "backend changed"):
                self.load()

    def test_failed_recovery_cannot_start_pristine(self) -> None:
        self.prepare()
        fresh_attempt = self.target / "slurm_attempts/relax/new-1"
        fresh_attempt.mkdir(parents=True)
        calls = []

        def failed_process(command, cwd, stdout_path, stderr_path):
            calls.append(list(command))
            stdout_path.write_text(self.output())
            stderr_path.write_text("")
            return {"returncode": 0}

        environment = {"SLURM_JOB_ID": "123457", "SLURM_JOB_NODELIST": "c001", "P3_ATTEMPT_DIR": str(fresh_attempt), "P3_PSEUDO_DIR": str(self.pseudo_dir)}
        with patch.dict(os.environ, environment), patch.object(core, "prepare_starting_geometry", return_value=(self.reference, {"pass": True})), patch.object(core, "run_process", side_effect=failed_process):
            with self.assertRaisesRegex(core.CampaignError, "normal BFGS convergence"):
                core.command_run_relax(CONFIG, self.target)
        self.assertEqual(len(calls), 1)
        self.assertFalse((fresh_attempt / "pristine.in").exists())
        self.assertFalse((self.target / "relax/final").exists())
        fresh_input = (fresh_attempt / "relax.in").read_text()
        self.assertIn("restart_mode = 'from_scratch'", fresh_input)
        self.assertIn("startingpot = 'atomic'", fresh_input)
        self.assertIn("startingwfc = 'atomic+random'", fresh_input)
        self.assertEqual((fresh_attempt / "reference_unitcell.in").read_text(), self.reference)

    def test_success_requires_original_cumulative_displacement_gate(self) -> None:
        self.write("relax.out", self.output(shift=0.004))
        self.refresh_process()
        for label, final_shift, expected_pass in (("valid", 0.0041, True), ("too-far", 0.007, False)):
            with self.subTest(label=label):
                self.target = self.root / label
                self.prepare()
                fresh_attempt = self.target / "slurm_attempts/relax/new-1"
                fresh_attempt.mkdir(parents=True)

                def successful_process(command, cwd, stdout_path, stderr_path):
                    stdout_path.write_text(self.output(converged=True, shift=final_shift))
                    stderr_path.write_text("")
                    return {"command": command, "cwd": str(cwd), "returncode": 0, "stdout_sha256": core.sha256_path(stdout_path), "stderr_sha256": core.sha256_path(stderr_path)}

                environment = {"SLURM_JOB_ID": "123457", "SLURM_JOB_NODELIST": "c001", "P3_ATTEMPT_DIR": str(fresh_attempt), "P3_PSEUDO_DIR": str(self.pseudo_dir)}
                scan = [{"symprec_angstrom": 1e-6, "spacegroup_number": 62}]
                with patch.dict(os.environ, environment), patch.object(core, "prepare_starting_geometry", return_value=(self.reference, {"pass": True})), patch.object(core, "run_process", side_effect=successful_process), patch.object(core, "symmetry_scan", return_value=scan):
                    core.command_run_relax(CONFIG, self.target)
                    if expected_pass:
                        self.assertTrue(core.command_finalize_relax(CONFIG, self.target)["pass"])
                    else:
                        with self.assertRaisesRegex(core.CampaignError, "tight-relax gate failed"):
                            core.command_finalize_relax(CONFIG, self.target)
                gate = core.load_json(fresh_attempt / "relax_gate.json")
                self.assertEqual(gate["checks"]["position_shift_within_limit"], expected_pass)
                self.assertEqual((self.target / "relax/final/gate.json").exists(), expected_pass)


if __name__ == "__main__":
    unittest.main()

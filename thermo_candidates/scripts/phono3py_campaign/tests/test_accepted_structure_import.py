from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import accepted_structure_import as importer
import campaign as core
import force_backend
import relax_recovery as recovery
import submit
from qe_input import parse_qe_input, replace_geometry_from_final_coordinates


CONFIG = core.REPO_ROOT / "thermo_candidates/SrZrS3/phono3py/campaign.json"


class AcceptedStructureImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.config = core.load_json(CONFIG)
        self.pseudo = self.root / "pseudo"
        self.pseudo.mkdir()
        for species, filename in self.config["pseudopotentials"]["files"].items():
            (self.pseudo / filename).write_text(f"immutable synthetic {species} pseudopotential\n")
        self.pseudos = core.pseudopotential_hashes(self.config, self.pseudo)
        self.original = self.root / "original-failure"
        core.command_prepare_relax(CONFIG, self.original)
        self.original_attempt = self.original / "slurm_attempts/relax/failed-1"
        self.original_attempt.mkdir(parents=True)
        source_text = core.resolve_repo_source(self.config, "source.qe_scf_input").read_text()
        relax_text = core.resolve_repo_source(self.config, "source.original_relax_output").read_text()
        self.reference = replace_geometry_from_final_coordinates(
            source_text, relax_text, expected_atoms=20, require_cell=True
        )
        self._make_failed_attempt()
        self.source = self.root / "accepted-source"
        recovery.prepare_recovery(
            CONFIG,
            self.source,
            source_run_dir=self.original,
            source_attempt=self.original_attempt,
            source_manifest_sha256=core.sha256_path(self.original / core.RUN_MANIFEST),
            source_output_sha256=core.sha256_path(self.original_attempt / "relax.out"),
        )
        self.accepted_attempt = self.source / "slurm_attempts/relax/accepted-1"
        self.accepted_attempt.mkdir(parents=True)
        self._make_accepted_attempt()
        # Model the actual problem: accepted structure policy is unchanged while
        # the source preflight policy predates the current count-only candidates.
        source_manifest = core.load_json(self.source / core.RUN_MANIFEST)
        source_manifest["preflight_policy_sha256"] = "0" * 64
        (self.source / core.RUN_MANIFEST).write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n")
        self.target = self.root / "fresh-import"

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def _qe_output(self, *, converged_bfgs: bool, shift: float) -> str:
        parsed = parse_qe_input(self.reference)
        positions = [
            f"{item.label} {item.coordinates[0] + shift:.12f} "
            f"{item.coordinates[1]:.12f} {item.coordinates[2]:.12f}"
            for item in parsed.atomic_positions
        ]
        lines = [
            "Program PWSCF v.7.3.1",
            "convergence has been achieved in 8 iterations",
            "Forces acting on atoms (cartesian axes, Ry/au):",
            "",
        ]
        lines.extend(
            f"atom {index} type 1 force = 0.00000900 0.00000000 0.00000000"
            for index in range(1, 21)
        )
        lines.append("Total force = 0.00001 Total SCF correction = 0.00000000")
        if converged_bfgs:
            lines.extend(
                [
                    "bfgs converged",
                    "End of BFGS Geometry Optimization",
                    "Begin final coordinates",
                    "ATOMIC_POSITIONS (crystal)",
                    *positions,
                    "End final coordinates",
                ]
            )
        else:
            lines.extend(
                [
                    "bfgs failed",
                    "convergence not achieved",
                    "Begin final coordinates",
                    "ATOMIC_POSITIONS (crystal)",
                    *positions,
                    "End final coordinates",
                ]
            )
        lines.append("JOB DONE.")
        return "\n".join(lines) + "\n"

    def _make_failed_attempt(self) -> None:
        manifest = core.load_json(self.original / core.RUN_MANIFEST)
        attempt = self.original_attempt
        (attempt / "starting_unitcell.in").write_text(self.reference)
        self._write_json(
            attempt / "starting_structure_audit.json",
            {
                "pass": True,
                "standardized": False,
                "accepted_starting_geometry_sha256": hashlib.sha256(self.reference.encode()).hexdigest(),
            },
        )
        relax_input = core.relax_input_for(self.config, self.reference, self.pseudo)
        (attempt / "relax.in").write_text(relax_input)
        (attempt / "relax.out").write_text(self._qe_output(converged_bfgs=False, shift=0.0001))
        (attempt / "relax.err").write_text("")
        command = ["srun", "pw.x", "-nk", "1", "-in", "relax.in"]
        self._write_json(
            attempt / "relax_launch.json",
            {
                "command": command,
                "config_sha256": manifest["config_sha256"],
                "structure_policy_sha256": manifest["structure_policy_sha256"],
                "relax_input_sha256": core.sha256_path(attempt / "relax.in"),
                "starting_structure_audit_sha256": core.sha256_path(attempt / "starting_structure_audit.json"),
                "pseudopotentials": self.pseudos,
            },
        )
        self._write_json(
            attempt / "relax.process.json",
            {
                "command": command,
                "cwd": str(attempt),
                "returncode": 0,
                "stdout_sha256": core.sha256_path(attempt / "relax.out"),
                "stderr_sha256": core.sha256_path(attempt / "relax.err"),
            },
        )
        (attempt / "context.tsv").write_text(
            "".join(
                f"{key}\t{value}\n"
                for key, value in {
                    "stage": "relax",
                    "attempt_id": attempt.name,
                    "run_dir": str(self.original),
                    "slurm_job_id": "100001",
                    "config_sha256": manifest["config_sha256"],
                    "campaign_cli_sha256": core.sha256_path(Path(core.__file__)),
                }.items()
            )
        )
        (attempt / "exit_code.txt").write_text("2\n")
        (attempt / "finished_utc.txt").write_text("2026-09-10T09:00:00Z\n")

    def _make_accepted_attempt(self) -> None:
        call = {"count": 0}

        def successful_process(command, cwd, stdout_path, stderr_path):
            call["count"] += 1
            stdout_path.write_text(
                self._qe_output(converged_bfgs=True, shift=0.0002)
                if call["count"] == 1
                else self._qe_output(converged_bfgs=False, shift=0.0002)
            )
            stderr_path.write_text("")
            record = {
                "command": list(command),
                "cwd": str(cwd),
                "returncode": 0,
                "stdout_sha256": core.sha256_path(stdout_path),
                "stderr_sha256": core.sha256_path(stderr_path),
            }
            self._write_json(stdout_path.with_name(f"{stdout_path.stem}.process.json"), record)
            return record

        environment = {
            "SLURM_JOB_ID": "200002",
            "SLURM_JOB_NODELIST": "c001",
            "P3_ATTEMPT_DIR": str(self.accepted_attempt),
            "P3_PSEUDO_DIR": str(self.pseudo),
        }
        scan = [{"symprec_angstrom": value["symprec_angstrom"], "spacegroup_number": 62,
                 "international_symbol": "Pnma"}
                for value in self.config["symmetry_validation"]["scan_symprec_pairs"]]
        with patch.dict(os.environ, environment), \
             patch.object(core, "prepare_starting_geometry", return_value=(self.reference, {"pass": True})), \
             patch.object(core, "run_process", side_effect=successful_process), \
             patch.object(core, "symmetry_scan", return_value=scan):
            core.command_run_relax(CONFIG, self.source)
            core.command_finalize_relax(CONFIG, self.source)

        manifest = core.load_json(self.source / core.RUN_MANIFEST)
        (self.accepted_attempt / "context.tsv").write_text(
            "".join(
                f"{key}\t{value}\n"
                for key, value in {
                    "stage": "relax",
                    "attempt_id": self.accepted_attempt.name,
                    "run_dir": str(self.source),
                    "slurm_job_id": "200002",
                    "config_sha256": manifest["config_sha256"],
                    "campaign_cli_sha256": core.sha256_path(Path(core.__file__)),
                }.items()
            )
        )
        (self.accepted_attempt / "exit_code.txt").write_text("0\n")
        (self.accepted_attempt / "finished_utc.txt").write_text("2026-09-10T10:00:00Z\n")
        (self.accepted_attempt / "stdout.log").write_text("synthetic wrapper stdout\n")
        (self.accepted_attempt / "stderr.log").write_text("")

    def _anchors(self) -> dict[str, str]:
        return {
            "source_manifest_sha256": core.sha256_path(self.source / core.RUN_MANIFEST),
            "source_gate_sha256": core.sha256_path(self.source / "relax/final/gate.json"),
            "source_provenance_sha256": core.sha256_path(self.source / "relax/final/provenance.json"),
            "source_unitcell_sha256": core.sha256_path(self.source / "relax/final/unitcell.in"),
        }

    def _rewrite_execution_anchor(self, execution: dict[str, object]) -> None:
        execution_path = self.accepted_attempt / "execution_manifest.json"
        self._write_json(execution_path, execution)
        provenance_path = self.source / "relax/final/provenance.json"
        provenance = core.load_json(provenance_path)
        provenance["execution_manifest_sha256"] = core.sha256_path(execution_path)
        self._write_json(provenance_path, provenance)

    def _prepare(self, **overrides):
        values = self._anchors()
        values.update(overrides)
        scan = [{"symprec_angstrom": value["symprec_angstrom"], "spacegroup_number": 62,
                 "international_symbol": "Pnma"}
                for value in self.config["symmetry_validation"]["scan_symprec_pairs"]]
        with patch.object(core, "symmetry_scan", return_value=scan):
            return importer.prepare_import(
                CONFIG,
                self.target,
                source_run_dir=self.source,
                **values,
            )

    def _verify(self):
        scan = [{"symprec_angstrom": value["symprec_angstrom"], "spacegroup_number": 62,
                 "international_symbol": "Pnma"}
                for value in self.config["symmetry_validation"]["scan_symprec_pairs"]]
        with patch.object(core, "symmetry_scan", return_value=scan):
            return importer.verify_imported_acceptance(CONFIG, self.target)

    def test_imports_to_fresh_self_contained_current_policy_run(self) -> None:
        before = core.sha256_path(self.source / "relax/final/unitcell.in")
        result = self._prepare()
        self.assertTrue(result["healthy"])
        self.assertEqual(result["source_preflight_policy_sha256"], "0" * 64)
        self.assertEqual(
            result["destination_preflight_policy_sha256"],
            core.policy_sha256(self.config, "preflight"),
        )
        self.assertEqual(before, core.sha256_path(self.source / "relax/final/unitcell.in"))
        manifest = core.load_json(self.target / core.RUN_MANIFEST)
        self.assertEqual(manifest["structure_policy_sha256"], core.policy_sha256(self.config, "structure"))
        self.assertEqual(manifest["preflight_policy_sha256"], core.policy_sha256(self.config, "preflight"))
        self.assertTrue(Path(manifest["source_qe_input"]).is_relative_to(self.target))
        self.assertEqual(
            core.verify_upstream_manifest(
                self.config, CONFIG, self.target, stage="preflight"
            )["accepted_structure_import"]["sha256"],
            result["receipt_sha256"],
        )
        self.assertFalse((self.target / "slurm_attempts/relax").exists())
        self.assertFalse((self.target / "accepted_structure_source/source_run/preflight").exists())
        self.assertFalse((self.target / "accepted_structure_source/source_run/tmp-relax").exists())

        moved = self.root / "source-removed"
        self.source.rename(moved)
        verified = self._verify()
        self.assertTrue(verified["healthy"])
        self.assertFalse(verified["external_source_paths_required"])
        manifest = core.load_json(self.target / core.RUN_MANIFEST)
        submit_context = submit.SubmissionContext(
            config_path=CONFIG.resolve(),
            run_dir=self.target.resolve(),
            config=self.config,
            manifest=manifest,
            config_sha256=manifest["config_sha256"],
        )
        scan = [
            {"symprec_angstrom": value["symprec_angstrom"],
             "spacegroup_number": 62, "international_symbol": "Pnma"}
            for value in self.config["symmetry_validation"]["scan_symprec_pairs"]
        ]
        with patch.object(core, "symmetry_scan", return_value=scan):
            self.assertTrue(core.verify_imported_structure_if_present(
                CONFIG, self.target, manifest
            )["healthy"])
            self.assertTrue(submit.require_imported_acceptance(submit_context)["healthy"])
            force_hashes = force_backend._imported_acceptance_provenance(
                CONFIG, self.target, manifest
            )
        self.assertIn(str(self.target / importer.RECEIPT), force_hashes)
        self.assertTrue(any(str(importer.ARCHIVE) in path for path in force_hashes))

        selected = copy.deepcopy(self.config)
        selected["production"]["selection_required"] = False
        selected["production"]["selected_supercell"] = "sr_fc3_3x2x1"
        selected["production"]["selected_cutoff"] = "sr_cutoff_4A"
        selected["production"]["automatic_submission_allowed"] = True
        selected["force_and_amplitude_validation"]["selection_required"] = False
        # Populate the force settings only to keep the full config validator
        # satisfied; these values are not evidence and no force task is run.
        selected["force_and_amplitude_validation"].update(
            selected_displacement_distance_angstrom=0.03,
            selected_displacement_distance_cli_bohr=0.03 / core.BOHR_TO_ANGSTROM,
            selected_ecutwfc_Ry=80,
            selected_ecutrho_Ry=640,
            selected_conv_thr_Ry=1e-10,
            selected_k_points=[3, 3, 3],
        )
        selected_path = self.root / "selected.json"
        selected_path.write_text(json.dumps(selected))
        with patch.object(core, "symmetry_scan", return_value=[
            {"symprec_angstrom": value["symprec_angstrom"], "spacegroup_number": 62,
             "international_symbol": "Pnma"}
            for value in self.config["symmetry_validation"]["scan_symprec_pairs"]
        ]):
            self.assertTrue(
                importer.verify_imported_acceptance(selected_path, self.target)["healthy"]
            )

    def test_rejects_anchor_mismatch_before_destination_creation(self) -> None:
        with self.assertRaisesRegex(core.CampaignError, "source_final_gate_sha256 mismatch"):
            self._prepare(source_gate_sha256="f" * 64)
        self.assertFalse(self.target.exists())

    def test_rejects_structure_policy_drift_before_destination_creation(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["tight_relax"]["accept_max_force_ry_bohr"] *= 0.5
        changed_path = self.root / "changed.json"
        changed_path.write_text(json.dumps(changed))
        values = self._anchors()
        with self.assertRaisesRegex(core.CampaignError, "source structure policy differs"):
            importer.prepare_import(
                changed_path,
                self.target,
                source_run_dir=self.source,
                **values,
            )
        self.assertFalse(self.target.exists())

    def test_rejects_mutated_nested_process_receipt(self) -> None:
        execution = core.load_json(self.accepted_attempt / "execution_manifest.json")
        execution["relax_process"]["returncode"] = 7
        self._rewrite_execution_anchor(execution)
        with self.assertRaisesRegex(core.CampaignError, "nested process receipts"):
            self._prepare()
        self.assertFalse(self.target.exists())

    def test_rejects_relax_output_with_terminal_marker_before_final_coordinates(self) -> None:
        output_path = self.accepted_attempt / "relax.out"
        output = output_path.read_text()
        output_path.write_text(
            output.replace("Begin final coordinates", "JOB DONE.\nBegin final coordinates")
            .replace("End final coordinates\nJOB DONE.", "End final coordinates")
        )
        output_sha = core.sha256_path(output_path)
        process_path = self.accepted_attempt / "relax.process.json"
        process = core.load_json(process_path)
        process["stdout_sha256"] = output_sha
        self._write_json(process_path, process)
        pristine_launch_path = self.accepted_attempt / "pristine_launch.json"
        pristine_launch = core.load_json(pristine_launch_path)
        pristine_launch["relax_output_sha256"] = output_sha
        self._write_json(pristine_launch_path, pristine_launch)
        execution = core.load_json(self.accepted_attempt / "execution_manifest.json")
        execution["relax_output_sha256"] = output_sha
        execution["relax_process"] = process
        self._rewrite_execution_anchor(execution)
        with self.assertRaisesRegex(core.CampaignError, "must order its last force block"):
            self._prepare()
        self.assertFalse(self.target.exists())

    def test_rejects_rehashed_additional_complete_final_block_and_terminal_marker(self) -> None:
        output_path = self.accepted_attempt / "relax.out"
        output = output_path.read_text()
        begin = output.index("Begin final coordinates")
        end = output.index("End final coordinates") + len("End final coordinates")
        output_path.write_text(output + output[begin:end] + "\nJOB DONE.\n")
        output_sha = core.sha256_path(output_path)
        process_path = self.accepted_attempt / "relax.process.json"
        process = core.load_json(process_path)
        process["stdout_sha256"] = output_sha
        self._write_json(process_path, process)
        pristine_launch_path = self.accepted_attempt / "pristine_launch.json"
        pristine_launch = core.load_json(pristine_launch_path)
        pristine_launch["relax_output_sha256"] = output_sha
        self._write_json(pristine_launch_path, pristine_launch)
        execution = core.load_json(self.accepted_attempt / "execution_manifest.json")
        execution["relax_output_sha256"] = output_sha
        execution["relax_process"] = process
        self._rewrite_execution_anchor(execution)
        with self.assertRaisesRegex(
            core.CampaignError, "exactly one final-coordinate block"
        ):
            self._prepare()
        self.assertFalse(self.target.exists())

    def test_archive_tamper_fails_without_external_source(self) -> None:
        self._prepare()
        shutil.rmtree(self.source)
        archived = self.target / (
            "accepted_structure_source/source_run/slurm_attempts/relax/accepted-1/relax.out"
        )
        archived.write_text(archived.read_text() + "tampered\n")
        with self.assertRaisesRegex(core.CampaignError, "hash mismatch"):
            self._verify()

    def test_receipt_tamper_fails_campaign_submit_and_force_choke_points(self) -> None:
        self._prepare()
        shutil.rmtree(self.source)
        receipt_path = self.target / importer.RECEIPT
        receipt_path.write_text(receipt_path.read_text() + " ")
        manifest = core.load_json(self.target / core.RUN_MANIFEST)
        context = submit.SubmissionContext(
            config_path=CONFIG.resolve(),
            run_dir=self.target.resolve(),
            config=self.config,
            manifest=manifest,
            config_sha256=manifest["config_sha256"],
        )
        with self.assertRaisesRegex(core.CampaignError, "receipt hash mismatch"):
            core.verify_imported_structure_if_present(CONFIG, self.target, manifest)
        with self.assertRaisesRegex(submit.SubmissionError, "receipt hash mismatch"):
            submit.require_imported_acceptance(context)
        with self.assertRaisesRegex(core.CampaignError, "receipt hash mismatch"):
            force_backend._imported_acceptance_provenance(CONFIG, self.target, manifest)

    def test_destination_gate_cannot_be_rewritten_after_import(self) -> None:
        self._prepare()
        gate_path = self.target / "relax/final/gate.json"
        gate = core.load_json(gate_path)
        gate["checks"]["bfgs_converged"] = False
        gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
        with self.assertRaisesRegex(core.CampaignError, "gate replay mismatch"):
            self._verify()

    def test_rejects_symlinked_source_evidence_and_existing_destination(self) -> None:
        original = self.source / "relax/final/unitcell.in"
        replacement = self.root / "same-unitcell.in"
        replacement.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(replacement)
        with self.assertRaisesRegex(core.CampaignError, "may not contain a symlink"):
            self._prepare()
        self.assertFalse(self.target.exists())

        original.unlink()
        original.write_bytes(replacement.read_bytes())
        self.target.mkdir()
        with self.assertRaisesRegex(core.CampaignError, "already exists"):
            self._prepare()

    def test_rejects_nested_and_frozen_destination_paths(self) -> None:
        with self.assertRaisesRegex(core.CampaignError, "non-nested"):
            importer.prepare_import(
                CONFIG,
                self.source / "child",
                source_run_dir=self.source,
                **self._anchors(),
            )
        frozen = self.root / "READY_TO_ATTACH" / "run"
        with self.assertRaisesRegex(core.CampaignError, "READY_TO_ATTACH"):
            importer.prepare_import(
                CONFIG,
                frozen,
                source_run_dir=self.source,
                **self._anchors(),
            )


if __name__ == "__main__":
    unittest.main()

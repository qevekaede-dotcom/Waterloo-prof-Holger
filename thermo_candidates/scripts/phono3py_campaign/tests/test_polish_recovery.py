from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as core
import polish_recovery as polish
import relax_recovery
import submit
from qe_input import FinalCoordinates, _set_namelist_values, extract_final_coordinates, parse_qe_input, replace_geometry_from_final_coordinates, replace_qe_geometry


CONFIG = core.REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"


class PolishRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.config = core.load_json(CONFIG)
        self.pseudo_dir = self.root / "pseudo"
        self.pseudo_dir.mkdir()
        for species, filename in self.config["pseudopotentials"]["files"].items():
            (self.pseudo_dir / filename).write_text(f"fake fixture {species}\n")
        self.pseudos = core.pseudopotential_hashes(self.config, self.pseudo_dir)

        self.original_run = self.root / "original"
        core.command_prepare_relax(CONFIG, self.original_run)
        self.original_manifest = core.load_json(self.original_run / core.RUN_MANIFEST)
        self.original_attempt = self.original_run / "slurm_attempts/relax/original-failure"
        self.original_attempt.mkdir(parents=True)
        self.reference = replace_geometry_from_final_coordinates(
            core.resolve_repo_source(self.config, "source.qe_scf_input").read_text(),
            core.resolve_repo_source(self.config, "source.original_relax_output").read_text(),
            expected_atoms=18,
            require_cell=True,
        )
        self._write_failure_attempt(
            self.original_run,
            self.original_attempt,
            self.reference,
            self.reference,
            self.original_manifest,
            reset=False,
            shift=0.0001,
        )

        self.recovery_run = self.root / "one-reset"
        relax_recovery.prepare_recovery(
            CONFIG,
            self.recovery_run,
            source_run_dir=self.original_run,
            source_attempt=self.original_attempt,
            source_manifest_sha256=core.sha256_path(self.original_run / core.RUN_MANIFEST),
            source_output_sha256=core.sha256_path(self.original_attempt / "relax.out"),
        )
        self.recovery_manifest = core.load_json(self.recovery_run / core.RUN_MANIFEST)
        self.recovery_attempt = self.recovery_run / "slurm_attempts/relax/one-reset-failure"
        self.recovery_attempt.mkdir(parents=True)
        self.recovery_seed, self.recovery_review = relax_recovery.load_recovery_start(
            self.config,
            self.recovery_run,
            self.recovery_manifest,
            self.reference,
            self.pseudos,
        )
        self._write_failure_attempt(
            self.recovery_run,
            self.recovery_attempt,
            self.recovery_seed,
            self.reference,
            self.recovery_manifest,
            reset=True,
            shift=0.0001,
        )
        self.polish_run = self.root / "polish"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _output(
        self,
        source: str,
        *,
        shift: float = 0.0,
        force: float = 1.0e-5,
        converged_bfgs: bool = False,
        reset_marker: bool = False,
        include_final: bool = True,
    ) -> str:
        parsed = parse_qe_input(source)
        positions = [
            f"{item.label} {item.coordinates[0] + shift:.12f} {item.coordinates[1]:.12f} {item.coordinates[2]:.12f}"
            for item in parsed.atomic_positions
        ]
        lines = [
            "Program PWSCF v.7.3.1",
            "convergence has been achieved",
            "Forces acting on atoms (cartesian axes, Ry/au):",
            "",
            *[
                f"atom {index} type 1 force = {force:.8f} 0.00000000 0.00000000"
                for index in range(1, 19)
            ],
            "",
            f"Total force = {force:.8f} Total SCF correction = 0.00000000",
        ]
        if reset_marker:
            lines.append("history already reset at previous step: exiting")
        if converged_bfgs:
            lines.extend(["bfgs converged", "End of BFGS Geometry Optimization"])
        elif include_final:
            lines.extend(["bfgs failed", "convergence not achieved"])
        if include_final:
            lines.extend(
                [
                    "Begin final coordinates",
                    "ATOMIC_POSITIONS (crystal)",
                    *positions,
                    "End final coordinates",
                ]
            )
        lines.extend(["JOB DONE.", ""])
        return "\n".join(lines)

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value))

    def _write_failure_attempt(
        self,
        run_dir: Path,
        attempt: Path,
        starting: str,
        reference: str,
        manifest: dict,
        *,
        reset: bool,
        shift: float,
    ) -> None:
        attempt.joinpath("starting_unitcell.in").write_text(starting)
        if reset:
            attempt.joinpath("reference_unitcell.in").write_text(reference)
        audit = {
            "pass": True,
            "standardized": False,
            "accepted_starting_geometry_sha256": hashlib.sha256(starting.encode()).hexdigest(),
        }
        self._write_json(attempt / "starting_structure_audit.json", audit)
        relax_input = core.relax_input_for(self.config, starting, self.pseudo_dir)
        if reset:
            relax_input = _set_namelist_values(
                relax_input, "CONTROL", {"restart_mode": "'from_scratch'"}
            )
            relax_input = _set_namelist_values(
                relax_input,
                "ELECTRONS",
                {"startingpot": "'atomic'", "startingwfc": "'atomic+random'"},
            )
        attempt.joinpath("relax.in").write_text(relax_input)
        attempt.joinpath("relax.out").write_text(
            self._output(starting, shift=shift, reset_marker=reset)
        )
        attempt.joinpath("relax.err").write_text("")
        command = ["srun", "pw.x", "-nk", "1", "-in", "relax.in"]
        launch = {
            "command": command,
            "config_sha256": manifest["config_sha256"],
            "structure_policy_sha256": manifest["structure_policy_sha256"],
            "relax_input_sha256": core.sha256_path(attempt / "relax.in"),
            "starting_structure_audit_sha256": core.sha256_path(attempt / "starting_structure_audit.json"),
            "pseudopotentials": self.pseudos,
            "recovery": self.recovery_review if reset else None,
        }
        self._write_json(attempt / "relax_launch.json", launch)
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
        context = {
            "stage": "relax",
            "attempt_id": attempt.name,
            "run_dir": str(run_dir),
            "slurm_job_id": "123457" if reset else "123456",
            "config_sha256": manifest["config_sha256"],
            "campaign_cli_sha256": manifest["workflow_files"][
                "thermo_candidates/scripts/phono3py_campaign/campaign.py"
            ],
        }
        attempt.joinpath("context.tsv").write_text(
            "\n".join(f"{key}\t{value}" for key, value in context.items()) + "\n"
        )
        attempt.joinpath("exit_code.txt").write_text("2\n")
        attempt.joinpath("finished_utc.txt").write_text("2026-09-11T08:00:00Z\n")

    def _prepare(self) -> dict:
        return polish.prepare_lineage(
            CONFIG,
            self.polish_run,
            source_run_dir=self.recovery_run,
            source_attempt=self.recovery_attempt,
            source_manifest_sha256=core.sha256_path(self.recovery_run / core.RUN_MANIFEST),
            source_output_sha256=core.sha256_path(self.recovery_attempt / "relax.out"),
        )

    def _write_diagnostic_execution(self) -> Path:
        attempt = self.polish_run / "diagnostic/attempts/diag-1"
        attempt.mkdir()
        execution = {
            "schema_version": 1,
            "created_utc": "2026-09-11T08:30:00Z",
            "started_utc": "2026-09-11T08:29:00Z",
            "finished_utc": "2026-09-11T08:30:00Z",
            "slurm": {"job_id": "123460", "node_list": "c001"},
            "context": {
                "run_dir": str(self.polish_run),
                "attempt_id": "diag-1",
                "config_canonical_sha256": core.canonical_sha256(self.config),
            },
            "lineage_sha256": core.sha256_path(self.polish_run / polish.LINEAGE_RECEIPT),
            "polish_policy_sha256": core.load_json(self.polish_run / polish.LINEAGE_RECEIPT)["polish_policy_sha256"],
            "runs": {},
            "structure_accepted": False,
        }
        for label, input_name, force in (
            ("baseline-a", "baseline.in", 1.00e-5),
            ("baseline-b", "baseline.in", 1.10e-5),
            ("higher-ecutrho", "higher_ecutrho.in", 1.20e-5),
        ):
            work = attempt / label
            work.mkdir()
            input_text = (self.polish_run / "diagnostic/inputs" / input_name).read_text()
            (work / "scf.in").write_text(input_text)
            (work / "scf.out").write_text(
                self._output(input_text, force=force, include_final=False)
            )
            (work / "scf.err").write_text("")
            command = ["srun", "pw.x", "-nk", "1", "-in", "scf.in"]
            process = {
                "command": command,
                "cwd": str(work),
                "started_utc": "2026-09-11T08:29:00Z",
                "finished_utc": "2026-09-11T08:30:00Z",
                "returncode": 0,
                "stdout_sha256": core.sha256_path(work / "scf.out"),
                "stderr_sha256": core.sha256_path(work / "scf.err"),
            }
            execution["runs"][label] = {
                "command": command,
                "input_sha256": core.sha256_path(work / "scf.in"),
                "output_sha256": process["stdout_sha256"],
                "stderr_sha256": process["stderr_sha256"],
                "process": process,
            }
            self._write_json(work / "scf.process.json", process)
            execution["runs"][label]["process_record_sha256"] = core.sha256_path(
                work / "scf.process.json"
            )
            execution["runs"][label]["fresh_scratch"] = True
        self._write_json(attempt / polish.DIAGNOSTIC_EXECUTION, execution)
        return attempt

    def _write_passing_diagnostic(self) -> dict:
        attempt = self._write_diagnostic_execution()
        receipt = polish.finalize_diagnostic(
            CONFIG,
            self.polish_run,
            attempt_id="diag-1",
            expected_execution_sha256=core.sha256_path(attempt / polish.DIAGNOSTIC_EXECUTION),
        )
        return receipt

    def test_archives_exact_lineage_without_mutating_source_or_accepting_structure(self) -> None:
        before = {
            str(path.relative_to(self.recovery_run)): core.sha256_path(path)
            for path in self.recovery_run.rglob("*")
            if path.is_file()
        }
        result = self._prepare()
        after = {
            str(path.relative_to(self.recovery_run)): core.sha256_path(path)
            for path in self.recovery_run.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertEqual(result["baseline_input_sha256"], core.sha256_path(self.polish_run / "diagnostic/inputs/baseline.in"))
        self.assertEqual(result["higher_ecutrho_input_sha256"], core.sha256_path(self.polish_run / "diagnostic/inputs/higher_ecutrho.in"))
        baseline = parse_qe_input(
            (self.polish_run / "diagnostic/inputs/baseline.in").read_text()
        )
        higher = parse_qe_input(
            (self.polish_run / "diagnostic/inputs/higher_ecutrho.in").read_text()
        )
        self.assertEqual((baseline.ecutwfc_ry, baseline.ecutrho_ry), (100.0, 800.0))
        self.assertEqual((higher.ecutwfc_ry, higher.ecutrho_ry), (100.0, 1000.0))
        self.assertEqual(baseline.cell_parameters, higher.cell_parameters)
        self.assertEqual(baseline.atomic_positions, higher.atomic_positions)
        self.assertEqual(baseline.k_points, higher.k_points)
        self.assertFalse((self.polish_run / core.RUN_MANIFEST).exists())
        self.assertFalse((self.polish_run / "relax/final").exists())
        self.assertFalse(result["structure_accepted"])

    def test_diagnostic_hash_gate_releases_only_one_polish_and_keeps_preflight_blocked(self) -> None:
        self._prepare()
        receipt = self._write_passing_diagnostic()
        self.assertTrue(receipt["pass"])
        self.assertFalse(receipt["structure_accepted"])
        self.assertFalse(receipt["preflight_unlocked"])
        released = polish.release_polish(CONFIG, self.polish_run)
        manifest = core.load_json(self.polish_run / core.RUN_MANIFEST)
        self.assertIn("relax_polish", manifest)
        self.assertNotIn("relax_recovery", manifest)
        self.assertEqual(released["maximum_attempts"], 1)
        context = submit.resolve_context(CONFIG, self.polish_run, "relax")
        submit.stage_plan(context, "relax", attempt_id="only-polish")
        with self.assertRaisesRegex(submit.SubmissionError, "tight-relax gate"):
            submit.stage_plan(
                submit.resolve_context(CONFIG, self.polish_run, "preflight"),
                "preflight",
                attempt_id="blocked-preflight",
            )
        prior = self.polish_run / "submissions/relax/consumed"
        prior.mkdir(parents=True)
        with self.assertRaisesRegex(submit.SubmissionError, "already been consumed"):
            submit.stage_plan(context, "relax", attempt_id="second-polish")
        with self.assertRaisesRegex(core.CampaignError, "already been released"):
            polish.release_polish(CONFIG, self.polish_run)

    def test_diagnostic_allows_only_one_fresh_attempt_directory(self) -> None:
        self._prepare()
        (self.polish_run / "diagnostic/attempts/already-used").mkdir()
        with patch.dict(
            os.environ,
            {"SLURM_JOB_ID": "123459", "SLURM_JOB_NODELIST": "c001"},
        ), self.assertRaisesRegex(core.CampaignError, "already been consumed"):
            polish.run_diagnostic(CONFIG, self.polish_run, attempt_id="second")

    def test_run_diagnostic_captures_slurm_identity_and_exact_process_records(self) -> None:
        self._prepare()

        def fake_process(command, cwd, stdout_path, stderr_path):
            source = (cwd / "scf.in").read_text()
            stdout_path.write_text(self._output(source, force=1.0e-5, include_final=False))
            stderr_path.write_text("")
            process = {
                "command": list(command),
                "cwd": str(cwd),
                "started_utc": "2026-09-11T08:29:00Z",
                "finished_utc": "2026-09-11T08:30:00Z",
                "returncode": 0,
                "stdout_sha256": core.sha256_path(stdout_path),
                "stderr_sha256": core.sha256_path(stderr_path),
            }
            core.write_json_immutable(stdout_path.with_name("scf.process.json"), process)
            return process

        with (
            patch.dict(
                os.environ,
                {"SLURM_JOB_ID": "7654321", "SLURM_JOB_NODELIST": "c[001-002]"},
            ),
            patch.object(core, "run_process", side_effect=fake_process),
        ):
            execution = polish.run_diagnostic(
                CONFIG, self.polish_run, attempt_id="captured"
            )
        self.assertEqual(
            execution["slurm"],
            {"job_id": "7654321", "node_list": "c[001-002]"},
        )
        self.assertEqual(execution["context"]["attempt_id"], "captured")
        self.assertEqual(execution["context"]["run_dir"], str(self.polish_run))
        for record in execution["runs"].values():
            self.assertEqual(record["command"], core.qe_command("scf.in"))
            self.assertRegex(record["process_record_sha256"], r"^[0-9a-f]{64}$")

    def test_finalize_rejects_substituted_command_and_invalid_slurm_identity(self) -> None:
        for case in ("command", "slurm"):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                self._prepare()
                attempt = self._write_diagnostic_execution()
                execution_path = attempt / polish.DIAGNOSTIC_EXECUTION
                execution = core.load_json(execution_path)
                if case == "command":
                    record = execution["runs"]["baseline-a"]
                    record["command"] = ["srun", "other-pw.x", "-in", "scf.in"]
                    record["process"]["command"] = record["command"]
                    process_path = attempt / "baseline-a/scf.process.json"
                    self._write_json(process_path, record["process"])
                    record["process_record_sha256"] = core.sha256_path(process_path)
                    message = "process identity"
                else:
                    execution["slurm"]["job_id"] = "0"
                    message = "invalid Slurm identity"
                self._write_json(execution_path, execution)
                with self.assertRaisesRegex(core.CampaignError, message):
                    polish.finalize_diagnostic(
                        CONFIG,
                        self.polish_run,
                        attempt_id="diag-1",
                        expected_execution_sha256=core.sha256_path(execution_path),
                    )

    def test_diagnostic_rejects_output_hash_drift_before_release(self) -> None:
        self._prepare()
        attempt = self.polish_run / "diagnostic/attempts/diag-1"
        self._write_passing_diagnostic()
        with (attempt / "baseline-a/scf.out").open("a") as handle:
            handle.write("tampered\n")
        with self.assertRaisesRegex(core.CampaignError, "diagnostic exact hash mismatch"):
            polish.release_polish(CONFIG, self.polish_run)
        self.assertFalse((self.polish_run / core.RUN_MANIFEST).exists())

    def test_release_rejects_execution_and_stderr_mutation(self) -> None:
        for case in ("execution", "stderr"):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                self._prepare()
                self._write_passing_diagnostic()
                attempt = self.polish_run / "diagnostic/attempts/diag-1"
                if case == "execution":
                    with (attempt / polish.DIAGNOSTIC_EXECUTION).open("a") as handle:
                        handle.write(" ")
                    message = "execution SHA256 mismatch"
                else:
                    (attempt / "baseline-b/scf.err").write_text("unexpected stderr\n")
                    message = "diagnostic exact hash mismatch"
                with self.assertRaisesRegex(core.CampaignError, message):
                    polish.release_polish(CONFIG, self.polish_run)

    def test_load_polish_replays_raw_diagnostic_after_release(self) -> None:
        self._prepare()
        self._write_passing_diagnostic()
        polish.release_polish(CONFIG, self.polish_run)
        attempt = self.polish_run / "diagnostic/attempts/diag-1"
        with (attempt / "higher-ecutrho/scf.out").open("a") as handle:
            handle.write("post-release drift\n")
        with self.assertRaisesRegex(core.CampaignError, "diagnostic exact hash mismatch"):
            polish.load_polish_start(
                self.config,
                self.polish_run,
                core.load_json(self.polish_run / core.RUN_MANIFEST),
                self.reference,
                self.pseudos,
            )

    def test_terminal_recovery_to_polish_uses_fresh_scratch_and_ordinary_gate(self) -> None:
        self._prepare()
        self._write_passing_diagnostic()
        polish.release_polish(CONFIG, self.polish_run)
        attempt = self.polish_run / "slurm_attempts/relax/polish-1"
        attempt.mkdir(parents=True)
        calls: list[list[str]] = []

        def successful_process(command, cwd, stdout_path, stderr_path):
            calls.append(list(command))
            if command[-1] == "relax.in":
                source = (cwd / "starting_unitcell.in").read_text()
                stdout_path.write_text(
                    self._output(source, shift=0.0001, converged_bfgs=True)
                )
            else:
                source = (cwd / "pristine.in").read_text()
                stdout_path.write_text(
                    self._output(source, force=1.0e-5, include_final=False)
                )
            stderr_path.write_text("")
            return {
                "command": list(command),
                "cwd": str(cwd),
                "returncode": 0,
                "stdout_sha256": core.sha256_path(stdout_path),
                "stderr_sha256": core.sha256_path(stderr_path),
            }

        environment = {
            "SLURM_JOB_ID": "123458",
            "SLURM_JOB_NODELIST": "c001",
            "P3_ATTEMPT_DIR": str(attempt),
            "P3_PSEUDO_DIR": str(self.pseudo_dir),
        }
        symmetry = [{"symprec_angstrom": 1e-6, "spacegroup_number": 72}]
        with (
            patch.dict(os.environ, environment),
            patch.object(core, "prepare_starting_geometry", return_value=(self.reference, {"pass": True})),
            patch.object(core, "run_process", side_effect=successful_process),
            patch.object(core, "symmetry_scan", return_value=symmetry),
        ):
            core.command_run_relax(CONFIG, self.polish_run)
            gate = core.command_finalize_relax(CONFIG, self.polish_run)
        self.assertTrue(gate["pass"])
        self.assertEqual(len(calls), 2)
        relax_input = (attempt / "relax.in").read_text()
        self.assertIn("restart_mode = 'from_scratch'", relax_input)
        self.assertIn("startingpot = 'atomic'", relax_input)
        self.assertIn("startingwfc = 'atomic+random'", relax_input)
        self.assertIn("trust_radius_ini = 0.05", relax_input)
        self.assertIn("trust_radius_min = 0.0001", relax_input)
        self.assertIn("trust_radius_max = 0.2", relax_input)
        self.assertEqual((attempt / "reference_unitcell.in").read_text(), self.reference)
        self.assertFalse((attempt / "tmp-relax").exists())
        self.assertFalse((attempt / "tmp-pristine").exists())


if __name__ == "__main__":
    unittest.main()

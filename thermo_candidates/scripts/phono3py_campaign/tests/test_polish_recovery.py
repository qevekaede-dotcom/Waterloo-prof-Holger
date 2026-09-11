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

    def _workflow_hashes(self) -> dict[str, str]:
        campaign_dir = Path(polish.__file__).resolve().parent
        return {
            "submit.py": core.sha256_path(campaign_dir / "submit.py"),
            "campaign.py": core.sha256_path(campaign_dir / "campaign.py"),
            "cluster.env": core.sha256_path(campaign_dir / "slurm/cluster.env"),
            "diagnostic.sbatch": core.sha256_path(
                campaign_dir / "slurm/diagnostic.sbatch"
            ),
            "polish_recovery.py": core.sha256_path(Path(polish.__file__)),
        }

    def _diagnostic_environment(self) -> dict[str, str]:
        resources = self.config["scheduler"]["diagnostic_resources"]
        workflow = self._workflow_hashes()
        return {
            "SLURM_JOB_ID": "123460",
            "SLURM_JOB_NODELIST": "c001",
            "SLURM_JOB_ACCOUNT": self.config["scheduler"]["slurm_account"],
            "SLURM_JOB_NUM_NODES": str(resources["nodes"]),
            "SLURM_NTASKS": str(resources["ntasks"]),
            "SLURM_CPUS_PER_TASK": str(resources["cpus_per_task"]),
            "SLURM_MEM_PER_CPU": f"{resources['mem_per_cpu_mb']}M",
            "SLURM_JOB_PARTITION": resources["partition"],
            "SLURM_TIMELIMIT": str(int(resources["walltime_hours"] * 60)),
            "P3_DIAGNOSTIC_RESOURCE_SHA256": core.canonical_sha256(resources),
            "P3_DIAGNOSTIC_LINEAGE_SHA256": core.sha256_path(
                self.polish_run / polish.LINEAGE_RECEIPT
            ),
            "P3_DIAGNOSTIC_BACKEND_SHA256": workflow["polish_recovery.py"],
            "P3_SUBMIT_SCRIPT_SHA256": workflow["submit.py"],
            "P3_CAMPAIGN_CLI_SHA256": workflow["campaign.py"],
            "P3_CLUSTER_ENV_SHA256": workflow["cluster.env"],
            "P3_STAGE_SCRIPT_SHA256": workflow["diagnostic.sbatch"],
        }

    def _write_dispatch_evidence(
        self, attempt_id: str = "diag-1", job_id: str = "123460"
    ) -> Path:
        resources = self.config["scheduler"]["diagnostic_resources"]
        workflow = self._workflow_hashes()
        lineage_sha = core.sha256_path(self.polish_run / polish.LINEAGE_RECEIPT)
        resource_sha = core.canonical_sha256(resources)
        claim = self.polish_run / "diagnostic/dispatch_claim"
        claim.mkdir()
        claim_context = {
            "attempt_id": attempt_id,
            "slurm_job_id": job_id,
            "config_sha256": core.sha256_path(CONFIG),
            "lineage_sha256": lineage_sha,
            "resource_sha256": resource_sha,
            "submit_script_sha256": workflow["submit.py"],
            "stage_script_sha256": workflow["diagnostic.sbatch"],
            "cluster_env_sha256": workflow["cluster.env"],
            "campaign_cli_sha256": workflow["campaign.py"],
            "diagnostic_backend_sha256": workflow["polish_recovery.py"],
            "claimed_utc": "2026-09-11T08:28:00Z",
        }
        (claim / "context.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in claim_context.items())
        )
        wrapper = self.polish_run / "slurm_attempts/diagnostic" / attempt_id
        wrapper.mkdir(parents=True)
        wrapper_context = {
            "stage": "diagnostic",
            "attempt_id": attempt_id,
            "slurm_job_id": job_id,
            "slurm_job_account": self.config["scheduler"]["slurm_account"],
            "slurm_job_partition": resources["partition"],
            "slurm_job_num_nodes": str(resources["nodes"]),
            "slurm_ntasks": str(resources["ntasks"]),
            "slurm_cpus_per_task": str(resources["cpus_per_task"]),
            "slurm_mem_per_cpu": f"{resources['mem_per_cpu_mb']}M",
            "slurm_timelimit": str(int(resources["walltime_hours"] * 60)),
            "config": str(CONFIG.resolve()),
            "config_sha256": core.sha256_path(CONFIG),
            "campaign_cli": str(Path(core.__file__).resolve()),
            "campaign_cli_sha256": workflow["campaign.py"],
            "submit_script_sha256": workflow["submit.py"],
            "stage_script_sha256": workflow["diagnostic.sbatch"],
            "cluster_env_sha256": workflow["cluster.env"],
            "run_dir": str(self.polish_run),
            "diagnostic_resource_sha256": resource_sha,
            "diagnostic_lineage_sha256": lineage_sha,
            "diagnostic_backend_sha256": workflow["polish_recovery.py"],
            "p3_account_uid": "12345",
            "p3_account_home": "/home/test",
            "stdenv_module": "StdEnv/2023",
            "qe_module": "quantumespresso/7.3.1",
            "p3_venv": "/home/test/venvs/p3",
            "p3_pseudo_dir": "/home/test/pseudos/SSSP-1.3.0-PBE-precision",
            "qe_executable": "pw.x",
            "qe_mpi_launcher": "srun",
            "qe_nk": "1",
            "omp_num_threads": str(resources["cpus_per_task"]),
        }
        (wrapper / "context.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in wrapper_context.items())
        )
        (wrapper / "stdout.log").write_text("")
        (wrapper / "stderr.log").write_text("")
        (wrapper / "exit_code.txt").write_text("0\n")
        (wrapper / "finished_utc.txt").write_text("2026-09-11T08:31:00Z\n")
        return wrapper

    def _write_submission_evidence(self) -> dict:
        context = submit.resolve_context(CONFIG, self.polish_run, "diagnostic")

        def fake_submit(command):
            is_collector = str(command[-1]).endswith("collect.sbatch")
            job_id = "123461" if is_collector else "123460"
            return job_id, {
                "command": list(command),
                "returncode": 0,
                "stdout": f"{job_id};nibi\n",
                "stderr": "",
                "finished_utc": "2026-09-11T08:27:00Z",
            }

        with (
            patch("submit.require_nibi_login"),
            patch(
                "submit.new_attempt_id", side_effect=("diag-1", "collect-diag-1")
            ),
            patch("submit.run_sbatch", side_effect=fake_submit),
        ):
            return submit.execute_submission(
                context,
                "diagnostic",
                expected_config_sha=core.sha256_path(CONFIG),
                task_map=None,
                max_in_flight=None,
            )

    def _write_collector_evidence(self, submission: dict, execution_path: Path) -> None:
        collector = submission["collector"]
        collector_attempt = self.polish_run / "slurm_attempts/collect" / collector[
            "attempt_id"
        ]
        collector_attempt.mkdir(parents=True)
        workflow = self._workflow_hashes()
        resources = self.config["scheduler"]["diagnostic_resources"]
        record = Path(submission["record_dir"])
        collector_context = {
            "stage": "collect",
            "attempt_id": collector["attempt_id"],
            "slurm_job_id": collector["job_id"],
            "slurm_job_account": self.config["scheduler"]["slurm_account"],
            "config_sha256": core.sha256_path(CONFIG),
            "run_dir": str(self.polish_run),
            "primary_stage": "diagnostic",
            "primary_attempt_id": "diag-1",
            "primary_job_id": "123460",
            "primary_request_sha256": core.sha256_path(record / "request.json"),
            "primary_result_sha256": core.sha256_path(
                record / "primary_result.json"
            ),
            "primary_stage_script_sha256": workflow["diagnostic.sbatch"],
            "campaign_cli_sha256": workflow["campaign.py"],
            "submit_script_sha256": workflow["submit.py"],
            "cluster_env_sha256": workflow["cluster.env"],
            "stage_script_sha256": core.sha256_path(
                Path(core.__file__).resolve().parent / "slurm/collect.sbatch"
            ),
            "diagnostic_resource_sha256": core.canonical_sha256(resources),
            "diagnostic_lineage_sha256": core.sha256_path(
                self.polish_run / polish.LINEAGE_RECEIPT
            ),
            "diagnostic_backend_sha256": workflow["polish_recovery.py"],
            "p3_account_uid": "12345",
            "p3_account_home": "/home/test",
            "stdenv_module": "StdEnv/2023",
            "qe_module": "quantumespresso/7.3.1",
            "p3_venv": "/home/test/venvs/p3",
            "p3_pseudo_dir": "/home/test/pseudos/SSSP-1.3.0-PBE-precision",
            "qe_executable": "pw.x",
            "qe_mpi_launcher": "srun",
            "qe_nk": "1",
            "omp_num_threads": str(resources["cpus_per_task"]),
        }
        (collector_attempt / "context.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in collector_context.items())
        )
        (collector_attempt / "stdout.log").write_text("")
        (collector_attempt / "stderr.log").write_text("")
        accounting = collector_attempt / "scheduler-accounting.psv"
        accounting.write_text(
            "|".join(core.DIAGNOSTIC_SACCT_FIELDS)
            + "\n"
            + "123460|123460|COMPLETED|0:0|1200|32||"
            + f"{self.config['scheduler']['slurm_account']}|"
            + f"{resources['partition']}|1|32|62.50G|120\n"
        )
        accounting_status = collector_attempt / "scheduler-accounting.exit_code.txt"
        accounting_status.write_text("0\n")
        with patch.dict(
            os.environ,
            {
                "SLURM_JOB_ID": collector["job_id"],
                "SLURM_JOB_NODELIST": "c002",
                "P3_ATTEMPT_DIR": str(collector_attempt),
            },
        ):
            report = core.command_collect(
                CONFIG,
                self.polish_run,
                primary_stage="diagnostic",
                primary_attempt_id="diag-1",
                primary_job_id="123460",
                scheduler_accounting=accounting,
                scheduler_accounting_status=accounting_status,
                expected_primary_request_sha256=core.sha256_path(
                    record / "request.json"
                ),
                expected_primary_result_sha256=core.sha256_path(
                    record / "primary_result.json"
                ),
                expected_primary_stage_script_sha256=workflow[
                    "diagnostic.sbatch"
                ],
            )
        self.assertTrue(report["diagnostic_execution_complete"])
        self.assertEqual(
            report["primary"]["diagnostic_execution_sha256"],
            core.sha256_path(execution_path),
        )
        (collector_attempt / "exit_code.txt").write_text("0\n")
        (collector_attempt / "finished_utc.txt").write_text(
            "2026-09-11T08:32:00Z\n"
        )

    def _write_diagnostic_execution(
        self, *, include_submission_chain: bool = True
    ) -> Path:
        submission = (
            self._write_submission_evidence() if include_submission_chain else None
        )
        if include_submission_chain:
            self._write_dispatch_evidence()
        attempt = self.polish_run / "diagnostic/attempts/diag-1"
        attempt.mkdir()
        resources = self.config["scheduler"]["diagnostic_resources"]
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
            "resources": {
                "policy_sha256": core.canonical_sha256(resources),
                "configured": resources,
                "observed_allocation": {
                    **{
                        key: resources[key]
                        for key in (
                            "partition",
                            "nodes",
                            "ntasks",
                            "cpus_per_task",
                            "mem_per_cpu_mb",
                        )
                    },
                    "account": self.config["scheduler"]["slurm_account"],
                    "time_limit_minutes": int(resources["walltime_hours"] * 60),
                },
            },
            "workflow_sha256": self._workflow_hashes(),
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
        if submission is not None:
            self._write_collector_evidence(
                submission, attempt / polish.DIAGNOSTIC_EXECUTION
            )
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

    def _rebind_collected_execution_sha(self, execution_path: Path) -> str:
        execution_sha = core.sha256_path(execution_path)
        collector_attempts = list(
            (self.polish_run / "slurm_attempts/collect").iterdir()
        )
        self.assertEqual(len(collector_attempts), 1)
        for filename in ("collection.json", "collection_receipt.json"):
            path = collector_attempts[0] / filename
            collection = core.load_json(path)
            collection["primary"]["diagnostic_execution_sha256"] = execution_sha
            self._write_json(path, collection)
        return execution_sha

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
        archived_pseudo_dir = self.polish_run / "lineage_source/pseudopotentials"
        self.assertIn(
            f"pseudo_dir = '{archived_pseudo_dir}'",
            (self.polish_run / "diagnostic/inputs/baseline.in").read_text(),
        )
        lineage = core.load_json(self.polish_run / polish.LINEAGE_RECEIPT)
        for record in lineage["pseudopotential_archive"].values():
            self.assertTrue((self.polish_run / record["relative_path"]).is_file())
        self.assertFalse((self.polish_run / core.RUN_MANIFEST).exists())
        self.assertFalse((self.polish_run / "relax/final").exists())
        self.assertFalse(result["structure_accepted"])

    def test_archived_pseudopotential_mutation_blocks_diagnostic_submission(self) -> None:
        self._prepare()
        lineage = core.load_json(self.polish_run / polish.LINEAGE_RECEIPT)
        first = next(iter(lineage["pseudopotential_archive"].values()))
        archived = self.polish_run / first["relative_path"]
        with archived.open("ab") as handle:
            handle.write(b"tampered\n")
        with self.assertRaisesRegex(
            core.CampaignError, "archived pseudopotential hash mismatch"
        ):
            polish.verify_diagnostic_submission_ready(CONFIG, self.polish_run)

    def test_diagnostic_submission_ready_is_prepare_lineage_only_and_one_shot(self) -> None:
        self._prepare()
        ready = polish.verify_diagnostic_submission_ready(CONFIG, self.polish_run)
        self.assertEqual(ready["material"], "Rb2Cu2SnS4")
        self.assertFalse(ready["structure_accepted"])
        self.assertFalse(ready["preflight_unlocked"])
        self.assertEqual(ready["maximum_diagnostic_attempts"], 1)
        self.assertRegex(ready["lineage_sha256"], r"^[0-9a-f]{64}$")

        marker = self.polish_run / "diagnostic/attempts/interrupted"
        marker.write_text("ambiguous consumed attempt\n")
        with self.assertRaisesRegex(core.CampaignError, "already been consumed"):
            polish.verify_diagnostic_submission_ready(CONFIG, self.polish_run)
        marker.unlink()
        (self.polish_run / core.RUN_MANIFEST).write_text("{}\n")
        with self.assertRaisesRegex(core.CampaignError, "already released"):
            polish.verify_diagnostic_submission_ready(CONFIG, self.polish_run)

    def test_diagnostic_submission_ready_rejects_prior_dispatch_evidence(self) -> None:
        for relative, message in (
            ("submissions/diagnostic/attempt-1/request.json", "submission"),
            ("slurm_attempts/diagnostic/attempt-1/context.tsv", "Slurm attempt"),
            ("diagnostic/dispatch_claim/context.tsv", "dispatch"),
        ):
            with self.subTest(relative=relative):
                self.tearDown()
                self.setUp()
                self._prepare()
                marker = self.polish_run / relative
                marker.parent.mkdir(parents=True)
                marker.write_text("consumed\n")
                with self.assertRaisesRegex(core.CampaignError, message):
                    polish.verify_diagnostic_submission_ready(CONFIG, self.polish_run)

    def test_diagnostic_submission_lock_file_alone_does_not_consume_attempt(self) -> None:
        self._prepare()
        lock = self.polish_run / "submissions/diagnostic/.submission.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("")
        ready = polish.verify_diagnostic_submission_ready(CONFIG, self.polish_run)
        self.assertEqual(ready["maximum_diagnostic_attempts"], 1)

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

    def test_relax_plan_rejects_symlinked_polish_gate_components(self) -> None:
        for case in ("gate", "parent"):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                self._prepare()
                self._write_passing_diagnostic()
                polish.release_polish(CONFIG, self.polish_run)
                if case == "gate":
                    target = self.polish_run / "diagnostic/final/gate.json"
                    backup = target.with_name("gate.backup.json")
                else:
                    target = self.polish_run / "diagnostic/final"
                    backup = self.polish_run / "diagnostic/final.backup"
                target.rename(backup)
                target.symlink_to(backup, target_is_directory=case == "parent")
                context = submit.resolve_context(CONFIG, self.polish_run, "relax")
                with self.assertRaisesRegex(submit.SubmissionError, "symlink"):
                    submit.stage_plan(context, "relax", attempt_id="blocked-polish")

    def test_relax_plan_treats_any_prior_slurm_entry_as_consumed(self) -> None:
        self._prepare()
        self._write_passing_diagnostic()
        polish.release_polish(CONFIG, self.polish_run)
        prior = self.polish_run / "slurm_attempts/relax/ambiguous-prior-attempt"
        prior.parent.mkdir(parents=True)
        prior.write_text("ambiguous evidence\n")
        context = submit.resolve_context(CONFIG, self.polish_run, "relax")
        with self.assertRaisesRegex(submit.SubmissionError, "already been consumed"):
            submit.stage_plan(context, "relax", attempt_id="blocked-polish")

    def test_finalize_requires_complete_dispatch_and_collection_chain(self) -> None:
        self._prepare()
        attempt = self._write_diagnostic_execution(include_submission_chain=False)
        with self.assertRaisesRegex(core.CampaignError, "submission root is missing"):
            polish.finalize_diagnostic(
                CONFIG,
                self.polish_run,
                attempt_id="diag-1",
                expected_execution_sha256=core.sha256_path(
                    attempt / polish.DIAGNOSTIC_EXECUTION
                ),
            )
        self.assertFalse((self.polish_run / "diagnostic/final").exists())

    def test_finalize_rejects_symlinked_diagnostic_evidence_components(self) -> None:
        relatives = (
            "submissions/diagnostic/diag-1",
            "slurm_attempts/diagnostic/diag-1",
            "diagnostic/dispatch_claim",
            "diagnostic/attempts/diag-1",
        )
        for index, relative in enumerate(relatives):
            with self.subTest(relative=relative):
                self.tearDown()
                self.setUp()
                self._prepare()
                attempt = self._write_diagnostic_execution()
                target = self.polish_run / relative
                backup = self.root / f"symlink-backup-{index}"
                target.rename(backup)
                target.symlink_to(backup, target_is_directory=True)
                with self.assertRaisesRegex(core.CampaignError, "symlink"):
                    polish.finalize_diagnostic(
                        CONFIG,
                        self.polish_run,
                        attempt_id="diag-1",
                        expected_execution_sha256=core.sha256_path(
                            backup / polish.DIAGNOSTIC_EXECUTION
                            if relative == "diagnostic/attempts/diag-1"
                            else attempt / polish.DIAGNOSTIC_EXECUTION
                        ),
                    )

    def test_finalize_rejects_extra_collector_export_even_if_records_are_rehashed(self) -> None:
        self._prepare()
        attempt = self._write_diagnostic_execution()
        record = self.polish_run / "submissions/diagnostic/diag-1"
        collector_request_path = record / "collector_request.json"
        collector_result_path = record / "collector_result.json"
        summary_path = record / "submission.json"
        collector_request = core.load_json(collector_request_path)
        collector_result = core.load_json(collector_result_path)
        summary = core.load_json(summary_path)
        command = list(collector_request["command"])
        export_index = next(
            index
            for index, item in enumerate(command)
            if item.startswith("--export=")
        )
        command[export_index] += ",BASH_ENV=/tmp/injected"
        collector_request["command"] = command
        self._write_json(collector_request_path, collector_request)
        collector_result["command"] = command
        self._write_json(collector_result_path, collector_result)
        summary["collector"]["command"] = command
        summary["collector"]["request_sha256"] = core.sha256_path(
            collector_request_path
        )
        summary["collector"]["result_sha256"] = core.sha256_path(
            collector_result_path
        )
        self._write_json(summary_path, summary)
        with self.assertRaisesRegex(core.CampaignError, "collector dispatch command"):
            polish.finalize_diagnostic(
                CONFIG,
                self.polish_run,
                attempt_id="diag-1",
                expected_execution_sha256=core.sha256_path(
                    attempt / polish.DIAGNOSTIC_EXECUTION
                ),
            )

    def test_diagnostic_allows_only_one_fresh_attempt_directory(self) -> None:
        self._prepare()
        (self.polish_run / "diagnostic/attempts/already-used").mkdir()
        with patch.dict(
            os.environ,
            {**self._diagnostic_environment(), "SLURM_JOB_ID": "123459"},
        ), self.assertRaisesRegex(core.CampaignError, "already been consumed"):
            polish.run_diagnostic(CONFIG, self.polish_run, attempt_id="second")

    def test_run_diagnostic_captures_slurm_identity_and_exact_process_records(self) -> None:
        self._prepare()
        wrapper = self._write_dispatch_evidence("captured", "7654321")

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
                {
                    **self._diagnostic_environment(),
                    "SLURM_JOB_ID": "7654321",
                    "SLURM_JOB_NODELIST": "c[001-002]",
                    "P3_ATTEMPT_DIR": str(wrapper),
                },
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

    def test_diagnostic_rejects_unsigned_or_mismatched_allocation_before_attempt(self) -> None:
        self._prepare()
        base = self._diagnostic_environment()
        base.pop("P3_DIAGNOSTIC_RESOURCE_SHA256")
        for change, message in (
            ({}, "resource-policy SHA256"),
            (
                {
                    "P3_DIAGNOSTIC_RESOURCE_SHA256": core.canonical_sha256(
                        self.config["scheduler"]["diagnostic_resources"]
                    ),
                    "SLURM_NTASKS": "16",
                },
                "configured ntasks",
            ),
        ):
            environment = {**base, **change}
            with self.subTest(change=change), patch.dict(
                os.environ, environment, clear=True
            ), self.assertRaisesRegex(core.CampaignError, message):
                polish.run_diagnostic(
                    CONFIG, self.polish_run, attempt_id="not-created"
                )
            self.assertFalse(
                (self.polish_run / "diagnostic/attempts/not-created").exists()
            )

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
                    message = "collection receipt evidence mismatch"
                else:
                    execution["slurm"]["job_id"] = "0"
                    message = "collection receipt evidence mismatch"
                self._write_json(execution_path, execution)
                with self.assertRaisesRegex(core.CampaignError, message):
                    polish.finalize_diagnostic(
                        CONFIG,
                        self.polish_run,
                        attempt_id="diag-1",
                        expected_execution_sha256=core.sha256_path(execution_path),
                    )

    def test_finalize_binds_execution_to_submitted_primary_job_id(self) -> None:
        self._prepare()
        attempt = self._write_diagnostic_execution()
        execution_path = attempt / polish.DIAGNOSTIC_EXECUTION
        execution = core.load_json(execution_path)
        execution["slurm"]["job_id"] = "999999"
        self._write_json(execution_path, execution)
        execution_sha = self._rebind_collected_execution_sha(execution_path)

        with self.assertRaisesRegex(
            core.CampaignError, "execution Slurm job ID differs"
        ):
            polish.finalize_diagnostic(
                CONFIG,
                self.polish_run,
                attempt_id="diag-1",
                expected_execution_sha256=execution_sha,
            )

    def test_finalize_uses_versioned_qe_command_not_caller_environment(self) -> None:
        self._prepare()
        attempt = self._write_diagnostic_execution()
        execution_path = attempt / polish.DIAGNOSTIC_EXECUTION
        execution = core.load_json(execution_path)
        record = execution["runs"]["baseline-a"]
        record["command"] = ["srun", "other-pw.x", "-nk", "1", "-in", "scf.in"]
        record["process"]["command"] = record["command"]
        process_path = attempt / "baseline-a/scf.process.json"
        self._write_json(process_path, record["process"])
        record["process_record_sha256"] = core.sha256_path(process_path)
        self._write_json(execution_path, execution)
        execution_sha = self._rebind_collected_execution_sha(execution_path)
        with patch.dict(os.environ, {"QE_EXECUTABLE": "other-pw.x"}):
            with self.assertRaisesRegex(core.CampaignError, "process identity"):
                polish.finalize_diagnostic(
                    CONFIG,
                    self.polish_run,
                    attempt_id="diag-1",
                    expected_execution_sha256=execution_sha,
                )

    def test_finalize_binds_runtime_paths_to_recorded_account_home(self) -> None:
        self._prepare()
        attempt = self._write_diagnostic_execution()
        wrapper = self.polish_run / "slurm_attempts/diagnostic/diag-1"
        wrapper_context = polish._context(wrapper / "context.tsv")
        wrapper_context["p3_venv"] = "/tmp/evil/venvs/p3"
        wrapper_context["p3_pseudo_dir"] = (
            "/tmp/evil/pseudos/SSSP-1.3.0-PBE-precision"
        )
        (wrapper / "context.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in wrapper_context.items())
        )
        collector_attempt = next(
            (self.polish_run / "slurm_attempts/collect").iterdir()
        )
        collector_context = polish._context(collector_attempt / "context.tsv")
        collector_context["p3_venv"] = wrapper_context["p3_venv"]
        collector_context["p3_pseudo_dir"] = wrapper_context["p3_pseudo_dir"]
        (collector_attempt / "context.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in collector_context.items())
        )
        for filename in ("collection.json", "collection_receipt.json"):
            path = collector_attempt / filename
            collection = core.load_json(path)
            collection["entry"]["context"] = wrapper_context
            collection["entry"]["evidence"] = core._hash_present_evidence(
                wrapper,
                (
                    "context.tsv",
                    "exit_code.txt",
                    "finished_utc.txt",
                    "stdout.log",
                    "stderr.log",
                ),
            )
            self._write_json(path, collection)
        with self.assertRaisesRegex(core.CampaignError, "derived runtime path"):
            polish.finalize_diagnostic(
                CONFIG,
                self.polish_run,
                attempt_id="diag-1",
                expected_execution_sha256=core.sha256_path(
                    attempt / polish.DIAGNOSTIC_EXECUTION
                ),
            )

    def test_finalize_requires_structure_neutral_execution_schema(self) -> None:
        for field, value in (("schema_version", 999), ("structure_accepted", True)):
            with self.subTest(field=field):
                self.tearDown()
                self.setUp()
                self._prepare()
                attempt = self._write_diagnostic_execution()
                execution_path = attempt / polish.DIAGNOSTIC_EXECUTION
                execution = core.load_json(execution_path)
                execution[field] = value
                self._write_json(execution_path, execution)
                execution_sha = self._rebind_collected_execution_sha(execution_path)
                with self.assertRaisesRegex(
                    core.CampaignError, "schema version 1 and structure-neutral"
                ):
                    polish.finalize_diagnostic(
                        CONFIG,
                        self.polish_run,
                        attempt_id="diag-1",
                        expected_execution_sha256=execution_sha,
                    )

    def test_finalize_binds_collection_scope_and_nonpublication_claims(self) -> None:
        self._prepare()
        attempt = self._write_diagnostic_execution()
        collector_attempt = next(
            (self.polish_run / "slurm_attempts/collect").iterdir()
        )
        for filename in ("collection.json", "collection_receipt.json"):
            path = collector_attempt / filename
            collection = core.load_json(path)
            collection.update(
                {
                    "material": "WRONG",
                    "scientific_gate_published": True,
                    "structure_accepted": True,
                    "preflight_unlocked": True,
                }
            )
            collection["submission"]["record_dir"] = "/wrong/submission"
            collection["primary"]["wrapper_attempt"] = "/wrong/wrapper"
            self._write_json(path, collection)
        with self.assertRaisesRegex(core.CampaignError, "collection receipt evidence"):
            polish.finalize_diagnostic(
                CONFIG,
                self.polish_run,
                attempt_id="diag-1",
                expected_execution_sha256=core.sha256_path(
                    attempt / polish.DIAGNOSTIC_EXECUTION
                ),
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
                    message = "execution/submission chain hash mismatch"
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

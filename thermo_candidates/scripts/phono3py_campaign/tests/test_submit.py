from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from campaign import CampaignError, _force_submission_binding
from submit import (
    SLURM_DIR,
    StagePlan,
    SubmissionContext,
    SubmissionError,
    build_parser,
    canonical_sha256,
    ensure_no_active_duplicate,
    execute_submission,
    plan_report,
    require_force_gate,
    require_nibi_login,
    resolve_context,
    sbatch_command,
    scheduler_job_is_active,
    sha256_path,
    stage_plan,
    validate_force_bundle,
    validate_task_map,
)


CONFIG_SHA = hashlib.sha256(b"{}\n").hexdigest()


class SubmissionTests(unittest.TestCase):
    def test_terminal_job_missing_from_squeue_falls_back_to_sacct(self) -> None:
        missing_from_queue = subprocess.CompletedProcess(
            [],
            1,
            stdout="",
            stderr="slurm_load_jobs error: Invalid job id specified\n",
        )
        terminal_in_accounting = subprocess.CompletedProcess(
            [], 0, stdout="FAILED|\n", stderr=""
        )
        with patch(
            "submit.subprocess.run",
            side_effect=[missing_from_queue, terminal_in_accounting],
        ) as run:
            self.assertFalse(scheduler_job_is_active("21657046"))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][0], "sacct")

    def test_unrelated_squeue_error_still_blocks_duplicate_check(self) -> None:
        scheduler_error = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="Unable to contact slurm controller\n"
        )
        with patch("submit.subprocess.run", return_value=scheduler_error) as run:
            with self.assertRaisesRegex(SubmissionError, "squeue failed"):
                scheduler_job_is_active("21657046")
        self.assertEqual(run.call_count, 1)

    def test_preflight_submission_accepts_immutable_upstream_workflow_hashes(self) -> None:
        with patch(
            "submit.validate_config",
            return_value=(self.config, {"config_sha256": CONFIG_SHA}),
        ), patch(
            "submit.verify_manifest",
            return_value={"material": "Example"},
        ) as strict, patch(
            "submit.verify_upstream_manifest",
            return_value={"material": "Example"},
        ) as upstream:
            context = resolve_context(self.config_path, self.run_dir, "preflight")
        self.assertEqual(context.manifest["material"], "Example")
        strict.assert_not_called()
        upstream.assert_called_once_with(
            self.config,
            self.config_path.resolve(),
            self.run_dir.resolve(),
            stage="preflight",
        )

    def test_diagnostic_context_uses_prepared_lineage_without_run_manifest(self) -> None:
        (self.run_dir / "run_manifest.json").unlink()
        ready = {
            "material": "Example",
            "config_sha256": CONFIG_SHA,
            "lineage_sha256": "d" * 64,
        }
        with patch(
            "submit.validate_config",
            return_value=(self.config, {"config_sha256": CONFIG_SHA}),
        ), patch(
            "polish_recovery.verify_diagnostic_submission_ready",
            return_value=ready,
        ) as verify:
            context = resolve_context(self.config_path, self.run_dir, "diagnostic")
        self.assertEqual(context.manifest, ready)
        verify.assert_called_once_with(
            self.config_path.resolve(), self.run_dir.resolve()
        )

    def test_accepts_real_nibi_login_hostname_but_not_other_hosts(self) -> None:
        with patch.dict("submit.os.environ", {}, clear=True), patch(
            "submit.socket.getfqdn", return_value="ic-l5.nibi.sharcnet"
        ):
            require_nibi_login()
        with patch.dict("submit.os.environ", {}, clear=True), patch(
            "submit.socket.getfqdn", return_value="l5"
        ):
            require_nibi_login()
        with patch.dict("submit.os.environ", {}, clear=True), patch(
            "submit.socket.getfqdn", return_value="ic-l5.nibi.sharcnet.example.org"
        ):
            with self.assertRaisesRegex(SubmissionError, "restricted to a Nibi login"):
                require_nibi_login()
        with patch.dict("submit.os.environ", {"SLURM_JOB_ID": "123"}, clear=True):
            with self.assertRaisesRegex(SubmissionError, "not inside a job"):
                require_nibi_login()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config_path = root / "campaign.json"
        self.config_path.write_text("{}\n")
        self.run_dir = root / "run with spaces"
        self.run_dir.mkdir()
        (self.run_dir / "run_manifest.json").write_text(
            json.dumps({"config_sha256": CONFIG_SHA}) + "\n"
        )
        self.config = {
            "material": {"formula": "Example"},
            "scheduler": {
                "cluster": "nibi",
                "slurm_account": "def-kleinke_cpu",
                "diagnostic_resources": {
                    "partition": "cpubase_bycore_b2",
                    "nodes": 1,
                    "ntasks": 32,
                    "cpus_per_task": 1,
                    "mem_per_cpu_mb": 2000,
                    "walltime_hours": 2,
                    "maximum_core_hours": 64,
                },
            },
            "reviewed_bfgs_polish": {},
            "displacements": {"hard_cap": 8},
            "resource_budget": {
                "selection_required_before_force_submission": False,
                "approved_total_core_hours_per_material": 10000,
                "initial_timing_and_noise_batch": {
                    "maximum_new_scf_tasks": 6,
                    "maximum_concurrent_force_tasks_per_material": 2,
                },
                "pilot_batch_maximum_new_scf_tasks": 32,
                "production_first_batch_maximum_tasks": 32,
                "production_later_batch_maximum_tasks": 64,
                "maximum_technical_retries_per_task": 1,
            },
            "production": {
                "selection_required": False,
                "selected_supercell": "candidate-a",
                "selected_cutoff": "cutoff-a",
                "automatic_submission_allowed": True,
            },
        }
        self.context = SubmissionContext(
            config_path=self.config_path.resolve(),
            run_dir=self.run_dir.resolve(),
            config=self.config,
            manifest={"material": "Example", "config_sha256": CONFIG_SHA},
            config_sha256=CONFIG_SHA,
        )
        self.signed_audits = {}
        self.selection_audits = {}
        self.initial_releases = {}
        self.signed_auditor = patch("force_backend.audit_signed_pilot_dataset", side_effect=self.audit_signed_fixture).start()
        self.initial_release_replayer = patch(
            "initial_pilot.replay_initial_pilot_release",
            side_effect=self.replay_initial_release_fixture,
        ).start()
        patch("force_backend.core.validate_config", return_value=(self.config, {})).start()
        self.selection_auditor = patch("force_backend.validate_selection_evidence", side_effect=lambda path, *args:
              copy.deepcopy(self.selection_audits[str(path)])).start()
        self.addCleanup(patch.stopall)

    def audit_signed_fixture(self, dataset, run_dir, config, settings, spec, *, expected_manifest_sha256):
        from force_backend import _match
        _match(Path(dataset)/"pilot_dataset_manifest.json", expected_manifest_sha256)
        return copy.deepcopy(self.signed_audits[str(Path(dataset).resolve())])

    def replay_initial_release_fixture(
        self, path: Path, *, expected_release_sha256: str, **kwargs
    ):
        resolved = Path(path).resolve()
        if sha256_path(resolved) != expected_release_sha256:
            raise CampaignError("pilot release hash mismatch")
        return copy.deepcopy(self.initial_releases[str(resolved)])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def pass_relax_gate(self) -> None:
        final = self.run_dir / "relax" / "final"
        final.mkdir(parents=True)
        (final / "gate.json").write_text('{"pass": true}\n')
        (final / "unitcell.in").write_text("unit cell\n")

    def write_force_final(self) -> tuple[Path, Path]:
        def write(name: str) -> Path:
            path = self.run_dir / "force-evidence" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"synthetic {name}\n")
            return path.resolve()

        def ref(path: Path) -> dict[str, str]:
            return {"path": str(path), "sha256": sha256_path(path)}

        backend_names = (
            "force_finalize.py", "campaign.py", "force_backend.py", "submit.py",
            "postprocess_backend.py", "qe_input.py", "qe_output.py",
        )
        backends = {
            str((SLURM_DIR.parent / name).resolve()): sha256_path(SLURM_DIR.parent / name)
            for name in backend_names
        }
        plan = write("plan.json")
        receipt = (self.run_dir / "slurm_attempts/force-finalize/final-1/force_finalize_receipt.json").resolve()
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({
            "schema_version": 1, "stage": "force_finalize", "pass": True,
            "material": "Example", "plan": str(plan.resolve()), "plan_sha256": sha256_path(plan),
            "force_dataset_ready_for_fc2_fc3_construction": True,
            "scientific_results_claimed": False, "audit_backend_sha256": backends,
            "force_finalize_backend_sha256": sha256_path(SLURM_DIR.parent / "force_finalize.py"),
        }))
        accepted = {name: ref(write(f"accepted-{name}")) for name in ("gate", "provenance", "unitcell")}
        named = {name: ref(write(name)) for name in (
            "preflight_inventory", "preflight_result", "dataset", "selection_receipt",
        )}
        canonical = {}
        for stem in ("input", "output", "stderr"):
            path = write(f"canonical-{stem}")
            canonical[f"{stem}_path"] = str(path)
            canonical[f"{stem}_sha256"] = sha256_path(path)
        artifact = {"displacement_id": 1}
        for stem in ("input", "output", "stderr"):
            path = write(f"artifact-{stem}")
            artifact[f"{stem}_path"] = str(path)
            artifact[f"{stem}_sha256"] = sha256_path(path)
        batch_names = (
            "collection", "force_manifest", "task_map", "budget_receipt",
            "budget_ledger_reservation", "submission_request", "submission_result",
            "submission_summary", "collector_request", "collector_result",
            "scheduler_accounting", "scheduler_accounting_status",
        )
        batch = {"batch_id": "batch-1", **{name: ref(write(name)) for name in batch_names}}
        raw_dir = (self.run_dir / "force-evidence/raw").resolve()
        raw_dir.mkdir()
        raw_file = raw_dir / "scf.out"
        raw_file.write_text("raw force\n")
        batch["raw_artifacts"] = [{
            "task_id": 0, "attempt_path": str(raw_dir),
            "files_sha256": {raw_file.name: sha256_path(raw_file)},
        }]
        final = self.run_dir / "force/final"
        final.mkdir(parents=True)
        index_path = final / "index.json"
        index = {
            "schema_version": 1, "stage": "force_dataset_index", "material": "Example",
            "config": str(self.config_path.resolve()), "config_sha256": self.context.config_sha256,
            "force_dataset_ready_for_fc2_fc3_construction": True,
            "plan": str(plan), "plan_sha256": sha256_path(plan),
            "finalize_receipt": ref(receipt), "audit_backend_sha256": backends,
            "force_finalize_backend_sha256": sha256_path(SLURM_DIR.parent / "force_finalize.py"),
            "accepted_structure": accepted, **named, "canonical_pristine": canonical,
            "artifacts": [artifact], "required_fc3_displacement_ids": [1], "batches": [batch],
        }
        index_path.write_text(json.dumps(index))
        (final / "gate.json").write_text(json.dumps({
            "schema_version": 1, "stage": "force_dataset_gate", "pass": True,
            "production_dataset_complete": True,
            "eligible_for_force_constant_construction": True,
            "scientific_results_claimed": False,
            "scope": "audited production force dataset readiness only",
            "material": "Example", "config_sha256": self.context.config_sha256,
            "index_sha256": sha256_path(index_path), "plan_sha256": sha256_path(plan),
            "finalize_receipt_sha256": sha256_path(receipt),
            "audit_backend_sha256": backends,
            "force_finalize_backend_sha256": sha256_path(SLURM_DIR.parent / "force_finalize.py"),
        }))
        return index_path, Path(batch["budget_ledger_reservation"]["path"])

    def write_task_map(self, count: int = 3) -> Path:
        path = self.run_dir / "force" / "task_map.tsv"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = ["task_id\tinput"] + [f"{index}\tdisp-{index:05d}.in" for index in range(count)]
        path.write_text("\n".join(rows) + "\n")
        return path

    def write_force_bundle(self, count: int = 3, *, mode: str = "production", pristine_count: int = 1,
                           duplicate_ids: list[int] | None = None) -> Path:
        path = self.write_task_map(count)
        bundle = path.parent.resolve()
        duplicate_ids = duplicate_ids or []
        original_count = count - pristine_count - len(duplicate_ids)
        original_ids = (
            [1, 3]
            if mode == "pilot"
            and count == 6
            and pristine_count == 2
            and duplicate_ids == [1, 3]
            else list(range(1, original_count + 1))
        )
        is_initial = (
            mode == "pilot"
            and count == 6
            and pristine_count == 2
            and duplicate_ids == [1, 3]
        )
        if is_initial:
            self.config["resource_budget"][
                "approved_total_core_hours_per_material"
            ] = None
        displacement_ids = [0]*pristine_count + original_ids + duplicate_ids
        for index, displacement_id in enumerate(displacement_ids):
            # Inputs are real files with measured hashes; duplicates intentionally
            # repeat the identical original input bytes in another task file.
            (bundle / f"input-{index}.in").write_text(f"! Synthetic input for displacement {displacement_id}\n&CONTROL\n calculation='scf'\n/\n")
        tasks = [
            {
                "task_id": index,
                "displacement_id": displacement_id,
                "role": "pristine" if displacement_id == 0 else "displacement",
                "input_path": str(bundle / f"input-{index}.in"),
                "input_sha256": sha256_path(bundle / f"input-{index}.in"),
            }
            for index, displacement_id in enumerate(displacement_ids)
        ]
        columns = ("task_id", "displacement_id", "role", "input_path", "input_sha256")
        path.write_text("\t".join(columns) + "\n" + "".join("\t".join(str(task[key]) for key in columns) + "\n" for task in tasks))
        workflow = SLURM_DIR.parent / "campaign.py"
        receipt = {
            "schema_version": 1,
            "material": "Example",
            "phase": "production" if mode == "production" else "initial" if is_initial else "validation",
            "task_map_sha256": sha256_path(path),
            "task_count": count,
            "mpi_ranks": 32,
            "maximum_concurrency": 2,
            "walltime_hours": 1,
            "maximum_technical_retries_per_task": 1,
            "reserved_core_hours": count * 32 * 1 * 2,
            "reserved_core_hours_before": 0,
            "charged_core_hours_before": 0,
            "used_core_hours": 0,
            "approved_total_core_hours": self.config["resource_budget"]["approved_total_core_hours_per_material"],
            "production_batch_number": 1 if mode == "production" else None,
            "production_input_hashes": [task["input_sha256"] for task in tasks if task["displacement_id"] != 0] if mode == "production" else [],
            "resource_policy_sha256": canonical_sha256(self.config["resource_budget"]),
        }
        receipt_path = bundle / "budget_receipt.json"
        receipt_path.write_text(json.dumps(receipt))
        backend = SLURM_DIR.parent / "force_backend.py"
        manifest = {
            "schema_version": 1,
            "stage": "force",
            "mode": mode,
            "material": "Example",
            "config_sha256": CONFIG_SHA,
            "task_map_sha256": sha256_path(path),
            "task_count": count,
            "tasks": tasks,
            "settings":{"synthetic":True},
            "pilot_spec": {"displacement_ids":original_ids, "duplicate_displacement_ids":duplicate_ids,
                           "pristine_repetitions":pristine_count} if mode == "pilot" else None,
            "backend_sha256": sha256_path(backend),
            "workflow_sha256": {str(workflow): sha256_path(workflow)},
            "budget_receipt_sha256": sha256_path(receipt_path),
            "selection_validation": {"pass": True} if mode == "production" else None,
        }
        if mode == "pilot":
            signed_dir = bundle / "signed_dataset"
            signed_dir.mkdir(exist_ok=True)
            signed_manifest = signed_dir / "pilot_dataset_manifest.json"
            signed_manifest.write_text(json.dumps({"synthetic":True, "ids":original_ids}))
            signed = {"dataset_dir":str(signed_dir), "expected_manifest_sha256":sha256_path(signed_manifest),
                "audit_result":{"healthy":True, "pilot_only":True},
                "files_sha256":{str(signed_manifest):sha256_path(signed_manifest)},
                "task_kinds":{"0":"pristine", **{str(i):"single" if i == 1 else "double" for i in original_ids}}}
            manifest["signed_pilot_dataset"] = signed
            manifest["evidence_sha256"] = signed["files_sha256"]
            pilot_code = SLURM_DIR.parent / "pilot_dataset.py"
            manifest["workflow_sha256"][str(pilot_code)] = sha256_path(pilot_code)
            self.signed_audits[str(signed_dir)] = copy.deepcopy(signed)
            if receipt["phase"] == "initial":
                receipt.update(
                    walltime_hours=2,
                    reserved_core_hours=768,
                    approved_total_core_hours=None,
                )
                receipt_path.write_text(json.dumps(receipt))
                manifest["budget_receipt_sha256"] = sha256_path(receipt_path)
                release_path = self.run_dir / "initial_pilot_release.json"
                release_path.write_text('{"synthetic_release":true}\n')
                identity = "9" * 64
                release = {
                    "scope": {
                        "mode": "pilot",
                        "phase": "initial",
                        "task_count": 6,
                        "task_displacement_ids": [0, 0, 1, 3, 1, 3],
                        "validation_authorized": False,
                        "production_authorized": False,
                    },
                    "force_pilot_spec": copy.deepcopy(manifest["pilot_spec"]),
                    "contract": {
                        "resources": {
                            "mpi_ranks": 32,
                            "walltime_hours": 2,
                            "max_concurrency": 2,
                            "maximum_technical_retries_per_task": 1,
                            "maximum_reserved_core_hours": 768,
                        }
                    },
                    "consumption_identity": identity,
                }
                self.initial_releases[str(release_path.resolve())] = release
                release_binding = {
                    "path": str(release_path.resolve()),
                    "sha256": sha256_path(release_path),
                    "consumption_identity": identity,
                }
                consumption_path = (
                    self.run_dir / ".initial_pilot_releases" / f"{identity}.json"
                )
                consumption_path.parent.mkdir(exist_ok=True)
                consumption_path.write_text(json.dumps({
                    "schema_version": 1,
                    "stage": "initial_pilot_release_consumption",
                    "consumption_identity": identity,
                    "release_path": str(release_path.resolve()),
                    "release_sha256": sha256_path(release_path),
                    "dataset_dir": str(signed_dir.resolve()),
                    "created_utc": "2026-09-14T00:00:00Z",
                }))
                signed_binding = {
                    **release_binding,
                    "consumption_path": str(consumption_path.resolve()),
                    "consumption_sha256": sha256_path(consumption_path),
                }
                signed_manifest.write_text(json.dumps({
                    "synthetic": True,
                    "ids": original_ids,
                    "initial_pilot_release": signed_binding,
                }))
                signed["expected_manifest_sha256"] = sha256_path(signed_manifest)
                signed["files_sha256"] = {
                    str(signed_manifest): sha256_path(signed_manifest)
                }
                manifest["signed_pilot_dataset"] = signed
                manifest["initial_pilot_release"] = release_binding
                manifest["evidence_sha256"] = {
                    **signed["files_sha256"],
                    str(release_path.resolve()): sha256_path(release_path),
                    str(consumption_path.resolve()): sha256_path(consumption_path),
                }
                initial_code = SLURM_DIR.parent / "initial_pilot.py"
                manifest["workflow_sha256"][str(initial_code)] = sha256_path(initial_code)
                self.signed_audits[str(signed_dir)] = copy.deepcopy(signed)
        else:
            selection_source = bundle / "selection-audit.json"
            selection_source.write_text('{"synthetic_audit_source":true}')
            manifest["selection_evidence_sha256"] = {str(selection_source):sha256_path(selection_source)}
            manifest["selection_validation"]["evidence_sha256"] = dict(manifest["selection_evidence_sha256"])
            manifest["selection_validation"].update(selection_receipt_path=str(selection_source),
                selection_receipt_sha256=sha256_path(selection_source))
            dataset = bundle / "phono3py_disp.yaml"
            dataset.write_text("synthetic submission adapter dataset\n")
            manifest["evidence_sha256"] = {str(dataset):sha256_path(dataset)}
            self.selection_audits[str(selection_source)] = copy.deepcopy(manifest["selection_validation"])
        (bundle / "force_manifest.json").write_text(json.dumps(manifest))
        ledger = self.run_dir / ".force_budget"
        ledger.mkdir(exist_ok=True)
        (ledger / "reservation-000000.json").write_text(
            json.dumps(
                {
                    "phase": receipt["phase"],
                    "task_count": count,
                    "reserved_core_hours": receipt["reserved_core_hours"],
                    "receipt_path": str(receipt_path.resolve()),
                    "receipt_sha256": sha256_path(receipt_path),
                }
            )
        )
        return path

    def rewrite_bundle(self, path: Path, *, tasks=None, rows: str | None = None, pilot_spec=None) -> None:
        """Rebind outer hashes so tests exercise inner row/file checks."""
        bundle = path.parent
        manifest = json.loads((bundle / "force_manifest.json").read_text())
        if tasks is not None:
            manifest["tasks"] = tasks
        if pilot_spec is not None:
            manifest["pilot_spec"] = pilot_spec
        if rows is None:
            columns = ("task_id", "displacement_id", "role", "input_path", "input_sha256")
            rows = "\t".join(columns) + "\n" + "".join("\t".join(str(task[key]) for key in columns) + "\n" for task in manifest["tasks"])
        path.write_text(rows)
        manifest.update(task_map_sha256=sha256_path(path), task_count=len(manifest["tasks"]))
        receipt_path = bundle / "budget_receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt.update(
            task_map_sha256=sha256_path(path), task_count=len(manifest["tasks"]),
            reserved_core_hours=len(manifest["tasks"]) * receipt["mpi_ranks"]
            * receipt["walltime_hours"] * (1 + receipt["maximum_technical_retries_per_task"]),
            production_input_hashes=[task["input_sha256"] for task in manifest["tasks"] if task["displacement_id"] != 0] if manifest["mode"] == "production" else [],
        )
        receipt_path.write_text(json.dumps(receipt))
        manifest["budget_receipt_sha256"] = sha256_path(receipt_path)
        (bundle / "force_manifest.json").write_text(json.dumps(manifest))
        (self.run_dir / ".force_budget/reservation-000000.json").write_text(json.dumps({
            "phase": receipt["phase"], "task_count": receipt["task_count"],
            "reserved_core_hours": receipt["reserved_core_hours"],
            "receipt_path": str(receipt_path.resolve()), "receipt_sha256": sha256_path(receipt_path),
        }))

    def test_rehashed_force_manifest_cannot_replace_replayed_selection(self) -> None:
        task_map = self.write_force_bundle()
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["selection_validation"]["analysis_sha256"] = "f" * 64
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "differs from raw-evidence replay"):
            validate_force_bundle(self.context, task_map)
        self.selection_auditor.assert_called_once()

    def test_production_selection_requires_explicit_receipt_identity(self) -> None:
        task_map = self.write_force_bundle()
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["selection_validation"].pop("selection_receipt_path")
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "not explicitly hash-anchored"):
            validate_force_bundle(self.context, task_map)
        self.selection_auditor.assert_not_called()

    def test_force_command_uses_exact_task_map_bounds_and_mandatory_exports(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle(3)
        plan = stage_plan(
            self.context,
            "force",
            attempt_id="force-attempt-1",
            task_map=task_map,
            max_in_flight=2,
        )
        command = sbatch_command(plan)

        self.assertEqual(plan.task_count, 3)
        self.assertEqual(plan.array, "0-2%2")
        self.assertEqual(command[:3], ["sbatch", "--parsable", "--account=def-kleinke_cpu"])
        self.assertEqual(command[3:5], ["--ntasks=32", "--time=01:00:00"])
        self.assertEqual(command[6], "--array=0-2%2")
        self.assertEqual(command[-1], str(SLURM_DIR / "force_array.sbatch"))
        exports = command[5]
        self.assertTrue(exports.startswith("--export=CAMPAIGN_CONFIG="))
        self.assertNotIn("--export=ALL", exports)
        self.assertNotIn("BASH_ENV", exports)
        self.assertIn(f",RUN_DIR={self.run_dir.resolve()}", exports)
        self.assertIn(",ATTEMPT_ID=force-attempt-1", exports)
        self.assertIn(f",P3_SLURM_DIR={SLURM_DIR}", exports)
        self.assertIn(f",TASK_MAP={task_map.resolve()}", exports)
        self.assertIn(",FORCE_MANIFEST=", exports)
        self.assertIn(",FORCE_BUDGET_RECEIPT=", exports)

    def test_preflight_requires_passing_relax_gate(self) -> None:
        with self.assertRaisesRegex(SubmissionError, "tight-relax gate is missing"):
            stage_plan(self.context, "preflight", attempt_id="preflight-1")

        final = self.run_dir / "relax" / "final"
        final.mkdir(parents=True)
        (final / "gate.json").write_text('{"pass": false}\n')
        (final / "unitcell.in").write_text("unit cell\n")
        with self.assertRaisesRegex(SubmissionError, "has not passed"):
            stage_plan(self.context, "preflight", attempt_id="preflight-2")

    def test_imported_run_replays_for_downstream_and_rejects_relax(self) -> None:
        self.pass_relax_gate()
        imported = SubmissionContext(
            config_path=self.context.config_path,
            run_dir=self.context.run_dir,
            config=self.context.config,
            manifest={**self.context.manifest, "accepted_structure_import": {"receipt": "x"}},
            config_sha256=self.context.config_sha256,
        )
        with patch(
            "accepted_structure_import.verify_imported_acceptance",
            return_value={"healthy": True},
        ) as replay:
            stage_plan(imported, "preflight", attempt_id="imported-preflight")
        replay.assert_called_once_with(imported.config_path, imported.run_dir)
        with self.assertRaisesRegex(SubmissionError, "cannot submit a relax stage"):
            stage_plan(imported, "relax", attempt_id="imported-relax")

    def test_import_replay_failure_stops_each_downstream_stage(self) -> None:
        imported = SubmissionContext(
            config_path=self.context.config_path,
            run_dir=self.context.run_dir,
            config=self.context.config,
            manifest={**self.context.manifest, "accepted_structure_import": {"receipt": "x"}},
            config_sha256=self.context.config_sha256,
        )
        for stage in ("preflight", "force", "postprocess"):
            with self.subTest(stage=stage), patch(
                "accepted_structure_import.verify_imported_acceptance",
                side_effect=CampaignError("receipt hash mismatch"),
            ):
                with self.assertRaisesRegex(SubmissionError, "receipt hash mismatch"):
                    stage_plan(imported, stage, attempt_id=f"imported-{stage}")

    def test_force_requires_recorded_production_selection(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle()
        self.config["production"]["selection_required"] = True
        self.config["production"]["selected_supercell"] = None
        self.config["production"]["selected_cutoff"] = None
        with self.assertRaisesRegex(SubmissionError, "selection is still required"):
            stage_plan(
                self.context,
                "force",
                attempt_id="force-attempt-2",
                task_map=task_map,
            )

    def test_pilot_force_uses_receipt_while_production_selection_is_null(self) -> None:
        self.pass_relax_gate()
        self.config["production"].update(
            selection_required=True,
            selected_supercell=None,
            selected_cutoff=None,
            automatic_submission_allowed=False,
        )
        self.config["resource_budget"].update(
            selection_required_before_force_submission=True,
            approved_total_core_hours_per_material=None,
        )
        task_map = self.write_force_bundle(4, mode="pilot")
        plan = stage_plan(
            self.context,
            "force",
            attempt_id="pilot-attempt",
            task_map=task_map,
        )
        self.assertEqual(plan.force_mode, "pilot")
        self.assertEqual(plan.array, "0-3%2")
        self.assertEqual(plan.scheduler_options, ("--ntasks=32", "--time=01:00:00"))

    def test_force_receipt_controls_concurrency_and_detects_tampering(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle(3)
        with self.assertRaisesRegex(SubmissionError, "must equal the immutable"):
            stage_plan(
                self.context,
                "force",
                attempt_id="wrong-concurrency",
                task_map=task_map,
                max_in_flight=1,
            )
        receipt = task_map.parent / "budget_receipt.json"
        value = json.loads(receipt.read_text())
        value["mpi_ranks"] = 16
        receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(SubmissionError, "budget-receipt hash"):
            stage_plan(
                self.context,
                "force",
                attempt_id="tampered-receipt",
                task_map=task_map,
            )

    def test_task_map_rejects_nonsequential_or_out_of_run_rows(self) -> None:
        task_map = self.write_task_map(2)
        task_map.write_text("task_id\tinput\n0\ta\n2\tb\n")
        with self.assertRaisesRegex(SubmissionError, "exactly 0..N-1"):
            validate_task_map(task_map, self.run_dir.resolve(), 8)

        outside = Path(self.temp_dir.name) / "outside.tsv"
        outside.write_text("0\ta\n")
        with self.assertRaisesRegex(SubmissionError, "inside RUN_DIR"):
            validate_task_map(outside, self.run_dir.resolve(), 8)

    def test_force_bundle_replays_synchronously_rehashed_ledger_semantics(self) -> None:
        task_map = self.write_force_bundle(3)
        bundle = task_map.parent
        receipt_path = bundle / "budget_receipt.json"
        ledger_path = self.run_dir / ".force_budget" / "reservation-000000.json"
        manifest_path = bundle / "force_manifest.json"
        original_receipt = receipt_path.read_text()
        original_ledger = ledger_path.read_text()
        original_manifest = manifest_path.read_text()
        cases = (
            ("phase", "not-a-phase", "budget receipt phase is invalid"),
            ("task_count", -1, "budget receipt does not bind"),
            ("reserved_core_hours", -1, "budget ledger replay failed.*reserved_core_hours"),
            ("reserved_core_hours", 1, "budget ledger replay failed.*inconsistent"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                receipt = json.loads(original_receipt)
                ledger = json.loads(original_ledger)
                receipt[field] = value
                ledger[field] = value
                receipt_path.write_text(json.dumps(receipt))
                ledger["receipt_sha256"] = sha256_path(receipt_path)
                ledger_path.write_text(json.dumps(ledger))
                manifest = json.loads(original_manifest)
                manifest["budget_receipt_sha256"] = sha256_path(receipt_path)
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(SubmissionError, expected):
                    validate_force_bundle(self.context, task_map)
                receipt_path.write_text(original_receipt)
                ledger_path.write_text(original_ledger)
                manifest_path.write_text(original_manifest)

    def test_force_map_requires_exact_explicit_header(self) -> None:
        task_map = self.write_force_bundle()
        rows = task_map.read_text().replace("task_id\tdisplacement_id", "task\tdisplacement_id", 1)
        self.rewrite_bundle(task_map, rows=rows)
        with self.assertRaisesRegex(SubmissionError, "header must be"):
            validate_force_bundle(self.context, task_map)

    def test_force_map_rejects_extra_or_missing_fields(self) -> None:
        task_map = self.write_force_bundle()
        rows = task_map.read_text().splitlines()
        rows[1] += "\textra"
        self.rewrite_bundle(task_map, rows="\n".join(rows)+"\n")
        with self.assertRaisesRegex(SubmissionError, "exactly five fields"):
            validate_force_bundle(self.context, task_map)

    def test_force_map_rows_must_match_manifest_fields(self) -> None:
        task_map = self.write_force_bundle()
        rows = task_map.read_text().splitlines()
        row = rows[2].split("\t")
        row[1] = "99"
        rows[2] = "\t".join(row)
        self.rewrite_bundle(task_map, rows="\n".join(rows)+"\n")
        with self.assertRaisesRegex(SubmissionError, "differs from manifest.tasks"):
            validate_force_bundle(self.context, task_map)

    def test_force_manifest_task_ids_cannot_be_reordered(self) -> None:
        task_map = self.write_force_bundle()
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["tasks"][1]["task_id"] = 2
        manifest["tasks"][2]["task_id"] = 1
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "exactly 0..N-1"):
            validate_force_bundle(self.context, task_map)

    def test_force_input_bytes_must_match_actual_sha256(self) -> None:
        task_map = self.write_force_bundle()
        manifest = json.loads((task_map.parent / "force_manifest.json").read_text())
        Path(manifest["tasks"][1]["input_path"]).write_text("altered input")
        with self.assertRaisesRegex(SubmissionError, "SHA-256 mismatch"):
            validate_force_bundle(self.context, task_map)

    def test_missing_force_input_rejected(self) -> None:
        task_map = self.write_force_bundle()
        manifest = json.loads((task_map.parent / "force_manifest.json").read_text())
        Path(manifest["tasks"][1]["input_path"]).unlink()
        with self.assertRaisesRegex(SubmissionError, "file missing"):
            validate_force_bundle(self.context, task_map)

    def test_force_input_must_stay_inside_its_bundle_not_just_run(self) -> None:
        task_map = self.write_force_bundle()
        tasks = json.loads((task_map.parent / "force_manifest.json").read_text())["tasks"]
        outside = self.run_dir / "outside-input.in"
        outside.write_text("separate bundle input")
        tasks[1].update(input_path=str(outside.resolve()), input_sha256=sha256_path(outside))
        self.rewrite_bundle(task_map, tasks=tasks)
        with self.assertRaisesRegex(SubmissionError, "strict descendant"):
            validate_force_bundle(self.context, task_map)

    def test_force_input_symlink_cannot_escape_bundle(self) -> None:
        task_map = self.write_force_bundle()
        tasks = json.loads((task_map.parent / "force_manifest.json").read_text())["tasks"]
        input_path = Path(tasks[1]["input_path"])
        outside = self.run_dir / "outside-target.in"
        outside.write_text(input_path.read_text())
        input_path.unlink()
        input_path.symlink_to(outside.resolve())
        with self.assertRaisesRegex(SubmissionError, "strict descendant"):
            validate_force_bundle(self.context, task_map)

    def test_production_requires_one_pristine_and_unique_positive_displacements(self) -> None:
        task_map = self.write_force_bundle(4, pristine_count=2)
        with self.assertRaisesRegex(SubmissionError, "exactly one pristine"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle(4, duplicate_ids=[1])
        with self.assertRaisesRegex(SubmissionError, "unique positive"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle(3)
        tasks = json.loads((task_map.parent / "force_manifest.json").read_text())["tasks"]
        tasks[1]["displacement_id"] = -1
        self.rewrite_bundle(task_map, tasks=tasks)
        with self.assertRaisesRegex(SubmissionError, "unique positive"):
            validate_force_bundle(self.context, task_map)

    def test_pilot_accepts_two_pristine_and_declared_identical_duplicate(self) -> None:
        task_map = self.write_force_bundle(5, mode="pilot", pristine_count=2, duplicate_ids=[1])
        validated = validate_force_bundle(self.context, task_map)
        self.assertEqual(validated[1], 5)
        self.assertEqual([x["displacement_id"] for x in validated[4]["tasks"]], [0,0,1,2,1])

    def test_initial_pilot_reaudits_bound_sha_and_accepts_only_six(self) -> None:
        task_map = self.write_force_bundle(6, mode="pilot", pristine_count=2, duplicate_ids=[1,3])
        validated = validate_force_bundle(self.context, task_map)
        self.assertEqual(validated[1], 6)
        signed = validated[4]["signed_pilot_dataset"]
        self.assertEqual(self.signed_auditor.call_args.kwargs["expected_manifest_sha256"], signed["expected_manifest_sha256"])
        self.assertEqual(validated[6]["phase"], "initial")
        Path(signed["dataset_dir"], "pilot_dataset_manifest.json").write_text("altered signed plan")
        with self.assertRaisesRegex(SubmissionError, "signed pilot dataset gate"):
            validate_force_bundle(self.context, task_map)

    def test_initial_pilot_rejects_changed_release_and_escaped_release(self) -> None:
        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        release_path = Path(manifest["initial_pilot_release"]["path"])
        release_path.write_text('{"changed":true}\n')
        with self.assertRaisesRegex(SubmissionError, "release replay.*hash mismatch"):
            validate_force_bundle(self.context, task_map)

        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        manifest = json.loads(manifest_path.read_text())
        escaped = Path(self.temp_dir.name) / "escaped-release.json"
        escaped.write_text('{"synthetic_release":true}\n')
        old_path = manifest["initial_pilot_release"]["path"]
        manifest["initial_pilot_release"].update(
            path=str(escaped.resolve()), sha256=sha256_path(escaped)
        )
        manifest["evidence_sha256"].pop(old_path)
        manifest["evidence_sha256"][str(escaped.resolve())] = sha256_path(escaped)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "strict descendant"):
            validate_force_bundle(self.context, task_map)

    def test_initial_release_is_rejected_for_validation_and_production(self) -> None:
        validation = self.write_force_bundle(4, mode="pilot")
        manifest_path = validation.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["initial_pilot_release"] = {
            "path": str((self.run_dir / "bogus-release.json").resolve()),
            "sha256": "a" * 64,
            "consumption_identity": "b" * 64,
        }
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "validation pilot may not"):
            validate_force_bundle(self.context, validation)

        production = self.write_force_bundle(3, mode="production")
        manifest_path = production.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["initial_pilot_release"] = {
            "path": str((self.run_dir / "bogus-release.json").resolve()),
            "sha256": "a" * 64,
            "consumption_identity": "b" * 64,
        }
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "production force manifest may not"):
            validate_force_bundle(self.context, production)

    def test_initial_pilot_rejects_resource_or_consumption_claim_drift(self) -> None:
        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        receipt_path = task_map.parent / "budget_receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["maximum_concurrency"] = 3
        receipt_path.write_text(json.dumps(receipt))
        self.rewrite_bundle(task_map)
        with self.assertRaisesRegex(SubmissionError, "release replay failed"):
            validate_force_bundle(self.context, task_map)

        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        manifest = json.loads((task_map.parent / "force_manifest.json").read_text())
        signed_manifest_path = Path(
            manifest["signed_pilot_dataset"]["dataset_dir"]
        ) / "pilot_dataset_manifest.json"
        signed_manifest = json.loads(signed_manifest_path.read_text())
        consumption_path = Path(
            signed_manifest["initial_pilot_release"]["consumption_path"]
        )
        claim = json.loads(consumption_path.read_text())
        claim["dataset_dir"] = str(self.run_dir / "copied-dataset")
        consumption_path.write_text(json.dumps(claim))
        signed_manifest["initial_pilot_release"]["consumption_sha256"] = sha256_path(
            consumption_path
        )
        signed_manifest_path.write_text(json.dumps(signed_manifest))
        signed = manifest["signed_pilot_dataset"]
        signed["expected_manifest_sha256"] = sha256_path(signed_manifest_path)
        signed["files_sha256"] = {
            str(signed_manifest_path): sha256_path(signed_manifest_path)
        }
        manifest["evidence_sha256"].update(signed["files_sha256"])
        manifest["evidence_sha256"][str(consumption_path)] = sha256_path(
            consumption_path
        )
        (task_map.parent / "force_manifest.json").write_text(json.dumps(manifest))
        self.signed_audits[str(Path(signed["dataset_dir"]).resolve())] = copy.deepcopy(
            signed
        )
        with self.assertRaisesRegex(SubmissionError, "consumption claim is invalid"):
            validate_force_bundle(self.context, task_map)

    def test_retry_plan_submits_only_proven_technical_failure_subset(self) -> None:
        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        manifest_path = task_map.parent / "force_manifest.json"
        records = {}
        for name in ("primary_request", "primary_result", "collector_request",
                     "collector_result"):
            path = self.run_dir / f"retry-{name}.json"
            path.write_text(json.dumps({"stage_script_sha256": "f" * 64}))
            records[name] = {"path": str(path.resolve()), "sha256": sha256_path(path)}
        entries = [
            {"task_id": task_id,
             "outcome": "upstream_failed" if task_id in (1, 4) else "accepted_success",
             "errors": [],
             "resource_usage": {"elapsed_seconds": 60, "allocated_cpus": 32,
                                "timelimit_minutes": 120, "core_hours": 32 / 60},
             "scheduler_records": ([{"State": "NODE_FAIL", "JobIDRaw": str(9000 + task_id)}]
                                   if task_id in (1, 4) else [{"State": "COMPLETED"}])}
            for task_id in range(6)
        ]
        collector_attempt = self.run_dir / "slurm_attempts/collect/primary-collector"
        collector_attempt.mkdir(parents=True)
        collection = {
            "schema_version": 1, "stage": "collect",
            "collection_kind": "force_array_batch", "material": "Example",
            "force_mode": "pilot", "expected_task_count": 6,
            "submitted_task_ids": list(range(6)),
            "submitted_task_count": 6,
            "collector_attempt": str(collector_attempt),
            "accepted_success_count": 4, "upstream_failure_count": 2,
            "unfinished_or_invalid_count": 0,
            "collection_integrity_complete": True, "global_errors": [],
            "primary": {"attempt_id": "primary-1", "job_id": "99",
                        "force_manifest_sha256": sha256_path(manifest_path),
                        "task_map_sha256": sha256_path(task_map),
                        "submission_records": records},
            "entries": entries,
        }
        collection_path = self.run_dir / "primary-collection.json"
        collection_path.write_text(json.dumps(collection))
        self.pass_relax_gate()
        with patch("campaign._force_submission_binding", return_value=records):
            plan = stage_plan(
                self.context, "force", attempt_id="retry-1", task_map=task_map,
                max_in_flight=2, retry_collection=collection_path,
                expected_retry_collection_sha256=sha256_path(collection_path),
            )
        self.assertEqual(plan.submitted_task_ids, (1, 4))
        self.assertEqual(plan.array, "1,4%2")
        self.assertEqual(plan.retry_collection, collection_path.resolve())

        for field, value in (
            ("allocated_cpus", 31),
            ("timelimit_minutes", 121),
            ("elapsed_seconds", 7201),
            ("core_hours", 65),
        ):
            with self.subTest(invalid_retry_resource=field):
                invalid_entries = copy.deepcopy(entries)
                invalid_entries[1]["resource_usage"][field] = value
                collection["entries"] = invalid_entries
                collection_path.write_text(json.dumps(collection))
                with patch("campaign._force_submission_binding", return_value=records), \
                     self.assertRaisesRegex(SubmissionError, "resource evidence"):
                    stage_plan(
                        self.context, "force", attempt_id=f"retry-bad-{field}",
                        task_map=task_map, retry_collection=collection_path,
                        expected_retry_collection_sha256=sha256_path(collection_path),
                    )
        collection["entries"] = entries

        successful_entry_mutations = (
            ("errors", ["forged successful-entry error"]),
            ("allocated_cpus", 31),
            ("timelimit_minutes", 121),
            ("elapsed_seconds", 7201),
            ("core_hours", 65),
            ("malformed_usage", "not-an-object"),
        )
        for field, value in successful_entry_mutations:
            with self.subTest(invalid_success_resource=field):
                invalid_entries = copy.deepcopy(entries)
                if field == "errors":
                    invalid_entries[0]["errors"] = value
                elif field == "malformed_usage":
                    invalid_entries[0]["resource_usage"] = value
                else:
                    invalid_entries[0]["resource_usage"][field] = value
                collection["entries"] = invalid_entries
                collection_path.write_text(json.dumps(collection))
                with patch("campaign._force_submission_binding", return_value=records), \
                     self.assertRaisesRegex(SubmissionError, "resource evidence"):
                    stage_plan(
                        self.context, "force", attempt_id=f"bad-success-{field}",
                        task_map=task_map, retry_collection=collection_path,
                        expected_retry_collection_sha256=sha256_path(collection_path),
                    )
        collection["entries"] = entries

        outside_collector = Path(self.temp_dir.name).resolve() / "outside-collector"
        outside_collector.mkdir()
        collection["collector_attempt"] = str(outside_collector)
        collection_path.write_text(json.dumps(collection))
        with self.assertRaisesRegex(SubmissionError, "strict descendant"):
            stage_plan(
                self.context, "force", attempt_id="retry-external-collector",
                task_map=task_map, retry_collection=collection_path,
                expected_retry_collection_sha256=sha256_path(collection_path),
            )
        alias = collector_attempt.parent / "symlinked-collector"
        alias.symlink_to(outside_collector, target_is_directory=True)
        collection["collector_attempt"] = str(alias)
        collection_path.write_text(json.dumps(collection))
        with self.assertRaisesRegex(SubmissionError, "symlink"):
            stage_plan(
                self.context, "force", attempt_id="retry-symlinked-collector",
                task_map=task_map, retry_collection=collection_path,
                expected_retry_collection_sha256=sha256_path(collection_path),
            )
        collection["collector_attempt"] = str(collector_attempt)

        collection["submitted_task_ids"] = [1, 4]
        collection["submitted_task_count"] = 2
        collection["entries"] = [entries[1], entries[4]]
        collection_path.write_text(json.dumps(collection))
        with self.assertRaisesRegex(SubmissionError, "original full primary"):
            stage_plan(
                self.context, "force", attempt_id="retry-of-retry",
                task_map=task_map, retry_collection=collection_path,
                expected_retry_collection_sha256=sha256_path(collection_path),
            )

        collection["submitted_task_ids"] = list(range(6))
        collection["submitted_task_count"] = 6
        collection["entries"] = entries
        source_request = Path(records["primary_request"]["path"])
        source_request.write_text(json.dumps({
            "stage_script_sha256": "f" * 64,
            "retry_collection": str(collection_path),
            "retry_collection_sha256": "a" * 64,
        }))
        records["primary_request"]["sha256"] = sha256_path(source_request)
        collection["primary"]["submission_records"] = records
        collection_path.write_text(json.dumps(collection))
        with self.assertRaisesRegex(SubmissionError, "cannot authorize another retry"):
            stage_plan(
                self.context, "force", attempt_id="retry-recursive",
                task_map=task_map, retry_collection=collection_path,
                expected_retry_collection_sha256=sha256_path(collection_path),
            )
        source_request.write_text(json.dumps({"stage_script_sha256": "f" * 64}))
        records["primary_request"]["sha256"] = sha256_path(source_request)
        collection["primary"]["submission_records"] = records
        collection["entries"][1]["scheduler_records"] = [{"State": "FAILED"}]
        collection_path.write_text(json.dumps(collection))
        with patch("campaign._force_submission_binding", return_value=records), \
             self.assertRaisesRegex(SubmissionError, "nontechnical or unresolved"):
            stage_plan(
                self.context, "force", attempt_id="retry-bad", task_map=task_map,
                retry_collection=collection_path,
                expected_retry_collection_sha256=sha256_path(collection_path),
            )

    def test_initial_cannot_be_declared_for_incomplete_validation_composition(self) -> None:
        task_map = self.write_force_bundle(4, mode="pilot")
        receipt_path = task_map.parent / "budget_receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["phase"] = "initial"
        receipt_path.write_text(json.dumps(receipt))
        self.rewrite_bundle(task_map)
        with self.assertRaisesRegex(SubmissionError, "initial pilot requires exactly"):
            validate_force_bundle(self.context, task_map)

    def test_submit_rejects_missing_signed_provenance_or_changed_audit(self) -> None:
        task_map = self.write_force_bundle(6, mode="pilot", pristine_count=2, duplicate_ids=[1,3])
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["evidence_sha256"] = {}
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "bind every signed"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle(6, mode="pilot", pristine_count=2, duplicate_ids=[1,3])
        manifest = json.loads(manifest_path.read_text())
        signed = manifest["signed_pilot_dataset"]
        self.signed_audits[signed["dataset_dir"]]["task_kinds"]["2"] = "single"
        with self.assertRaisesRegex(SubmissionError, "re-audit differs"):
            validate_force_bundle(self.context, task_map)

    def test_pilot_rejects_undeclared_duplicate_and_mismatched_duplicate_input(self) -> None:
        task_map = self.write_force_bundle(4, mode="pilot", duplicate_ids=[1])
        self.rewrite_bundle(task_map, pilot_spec={"displacement_ids":[1,2,3], "duplicate_displacement_ids":[]})
        with self.assertRaisesRegex(SubmissionError, "declared pristine/original/duplicate"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle(4, mode="pilot", duplicate_ids=[1])
        tasks = json.loads((task_map.parent / "force_manifest.json").read_text())["tasks"]
        duplicate = Path(tasks[-1]["input_path"])
        duplicate.write_text("different force settings")
        tasks[-1]["input_sha256"] = sha256_path(duplicate)
        self.rewrite_bundle(task_map, tasks=tasks)
        with self.assertRaisesRegex(SubmissionError, "duplicate input SHA-256 differs"):
            validate_force_bundle(self.context, task_map)

    def test_pilot_rejects_three_pristine_or_missing_semantics(self) -> None:
        task_map = self.write_force_bundle(5, mode="pilot", pristine_count=3)
        with self.assertRaisesRegex(SubmissionError, "one or two pristine"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle(3, mode="pilot")
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.pop("pilot_spec")
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "explicit pilot_spec"):
            validate_force_bundle(self.context, task_map)

    def test_boolean_ids_and_invalid_roles_rejected(self) -> None:
        task_map = self.write_force_bundle()
        tasks = json.loads((task_map.parent / "force_manifest.json").read_text())["tasks"]
        tasks[1]["displacement_id"] = True
        self.rewrite_bundle(task_map, tasks=tasks)
        with self.assertRaisesRegex(SubmissionError, "must be an integer"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle()
        tasks = json.loads((task_map.parent / "force_manifest.json").read_text())["tasks"]
        tasks[1]["role"] = "unknown"
        self.rewrite_bundle(task_map, tasks=tasks)
        with self.assertRaisesRegex(SubmissionError, "role must be"):
            validate_force_bundle(self.context, task_map)

    def test_sha_mismatch_stops_before_sbatch(self) -> None:
        with patch("submit.require_nibi_login"), patch("submit.subprocess.run") as run:
            with self.assertRaisesRegex(SubmissionError, "SHA-256 changed"):
                execute_submission(
                    self.context,
                    "relax",
                    expected_config_sha="b" * 64,
                    task_map=None,
                    max_in_flight=32,
                )
        run.assert_not_called()

    def test_diagnostic_plan_and_execute_include_afterany_collector(self) -> None:
        (self.run_dir / "run_manifest.json").unlink()
        ready = {
            "material": "Example",
            "config_sha256": CONFIG_SHA,
            "lineage_sha256": "d" * 64,
            "structure_accepted": False,
            "preflight_unlocked": False,
        }
        self.context.manifest.clear()
        self.context.manifest.update(ready)
        with patch(
            "polish_recovery.verify_diagnostic_submission_ready",
            return_value=ready,
        ):
            report = plan_report(
                self.context,
                "diagnostic",
                task_map=None,
                max_in_flight=None,
            )
        self.assertTrue(report["collector"])
        self.assertEqual(
            report["scheduler_options"],
            [
                "--partition=cpubase_bycore_b2",
                "--nodes=1",
                "--ntasks=32",
                "--cpus-per-task=1",
                "--mem-per-cpu=2000M",
                "--time=02:00:00",
            ],
        )

        primary_completed = subprocess.CompletedProcess(
            [], 0, stdout="32345;nibi\n", stderr=""
        )
        collector_completed = subprocess.CompletedProcess(
            [], 0, stdout="32346;nibi\n", stderr=""
        )
        with patch.dict(os.environ, {"SLURM_EXPORT_ENV": "ALL"}), patch(
            "submit.require_nibi_login"
        ), patch(
            "submit.new_attempt_id",
            side_effect=("diagnostic-attempt", "diagnostic-collector"),
        ), patch(
            "polish_recovery.verify_diagnostic_submission_ready",
            return_value=ready,
        ), patch(
            "submit.subprocess.run",
            side_effect=(primary_completed, collector_completed),
        ) as run:
            result = execute_submission(
                self.context,
                "diagnostic",
                expected_config_sha=CONFIG_SHA,
                task_map=None,
                max_in_flight=None,
            )
        self.assertEqual(run.call_count, 2)
        command = run.call_args_list[0].args[0]
        self.assertIn("--partition=cpubase_bycore_b2", command)
        self.assertIn("--ntasks=32", command)
        export = next(item for item in command if item.startswith("--export="))
        self.assertFalse(export.startswith("--export=ALL"))
        self.assertNotIn("SLURM_EXPORT_ENV", export)
        self.assertIn(",P3_DIAGNOSTIC_RESOURCE_SHA256=", export)
        self.assertIn(",P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES=120", export)
        self.assertEqual(command[-1], str(SLURM_DIR / "diagnostic.sbatch"))
        self.assertEqual(result["collector"]["job_id"], "32346")
        self.assertEqual(result["collector"]["dependency"], "afterany:32345")
        collector_command = run.call_args_list[1].args[0]
        self.assertIn("--dependency=afterany:32345", collector_command)
        self.assertEqual(collector_command[-1], str(SLURM_DIR / "collect.sbatch"))
        record = Path(result["record_dir"])
        request = json.loads((record / "request.json").read_text())
        response = json.loads((record / "primary_result.json").read_text())
        self.assertEqual(request["config_sha256"], CONFIG_SHA)
        self.assertEqual(request["polish_lineage_sha256"], "d" * 64)
        self.assertIsNone(request["run_manifest_sha256"])
        self.assertEqual(response["job_id"], "32345")
        self.assertEqual(response["stdout"], "32345;nibi\n")
        self.assertEqual(response["config_sha256"], CONFIG_SHA)
        self.assertTrue((record / "submission.json").is_file())
        self.assertTrue((record / "collector_request.json").is_file())
        self.assertTrue((record / "collector_result.json").is_file())

    def test_preflight_plan_exports_only_the_signed_reviewed_subset(self) -> None:
        config_path = Path(__file__).resolve().parents[4] / (
            "thermo_candidates/SrZrS3/phono3py/campaign.json"
        )
        config = json.loads(config_path.read_text())
        context = SubmissionContext(
            config_path=config_path.resolve(),
            run_dir=self.run_dir.resolve(),
            config=config,
            manifest={"material": "SrZrS3"},
            config_sha256=sha256_path(config_path),
        )
        self.pass_relax_gate()
        requested = [
            "sr_fc3_3x1x1__sr_cutoff_3p70A",
            "sr_fc3_2x1x1__sr_cutoff_3p70A",
        ]
        plan = stage_plan(
            context,
            "preflight",
            attempt_id="subset-preflight",
            candidate_ids=requested,
        )
        self.assertEqual(
            plan.candidate_ids,
            (
                "sr_fc3_2x1x1__sr_cutoff_3p70A",
                "sr_fc3_3x1x1__sr_cutoff_3p70A",
            ),
        )
        self.assertRegex(plan.candidate_subset_sha256 or "", r"^[0-9a-f]{64}$")
        command = sbatch_command(plan)
        exports = next(item for item in command if item.startswith("--export="))
        self.assertIn(
            ",P3_PREFLIGHT_CANDIDATE_IDS="
            "sr_fc3_2x1x1__sr_cutoff_3p70A:"
            "sr_fc3_3x1x1__sr_cutoff_3p70A",
            exports,
        )
        self.assertIn(",P3_PREFLIGHT_CANDIDATE_SHA256=", exports)
        self.assertNotIn("sr_fc3_3x2x1__sr_cutoff_4A", exports)
        with patch("submit.require_nibi_login"), patch("submit.subprocess.run") as run:
            with self.assertRaisesRegex(
                SubmissionError, "requires the exact 64-character"
            ):
                execute_submission(
                    context,
                    "preflight",
                    expected_config_sha=context.config_sha256,
                    task_map=None,
                    max_in_flight=None,
                    candidate_ids=requested,
                )
            with self.assertRaisesRegex(SubmissionError, "changed or was not copied"):
                execute_submission(
                    context,
                    "preflight",
                    expected_config_sha=context.config_sha256,
                    task_map=None,
                    max_in_flight=None,
                    candidate_ids=requested,
                    expected_candidate_subset_sha="0" * 64,
                )
        run.assert_not_called()

        completed = subprocess.CompletedProcess(
            [], 0, stdout="42345\n", stderr=""
        )
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", return_value="signed-subset"
        ), patch("submit.subprocess.run", return_value=completed) as run:
            submitted = execute_submission(
                context,
                "preflight",
                expected_config_sha=context.config_sha256,
                task_map=None,
                max_in_flight=None,
                candidate_ids=requested,
                expected_candidate_subset_sha=plan.candidate_subset_sha256,
            )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(
            submitted["candidate_subset_sha256"], plan.candidate_subset_sha256
        )
        request = json.loads(
            (Path(submitted["record_dir"]) / "request.json").read_text()
        )
        self.assertEqual(
            request["candidate_subset_sha256"], plan.candidate_subset_sha256
        )
        for bad, message in (
            ([requested[0], requested[0]], "duplicates"),
            (["missing"], "not uniquely present"),
            ([], "nonempty"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                SubmissionError, message
            ):
                stage_plan(
                    context,
                    "preflight",
                    attempt_id="bad-subset",
                    candidate_ids=bad,
                )

    def test_candidate_subset_is_rejected_for_non_preflight_stage(self) -> None:
        with self.assertRaisesRegex(SubmissionError, "only for the preflight"):
            stage_plan(
                self.context,
                "relax",
                attempt_id="wrong-stage",
                candidate_ids=["candidate"],
            )

    def test_subset_expectation_is_forbidden_for_full_preflight(self) -> None:
        with patch("submit.require_nibi_login"), patch("submit.subprocess.run") as run:
            with self.assertRaisesRegex(SubmissionError, "forbidden without"):
                execute_submission(
                    self.context,
                    "preflight",
                    expected_config_sha=CONFIG_SHA,
                    task_map=None,
                    max_in_flight=None,
                    expected_candidate_subset_sha="0" * 64,
                )
        run.assert_not_called()

    def test_execute_cli_has_independent_subset_expectation_argument(self) -> None:
        parsed = build_parser().parse_args(
            [
                "execute",
                "--stage",
                "preflight",
                "--config",
                str(self.config_path),
                "--run-dir",
                str(self.run_dir),
                "--expect-config-sha",
                CONFIG_SHA,
                "--candidate-id",
                "candidate-a__cutoff-a",
                "--expect-candidate-subset-sha",
                "a" * 64,
            ]
        )
        self.assertEqual(parsed.expect_candidate_subset_sha, "a" * 64)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "plan",
                    "--stage",
                    "preflight",
                    "--config",
                    str(self.config_path),
                    "--run-dir",
                    str(self.run_dir),
                    "--expect-candidate-subset-sha",
                    "a" * 64,
                ]
            )

    def test_relax_execute_submits_distinct_afterany_collector(self) -> None:
        completed = [
            subprocess.CompletedProcess([], 0, stdout="12345\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="12346;nibi\n", stderr=""),
        ]
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", side_effect=["relax-attempt", "collector-attempt"]
        ), patch("submit.subprocess.run", side_effect=completed) as run:
            result = execute_submission(
                self.context,
                "relax",
                expected_config_sha=CONFIG_SHA,
                task_map=None,
                max_in_flight=32,
            )

        self.assertEqual(run.call_count, 2)
        primary = run.call_args_list[0].args[0]
        collector = run.call_args_list[1].args[0]
        self.assertEqual(primary[:2], ["sbatch", "--parsable"])
        self.assertEqual(primary[2], "--account=def-kleinke_cpu")
        self.assertIn(",ATTEMPT_ID=relax-attempt", primary[3])
        self.assertIn(f",P3_SLURM_DIR={SLURM_DIR}", primary[3])
        self.assertEqual(primary[-1], str(SLURM_DIR / "relax.sbatch"))
        self.assertIn(",ATTEMPT_ID=collector-attempt", collector[3])
        self.assertNotIn(",ATTEMPT_ID=relax-attempt,", collector[3])
        self.assertIn(",PRIMARY_STAGE=relax", collector[3])
        self.assertIn(",PRIMARY_ATTEMPT_ID=relax-attempt", collector[3])
        self.assertIn(",PRIMARY_JOB_ID=12345", collector[3])
        self.assertIn("--dependency=afterany:12345", collector)
        self.assertEqual(collector[-1], str(SLURM_DIR / "collect.sbatch"))
        self.assertEqual(result["primary_job_id"], "12345")
        self.assertEqual(result["collector"]["job_id"], "12346")
        record = Path(result["record_dir"])
        self.assertTrue((record / "request.json").is_file())
        self.assertTrue((record / "primary_result.json").is_file())
        self.assertTrue((record / "collector_result.json").is_file())
        self.assertTrue((record / "submission.json").is_file())

    def test_force_collector_receives_exact_primary_and_bundle_identity(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle(3)
        completed = [
            subprocess.CompletedProcess([], 0, stdout="22345\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="22346\n", stderr=""),
        ]
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", side_effect=["force-primary", "force-collector"]
        ), patch("submit.subprocess.run", side_effect=completed) as run:
            result = execute_submission(
                self.context,
                "force",
                expected_config_sha=CONFIG_SHA,
                task_map=task_map,
                max_in_flight=2,
            )

        collector = run.call_args_list[1].args[0]
        self.assertNotIn("--hold", run.call_args_list[0].args[0])
        exports = next(item for item in collector if item.startswith("--export="))
        self.assertIn(",ATTEMPT_ID=force-collector", exports)
        self.assertIn(",PRIMARY_STAGE=force", exports)
        self.assertIn(",PRIMARY_ATTEMPT_ID=force-primary", exports)
        self.assertIn(",PRIMARY_JOB_ID=22345", exports)
        self.assertIn(",PRIMARY_TASK_MAP_SHA256=", exports)
        self.assertIn(",PRIMARY_FORCE_MANIFEST_SHA256=", exports)
        self.assertIn(f",TASK_MAP={task_map.resolve()}", exports)
        self.assertIn(",FORCE_MANIFEST=", exports)
        self.assertIn(",FORCE_BUDGET_RECEIPT=", exports)
        self.assertNotIn("--array=", " ".join(collector))
        self.assertIn("--dependency=afterany:22345", collector)
        self.assertEqual(result["collector"]["primary_attempt_id"], "force-primary")
        self.assertEqual(result["collector"]["primary_job_id"], "22345")

    def test_initial_force_is_held_until_collector_is_immutably_attached(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        plan = stage_plan(
            self.context, "force", attempt_id="initial-plan", task_map=task_map,
            max_in_flight=2,
        )
        self.assertTrue(plan.hold_primary)
        self.assertIn("--hold", sbatch_command(plan))

        completed = [
            subprocess.CompletedProcess([], 0, stdout="32345\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="32346\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", side_effect=["initial-primary", "initial-collector"]
        ), patch("submit.subprocess.run", side_effect=completed) as run:
            result = execute_submission(
                self.context,
                "force",
                expected_config_sha=CONFIG_SHA,
                task_map=task_map,
                max_in_flight=2,
            )

        self.assertEqual(run.call_count, 3)
        self.assertIn("--hold", run.call_args_list[0].args[0])
        self.assertIn("--dependency=afterany:32345", run.call_args_list[1].args[0])
        self.assertEqual(run.call_args_list[2].args[0], ["scontrol", "release", "32345"])
        record = Path(result["record_dir"])
        request = json.loads((record / "request.json").read_text())
        attachment = json.loads((record / "collector_attachment.json").read_text())
        release = json.loads((record / "primary_release.json").read_text())
        self.assertTrue(request["hold_primary"])
        self.assertEqual(
            attachment["kind"], "initial_pilot_afterany_collector_attachment"
        )
        self.assertEqual(
            release["collector_attachment_sha256"],
            sha256_path(record / "collector_attachment.json"),
        )
        self.assertEqual(
            result["collector"]["primary_release_sha256"],
            sha256_path(record / "primary_release.json"),
        )
        collector_attempt = self.run_dir / "slurm_attempts/collect/initial-collector"
        collector_attempt.mkdir(parents=True)
        (collector_attempt / "context.tsv").write_text(
            "attempt_id\tinitial-collector\nslurm_job_id\t32346\n"
        )
        records = _force_submission_binding(
            config_path=self.config_path.resolve(), run_dir=self.run_dir.resolve(),
            collector_attempt=collector_attempt,
            primary_attempt_id="initial-primary", primary_job_id="32345",
            force_manifest_sha256=plan.force_manifest_sha256,
            task_map_sha256=plan.task_map_sha256,
            submitted_task_ids=list(range(6)),
            expected_primary_request_sha256=sha256_path(record / "request.json"),
            expected_primary_result_sha256=sha256_path(record / "primary_result.json"),
            expected_primary_stage_script_sha256=request["stage_script_sha256"],
            require_held_primary=True,
        )
        self.assertEqual(
            set(records),
            {"primary_request", "primary_result", "collector_request",
             "collector_result", "collector_attachment", "primary_release"},
        )

        original_release = (record / "primary_release.json").read_text()
        bad_release = json.loads(original_release)
        bad_release["returncode"] = 1
        (record / "primary_release.json").write_text(json.dumps(bad_release))
        with self.assertRaisesRegex(CampaignError, "release evidence mismatch"):
            _force_submission_binding(
                config_path=self.config_path.resolve(), run_dir=self.run_dir.resolve(),
                collector_attempt=collector_attempt,
                primary_attempt_id="initial-primary", primary_job_id="32345",
                force_manifest_sha256=plan.force_manifest_sha256,
                task_map_sha256=plan.task_map_sha256,
                submitted_task_ids=list(range(6)),
                expected_primary_request_sha256=sha256_path(record / "request.json"),
                expected_primary_result_sha256=sha256_path(record / "primary_result.json"),
                expected_primary_stage_script_sha256=request["stage_script_sha256"],
                require_held_primary=True,
            )
        (record / "primary_release.json").write_text(original_release)
        request["hold_primary"] = False
        (record / "request.json").write_text(json.dumps(request))
        with self.assertRaisesRegex(CampaignError, "was not held"):
            _force_submission_binding(
                config_path=self.config_path.resolve(), run_dir=self.run_dir.resolve(),
                collector_attempt=collector_attempt,
                primary_attempt_id="initial-primary", primary_job_id="32345",
                force_manifest_sha256=plan.force_manifest_sha256,
                task_map_sha256=plan.task_map_sha256,
                submitted_task_ids=list(range(6)),
                expected_primary_request_sha256=sha256_path(record / "request.json"),
                expected_primary_result_sha256=sha256_path(record / "primary_result.json"),
                expected_primary_stage_script_sha256=request["stage_script_sha256"],
                require_held_primary=True,
            )

    def test_initial_force_collector_failure_never_releases_held_primary(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        completed = [
            subprocess.CompletedProcess([], 0, stdout="42345\n", stderr=""),
            subprocess.CompletedProcess([], 1, stdout="", stderr="rejected"),
        ]
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", side_effect=["failed-primary", "failed-collector"]
        ), patch("submit.subprocess.run", side_effect=completed) as run, \
             self.assertRaisesRegex(SubmissionError, "afterany collector was not"):
            execute_submission(
                self.context,
                "force",
                expected_config_sha=CONFIG_SHA,
                task_map=task_map,
                max_in_flight=2,
            )
        self.assertEqual(run.call_count, 2)
        self.assertIn("--hold", run.call_args_list[0].args[0])
        record = self.run_dir / "submissions/force/failed-primary"
        self.assertTrue((record / "collector_error.json").is_file())
        self.assertFalse((record / "collector_attachment.json").exists())
        self.assertFalse((record / "primary_release.json").exists())

    def test_initial_force_release_failure_remains_fail_closed(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_force_bundle(
            6, mode="pilot", pristine_count=2, duplicate_ids=[1, 3]
        )
        completed = [
            subprocess.CompletedProcess([], 0, stdout="52345\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="52346\n", stderr=""),
            subprocess.CompletedProcess([], 1, stdout="", stderr="not released"),
        ]
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", side_effect=["held-primary", "held-collector"]
        ), patch("submit.subprocess.run", side_effect=completed) as run, \
             self.assertRaisesRegex(SubmissionError, "remains held"):
            execute_submission(
                self.context,
                "force",
                expected_config_sha=CONFIG_SHA,
                task_map=task_map,
                max_in_flight=2,
            )
        self.assertEqual(run.call_count, 3)
        record = self.run_dir / "submissions/force/held-primary"
        self.assertTrue((record / "collector_attachment.json").is_file())
        self.assertTrue((record / "primary_release_rejected.json").is_file())
        self.assertFalse((record / "primary_release.json").exists())

    def test_active_record_blocks_duplicate_submission(self) -> None:
        record = self.run_dir / "submissions" / "relax" / "old-attempt"
        record.mkdir(parents=True)
        (record / "request.json").write_text("{}\n")
        (record / "submission.json").write_text(
            json.dumps(
                {
                    "primary_job_id": "9001",
                    "collector": {"job_id": "9002"},
                }
            )
            + "\n"
        )
        queued = subprocess.CompletedProcess([], 0, stdout="RUNNING\n", stderr="")
        with patch("submit.subprocess.run", return_value=queued) as run:
            with self.assertRaisesRegex(SubmissionError, "active duplicate relax"):
                ensure_no_active_duplicate(self.run_dir.resolve(), "relax")
        self.assertEqual(run.call_count, 2)
        checked_ids = [call.args[0][3] for call in run.call_args_list]
        self.assertEqual(checked_ids, ["9001", "9002"])

    def test_uncertain_local_record_blocks_without_scheduler_query(self) -> None:
        record = self.run_dir / "submissions" / "preflight" / "interrupted-submit"
        record.mkdir(parents=True)
        (record / "request.json").write_text("{}\n")
        with patch("submit.subprocess.run") as run:
            with self.assertRaisesRegex(SubmissionError, "uncertain prior submission"):
                ensure_no_active_duplicate(self.run_dir.resolve(), "preflight")
        run.assert_not_called()

    def test_success_without_parseable_job_id_is_immutable_and_blocks_retry(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 0, stdout="Submitted batch job UNKNOWN\n", stderr=""
        )
        with patch("submit.require_nibi_login"), patch(
            "submit.new_attempt_id", return_value="uncertain-relax"
        ), patch("submit.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(SubmissionError, "potentially active"):
                execute_submission(
                    self.context,
                    "relax",
                    expected_config_sha=CONFIG_SHA,
                    task_map=None,
                    max_in_flight=32,
                )
        record = self.run_dir / "submissions" / "relax" / "uncertain-relax"
        self.assertTrue((record / "primary_uncertain.json").is_file())
        with patch("submit.subprocess.run") as scheduler_query:
            with self.assertRaisesRegex(SubmissionError, "scheduler reconciliation"):
                ensure_no_active_duplicate(self.run_dir.resolve(), "relax")
        scheduler_query.assert_not_called()

    def test_postprocess_requires_collected_force_gate(self) -> None:
        with self.assertRaisesRegex(SubmissionError, "canonical force/final"):
            stage_plan(self.context, "postprocess", attempt_id="postprocess-1")
        final = self.run_dir / "force" / "final"
        final.mkdir(parents=True)
        (final / "gate.json").write_text('{"pass": true}\n')
        with self.assertRaisesRegex(SubmissionError, "canonical force/final"):
            stage_plan(self.context, "postprocess", attempt_id="postprocess-2")

    def test_require_force_gate_rejects_indexed_budget_ledger_mutation(self) -> None:
        _, ledger = self.write_force_final()
        require_force_gate(self.context)
        ledger.write_text(ledger.read_text() + "mutated\n")
        with self.assertRaisesRegex(SubmissionError, "budget_ledger_reservation hash mismatch"):
            require_force_gate(self.context)

    def test_indexed_file_rejects_symlink_component_targeting_run_dir(self) -> None:
        index_path, _ = self.write_force_final()
        alias = self.run_dir / "root-alias"
        alias.symlink_to(self.run_dir, target_is_directory=True)
        index = json.loads(index_path.read_text())
        original = Path(index["accepted_structure"]["gate"]["path"])
        index["accepted_structure"]["gate"]["path"] = str(
            alias / original.relative_to(self.run_dir.resolve())
        )
        index_path.write_text(json.dumps(index))
        gate_path = self.run_dir / "force/final/gate.json"
        gate = json.loads(gate_path.read_text())
        gate["index_sha256"] = sha256_path(index_path)
        gate_path.write_text(json.dumps(gate))
        with self.assertRaisesRegex(SubmissionError, "path may not contain a symlink"):
            require_force_gate(self.context)

    def test_dependency_syntax_is_fail_closed(self) -> None:
        plan = StagePlan(
            stage="relax",
            script=SLURM_DIR / "relax.sbatch",
            account="def-kleinke_cpu",
            exports={
                "CAMPAIGN_CONFIG": str(self.config_path.resolve()),
                "RUN_DIR": str(self.run_dir.resolve()),
                "ATTEMPT_ID": "attempt",
                "P3_SLURM_DIR": str(SLURM_DIR),
                "P3_EXPECTED_CONFIG_SHA256": "a" * 64,
                "P3_SUBMIT_SCRIPT_SHA256": "b" * 64,
                "P3_STAGE_SCRIPT_SHA256": "c" * 64,
                "P3_CLUSTER_ENV_SHA256": "d" * 64,
                "P3_CAMPAIGN_CLI_SHA256": "e" * 64,
            },
            array=None,
            task_count=None,
            task_map=None,
            task_map_sha256=None,
        )
        with self.assertRaisesRegex(SubmissionError, "unsafe or unsupported dependency"):
            sbatch_command(plan, dependency="afterok:1;touch /tmp/x")
        plan.exports["BASH_ENV"] = "/tmp/injected"
        with self.assertRaisesRegex(SubmissionError, "explicit allow-list"):
            sbatch_command(plan)


if __name__ == "__main__":
    unittest.main()

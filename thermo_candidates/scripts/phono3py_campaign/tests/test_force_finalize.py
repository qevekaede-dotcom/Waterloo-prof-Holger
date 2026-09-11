from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as core
import force_backend as fb
import force_finalize as ff
import submit as submit_backend
from postprocess_backend import canonical_hash, file_hash, qe_settings


INPUT = """&CONTROL
 calculation = 'scf', prefix = 'test', outdir = './tmp',
 pseudo_dir = '/pseudo', tprnfor = .true.
/
&SYSTEM
 ibrav = 0, nat = 2, ntyp = 2, ecutwfc = 80, ecutrho = 640,
 occupations = 'fixed', nosym = .true., noinv = .true.
/
&ELECTRONS
 conv_thr = 1.0d-10
/
&IONS
/
&CELL
/
ATOMIC_SPECIES
S 32.06 S.UPF
Zr 91.22 Zr.UPF
ATOMIC_POSITIONS crystal
S 0 0 0
Zr 0.5 0.5 0.5
K_POINTS automatic
2 2 2 0 0 0
CELL_PARAMETERS angstrom
10 0 0
0 10 0
0 0 10
"""


def output(force: float) -> str:
    return f"""Program PWSCF
 convergence has been achieved in 10 iterations
 Forces acting on atoms (cartesian axes, Ry/au):

 atom 1 type 1 force = {force:.9f} 0.000000000 0.000000000
 atom 2 type 2 force = {-force:.9f} 0.000000000 0.000000000
 Total force = {abs(force) * 2:.9f} Total SCF correction = 0.0
 JOB DONE.
"""


class ForceFinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.config_path = self.root / "campaign.json"
        self.config_path.write_text("{}\n")
        self.matrix = [[2, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.config = {
            "material": {"formula": "Test2"},
            "production": {
                "selection_required": False,
                "automatic_submission_allowed": True,
                "selected_supercell": "m2",
                "selected_cutoff": "c1",
                "selected_fc3_supercell_matrix": copy.deepcopy(self.matrix),
                "selected_fc2_supercell_matrix": copy.deepcopy(self.matrix),
                "pristine_comparison_tolerances_ry_bohr": {
                    "maximum_component": 1e-6,
                    "rms_component": 1e-6,
                },
            },
            "force_and_amplitude_validation": {"selection_required": False},
            "displacements": {"hard_cap": 100},
            "resource_budget": {
                "maximum_total_core_hours": 1000,
                "approved_total_core_hours_per_material": 1000,
                "initial_timing_and_noise_batch": {"maximum_new_scf_tasks": 6},
                "pilot_batch_maximum_new_scf_tasks": 32,
                "production_first_batch_maximum_tasks": 32,
                "production_later_batch_maximum_tasks": 64,
                "maximum_technical_retries_per_task": 1,
            },
        }
        self.settings = {
            "supercell_id": "m2",
            "cutoff_id": "c1",
            "matrix": copy.deepcopy(self.matrix),
            "atoms": 2,
            "amplitude_angstrom": 0.03,
            "amplitude_bohr": 0.056,
            "ecutwfc_Ry": 80.0,
            "ecutrho_Ry": 640.0,
            "conv_thr_Ry": 1e-10,
            "kmesh": [2, 2, 2],
            "kshift": [0, 0, 0],
            "cutoff_pair_distance_cli_bohr": 4.0,
        }
        self._make_upstream()

    def ref(self, path: Path) -> dict[str, str]:
        return {"path": str(path.resolve()), "sha256": file_hash(path)}

    def dump(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def _make_upstream(self) -> None:
        final = self.run / "relax" / "final"
        final.mkdir(parents=True)
        self.unitcell = final / "unitcell.in"
        self.unitcell.write_text("accepted unitcell\n")
        self.gate = final / "gate.json"
        self.dump(self.gate, {"pass": True, "final_unitcell_sha256": file_hash(self.unitcell)})
        self.provenance = final / "provenance.json"
        self.dump(self.provenance, {"accepted": True})

        self.dataset_dir = self.run / "preflight" / "selected"
        self.dataset_dir.mkdir(parents=True)
        self.dataset = self.dataset_dir / "phono3py_disp.yaml"
        displacement_data = {
            "physical_unit": {"length": "au"},
            "supercell_matrix": self.matrix,
            "displacement_pairs": [
                {
                    "displacement_id": 1,
                    "displacement": [0.01, 0.0, 0.0],
                    "paired_with": [{
                        "displacements": [[0.01, 0.0, 0.0]],
                        "displacement_ids": [3],
                        "included": True,
                        "pair_distance": 1.0,
                    }],
                },
                {
                    "displacement_id": 2,
                    "displacement": [0.0, 0.01, 0.0],
                    "paired_with": [{
                        "displacements": [[0.0, 0.01, 0.0]],
                        "displacement_ids": [4],
                        "included": True,
                        "pair_distance": 1.5,
                    }],
                },
            ],
        }
        self.dump(self.dataset, displacement_data)
        self.supercell = self.dataset_dir / "supercell.in"
        self.supercell.write_text("pristine supercell\n")
        self.preflight_result = self.dataset_dir / "preflight_result.json"
        self.dump(self.preflight_result, {
            "selection_eligible": True,
            "supercell_id": "m2",
            "cutoff_id": "c1",
            "generated_displacement_ids": [1, 2, 3, 4],
            "yaml_sha256": file_hash(self.dataset),
        })
        self.inventory = self.run / "preflight" / "preflight_inventory.json"
        self.dump(self.inventory, {"stage": "preflight", "results": [_json(self.preflight_result)]})
        self.selection = self.run / "selection" / "selection_receipt.json"
        self.dump(self.selection, {"pass": True, "raw_replay": True})
        self.selection_validation = {
            "pass": True,
            "selection_receipt_path": str(self.selection.resolve()),
            "selection_receipt_sha256": file_hash(self.selection),
            "evidence_sha256": {str(self.selection.resolve()): file_hash(self.selection)},
        }
        self.pseudos = {}
        for species in ("S", "Zr"):
            path = self.run / "pseudos" / f"{species}.UPF"
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"{species} pseudo\n")
            self.pseudos[species] = {"file": str(path.resolve()), "sha256": file_hash(path)}
        self.sources = {
            str(path.resolve()): file_hash(path)
            for path in (
                self.gate,
                self.provenance,
                self.unitcell,
                self.inventory,
                self.preflight_result,
                self.dataset,
                self.supercell,
            )
        }

    def tearDown(self) -> None:
        # Some table-driven tests create a fresh fixture between cases.  The
        # TemporaryDirectory cleanups registered by setUp remain authoritative.
        pass

    def _make_task(
        self, bundle: Path, attempt_root: Path, task_id: int,
        displacement_id: int, manifest_path: Path, manifest_sha: str,
        job_id: str, force: float,
    ) -> tuple[Path, dict[str, object]]:
        task = _json(manifest_path)["tasks"][task_id]
        attempt = attempt_root / f"task-{task_id}"
        attempt.mkdir(parents=True)
        raw_job_id = str(int(job_id) * 100 + task_id)
        context = {
            "stage": "force",
            "attempt_id": attempt_root.name,
            "slurm_job_id": raw_job_id,
            "slurm_array_job_id": job_id,
            "slurm_array_task_id": str(task_id),
            "run_dir": str(self.run.resolve()),
            "config_sha256": file_hash(self.config_path),
        }
        (attempt / "context.tsv").write_text("".join(f"{key}\t{value}\n" for key, value in context.items()))
        (attempt / "exit_code.txt").write_text("0\n")
        (attempt / "finished_utc.txt").write_text("2026-01-01T00:00:00Z\n")
        (attempt / "scf.in").write_text(Path(task["input_path"]).read_text())
        (attempt / "scf.out").write_text(output(force))
        (attempt / "scf.err").write_text("")
        command = ["srun", "pw.x", "-nk", "1", "-in", "scf.in"]
        process = {
            "command": command,
            "cwd": str(attempt.resolve()),
            "returncode": 0,
            "stdout_sha256": file_hash(attempt / "scf.out"),
            "stderr_sha256": file_hash(attempt / "scf.err"),
        }
        self.dump(attempt / "force_claim.json", {"task_id": task_id, "manifest_sha256": manifest_sha})
        self.dump(attempt / "launch.json", {"task": task, "force_manifest_sha256": manifest_sha, "command": command})
        self.dump(attempt / "scf.process.json", process)
        self.dump(attempt / "result.json", {
            "healthy": True,
            "task_id": task_id,
            "displacement_id": displacement_id,
            "role": task["role"],
            "health": {"healthy": True},
            "process": process,
            "input_sha256": task["input_sha256"],
            "output_sha256": process["stdout_sha256"],
            "force_manifest_sha256": manifest_sha,
        })
        hashes = {name: file_hash(attempt / name) for name in ff.RAW_FILES}
        entry = {
            "task_id": task_id,
            "displacement_id": displacement_id,
            "role": task["role"],
            "attempt_path": str(attempt.resolve()),
            "context": context,
            "exit_code": 0,
            "finished": True,
            "errors": [],
            "outcome": "accepted_success",
            "evidence": {name: {"sha256": digest, "bytes": (attempt / name).stat().st_size} for name, digest in hashes.items()},
            "scheduler_records": [{
                "JobID": f"{job_id}_{task_id}",
                "JobIDRaw": raw_job_id,
                "State": "COMPLETED",
                "ExitCode": "0:0",
                "ElapsedRaw": "10",
                "AllocCPUS": "2",
                "MaxRSS": "1M",
            }],
        }
        raw = {"task_id": task_id, "attempt_path": str(attempt.resolve()), "files_sha256": hashes}
        return attempt, {"entry": entry, "raw": raw}

    def make_batch(
        self, batch_id: str, displacements: list[int], pristine_force: float
    ) -> dict[str, object]:
        attempt_id = f"force-{batch_id}"
        job_id = str(900 + len(list((self.run / "force").glob("bundle-*"))))
        bundle = self.run / "force" / f"bundle-{batch_id}"
        inputs = bundle / "inputs"
        inputs.mkdir(parents=True)
        tasks = []
        for task_id, displacement_id in enumerate([0] + displacements):
            input_path = inputs / f"task-{task_id:05d}.in"
            text = INPUT if displacement_id == 0 else INPUT.replace("S 0 0 0", f"S 0.00{displacement_id} 0 0")
            input_path.write_text(text)
            tasks.append({
                "task_id": task_id,
                "displacement_id": displacement_id,
                "role": "pristine" if displacement_id == 0 else "displacement",
                "input_path": str(input_path.resolve()),
                "input_sha256": file_hash(input_path),
                "nat": 2,
                "atom_labels": ["S", "Zr"],
                "species_types": [1, 2],
            })
        task_map = bundle / "task_map.tsv"
        with task_map.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=core.FORCE_TASK_MAP_FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(tasks)
        ledger = self.run / ".force_budget"
        ledger.mkdir(exist_ok=True)
        prior_records = [
            _json(path) for path in sorted(ledger.glob("reservation-*.json"))
        ]
        prior_reserved = sum(record["reserved_core_hours"] for record in prior_records)
        budget = bundle / "budget_receipt.json"
        self.dump(budget, {
            "schema_version": 1,
            "material": "Test2",
            "task_map_sha256": file_hash(task_map),
            "task_count": len(tasks),
            "resource_policy_sha256": core.canonical_sha256(self.config["resource_budget"]),
            "phase": "production",
            "mpi_ranks": 2,
            "maximum_concurrency": 1,
            "maximum_technical_retries_per_task": 1,
            "walltime_hours": 1,
            "reserved_core_hours": len(tasks) * 2 * 1 * 2,
            "reserved_core_hours_before": prior_reserved,
            "charged_core_hours_before": prior_reserved,
            "used_core_hours": 0,
            "approved_total_core_hours": self.config["resource_budget"]["approved_total_core_hours_per_material"],
            "production_batch_number": len(prior_records) + 1,
            "production_input_hashes": [task["input_sha256"] for task in tasks if task["displacement_id"] != 0],
        })
        ledger_reservation = ledger / f"reservation-{int(batch_id) - 1:06d}.json"
        self.dump(ledger_reservation, {
            "phase": "production",
            "task_count": len(tasks),
            "reserved_core_hours": len(tasks) * 2 * 1 * 2,
            "receipt_path": str(budget.resolve()),
            "receipt_sha256": file_hash(budget),
        })
        manifest = {
            "schema_version": 1,
            "stage": "force",
            "mode": "production",
            "material": "Test2",
            "config_sha256": file_hash(self.config_path),
            "force_policy_sha256": core.canonical_sha256({"production": self.config["production"], "force": self.config["force_and_amplitude_validation"]}),
            "settings": self.settings,
            "task_map_sha256": file_hash(task_map),
            "budget_receipt_sha256": file_hash(budget),
            "task_count": len(tasks),
            "tasks": tasks,
            "pseudopotentials": self.pseudos,
            "evidence_sha256": self.sources,
            "selection_validation": self.selection_validation,
            "selection_evidence_sha256": self.selection_validation["evidence_sha256"],
            "backend_sha256": file_hash(Path(fb.__file__).resolve()),
            "workflow_sha256": {
                str(Path(core.__file__).resolve()): file_hash(Path(core.__file__).resolve()),
            },
        }
        manifest_path = bundle / "force_manifest.json"
        self.dump(manifest_path, manifest)
        manifest_sha = file_hash(manifest_path)
        attempt_root = self.run / "slurm_attempts" / "force" / attempt_id
        rows = []
        for task_id, displacement_id in enumerate([0] + displacements):
            _, row = self._make_task(
                bundle, attempt_root, task_id, displacement_id, manifest_path,
                manifest_sha, job_id, pristine_force if displacement_id == 0 else 3e-6,
            )
            rows.append(row)

        submission = self.run / "submissions" / "force" / attempt_id
        request = submission / "request.json"
        primary_command = ["sbatch", "force_array.sbatch"]
        self.dump(request, {
            "stage": "force",
            "attempt_id": attempt_id,
            "config": str(self.config_path.resolve()),
            "config_sha256": file_hash(self.config_path),
            "run_dir": str(self.run.resolve()),
            "force_mode": "production",
            "force_manifest": str(manifest_path.resolve()),
            "force_manifest_sha256": manifest_sha,
            "task_map": str(task_map.resolve()),
            "task_map_sha256": file_hash(task_map),
            "budget_receipt": str(budget.resolve()),
            "budget_receipt_sha256": file_hash(budget),
            "command": primary_command,
        })
        submission_result = submission / "primary_result.json"
        self.dump(submission_result, {
            "job_id": job_id,
            "returncode": 0,
            "command": primary_command,
            "stdout": f"{job_id}\n",
        })
        collector = self.run / "slurm_attempts" / "collect" / f"collect-{batch_id}"
        collector.mkdir(parents=True)
        collector_job_id = str(int(job_id) + 5000)
        collector_command = ["sbatch", f"--dependency=afterany:{job_id}", "collect.sbatch"]
        collector_request = submission / "collector_request.json"
        self.dump(collector_request, {
            "attempt_id": collector.name,
            "primary_stage": "force",
            "primary_attempt_id": attempt_id,
            "primary_job_id": job_id,
            "dependency": f"afterany:{job_id}",
            "command": collector_command,
        })
        collector_result = submission / "collector_result.json"
        self.dump(collector_result, {"job_id": collector_job_id, "returncode": 0})
        submission_summary = submission / "submission.json"
        self.dump(submission_summary, {
            "healthy": True,
            "stage": "force",
            "attempt_id": attempt_id,
            "primary_job_id": job_id,
            "config_sha256": file_hash(self.config_path),
            "run_dir": str(self.run.resolve()),
            "task_map_sha256": file_hash(task_map),
            "force_manifest_sha256": manifest_sha,
            "budget_receipt_sha256": file_hash(budget),
            "force_mode": "production",
            "record_dir": str(submission.resolve()),
            "collector": {
                "attempt_id": collector.name,
                "job_id": collector_job_id,
                "primary_stage": "force",
                "primary_attempt_id": attempt_id,
                "primary_job_id": job_id,
                "dependency": f"afterany:{job_id}",
                "command": collector_command,
            },
        })
        accounting = collector / "primary_sacct.psv"
        accounting.write_text(
            "JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS\n"
            + "".join(
                "|".join(str(entry["scheduler_records"][0][key]) for key in core.SACCT_FIELDS) + "\n"
                for entry in [row["entry"] for row in rows]
            )
        )
        accounting_status = collector / "primary_sacct_exit_code.txt"
        accounting_status.write_text("0\n")
        collection_path = collector / "collection.json"
        self.dump(collection_path, {
            "schema_version": 1,
            "stage": "collect",
            "collection_kind": "force_array_batch",
            "material": "Test2",
            "collector_attempt": str(collector.resolve()),
            "force_mode": "production",
            "collection_integrity_complete": True,
            "batch_execution_complete": True,
            "incomplete": False,
            "primary": {
                "attempt_id": attempt_id,
                "job_id": job_id,
                "force_manifest": str(manifest_path.resolve()),
                "force_manifest_sha256": manifest_sha,
                "submitted_force_manifest_sha256": manifest_sha,
                "task_map": str(task_map.resolve()),
                "task_map_sha256": file_hash(task_map),
                "submitted_task_map_sha256": file_hash(task_map),
                "scheduler_accounting": {
                    "path": str(accounting.resolve()),
                    "sha256": file_hash(accounting),
                    "status_path": str(accounting_status.resolve()),
                    "status_sha256": file_hash(accounting_status),
                    "sacct_exit_code": 0,
                },
            },
            "entries": [row["entry"] for row in rows],
        })
        return {
            "batch_id": batch_id,
            "collection": self.ref(collection_path),
            "force_manifest": self.ref(manifest_path),
            "task_map": self.ref(task_map),
            "budget_receipt": self.ref(budget),
            "budget_ledger_reservation": self.ref(ledger_reservation),
            "submission_request": self.ref(request),
            "submission_result": self.ref(submission_result),
            "submission_summary": self.ref(submission_summary),
            "collector_request": self.ref(collector_request),
            "collector_result": self.ref(collector_result),
            "scheduler_accounting": self.ref(accounting),
            "scheduler_accounting_status": self.ref(accounting_status),
            "raw_artifacts": [row["raw"] for row in rows],
        }

    def make_plan(
        self,
        batch_displacements: list[list[int]] | None = None,
        pristine_forces: list[float] | None = None,
    ) -> tuple[Path, Path, dict[str, object]]:
        batch_displacements = batch_displacements or [[1, 3], [2, 4]]
        pristine_forces = pristine_forces or [1e-6, 1.5e-6]
        batches = [
            self.make_batch(str(index + 1), ids, pristine_forces[index])
            for index, ids in enumerate(batch_displacements)
        ]
        first_manifest = _json(Path(batches[0]["force_manifest"]["path"]))
        pristine_task = next(task for task in first_manifest["tasks"] if task["displacement_id"] == 0)
        first_raw = batches[0]["raw_artifacts"][pristine_task["task_id"]]
        plan = {
            "schema_version": 1,
            "stage": "force_finalize_plan",
            "material": "Test2",
            "config_sha256": file_hash(self.config_path),
            "accepted_structure": {
                "gate": self.ref(self.gate),
                "provenance": self.ref(self.provenance),
                "unitcell": self.ref(self.unitcell),
            },
            "selected_preflight": {
                "inventory": self.ref(self.inventory),
                "result": self.ref(self.preflight_result),
                "dataset": self.ref(self.dataset),
            },
            "selection_receipt": self.ref(self.selection),
            "pristine_comparison_tolerances_ry_bohr": {
                "maximum_component": 1e-6,
                "rms_component": 1e-6,
            },
            "canonical_pristine": {
                "batch_id": "1",
                "task_id": pristine_task["task_id"],
                "output_sha256": first_raw["files_sha256"]["scf.out"],
            },
            "batches": batches,
        }
        plan_path = self.run / "plans" / "force-finalize.json"
        self.dump(plan_path, plan)
        attempt = self.run / "slurm_attempts" / "force-finalize" / "attempt-1"
        attempt.mkdir(parents=True)
        return plan_path, attempt, plan

    def patches(self):
        return (
            patch("force_finalize.core.validate_config", return_value=(self.config, {"healthy": True})),
            patch("force_finalize.fb._settings", return_value=self.settings),
            patch("force_finalize.fb._provenance", return_value=(self.sources, {"accepted": True})),
            patch("force_finalize.fb.validate_selection_evidence", return_value=self.selection_validation),
            patch("force_finalize.fb.verify_selection_provenance"),
        )

    def execute(self, plan_path: Path, attempt: Path, expected_sha: str | None = None):
        managers = self.patches()
        for manager in managers:
            manager.start()
            self.addCleanup(manager.stop)
        return ff.finalize_force_dataset(
            self.config_path,
            self.run,
            plan_path,
            expected_plan_sha256=expected_sha or file_hash(plan_path),
            attempt_dir=attempt,
        )

    def assert_failure(self, plan_path: Path, attempt: Path, pattern: str) -> None:
        with self.assertRaisesRegex(ff.ForceFinalizeError, pattern):
            self.execute(plan_path, attempt)
        receipt = _json(attempt / "force_finalize_receipt.json")
        self.assertFalse(receipt["pass"])
        self.assertFalse((self.run / "force" / "final" / "gate.json").exists())

    def assert_budget_semantic_failure(self, field: str, value: object, pattern: str) -> None:
        """Rehash all outer pointers to model a ledger/receipt co-tamper."""
        plan_path, attempt, plan = self.make_plan()
        batch = plan["batches"][0]
        budget_path = Path(batch["budget_receipt"]["path"])
        ledger_path = Path(batch["budget_ledger_reservation"]["path"])
        manifest_path = Path(batch["force_manifest"]["path"])
        budget = _json(budget_path)
        ledger = _json(ledger_path)
        budget[field] = value
        ledger[field] = value
        self.dump(budget_path, budget)
        ledger["receipt_sha256"] = file_hash(budget_path)
        self.dump(ledger_path, ledger)
        manifest = _json(manifest_path)
        manifest["budget_receipt_sha256"] = file_hash(budget_path)
        self.dump(manifest_path, manifest)
        for key in ("budget_receipt", "budget_ledger_reservation", "force_manifest"):
            batch[key] = self.ref(Path(batch[key]["path"]))
        self.dump(plan_path, plan)
        self.assert_failure(plan_path, attempt, pattern)

    def refresh_plan_ref(self, plan_path: Path, plan: dict, batch: int, key: str) -> None:
        path = Path(plan["batches"][batch][key]["path"])
        plan["batches"][batch][key] = self.ref(path)
        self.dump(plan_path, plan)

    def mutate_first_displaced_input_physics(self, plan_path: Path, plan: dict) -> None:
        """Coherently rehash one task while leaving manifest.settings unchanged."""

        batch = plan["batches"][0]
        manifest_path = Path(batch["force_manifest"]["path"])
        manifest = _json(manifest_path)
        task = manifest["tasks"][1]
        source = Path(task["input_path"])
        source.write_text(source.read_text().replace("ecutwfc = 80", "ecutwfc = 81"))
        task["input_sha256"] = file_hash(source)

        task_map = Path(batch["task_map"]["path"])
        with task_map.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=core.FORCE_TASK_MAP_FIELDS,
                delimiter="\t",
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(manifest["tasks"])

        budget_path = Path(batch["budget_receipt"]["path"])
        budget = _json(budget_path)
        budget["task_map_sha256"] = file_hash(task_map)
        budget["production_input_hashes"] = [
            task["input_sha256"] for task in manifest["tasks"]
            if task["displacement_id"] != 0
        ]
        self.dump(budget_path, budget)
        reservation = self.run / ".force_budget" / "reservation-000000.json"
        reservation_value = _json(reservation)
        reservation_value["receipt_sha256"] = file_hash(budget_path)
        self.dump(reservation, reservation_value)

        manifest["task_map_sha256"] = file_hash(task_map)
        manifest["budget_receipt_sha256"] = file_hash(budget_path)
        self.dump(manifest_path, manifest)
        manifest_sha = file_hash(manifest_path)

        for raw_item in batch["raw_artifacts"]:
            task_id = raw_item["task_id"]
            attempt = Path(raw_item["attempt_path"])
            if task_id == 1:
                (attempt / "scf.in").write_text(source.read_text())
            claim = _json(attempt / "force_claim.json")
            claim["manifest_sha256"] = manifest_sha
            self.dump(attempt / "force_claim.json", claim)
            launch = _json(attempt / "launch.json")
            launch["task"] = manifest["tasks"][task_id]
            launch["force_manifest_sha256"] = manifest_sha
            self.dump(attempt / "launch.json", launch)
            result = _json(attempt / "result.json")
            result["force_manifest_sha256"] = manifest_sha
            result["input_sha256"] = manifest["tasks"][task_id]["input_sha256"]
            self.dump(attempt / "result.json", result)
            raw_item["files_sha256"] = {
                name: file_hash(attempt / name) for name in raw_item["files_sha256"]
            }

        request_path = Path(batch["submission_request"]["path"])
        request = _json(request_path)
        request["force_manifest_sha256"] = manifest_sha
        request["task_map_sha256"] = file_hash(task_map)
        request["budget_receipt_sha256"] = file_hash(budget_path)
        self.dump(request_path, request)
        summary_path = Path(batch["submission_summary"]["path"])
        summary = _json(summary_path)
        summary["force_manifest_sha256"] = manifest_sha
        summary["task_map_sha256"] = file_hash(task_map)
        summary["budget_receipt_sha256"] = file_hash(budget_path)
        self.dump(summary_path, summary)

        collection_path = Path(batch["collection"]["path"])
        collection = _json(collection_path)
        primary = collection["primary"]
        primary["force_manifest_sha256"] = manifest_sha
        primary["submitted_force_manifest_sha256"] = manifest_sha
        primary["task_map_sha256"] = file_hash(task_map)
        primary["submitted_task_map_sha256"] = file_hash(task_map)
        for raw_item, entry in zip(batch["raw_artifacts"], collection["entries"]):
            attempt = Path(raw_item["attempt_path"])
            entry["evidence"] = {
                name: {"sha256": digest, "bytes": (attempt / name).stat().st_size}
                for name, digest in raw_item["files_sha256"].items()
            }
        self.dump(collection_path, collection)

        for key in (
            "collection",
            "force_manifest",
            "task_map",
            "budget_receipt",
            "budget_ledger_reservation",
            "submission_request",
            "submission_summary",
        ):
            path = Path(batch[key]["path"])
            batch[key] = self.ref(path)
        self.dump(plan_path, plan)

    def test_happy_multi_batch_publishes_audited_force_only_gate(self) -> None:
        plan_path, attempt, _ = self.make_plan()
        result = self.execute(plan_path, attempt)
        self.assertTrue(result["pass"])
        gate = _json(Path(result["gate"]))
        index = _json(Path(result["index"]))
        self.assertTrue(gate["production_dataset_complete"])
        self.assertTrue(gate["eligible_for_force_constant_construction"])
        self.assertFalse(gate["scientific_results_claimed"])
        self.assertEqual(gate["force_finalize_backend_sha256"], file_hash(Path(ff.__file__).resolve()))
        self.assertEqual(index["force_finalize_backend_sha256"], gate["force_finalize_backend_sha256"])
        ledger = index["batches"][0]["budget_ledger_reservation"]
        self.assertEqual(file_hash(Path(ledger["path"])), ledger["sha256"])
        self.assertEqual(index["required_fc3_displacement_ids"], [1, 2, 3, 4])
        self.assertEqual(index["required_fc2_first_displacement_ids"], [1, 2])
        self.assertEqual([item["displacement_id"] for item in index["artifacts"]], [1, 2, 3, 4])

    def test_campaign_plan_then_finalize_happy_multi_batch(self) -> None:
        batch_1 = self.make_batch("1", [1, 3], 1e-6)
        batch_2 = self.make_batch("2", [2, 4], 1.5e-6)
        plan_path = self.run / "plans" / "campaign-generated.json"
        managers = self.patches()
        for manager in managers:
            manager.start()
            self.addCleanup(manager.stop)
        with patch("campaign.validate_config", return_value=(self.config, {"healthy": True})):
            planned = core.command_plan_force_finalize(
                self.config_path,
                self.run,
                output_path=plan_path,
                collection_paths=None,
                submission_attempt_ids=["force-1", "force-2"],
                canonical_pristine_batch_id="force-1",
            )
            finalized = core.command_finalize_force(
                self.config_path,
                self.run,
                plan_path=plan_path,
                expected_plan_sha256=planned["plan_sha256"],
                attempt_id="campaign-finalize-1",
            )
        self.assertTrue(finalized["pass"])
        generated = _json(plan_path)
        self.assertEqual([item["batch_id"] for item in generated["batches"]], ["force-1", "force-2"])
        self.assertIn("budget_ledger_reservation", generated["batches"][0])
        self.assertEqual(
            generated["pristine_comparison_tolerances_ry_bohr"],
            self.config["production"]["pristine_comparison_tolerances_ry_bohr"],
        )

    def test_finalize_force_cli_requires_separate_expected_plan_sha(self) -> None:
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            core.build_parser().parse_args(
                [
                    "finalize-force",
                    "--config",
                    str(self.config_path),
                    "--run-dir",
                    str(self.run),
                    "--plan",
                    str(self.run / "plans" / "force-finalize.json"),
                    "--attempt-id",
                    "attempt-1",
                ]
            )

    def test_submit_replays_canonical_gate_and_rejects_forged_backend(self) -> None:
        plan_path, attempt, _ = self.make_plan()
        finalized = self.execute(plan_path, attempt)
        context = submit_backend.SubmissionContext(
            config_path=self.config_path.resolve(),
            run_dir=self.run.resolve(),
            config=self.config,
            manifest={"material": "Test2"},
            config_sha256=file_hash(self.config_path),
        )
        submit_backend.require_force_gate(context)
        gate_path = Path(finalized["gate"])
        gate = _json(gate_path)
        gate["audit_backend_sha256"][str(Path(ff.__file__).resolve())] = "a" * 64
        self.dump(gate_path, gate)
        with self.assertRaisesRegex(
            submit_backend.SubmissionError, "backend hashes are stale or forged"
        ):
            submit_backend.require_force_gate(context)

    def test_submit_rejects_post_finalize_raw_mutation(self) -> None:
        plan_path, attempt, plan = self.make_plan()
        self.execute(plan_path, attempt)
        context = submit_backend.SubmissionContext(
            config_path=self.config_path.resolve(),
            run_dir=self.run.resolve(),
            config=self.config,
            manifest={"material": "Test2"},
            config_sha256=file_hash(self.config_path),
        )
        raw = Path(plan["batches"][0]["raw_artifacts"][1]["attempt_path"]) / "scf.out"
        raw.write_text(raw.read_text() + "mutated after finalization\n")
        with self.assertRaisesRegex(submit_backend.SubmissionError, "hash mismatch"):
            submit_backend.require_force_gate(context)

    def test_plan_generation_rejects_ambiguous_collection_and_missing_tolerances(self) -> None:
        batch = self.make_batch("1", [1, 2, 3, 4], 1e-6)
        collection = Path(batch["collection"]["path"])
        with patch("campaign.validate_config", return_value=(self.config, {"healthy": True})):
            with self.assertRaisesRegex(core.CampaignError, "collections must be unique"):
                core.command_plan_force_finalize(
                    self.config_path,
                    self.run,
                    output_path=self.run / "plans" / "ambiguous.json",
                    collection_paths=[collection, collection],
                    submission_attempt_ids=None,
                    canonical_pristine_batch_id="force-1",
                )
        missing = copy.deepcopy(self.config)
        missing["production"].pop("pristine_comparison_tolerances_ry_bohr")
        with patch("campaign.validate_config", return_value=(missing, {"healthy": True})):
            with self.assertRaisesRegex(
                core.CampaignError,
                "missing required config field: production.pristine_comparison_tolerances",
            ):
                core.command_plan_force_finalize(
                    self.config_path,
                    self.run,
                    output_path=self.run / "plans" / "missing-tolerance.json",
                    collection_paths=[collection],
                    submission_attempt_ids=None,
                    canonical_pristine_batch_id="force-1",
                )

    def test_active_material_configs_remain_force_finalize_blocked(self) -> None:
        repository = Path(core.__file__).resolve().parents[3]
        for material in ("SrZrS3", "Rb2Cu2SnS4"):
            with self.subTest(material=material):
                config, _ = core.validate_config(
                    repository / "thermo_candidates" / material / "phono3py" / "campaign.json"
                )
                with self.assertRaisesRegex(
                    core.CampaignError, "production selection has not been released"
                ):
                    core._force_finalize_tolerances(config)

    def test_missing_extra_and_duplicate_displacements_fail(self) -> None:
        cases = (
            ([[1, 3], [2]], r"missing=\[4\]"),
            ([[1, 3], [2, 4, 5]], r"extra=\[5\]"),
            ([[1, 3], [2, 3, 4]], "duplicate displacement ID|repeats production task inputs"),
        )
        for batches, pattern in cases:
            with self.subTest(batches=batches):
                self.tearDown()
                self.setUp()
                plan_path, attempt, _ = self.make_plan(batches)
                self.assert_failure(plan_path, attempt, pattern)

    def test_raw_mutation_and_plan_hash_mismatch_fail(self) -> None:
        plan_path, attempt, plan = self.make_plan()
        raw = Path(plan["batches"][1]["raw_artifacts"][1]["attempt_path"]) / "scf.out"
        raw.write_text(raw.read_text() + "mutated\n")
        self.assert_failure(plan_path, attempt, "scf.out hash mismatch")

        self.tearDown()
        self.setUp()
        plan_path, attempt, _ = self.make_plan()
        with self.assertRaisesRegex(ff.ForceFinalizeError, "plan hash mismatch"):
            self.execute(plan_path, attempt, expected_sha="a" * 64)

    def test_first_batch_internal_physics_mismatch_fails(self) -> None:
        plan_path, attempt, plan = self.make_plan()
        self.mutate_first_displaced_input_physics(plan_path, plan)
        self.assert_failure(plan_path, attempt, "force artifact mismatch: settings_sha256")

    def test_submitted_bundle_anchor_rejects_coherently_rehashed_map_and_manifest(self) -> None:
        plan_path, attempt, plan = self.make_plan()
        batch = plan["batches"][0]
        manifest_path = Path(batch["force_manifest"]["path"])
        manifest = _json(manifest_path)
        task = manifest["tasks"][1]
        source = Path(task["input_path"])
        source.write_text(source.read_text() + "! rewritten before a second reservation\n")
        task["input_sha256"] = file_hash(source)
        task_map = Path(batch["task_map"]["path"])
        with task_map.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=core.FORCE_TASK_MAP_FIELDS,
                                    delimiter="\t", lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(manifest["tasks"])
        budget_path = Path(batch["budget_receipt"]["path"])
        budget = _json(budget_path)
        budget["task_map_sha256"] = file_hash(task_map)
        budget["production_input_hashes"] = [
            item["input_sha256"] for item in manifest["tasks"] if item["displacement_id"] != 0
        ]
        self.dump(budget_path, budget)
        ledger_path = Path(batch["budget_ledger_reservation"]["path"])
        ledger = _json(ledger_path)
        ledger["receipt_sha256"] = file_hash(budget_path)
        self.dump(ledger_path, ledger)
        manifest["task_map_sha256"] = file_hash(task_map)
        manifest["budget_receipt_sha256"] = file_hash(budget_path)
        self.dump(manifest_path, manifest)
        for key in ("force_manifest", "task_map", "budget_receipt", "budget_ledger_reservation"):
            batch[key] = self.ref(Path(batch[key]["path"]))
        self.dump(plan_path, plan)
        self.assert_failure(plan_path, attempt, "submitted force request no longer binds")

    def test_budget_ledger_replay_failure_fails(self) -> None:
        plan_path, attempt, _ = self.make_plan()
        reservation = self.run / ".force_budget" / "reservation-000000.json"
        value = _json(reservation)
        value["receipt_sha256"] = "a" * 64
        self.dump(reservation, value)
        self.assert_failure(plan_path, attempt, "budget ledger reservation hash mismatch")

    def test_finalizer_rejects_wrong_budget_phase_after_full_rehash(self) -> None:
        self.assert_budget_semantic_failure(
            "phase", "validation", "budget receipt phase and force-manifest mode disagree"
        )

    def test_finalizer_rejects_negative_budget_task_count_after_full_rehash(self) -> None:
        self.assert_budget_semantic_failure(
            "task_count", -1, "budget ledger replay failed.*task_count is invalid"
        )

    def test_finalizer_rejects_inconsistent_budget_reservation_after_full_rehash(self) -> None:
        self.assert_budget_semantic_failure(
            "reserved_core_hours", 1, "budget ledger replay failed.*inconsistent|submitted force request"
        )

    def test_index_exposes_post_finalize_budget_ledger_drift(self) -> None:
        plan_path, attempt, _ = self.make_plan()
        result = self.execute(plan_path, attempt)
        index = _json(Path(result["index"]))
        ledger = index["batches"][0]["budget_ledger_reservation"]
        ledger_path = Path(ledger["path"])
        value = _json(ledger_path)
        value["receipt_sha256"] = "a" * 64
        self.dump(ledger_path, value)
        self.assertNotEqual(file_hash(ledger_path), ledger["sha256"])

    def test_submission_and_accounting_mutations_fail(self) -> None:
        plan_path, attempt, plan = self.make_plan()
        result_path = Path(plan["batches"][0]["submission_result"]["path"])
        value = _json(result_path)
        value["job_id"] = "99999"
        self.dump(result_path, value)
        self.refresh_plan_ref(plan_path, plan, 0, "submission_result")
        self.assert_failure(plan_path, attempt, "submission result job/command mismatch")

        self.tearDown()
        self.setUp()
        plan_path, attempt, plan = self.make_plan()
        collection_path = Path(plan["batches"][0]["collection"]["path"])
        collection = _json(collection_path)
        collection["entries"][1]["scheduler_records"][0]["State"] = "FAILED"
        accounting_path = Path(plan["batches"][0]["scheduler_accounting"]["path"])
        lines = accounting_path.read_text().splitlines()
        fields = lines[2].split("|")
        fields[2] = "FAILED"
        lines[2] = "|".join(fields)
        accounting_path.write_text("\n".join(lines) + "\n")
        collection["primary"]["scheduler_accounting"]["sha256"] = file_hash(accounting_path)
        self.dump(collection_path, collection)
        self.refresh_plan_ref(plan_path, plan, 0, "scheduler_accounting")
        self.refresh_plan_ref(plan_path, plan, 0, "collection")
        self.assert_failure(plan_path, attempt, "scheduler state is not COMPLETED")

    def test_pristine_mismatch_fails_closed(self) -> None:
        plan_path, attempt, _ = self.make_plan(pristine_forces=[1e-6, 9e-6])
        self.assert_failure(plan_path, attempt, "pristine maximum-component mismatch")

    def test_symlink_escape_ready_to_attach_and_collision_fail(self) -> None:
        plan_path, attempt, plan = self.make_plan()
        original = Path(plan["batches"][0]["collection"]["path"])
        linked = self.run / "linked-collection.json"
        linked.symlink_to(original)
        plan["batches"][0]["collection"] = {"path": str(linked), "sha256": file_hash(original)}
        self.dump(plan_path, plan)
        self.assert_failure(plan_path, attempt, "symlink")

        self.tearDown()
        self.setUp()
        plan_path, attempt, _ = self.make_plan()
        outside = self.root / "outside-plan.json"
        outside.write_text(plan_path.read_text())
        with self.assertRaisesRegex(ff.ForceFinalizeError, "strict descendant"):
            self.execute(outside, attempt, expected_sha=file_hash(outside))

        self.tearDown()
        self.setUp()
        plan_path, attempt, _ = self.make_plan()
        frozen = self.run / "READY_TO_ATTACH" / "plan.json"
        frozen.parent.mkdir()
        frozen.write_text(plan_path.read_text())
        with self.assertRaisesRegex(ff.ForceFinalizeError, "READY_TO_ATTACH"):
            self.execute(frozen, attempt, expected_sha=file_hash(frozen))

        self.tearDown()
        self.setUp()
        plan_path, attempt, _ = self.make_plan()
        alias = self.run / "root-alias"
        alias.symlink_to(self.run, target_is_directory=True)
        aliased_plan = alias / plan_path.relative_to(self.run)
        with self.assertRaisesRegex(ff.ForceFinalizeError, "symlink"):
            self.execute(aliased_plan, attempt, expected_sha=file_hash(plan_path))

        self.tearDown()
        self.setUp()
        plan_path, _, _ = self.make_plan()
        nested_attempt = self.run / "slurm_attempts" / "force-finalize" / "outer" / "inner"
        nested_attempt.mkdir(parents=True)
        with self.assertRaisesRegex(ff.ForceFinalizeError, "one direct"):
            self.execute(plan_path, nested_attempt)

        self.tearDown()
        self.setUp()
        plan_path, attempt, _ = self.make_plan()
        prior = attempt / "force_finalize_receipt.json"
        prior.write_text('{"sentinel": true}\n')
        with self.assertRaisesRegex(ff.ForceFinalizeError, "receipt already exists"):
            self.execute(plan_path, attempt)
        self.assertEqual(prior.read_text(), '{"sentinel": true}\n')

        self.tearDown()
        self.setUp()
        plan_path, attempt, _ = self.make_plan()
        final = self.run / "force" / "final"
        final.mkdir(parents=True)
        marker = final / "marker"
        marker.write_text("keep")
        self.assert_failure(plan_path, attempt, "canonical force final directory already exists")
        self.assertEqual(marker.read_text(), "keep")

    def test_independent_fc2_matrix_is_rejected(self) -> None:
        plan_path, attempt, _ = self.make_plan()
        self.config["production"]["selected_fc2_supercell_matrix"] = [[3, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assert_failure(plan_path, attempt, "independent FC2 supercells are not supported")


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


if __name__ == "__main__":
    unittest.main()

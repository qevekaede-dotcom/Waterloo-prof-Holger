from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import campaign


VALID_QE_INPUT = """&CONTROL
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

VALID_QE_OUTPUT = """Program PWSCF
 convergence has been achieved in 10 iterations
 Forces acting on atoms (cartesian axes, Ry/au):

 atom 1 type 1 force = 0.000001 0.000000 0.000000
 atom 2 type 2 force = -0.000001 0.000000 0.000000
 Total force = 0.0000014 Total SCF correction = 0.0
 JOB DONE.
"""


class ForceCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.config_path = self.root / "campaign.json"
        self.config_path.write_text('{"fixture": true}\n')
        self.config = {"material": {"formula": "Test2"}}
        self.primary_attempt_id = "force-primary-1"
        self.primary_job_id = "900"
        self.bundle = self.run_dir / "force" / "bundle-1"
        (self.bundle / "inputs").mkdir(parents=True)
        self.collector = self.run_dir / "slurm_attempts" / "collect" / "collector-1"
        self.collector.mkdir(parents=True)

    def make_bundle(self, mode: str = "pilot") -> tuple[Path, Path, list[dict[str, object]]]:
        tasks: list[dict[str, object]] = []
        for task_id, displacement_id in enumerate((0, 1)):
            source = self.bundle / "inputs" / f"task-{task_id:05d}.in"
            source.write_text(f"input {task_id}\n")
            tasks.append(
                {
                    "task_id": task_id,
                    "displacement_id": displacement_id,
                    "role": "pristine" if displacement_id == 0 else "displacement",
                    "input_path": str(source.resolve()),
                    "input_sha256": campaign.sha256_path(source),
                    "nat": 2,
                    "atom_labels": ["T", "T"],
                    "species_types": [1, 1],
                }
            )
        stream = io.StringIO()
        writer = csv.DictWriter(
            stream,
            fieldnames=campaign.FORCE_TASK_MAP_FIELDS,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(tasks)
        task_map = self.bundle / "task_map.tsv"
        task_map.write_text(stream.getvalue())
        manifest = {
            "schema_version": 1,
            "stage": "force",
            "mode": mode,
            "material": "Test2",
            "config_sha256": campaign.sha256_path(self.config_path),
            "task_map_sha256": campaign.sha256_path(task_map),
            "task_count": len(tasks),
            "tasks": tasks,
        }
        manifest_path = self.bundle / "force_manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        return manifest_path, task_map, tasks

    def make_real_bundle(self) -> tuple[Path, Path, list[dict[str, object]]]:
        """Build a minimal raw receipt chain accepted by the real adapter."""

        dataset_dir = self.run_dir / "preflight" / "candidate-real"
        dataset_dir.mkdir(parents=True)
        dataset = dataset_dir / "phono3py_disp.yaml"
        dataset.write_text("synthetic displacement dataset\n")
        supercell = dataset_dir / "supercell.in"
        supercell.write_text("synthetic pristine supercell\n")
        pseudo_dir = self.run_dir / "pseudos"
        pseudo_dir.mkdir()
        pseudos: dict[str, dict[str, str]] = {}
        for label in ("S", "Zr"):
            pseudo = pseudo_dir / f"{label}.UPF"
            pseudo.write_text(f"synthetic {label} pseudopotential\n")
            pseudos[label] = {
                "file": str(pseudo.resolve()),
                "sha256": campaign.sha256_path(pseudo),
            }

        tasks: list[dict[str, object]] = []
        for task_id, displacement_id in enumerate((0, 1)):
            source = self.bundle / "inputs" / f"task-{task_id:05d}.in"
            contents = VALID_QE_INPUT
            if displacement_id:
                contents = contents.replace("S 0 0 0", "S 0.001 0 0")
            source.write_text(contents)
            tasks.append(
                {
                    "task_id": task_id,
                    "displacement_id": displacement_id,
                    "role": "pristine" if displacement_id == 0 else "displacement",
                    "input_path": str(source.resolve()),
                    "input_sha256": campaign.sha256_path(source),
                    "nat": 2,
                    "atom_labels": ["S", "Zr"],
                    "species_types": [1, 2],
                }
            )
        task_map = self.bundle / "task_map.tsv"
        with task_map.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=campaign.FORCE_TASK_MAP_FIELDS,
                delimiter="\t",
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(tasks)
        manifest = {
            "schema_version": 1,
            "stage": "force",
            "mode": "pilot",
            "material": "Test2",
            "config_sha256": campaign.sha256_path(self.config_path),
            "task_map_sha256": campaign.sha256_path(task_map),
            "task_count": len(tasks),
            "tasks": tasks,
            "pseudopotentials": pseudos,
            "evidence_sha256": {
                str(dataset.resolve()): campaign.sha256_path(dataset),
                str(supercell.resolve()): campaign.sha256_path(supercell),
            },
        }
        manifest_path = self.bundle / "force_manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        return manifest_path, task_map, tasks

    def make_task(self, task_id: int, exit_code: int) -> Path:
        task = (
            self.run_dir
            / "slurm_attempts"
            / "force"
            / self.primary_attempt_id
            / f"task-{task_id}"
        )
        task.mkdir(parents=True)
        raw_job_id = str(int(self.primary_job_id) + task_id + 1)
        context = {
            "stage": "force",
            "attempt_id": self.primary_attempt_id,
            "slurm_job_id": raw_job_id,
            "slurm_array_job_id": self.primary_job_id,
            "slurm_array_task_id": str(task_id),
            "run_dir": str(self.run_dir.resolve()),
            "config_sha256": campaign.sha256_path(self.config_path),
        }
        (task / "context.tsv").write_text(
            "".join(f"{key}\t{value}\n" for key, value in context.items())
        )
        (task / "exit_code.txt").write_text(f"{exit_code}\n")
        (task / "finished_utc.txt").write_text("2026-09-10T00:00:00Z\n")
        (task / "launch.json").write_text(
            json.dumps({"job_id": raw_job_id})
        )
        if exit_code:
            (task / "failure.json").write_text(
                json.dumps(
                    {
                        "task_id": task_id,
                        "error_type": "ForceError",
                        "error": "synthetic upstream failure",
                        "created_utc": "2026-09-10T00:00:00Z",
                    }
                )
            )
        return task

    def make_real_success_task(
        self, manifest_path: Path, task: dict[str, object]
    ) -> Path:
        task_id = int(task["task_id"])
        attempt = self.make_task(task_id, 0)
        (attempt / "scf.in").write_text(Path(str(task["input_path"])).read_text())
        (attempt / "scf.out").write_text(VALID_QE_OUTPUT)
        (attempt / "scf.err").write_text("")
        command = ["srun", "pw.x", "-nk", "1", "-in", "scf.in"]
        process = {
            "command": command,
            "cwd": str(attempt.resolve()),
            "started_utc": "2026-09-10T00:00:00Z",
            "finished_utc": "2026-09-10T00:02:00Z",
            "returncode": 0,
            "stdout_sha256": campaign.sha256_path(attempt / "scf.out"),
            "stderr_sha256": campaign.sha256_path(attempt / "scf.err"),
        }
        manifest_sha = campaign.sha256_path(manifest_path)
        (attempt / "force_claim.json").write_text(
            json.dumps({"task_id": task_id, "manifest_sha256": manifest_sha})
        )
        raw_job_id = str(int(self.primary_job_id) + task_id + 1)
        (attempt / "launch.json").write_text(
            json.dumps(
                {
                    "task": task,
                    "force_manifest_sha256": manifest_sha,
                    "command": command,
                    "created_utc": "2026-09-10T00:00:00Z",
                    "job_id": raw_job_id,
                }
            )
        )
        (attempt / "scf.process.json").write_text(json.dumps(process))
        (attempt / "result.json").write_text(
            json.dumps(
                {
                    "healthy": True,
                    "task_id": task_id,
                    "displacement_id": task["displacement_id"],
                    "role": task["role"],
                    "health": {"healthy": True},
                    "process": process,
                    "input_sha256": task["input_sha256"],
                    "output_sha256": process["stdout_sha256"],
                    "force_manifest_sha256": manifest_sha,
                }
            )
        )
        return attempt

    def make_accounting(self, states: tuple[tuple[str, str], ...]) -> tuple[Path, Path]:
        accounting = self.collector / "primary_sacct.psv"
        lines = ["|".join(campaign.SACCT_FIELDS)]
        for task_id, (state, exit_code) in enumerate(states):
            display_id = f"{self.primary_job_id}_{task_id}"
            raw_job_id = str(int(self.primary_job_id) + task_id + 1)
            lines.append(
                f"{display_id}|{raw_job_id}|{state}|{exit_code}|120|32|"
            )
            lines.append(
                f"{display_id}.batch|{raw_job_id}.batch|{state}|{exit_code}|120|32|128M"
            )
        accounting.write_text("\n".join(lines) + "\n")
        status = self.collector / "primary_sacct_exit_code.txt"
        status.write_text("0\n")
        return accounting, status

    def collect(self, manifest: Path, task_map: Path, accounting: Path, status: Path):
        with patch.object(campaign, "require_compute_node"), patch.object(
            campaign, "validate_config", return_value=(self.config, {})
        ), patch.object(campaign, "verify_upstream_manifest", return_value={}), patch.dict(
            os.environ, {"P3_ATTEMPT_DIR": str(self.collector)}
        ):
            return campaign.command_collect(
                self.config_path,
                self.run_dir,
                primary_stage="force",
                primary_attempt_id=self.primary_attempt_id,
                primary_job_id=self.primary_job_id,
                scheduler_accounting=accounting,
                scheduler_accounting_status=status,
                force_manifest=manifest,
                task_map=task_map,
                expected_force_manifest_sha256=campaign.sha256_path(manifest),
                expected_task_map_sha256=campaign.sha256_path(task_map),
            )

    @staticmethod
    def artifact(task: Path, task_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            input_path=str(task / "scf.in"),
            output_path=str(task / "scf.out"),
            stderr_path=str(task / "scf.err"),
            manifest={"task_id": task_id, "receipt_chain_reaudited": True},
        )

    def test_failed_array_is_collected_successfully_but_remains_incomplete(self) -> None:
        manifest, task_map, _ = self.make_bundle("pilot")
        success = self.make_task(0, 0)
        self.make_task(1, 1)
        accounting, status = self.make_accounting(
            (("COMPLETED", "0:0"), ("FAILED", "1:0"))
        )
        with patch(
            "postprocess_backend.load_force_artifact",
            return_value=self.artifact(success, 0),
        ) as loader:
            report = self.collect(manifest, task_map, accounting, status)

        loader.assert_called_once_with(manifest.resolve(), success.resolve(), 0)
        self.assertTrue(report["collection_integrity_complete"])
        self.assertFalse(report["batch_execution_complete"])
        self.assertTrue(report["incomplete"])
        self.assertEqual(report["upstream_failure_count"], 1)
        self.assertEqual(report["entries"][1]["outcome"], "upstream_failed")
        self.assertEqual(
            report["entries"][0]["scheduler_records"][1]["MaxRSS"], "128M"
        )
        self.assertFalse(report["scientific_gate_published"])
        self.assertFalse(report["production_dataset_complete"])
        self.assertFalse(report["eligible_for_force_constant_construction"])
        self.assertTrue((self.collector / "collection.json").is_file())
        self.assertFalse((self.run_dir / "force" / "final" / "gate.json").exists())

    def test_successful_production_batch_is_not_a_full_dataset_gate(self) -> None:
        manifest, task_map, _ = self.make_bundle("production")
        tasks = [self.make_task(0, 0), self.make_task(1, 0)]
        accounting, status = self.make_accounting(
            (("COMPLETED", "0:0"), ("COMPLETED", "0:0"))
        )
        with patch(
            "postprocess_backend.load_force_artifact",
            side_effect=[self.artifact(task, i) for i, task in enumerate(tasks)],
        ):
            report = self.collect(manifest, task_map, accounting, status)

        self.assertTrue(report["batch_execution_complete"])
        self.assertFalse(report["incomplete"])
        self.assertEqual(report["force_mode"], "production")
        self.assertFalse(report["scientific_gate_published"])
        self.assertFalse(report["production_dataset_complete"])
        self.assertFalse(report["eligible_for_force_constant_construction"])

    def test_success_path_reaudits_real_raw_receipt_chain(self) -> None:
        manifest, task_map, task_records = self.make_real_bundle()
        task_dirs = [
            self.make_real_success_task(manifest, task) for task in task_records
        ]
        accounting, status = self.make_accounting(
            (("COMPLETED", "0:0"), ("COMPLETED", "0:0"))
        )

        report = self.collect(manifest, task_map, accounting, status)

        self.assertTrue(report["batch_execution_complete"])
        self.assertEqual(report["accepted_success_count"], 2)
        self.assertEqual(
            report["entries"][1]["artifact"]["output_path"],
            str((task_dirs[1] / "scf.out").resolve()),
        )
        receipt = report["entries"][1]["artifact"]["receipt"]
        self.assertEqual(receipt["force_manifest_sha256"], campaign.sha256_path(manifest))
        self.assertIn("result.json", receipt["receipt_sha256"])
        self.assertTrue(report["scientific_dataset_incomplete"])

    def test_missing_accounting_creates_incomplete_receipt_not_false_success(self) -> None:
        manifest, task_map, _ = self.make_bundle("pilot")
        self.make_task(0, 1)
        self.make_task(1, 1)
        accounting = self.collector / "missing.psv"
        status = self.collector / "missing-status.txt"
        with patch("postprocess_backend.load_force_artifact") as loader:
            report = self.collect(manifest, task_map, accounting, status)
        loader.assert_not_called()
        self.assertFalse(report["collection_integrity_complete"])
        self.assertTrue(report["incomplete"])
        self.assertTrue(
            any("missing scheduler accounting" in error for error in report["global_errors"])
        )

    def test_nonzero_exit_requires_a_failure_receipt(self) -> None:
        manifest, task_map, _ = self.make_bundle("pilot")
        self.make_task(0, 1)
        missing = self.make_task(1, 1)
        (missing / "failure.json").unlink()
        accounting, status = self.make_accounting(
            (("FAILED", "1:0"), ("FAILED", "1:0"))
        )

        report = self.collect(manifest, task_map, accounting, status)

        self.assertFalse(report["collection_integrity_complete"])
        self.assertTrue(report["incomplete"])
        self.assertIn("nonzero task exit lacks failure.json", report["entries"][1]["errors"])

    def test_scheduler_raw_job_and_exit_code_must_match_task_context(self) -> None:
        manifest, task_map, _ = self.make_bundle("pilot")
        self.make_task(0, 1)
        self.make_task(1, 1)
        accounting, status = self.make_accounting(
            (("FAILED", "1:0"), ("FAILED", "1:0"))
        )
        accounting.write_text(
            accounting.read_text()
            .replace("900_0|901|FAILED|1:0", "900_0|999|FAILED|2:0")
            .replace("900_0.batch|901.batch", "900_0.batch|999.batch")
        )

        report = self.collect(manifest, task_map, accounting, status)

        self.assertFalse(report["collection_integrity_complete"])
        errors = report["entries"][0]["errors"]
        self.assertTrue(any("context raw job" in error for error in errors))
        self.assertTrue(any("exit_code.txt disagrees" in error for error in errors))

    def test_altered_task_input_fails_before_writing_a_receipt(self) -> None:
        manifest, task_map, tasks = self.make_bundle("pilot")
        Path(str(tasks[0]["input_path"])).write_text("altered\n")
        self.make_task(0, 1)
        self.make_task(1, 1)
        accounting, status = self.make_accounting(
            (("FAILED", "1:0"), ("FAILED", "1:0"))
        )
        with self.assertRaisesRegex(campaign.CampaignError, "altered"):
            self.collect(manifest, task_map, accounting, status)
        self.assertFalse((self.collector / "collection.json").exists())

    def test_collection_receipt_refuses_nonidentical_overwrite(self) -> None:
        manifest, task_map, _ = self.make_bundle("pilot")
        self.make_task(0, 1)
        self.make_task(1, 1)
        accounting, status = self.make_accounting(
            (("FAILED", "1:0"), ("FAILED", "1:0"))
        )
        (self.collector / "collection.json").write_text('{"wrong": true}\n')
        with self.assertRaisesRegex(campaign.CampaignError, "overwrite"):
            self.collect(manifest, task_map, accounting, status)

    def test_collect_cli_forwards_explicit_primary_identity_and_force_anchors(self) -> None:
        arguments = [
            "collect",
            "--config",
            str(self.config_path),
            "--run-dir",
            str(self.run_dir),
            "--primary-stage",
            "force",
            "--primary-attempt-id",
            self.primary_attempt_id,
            "--primary-job-id",
            self.primary_job_id,
            "--scheduler-accounting",
            str(self.collector / "primary_sacct.psv"),
            "--scheduler-accounting-status",
            str(self.collector / "primary_sacct_exit_code.txt"),
            "--force-manifest",
            str(self.bundle / "force_manifest.json"),
            "--task-map",
            str(self.bundle / "task_map.tsv"),
            "--expect-force-manifest-sha",
            "a" * 64,
            "--expect-task-map-sha",
            "b" * 64,
        ]
        with patch.object(
            campaign, "command_collect", return_value={"schema_version": 1}
        ) as command, patch.object(campaign, "print_json"):
            self.assertEqual(campaign.main(arguments), 0)
        keywords = command.call_args.kwargs
        self.assertEqual(keywords["primary_stage"], "force")
        self.assertEqual(keywords["primary_attempt_id"], self.primary_attempt_id)
        self.assertEqual(keywords["primary_job_id"], self.primary_job_id)
        self.assertEqual(
            keywords["force_manifest"], self.bundle / "force_manifest.json"
        )
        self.assertEqual(keywords["task_map"], self.bundle / "task_map.tsv")
        self.assertEqual(keywords["expected_force_manifest_sha256"], "a" * 64)
        self.assertEqual(keywords["expected_task_map_sha256"], "b" * 64)

    def test_submitted_manifest_digest_cannot_be_rebound_before_collection(self) -> None:
        manifest, task_map, _ = self.make_bundle("pilot")
        original_hash = campaign.sha256_path(manifest)
        value = json.loads(manifest.read_text())
        value["created_after_submission"] = True
        manifest.write_text(json.dumps(value))
        self.make_task(0, 1)
        self.make_task(1, 1)
        accounting, status = self.make_accounting(
            (("FAILED", "1:0"), ("FAILED", "1:0"))
        )
        with patch.object(campaign, "require_compute_node"), patch.object(
            campaign, "validate_config", return_value=(self.config, {})
        ), patch.object(campaign, "verify_upstream_manifest", return_value={}), patch.dict(
            os.environ, {"P3_ATTEMPT_DIR": str(self.collector)}
        ), self.assertRaisesRegex(campaign.CampaignError, "submitted primary plan"):
            campaign.command_collect(
                self.config_path,
                self.run_dir,
                primary_stage="force",
                primary_attempt_id=self.primary_attempt_id,
                primary_job_id=self.primary_job_id,
                scheduler_accounting=accounting,
                scheduler_accounting_status=status,
                force_manifest=manifest,
                task_map=task_map,
                expected_force_manifest_sha256=original_hash,
                expected_task_map_sha256=campaign.sha256_path(task_map),
            )


if __name__ == "__main__":
    unittest.main()

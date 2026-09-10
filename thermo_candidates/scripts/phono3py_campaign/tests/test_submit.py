from __future__ import annotations

import json
import copy
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from submit import (
    SLURM_DIR,
    StagePlan,
    SubmissionContext,
    SubmissionError,
    canonical_sha256,
    ensure_no_active_duplicate,
    execute_submission,
    require_nibi_login,
    resolve_context,
    sbatch_command,
    sha256_path,
    stage_plan,
    validate_force_bundle,
    validate_task_map,
)


CONFIG_SHA = hashlib.sha256(b"{}\n").hexdigest()


class SubmissionTests(unittest.TestCase):
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
            "scheduler": {"cluster": "nibi", "slurm_account": "def-kleinke_cpu"},
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
        self.signed_auditor = patch("force_backend.audit_signed_pilot_dataset", side_effect=self.audit_signed_fixture).start()
        patch("force_backend.core.validate_config", return_value=(self.config, {})).start()
        self.selection_auditor = patch("force_backend.validate_selection_evidence", side_effect=lambda path, *args:
              copy.deepcopy(self.selection_audits[str(path)])).start()
        self.addCleanup(patch.stopall)

    def audit_signed_fixture(self, dataset, run_dir, config, settings, spec, *, expected_manifest_sha256):
        from force_backend import _match
        _match(Path(dataset)/"pilot_dataset_manifest.json", expected_manifest_sha256)
        return copy.deepcopy(self.signed_audits[str(Path(dataset).resolve())])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def pass_relax_gate(self) -> None:
        final = self.run_dir / "relax" / "final"
        final.mkdir(parents=True)
        (final / "gate.json").write_text('{"pass": true}\n')
        (final / "unitcell.in").write_text("unit cell\n")

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
        original_ids = list(range(1, original_count+1))
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
            "phase": "production" if mode == "production" else "initial" if count == 6 and pristine_count == 2 and len(duplicate_ids) == 2 else "validation",
            "task_map_sha256": sha256_path(path),
            "task_count": count,
            "mpi_ranks": 32,
            "maximum_concurrency": 2,
            "walltime_hours": 1,
            "maximum_technical_retries_per_task": 1,
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
        receipt.update(task_map_sha256=sha256_path(path), task_count=len(manifest["tasks"]))
        receipt_path.write_text(json.dumps(receipt))
        manifest["budget_receipt_sha256"] = sha256_path(receipt_path)
        (bundle / "force_manifest.json").write_text(json.dumps(manifest))
        (self.run_dir / ".force_budget/reservation-000000.json").write_text(json.dumps({"receipt_path":str(receipt_path.resolve()), "receipt_sha256":sha256_path(receipt_path)}))

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
        self.assertTrue(exports.startswith("--export=ALL,CAMPAIGN_CONFIG="))
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
        task_map = self.write_force_bundle(6, mode="pilot", pristine_count=2, duplicate_ids=[1,2])
        validated = validate_force_bundle(self.context, task_map)
        self.assertEqual(validated[1], 6)
        signed = validated[4]["signed_pilot_dataset"]
        self.assertEqual(self.signed_auditor.call_args.kwargs["expected_manifest_sha256"], signed["expected_manifest_sha256"])
        self.assertEqual(validated[6]["phase"], "initial")
        Path(signed["dataset_dir"], "pilot_dataset_manifest.json").write_text("altered signed plan")
        with self.assertRaisesRegex(SubmissionError, "signed pilot dataset gate"):
            validate_force_bundle(self.context, task_map)

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
        task_map = self.write_force_bundle(6, mode="pilot", pristine_count=2, duplicate_ids=[1,2])
        manifest_path = task_map.parent / "force_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["evidence_sha256"] = {}
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(SubmissionError, "bind every signed"):
            validate_force_bundle(self.context, task_map)
        task_map = self.write_force_bundle(6, mode="pilot", pristine_count=2, duplicate_ids=[1,2])
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
        with self.assertRaisesRegex(SubmissionError, "passing collected-force gate"):
            stage_plan(self.context, "postprocess", attempt_id="postprocess-1")
        final = self.run_dir / "force" / "final"
        final.mkdir(parents=True)
        (final / "gate.json").write_text('{"pass": true}\n')
        plan = stage_plan(self.context, "postprocess", attempt_id="postprocess-2")
        self.assertEqual(plan.script, SLURM_DIR / "postprocess.sbatch")

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
            },
            array=None,
            task_count=None,
            task_map=None,
            task_map_sha256=None,
        )
        with self.assertRaisesRegex(SubmissionError, "unsafe or unsupported dependency"):
            sbatch_command(plan, dependency="afterok:1;touch /tmp/x")


if __name__ == "__main__":
    unittest.main()

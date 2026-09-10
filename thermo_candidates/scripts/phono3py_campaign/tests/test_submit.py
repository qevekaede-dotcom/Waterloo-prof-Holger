from __future__ import annotations

import json
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
    ensure_no_active_duplicate,
    execute_submission,
    require_nibi_login,
    sbatch_command,
    stage_plan,
    validate_task_map,
)


CONFIG_SHA = "a" * 64


class SubmissionTests(unittest.TestCase):
    def test_accepts_real_nibi_login_hostname_but_not_other_hosts(self) -> None:
        with patch.dict("submit.os.environ", {}, clear=True), patch(
            "submit.socket.getfqdn", return_value="ic-l5.nibi.sharcnet"
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
            "scheduler": {"cluster": "nibi", "slurm_account": "def-kleinke_cpu"},
            "displacements": {"hard_cap": 8},
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

    def test_force_command_uses_exact_task_map_bounds_and_mandatory_exports(self) -> None:
        self.pass_relax_gate()
        task_map = self.write_task_map(3)
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
        self.assertEqual(command[4], "--array=0-2%2")
        self.assertEqual(command[-1], str(SLURM_DIR / "force_array.sbatch"))
        exports = command[3]
        self.assertTrue(exports.startswith("--export=ALL,CAMPAIGN_CONFIG="))
        self.assertIn(f",RUN_DIR={self.run_dir.resolve()}", exports)
        self.assertIn(",ATTEMPT_ID=force-attempt-1", exports)
        self.assertIn(f",P3_SLURM_DIR={SLURM_DIR}", exports)
        self.assertIn(f",TASK_MAP={task_map.resolve()}", exports)

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
        task_map = self.write_task_map()
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

    def test_task_map_rejects_nonsequential_or_out_of_run_rows(self) -> None:
        task_map = self.write_task_map(2)
        task_map.write_text("task_id\tinput\n0\ta\n2\tb\n")
        with self.assertRaisesRegex(SubmissionError, "exactly 0..N-1"):
            validate_task_map(task_map, self.run_dir.resolve(), 8)

        outside = Path(self.temp_dir.name) / "outside.tsv"
        outside.write_text("0\ta\n")
        with self.assertRaisesRegex(SubmissionError, "inside RUN_DIR"):
            validate_task_map(outside, self.run_dir.resolve(), 8)

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
        self.assertNotIn("ATTEMPT_ID=relax-attempt", collector[3])
        self.assertIn("--dependency=afterany:12345", collector)
        self.assertEqual(collector[-1], str(SLURM_DIR / "collect.sbatch"))
        self.assertEqual(result["primary_job_id"], "12345")
        self.assertEqual(result["collector"]["job_id"], "12346")
        record = Path(result["record_dir"])
        self.assertTrue((record / "request.json").is_file())
        self.assertTrue((record / "primary_result.json").is_file())
        self.assertTrue((record / "collector_result.json").is_file())
        self.assertTrue((record / "submission.json").is_file())

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

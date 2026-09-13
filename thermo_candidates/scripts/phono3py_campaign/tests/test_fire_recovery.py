from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as core
import fire_recovery as fire
import submit
from qe_input import parse_qe_input


CONFIG = core.REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"
REAL_SUBPROCESS_RUN = subprocess.run


class FireRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        # macOS exposes /var as a symlink to /private/var.  Use the physical
        # temporary root so ordinary test paths do not intentionally trip the
        # production lexical-ancestor policy.
        self.root = Path(self.temp.name).resolve()
        self.config = core.load_json(CONFIG)
        self.old = self.root / "old-real-lineage"
        source = core.resolve_repo_source(self.config, "source.qe_scf_input").read_bytes()
        for name in fire.REQUIRED_SEED_FILES:
            path = self.old / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source)
        audit = self.old / fire.STANDARDIZATION_AUDIT
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text('{"pass": true, "standardized": true, "strict_spacegroup_match": true, "reference_cell_match": true}\n')
        failed = self.old / fire.TRUSTED_FAILED_RELAX_OUTPUT
        failed.parent.mkdir(parents=True, exist_ok=True); failed.write_text("failed BFGS evidence\n")
        failed_context = failed.parent / "context.tsv"
        failed_context.write_text(
            f"stage\trelax\nattempt_id\t20260913T133538Z-relax-2d3fd832\n"
            f"slurm_job_id\t21848175\nconfig_sha256\t{fire._TRUSTED_HISTORICAL_CONFIG_SHA256}\n"
            f"run_dir\t{self.old.resolve()}\ngit_commit\t\n"
        )
        collection = self.old / fire.TRUSTED_LATER_COLLECTION
        collection.parent.mkdir(parents=True, exist_ok=True); collection.write_text("later collector evidence\n")
        collector_context = collection.parent / "context.tsv"
        collector_context.write_text(
            f"stage\tcollect\nattempt_id\t20260913T133539Z-collect-6d5ba984\n"
            f"slurm_job_id\t21848176\nconfig_sha256\t{fire._TRUSTED_HISTORICAL_CONFIG_SHA256}\n"
            f"primary_stage\trelax\nprimary_attempt_id\t20260913T133538Z-relax-2d3fd832\n"
            f"primary_job_id\t21848175\nrun_dir\t{self.old.resolve()}\ngit_commit\t\n"
        )
        pseudo_inventory = {}
        for species, filename in self.config["pseudopotentials"]["files"].items():
            pseudo = self.old / "lineage_source/pseudopotentials" / filename
            pseudo.parent.mkdir(parents=True, exist_ok=True)
            pseudo.write_bytes(f"trusted-{species}-upf\n".encode())
            pseudo_inventory[species] = {
                "filename": filename,
                "relative_path": f"lineage_source/pseudopotentials/{filename}",
                "sha256": core.sha256_path(pseudo),
            }
        (self.old / "polish_lineage_receipt.json").write_text(
            json.dumps({"pseudopotential_archive": pseudo_inventory})
        )
        binding = self.config["reviewed_fire_recovery"]["trusted_old_lineage"]
        binding["run_dir"] = str(self.old.resolve())
        binding["reference_sha256"] = hashlib.sha256(source).hexdigest()
        binding["standardization_audit_sha256"] = core.sha256_path(audit)
        binding["failed_relax_output_sha256"] = core.sha256_path(failed)
        binding["failed_relax_context_sha256"] = core.sha256_path(failed_context)
        binding["later_collector_collection_sha256"] = core.sha256_path(collection)
        binding["later_collector_context_sha256"] = core.sha256_path(collector_context)
        self.trust_patch = patch.object(fire, "TRUSTED_OLD_LINEAGE", dict(binding))
        self.trust_patch.start()
        self.audit_gate = {"submission_chain": {"primary_job_id": "21732222", "collector_job_id": "21732223"}}
        self.audit_patch = patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate)
        self.audit_patch.start()
        self.config_path = self.root / "campaign.json"
        self.config_path.write_text(json.dumps(self.config))

    def tearDown(self) -> None:
        self.audit_patch.stop()
        self.trust_patch.stop()
        self.temp.cleanup()

    def _reset_test_global_claim(self) -> None:
        registry = self.old.parent / fire.GLOBAL_CLAIM_DIRECTORY
        if registry.exists():
            shutil.rmtree(registry)

    def _successful_sbatch(self, *job_ids: str):
        pending = iter(job_ids)

        def run(command):
            job_id = next(pending)
            return job_id, {
                "command": list(command),
                "returncode": 0,
                "stdout": job_id + ";nibi\n",
                "stderr": "",
                "finished_utc": "2026-09-14T00:00:00Z",
            }

        return run

    @staticmethod
    def _successful_release(command, *args, **kwargs):
        if list(command[:2]) == ["scontrol", "release"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return REAL_SUBPROCESS_RUN(command, *args, **kwargs)

    def test_policy_has_exact_fire_controls_and_rejects_bfgs(self) -> None:
        fire.validate_fire_policy(self.config)
        bad = copy.deepcopy(self.config)
        bad["reviewed_fire_recovery"]["settings"]["trust_radius_ini"] = 0.1
        with self.assertRaises(core.CampaignError):
            fire.validate_fire_policy(bad)
        bad = copy.deepcopy(self.config)
        bad["reviewed_fire_recovery"]["pilot"]["release_conditions"].append("JOB_DONE")
        with self.assertRaises(core.CampaignError):
            fire.validate_fire_policy(bad)
        bad = copy.deepcopy(self.config)
        bad["reviewed_fire_recovery"]["trusted_old_lineage"]["run_dir"] = "/scratch/forged"
        with self.assertRaises(core.CampaignError):
            fire.validate_fire_policy(bad)

    def test_prepare_only_accepts_three_identical_reference_records(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate) as audit:
            result = fire.prepare_lineage(self.config_path, run, self.old)
        audit.assert_called_once()
        historical_config, historical_path = audit.call_args.args[:2]
        self.assertEqual(historical_config, {k: v for k, v in self.config.items() if k != fire.POLICY})
        self.assertEqual(historical_path, self.config_path.resolve())
        self.assertEqual(audit.call_args.kwargs["expected_config_sha256"], fire._TRUSTED_HISTORICAL_CONFIG_SHA256)
        self.assertTrue(result["healthy"])
        self.assertFalse(result["structure_accepted"])
        self.assertFalse(result["preflight_unlocked"])
        self.assertEqual((run / "fire_seed.in").read_bytes(), (self.old / "polish_reference.in").read_bytes())
        self.assertTrue((run / "lineage_source/one_reset_attempt/reference_unitcell.in").is_file())
        self.assertFalse((run / "lineage_source/lineage_source").exists())
        self.assertEqual(fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")["stage"], "fire-pilot")
        with self.assertRaises(core.CampaignError):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-full")
        (run / "fire_pilot_gate.json").write_text('{"pass": true, "full_release": true}\n')
        with self.assertRaises(core.CampaignError):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-full")

    def test_reference_mismatch_or_symlink_fails_closed(self) -> None:
        (self.old / "lineage_source/one_reset_run/recovery_reference.in").write_text("not a QE input\n")
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            with self.assertRaises(core.CampaignError):
                fire.prepare_lineage(self.config_path, self.root / "mismatch", self.old)
        # A source symlink is evidence ambiguity, even when its bytes match.
        target = self.old / "polish_reference.in"
        link = self.old / "lineage_source/one_reset_attempt/reference_unitcell.in"
        link.unlink(); link.symlink_to(target)
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            with self.assertRaises(core.CampaignError):
                fire.prepare_lineage(self.config_path, self.root / "symlink", self.old)

    def test_historical_failed_relax_context_job_drift_fails_closed(self) -> None:
        path = self.old / fire.TRUSTED_FAILED_RELAX_OUTPUT
        path = path.parent / "context.tsv"
        path.write_text(f"stage\trelax\nslurm_job_id\t999\nrun_dir\t{self.old.resolve()}\n")
        with self.assertRaises(core.CampaignError):
            fire.prepare_lineage(self.config_path, self.root / "bad-failed-context", self.old)

    def test_historical_context_identity_and_git_commit_drift_fail_closed(self) -> None:
        cases = (
            (fire.TRUSTED_FAILED_RELAX_OUTPUT, "attempt_id", "wrong-attempt", "failed_relax_context_sha256"),
            (fire.TRUSTED_FAILED_RELAX_OUTPUT, "config_sha256", "0" * 64, "failed_relax_context_sha256"),
            (fire.TRUSTED_LATER_COLLECTION, "primary_attempt_id", "wrong-attempt", "later_collector_context_sha256"),
            (fire.TRUSTED_LATER_COLLECTION, "git_commit", "unexpected", "later_collector_context_sha256"),
        )
        for relative, key, value, binding_key in cases:
            with self.subTest(key=key):
                context = self.old / relative
                context = context.parent / "context.tsv"
                original_context = context.read_text()
                fields = dict(line.split("\t", 1) for line in context.read_text().splitlines())
                fields[key] = value
                context.write_text("".join(f"{name}\t{item}\n" for name, item in fields.items()))
                binding = self.config["reviewed_fire_recovery"]["trusted_old_lineage"]
                original_hash = binding[binding_key]
                binding[binding_key] = core.sha256_path(context)
                self.config_path.write_text(json.dumps(self.config))
                with patch.object(fire, "TRUSTED_OLD_LINEAGE", dict(binding)):
                    with self.assertRaises(core.CampaignError):
                        fire.prepare_lineage(self.config_path, self.root / f"bad-context-{key}", self.old)
                context.write_text(original_context)
                binding[binding_key] = original_hash
                self.config_path.write_text(json.dumps(self.config))

        # Additional legitimate fields exist in the real Nibi contexts, so
        # schema minimization is unsafe.  Byte-level binding still rejects any
        # newly appended or rewritten field without changing the trust root.
        context = self.old / fire.TRUSTED_FAILED_RELAX_OUTPUT
        context = context.parent / "context.tsv"
        context.write_text(context.read_text() + "unreviewed\textra\n")
        with self.assertRaises(core.CampaignError):
            fire.prepare_lineage(
                self.config_path, self.root / "bad-context-extra", self.old
            )

    def test_prepare_rejects_symlinked_ancestor_before_safe_run_dir(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        alias_parent = self.root / "alias-parent"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(core.CampaignError):
            fire.prepare_lineage(self.config_path, alias_parent / "new-run", self.old)

    def test_ancestor_check_expands_home_and_rejects_dotdot(self) -> None:
        real_parent = self.root / "real-home"
        real_parent.mkdir()
        alias_parent = self.root / "alias-home"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        with patch.dict(os.environ, {"HOME": str(alias_parent)}):
            with self.assertRaises(core.CampaignError):
                fire._reject_existing_ancestor_symlinks(Path("~/new-run"), "RUN_DIR")
        with self.assertRaises(core.CampaignError):
            fire._reject_existing_ancestor_symlinks(self.root / "real-home/../new-run", "RUN_DIR")

    def test_polish_verifier_workflow_drift_rejects_prepared_receipt(self) -> None:
        run = self.root / "workflow-drift"
        fire.prepare_lineage(self.config_path, run, self.old)
        drift = fire._workflow_hashes()
        drift["polish_recovery.py"] = "0" * 64
        with patch("fire_recovery._workflow_hashes", return_value=drift):
            with self.assertRaises(core.CampaignError):
                fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")

    def test_exact_old_evidence_paths_reject_moved_hash_decoy_and_context(self) -> None:
        """A matching digest elsewhere cannot substitute the reviewed attempt."""
        source = self.old / fire.TRUSTED_FAILED_RELAX_OUTPUT
        decoy = self.old / "slurm_attempts/relax/decoy/relax.out"
        decoy.parent.mkdir(parents=True)
        os.replace(source, decoy)
        (decoy.parent / "context.tsv").write_text(
            f"stage\trelax\nslurm_job_id\t21848175\nrun_dir\t{self.old.resolve()}\n"
        )
        with self.assertRaises(core.CampaignError):
            fire.prepare_lineage(self.config_path, self.root / "moved-evidence", self.old)

    def test_exact_old_collection_path_rejects_moved_hash_decoy_and_context(self) -> None:
        """The later collector must also remain at its reviewed exact path."""
        source = self.old / fire.TRUSTED_LATER_COLLECTION
        decoy = self.old / "slurm_attempts/collect/decoy/collection.json"
        decoy.parent.mkdir(parents=True)
        os.replace(source, decoy)
        (decoy.parent / "context.tsv").write_text(
            "stage\tcollect\n"
            "slurm_job_id\t21848176\n"
            "primary_stage\trelax\n"
            "primary_job_id\t21848175\n"
            f"run_dir\t{self.old.resolve()}\n"
        )
        with self.assertRaises(core.CampaignError):
            fire.prepare_lineage(
                self.config_path, self.root / "moved-collection", self.old
            )

    def test_input_contains_fire_not_bfgs_controls(self) -> None:
        seed = core.resolve_repo_source(self.config, "source.qe_scf_input").read_text()
        text = fire._input(self.config, seed, Path("/tmp/pseudo"), "pilot")
        self.assertIn("ion_dynamics = 'fire'", text)
        self.assertIn("fire_dtmax", text)
        self.assertNotIn("trust_radius", text)
        self.assertNotIn("bfgs_ndim", text)
        control = text[text.index("&CONTROL"):text.index("&SYSTEM")]
        ions = text[text.index("&IONS"):text.index("ATOMIC_SPECIES")]
        self.assertRegex(control, r"(?m)^\s*dt\s*=")
        self.assertIsNone(re.search(r"(?m)^\s*dt\s*=", ions))
        electrons = text[text.index("&ELECTRONS"):text.index("&IONS")]
        self.assertRegex(electrons, r"(?m)^\s*scf_must_converge\s*=\s*\.true\.")

    def test_frozen_pseudopotential_same_filename_changed_bytes_fail(self) -> None:
        run = self.root / "pseudo-byte-drift"
        fire.prepare_lineage(self.config_path, run, self.old)
        filename = next(iter(self.config["pseudopotentials"]["files"].values()))
        pseudo = run / "lineage_source/pseudopotentials" / filename
        os.chmod(pseudo, 0o600)
        pseudo.write_bytes(b"changed bytes under the same trusted filename\n")
        with self.assertRaisesRegex(core.CampaignError, "pseudopotential hash drift"):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")

    def test_job_done_without_fire_markers_is_not_normal_convergence(self) -> None:
        self.assertFalse(all(marker in "JOB DONE." for marker in fire.FIRE_MARKERS))

    def test_pilot_plan_is_32_rank_two_hour_afterany_collectable(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        plan = submit.stage_plan(context, "fire-pilot", attempt_id="fire-pilot-test")
        self.assertIn("--ntasks=32", plan.scheduler_options)
        self.assertIn("--time=02:00:00", plan.scheduler_options)
        self.assertIn("P3_FIRE_RECOVERY_SHA256", plan.exports)
        self.assertIn("P3_FIRE_RELEASE_SHA256", plan.exports)
        self.assertIn("fire-pilot", submit.COLLECTED_STAGES)
        report = submit.plan_report(context, "fire-pilot", task_map=None, max_in_flight=None)
        self.assertTrue(report["execution_released"])
        self.assertIsNotNone(report["primary_command_template"])

    def test_execute_fire_pilot_requires_exact_config_then_submits_afterany(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        with patch("submit.require_nibi_login"), patch(
            "submit.run_sbatch",
            side_effect=self._successful_sbatch("101", "102"),
        ) as sbatch, patch(
            "submit.subprocess.run",
            side_effect=self._successful_release,
        ):
            result = submit.execute_submission(context, "fire-pilot", expected_config_sha=context.config_sha256, task_map=None, max_in_flight=None)
        self.assertEqual(sbatch.call_count, 2)
        self.assertEqual(result["primary_job_id"], "101")
        self.assertEqual(result["collector"]["dependency"], "afterany:101")
        record = Path(result["record_dir"])
        self.assertIn("--hold", core.load_json(record / "request.json")["command"])
        self.assertTrue((record / "collector_attachment.json").is_file())
        self.assertTrue((record / "primary_release.json").is_file())
        fire.verify_fire_collector_attachment(
            self.config_path, run, result["attempt_id"], "101"
        )
        attachment_path = record / "collector_attachment.json"
        os.chmod(attachment_path, 0o600)
        attachment = core.load_json(attachment_path)
        attachment["collector_dependency"] = "afterok:101"
        attachment_path.write_text(json.dumps(attachment))
        with self.assertRaisesRegex(core.CampaignError, "attachment exact binding drift"):
            fire.verify_fire_collector_attachment(
                self.config_path, run, result["attempt_id"], "101"
            )

    def test_full_public_and_internal_execute_remain_hard_locked(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            fire.prepare_lineage(self.config_path, run, self.old)
        with self.assertRaises(submit.SubmissionError):
            submit.resolve_context(self.config_path, run, "fire-full")
        context = submit.SubmissionContext(self.config_path.resolve(), run.resolve(), self.config, {"material": "Rb2Cu2SnS4"}, core.sha256_path(self.config_path))
        with patch("submit.run_sbatch") as sbatch:
            with self.assertRaises(submit.SubmissionError):
                submit._execute_locked(context, "fire-full", task_map=None, max_in_flight=None)
        sbatch.assert_not_called()

    def test_fire_primary_remains_held_if_afterany_collector_submission_fails(self) -> None:
        run = self.root / "collector-submit-failure"
        fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        primary_command: list[str] = []

        def fail_collector(command):
            if not primary_command:
                primary_command.extend(command)
                return "101", {
                    "command": list(command), "returncode": 0,
                    "stdout": "101;nibi\n", "stderr": "",
                    "finished_utc": "2026-09-14T00:00:00Z",
                }
            raise submit.RejectedSubmissionError(
                "collector rejected",
                {"command": list(command), "returncode": 1, "stdout": "", "stderr": "rejected", "finished_utc": "2026-09-14T00:00:01Z"},
            )

        release_calls: list[list[str]] = []

        def observe_release(command, *args, **kwargs):
            if command[0] == "scontrol":
                release_calls.append(list(command))
            return REAL_SUBPROCESS_RUN(command, *args, **kwargs)

        with patch("submit.require_nibi_login"), patch(
            "submit.run_sbatch", side_effect=fail_collector
        ), patch("submit.subprocess.run", side_effect=observe_release):
            with self.assertRaisesRegex(submit.SubmissionError, "afterany collector"):
                submit.execute_submission(
                    context, "fire-pilot",
                    expected_config_sha=context.config_sha256,
                    task_map=None, max_in_flight=None,
                )
        self.assertIn("--hold", primary_command)
        self.assertEqual(release_calls, [])
        records = [
            path for path in (run / "submissions/fire-pilot").iterdir()
            if path.name != ".submission.lock"
        ]
        self.assertEqual(len(records), 1)
        self.assertFalse((records[0] / "collector_attachment.json").exists())
        self.assertFalse((records[0] / "primary_release.json").exists())

    def test_internal_fire_pilot_cannot_bypass_public_login_config_and_lock_path(self) -> None:
        run = self.root / "internal-bypass"
        fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        with patch("submit.run_sbatch") as sbatch, patch(
            "submit.require_nibi_login",
            side_effect=submit.SubmissionError("login guard reached"),
        ) as login:
            with self.assertRaisesRegex(submit.SubmissionError, "login guard reached"):
                submit._execute_locked(
                    context,
                    "fire-pilot",
                    expected_config_sha=context.config_sha256,
                    task_map=None,
                    max_in_flight=None,
                )
        login.assert_called_once_with()
        sbatch.assert_not_called()
        with patch("submit.require_nibi_login"), patch(
            "submit.submission_lock",
            side_effect=submit.SubmissionError("submission lock reached"),
        ) as lock, patch("submit.run_sbatch") as sbatch:
            with self.assertRaisesRegex(submit.SubmissionError, "submission lock reached"):
                submit._execute_locked(
                    context,
                    "fire-pilot",
                    expected_config_sha=context.config_sha256,
                    task_map=None,
                    max_in_flight=None,
                )
        lock.assert_called_once_with(context.run_dir, "fire-pilot")
        sbatch.assert_not_called()

    def test_coherent_seed_receipt_replacement_and_unsafe_roots_fail_closed(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            fire.prepare_lineage(self.config_path, run, self.old)
        # Simulate an attacker changing all visible seed copies and their
        # self-reported receipt hashes.  The code-owned old-lineage anchor
        # must still reject the coherent local rewrite.
        replacement = (run / "fire_seed.in").read_bytes() + b"\n! coherent tamper\n"
        for relative in ("fire_seed.in", "lineage_source/polish_reference.in", "lineage_source/one_reset_attempt/reference_unitcell.in", "lineage_source/one_reset_run/recovery_reference.in"):
            path = run / relative
            os.chmod(path, 0o600); path.write_bytes(replacement)
        receipt_path = run / fire.LINEAGE
        os.chmod(receipt_path, 0o600)
        receipt = core.load_json(receipt_path)
        digest = hashlib.sha256(replacement).hexdigest()
        receipt["seed_sha256"] = digest
        receipt["source_hashes"] = {name: digest for name in fire.REQUIRED_SEED_FILES}
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaises(core.CampaignError):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")
        # A symlinked receipt/root must be rejected before its contents count.
        receipt_path.unlink(); receipt_path.symlink_to(run / "fire_seed.in")
        with self.assertRaises(core.CampaignError):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")

    def test_receipt_shape_release_flag_and_config_drift_fail_closed(self) -> None:
        for mutation in ("extra", "release", "scheduler"):
            with self.subTest(mutation=mutation):
                run = self.root / f"new-fire-run-{mutation}"
                with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
                    fire.prepare_lineage(self.config_path, run, self.old)
                if mutation == "scheduler":
                    altered = core.load_json(self.config_path)
                    altered["scheduler"]["slurm_account"] = "other_account"
                    self.config_path.write_text(json.dumps(altered))
                else:
                    path = run / fire.LINEAGE; os.chmod(path, 0o600)
                    receipt = core.load_json(path)
                    if mutation == "extra": receipt["unreviewed"] = True
                    else: receipt["structure_accepted"] = True
                    path.write_text(json.dumps(receipt))
                with self.assertRaises(core.CampaignError):
                    fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")
                if mutation == "scheduler":
                    self.config_path.write_text(json.dumps(self.config))
                self._reset_test_global_claim()

    def test_seed_attempt_and_submission_symlinks_fail_closed(self) -> None:
        for target in ("fire_seed.in", "slurm_attempts/fire-pilot", "submissions/fire-pilot"):
            with self.subTest(target=target):
                run = self.root / ("unsafe-" + target.replace("/", "-"))
                with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
                    fire.prepare_lineage(self.config_path, run, self.old)
                path = run / target
                if path.is_dir():
                    path.rmdir()
                    path.symlink_to(run / "lineage_source", target_is_directory=True)
                else:
                    path.unlink()
                    path.symlink_to(run / "lineage_source/polish_reference.in")
                with self.assertRaises(core.CampaignError):
                    fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")
                self._reset_test_global_claim()

    def test_any_previous_attempt_or_submission_consumes_the_one_shot_slot(self) -> None:
        for relative in ("slurm_attempts/fire-pilot/older-attempt", "submissions/fire-pilot/other-attempt"):
            with self.subTest(relative=relative):
                run = self.root / ("consumed-" + relative.replace("/", "-"))
                fire.prepare_lineage(self.config_path, run, self.old)
                (run / relative).mkdir()
                with self.assertRaisesRegex(core.CampaignError, "consumed"):
                    fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")
                self._reset_test_global_claim()

    def test_old_plan_only_receipt_and_release_tamper_fail_workflow_gate(self) -> None:
        run = self.root / "old-plan-only"
        fire.prepare_lineage(self.config_path, run, self.old)
        lineage_path = run / fire.LINEAGE
        os.chmod(lineage_path, 0o600)
        lineage = core.load_json(lineage_path)
        lineage["schema_version"] = 2
        lineage.pop("execution_policy_version")
        lineage.pop("git_commit")
        lineage_path.write_text(json.dumps(lineage))
        with self.assertRaises(core.CampaignError):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")

        self._reset_test_global_claim()
        run = self.root / "release-tamper"
        fire.prepare_lineage(self.config_path, run, self.old)
        release_path = run / fire.PILOT_RELEASE
        os.chmod(release_path, 0o600)
        release = core.load_json(release_path)
        release["full_execution_released"] = True
        release_path.write_text(json.dumps(release))
        with self.assertRaises(core.CampaignError):
            fire.verify_fire_submission_ready(self.config_path, run, "fire-pilot")

    def test_trusted_old_lineage_can_issue_only_one_global_ready_lineage(self) -> None:
        first = self.root / "global-first"
        second = self.root / "global-second"
        fire.prepare_lineage(self.config_path, first, self.old)
        self.assertEqual(
            fire.verify_fire_submission_ready(self.config_path, first, "fire-pilot")["stage"],
            "fire-pilot",
        )
        with self.assertRaisesRegex(core.CampaignError, "globally unique.*consumed"):
            fire.prepare_lineage(self.config_path, second, self.old)
        self.assertFalse((second / fire.PILOT_RELEASE).exists())

    def test_direct_fire_execution_cli_and_runner_are_hard_locked(self) -> None:
        with self.assertRaises(core.CampaignError):
            fire.run_stage(self.config_path, self.root / "absent", "pilot")
        with self.assertRaises(core.CampaignError):
            fire.finalize_stage(self.config_path, self.root / "absent", "pilot")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                fire.main(["run", "--config", str(self.config_path), "--run-dir", str(self.root / "absent"), "--stage", "pilot"])
            with self.assertRaises(SystemExit):
                fire.main(["finalize-pilot", "--config", str(self.config_path), "--run-dir", str(self.root / "absent"), "--collection", str(self.root / "none"), "--expect-collection-sha", "0" * 64])

    def _pilot_output(self, *, final_force: float = 5e-5, shift_fractional: float = 0.0) -> str:
        seed = parse_qe_input(core.resolve_repo_source(self.config, "source.qe_scf_input").read_text())
        chunks = ["Program PWSCF v.7.3.1 starts\n"]
        for step in range(8):
            force = 2e-4 + (final_force - 2e-4) * step / 7
            chunks.append("convergence has been achieved\nForces acting on atoms (cartesian axes, Ry/au):\n\n")
            for atom in range(1, seed.nat + 1):
                value = force if atom == 1 else 0.0
                chunks.append(f"atom {atom:4d} type  1   force = {value: .10E}  0.0000000000E+00  0.0000000000E+00\n")
            chunks.append(f"Total force = {abs(force):.10E}     Total SCF correction = 0.0000000000E+00\n")
        chunks.append("Begin final coordinates\nATOMIC_POSITIONS (crystal)\n")
        for index, atom in enumerate(seed.atomic_positions):
            x, y, z = atom.coordinates
            if index == 0:
                x += shift_fractional
            chunks.append(f"{atom.label} {x:.12f} {y:.12f} {z:.12f}\n")
        chunks.append("End final coordinates\nJOB DONE.\n")
        return "".join(chunks)

    def test_pilot_trajectory_success_and_failure_matrix(self) -> None:
        seed_path = core.resolve_repo_source(self.config, "source.qe_scf_input")
        output = self.root / "pilot.out"
        output.write_text(self._pilot_output())
        with patch("campaign.symmetry_scan", return_value=[{"symprec_angstrom": 1e-6, "spacegroup_number": 72, "spacegroup_symbol": "Ibam"}]):
            report = fire._pilot_trajectory(output, seed_path, 18)
        self.assertTrue(all(report["checks"].values()))
        cases = {
            "scf": self._pilot_output().replace("convergence has been achieved", "convergence NOT achieved", 1),
            "fatal": self._pilot_output() + "Error in routine electrons\n",
            "incomplete_force": self._pilot_output().replace("atom   18 type  1   force", "not-an-atom   18 force", 1),
            "missing_pwscf_header": self._pilot_output().replace(
                "Program PWSCF v.7.3.1 starts\n", "", 1
            ),
            "wrong_pwscf_version": self._pilot_output().replace(
                "Program PWSCF v.7.3.1 starts", "Program PWSCF v.6.0 starts", 1
            ),
            "final_coordinates_before_forces": (
                lambda text, block: text.replace(block, "", 1).replace(
                    "Program PWSCF v.7.3.1 starts\n",
                    "Program PWSCF v.7.3.1 starts\n" + block,
                    1,
                )
            )(
                self._pilot_output(),
                self._pilot_output()[
                    self._pilot_output().index("Begin final coordinates"):
                    self._pilot_output().index("JOB DONE.")
                ],
            ),
            "force_trend": self._pilot_output(final_force=2e-4),
            "threshold": self._pilot_output(final_force=1.1e-4),
            "shift": self._pilot_output(shift_fractional=0.01),
        }
        ordered = self._pilot_output()
        begin = ordered.index("Begin final coordinates")
        end = ordered.index("End final coordinates") + len("End final coordinates\n")
        final_block = ordered[begin:end]
        cases["final_coordinates_before_force_trajectory"] = (
            ordered[: ordered.index("\n") + 1]
            + final_block
            + ordered[ordered.index("\n") + 1 : begin]
            + ordered[end:]
        )
        for name, text in cases.items():
            with self.subTest(name=name):
                output.write_text(text)
                with patch("campaign.symmetry_scan", return_value=[{"symprec_angstrom": 1e-6, "spacegroup_number": 72, "spacegroup_symbol": "Ibam"}]):
                    result = fire._pilot_trajectory(output, seed_path, 18)
                self.assertFalse(all(result["checks"].values()) and not result["errors"])
        output.write_text(self._pilot_output())
        with patch("campaign.symmetry_scan", return_value=[{"symprec_angstrom": 1e-6, "spacegroup_number": 1, "spacegroup_symbol": "P1"}]):
            self.assertFalse(fire._pilot_trajectory(output, seed_path, 18)["checks"]["Ibam_at_1e-6A"])
        seed = parse_qe_input(seed_path.read_text())
        changed_cell = [list(row) for row in seed.cell_parameters]
        changed_cell[0][0] += 1e-4
        cell_block = "CELL_PARAMETERS (angstrom)\n" + "".join(
            " ".join(f"{value:.12f}" for value in row) + "\n" for row in changed_cell
        )
        output.write_text(self._pilot_output().replace("ATOMIC_POSITIONS (crystal)\n", cell_block + "ATOMIC_POSITIONS (crystal)\n", 1))
        with patch("campaign.symmetry_scan", return_value=[{"symprec_angstrom": 1e-6, "spacegroup_number": 72, "spacegroup_symbol": "Ibam"}]):
            self.assertFalse(fire._pilot_trajectory(output, seed_path, 18)["checks"]["cell_unchanged"])
        final_marker = self._pilot_output().index("Begin final coordinates")
        ordered = self._pilot_output()
        first_label = seed.atomic_positions[0].label
        different_label = next(atom.label for atom in seed.atomic_positions if atom.label != first_label)
        position = ordered.index(first_label + " ", final_marker)
        ordered = ordered[:position] + different_label + ordered[position + len(first_label):]
        output.write_text(ordered)
        with patch("campaign.symmetry_scan", return_value=[{"symprec_angstrom": 1e-6, "spacegroup_number": 72, "spacegroup_symbol": "Ibam"}]):
            with self.assertRaises(ValueError):
                fire._pilot_trajectory(output, seed_path, 18)

    def test_successful_raw_submission_collection_replays_read_only(self) -> None:
        run = self.root / "replay-success"
        fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        with patch("submit.require_nibi_login"), patch(
            "submit.run_sbatch",
            side_effect=self._successful_sbatch("101", "102"),
        ), patch(
            "submit.subprocess.run",
            side_effect=self._successful_release,
        ):
            submitted = submit.execute_submission(context, "fire-pilot", expected_config_sha=context.config_sha256, task_map=None, max_in_flight=None)
        attempt_id = submitted["attempt_id"]
        record_dir = Path(submitted["record_dir"])
        request = core.load_json(record_dir / "request.json")
        wrapper = run / "slurm_attempts/fire-pilot" / attempt_id
        wrapper.mkdir()
        workflow = request["workflow_sha256"]
        wrapper_context = {
            "stage": "fire-pilot", "attempt_id": attempt_id, "slurm_job_id": "101",
            "slurm_job_account": "def-kleinke_cpu", "slurm_job_partition": "cpubase_bycore_b2",
            "slurm_job_num_nodes": "1", "slurm_ntasks": "32", "slurm_cpus_per_task": "1",
            "slurm_mem_per_cpu": "2000", "slurm_timelimit": "02:00:00",
            "stdenv_module": "StdEnv/2023", "qe_module": "quantumespresso/7.3.1",
            "qe_executable": "pw.x", "qe_mpi_launcher": "srun", "qe_nk": "1",
            "omp_num_threads": "1",
            "run_dir": str(run), "config_sha256": context.config_sha256,
            "fire_lineage_sha256": request["fire_lineage_sha256"],
            "fire_release_sha256": request["fire_release_sha256"],
            "fire_backend_sha256": workflow["fire_recovery.py"],
            "fire_requested_walltime_minutes": "120", "fire_time_limit_source": "native_slurm_timelimit",
            "submit_script_sha256": workflow["submit.py"], "campaign_cli_sha256": workflow["campaign.py"],
            "cluster_env_sha256": workflow["cluster.env"], "stage_script_sha256": workflow["fire_pilot.sbatch"],
            "git_commit": request["git_commit"],
        }
        (wrapper / "context.tsv").write_text("".join(f"{key}\t{value}\n" for key, value in wrapper_context.items()))
        frozen_pseudo_dir = run / "lineage_source/pseudopotentials"
        input_text = fire._input(
            self.config, (run / "fire_seed.in").read_text(), frozen_pseudo_dir, "pilot"
        )
        (wrapper / "fire.in").write_text(input_text)
        (wrapper / "fire.out").write_text(self._pilot_output())
        (wrapper / "fire.err").write_text("")
        command = ["srun", "pw.x", "-nk", "1", "-in", "fire.in"]
        process = {
            "command": command, "cwd": str(wrapper),
            "started_utc": "2026-09-14T00:00:00Z",
            "finished_utc": "2026-09-14T00:01:00Z", "returncode": 0,
            "stdout_sha256": core.sha256_path(wrapper / "fire.out"),
            "stderr_sha256": core.sha256_path(wrapper / "fire.err"),
        }
        (wrapper / "fire.process.json").write_text(json.dumps(process))
        lineage = core.load_json(run / fire.LINEAGE)
        launch = {
            "schema_version": 1, "stage": "fire-pilot", "attempt_id": attempt_id,
            "slurm_job_id": "101", "config_sha256": context.config_sha256,
            "fire_lineage_sha256": request["fire_lineage_sha256"],
            "fire_release_sha256": request["fire_release_sha256"],
            "fire_seed_sha256": core.sha256_path(run / "fire_seed.in"),
            "fire_input_sha256": core.sha256_path(wrapper / "fire.in"),
            "pseudopotentials": {
                species: {
                    "file": str(frozen_pseudo_dir / item["filename"]),
                    "sha256": item["sha256"],
                }
                for species, item in lineage["pseudopotential_archive"].items()
            },
            "command": command, "fresh_scratch": True, "nstep": 8,
            "max_seconds": 6300, "structure_accepted": False,
            "preflight_unlocked": False,
        }
        (wrapper / "launch.json").write_text(json.dumps(launch))
        execution = {**launch, "fire_output_sha256": core.sha256_path(wrapper / "fire.out"), "fire_stderr_sha256": core.sha256_path(wrapper / "fire.err"), "process_record_sha256": core.sha256_path(wrapper / "fire.process.json"), "process": process, "finished_utc": "2026-09-14T00:01:00Z"}
        (wrapper / "execution.json").write_text(json.dumps(execution))
        (wrapper / "exit_code.txt").write_text("0\n")
        (wrapper / "finished_utc.txt").write_text("2026-09-14T00:00:00Z\n")

        collector_id = submitted["collector"]["attempt_id"]
        collector_job = submitted["collector"]["job_id"]
        collector = run / "slurm_attempts/collect" / collector_id
        collector.mkdir(parents=True)
        collector_request = core.load_json(record_dir / "collector_request.json")
        collector_context = {
            "stage": "collect", "attempt_id": collector_id, "slurm_job_id": collector_job,
            "run_dir": str(run), "config_sha256": context.config_sha256,
            "primary_stage": "fire-pilot", "primary_attempt_id": attempt_id, "primary_job_id": "101",
            "primary_request_sha256": collector_request["primary_request_sha256"],
            "primary_result_sha256": collector_request["primary_result_sha256"],
            "primary_stage_script_sha256": collector_request["primary_stage_script_sha256"],
            "fire_lineage_sha256": collector_request["fire_lineage_sha256"],
            "fire_release_sha256": collector_request["fire_release_sha256"],
            "fire_backend_sha256": collector_request["fire_backend_sha256"],
            "fire_requested_walltime_minutes": "120",
            "submit_script_sha256": collector_request["submit_script_sha256"],
            "campaign_cli_sha256": collector_request["campaign_cli_sha256"],
            "cluster_env_sha256": collector_request["cluster_env_sha256"],
            "stage_script_sha256": collector_request["collector_script_sha256"],
        }
        (collector / "context.tsv").write_text("".join(f"{key}\t{value}\n" for key, value in collector_context.items()))
        accounting = collector / "primary_sacct.psv"
        accounting.write_text("JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS|Account|Partition|NNodes|NCPUS|ReqMem|TimelimitRaw\n101|101|COMPLETED|0:0|3600|32||def-kleinke_cpu|cpubase_bycore_b2|1|32|2000Mc|120\n")
        status = collector / "primary_sacct_exit_code.txt"; status.write_text("0\n")
        records, errors, metadata = core._read_sacct_records(accounting, status, core.DIAGNOSTIC_SACCT_FIELDS)
        collected = fire.collect_pilot_evidence(
            config=self.config, config_path=self.config_path, run_dir=run, current_attempt=collector,
            primary_attempt_id=attempt_id, primary_job_id="101",
            expected_primary_request_sha256=collector_request["primary_request_sha256"],
            expected_primary_result_sha256=collector_request["primary_result_sha256"],
            expected_primary_stage_script_sha256=collector_request["primary_stage_script_sha256"],
            accounting_records=records, accounting_errors=errors, accounting_metadata=metadata,
        )
        collection_path = collector / "collection.json"; collection_path.write_text(json.dumps(collected))
        with patch("campaign.symmetry_scan", return_value=[{"symprec_angstrom": 1e-6, "spacegroup_number": 72, "spacegroup_symbol": "Ibam"}]):
            replay = fire.replay_pilot(self.config_path, run, collection_path, expected_collection_sha256=core.sha256_path(collection_path))
        self.assertTrue(replay["pass"])
        self.assertTrue(replay["full_review_eligible"])
        self.assertFalse(replay["structure_accepted"])
        self.assertFalse(replay["preflight_unlocked"])
        self.assertFalse(replay["full_execution_released"])

        # Both submitter crash windows remain replayable negative evidence:
        # after scontrol returns but before its result receipt, and after that
        # receipt but before the final summary.
        summary_path = record_dir / "submission.json"
        release_result_path = record_dir / "primary_release.json"
        original_summary = summary_path.read_text()
        original_release_result = release_result_path.read_text()
        summary_path.unlink()
        summary_window = fire.replay_pilot(
            self.config_path, run, collection_path,
            expected_collection_sha256=core.sha256_path(collection_path),
        )
        self.assertFalse(summary_window["pass"])
        self.assertTrue(summary_window["submission_incomplete_reasons"])
        summary_path.write_text(original_summary)
        release_result_path.unlink()
        summary_path.unlink()
        release_window = fire.replay_pilot(
            self.config_path, run, collection_path,
            expected_collection_sha256=core.sha256_path(collection_path),
        )
        self.assertFalse(release_window["pass"])
        self.assertTrue(release_window["submission_incomplete_reasons"])
        release_result_path.write_text(original_release_result)
        summary_path.write_text(original_summary)

        # Coherently updating every self-reported input hash cannot authorize
        # an extra QE control absent from the exact frozen input rebuild.
        input_path = wrapper / "fire.in"
        launch_path = wrapper / "launch.json"
        execution_path = wrapper / "execution.json"
        original_input = input_path.read_text()
        original_launch = launch_path.read_text()
        original_execution = execution_path.read_text()
        original_collection = collection_path.read_text()
        input_path.write_text(original_input.replace("&SYSTEM\n", "&SYSTEM\n  nosym = .true.,\n", 1))
        launch_t = core.load_json(launch_path)
        execution_t = core.load_json(execution_path)
        launch_t["fire_input_sha256"] = core.sha256_path(input_path)
        execution_t["fire_input_sha256"] = core.sha256_path(input_path)
        launch_path.write_text(json.dumps(launch_t))
        execution_path.write_text(json.dumps(execution_t))
        coherent_input_collection = fire.collect_pilot_evidence(
            config=self.config, config_path=self.config_path, run_dir=run,
            current_attempt=collector, primary_attempt_id=attempt_id,
            primary_job_id="101",
            expected_primary_request_sha256=collector_request["primary_request_sha256"],
            expected_primary_result_sha256=collector_request["primary_result_sha256"],
            expected_primary_stage_script_sha256=collector_request["primary_stage_script_sha256"],
            accounting_records=records, accounting_errors=errors,
            accounting_metadata=metadata,
        )
        collection_path.write_text(json.dumps(coherent_input_collection))
        with self.assertRaisesRegex(core.CampaignError, "exact frozen-seed/policy rebuild"):
            fire.replay_pilot(
                self.config_path, run, collection_path,
                expected_collection_sha256=core.sha256_path(collection_path),
            )
        input_path.write_text(original_input)
        launch_path.write_text(original_launch)
        execution_path.write_text(original_execution)
        collection_path.write_text(original_collection)

        # Existing wrapper provenance corruption is never downgraded to an
        # ordinary negative scientific gate.
        context_path = wrapper / "context.tsv"
        original_context = context_path.read_text()
        context_path.write_text(original_context + "duplicate\tcorrupt\n")
        with self.assertRaises(core.CampaignError):
            fire.replay_pilot(
                self.config_path, run, collection_path,
                expected_collection_sha256=core.sha256_path(collection_path),
            )
        context_path.write_text(original_context)
        execution_path = wrapper / "execution.json"
        original_execution = execution_path.read_text()
        execution_path.write_text(original_execution + "\n")
        with self.assertRaises(core.CampaignError):
            fire.replay_pilot(
                self.config_path, run, collection_path,
                expected_collection_sha256=core.sha256_path(collection_path),
            )
        execution_path.write_text(original_execution)

        # Even a coherent rewrite of collector request/result/attachment,
        # release and summary cannot change afterany into an unreviewed command.
        tamper_paths = {
            name: record_dir / name
            for name in (
                "collector_request.json", "collector_result.json",
                "collector_attachment.json", "primary_release.json",
                "submission.json",
            )
        }
        originals = {name: path.read_text() for name, path in tamper_paths.items()}
        collector_request_t = core.load_json(tamper_paths["collector_request.json"])
        collector_result_t = core.load_json(tamper_paths["collector_result.json"])
        untrusted = list(collector_request_t["command"])
        untrusted[untrusted.index("--dependency=afterany:101")] = "--dependency=afterok:101"
        untrusted[-1] = str(self.root / "untrusted.sbatch")
        collector_request_t["dependency"] = "afterok:101"
        collector_request_t["command"] = untrusted
        collector_result_t["command"] = untrusted
        tamper_paths["collector_request.json"].write_text(json.dumps(collector_request_t))
        tamper_paths["collector_result.json"].write_text(json.dumps(collector_result_t))
        attachment_t = core.load_json(tamper_paths["collector_attachment.json"])
        attachment_t["collector_dependency"] = "afterok:101"
        attachment_t["collector_command"] = untrusted
        attachment_t["collector_request_sha256"] = core.sha256_path(tamper_paths["collector_request.json"])
        attachment_t["collector_result_sha256"] = core.sha256_path(tamper_paths["collector_result.json"])
        tamper_paths["collector_attachment.json"].write_text(json.dumps(attachment_t))
        release_t = core.load_json(tamper_paths["primary_release.json"])
        release_t["collector_attachment_sha256"] = core.sha256_path(tamper_paths["collector_attachment.json"])
        tamper_paths["primary_release.json"].write_text(json.dumps(release_t))
        summary_t = core.load_json(tamper_paths["submission.json"])
        summary_t["collector"]["dependency"] = "afterok:101"
        summary_t["collector"]["command"] = untrusted
        summary_t["collector"]["request_sha256"] = core.sha256_path(tamper_paths["collector_request.json"])
        summary_t["collector"]["result_sha256"] = core.sha256_path(tamper_paths["collector_result.json"])
        summary_t["collector"]["attachment_sha256"] = core.sha256_path(tamper_paths["collector_attachment.json"])
        summary_t["collector"]["primary_release_sha256"] = core.sha256_path(tamper_paths["primary_release.json"])
        tamper_paths["submission.json"].write_text(json.dumps(summary_t))
        with self.assertRaises(core.CampaignError):
            fire.replay_pilot(
                self.config_path, run, collection_path,
                expected_collection_sha256=core.sha256_path(collection_path),
            )
        for name, text in originals.items():
            tamper_paths[name].write_text(text)

        # Terminal scheduler/wrapper failure with intact provenance is a
        # replayable negative gate, not an integrity exception.
        accounting.write_text("JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS|Account|Partition|NNodes|NCPUS|ReqMem|TimelimitRaw\n101|101|FAILED|1:0|60|32||def-kleinke_cpu|cpubase_bycore_b2|1|32|2000Mc|120\n")
        (wrapper / "exit_code.txt").write_text("1\n")
        records, errors, metadata = core._read_sacct_records(
            accounting, status, core.DIAGNOSTIC_SACCT_FIELDS
        )
        failed_collection = fire.collect_pilot_evidence(
            config=self.config, config_path=self.config_path, run_dir=run,
            current_attempt=collector, primary_attempt_id=attempt_id,
            primary_job_id="101",
            expected_primary_request_sha256=collector_request["primary_request_sha256"],
            expected_primary_result_sha256=collector_request["primary_result_sha256"],
            expected_primary_stage_script_sha256=collector_request["primary_stage_script_sha256"],
            accounting_records=records, accounting_errors=errors,
            accounting_metadata=metadata,
        )
        collection_path.write_text(json.dumps(failed_collection))
        failed_replay = fire.replay_pilot(
            self.config_path, run, collection_path,
            expected_collection_sha256=core.sha256_path(collection_path),
        )
        self.assertFalse(failed_replay["pass"])
        self.assertFalse(failed_replay["full_review_eligible"])

        # A node loss after stdout/stderr creation but before the process or
        # execution JSON is written is an honest incomplete attempt.
        (wrapper / "fire.process.json").unlink()
        (wrapper / "execution.json").unlink()
        interrupted_collection = fire.collect_pilot_evidence(
            config=self.config, config_path=self.config_path, run_dir=run,
            current_attempt=collector, primary_attempt_id=attempt_id,
            primary_job_id="101",
            expected_primary_request_sha256=collector_request["primary_request_sha256"],
            expected_primary_result_sha256=collector_request["primary_result_sha256"],
            expected_primary_stage_script_sha256=collector_request["primary_stage_script_sha256"],
            accounting_records=records, accounting_errors=errors,
            accounting_metadata=metadata,
        )
        collection_path.write_text(json.dumps(interrupted_collection))
        interrupted_replay = fire.replay_pilot(
            self.config_path, run, collection_path,
            expected_collection_sha256=core.sha256_path(collection_path),
        )
        self.assertFalse(interrupted_replay["pass"])

        # In the earlier writer-order state where only fire.in exists, a
        # same-nat geometry edit remains provenance corruption, not incomplete.
        (wrapper / "launch.json").unlink()
        (wrapper / "fire.out").unlink()
        (wrapper / "fire.err").unlink()
        fire_lines = (wrapper / "fire.in").read_text().splitlines()
        position_index = next(
            index for index, line in enumerate(fire_lines)
            if line.startswith("ATOMIC_POSITIONS")
        ) + 1
        fields = fire_lines[position_index].split()
        fields[1] = f"{float(fields[1]) + 0.001:.12f}"
        fire_lines[position_index] = " ".join(fields)
        (wrapper / "fire.in").write_text("\n".join(fire_lines) + "\n")
        fire_in_only_collection = fire.collect_pilot_evidence(
            config=self.config, config_path=self.config_path, run_dir=run,
            current_attempt=collector, primary_attempt_id=attempt_id,
            primary_job_id="101",
            expected_primary_request_sha256=collector_request["primary_request_sha256"],
            expected_primary_result_sha256=collector_request["primary_result_sha256"],
            expected_primary_stage_script_sha256=collector_request["primary_stage_script_sha256"],
            accounting_records=records, accounting_errors=errors,
            accounting_metadata=metadata,
        )
        collection_path.write_text(json.dumps(fire_in_only_collection))
        with self.assertRaisesRegex(core.CampaignError, "exact frozen-seed/policy rebuild"):
            fire.replay_pilot(
                self.config_path, run, collection_path,
                expected_collection_sha256=core.sha256_path(collection_path),
            )

        # A genuine startup-before-attempt failure is likewise replayable false.
        shutil.rmtree(wrapper)
        missing_collection = fire.collect_pilot_evidence(
            config=self.config, config_path=self.config_path, run_dir=run,
            current_attempt=collector, primary_attempt_id=attempt_id,
            primary_job_id="101",
            expected_primary_request_sha256=collector_request["primary_request_sha256"],
            expected_primary_result_sha256=collector_request["primary_result_sha256"],
            expected_primary_stage_script_sha256=collector_request["primary_stage_script_sha256"],
            accounting_records=records, accounting_errors=errors,
            accounting_metadata=metadata,
        )
        collection_path.write_text(json.dumps(missing_collection))
        missing_replay = fire.replay_pilot(
            self.config_path, run, collection_path,
            expected_collection_sha256=core.sha256_path(collection_path),
        )
        self.assertFalse(missing_replay["pass"])

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as core
import fire_recovery as fire
import submit


CONFIG = core.REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"


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
        self.assertNotIn("fire-pilot", submit.COLLECTED_STAGES)
        report = submit.plan_report(context, "fire-pilot", task_map=None, max_in_flight=None)
        self.assertFalse(report["execution_released"])
        self.assertIsNone(report["primary_command_template"])

    def test_execute_fire_hard_locks_before_sbatch(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        with patch("submit.run_sbatch") as sbatch:
            with self.assertRaises(submit.SubmissionError):
                submit.execute_submission(context, "fire-pilot", expected_config_sha=context.config_sha256, task_map=None, max_in_flight=None)
        sbatch.assert_not_called()

    def test_internal_execute_bypass_is_hard_locked_before_sbatch(self) -> None:
        run = self.root / "new-fire-run"
        with patch("polish_recovery._audit_final_diagnostic", return_value=self.audit_gate):
            fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        with patch("submit.run_sbatch") as sbatch:
            with self.assertRaises(submit.SubmissionError):
                submit._execute_locked(context, "fire-pilot", task_map=None, max_in_flight=None)
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

    def test_direct_fire_execution_cli_and_runner_are_hard_locked(self) -> None:
        with self.assertRaises(core.CampaignError):
            fire.run_stage(self.config_path, self.root / "absent", "pilot")
        with self.assertRaises(core.CampaignError):
            fire.finalize_stage(self.config_path, self.root / "absent", "pilot")
        for command in ("run", "finalize"):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    fire.main([command, "--config", str(self.config_path), "--run-dir", str(self.root / "absent"), "--stage", "pilot"])

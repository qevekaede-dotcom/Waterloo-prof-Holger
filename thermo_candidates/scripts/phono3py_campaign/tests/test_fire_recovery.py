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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
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
        diagnostic_gate = self.old / "diagnostic/final/gate.json"
        diagnostic_gate.parent.mkdir(parents=True, exist_ok=True)
        diagnostic_gate.write_text(json.dumps({"fixture": "trusted diagnostic gate"}))
        historical = dict(self.config)
        historical.pop(fire.POLICY)
        pseudo_review = {
            species: {"filename": item["filename"], "sha256": item["sha256"]}
            for species, item in pseudo_inventory.items()
        }
        polish_lineage = {
            "schema_version": 1,
            "kind": "reviewed_single_bfgs_polish_after_terminal_one_reset",
            "created_utc": "2026-09-13T00:00:00Z",
            "material": self.config["material"]["formula"],
            "structure_policy_sha256": core.policy_sha256(historical, "structure"),
            "polish_policy_sha256": core.canonical_sha256(historical["reviewed_bfgs_polish"]),
            "config_canonical_sha256": fire._TRUSTED_HISTORICAL_CONFIG_CANONICAL_SHA256,
            "source_run_dir": str(self.root / "one-reset-run"),
            "source_attempt": str(self.root / "one-reset-run/slurm_attempts/relax/attempt"),
            "source_manifest_sha256": "1" * 64,
            "source_output_sha256": "2" * 64,
            "source_files": {"one_reset_attempt/relax.out": "3" * 64},
            "seed_unitcell_sha256": "4" * 64,
            "reference_unitcell_sha256": hashlib.sha256(source).hexdigest(),
            "backend_sha256": "5d72c59aaa2a773005c16ec3160745007890ca62d55bca22266b6bd56b852539",
            "diagnostic_input_sha256": {
                "baseline.in": "5" * 64,
                "higher_ecutrho.in": "6" * 64,
            },
            "pseudopotential_archive": pseudo_inventory,
            "review": {
                "one_reset_job_id": "fixture",
                "one_reset_qe_health": {"healthy": True},
                "maximum_cumulative_shift_angstrom": 0.001,
                "pseudopotentials": pseudo_review,
                "original_recovery": {"fixture": True},
            },
            "automatic_reset": False,
            "maximum_polish_attempts": 1,
            "reuse_qe_scratch": False,
            "acceptance": "diagnostic cannot accept structure; normal BFGS plus independent pristine SCF and ordinary final gate remain mandatory",
        }
        polish_lineage_path = self.old / "polish_lineage.json"
        polish_lineage_path.write_text(json.dumps(polish_lineage))
        polish_lineage_sha = core.sha256_path(polish_lineage_path)
        run_manifest = {
            "schema_version": 2,
            "material": self.config["material"]["formula"],
            "created_utc": "2026-09-13T00:00:01Z",
            "config_path": "/home/yuhansun/repo/thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json",
            "config_sha256": fire._TRUSTED_HISTORICAL_CONFIG_SHA256,
            "structure_policy_sha256": core.policy_sha256(historical, "structure"),
            "preflight_policy_sha256": core.policy_sha256(historical, "preflight"),
            "source_qe_input": "/home/yuhansun/repo/source/Rb2Cu2SnS4.scf.in",
            "source_qe_sha256": core.sha256_path(core.resolve_repo_source(historical, "source.qe_scf_input")),
            "source_relax_output": "/home/yuhansun/repo/source/Rb2Cu2SnS4.relax.out",
            "source_relax_sha256": core.sha256_path(core.resolve_repo_source(historical, "source.original_relax_output")),
            "workflow_files": {
                "thermo_candidates/scripts/phono3py_campaign/campaign.py": "eeabcfed82076d1718b96c1b67b12864693dd5938174face8d8764663797a79d",
                "thermo_candidates/scripts/phono3py_campaign/qe_input.py": "7" * 64,
                "thermo_candidates/scripts/phono3py_campaign/qe_output.py": "8" * 64,
                "thermo_candidates/scripts/phono3py_campaign/polish_recovery.py": "5d72c59aaa2a773005c16ec3160745007890ca62d55bca22266b6bd56b852539",
            },
            "git_commit": fire._TRUSTED_HISTORICAL_COMMIT,
            "relax_polish": {
                "kind": "single_reviewed_bfgs_polish",
                "lineage_receipt": "polish_lineage.json",
                "lineage_sha256": polish_lineage_sha,
                "diagnostic_gate": "diagnostic/final/gate.json",
                "diagnostic_gate_sha256": core.sha256_path(diagnostic_gate),
                "maximum_attempts": 1,
                "automatic_submission_allowed": False,
            },
        }
        run_manifest_path = self.old / "run_manifest.json"
        run_manifest_path.write_text(json.dumps(run_manifest))
        binding = self.config["reviewed_fire_recovery"]["trusted_old_lineage"]
        binding["run_dir"] = str(self.old.resolve())
        binding["reference_sha256"] = hashlib.sha256(source).hexdigest()
        binding["standardization_audit_sha256"] = core.sha256_path(audit)
        binding["failed_relax_output_sha256"] = core.sha256_path(failed)
        binding["failed_relax_context_sha256"] = core.sha256_path(failed_context)
        binding["later_collector_collection_sha256"] = core.sha256_path(collection)
        binding["later_collector_context_sha256"] = core.sha256_path(collector_context)
        binding["polish_lineage_sha256"] = polish_lineage_sha
        binding["run_manifest_sha256"] = core.sha256_path(run_manifest_path)
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

    def _rebind_mutated_polish_release(self, *, update_pointer: bool = True):
        """Test-only rebind so semantic checks run past whole-file anchors."""
        lineage = self.old / "polish_lineage.json"
        manifest_path = self.old / "run_manifest.json"
        manifest = core.load_json(manifest_path)
        lineage_sha = core.sha256_path(lineage)
        if update_pointer:
            manifest["relax_polish"]["lineage_sha256"] = lineage_sha
        manifest_path.write_text(json.dumps(manifest))
        binding = self.config["reviewed_fire_recovery"]["trusted_old_lineage"]
        binding["polish_lineage_sha256"] = lineage_sha
        binding["run_manifest_sha256"] = core.sha256_path(manifest_path)
        self.config_path.write_text(json.dumps(self.config))
        return patch.object(fire, "TRUSTED_OLD_LINEAGE", dict(binding))

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

    def _successful_sbatch_with_collector_note(
        self, primary_job_id: str, collector_job_id: str
    ):
        run = self._successful_sbatch(primary_job_id, collector_job_id)

        def with_exact_nibi_note(command):
            job_id, evidence = run(command)
            if job_id == collector_job_id:
                evidence["stderr"] = fire._NIBI_4G_MEMORY_NOTE
            return job_id, evidence

        return with_exact_nibi_note

    @staticmethod
    def _successful_release(command, *args, **kwargs):
        if list(command[:2]) == ["scontrol", "release"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return REAL_SUBPROCESS_RUN(command, *args, **kwargs)

    def _startup_incident_fixture(self):
        run = self.root / "startup-incident"
        fire.prepare_lineage(self.config_path, run, self.old)
        context = submit.resolve_context(self.config_path, run, "fire-pilot")
        with patch("submit.require_nibi_login"), patch(
            "submit.run_sbatch",
            side_effect=self._successful_sbatch_with_collector_note("101", "102"),
        ), patch("submit.subprocess.run", side_effect=self._successful_release):
            submitted = submit.execute_submission(
                context, "fire-pilot", expected_config_sha=context.config_sha256,
                task_map=None, max_in_flight=None,
            )
        primary_attempt = submitted["attempt_id"]
        collector_attempt = submitted["collector"]["attempt_id"]
        collector = run / "slurm_attempts/collect" / collector_attempt
        collector.mkdir(parents=True)
        record = Path(submitted["record_dir"])
        request = core.load_json(record / "request.json")
        primary_result = core.load_json(record / "primary_result.json")
        lineage_sha = core.sha256_path(run / fire.LINEAGE)
        release_sha = core.sha256_path(run / fire.PILOT_RELEASE)
        collector_context = (
            f"stage\tcollect\nattempt_id\t{collector_attempt}\nslurm_job_id\t102\n"
            "slurm_job_account\tdef-kleinke_cpu\n"
            "slurm_job_partition\tcpubase_bycore_b2\nslurm_job_num_nodes\t1\n"
            "slurm_ntasks\t1\nslurm_cpus_per_task\t\n"
            "slurm_mem_per_cpu\t\nslurm_timelimit\t\n"
            f"run_dir\t{run}\nconfig_sha256\t{context.config_sha256}\n"
            f"primary_stage\tfire-pilot\nprimary_attempt_id\t{primary_attempt}\n"
            "primary_job_id\t101\n"
            f"primary_request_sha256\t{core.sha256_path(record / 'request.json')}\n"
            f"primary_result_sha256\t{core.sha256_path(record / 'primary_result.json')}\n"
            f"fire_lineage_sha256\t{lineage_sha}\nfire_release_sha256\t{release_sha}\n"
            "git_commit\t\n"
        )
        primary_row = (
            "101|FAILED|2:0|4|32||def-kleinke_cpu|cpubase_bycore_b2|"
            "1|32|62.50G|120"
        )
        primary_collector_row = (
            "101|101|FAILED|2:0|4|32||def-kleinke_cpu|cpubase_bycore_b2|"
            "1|32|62.50G|120"
        )
        collector_accounting_header = (
            "JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS|"
            "Account|Partition|NNodes|NCPUS|ReqMem|TimelimitRaw"
        )
        collector_accounting_text = (
            collector_accounting_header
            + "\n"
            + primary_collector_row
            + "\n"
            + "101.batch|101.batch|FAILED|2:0|4|32|4848K|"
            "def-kleinke_cpu||1|32||\n"
            + "101.extern|101.extern|COMPLETED|0:0|4|32||"
            "def-kleinke_cpu||1|32||\n"
        )
        raw = {
            "context.tsv": collector_context.encode(),
            "stdout.log": b'{"command":"collect","error":"git missing","healthy":false}\n',
            "stderr.log": b"",
            "exit_code.txt": b"2\n",
            "finished_utc.txt": b"2026-09-14T00:00:00Z\n",
            "primary_sacct.psv": collector_accounting_text.encode(),
            "primary_sacct-query-01.psv": collector_accounting_text.encode(),
            "primary_sacct.err": b"",
            "primary_sacct-query-01.err": b"",
            "primary_sacct_exit_code.txt": b"0\n",
            "primary_sacct_query_count.txt": b"1\n",
        }
        for name, data in raw.items():
            (collector / name).write_bytes(data)
        scheduler_root = self.root / "thermo_candidates/scripts/phono3py_campaign"
        scheduler_root.mkdir(parents=True)
        primary_scheduler_text = (
            "/var/spool/slurmd/job101/slurm_script: line 32: git: command not found\n"
            "ERROR: FIRE pilot checkout commit differs from the released lineage\n"
        )
        (scheduler_root / "slurm-101.out").write_text(primary_scheduler_text)
        (scheduler_root / "slurm-p3-collect-102.out").write_bytes(raw["stdout.log"])
        incident = copy.deepcopy(fire.TRUSTED_STARTUP_INCIDENT)
        incident.update({
            "run_dir": str(run), "checkout": str(self.root),
            "config_relative": "campaign.json",
            "config_sha256": context.config_sha256,
            "git_commit": request["git_commit"],
            "primary_attempt_id": primary_attempt, "primary_job_id": "101",
            "collector_attempt_id": collector_attempt, "collector_job_id": "102",
            "primary_allocation": primary_row,
            "primary_collector_allocation": primary_collector_row,
            "collector_allocation": (
                "102|FAILED|2:0|5|1||def-kleinke_cpu|cpubase_bycore_b2|1|1|4G|30"
            ),
            "primary_scheduler_text": primary_scheduler_text,
        })
        claim_path = Path(core.load_json(run / fire.LINEAGE)["global_claim_path"])
        hashes = {
            "global_claim": core.sha256_path(claim_path),
            fire.LINEAGE: lineage_sha,
            fire.PILOT_RELEASE: release_sha,
            "fire_seed.in": core.sha256_path(run / "fire_seed.in"),
        }
        for name in (
            "request.json", "primary_result.json", "collector_request.json",
            "collector_result.json", "collector_attachment.json",
            "primary_release.json", "submission.json",
        ):
            hashes[name] = core.sha256_path(record / name)
        for name in raw:
            hashes[f"collector/{name}"] = core.sha256_path(collector / name)
        hashes["primary_scheduler_log"] = core.sha256_path(
            scheduler_root / "slurm-101.out"
        )
        hashes["collector_scheduler_log"] = core.sha256_path(
            scheduler_root / "slurm-p3-collect-102.out"
        )
        incident["hashes"] = hashes
        return run, incident

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

    def test_real_polish_receipt_name_is_mandatory(self) -> None:
        (self.old / "polish_lineage.json").rename(
            self.old / "polish_lineage_receipt.json"
        )
        with self.assertRaisesRegex(core.CampaignError, "polish_lineage.json"):
            fire.prepare_lineage(self.config_path, self.root / "wrong-polish-name", self.old)

    def test_polish_lineage_and_run_manifest_raw_hash_tamper_fail(self) -> None:
        for filename, expected in (
            ("polish_lineage.json", "lineage receipt hash drift"),
            ("run_manifest.json", "run manifest hash drift"),
        ):
            with self.subTest(filename=filename):
                path = self.old / filename
                original = path.read_text()
                path.write_text(original + " \n")
                with self.assertRaisesRegex(core.CampaignError, expected):
                    fire.prepare_lineage(
                        self.config_path, self.root / f"tampered-{filename}", self.old
                    )
                path.write_text(original)

    def test_trusted_polish_json_hash_and_parse_share_one_open_snapshot(self) -> None:
        targets = {
            self.old / "polish_lineage.json",
            self.old / "run_manifest.json",
        }
        open_counts = {path: 0 for path in targets}
        real_open = os.open
        real_sha256_path = core.sha256_path
        real_load_json = core.load_json

        def counted_open(path, flags, *args, **kwargs):
            candidate = Path(path)
            if candidate in open_counts:
                open_counts[candidate] += 1
            return real_open(path, flags, *args, **kwargs)

        def reject_split_hash(path):
            candidate = Path(path)
            if candidate in targets:
                raise AssertionError("trusted JSON must not be reopened for hashing")
            return real_sha256_path(path)

        def reject_split_parse(path):
            candidate = Path(path)
            if candidate in targets:
                raise AssertionError("trusted JSON must not be reopened for parsing")
            return real_load_json(path)

        with patch("fire_recovery.os.open", side_effect=counted_open), patch(
            "fire_recovery.core.sha256_path", side_effect=reject_split_hash
        ), patch("fire_recovery.core.load_json", side_effect=reject_split_parse):
            fire.prepare_lineage(
                self.config_path, self.root / "single-snapshot", self.old
            )
        self.assertEqual(open_counts, {path: 1 for path in targets})

    def test_trusted_polish_json_path_replacement_during_read_fails(self) -> None:
        target = self.old / "polish_lineage.json"
        replacement = self.old / "replacement-polish-lineage.json"
        replacement.write_bytes(target.read_bytes())
        target_identity = (os.lstat(target).st_dev, os.lstat(target).st_ino)
        real_read = os.read
        replaced = False

        def replace_after_open(descriptor, size):
            nonlocal replaced
            descriptor_stat = os.fstat(descriptor)
            if not replaced and (descriptor_stat.st_dev, descriptor_stat.st_ino) == target_identity:
                os.replace(replacement, target)
                replaced = True
            return real_read(descriptor, size)

        with patch("fire_recovery.os.read", side_effect=replace_after_open):
            with self.assertRaisesRegex(core.CampaignError, "changed while reading"):
                fire.prepare_lineage(
                    self.config_path, self.root / "racing-polish-replacement", self.old
                )
        self.assertTrue(replaced)

    def test_startup_incident_authorizes_exactly_one_replacement_without_new_lineage(self) -> None:
        run, incident = self._startup_incident_fixture()
        lineage_before = core.sha256_path(run / fire.LINEAGE)
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch("fire_recovery._query_exact_incident_scheduler_rows", return_value=rows):
            result = fire.create_infrastructure_replacement_authorization(
                self.config_path, run
            )
            verified = fire.verify_infrastructure_replacement_authorization(
                self.config_path, run
            )
            with self.assertRaises(core.CampaignError):
                fire.create_infrastructure_replacement_authorization(
                    self.config_path, run
                )
        self.assertTrue(result["replacement_submission_released"])
        self.assertEqual(verified["authorization_sha256"], result["authorization_sha256"])
        self.assertEqual(core.sha256_path(run / fire.LINEAGE), lineage_before)
        receipt = core.load_json(Path(result["authorization"]))
        self.assertEqual(receipt["original_global_claims_consumed"], 1)
        self.assertEqual(receipt["scientific_attempts_observed"], 0)
        self.assertEqual(receipt["maximum_scientific_attempts"], 1)
        self.assertFalse(receipt["new_lineage_created"])
        for field in (
            "structure_accepted", "preflight_unlocked", "full_execution_released",
            "force_execution_released", "production_execution_released",
        ):
            self.assertFalse(receipt[field])

    def test_startup_incident_uses_exact_empty_collector_resource_context(self) -> None:
        self.assertEqual(
            fire.TRUSTED_STARTUP_INCIDENT["hashes"]["collector/context.tsv"],
            "4c30ae4e5ebace93aac0f9dcbeac44f2c554f7c1e8413d1f7e766eccc6dee957",
        )
        run, incident = self._startup_incident_fixture()
        context_path = (
            run
            / "slurm_attempts/collect"
            / incident["collector_attempt_id"]
            / "context.tsv"
        )
        context = fire._context_snapshot_fields(
            context_path.read_bytes(), "fixture collector context"
        )
        self.assertEqual(context["slurm_cpus_per_task"], "")
        self.assertEqual(context["slurm_mem_per_cpu"], "")
        self.assertEqual(context["slurm_timelimit"], "")
        self.assertEqual(
            incident["hashes"]["collector/context.tsv"],
            core.sha256_path(context_path),
        )

    def test_startup_incident_requires_exact_nibi_collector_memory_note(self) -> None:
        self.assertEqual(
            fire.TRUSTED_STARTUP_INCIDENT["hashes"]["collector_result.json"],
            "79a943bd50be96687dc066dacfa44f3a770aeaedbe48751e25640bb4da48034b",
        )
        run, incident = self._startup_incident_fixture()
        record = run / "submissions/fire-pilot" / incident["primary_attempt_id"]
        collector_result_path = record / "collector_result.json"
        collector_result = core.load_json(collector_result_path)
        self.assertEqual(collector_result["stderr"], fire._NIBI_4G_MEMORY_NOTE)

        # Even a coherently rehashed caller-controlled chain cannot replace the
        # code-owned exact Nibi note with a fabricated blank stderr.
        collector_result["stderr"] = ""
        collector_result_path.write_text(json.dumps(collector_result))
        attachment_path = record / "collector_attachment.json"
        attachment = core.load_json(attachment_path)
        attachment["collector_result_sha256"] = core.sha256_path(
            collector_result_path
        )
        attachment_path.write_text(json.dumps(attachment))
        release_path = record / "primary_release.json"
        release = core.load_json(release_path)
        release["collector_attachment_sha256"] = core.sha256_path(attachment_path)
        release_path.write_text(json.dumps(release))
        summary_path = record / "submission.json"
        summary = core.load_json(summary_path)
        summary["collector"]["result_sha256"] = core.sha256_path(
            collector_result_path
        )
        summary["collector"]["attachment_sha256"] = core.sha256_path(
            attachment_path
        )
        summary["collector"]["primary_release_sha256"] = core.sha256_path(
            release_path
        )
        summary_path.write_text(json.dumps(summary))
        for name, path in (
            ("collector_result.json", collector_result_path),
            ("collector_attachment.json", attachment_path),
            ("primary_release.json", release_path),
            ("submission.json", summary_path),
        ):
            incident["hashes"][name] = core.sha256_path(path)
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            return_value=rows,
        ):
            with self.assertRaisesRegex(core.CampaignError, "identity drift"):
                fire.create_infrastructure_replacement_authorization(
                    self.config_path, run
                )

    def test_startup_incident_keeps_live_and_archived_sacct_rows_distinct(self) -> None:
        incident = fire.TRUSTED_STARTUP_INCIDENT
        self.assertEqual(
            incident["primary_allocation"],
            "21864180|FAILED|2:0|4|32||def-kleinke_cpu|"
            "cpubase_bycore_b2|1|32|62.50G|120",
        )
        self.assertEqual(
            incident["primary_collector_allocation"],
            "21864180|21864180|FAILED|2:0|4|32||def-kleinke_cpu|"
            "cpubase_bycore_b2|1|32|62.50G|120",
        )
        self.assertNotEqual(
            incident["primary_allocation"],
            incident["primary_collector_allocation"],
        )

    def test_startup_incident_any_raw_hash_or_scheduler_row_drift_fails(self) -> None:
        run, incident = self._startup_incident_fixture()
        record = run / "submissions/fire-pilot" / incident["primary_attempt_id"]
        target = record / "collector_request.json"
        original = target.read_text()
        target.write_text(original + " ")
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch("fire_recovery._query_exact_incident_scheduler_rows") as query:
            with self.assertRaisesRegex(core.CampaignError, "hash drift"):
                fire.create_infrastructure_replacement_authorization(
                    self.config_path, run
                )
        query.assert_not_called()
        target.write_text(original)
        bad_rows = {
            "101": incident["primary_allocation"].replace("FAILED", "COMPLETED"),
            "102": incident["collector_allocation"],
        }
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            side_effect=core.CampaignError(str(bad_rows)),
        ):
            with self.assertRaises(core.CampaignError):
                fire.create_infrastructure_replacement_authorization(
                    self.config_path, run
                )

    def test_startup_incident_rejects_any_primary_attempt_or_arbitrary_authority(self) -> None:
        run, incident = self._startup_incident_fixture()
        primary = run / "slurm_attempts/fire-pilot" / incident["primary_attempt_id"]
        primary.mkdir()
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ):
            with self.assertRaisesRegex(core.CampaignError, "scientific primary attempt"):
                fire.create_infrastructure_replacement_authorization(
                    self.config_path, run
                )
        primary.rmdir()
        config, _ = core.validate_config(self.config_path)
        authority = fire._replacement_authorization_path(config, run)
        authority.write_text('{"released": true}\n')
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident):
            with self.assertRaises(core.CampaignError):
                fire.verify_infrastructure_replacement_authorization(
                    self.config_path, run
                )

    def test_replacement_authorization_creation_is_globally_exclusive_under_race(self) -> None:
        run, incident = self._startup_incident_fixture()
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }

        def create_once():
            try:
                fire.create_infrastructure_replacement_authorization(
                    self.config_path, run
                )
            except core.CampaignError:
                return "rejected"
            return "created"

        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch("fire_recovery._query_exact_incident_scheduler_rows", return_value=rows):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: create_once(), range(2)))
        self.assertEqual(sorted(outcomes), ["created", "rejected"])

    def test_replacement_plan_and_execute_bind_authority_through_afterany_chain(self) -> None:
        run, incident = self._startup_incident_fixture()
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            return_value=rows,
        ):
            authorization = fire.create_infrastructure_replacement_authorization(
                self.config_path, run
            )
            context = submit.resolve_context(
                self.config_path,
                run,
                "fire-pilot",
                infrastructure_replacement=True,
            )
            plan = submit.plan_report(
                context,
                "fire-pilot",
                task_map=None,
                max_in_flight=None,
                infrastructure_replacement=True,
            )
            self.assertEqual(plan["mode"], "plan-replacement")
            self.assertEqual(
                plan["fire_replacement_sha256"],
                authorization["authorization_sha256"],
            )
            with patch(
                "submit.run_sbatch",
                side_effect=self._successful_sbatch_with_collector_note(
                    "201", "202"
                ),
            ), patch(
                "submit.subprocess.run", side_effect=self._successful_release
            ):
                submitted = submit.execute_infrastructure_replacement(
                    context,
                    expected_config_sha=context.config_sha256,
                    expected_replacement_authorization_sha=authorization[
                        "authorization_sha256"
                    ],
                )

            record = Path(submitted["record_dir"])
            for name in (
                "request.json",
                "primary_result.json",
                "collector_request.json",
                "collector_result.json",
                "collector_attachment.json",
                "primary_release.json",
                "submission.json",
            ):
                self.assertEqual(
                    core.load_json(record / name)["fire_replacement_sha256"],
                    authorization["authorization_sha256"],
                )
            request = core.load_json(record / "request.json")
            collector_request = core.load_json(record / "collector_request.json")
            self.assertIn("--hold", request["command"])
            self.assertIn("--dependency=afterany:201", collector_request["command"])
            self.assertEqual(collector_request["dependency"], "afterany:201")
            self.assertFalse(submitted.get("structure_accepted", False))
            self.assertFalse(submitted.get("preflight_unlocked", False))

            collector_attempt_id = submitted["collector"]["attempt_id"]
            collector = run / "slurm_attempts/collect" / collector_attempt_id
            collector.mkdir()
            collector_context = {
                "stage": "collect",
                "attempt_id": collector_attempt_id,
                "slurm_job_id": "202",
                "run_dir": str(run),
                "config_sha256": context.config_sha256,
                "primary_stage": "fire-pilot",
                "primary_attempt_id": submitted["attempt_id"],
                "primary_job_id": "201",
                "primary_request_sha256": collector_request[
                    "primary_request_sha256"
                ],
                "primary_result_sha256": collector_request[
                    "primary_result_sha256"
                ],
                "primary_stage_script_sha256": collector_request[
                    "primary_stage_script_sha256"
                ],
                "fire_lineage_sha256": collector_request[
                    "fire_lineage_sha256"
                ],
                "fire_release_sha256": collector_request[
                    "fire_release_sha256"
                ],
                "fire_backend_sha256": collector_request[
                    "fire_backend_sha256"
                ],
                "fire_requested_walltime_minutes": "120",
                "fire_replacement_sha256": authorization[
                    "authorization_sha256"
                ],
                "submit_script_sha256": collector_request[
                    "submit_script_sha256"
                ],
                "campaign_cli_sha256": collector_request[
                    "campaign_cli_sha256"
                ],
                "cluster_env_sha256": collector_request[
                    "cluster_env_sha256"
                ],
                "stage_script_sha256": collector_request[
                    "collector_script_sha256"
                ],
            }
            (collector / "context.tsv").write_text(
                "".join(f"{key}\t{value}\n" for key, value in collector_context.items())
            )
            accounting = collector / "primary_sacct.psv"
            accounting.write_text(
                "JobID|JobIDRaw|State|ExitCode|ElapsedRaw|AllocCPUS|MaxRSS|"
                "Account|Partition|NNodes|NCPUS|ReqMem|TimelimitRaw\n"
                "201|201|FAILED|2:0|4|32||def-kleinke_cpu|"
                "cpubase_bycore_b2|1|32|2000Mc|120\n"
            )
            accounting_status = collector / "primary_sacct_exit_code.txt"
            accounting_status.write_text("0\n")
            records, errors, metadata = core._read_sacct_records(
                accounting, accounting_status, core.DIAGNOSTIC_SACCT_FIELDS
            )
            collection = fire.collect_pilot_evidence(
                config=self.config,
                config_path=self.config_path,
                run_dir=run,
                current_attempt=collector,
                primary_attempt_id=submitted["attempt_id"],
                primary_job_id="201",
                expected_primary_request_sha256=collector_request[
                    "primary_request_sha256"
                ],
                expected_primary_result_sha256=collector_request[
                    "primary_result_sha256"
                ],
                expected_primary_stage_script_sha256=collector_request[
                    "primary_stage_script_sha256"
                ],
                accounting_records=records,
                accounting_errors=errors,
                accounting_metadata=metadata,
            )
            self.assertEqual(
                collection["fire_replacement_sha256"],
                authorization["authorization_sha256"],
            )
            collection_path = collector / "collection.json"
            collection_path.write_text(json.dumps(collection))
            replay = fire.replay_pilot(
                self.config_path,
                run,
                collection_path,
                expected_collection_sha256=core.sha256_path(collection_path),
            )
            self.assertFalse(replay["pass"])
            self.assertEqual(
                replay["fire_replacement_sha256"],
                authorization["authorization_sha256"],
            )
            self.assertFalse(replay["structure_accepted"])
            self.assertFalse(replay["preflight_unlocked"])
            self.assertFalse(replay["full_execution_released"])

            # A future Nibi client may either emit the known 4G normalization
            # note or remain silent.  Both are benign; every other stderr byte
            # must still fail before QE can start.
            collector_result_path = record / "collector_result.json"
            attachment_path = record / "collector_attachment.json"
            release_path = record / "primary_release.json"

            def rewrite_collector_stderr(value: object) -> None:
                collector_result = core.load_json(collector_result_path)
                collector_result["stderr"] = value
                collector_result_path.write_text(json.dumps(collector_result))
                attachment = core.load_json(attachment_path)
                attachment["collector_result_sha256"] = core.sha256_path(
                    collector_result_path
                )
                attachment_path.write_text(json.dumps(attachment))
                release = core.load_json(release_path)
                release["collector_attachment_sha256"] = core.sha256_path(
                    attachment_path
                )
                release_path.write_text(json.dumps(release))

            rewrite_collector_stderr("")
            fire.verify_fire_collector_attachment(
                self.config_path,
                run,
                submitted["attempt_id"],
                "201",
                replacement_authorization_sha256=authorization[
                    "authorization_sha256"
                ],
                allow_primary_attempt=True,
                replacement_collector_attempt_id=collector_attempt_id,
            )
            for rejected_stderr in (
                "unexpected scheduler warning\n",
                ["unexpected non-string stderr"],
            ):
                rewrite_collector_stderr(rejected_stderr)
                with self.assertRaisesRegex(
                    core.CampaignError, "acceptance evidence"
                ):
                    fire.verify_fire_collector_attachment(
                        self.config_path,
                        run,
                        submitted["attempt_id"],
                        "201",
                        replacement_authorization_sha256=authorization[
                            "authorization_sha256"
                        ],
                        allow_primary_attempt=True,
                        replacement_collector_attempt_id=collector_attempt_id,
                    )

            with patch("submit.run_sbatch") as second_sbatch:
                with self.assertRaises((core.CampaignError, submit.SubmissionError)):
                    submit.execute_infrastructure_replacement(
                        context,
                        expected_config_sha=context.config_sha256,
                        expected_replacement_authorization_sha=authorization[
                            "authorization_sha256"
                        ],
                    )
            second_sbatch.assert_not_called()

    def test_replacement_rejected_primary_consumes_slot_before_sbatch_retry(self) -> None:
        run, incident = self._startup_incident_fixture()
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        rejection = submit.RejectedSubmissionError(
            "reviewed rejection",
            {
                "command": ["sbatch"],
                "returncode": 1,
                "stdout": "",
                "stderr": "rejected",
                "finished_utc": "2026-09-14T00:00:00Z",
            },
        )
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            return_value=rows,
        ):
            authorization = fire.create_infrastructure_replacement_authorization(
                self.config_path, run
            )
            context = submit.resolve_context(
                self.config_path,
                run,
                "fire-pilot",
                infrastructure_replacement=True,
            )
            with patch("submit.run_sbatch", side_effect=rejection) as sbatch:
                with self.assertRaises(submit.RejectedSubmissionError):
                    submit.execute_infrastructure_replacement(
                        context,
                        expected_config_sha=context.config_sha256,
                        expected_replacement_authorization_sha=authorization[
                            "authorization_sha256"
                        ],
                    )
            self.assertEqual(sbatch.call_count, 1)
            replacement_records = [
                item
                for item in (run / "submissions/fire-pilot").iterdir()
                if item.is_dir()
                and item.name != incident["primary_attempt_id"]
            ]
            self.assertEqual(len(replacement_records), 1)
            self.assertTrue((replacement_records[0] / "primary_rejected.json").is_file())
            with patch("submit.run_sbatch") as retry:
                with self.assertRaises((core.CampaignError, submit.SubmissionError)):
                    submit.execute_infrastructure_replacement(
                        context,
                        expected_config_sha=context.config_sha256,
                        expected_replacement_authorization_sha=authorization[
                            "authorization_sha256"
                        ],
                    )
            retry.assert_not_called()

    def test_replacement_concurrency_allows_only_one_primary_submission_chain(self) -> None:
        run, incident = self._startup_incident_fixture()
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        entered = Event()
        release_first = Event()
        call_lock = Lock()
        calls: list[list[str]] = []

        def controlled_sbatch(command):
            with call_lock:
                calls.append(list(command))
                call_number = len(calls)
            if call_number == 1:
                entered.set()
                self.assertTrue(release_first.wait(5))
                job_id = "301"
            else:
                job_id = "302"
            return job_id, {
                "command": list(command),
                "returncode": 0,
                "stdout": job_id + ";nibi\n",
                "stderr": "",
                "finished_utc": "2026-09-14T00:00:00Z",
            }

        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            return_value=rows,
        ):
            authorization = fire.create_infrastructure_replacement_authorization(
                self.config_path, run
            )
            context = submit.resolve_context(
                self.config_path,
                run,
                "fire-pilot",
                infrastructure_replacement=True,
            )

            def execute_once():
                return submit.execute_infrastructure_replacement(
                    context,
                    expected_config_sha=context.config_sha256,
                    expected_replacement_authorization_sha=authorization[
                        "authorization_sha256"
                    ],
                )

            with patch("submit.run_sbatch", side_effect=controlled_sbatch), patch(
                "submit.subprocess.run", side_effect=self._successful_release
            ), ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(execute_once)
                self.assertTrue(entered.wait(5))
                second = pool.submit(execute_once)
                with self.assertRaises(submit.SubmissionError):
                    second.result(timeout=5)
                release_first.set()
                result = first.result(timeout=5)
        self.assertEqual(result["primary_job_id"], "301")
        self.assertEqual(len(calls), 2)
        self.assertEqual(sum("--hold" in command for command in calls), 1)

    def test_replacement_crash_after_consuming_record_prevents_retry(self) -> None:
        run, incident = self._startup_incident_fixture()
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            return_value=rows,
        ):
            authorization = fire.create_infrastructure_replacement_authorization(
                self.config_path, run
            )
            context = submit.resolve_context(
                self.config_path,
                run,
                "fire-pilot",
                infrastructure_replacement=True,
            )
            with patch(
                "submit.run_sbatch", side_effect=RuntimeError("simulated crash")
            ) as sbatch:
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    submit.execute_infrastructure_replacement(
                        context,
                        expected_config_sha=context.config_sha256,
                        expected_replacement_authorization_sha=authorization[
                            "authorization_sha256"
                        ],
                    )
            self.assertEqual(sbatch.call_count, 1)
            with patch("submit.run_sbatch") as retry:
                with self.assertRaises((core.CampaignError, submit.SubmissionError)):
                    submit.execute_infrastructure_replacement(
                        context,
                        expected_config_sha=context.config_sha256,
                        expected_replacement_authorization_sha=authorization[
                            "authorization_sha256"
                        ],
                    )
            retry.assert_not_called()

    def test_internal_replacement_entry_cannot_bypass_login_or_authority_hash(self) -> None:
        run, incident = self._startup_incident_fixture()
        rows = {
            "101": incident["primary_allocation"],
            "102": incident["collector_allocation"],
        }
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch(
            "fire_recovery._query_exact_incident_scheduler_rows",
            return_value=rows,
        ):
            authorization = fire.create_infrastructure_replacement_authorization(
                self.config_path, run
            )
            context = submit.resolve_context(
                self.config_path,
                run,
                "fire-pilot",
                infrastructure_replacement=True,
            )
        with patch(
            "submit.require_nibi_login",
            side_effect=submit.SubmissionError("not Nibi"),
        ), patch("submit.run_sbatch") as sbatch:
            with self.assertRaisesRegex(submit.SubmissionError, "not Nibi"):
                submit._execute_locked(
                    context,
                    "fire-pilot",
                    expected_config_sha=context.config_sha256,
                    task_map=None,
                    max_in_flight=None,
                    expected_replacement_authorization_sha=authorization[
                        "authorization_sha256"
                    ],
                    infrastructure_replacement=True,
                )
        sbatch.assert_not_called()
        with patch.object(fire, "TRUSTED_STARTUP_INCIDENT", incident), patch(
            "submit.require_nibi_login"
        ), patch("submit.run_sbatch") as sbatch:
            with self.assertRaises(submit.SubmissionError):
                submit._execute_locked(
                    context,
                    "fire-pilot",
                    expected_config_sha=context.config_sha256,
                    task_map=None,
                    max_in_flight=None,
                    expected_replacement_authorization_sha="0" * 64,
                    infrastructure_replacement=True,
                )
        sbatch.assert_not_called()

    def test_manifest_wrong_lineage_filename_fails_after_coherent_rehash(self) -> None:
        manifest_path = self.old / "run_manifest.json"
        manifest = core.load_json(manifest_path)
        manifest["relax_polish"]["lineage_receipt"] = "polish_lineage_receipt.json"
        manifest_path.write_text(json.dumps(manifest))
        with self._rebind_mutated_polish_release():
            with self.assertRaisesRegex(core.CampaignError, "manifest/lineage relation drift"):
                fire.prepare_lineage(
                    self.config_path, self.root / "wrong-pointer-name", self.old
                )

    def test_manifest_wrong_lineage_hash_fails_after_manifest_rehash(self) -> None:
        manifest_path = self.old / "run_manifest.json"
        manifest = core.load_json(manifest_path)
        manifest["relax_polish"]["lineage_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        with self._rebind_mutated_polish_release(update_pointer=False):
            with self.assertRaisesRegex(core.CampaignError, "manifest/lineage relation drift"):
                fire.prepare_lineage(
                    self.config_path, self.root / "wrong-pointer-hash", self.old
                )

    def test_polish_schema_material_and_commit_are_semantically_validated(self) -> None:
        cases = (
            ("lineage-extra", "lineage", "extra", True),
            ("lineage-material", "lineage", "material", "SrCu2SnS4"),
            ("manifest-commit", "manifest", "git_commit", "0" * 40),
        )
        for label, document, field, value in cases:
            with self.subTest(label=label):
                lineage_path = self.old / "polish_lineage.json"
                manifest_path = self.old / "run_manifest.json"
                original_lineage = lineage_path.read_text()
                original_manifest = manifest_path.read_text()
                path = lineage_path if document == "lineage" else manifest_path
                payload = core.load_json(path)
                payload[field] = value
                path.write_text(json.dumps(payload))
                with self._rebind_mutated_polish_release():
                    with self.assertRaises(core.CampaignError):
                        fire.prepare_lineage(
                            self.config_path, self.root / f"bad-{label}", self.old
                        )
                lineage_path.write_text(original_lineage)
                manifest_path.write_text(original_manifest)
                binding = self.config["reviewed_fire_recovery"]["trusted_old_lineage"]
                binding["polish_lineage_sha256"] = core.sha256_path(lineage_path)
                binding["run_manifest_sha256"] = core.sha256_path(manifest_path)
                self.config_path.write_text(json.dumps(self.config))

    def test_old_polish_pseudopotential_bytes_tamper_fails(self) -> None:
        filename = next(iter(self.config["pseudopotentials"]["files"].values()))
        pseudo = self.old / "lineage_source/pseudopotentials" / filename
        pseudo.write_bytes(b"changed old archive bytes under the same name\n")
        with self.assertRaisesRegex(core.CampaignError, "pseudopotential bytes drifted"):
            fire.prepare_lineage(self.config_path, self.root / "old-pseudo-drift", self.old)

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

    def test_slurm_git_commit_uses_only_exact_pinned_nibi_binary(self) -> None:
        with patch.dict(os.environ, {"SLURM_JOB_ID": "123", "P3_GIT": "/tmp/git"}):
            with patch("fire_recovery.subprocess.run") as run:
                with self.assertRaisesRegex(core.CampaignError, "exact pinned Nibi git"):
                    fire._git_commit()
            run.assert_not_called()
        pinned = "/cvmfs/soft.computecanada.ca/gentoo/2023/x86-64-v3/usr/bin/git"
        version = subprocess.CompletedProcess(
            [pinned], 0, stdout="git version 2.41.0\n", stderr=""
        )
        completed = subprocess.CompletedProcess(
            [pinned], 0, stdout="a" * 40 + "\n", stderr=""
        )
        pinned_env = {
            "SLURM_JOB_ID": "123", "P3_GIT": pinned,
            "P3_GIT_SHA256": fire._PINNED_NIBI_GIT_SHA256,
            "P3_GIT_VERSION": fire._PINNED_NIBI_GIT_VERSION,
        }
        with patch.dict(os.environ, pinned_env), patch(
            "fire_recovery.os.lstat", return_value=os.stat(__file__)
        ), patch("fire_recovery.os.access", return_value=True), patch(
            "fire_recovery._load_strict_bytes_snapshot",
            return_value=(b"git", fire._PINNED_NIBI_GIT_SHA256),
        ), patch(
            "fire_recovery.subprocess.run", side_effect=(version, completed)
        ) as run:
            self.assertEqual(fire._git_commit(), "a" * 40)
        self.assertEqual(run.call_args_list[-1].args[0][0], pinned)

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

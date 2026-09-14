"""Read-only Sr exact-six release and numerical-gate tests."""
import copy
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import campaign as core
import force_backend as fb
import initial_pilot as ip
from postprocess_backend import qe_settings


REPO = Path(__file__).resolve().parents[4]
CONFIG = REPO / "thermo_candidates" / "SrZrS3" / "phono3py" / "campaign.json"
EVIDENCE = (REPO / "thermo_candidates" / "SrZrS3" / "phono3py" / "evidence"
            / "3p5541348625A_count_only")


class InitialPilotTests(unittest.TestCase):
    def setUp(self):
        self.config, _ = core.validate_config(CONFIG)
        self.contract = ip._contract(self.config)

    def test_real_archive_replays_cutoff_edge_mapping(self):
        paths = ip._evidence_paths(self.config, self.contract)
        ip._validate_yaml_mapping(paths["yaml"], paths["accepted_unitcell"],
                                  self.contract)
        probe = ip.expected_probe_spec(self.contract)
        self.assertEqual(probe["singles"][0]["atom"], 33)
        self.assertEqual(probe["mixed"][0]["second"]["atom"], 35)
        self.assertEqual(probe["mixed"][0]["second"]["direction_cartesian"],
                         [-x for x in self.contract["unit_vector_33_to_35"]])

    def test_release_is_hash_bound_and_denies_broader_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = (Path(temporary) / "run").resolve()
            final = run / "relax" / "final"
            final.mkdir(parents=True)
            shutil.copyfile(EVIDENCE / "relax/final/unitcell.in", final / "unitcell.in")
            (final / "gate.json").write_text(json.dumps({
                "pass": True,
                "final_unitcell_sha256": core.sha256_path(final / "unitcell.in"),
            }))
            (final / "provenance.json").write_text("{}")
            (run / core.RUN_MANIFEST).write_text(json.dumps({
                "schema_version": 2,
                "material": "SrZrS3",
                "preflight_policy_sha256": core.policy_sha256(self.config, "preflight"),
                "accepted_structure_import": {"receipt": "accepted_structure_import.json"},
            }))
            verified = {"healthy": True, "kind": "imported_accepted_structure",
                "run_dir": str(run.resolve()), "preflight_policy_sha256":
                core.policy_sha256(self.config, "preflight"),
                "accepted_unitcell_sha256": core.sha256_path(final / "unitcell.in"),
                "receipt_sha256": "a" * 64}
            with patch("accepted_structure_import.verify_imported_acceptance",
                       return_value=verified):
                result = ip.prepare_initial_pilot_release(CONFIG, run,
                                                          run / "pilot_release.json")
                release = ip.replay_initial_pilot_release(result["release"],
                    config_path=CONFIG, run_dir=run,
                    expected_release_sha256=result["release_sha256"])
            self.assertEqual(release["scope"]["task_displacement_ids"],
                             [0, 0, 1, 3, 1, 3])
            self.assertFalse(release["scope"]["validation_authorized"])
            self.assertFalse(release["scope"]["production_authorized"])
            with self.assertRaisesRegex(ip.InitialPilotError, "hash mismatch"):
                ip.replay_initial_pilot_release(result["release"],
                    config_path=CONFIG, run_dir=run,
                    expected_release_sha256="0" * 64)

            historical = Path(temporary) / "historical-workflow"
            historical.mkdir()
            for name in ip.WORKFLOW_FILES:
                destination = historical / name
                shutil.copy2(Path(ip.__file__).resolve().parent / name, destination)
            with patch("accepted_structure_import.verify_imported_acceptance",
                       return_value=verified):
                old_stable = ip._stable_release(
                    CONFIG, run, workflow_dir=historical
                )
            old_release = run / "historical_release.json"
            old_release.write_text(json.dumps({
                **old_stable, "created_utc": "2026-09-14T00:00:00Z",
            }))
            old_sha = core.sha256_path(old_release)
            with patch("accepted_structure_import.verify_imported_acceptance",
                       return_value=verified):
                with self.assertRaisesRegex(ip.InitialPilotError,
                                            "workflow_sha256"):
                    ip.replay_initial_pilot_release(
                        old_release, config_path=CONFIG, run_dir=run,
                        expected_release_sha256=old_sha,
                    )
                replayed_old = ip.replay_initial_pilot_release(
                    old_release, config_path=CONFIG, run_dir=run,
                    expected_release_sha256=old_sha,
                    historical_workflow_dir=historical,
                )
            self.assertEqual(replayed_old["workflow_sha256"],
                             old_stable["workflow_sha256"])
            copied = Path(temporary) / "copied-run"
            shutil.copytree(run, copied)
            copied_release = copied / "pilot_release.json"
            copied_verified = {**verified, "run_dir": str(copied.resolve())}
            with patch("accepted_structure_import.verify_imported_acceptance",
                       return_value=copied_verified), self.assertRaisesRegex(
                       ip.InitialPilotError, "replay mismatch"):
                ip.replay_initial_pilot_release(copied_release,
                    config_path=CONFIG, run_dir=copied,
                    expected_release_sha256=core.sha256_path(copied_release))

            external_release = Path(temporary) / "external-release.json"
            shutil.copyfile(result["release"], external_release)
            linked_release = run / "linked-release.json"
            linked_release.symlink_to(external_release)
            with self.assertRaisesRegex(ip.InitialPilotError, "symlink"):
                ip.replay_initial_pilot_release(linked_release,
                    config_path=CONFIG, run_dir=run,
                    expected_release_sha256=core.sha256_path(external_release))

    def test_skeletal_run_lineage_cannot_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run"
            final = run / "relax/final"
            final.mkdir(parents=True)
            shutil.copyfile(EVIDENCE / "relax/final/unitcell.in", final / "unitcell.in")
            (final / "gate.json").write_text(json.dumps({"pass": True,
                "final_unitcell_sha256": core.sha256_path(final / "unitcell.in")}))
            (final / "provenance.json").write_text("{}")
            (run / core.RUN_MANIFEST).write_text(json.dumps({"schema_version": 2,
                "material": "SrZrS3", "preflight_policy_sha256":
                core.policy_sha256(self.config, "preflight")}))
            with self.assertRaisesRegex(ip.InitialPilotError,
                                        "fully replayable accepted-structure import"):
                ip.prepare_initial_pilot_release(CONFIG, run, run / "pilot_release.json")

    def test_archived_manifest_and_yaml_hash_tamper_fail_closed(self):
        paths = ip._evidence_paths(self.config, self.contract)
        original_hash = core.sha256_path
        for target in (paths["manifest"], paths["yaml"]):
            with self.subTest(target=target.name), patch(
                    "campaign.sha256_path",
                    side_effect=lambda path, target=target: (
                        "0" * 64 if Path(path).resolve() == target.resolve()
                        else original_hash(Path(path)))):
                with self.assertRaisesRegex(ip.InitialPilotError, "hash mismatch"):
                    ip._evidence_paths(self.config, self.contract)

    def test_all_787_candidate_checksums_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            candidate.mkdir()
            rows = []
            for index in range(1, 788):
                name = f"supercell-{index:05d}.in"
                path = candidate / name
                path.write_text(f"input {index}\n")
                rows.append(f"{core.sha256_path(path)}  {name}\n")
            for name in ("phono3py_disp.yaml", "supercell.in", "unitcell.in"):
                (candidate / name).write_text(name + "\n")
            checksums = root / "generated_inputs.SHA256SUMS"
            checksums.write_text("".join(rows))
            release = {"source": {
                "generated_input_checksums_path": str(checksums),
                "generated_input_checksums_sha256": core.sha256_path(checksums),
                "yaml_sha256": core.sha256_path(candidate / "phono3py_disp.yaml"),
                "candidate_supercell_sha256": core.sha256_path(candidate / "supercell.in"),
                "accepted_unitcell_sha256": core.sha256_path(candidate / "unitcell.in"),
            }}
            ip.validate_released_candidate_files(release, candidate)
            (candidate / "supercell-00787.in").write_text("tampered\n")
            with self.assertRaisesRegex(ip.InitialPilotError, "hash mismatch"):
                ip.validate_released_candidate_files(release, candidate)

    @staticmethod
    def forces(value):
        return [[[value, value, value] for _ in range(40)]][0]

    def test_exact_numerical_contract_and_equality_pass(self):
        # Duplicate differences are exactly 1e-6.  Pair means give incremental
        # signals far above 10*sqrt(2)*1e-6.
        forces = [self.forces(0), self.forces(1e-6),
                  self.forces(2e-5), self.forces(4e-5),
                  self.forces(2.1e-5), self.forces(4.1e-5)]
        result = ip.evaluate_initial_forces(forces, self.contract["acceptance"])
        self.assertEqual(result["status"], "accepted_initial_timing_noise")
        self.assertTrue(result["pass"])
        self.assertAlmostEqual(result["duplicate_rms_Ry_per_bohr"]["pristine"], 1e-6)

        # Equality with the 10*eta threshold passes by contract.
        eps = self.contract["acceptance"]["epsilon_Ry_per_bohr"]
        noise = 1e-6
        signal = 10 * math.hypot(noise, noise)
        equality = [self.forces(0), self.forces(noise),
                    self.forces(signal), self.forces(2*signal),
                    self.forces(signal+noise), self.forces(2*signal+noise)]
        result = ip.evaluate_initial_forces(equality, self.contract["acceptance"])
        self.assertTrue(result["incremental_signal_pass"]["single_minus_pristine"])
        self.assertTrue(result["incremental_signal_pass"]["double_minus_single"])
        self.assertGreater(result["incremental_signal_rms_Ry_per_bohr"]["single_minus_pristine"], eps)

    def test_noise_failure_and_below_resolution_are_distinct(self):
        noisy = [self.forces(0), self.forces(6e-6),
                 self.forces(2e-5), self.forces(4e-5),
                 self.forces(2e-5), self.forces(4e-5)]
        self.assertEqual(ip.evaluate_initial_forces(
            noisy, self.contract["acceptance"])["status"], "noise_gate_failed")
        flat = [self.forces(0) for _ in range(6)]
        self.assertEqual(ip.evaluate_initial_forces(
            flat, self.contract["acceptance"])["status"], "below_resolution")

    def test_release_use_rejects_resource_and_force_scope_drift(self):
        release = {"scope": {"mode": "pilot", "phase": "initial", "task_count": 6,
                    "task_displacement_ids": [0, 0, 1, 3, 1, 3],
                    "validation_authorized": False, "production_authorized": False},
                   "contract": self.contract,
                   "force_pilot_spec": ip.expected_force_spec(self.contract),
                   "probe_spec": ip.expected_probe_spec(self.contract)}
        resource = {"phase": "initial", "mpi_ranks": 32,
                    "walltime_hours": 2, "max_concurrency": 2}
        ip.validate_release_use(release, force_spec=release["force_pilot_spec"],
                                resource_request=resource)
        with self.assertRaisesRegex(ip.InitialPilotError, "resource request"):
            ip.validate_release_use(release, force_spec=release["force_pilot_spec"],
                                    resource_request={**resource, "max_concurrency": 3})
        for phase in ("validation", "production"):
            with self.subTest(phase=phase), self.assertRaisesRegex(
                    ip.InitialPilotError, "resource request"):
                ip.validate_release_use(release, force_spec=release["force_pilot_spec"],
                                        resource_request={**resource, "phase": phase})
        bad = copy.deepcopy(release["force_pilot_spec"])
        bad["displacement_ids"] = [1, 3, 2]
        with self.assertRaisesRegex(ip.InitialPilotError, "force pilot specification"):
            ip.validate_release_use(release, force_spec=bad,
                                    resource_request=resource)

    def test_consumption_identity_is_single_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run"
            run.mkdir()
            release_path = run / "pilot_release.json"
            release_path.write_text("{}")
            release = {"consumption_identity": "a" * 64}
            claim = ip.claim_release_consumption(
                run, release_path, core.sha256_path(release_path), release,
                run / "pilot_dataset")
            self.assertTrue(claim.is_file())
            with self.assertRaisesRegex(ip.InitialPilotError, "already consumed"):
                ip.claim_release_consumption(
                    run, release_path, core.sha256_path(release_path), release,
                    run / "another_dataset")

    def test_numerical_failure_writes_and_replays_immutable_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run"
            run.mkdir()
            config_path = CONFIG
            release_path = run / "pilot_release.json"
            release_path.write_text("{}")
            release_sha = core.sha256_path(release_path)
            force_workflow = {str(Path(ip.__file__).with_name(name).resolve()):
                              core.sha256_path(Path(ip.__file__).with_name(name))
                              for name in ("campaign.py", "qe_input.py", "qe_output.py",
                                           "pilot_dataset.py", "initial_pilot.py")}
            release = {
                "consumption_identity": "b" * 64,
                "contract": self.contract,
                "force_pilot_spec": ip.expected_force_spec(self.contract),
                "workflow_sha256": force_workflow,
                "limitations": ["initial only"],
            }
            bundle = run / "force"
            bundle.mkdir()
            task_map = bundle / "task_map.tsv"
            task_map.write_text("synthetic task map\n")
            budget = {
                "phase": "initial", "task_count": 6, "material": "SrZrS3",
                "task_map_sha256": core.sha256_path(task_map),
                "resource_policy_sha256": core.canonical_sha256(self.config["resource_budget"]),
                "mpi_ranks": 32,
                "maximum_concurrency": 2, "walltime_hours": 2,
                "maximum_technical_retries_per_task": 1,
                "reserved_core_hours": 768, "approved_total_core_hours": None,
            }
            (bundle / "budget_receipt.json").write_text(json.dumps(budget))
            tasks = [{"task_id": i, "displacement_id": displacement,
                      "role": "pristine" if displacement == 0 else "displacement",
                      "atom_labels": ["S"] * 40}
                     for i, displacement in enumerate([0, 0, 1, 3, 1, 3])]
            settings = fb._settings(self.config, "pilot",
                                    release["force_pilot_spec"],
                                    allow_count_only_initial=True)
            dataset = run / "dataset"
            dataset.mkdir()
            signed = {"dataset_dir": str(dataset),
                      "expected_manifest_sha256": "d" * 64}
            pseudo = run / "pseudos" / "S.upf"
            pseudo.parent.mkdir()
            pseudo.write_text("synthetic")
            manifest = {
                "schema_version": 1, "stage": "force", "mode": "pilot",
                "material": "SrZrS3", "config_sha256": core.sha256_path(config_path),
                "force_policy_sha256": core.canonical_sha256({
                    "production": self.config["production"],
                    "force": self.config["force_and_amplitude_validation"]}),
                "pilot_spec": release["force_pilot_spec"],
                "settings": settings, "tasks": tasks,
                "signed_pilot_dataset": signed,
                "pseudopotentials": {"S": {"file": str(pseudo), "sha256": core.sha256_path(pseudo)}},
                "task_map_sha256": core.sha256_path(task_map),
                "backend_sha256": core.sha256_path(Path(fb.__file__)),
                "workflow_sha256": release["workflow_sha256"],
                "selection_validation": None, "selection_evidence_sha256": {},
                "initial_pilot_release": {"path": str(release_path),
                    "sha256": release_sha,
                    "consumption_identity": release["consumption_identity"]},
                "budget_receipt_sha256": core.sha256_path(bundle / "budget_receipt.json"),
            }
            force_manifest = bundle / "force_manifest.json"
            force_manifest.write_text(json.dumps(manifest))
            force_sha = core.sha256_path(force_manifest)
            outputs = []
            entries = []
            attempt_root = run / "attempts"
            collector_attempt = run / "collector"
            collector_attempt.mkdir()
            for i, displacement in enumerate([0, 0, 1, 3, 1, 3]):
                attempt = attempt_root / f"task-{i}"
                attempt.mkdir(parents=True)
                output = attempt / "scf.out"
                output.write_text(str(i))
                (attempt / "scf.in").write_text("synthetic input")
                (attempt / "scf.err").write_text("")
                context = {"stage": "force", "attempt_id": "attempt-1",
                    "slurm_array_job_id": "99", "slurm_array_task_id": str(i),
                    "slurm_job_id": str(9900 + i), "run_dir": str(run.resolve()),
                    "config_sha256": core.sha256_path(config_path)}
                (attempt / "context.tsv").write_text("".join(
                    f"{key}\t{value}\n" for key, value in context.items()))
                (attempt / "exit_code.txt").write_text("0\n")
                (attempt / "finished_utc.txt").write_text("2026-09-14T00:00:00Z\n")
                for name in ("force_claim.json", "launch.json", "result.json",
                             "scf.process.json"):
                    (attempt / name).write_text("{}")
                evidence = {path.name: {"sha256": core.sha256_path(path),
                    "bytes": path.stat().st_size} for path in attempt.iterdir()
                    if path.is_file()}
                outputs.append(output)
                entries.append({"task_id": i, "displacement_id": displacement,
                    "role": "pristine" if displacement == 0 else "displacement",
                    "outcome": "accepted_success", "exit_code": 0, "errors": [],
                    "attempt_path": str(attempt), "context": context,
                    "evidence": evidence,
                    "timing": {"elapsed_seconds": 60, "allocated_cpus": 32,
                        "timelimit_minutes": 120, "max_rss": "100M", "scf_iterations": 8,
                        "core_hours": 32 / 60},
                    "resource_usage": {"elapsed_seconds": 60,
                        "allocated_cpus": 32, "timelimit_minutes": 120,
                        "core_hours": 32 / 60},
                    "scheduler_records": [{
                        "JobID": f"99_{i}", "JobIDRaw": str(9900 + i),
                        "State": "COMPLETED", "ExitCode": "0:0"}]})
            submission_records = {}
            for name in ("primary_request", "primary_result", "collector_request",
                         "collector_result"):
                path = run / f"{name}.json"
                path.write_text(json.dumps({"stage_script_sha256": "f" * 64}))
                submission_records[name] = {"path": str(path),
                    "sha256": core.sha256_path(path)}
            collection = {
                "schema_version": 1, "stage": "collect", "force_mode": "pilot",
                "collection_kind": "force_array_batch", "material": "SrZrS3",
                "collector_attempt": str(collector_attempt),
                "submitted_task_ids": list(range(6)), "submitted_task_count": 6,
                "expected_task_count": 6, "accepted_success_count": 6,
                "upstream_failure_count": 0, "unfinished_or_invalid_count": 0,
                "collection_integrity_complete": True, "batch_execution_complete": True,
                "incomplete": False, "status": "collected_successful_batch_no_scientific_gate",
                "global_errors": [], "scientific_gate_published": False,
                "production_dataset_complete": False, "scientific_dataset_incomplete": True,
                "eligible_for_force_constant_construction": False,
                "primary": {"stage": "force", "attempt_id": "attempt-1",
                    "job_id": "99", "attempt_root": str(attempt_root),
                    "force_manifest": str(force_manifest),
                    "force_manifest_sha256": force_sha,
                    "submitted_force_manifest_sha256": force_sha,
                    "task_map": str(task_map),
                    "task_map_sha256": core.sha256_path(task_map),
                    "submitted_task_map_sha256": core.sha256_path(task_map),
                    "submission_records": submission_records},
                "entries": entries,
            }
            collection_path = run / "collection.json"
            collection_path.write_text(json.dumps(collection))
            collection_sha = core.sha256_path(collection_path)
            matrices = [self.forces(0) for _ in range(6)]

            def artifact(_manifest, _attempt, task_id):
                attempt = Path(_attempt)
                return SimpleNamespace(input_path=str(attempt / "scf.in"),
                    output_path=str(attempt / "scf.out"), stderr_path=str(attempt / "scf.err"),
                    manifest={"settings_sha256": "e" * 64})

            def record(path, expected_atoms):
                return SimpleNamespace(forces_ry_bohr=matrices[int(Path(path).read_text())])

            output_path = run / "initial_result.json"
            with patch("initial_pilot.replay_initial_pilot_release", return_value=release), \
                 patch("force_backend.audit_signed_pilot_dataset", return_value=signed), \
                 patch("force_backend._dataset_inputs", return_value=({0:"x",1:"x",3:"x"}, {})), \
                 patch("postprocess_backend.load_force_artifact", side_effect=artifact), \
                 patch("initial_pilot.audit_actual_initial_input", return_value=("e" * 64, ["S"] * 40)), \
                 patch("initial_pilot.inspect_output", return_value={"healthy": True}), \
                 patch("initial_pilot.parse_last_force_block", side_effect=record), \
                 patch("campaign._force_submission_binding",
                       return_value=submission_records):
                finalized = ip.finalize_initial_pilot(config_path, run,
                    release_path=release_path, release_sha256=release_sha,
                    force_manifest_path=force_manifest,
                    collection_path=collection_path, collection_sha256=collection_sha,
                    output_path=output_path)
                self.assertEqual(finalized["status"], "below_resolution")
                replayed = ip.replay_initial_pilot_result(output_path,
                    config_path=config_path, run_dir=run,
                    expected_result_sha256=finalized["result_sha256"])
                self.assertEqual(replayed["status"], "below_resolution")
                self.assertTrue(all(value is False for key, value in
                    replayed["scope_claims"].items() if key !=
                    "initial_timing_repeatability_and_incremental_response_only"))
                self.assertIsNone(replayed["production_budget"])

                # Replace one failed logical task with exactly one successful
                # retry collection; the numerical evaluator still receives six.
                collection["entries"][2]["outcome"] = "upstream_failed"
                collection["entries"][2]["exit_code"] = 1
                collection.update(accepted_success_count=5,
                    upstream_failure_count=1, batch_execution_complete=False,
                    incomplete=True, status="collected_incomplete_force_batch")
                collection_path.write_text(json.dumps(collection))
                retry_root = run / "retry-attempts"
                retry_attempt = retry_root / "task-2"
                shutil.copytree(attempt_root / "task-2", retry_attempt)
                retry_context = {**entries[2]["context"],
                    "attempt_id": "retry-1", "slurm_array_job_id": "100",
                    "slurm_job_id": "10002"}
                (retry_attempt / "context.tsv").write_text("".join(
                    f"{key}\t{value}\n" for key, value in retry_context.items()))
                retry_evidence = {path.name: {"sha256": core.sha256_path(path),
                    "bytes": path.stat().st_size} for path in retry_attempt.iterdir()
                    if path.is_file()}
                retry_entry = {**entries[2], "attempt_path": str(retry_attempt),
                    "context": retry_context, "exit_code": 0,
                    "outcome": "accepted_success", "errors": [],
                    "evidence": retry_evidence,
                    "scheduler_records": [{"JobID": "100_2", "JobIDRaw": "10002",
                        "State": "COMPLETED", "ExitCode": "0:0"}]}
                retry_collector = run / "retry-collector"
                retry_collector.mkdir()
                retry_collection = {**collection,
                    "collector_attempt": str(retry_collector),
                    "submitted_task_ids": [2], "submitted_task_count": 1,
                    "accepted_success_count": 1, "upstream_failure_count": 0,
                    "batch_execution_complete": True, "incomplete": False,
                    "status": "collected_successful_batch_no_scientific_gate",
                    "primary": {**collection["primary"], "attempt_id": "retry-1",
                        "job_id": "100", "attempt_root": str(retry_root)},
                    "entries": [retry_entry]}
                retry_path = run / "retry-collection.json"
                retry_path.write_text(json.dumps(retry_collection))
                merged = ip.finalize_initial_pilot(config_path, run,
                    release_path=release_path, release_sha256=release_sha,
                    force_manifest_path=force_manifest,
                    collection_path=collection_path,
                    collection_sha256=core.sha256_path(collection_path),
                    retry_collection_path=retry_path,
                    retry_collection_sha256=core.sha256_path(retry_path),
                    output_path=run / "merged-result.json")
                self.assertEqual(merged["status"], "below_resolution")
                merged_payload = core.load_json(Path(merged["result"]))
                self.assertEqual(
                    merged_payload["timing_resource_summary"]["technical_retry_task_ids"],
                    [2],
                )
                self.assertEqual(
                    merged_payload["timing_resource_summary"]["logical_task_count"], 6
                )
                self.assertEqual(
                    merged_payload["timing_resource_summary"]["allocation_attempt_count"],
                    7,
                )
                self.assertAlmostEqual(
                    merged_payload["timing_resource_summary"]["observed_total_core_hours"],
                    7 * 32 / 60,
                )
                collection["entries"][0]["resource_usage"]["timelimit_minutes"] = 121
                collection_path.write_text(json.dumps(collection))
                rejected_output = run / "invalid-resource-result.json"
                with self.assertRaisesRegex(
                    ip.InitialPilotError, "resource evidence exceeds"
                ):
                    ip.finalize_initial_pilot(
                        config_path, run,
                        release_path=release_path, release_sha256=release_sha,
                        force_manifest_path=force_manifest,
                        collection_path=collection_path,
                        collection_sha256=core.sha256_path(collection_path),
                        retry_collection_path=retry_path,
                        retry_collection_sha256=core.sha256_path(retry_path),
                        output_path=rejected_output,
                    )
                self.assertFalse(rejected_output.exists())

    def test_invalid_evidence_never_writes_a_numerical_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run"
            run.mkdir()
            config = run / "campaign.json"
            config.write_text("{}")
            output = run / "must-not-exist.json"
            with self.assertRaises(ip.InitialPilotError):
                ip.finalize_initial_pilot(config, run,
                    release_path=run / "missing-release.json",
                    release_sha256="0" * 64,
                    force_manifest_path=run / "missing-force.json",
                    collection_path=run / "missing-collection.json",
                    collection_sha256="0" * 64, output_path=output)
            self.assertFalse(output.exists())

    def test_result_replay_rejects_external_or_symlinked_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "run"
            run.mkdir()
            external = root / "result.json"
            external.write_text("{}\n")
            with self.assertRaisesRegex(
                ip.InitialPilotError, "strict descendant|symlink"
            ):
                ip.replay_initial_pilot_result(
                    external,
                    config_path=CONFIG,
                    run_dir=run,
                    expected_result_sha256=core.sha256_path(external),
                )
            linked = run / "result.json"
            linked.symlink_to(external)
            with self.assertRaisesRegex(ip.InitialPilotError, "symlink"):
                ip.replay_initial_pilot_result(
                    linked,
                    config_path=CONFIG,
                    run_dir=run,
                    expected_result_sha256=core.sha256_path(external),
                )

    def test_actual_scf_input_settings_and_geometry_are_reparsed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fragment = root / "supercell.in"
            positions = "".join(f"S {(index % 5) / 5} 0 0\n" for index in range(40))
            fragment.write_text(
                "! ibrav = 0, nat = 40, ntyp = 1\n"
                "CELL_PARAMETERS bohr\n10 0 0\n0 10 0\n0 0 10\n"
                "ATOMIC_SPECIES\nS 32.065 S.upf\n"
                "ATOMIC_POSITIONS crystal\n" + positions)
            settings = fb._settings(self.config, "pilot",
                ip.expected_force_spec(self.contract), allow_count_only_initial=True)
            text = fb._fragment(fragment, settings, root)
            path = root / "scf.in"
            path.write_text(text)

            def audit(candidate, expected):
                path.write_text(candidate)
                task = {"input_sha256": core.sha256_path(path),
                        "atom_labels": ["S"] * 40}
                manifest = {"settings_sha256": core.canonical_sha256(qe_settings(candidate))}
                return ip.audit_actual_initial_input(path, expected, task, manifest)

            audit(text, text)
            wrong = (text.replace("ecutwfc=80, ecutrho=640", "ecutwfc=70, ecutrho=560")
                     .replace("conv_thr=1e-10", "conv_thr=1e-9")
                     .replace("3 3 3 0 0 0", "2 2 2 0 0 0"))
            with self.assertRaisesRegex(ip.InitialPilotError, "actual QE settings"):
                audit(wrong, wrong)
            displaced = text.replace("S 0.0 0 0", "S 0.01 0 0", 1)
            with self.assertRaisesRegex(ip.InitialPilotError, "geometry/settings"):
                audit(displaced, text)
            with self.assertRaisesRegex(ip.InitialPilotError, "settings hash"):
                task = {"input_sha256": core.sha256_path(path),
                        "atom_labels": ["S"] * 40}
                ip.audit_actual_initial_input(path, displaced, task,
                                              {"settings_sha256": "0" * 64})

    def test_collection_scope_contradictions_and_external_attempt_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "run"
            run.mkdir()
            release_path = run / "release.json"
            force_path = run / "force.json"
            collection_path = run / "collection.json"
            release_path.write_text("{}")
            force_path.write_text("{}")
            release = {"consumption_identity": "f" * 64, "contract": self.contract,
                       "force_pilot_spec": ip.expected_force_spec(self.contract),
                       "limitations": []}
            base = {
                "schema_version": 1, "stage": "collect",
                "collection_kind": "force_array_batch", "material": "SrZrS3",
                "force_mode": "pilot", "expected_task_count": 6,
                "accepted_success_count": 6, "upstream_failure_count": 0,
                "unfinished_or_invalid_count": 0,
                "collection_integrity_complete": True,
                "batch_execution_complete": True, "incomplete": False,
                "status": "collected_successful_batch_no_scientific_gate",
                "global_errors": [], "scientific_gate_published": False,
                "production_dataset_complete": False,
                "scientific_dataset_incomplete": True,
                "eligible_for_force_constant_construction": False,
            }
            for mutation in ({"collection_kind": "wrong"}, {"material": "Rb2Cu2SnS4"},
                             {"incomplete": True}):
                collection_path.write_text(json.dumps({**base, **mutation}))
                output = run / (next(iter(mutation)) + ".json")
                with patch("initial_pilot.replay_initial_pilot_release",
                           return_value=release), self.assertRaises(ip.InitialPilotError):
                    ip.finalize_initial_pilot(CONFIG, run,
                        release_path=release_path,
                        release_sha256=core.sha256_path(release_path),
                        force_manifest_path=force_path,
                        collection_path=collection_path,
                        collection_sha256=core.sha256_path(collection_path),
                        output_path=output)
                self.assertFalse(output.exists())

            collector = run / "collector"
            collector.mkdir()
            external = root / "external-attempts"
            external.mkdir()
            collection_path.write_text(json.dumps({**base,
                "collector_attempt": str(collector),
                "primary": {"stage": "force", "attempt_id": "attempt-1",
                            "job_id": "99", "attempt_root": str(external)}}))
            output = run / "external.json"
            with patch("initial_pilot.replay_initial_pilot_release",
                       return_value=release), self.assertRaises(ip.InitialPilotError):
                ip.finalize_initial_pilot(CONFIG, run,
                    release_path=release_path,
                    release_sha256=core.sha256_path(release_path),
                    force_manifest_path=force_path,
                    collection_path=collection_path,
                    collection_sha256=core.sha256_path(collection_path),
                        output_path=output)
            self.assertFalse(output.exists())
            linked = run / "linked-attempts"
            linked.symlink_to(external, target_is_directory=True)
            collection_path.write_text(json.dumps({**base,
                "collector_attempt": str(collector),
                "primary": {"stage": "force", "attempt_id": "attempt-1",
                            "job_id": "99", "attempt_root": str(linked)}}))
            output = run / "symlink.json"
            with patch("initial_pilot.replay_initial_pilot_release",
                       return_value=release), self.assertRaises(ip.InitialPilotError):
                ip.finalize_initial_pilot(CONFIG, run,
                    release_path=release_path,
                    release_sha256=core.sha256_path(release_path),
                    force_manifest_path=force_path,
                    collection_path=collection_path,
                    collection_sha256=core.sha256_path(collection_path),
                    output_path=output)
            self.assertFalse(output.exists())

    def test_known_failed_collector_can_only_be_recovered_from_all_six_raw_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = (Path(temporary) / "run").resolve()
            failed = run / "slurm_attempts" / "collect" / "failed-collector"
            failed.mkdir(parents=True)
            (failed / "context.tsv").write_text(
                "stage\tcollect\nattempt_id\tfailed-collector\nslurm_job_id\t777\n"
                "primary_stage\tforce\nprimary_attempt_id\tforce-1\nprimary_job_id\t123\n"
                "primary_request_sha256\t" + "a" * 64 + "\n"
                "primary_result_sha256\t" + "b" * 64 + "\n"
                "primary_stage_script_sha256\t" + "c" * 64 + "\n"
                "config\t" + str(CONFIG.resolve()) + "\n"
                "config_sha256\t" + core.sha256_path(CONFIG) + "\n"
                "git_commit\t" + "d" * 40 + "\n"
            )
            (failed / "exit_code.txt").write_text("2\n")
            (failed / "finished_utc.txt").write_text("2026-09-14T02:00:00Z\n")
            stdout = failed / "stdout.log"
            stdout.write_text(json.dumps({"command": "collect", "error": ip.FAILED_COLLECTOR_IDENTITY_ERROR,
                                          "healthy": False}) + "\n")
            (failed / "stderr.log").write_text("")
            accounting = failed / "primary_sacct.psv"
            accounting.write_text("synthetic accounting\n")
            accounting_status = failed / "primary_sacct_exit_code.txt"
            accounting_status.write_text("0\n")
            bundle = run / "force"
            bundle.mkdir()
            manifest, task_map = bundle / "force_manifest.json", bundle / "task_map.tsv"
            manifest.write_text("{}\n")
            task_map.write_text("task_id\n")
            historical = run / "historical-workflow"
            (historical / "slurm").mkdir(parents=True)
            for name in ip.HISTORICAL_WORKFLOW_FILES:
                source = Path(core.__file__).with_name(name) if "/" not in name else (
                    Path(core.__file__).parent / name)
                destination = historical / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            historical_hashes = {
                name: core.sha256_path(historical / name)
                for name in ip.HISTORICAL_WORKFLOW_FILES
            }
            report = {
                "expected_task_count": 6, "submitted_task_ids": list(range(6)),
                "accepted_success_count": 6, "upstream_failure_count": 0,
                "unfinished_or_invalid_count": 0, "collection_integrity_complete": True,
                "batch_execution_complete": True,
                "entries": [{"task_id": index, "outcome": "accepted_success",
                             "evidence": {"scf.out": {}}} for index in range(6)],
            }
            kwargs = dict(
                failed_collector_attempt=failed, primary_attempt_id="force-1",
                primary_job_id="123", force_manifest_path=manifest,
                force_manifest_sha256=core.sha256_path(manifest), task_map_path=task_map,
                task_map_sha256=core.sha256_path(task_map), primary_request_sha256="a" * 64,
                primary_result_sha256="b" * 64, primary_stage_script_sha256="c" * 64,
                accounting_sha256=core.sha256_path(accounting),
                accounting_status_sha256=core.sha256_path(accounting_status),
                failed_stdout_sha256=core.sha256_path(stdout),
                historical_workflow_dir=historical,
                historical_workflow_sha256=core.canonical_sha256(historical_hashes),
                output_path=run / "recovery.json",
            )
            with patch.object(core, "_read_sacct_records", return_value=([], [], {})), \
                 patch.object(core, "_collect_force_batch", return_value=report):
                result = ip.recover_failed_initial_pilot_collector(CONFIG, run, **kwargs)
            artifact = core.load_json(Path(result["recovery"]))
            self.assertTrue(artifact["original_collector_failed"])
            self.assertFalse(artifact["slurm_collector_succeeded"])
            self.assertEqual(artifact["reconstructed_collection_sha256"],
                             core.canonical_sha256(report))
            self.assertEqual(len(artifact["reconstructed_collection"]["entries"]), 6)
            original_campaign = (historical / "campaign.py").read_text()
            (historical / "campaign.py").write_text(original_campaign + "# altered\n")
            with self.assertRaisesRegex(ip.InitialPilotError, "historical workflow hash"):
                ip._historical_workflow(historical, kwargs["historical_workflow_sha256"])
            (historical / "campaign.py").write_text(original_campaign)
            bad_report = {**report, "entries": report["entries"][:5],
                          "accepted_success_count": 5}
            with patch.object(core, "_read_sacct_records", return_value=([], [], {})), \
                 patch.object(core, "_collect_force_batch", return_value=bad_report), \
                 self.assertRaisesRegex(ip.InitialPilotError, "exact complete six-task"):
                ip.recover_failed_initial_pilot_collector(CONFIG, run, **kwargs)

            stdout.write_text(json.dumps({"command": "collect", "error": "some other failure",
                                          "healthy": False}) + "\n")
            kwargs["failed_stdout_sha256"] = core.sha256_path(stdout)
            with self.assertRaisesRegex(ip.InitialPilotError, "known task-selector"):
                ip.recover_failed_initial_pilot_collector(CONFIG, run, **kwargs)
            stdout.write_text(json.dumps({"command": "collect", "error": ip.FAILED_COLLECTOR_IDENTITY_ERROR,
                                          "healthy": False, "extra": True}) + "\n")
            kwargs["failed_stdout_sha256"] = core.sha256_path(stdout)
            with self.assertRaisesRegex(ip.InitialPilotError, "exact known"):
                ip.recover_failed_initial_pilot_collector(CONFIG, run, **kwargs)
            stdout.write_text(json.dumps({"command": "collect", "error": ip.FAILED_COLLECTOR_IDENTITY_ERROR,
                                          "healthy": False}) + "\n")
            kwargs["failed_stdout_sha256"] = core.sha256_path(stdout)
            for name, altered in (("context.tsv", "stage\tforce\n"),
                                  ("exit_code.txt", "3\n"),
                                  ("finished_utc.txt", "not-a-time\n"),
                                  ("stderr.log", "unexpected stderr\n")):
                path = failed / name
                original = path.read_text()
                path.write_text(altered)
                with self.subTest(raw_failure_evidence=name), self.assertRaises(ip.InitialPilotError):
                    ip.recover_failed_initial_pilot_collector(CONFIG, run, **kwargs)
                path.write_text(original)
            outside = run / "outside-context.tsv"
            outside.write_text((failed / "context.tsv").read_text())
            (failed / "context.tsv").unlink()
            (failed / "context.tsv").symlink_to(outside)
            with self.assertRaisesRegex(ip.InitialPilotError, "symlink"):
                ip.recover_failed_initial_pilot_collector(CONFIG, run, **kwargs)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as campaign_module
from campaign import (
    CampaignError,
    analyze_displacement_yaml,
    command_prepare_relax,
    derive_no_cutoff_preflight_results,
    load_json,
    policy_sha256,
    preflight_candidate_id,
    preflight_completion_fields,
    safe_run_dir,
    select_preflight_candidates,
    supercell_lattices_match,
    validate_config,
    verify_manifest,
    verify_upstream_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SR_CONFIG = REPO_ROOT / "thermo_candidates/SrZrS3/phono3py/campaign.json"
RB_CONFIG = REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"


class CampaignConfigTests(unittest.TestCase):
    def test_direct_relax_rejects_imported_run_before_attempt_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary).resolve() / "imported-run"
            run_dir.mkdir()
            manifest = {
                "accepted_structure_import": {
                    "receipt": "accepted_structure_import.json"
                }
            }
            with patch.object(campaign_module, "require_compute_node"), patch.object(
                campaign_module, "validate_config", return_value=({}, {})
            ), patch.object(
                campaign_module, "safe_run_dir", return_value=run_dir
            ), patch.object(
                campaign_module, "verify_manifest", return_value=manifest
            ), patch.object(campaign_module, "attempt_dir") as attempt:
                with self.assertRaisesRegex(
                    CampaignError, "cannot execute a relax stage"
                ):
                    campaign_module.command_run_relax(SR_CONFIG, run_dir)
            attempt.assert_not_called()
            self.assertFalse((run_dir / "slurm_attempts/relax").exists())
            self.assertFalse(any(run_dir.rglob("relax.in")))

    def test_direct_finalize_rejects_imported_run_without_publication_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary).resolve() / "imported-run"
            final = run_dir / "relax/final"
            final.mkdir(parents=True)
            for name, content in (
                ("unitcell.in", b"immutable imported unitcell\n"),
                ("gate.json", b'{"pass":true}\n'),
                ("provenance.json", b'{"kind":"imported_accepted_structure"}\n'),
            ):
                (final / name).write_bytes(content)
            before = {
                str(path.relative_to(run_dir)): path.read_bytes()
                for path in run_dir.rglob("*") if path.is_file()
            }
            manifest = {
                "accepted_structure_import": {
                    "receipt": "accepted_structure_import.json"
                }
            }
            with patch.object(campaign_module, "require_compute_node"), patch.object(
                campaign_module, "validate_config", return_value=({}, {})
            ), patch.object(
                campaign_module, "safe_run_dir", return_value=run_dir
            ), patch.object(
                campaign_module, "verify_manifest", return_value=manifest
            ), patch.object(campaign_module, "attempt_dir") as attempt:
                with self.assertRaisesRegex(
                    CampaignError, "cannot finalize a relax stage"
                ):
                    campaign_module.command_finalize_relax(SR_CONFIG, run_dir)
            attempt.assert_not_called()
            after = {
                str(path.relative_to(run_dir)): path.read_bytes()
                for path in run_dir.rglob("*") if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertFalse((run_dir / "slurm_attempts/relax").exists())

    def test_preflight_replays_import_before_creating_attempt(self) -> None:
        run_dir = Path("/tmp/p3-imported-preflight-test")
        manifest = {"accepted_structure_import": {"receipt": "accepted_structure_import.json"}}
        with patch.object(campaign_module, "require_compute_node"), patch.object(
            campaign_module, "validate_config", return_value=({}, {})
        ), patch.object(
            campaign_module, "safe_run_dir", return_value=run_dir
        ), patch.object(
            campaign_module, "verify_upstream_manifest", return_value=manifest
        ), patch.object(
            campaign_module,
            "verify_imported_structure_if_present",
            side_effect=CampaignError("receipt hash mismatch"),
        ) as replay, patch.object(campaign_module, "attempt_dir") as attempt:
            with self.assertRaisesRegex(CampaignError, "receipt hash mismatch"):
                campaign_module.command_preflight(SR_CONFIG, run_dir)
        replay.assert_called_once_with(SR_CONFIG, run_dir, manifest)
        attempt.assert_not_called()

    def test_supercell_lattice_check_allows_phono3py_bohr_constant_roundoff(self) -> None:
        expected = (
            (21.76087607467058, 0.0, 0.0),
            (0.0, 32.6590246063486, 0.0),
            (0.0, 0.0, 26.461794777792868),
        )
        generated_by_phono3py_440 = (
            (21.760876217736488, 0.0, 0.0),
            (0.0, 32.6590248210639, 0.0),
            (0.0, 0.0, 26.461794951764755),
        )
        self.assertTrue(
            supercell_lattices_match(generated_by_phono3py_440, expected)
        )

        wrong_matrix = [list(row) for row in generated_by_phono3py_440]
        wrong_matrix[0][1] = 1e-5
        self.assertFalse(supercell_lattices_match(wrong_matrix, expected))

    def test_numeric_displacement_order_preserves_excluded_gaps_and_grouped_traversal(self) -> None:
        dataset = {
            "displacement_pairs": [
                {
                    "displacement_id": 1,
                    "displacement": [0.1, 0.0, 0.0],
                    "paired_with": [
                        {
                            "included": True,
                            "pair_distance": 2.5,
                            "displacements": [[0.1, 0.0, 0.0], [0.0, 0.1, 0.0]],
                            "displacement_ids": [3, 4],
                        },
                        {
                            "included": False,
                            "pair_distance": 6.0,
                            "displacements": [[-0.1, 0.0, 0.0]],
                            "displacement_ids": [5],
                        },
                    ],
                },
                {
                    "displacement_id": 2,
                    "displacement": [0.0, 0.0, 0.1],
                    "paired_with": [
                        {
                            "included": True,
                            "pair_distance": 3.0,
                            "displacements": [[0.0, -0.1, 0.0]],
                            "displacement_ids": [6],
                        },
                        {
                            "included": False,
                            "pair_distance": 7.0,
                            "displacements": [[0.0, 0.0, -0.1]],
                            "displacement_ids": [7],
                        },
                    ],
                },
            ]
        }
        inventory = analyze_displacement_yaml(dataset)
        self.assertEqual(inventory["all_displacement_ids"], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(inventory["grouped_traversal_displacement_ids"], [1, 3, 4, 5, 2, 6, 7])
        self.assertEqual(inventory["included_displacement_ids"], [1, 2, 3, 4, 6])
        self.assertEqual(inventory["single_displacements"], 2)
        self.assertEqual(inventory["included_pair_distances"], [2.5, 3.0])
        self.assertEqual(inventory["excluded_pair_distances"], [6.0, 7.0])
        self.assertEqual(inventory["nonzero_included_pair_groups"], 2)

    def test_material_configs_validate_and_remain_selection_gated(self) -> None:
        for config_path in (SR_CONFIG, RB_CONFIG):
            config, report = validate_config(config_path)
            self.assertTrue(report["healthy"])
            self.assertTrue(config["production"]["selection_required"])
            self.assertIsNone(config["production"]["selected_supercell"])
            self.assertIsNone(config["production"]["selected_cutoff"])

    def test_signed_preflight_subset_is_unique_nonempty_and_config_bound(self) -> None:
        config = load_json(SR_CONFIG)
        requested = [
            "sr_fc3_3x1x1__sr_cutoff_3p70A",
            "sr_fc3_2x1x1__sr_cutoff_3p70A",
        ]
        selected, signature = select_preflight_candidates(config, requested)
        self.assertEqual(
            signature["candidate_ids"],
            [
                "sr_fc3_2x1x1__sr_cutoff_3p70A",
                "sr_fc3_3x1x1__sr_cutoff_3p70A",
            ],
        )
        self.assertEqual(
            [preflight_candidate_id(item) for item in selected],
            signature["candidate_ids"],
        )
        self.assertRegex(signature["candidate_subset_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            preflight_completion_fields(signature),
            {
                "preflight_complete": False,
                "requested_scope_complete": True,
                "full_config_preflight_complete": False,
            },
        )
        all_selection = select_preflight_candidates(config, None)[1]
        self.assertEqual(
            preflight_completion_fields(all_selection),
            {
                "preflight_complete": True,
                "requested_scope_complete": True,
                "full_config_preflight_complete": True,
            },
        )
        self.assertEqual(
            select_preflight_candidates(config, list(reversed(requested)))[1],
            signature,
        )
        for bad, message in (
            ([], "nonempty"),
            ([requested[0], requested[0]], "duplicates"),
            (["not-configured"], "not uniquely present"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(CampaignError, message):
                select_preflight_candidates(config, bad)

        changed = copy.deepcopy(config)
        changed["displacements"]["hard_cap"] += 1
        self.assertNotEqual(
            select_preflight_candidates(changed, requested)[1][
                "candidate_subset_sha256"
            ],
            signature["candidate_subset_sha256"],
        )

    def test_no_cutoff_derivation_skips_unrun_parent_instead_of_failing(self) -> None:
        rows = [
            {
                "fc3_supercell_id": "sr_fc3_3x2x1",
                "cutoff_pair_id": None,
                "count_only_no_cutoff": True,
            },
            {
                "fc3_supercell_id": "sr_fc3_4x2x1",
                "cutoff_pair_id": None,
                "count_only_no_cutoff": True,
            },
        ]
        results, skipped = derive_no_cutoff_preflight_results(
            rows, {"sr_fc3_3x2x1": 11625}, 800
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["uncontracted_displacements"], 11625)
        self.assertEqual(
            skipped, ["sr_fc3_4x2x1__no_cutoff"]
        )

    def test_config_rejects_duplicate_preflight_candidate_identity(self) -> None:
        bad = copy.deepcopy(load_json(SR_CONFIG))
        bad["displacements"]["enumerate"].append(
            copy.deepcopy(bad["displacements"]["enumerate"][0])
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(
                CampaignError, "duplicate preflight candidate id"
            ):
                validate_config(path)

    def test_rejects_distance_unit_mismatch(self) -> None:
        bad = copy.deepcopy(load_json(SR_CONFIG))
        bad["displacements"]["amplitude_bohr"] = 0.03
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(CampaignError, "amplitude Å/bohr mismatch"):
                validate_config(path)

    def test_rejects_resource_or_scientific_gate_drift(self) -> None:
        cases = []
        wrong_budget = copy.deepcopy(load_json(SR_CONFIG))
        wrong_budget["resource_budget"]["approved_total_core_hours_per_material"] = 100
        cases.append((wrong_budget, "approved core hours must be null"))

        wrong_retry = copy.deepcopy(load_json(SR_CONFIG))
        wrong_retry["resource_budget"]["maximum_technical_retries_per_task"] = 2
        cases.append((wrong_retry, "exactly one technical retry"))

        wrong_nac = copy.deepcopy(load_json(SR_CONFIG))
        wrong_nac["nac"]["no_nac_branch_requires_explicit_cli_flag"] = ""
        cases.append((wrong_nac, "must use --nonac"))

        missing_mixed_signs = copy.deepcopy(load_json(SR_CONFIG))
        missing_mixed_signs["force_and_amplitude_validation"]["amplitude_pilot"][
            "double_displacement_four_sign_combinations_required"
        ] = False
        cases.append((missing_mixed_signs, "all four double-displacement signs"))

        wrong_diagnostic_resources = copy.deepcopy(load_json(RB_CONFIG))
        wrong_diagnostic_resources["scheduler"]["diagnostic_resources"][
            "maximum_core_hours"
        ] = 63
        cases.append(
            (
                wrong_diagnostic_resources,
                "maximum_core_hours must equal ntasks",
            )
        )

        with tempfile.TemporaryDirectory() as temporary:
            for index, (bad, message) in enumerate(cases):
                path = Path(temporary) / f"bad-{index}.json"
                path.write_text(json.dumps(bad))
                with self.subTest(message=message), self.assertRaisesRegex(
                    CampaignError, message
                ):
                    validate_config(path)

    def test_prepare_is_immutable_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            first = command_prepare_relax(SR_CONFIG, run_dir)
            second = command_prepare_relax(SR_CONFIG, run_dir)
            self.assertEqual(first["config_sha256"], second["config_sha256"])
            self.assertTrue((run_dir / "run_manifest.json").is_file())
            self.assertTrue((run_dir / "config.snapshot.json").is_file())

    def test_later_production_selection_does_not_invalidate_earlier_stages(self) -> None:
        config = load_json(SR_CONFIG)
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            initial_path = temporary_path / "initial.json"
            initial_path.write_text(json.dumps(config))
            run_dir = temporary_path / "run"
            command_prepare_relax(initial_path, run_dir)

            selected = copy.deepcopy(config)
            selected["production"]["selection_required"] = False
            selected["production"]["selected_supercell"] = selected["displacements"][
                "supercell_candidates"
            ][0]["id"]
            selected["production"]["selected_cutoff"] = selected["displacements"][
                "cutoff_candidates"
            ][0]["id"]
            selected_path = temporary_path / "selected.json"
            selected_path.write_text(json.dumps(selected))
            verify_manifest(selected, selected_path, run_dir, stage="structure")
            verify_manifest(selected, selected_path, run_dir, stage="preflight")

    def test_stage_policy_change_is_detected(self) -> None:
        config = load_json(SR_CONFIG)
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            initial_path = temporary_path / "initial.json"
            initial_path.write_text(json.dumps(config))
            run_dir = temporary_path / "run"
            command_prepare_relax(initial_path, run_dir)

            changed = copy.deepcopy(config)
            changed["tight_relax"]["conv_thr_ry"] *= 10
            changed_path = temporary_path / "changed.json"
            changed_path.write_text(json.dumps(changed))
            self.assertNotEqual(
                policy_sha256(config, "structure"),
                policy_sha256(changed, "structure"),
            )
            with self.assertRaisesRegex(CampaignError, "structure_policy_sha256"):
                verify_manifest(changed, changed_path, run_dir, stage="structure")

    def test_downstream_accepts_archived_code_hash_but_not_policy_drift(self) -> None:
        config = load_json(SR_CONFIG)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
            run_dir = root / "run"
            command_prepare_relax(config_path, run_dir)
            manifest_path = run_dir / "run_manifest.json"
            manifest = load_json(manifest_path)
            manifest["workflow_files"] = {"old/campaign.py": "a" * 64}
            manifest_path.write_text(json.dumps(manifest))

            with self.assertRaisesRegex(CampaignError, "workflow_files"):
                verify_manifest(config, config_path, run_dir, stage="preflight")
            self.assertEqual(
                verify_upstream_manifest(
                    config, config_path, run_dir, stage="preflight"
                )["workflow_files"],
                {"old/campaign.py": "a" * 64},
            )

            changed = copy.deepcopy(config)
            changed["displacements"]["hard_cap"] += 1
            changed_path = root / "changed.json"
            changed_path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(CampaignError, "preflight_policy_sha256"):
                verify_upstream_manifest(
                    changed, changed_path, run_dir, stage="preflight"
                )

    def test_rejects_frozen_or_broad_run_directory(self) -> None:
        with self.assertRaises(CampaignError):
            safe_run_dir(Path.home())
        with self.assertRaises(CampaignError):
            safe_run_dir(Path("/tmp/example/READY_TO_ATTACH/run"))

    def test_prepare_force_cli_passes_only_explicit_evidence_paths(self) -> None:
        arguments = [
            "prepare-force",
            "--config", str(SR_CONFIG),
            "--run-dir", "/tmp/p3-cli-run",
            "--preflight-inventory", "/tmp/p3-cli-run/preflight.json",
            "--dataset-dir", "/tmp/p3-cli-run/dataset",
            "--output-dir", "/tmp/p3-cli-run/force-bundle",
            "--pseudo-dir", "/tmp/pseudos",
            "--mode", "pilot",
            "--pilot-spec", "/tmp/p3-cli-run/pilot.json",
            "--expect-pilot-manifest-sha", "c" * 64,
            "--resource-request", "/tmp/p3-cli-run/resources.json",
        ]
        with patch.object(
            campaign_module,
            "command_prepare_force",
            return_value={"healthy": True},
        ) as command, patch.object(campaign_module, "print_json"):
            self.assertEqual(campaign_module.main(arguments), 0)
        keywords = command.call_args.kwargs
        self.assertEqual(keywords["mode"], "pilot")
        self.assertEqual(
            keywords["pilot_spec_path"], Path("/tmp/p3-cli-run/pilot.json")
        )
        self.assertEqual(keywords["pilot_dataset_manifest_sha256"], "c" * 64)
        self.assertIsNone(keywords["selection_evidence"])
        self.assertEqual(keywords["resource_request_path"], Path(arguments[-1]))

    def test_preflight_cli_forwards_signed_candidate_subset(self) -> None:
        candidate_ids = [
            "sr_fc3_2x1x1__sr_cutoff_3p70A",
            "sr_fc3_3x1x1__sr_cutoff_3p70A",
        ]
        signature = "a" * 64
        arguments = [
            "preflight",
            "--config",
            str(SR_CONFIG),
            "--run-dir",
            "/tmp/p3-preflight-subset",
            "--candidate-id",
            candidate_ids[0],
            "--candidate-id",
            candidate_ids[1],
            "--expect-candidate-subset-sha",
            signature,
        ]
        with patch.object(
            campaign_module, "command_preflight", return_value={"healthy": True}
        ) as command, patch.object(campaign_module, "print_json"):
            self.assertEqual(campaign_module.main(arguments), 0)
        self.assertEqual(command.call_args.kwargs["candidate_ids"], candidate_ids)
        self.assertEqual(
            command.call_args.kwargs["expected_candidate_subset_sha256"],
            signature,
        )

    def test_prepare_force_requires_pilot_anchor_and_rejects_it_for_production(self) -> None:
        common = {
            "preflight_inventory": Path("/tmp/p3-cli-run/preflight.json"),
            "dataset_dir": Path("/tmp/p3-cli-run/dataset"),
            "output_dir": Path("/tmp/p3-cli-run/force-bundle"),
            "pseudo_dir": Path("/tmp/pseudos"),
            "pilot_spec_path": Path("/tmp/p3-cli-run/pilot.json"),
            "selection_evidence": None,
            "resource_request_path": Path("/tmp/p3-cli-run/resources.json"),
        }
        with self.assertRaisesRegex(CampaignError, "expect-pilot-manifest-sha"):
            campaign_module.command_prepare_force(
                SR_CONFIG,
                Path("/tmp/p3-cli-run"),
                mode="pilot",
                pilot_dataset_manifest_sha256=None,
                **common,
            )
        with self.assertRaisesRegex(CampaignError, "64 lowercase hex"):
            campaign_module.command_prepare_force(
                SR_CONFIG,
                Path("/tmp/p3-cli-run"),
                mode="pilot",
                pilot_dataset_manifest_sha256="not-a-sha",
                **common,
            )
        with self.assertRaisesRegex(CampaignError, "production.*must not"):
            campaign_module.command_prepare_force(
                SR_CONFIG,
                Path("/tmp/p3-cli-run"),
                mode="production",
                pilot_dataset_manifest_sha256="c" * 64,
                **common,
            )

    def test_prepare_force_forwards_trusted_pilot_manifest_sha(self) -> None:
        with patch.object(
            campaign_module,
            "load_json",
            side_effect=[{"pilot": True}, {"phase": "initial"}],
        ), patch(
            "force_backend.prepare_force", return_value={"healthy": True}
        ) as prepare:
            result = campaign_module.command_prepare_force(
                SR_CONFIG,
                Path("/tmp/p3-cli-run"),
                preflight_inventory=Path("/tmp/p3-cli-run/preflight.json"),
                dataset_dir=Path("/tmp/p3-cli-run/dataset"),
                output_dir=Path("/tmp/p3-cli-run/force-bundle"),
                pseudo_dir=Path("/tmp/pseudos"),
                mode="pilot",
                pilot_spec_path=Path("/tmp/p3-cli-run/pilot.json"),
                pilot_dataset_manifest_sha256="d" * 64,
                selection_evidence=None,
                resource_request_path=Path("/tmp/p3-cli-run/resources.json"),
            )

        self.assertEqual(result, {"healthy": True})
        self.assertEqual(
            prepare.call_args.kwargs["pilot_dataset_manifest_sha256"], "d" * 64
        )

    def test_pilot_dataset_cli_requires_explicit_probe_plan(self) -> None:
        arguments = [
            "prepare-pilot-dataset",
            "--config", str(RB_CONFIG),
            "--run-dir", "/tmp/p3-pilot-run",
            "--candidate-dir", "/tmp/p3-pilot-run/preflight/candidate",
            "--preflight-inventory", "/tmp/p3-pilot-run/preflight/inventory.json",
            "--output-dir", "/tmp/p3-pilot-run/pilot",
            "--probe-spec", "/tmp/p3-pilot-run/probe.json",
        ]
        with patch.object(
            campaign_module,
            "command_prepare_pilot_dataset",
            return_value={"healthy": True},
        ) as command, patch.object(campaign_module, "print_json"):
            self.assertEqual(campaign_module.main(arguments), 0)
        self.assertEqual(command.call_args.kwargs["probe_spec_path"], Path(arguments[-1]))

    def test_force_task_cli_forwards_optional_retry_evidence(self) -> None:
        arguments = [
            "run-force-task",
            "--config", str(SR_CONFIG),
            "--run-dir", "/tmp/p3-force-run",
            "--task-map", "/tmp/p3-force-run/bundle/task_map.tsv",
            "--task-id", "3",
            "--retry-evidence", "/tmp/p3-force-run/retry.json",
        ]
        with patch.object(
            campaign_module,
            "command_run_force_task",
            return_value={"healthy": True},
        ) as command, patch.object(campaign_module, "print_json"):
            self.assertEqual(campaign_module.main(arguments), 0)
        self.assertEqual(command.call_args.kwargs["task_id"], 3)
        self.assertEqual(command.call_args.kwargs["retry_evidence"], Path(arguments[-1]))


if __name__ == "__main__":
    unittest.main()

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
    load_json,
    policy_sha256,
    safe_run_dir,
    supercell_lattices_match,
    validate_config,
    verify_manifest,
    verify_upstream_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SR_CONFIG = REPO_ROOT / "thermo_candidates/SrZrS3/phono3py/campaign.json"
RB_CONFIG = REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"


class CampaignConfigTests(unittest.TestCase):
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

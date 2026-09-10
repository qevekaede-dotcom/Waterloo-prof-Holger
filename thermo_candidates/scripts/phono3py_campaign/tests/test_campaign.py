from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from campaign import (
    CampaignError,
    analyze_displacement_yaml,
    command_prepare_relax,
    load_json,
    policy_sha256,
    safe_run_dir,
    validate_config,
    verify_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SR_CONFIG = REPO_ROOT / "thermo_candidates/SrZrS3/phono3py/campaign.json"
RB_CONFIG = REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"


class CampaignConfigTests(unittest.TestCase):
    def test_grouped_displacement_ids_are_sorted_only_for_file_comparison(self) -> None:
        dataset = {
            "displacement_pairs": [
                {
                    "displacement_id": 1,
                    "displacement": [0.1, 0.0, 0.0],
                    "paired_with": [
                        {
                            "included": True,
                            "displacements": [[0.1, 0.0, 0.0], [0.0, 0.1, 0.0]],
                            "displacement_ids": [3, 4],
                        }
                    ],
                },
                {
                    "displacement_id": 2,
                    "displacement": [0.0, 0.0, 0.1],
                    "paired_with": [],
                },
            ]
        }
        inventory = analyze_displacement_yaml(dataset)
        self.assertEqual(inventory["all_displacement_ids"], [1, 3, 4, 2])
        self.assertEqual(inventory["included_displacement_ids"], [1, 2, 3, 4])

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

    def test_rejects_frozen_or_broad_run_directory(self) -> None:
        with self.assertRaises(CampaignError):
            safe_run_dir(Path.home())
        with self.assertRaises(CampaignError):
            safe_run_dir(Path("/tmp/example/READY_TO_ATTACH/run"))


if __name__ == "__main__":
    unittest.main()

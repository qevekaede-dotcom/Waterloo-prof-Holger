from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import campaign as campaign_module
from campaign import (
    CampaignError,
    analyze_displacement_yaml,
    audit_count_only_prediction,
    command_prepare_relax,
    derive_no_cutoff_preflight_results,
    load_json,
    parse_phono3py_type1_yaml,
    policy_sha256,
    preflight_candidate_id,
    preflight_completion_fields,
    safe_run_dir,
    select_preflight_candidates,
    supercell_lattices_match,
    validate_config,
    validate_verified_count_only_result,
    verify_manifest,
    verify_upstream_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SR_CONFIG = REPO_ROOT / "thermo_candidates/SrZrS3/phono3py/campaign.json"
RB_CONFIG = REPO_ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json"
SR_COUNT_ONLY_EVIDENCE = (
    REPO_ROOT
    / "thermo_candidates/SrZrS3/phono3py/evidence/3p70A_count_only"
)
SR_VERIFIED_COUNT_ONLY_EVIDENCE = (
    REPO_ROOT
    / "thermo_candidates/SrZrS3/phono3py/evidence/3p5541348625A_count_only"
)
SR_VERIFIED_COUNT_ONLY_YAML = (
    SR_VERIFIED_COUNT_ONLY_EVIDENCE
    / "slurm_attempts/preflight/20260913T144259Z-preflight-2f0ab287"
    / "candidates/sr_fc3_2x1x1__sr_cutoff_3p5541348625A/phono3py_disp.yaml"
)


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
        self.assertEqual(inventory["included_pair_second_id_counts"], [2, 1])
        self.assertEqual(inventory["excluded_pair_second_id_counts"], [1, 1])
        self.assertEqual(inventory["nonzero_included_pair_groups"], 2)

    def test_dependency_free_phono3py_type1_parser_reads_real_archive(self) -> None:
        parsed = parse_phono3py_type1_yaml(
            SR_VERIFIED_COUNT_ONLY_YAML.read_text()
        )
        inventory = analyze_displacement_yaml(parsed)
        self.assertEqual(parsed["phono3py"]["version"], "4.4.0")
        self.assertEqual(parsed["physical_unit"]["length"], "au")
        self.assertEqual(
            parsed["supercell_matrix"], [[2, 0, 0], [0, 1, 0], [0, 0, 1]]
        )
        self.assertEqual(len(parsed["supercell"]["points"]), 40)
        self.assertEqual(
            [item["displacement_id"] for item in parsed["displacement_pairs"]],
            list(range(1, 26)),
        )
        self.assertEqual(len(inventory["all_displacement_ids"]), 4025)
        self.assertEqual(len(inventory["included_displacement_ids"]), 787)
        self.assertEqual(
            {
                key: parsed["displacement_pair_info"][key]
                for key in (
                    "number_of_singles",
                    "number_of_pairs",
                    "number_of_pairs_in_cutoff",
                )
            },
            {
                "number_of_singles": 25,
                "number_of_pairs": 4000,
                "number_of_pairs_in_cutoff": 762,
            },
        )

    def test_dependency_free_phono3py_parser_rejects_malformed_field(self) -> None:
        text = SR_VERIFIED_COUNT_ONLY_YAML.read_text().replace(
            "  displacement_id: 1\n", "  displacement_id 1\n", 1
        )
        with self.assertRaisesRegex(CampaignError, "not a mapping entry"):
            parse_phono3py_type1_yaml(text)

    def test_dependency_free_phono3py_parser_rejects_duplicate_key(self) -> None:
        text = SR_VERIFIED_COUNT_ONLY_YAML.read_text().replace(
            '  length: "au"\n', '  length: "au"\n  length: "au"\n', 1
        )
        with self.assertRaisesRegex(CampaignError, "duplicate key: length"):
            parse_phono3py_type1_yaml(text)

    def test_dependency_free_phono3py_parser_rejects_unsupported_yaml(self) -> None:
        text = SR_VERIFIED_COUNT_ONLY_YAML.read_text().replace(
            '  version: "4.4.0"\n', '  version: &version "4.4.0"\n', 1
        )
        with self.assertRaisesRegex(CampaignError, "unsupported YAML syntax"):
            parse_phono3py_type1_yaml(text)

    def test_dependency_free_phono3py_parser_rejects_pair_total_drift(self) -> None:
        text = SR_VERIFIED_COUNT_ONLY_YAML.read_text().replace(
            "  number_of_pairs_in_cutoff: 762\n",
            "  number_of_pairs_in_cutoff: 763\n",
            1,
        )
        with self.assertRaisesRegex(
            CampaignError, "number_of_pairs_in_cutoff differs from included IDs"
        ):
            parse_phono3py_type1_yaml(text)

    def test_material_configs_validate_and_remain_selection_gated(self) -> None:
        for config_path in (SR_CONFIG, RB_CONFIG):
            config, report = validate_config(config_path)
            self.assertTrue(report["healthy"])
            self.assertTrue(config["production"]["selection_required"])
            self.assertIsNone(config["production"]["selected_supercell"])
            self.assertIsNone(config["production"]["selected_cutoff"])

    def test_sr_verified_sub_cap_count_only_result_preserves_prediction_and_blocks_production(self) -> None:
        config, report = validate_config(SR_CONFIG)
        self.assertTrue(report["healthy"])
        cutoff_id = "sr_cutoff_3p5541348625A"
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == cutoff_id
        )
        self.assertEqual(cutoff["cutoff_pair_distance_angstrom"], 3.5541348625)
        self.assertEqual(cutoff["cutoff_pair_distance_cli_bohr"], 6.71634150010947)
        self.assertEqual(
            cutoff["candidate_status"],
            "verified_remote_count_only_not_force_pilot_or_production_acceptance",
        )
        self.assertFalse(cutoff["production_fc3_eligible_without_new_review"])
        prediction = cutoff["count_only_prediction"]
        self.assertEqual(
            prediction["evidence_status"],
            "prediction_from_read_only_thresholding_not_a_new_phono3py_result",
        )
        self.assertEqual(
            prediction["source_yaml_sha256"],
            "efdbe22c7e628d9bbf286250a7ddf5e1bce457048fc675a6e7ec050ba3aec70e",
        )
        self.assertEqual(
            prediction["source_preflight_inventory_sha256"],
            "ed52f4fbd933a8f786b1ff995637cdd497c2036d7a42eabbf0f4d5305c81594c",
        )
        self.assertEqual(
            prediction["source_preflight_inventory_path"],
            "thermo_candidates/SrZrS3/phono3py/evidence/3p70A_count_only/preflight_inventory.json",
        )
        self.assertEqual(prediction["shell_gap_angstrom"], [3.526178139, 3.582091586])
        self.assertEqual(prediction["source_cutoff_pair_distance_angstrom"], 3.7)
        self.assertEqual(
            prediction["source_cutoff_pair_distance_cli_bohr"],
            6.99198666111535,
        )
        self.assertEqual(prediction["expected_generated_displacement_supercells"], 787)
        self.assertEqual(prediction["expected_single_displacements"], 25)
        self.assertEqual(prediction["expected_second_displacement_ids"], 762)
        self.assertEqual(prediction["expected_included_pair_groups"], 147)
        self.assertEqual(prediction["expected_nonzero_included_pair_groups"], 122)
        self.assertEqual(
            prediction["expected_distinct_included_shells_angstrom"],
            [
                2.459508671,
                2.585175162,
                2.59813694,
                2.646829583,
                3.065676377,
                3.068714495,
                3.118844198,
                3.124895583,
                3.371525126,
                3.443068937,
                3.46404448,
                3.526178139,
            ],
        )
        self.assertEqual(
            prediction["expected_newly_excluded_shells_angstrom"],
            [3.582091586, 3.604263809, 3.616141604],
        )
        verified = cutoff["verified_count_only_result"]
        self.assertEqual(verified["job_id"], "21850149")
        self.assertEqual(
            verified["attempt_id"], "20260913T144259Z-preflight-2f0ab287"
        )
        self.assertEqual(
            verified["git_commit"],
            "5733f0cc486fa806ca2f6a1a653cd21541f70403",
        )
        self.assertEqual(
            verified["candidate_subset_sha256"],
            "03818d4d8a130f6ff6b8d8f0df6668f7bcd87cb01d995ae58acd36bed0e94504",
        )
        self.assertEqual(
            verified["preflight_policy_sha256"],
            "b8e4fff046f346babf938a794ffc890be819cb9fedb13825d03a8183a32e319d",
        )
        self.assertEqual(
            verified["candidate_selection"],
            {
                "schema_version": 1,
                "mode": "explicit_subset",
                "candidate_ids": [
                    "sr_fc3_2x1x1__sr_cutoff_3p5541348625A"
                ],
                "preflight_policy_sha256": "b8e4fff046f346babf938a794ffc890be819cb9fedb13825d03a8183a32e319d",
                "candidate_subset_sha256": "03818d4d8a130f6ff6b8d8f0df6668f7bcd87cb01d995ae58acd36bed0e94504",
                "configured_candidate_count": 10,
            },
        )
        self.assertEqual(
            (
                verified["generated_displacement_supercells"],
                verified["single_displacements"],
                verified["second_displacement_ids"],
                verified["included_pair_groups"],
                verified["nonzero_included_pair_groups"],
            ),
            (787, 25, 762, 147, 122),
        )
        self.assertTrue(verified["requested_scope_complete"])
        for field in (
            "preflight_complete",
            "full_config_preflight_complete",
            "selection_eligible",
            "force_pilot_authorized",
            "production_fc3_eligible",
        ):
            self.assertFalse(verified[field])
        rows = [
            item
            for item in config["displacements"]["enumerate"]
            if item.get("cutoff_pair_id") == cutoff_id
        ]
        self.assertEqual(
            rows,
            [
                {
                    "fc3_supercell_id": "sr_fc3_2x1x1",
                    "cutoff_pair_id": cutoff_id,
                    "count_only": True,
                }
            ],
        )
        selected, signature = select_preflight_candidates(
            config, [f"sr_fc3_2x1x1__{cutoff_id}"]
        )
        self.assertTrue(selected[0]["count_only"])
        self.assertEqual(
            preflight_completion_fields(signature),
            {
                "preflight_complete": False,
                "requested_scope_complete": True,
                "full_config_preflight_complete": False,
            },
        )
        self.assertTrue(config["production"]["selection_required"])
        self.assertIsNone(config["production"]["selected_supercell"])
        self.assertIsNone(config["production"]["selected_cutoff"])

    @staticmethod
    def count_only_prediction_inventory(
        cutoff: dict,
    ) -> dict:
        prediction = cutoff["count_only_prediction"]
        distances_angstrom: list[float] = []
        second_id_counts: list[int] = []

        def add_groups(shell: float, groups: int, second_ids: int) -> None:
            quotient, remainder = divmod(second_ids, groups)
            distances_angstrom.extend([shell] * groups)
            second_id_counts.extend(
                [quotient + 1] * remainder + [quotient] * (groups - remainder)
            )

        add_groups(
            0.0,
            prediction["expected_zero_distance_pair_groups"],
            prediction["expected_zero_distance_second_ids"],
        )
        for item in prediction["expected_included_shell_multiplicities"]:
            add_groups(
                item["shell_angstrom"], item["pair_groups"], item["second_ids"]
            )
        return {
            "included_displacement_ids": list(range(1, 788)),
            "single_displacements": 25,
            "included_pair_groups": 147,
            "nonzero_included_pair_groups": 122,
            "included_pair_distances": [
                value / campaign_module.BOHR_TO_ANGSTROM
                for value in distances_angstrom
            ],
            "included_pair_second_id_counts": second_id_counts,
            "excluded_pair_distances": [
                value / campaign_module.BOHR_TO_ANGSTROM
                for value in prediction["expected_newly_excluded_shells_angstrom"]
            ],
        }

    def test_count_only_prediction_runtime_audit_passes_and_records_evidence(self) -> None:
        config = load_json(SR_CONFIG)
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        prediction = cutoff["count_only_prediction"]
        inventory = self.count_only_prediction_inventory(cutoff)
        audit = audit_count_only_prediction(cutoff, inventory, 787)
        self.assertIsNotNone(audit)
        self.assertTrue(audit["pass"])
        self.assertEqual(audit["mismatches"], [])
        self.assertEqual(
            audit["observed"]["largest_positive_included_shell_angstrom"],
            3.526178139,
        )
        self.assertEqual(
            audit["observed"]["smallest_excluded_shell_angstrom"],
            3.582091586,
        )
        self.assertTrue(audit["distinct_included_shell_set_equivalent"])
        self.assertTrue(audit["included_shell_multiplicities_equivalent"])
        self.assertTrue(audit["newly_excluded_shell_set_equivalent"])
        self.assertEqual(
            audit["newly_excluded_interval_angstrom"],
            {"lower_exclusive": 3.5541348625, "upper_inclusive": 3.7},
        )

    def test_count_only_prediction_runtime_audit_fails_closed_on_mismatch(self) -> None:
        config = load_json(SR_CONFIG)
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        inventory = self.count_only_prediction_inventory(cutoff)
        with self.assertRaisesRegex(
            CampaignError, "generated_displacement_supercells"
        ):
            audit_count_only_prediction(cutoff, inventory, 788)

        missing_shell = copy.deepcopy(inventory)
        missing_shell["excluded_pair_distances"] = [
            3.604263809 / campaign_module.BOHR_TO_ANGSTROM,
            3.616141604 / campaign_module.BOHR_TO_ANGSTROM,
        ]
        with self.assertRaisesRegex(
            CampaignError, "smallest_excluded_shell_angstrom"
        ):
            audit_count_only_prediction(cutoff, missing_shell, 787)

    def test_count_only_prediction_runtime_rejects_unexpected_included_shell(self) -> None:
        config = load_json(SR_CONFIG)
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        inventory = self.count_only_prediction_inventory(cutoff)
        source_shell_bohr = 3.443068937 / campaign_module.BOHR_TO_ANGSTROM
        source_indices = [
            index
            for index, distance in enumerate(inventory["included_pair_distances"])
            if abs(distance - source_shell_bohr) < 1e-10
        ]
        inventory["included_pair_distances"][source_indices[0]] = (
            3.2 / campaign_module.BOHR_TO_ANGSTROM
        )
        with self.assertRaisesRegex(
            CampaignError, "distinct_positive_included_shells_angstrom"
        ):
            audit_count_only_prediction(cutoff, inventory, 787)

    def test_count_only_prediction_runtime_rejects_shell_multiplicity_redistribution(self) -> None:
        config = load_json(SR_CONFIG)
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        inventory = self.count_only_prediction_inventory(cutoff)
        source_shell_bohr = 3.443068937 / campaign_module.BOHR_TO_ANGSTROM
        source_index = next(
            index
            for index, distance in enumerate(inventory["included_pair_distances"])
            if abs(distance - source_shell_bohr) < 1e-10
        )
        inventory["included_pair_distances"][source_index] = (
            3.46404448 / campaign_module.BOHR_TO_ANGSTROM
        )
        with self.assertRaisesRegex(CampaignError, "included_shell_multiplicities"):
            audit_count_only_prediction(cutoff, inventory, 787)

    def test_count_only_prediction_runtime_requires_exact_newly_excluded_shell_set(self) -> None:
        config = load_json(SR_CONFIG)
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        unexpected = self.count_only_prediction_inventory(cutoff)
        unexpected["excluded_pair_distances"].append(
            3.65 / campaign_module.BOHR_TO_ANGSTROM
        )
        with self.assertRaisesRegex(
            CampaignError, "distinct_newly_excluded_shells_angstrom"
        ):
            audit_count_only_prediction(cutoff, unexpected, 787)

        beyond_source = self.count_only_prediction_inventory(cutoff)
        beyond_source["excluded_pair_distances"].append(
            3.75 / campaign_module.BOHR_TO_ANGSTROM
        )
        audit = audit_count_only_prediction(cutoff, beyond_source, 787)
        self.assertTrue(audit["newly_excluded_shell_set_equivalent"])

    def test_sr_predicted_cutoff_cannot_be_promoted_or_duplicate_supercell_added(self) -> None:
        cases = []
        promoted = copy.deepcopy(load_json(SR_CONFIG))
        next(
            item
            for item in promoted["displacements"]["enumerate"]
            if item.get("cutoff_pair_id") == "sr_cutoff_3p5541348625A"
        )["count_only"] = False
        cases.append((promoted, "enumeration must be count-only"))

        duplicated = copy.deepcopy(load_json(SR_CONFIG))
        duplicated["displacements"]["enumerate"].append(
            {
                "fc3_supercell_id": "sr_fc3_3x1x1",
                "cutoff_pair_id": "sr_cutoff_3p5541348625A",
                "count_only": True,
            }
        )
        cases.append((duplicated, "exactly one count-only enumeration"))

        shell_drift = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in shell_drift["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        cutoff["count_only_prediction"]["expected_smallest_excluded_shell_angstrom"] = 3.60
        cases.append((shell_drift, "shell-boundary contract is inconsistent"))

        source_cutoff_unit_drift = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in source_cutoff_unit_drift["displacements"][
                "cutoff_candidates"
            ]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        cutoff["count_only_prediction"][
            "source_cutoff_pair_distance_cli_bohr"
        ] = 3.7
        cases.append((source_cutoff_unit_drift, "source cutoff bound is invalid"))

        for changed, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "changed.json"
                path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(CampaignError, message):
                    validate_config(path)

    def test_sr_predicted_cutoff_cannot_be_selected_for_production(self) -> None:
        selected = copy.deepcopy(load_json(SR_CONFIG))
        selected["production"].update(
            selection_required=False,
            selected_supercell="sr_fc3_2x1x1",
            selected_cutoff="sr_cutoff_3p5541348625A",
            automatic_submission_allowed=True,
        )
        selected["force_and_amplitude_validation"].update(
            selection_required=False,
            selected_displacement_distance_angstrom=0.03,
            selected_displacement_distance_cli_bohr=0.0566917837388,
            selected_ecutwfc_Ry=80,
            selected_ecutrho_Ry=640,
            selected_conv_thr_Ry=1e-10,
            selected_k_points=[2, 2, 2],
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "selected.json"
            path.write_text(json.dumps(selected))
            with self.assertRaisesRegex(
                CampaignError, "selected cutoff requires a new scientific review"
            ):
                validate_config(path)

    def test_sr_prediction_evidence_is_path_and_hash_bound(self) -> None:
        for field, value, message in (
            ("source_yaml_sha256", "0" * 64, "source YAML hash mismatch"),
            (
                "source_preflight_inventory_path",
                "../outside.json",
                "escapes repository root",
            ),
        ):
            bad = copy.deepcopy(load_json(SR_CONFIG))
            cutoff = next(
                item
                for item in bad["displacements"]["cutoff_candidates"]
                if item["id"] == "sr_cutoff_3p5541348625A"
            )
            cutoff["count_only_prediction"][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad-evidence.json"
                path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(CampaignError, message):
                    validate_config(path)

    def test_sr_verified_count_only_manifest_is_path_hash_and_status_bound(self) -> None:
        cases = (
            ("manifest_sha256", "0" * 64, "manifest hash mismatch"),
            ("manifest_path", "../outside.json", "escapes repository root"),
        )
        for field, value, message in cases:
            bad = copy.deepcopy(load_json(SR_CONFIG))
            cutoff = next(
                item
                for item in bad["displacements"]["cutoff_candidates"]
                if item["id"] == "sr_cutoff_3p5541348625A"
            )
            cutoff["verified_count_only_result"][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad-verified-evidence.json"
                path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(CampaignError, message):
                    validate_config(path)

        bad_status = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in bad_status["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        cutoff["candidate_status"] = (
            "predicted_from_verified_remote_3p70A_yaml_not_a_generated_result"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad-status.json"
            path.write_text(json.dumps(bad_status))
            with self.assertRaisesRegex(CampaignError, "status is inconsistent"):
                validate_config(path)

    def test_sr_verified_count_only_manifest_rejects_rehashed_semantic_tamper(self) -> None:
        config = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            relative_evidence = Path(
                "thermo_candidates/SrZrS3/phono3py/evidence/3p5541348625A_count_only"
            )
            copied_evidence = temporary_root / relative_evidence
            shutil.copytree(SR_VERIFIED_COUNT_ONLY_EVIDENCE, copied_evidence)
            manifest_path = copied_evidence / "manifest.json"
            manifest = load_json(manifest_path)
            manifest["observed"]["generated_displacement_supercells"] = 788
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            cutoff["verified_count_only_result"]["manifest_sha256"] = (
                campaign_module.sha256_path(manifest_path)
            )
            with patch.object(campaign_module, "REPO_ROOT", temporary_root):
                with self.assertRaisesRegex(
                    CampaignError,
                    "manifest.observed.generated_displacement_supercells",
                ):
                    validate_verified_count_only_result(config, cutoff)

    def test_sr_verified_count_only_result_cannot_claim_promotion(self) -> None:
        for field in (
            "preflight_complete",
            "full_config_preflight_complete",
            "selection_eligible",
            "force_pilot_authorized",
            "production_fc3_eligible",
        ):
            bad = copy.deepcopy(load_json(SR_CONFIG))
            cutoff = next(
                item
                for item in bad["displacements"]["cutoff_candidates"]
                if item["id"] == "sr_cutoff_3p5541348625A"
            )
            cutoff["verified_count_only_result"][field] = True
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad-promotion.json"
                path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(CampaignError, field):
                    validate_config(path)

    def test_sr_verified_result_does_not_rewrite_archived_preflight_policy(self) -> None:
        current = load_json(SR_CONFIG)
        archived = load_json(SR_VERIFIED_COUNT_ONLY_EVIDENCE / "config.snapshot.json")
        expected = "b8e4fff046f346babf938a794ffc890be819cb9fedb13825d03a8183a32e319d"
        self.assertEqual(policy_sha256(archived, "preflight"), expected)
        self.assertEqual(policy_sha256(current, "preflight"), expected)

    def test_sr_verified_count_only_rejects_current_hard_cap_drift(self) -> None:
        config = copy.deepcopy(load_json(SR_CONFIG))
        config["displacements"]["hard_cap"] = 801
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        with self.assertRaisesRegex(CampaignError, "preflight_policy_sha256"):
            validate_verified_count_only_result(config, cutoff)

    def test_sr_verified_count_only_manifest_rejects_internal_symlink(self) -> None:
        config = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            copied_evidence = temporary_root / "real-evidence"
            shutil.copytree(SR_VERIFIED_COUNT_ONLY_EVIDENCE, copied_evidence)
            (temporary_root / "linked-evidence").symlink_to(
                copied_evidence, target_is_directory=True
            )
            cutoff["verified_count_only_result"]["manifest_path"] = (
                "linked-evidence/manifest.json"
            )
            with patch.object(campaign_module, "REPO_ROOT", temporary_root):
                with self.assertRaisesRegex(CampaignError, "contains a symlink"):
                    validate_verified_count_only_result(config, cutoff)

    def test_sr_verified_count_only_rejects_synchronized_id_rehash_without_yaml_change(
        self,
    ) -> None:
        config = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            relative_evidence = Path(
                "thermo_candidates/SrZrS3/phono3py/evidence/3p5541348625A_count_only"
            )
            copied_evidence = temporary_root / relative_evidence
            shutil.copytree(SR_VERIFIED_COUNT_ONLY_EVIDENCE, copied_evidence)
            manifest_path = copied_evidence / "manifest.json"
            manifest = load_json(manifest_path)

            generated_path = copied_evidence / "generated_inputs.SHA256SUMS"
            generated_rows = generated_path.read_text().splitlines()
            self.assertTrue(generated_rows[-1].endswith("  supercell-04011.in"))
            generated_rows[-1] = generated_rows[-1].replace(
                "supercell-04011.in", "supercell-04012.in"
            )
            generated_path.write_text("\n".join(generated_rows) + "\n")
            manifest["generated_inputs"]["sha256sums_sha256"] = (
                campaign_module.sha256_path(generated_path)
            )

            result_relative = manifest["result_artifacts"]["preflight_result_path"]
            inventory_relative = manifest["result_artifacts"][
                "preflight_inventory_path"
            ]
            result_path = copied_evidence / result_relative
            inventory_path = copied_evidence / inventory_relative
            preflight_result = load_json(result_path)
            preflight_result["generated_displacement_ids"][-1] = 4012
            result_path.write_text(json.dumps(preflight_result, indent=2) + "\n")
            inventory = load_json(inventory_path)
            inventory["results"] = [preflight_result]
            inventory_path.write_text(json.dumps(inventory, indent=2) + "\n")

            result_hash = campaign_module.sha256_path(result_path)
            inventory_hash = campaign_module.sha256_path(inventory_path)
            manifest["result_artifacts"]["preflight_result_sha256"] = result_hash
            manifest["result_artifacts"]["preflight_inventory_sha256"] = inventory_hash
            verified = cutoff["verified_count_only_result"]
            verified["preflight_result_sha256"] = result_hash
            verified["preflight_inventory_sha256"] = inventory_hash

            changed_generated_ids = preflight_result["generated_displacement_ids"]
            changed_excluded_ids = sorted(
                set(range(1, preflight_result["uncontracted_displacements"] + 1))
                - set(changed_generated_ids)
            )
            manifest["observed"]["canonical_generated_id_list_sha256"] = (
                campaign_module.hashlib.sha256(
                    ("\n".join(map(str, changed_generated_ids)) + "\n").encode()
                ).hexdigest()
            )
            manifest["observed"]["canonical_excluded_id_list_sha256"] = (
                campaign_module.hashlib.sha256(
                    ("\n".join(map(str, changed_excluded_ids)) + "\n").encode()
                ).hexdigest()
            )

            archive_path = copied_evidence / "SHA256SUMS"
            replacements = {
                result_relative: result_hash,
                inventory_relative: inventory_hash,
            }
            archive_rows = archive_path.read_text().splitlines()
            archive_path.write_text(
                "\n".join(
                    f"{replacements.get(name, digest)}  {name}"
                    for digest, name in (row.split("  ", 1) for row in archive_rows)
                )
                + "\n"
            )
            manifest["archive"]["raw_artifact_sha256sums_sha256"] = (
                campaign_module.sha256_path(archive_path)
            )
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            verified["manifest_sha256"] = campaign_module.sha256_path(manifest_path)

            with patch.object(campaign_module, "REPO_ROOT", temporary_root):
                with self.assertRaisesRegex(
                    CampaignError, "versus phono3py YAML included IDs"
                ):
                    validate_verified_count_only_result(config, cutoff)

    def test_sr_verified_count_only_rejects_rehashed_submission_tamper(self) -> None:
        config = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            relative_evidence = Path(
                "thermo_candidates/SrZrS3/phono3py/evidence/3p5541348625A_count_only"
            )
            copied_evidence = temporary_root / relative_evidence
            shutil.copytree(SR_VERIFIED_COUNT_ONLY_EVIDENCE, copied_evidence)
            manifest_path = copied_evidence / "manifest.json"
            manifest = load_json(manifest_path)
            request_relative = (
                "submissions/preflight/20260913T144259Z-preflight-2f0ab287/request.json"
            )
            request_path = copied_evidence / request_relative
            request = load_json(request_path)
            request["candidate_subset_sha256"] = "0" * 64
            request_path.write_text(json.dumps(request, indent=2) + "\n")
            request_hash = campaign_module.sha256_path(request_path)
            checksum_path = copied_evidence / "SHA256SUMS"
            checksum_lines = checksum_path.read_text().splitlines()
            checksum_path.write_text(
                "\n".join(
                    f"{request_hash}  {request_relative}"
                    if line.endswith(f"  {request_relative}")
                    else line
                    for line in checksum_lines
                )
                + "\n"
            )
            manifest["provenance"]["submission_sha256"]["request.json"] = request_hash
            manifest["archive"]["raw_artifact_sha256sums_sha256"] = (
                campaign_module.sha256_path(checksum_path)
            )
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            cutoff["verified_count_only_result"]["manifest_sha256"] = (
                campaign_module.sha256_path(manifest_path)
            )
            with patch.object(campaign_module, "REPO_ROOT", temporary_root):
                with self.assertRaisesRegex(
                    CampaignError, "request.candidate_subset_sha256"
                ):
                    validate_verified_count_only_result(config, cutoff)

    def test_sr_verified_count_only_rejects_checksum_list_path_escape(self) -> None:
        config = copy.deepcopy(load_json(SR_CONFIG))
        cutoff = next(
            item
            for item in config["displacements"]["cutoff_candidates"]
            if item["id"] == "sr_cutoff_3p5541348625A"
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            relative_evidence = Path(
                "thermo_candidates/SrZrS3/phono3py/evidence/3p5541348625A_count_only"
            )
            copied_evidence = temporary_root / relative_evidence
            shutil.copytree(SR_VERIFIED_COUNT_ONLY_EVIDENCE, copied_evidence)
            manifest_path = copied_evidence / "manifest.json"
            manifest = load_json(manifest_path)
            checksum_path = copied_evidence / "SHA256SUMS"
            checksum_lines = checksum_path.read_text().splitlines()
            digest, _ = checksum_lines[0].split("  ", 1)
            checksum_lines[0] = f"{digest}  ../escaped.json"
            checksum_path.write_text("\n".join(checksum_lines) + "\n")
            manifest["archive"]["raw_artifact_sha256sums_sha256"] = (
                campaign_module.sha256_path(checksum_path)
            )
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            cutoff["verified_count_only_result"]["manifest_sha256"] = (
                campaign_module.sha256_path(manifest_path)
            )
            with patch.object(campaign_module, "REPO_ROOT", temporary_root):
                with self.assertRaisesRegex(CampaignError, "stay inside"):
                    validate_verified_count_only_result(config, cutoff)

    def test_sr_durable_count_only_evidence_manifest_matches_files(self) -> None:
        manifest = load_json(SR_COUNT_ONLY_EVIDENCE / "manifest.json")
        self.assertEqual(
            manifest["evidence_status"],
            "frozen_raw_count_only_not_production_acceptance",
        )
        self.assertTrue(manifest["raw_bytes_unchanged"])
        for artifact in manifest["artifacts"]:
            path = SR_COUNT_ONLY_EVIDENCE / artifact["path"]
            with self.subTest(path=artifact["path"]):
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_size, artifact["size_bytes"])
                self.assertEqual(
                    campaign_module.sha256_path(path), artifact["sha256"]
                )

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

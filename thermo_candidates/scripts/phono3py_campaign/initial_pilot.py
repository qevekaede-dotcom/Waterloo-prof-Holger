"""Narrow SrZrS3 count-only -> exact-six initial-pilot authorization.

This module never submits or executes a scientific program.  It creates and
replays one immutable, hash-bound release, and finalizes only the timing,
repeatability, and resolvable incremental-force response of its six SCFs.
"""
from __future__ import annotations

import math
import os
import re
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import campaign as core
from qe_input import parse_qe_input
from qe_output import inspect_output, parse_last_force_block


InitialPilotError = core.CampaignError
SCHEMA_VERSION = 1
REL_TOL = 1e-8
ABS_TOL_BOHR = 2e-8
EXPECTED_TASK_IDS = [0, 0, 1, 3, 1, 3]
EXPECTED_ROLE_IDS = {
    "single": {"plus": 1, "minus": 2},
    "double": {"pp": 3, "pm": 4, "mp": 5, "mm": 6},
}
FAILED_COLLECTOR_IDENTITY_ERROR = (
    "force primary submission request identity/hash mismatch"
)
WORKFLOW_FILES = (
    "campaign.py",
    "force_backend.py",
    "initial_pilot.py",
    "pilot_dataset.py",
    "postprocess_backend.py",
    "qe_input.py",
    "qe_output.py",
)
HISTORICAL_WORKFLOW_FILES = tuple(dict.fromkeys(WORKFLOW_FILES + (
    "submit.py", "slurm/cluster.env", "slurm/force_array.sbatch",
    "slurm/collect.sbatch",
)))


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise InitialPilotError(message)


def _digest(value: Any, label: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{label} must be a lowercase SHA256",
    )
    return value


def _match(path: Path, digest: Any, label: str) -> None:
    _require(path.is_file(), f"missing {label}: {path}")
    _require(core.sha256_path(path) == _digest(digest, label), f"{label} hash mismatch")


def _close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=REL_TOL, abs_tol=ABS_TOL_BOHR)


def _vector_close(left: Sequence[float], right: Sequence[float]) -> bool:
    return len(left) == len(right) and all(_close(x, y) for x, y in zip(left, right))


def _contract(config: Mapping[str, Any]) -> Mapping[str, Any]:
    contract = config.get("initial_timing_noise_pilot")
    _require(isinstance(contract, Mapping), "initial_timing_noise_pilot contract is required")
    expected = {
        "schema_version": 1,
        "material": "SrZrS3",
        "source_supercell_id": "sr_fc3_2x1x1",
        "source_cutoff_id": "sr_cutoff_3p5541348625A",
        "atom_count": 40,
        "atom_1_based": [33, 35],
        "species": ["S", "S"],
        "task_displacement_ids": EXPECTED_TASK_IDS,
        "synthetic_role_ids": EXPECTED_ROLE_IDS,
    }
    for key, value in expected.items():
        _require(contract.get(key) == value, f"initial pilot contract mismatch: {key}")
    _require(contract.get("mode") == "pilot" and contract.get("phase") == "initial",
             "release scope must be pilot/initial")
    _require(contract.get("validation_authorized") is False
             and contract.get("production_authorized") is False,
             "release must deny validation and production")
    _require(contract.get("atom_33_direction") == "+unit_vector_33_to_35"
             and contract.get("atom_35_direction") == "-unit_vector_33_to_35",
             "initial pilot atom directions mismatch")
    _require(config["resource_budget"].get("approved_total_core_hours_per_material") is None,
             "initial pilot may not create or consume a production budget")
    _require(config["production"].get("automatic_submission_allowed") is False,
             "initial pilot requires production to remain unauthorized")
    direction = contract.get("unit_vector_33_to_35")
    _require(isinstance(direction, list) and _vector_close(direction, [
        0.5442795443484355, 0.06343291855365582, 0.836502266851456
    ]), "initial pilot unit vector mismatch")
    _require(_close(contract.get("pair_distance_bohr"), 6.663510948767675),
             "initial pilot pair distance bohr mismatch")
    _require(math.isclose(float(contract.get("pair_distance_angstrom")), 3.526178138690481,
                          rel_tol=REL_TOL, abs_tol=2e-8),
             "initial pilot pair distance angstrom mismatch")
    _require(_close(contract.get("amplitude_bohr"), 0.0566917837388)
             and math.isclose(float(contract.get("amplitude_angstrom")), 0.03,
                              rel_tol=REL_TOL, abs_tol=2e-8),
             "initial pilot amplitude mismatch")
    settings = contract.get("settings")
    resources = contract.get("resources")
    _require(settings == {"ecutwfc_Ry": 80, "ecutrho_Ry": 640,
                          "conv_thr_Ry": 1e-10, "kmesh": [3, 3, 3],
                          "kshift": [0, 0, 0], "nosym": True, "noinv": True},
             "initial pilot force settings mismatch")
    _require(resources == {"mpi_ranks": 32, "walltime_hours": 2,
                           "max_concurrency": 2,
                           "maximum_technical_retries_per_task": 1,
                           "maximum_reserved_core_hours": 768},
             "initial pilot resource contract mismatch")
    acceptance = contract.get("acceptance")
    _require(acceptance == {"component_count": 120, "remove_component_mean": False,
                            "maximum_each_duplicate_rms_Ry_per_bohr": 5e-6,
                            "epsilon_Ry_per_bohr": 1e-15,
                            "minimum_incremental_signal_to_propagated_noise": 10.0},
             "initial pilot acceptance contract mismatch")
    return contract


def _cutoff(config: Mapping[str, Any], cutoff_id: str) -> Mapping[str, Any]:
    matches = [item for item in config["displacements"]["cutoff_candidates"]
               if item.get("id") == cutoff_id]
    _require(len(matches) == 1, "initial pilot source cutoff is not unique")
    return matches[0]


def _repo_file_at(root: Path, raw: Any, field: str) -> Path:
    """Resolve one repository-relative file below an explicit immutable checkout."""
    _require(isinstance(raw, str) and raw, f"{field} must be a repository-relative path")
    relative = Path(raw)
    _require(not relative.is_absolute() and ".." not in relative.parts,
             f"{field} escapes repository root: {raw}")
    supplied_root = Path(root)
    _require(supplied_root.is_absolute()
             and supplied_root.is_dir()
             and not any(candidate.is_symlink()
                         for candidate in (supplied_root, *supplied_root.parents)),
             f"{field} repository root is unsafe")
    root = supplied_root.resolve()
    current = root
    for component in relative.parts:
        current = current / component
        _require(current.exists() and not current.is_symlink(),
                 f"{field} does not exist or contains a symlink: {current}")
    candidate = current.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise InitialPilotError(f"{field} escapes repository root: {raw}") from exc
    _require(candidate.is_file(), f"{field} does not exist: {candidate}")
    return candidate


def _evidence_paths(config: Mapping[str, Any], contract: Mapping[str, Any], *,
                    source_repo_root: Path | None = None) -> dict[str, Path]:
    cutoff = _cutoff(config, str(contract["source_cutoff_id"]))
    manifest = core.validate_verified_count_only_result(config, cutoff)
    _require(isinstance(manifest, Mapping), "verified count-only evidence is required")
    pointer = cutoff["verified_count_only_result"]
    manifest_path = (
        core.resolve_repo_relative_file_no_symlink(
            pointer["manifest_path"], "initial pilot source manifest")
        if source_repo_root is None
        else _repo_file_at(source_repo_root, pointer["manifest_path"],
                           "initial pilot source manifest")
    )
    root = manifest_path.parent
    artifacts = manifest["result_artifacts"]
    paths = {
        "manifest": manifest_path,
        "yaml": core.resolve_evidence_relative_file(
            root, artifacts["phono3py_disp_yaml_path"], "initial pilot source YAML"),
        "preflight_inventory": core.resolve_evidence_relative_file(
            root, artifacts["preflight_inventory_path"], "initial pilot source inventory"),
        "preflight_result": core.resolve_evidence_relative_file(
            root, artifacts["preflight_result_path"], "initial pilot source result"),
        "accepted_unitcell": core.resolve_evidence_relative_file(
            root, "relax/final/unitcell.in", "initial pilot archived accepted unitcell"),
        "accepted_gate": core.resolve_evidence_relative_file(
            root, "relax/final/gate.json", "initial pilot archived accepted gate"),
        "accepted_provenance": core.resolve_evidence_relative_file(
            root, "relax/final/provenance.json", "initial pilot archived accepted provenance"),
        "archived_run_manifest": core.resolve_evidence_relative_file(
            root, "run_manifest.json", "initial pilot archived run manifest"),
        "generated_input_checksums": core.resolve_evidence_relative_file(
            root, manifest["generated_inputs"]["sha256sums_path"],
            "initial pilot generated-input checksums"),
    }
    paths["candidate_supercell"] = paths["yaml"].parent / "supercell.in"
    expected = {
        "manifest": pointer["manifest_sha256"],
        "yaml": pointer["phono3py_disp_yaml_sha256"],
        "preflight_inventory": pointer["preflight_inventory_sha256"],
        "preflight_result": pointer["preflight_result_sha256"],
        "accepted_unitcell": manifest["provenance"]["accepted_unitcell_sha256"],
        "accepted_gate": core.sha256_path(paths["accepted_gate"]),
        "accepted_provenance": core.sha256_path(paths["accepted_provenance"]),
        "archived_run_manifest": manifest["provenance"]["run_manifest_sha256"],
        "generated_input_checksums": manifest["generated_inputs"]["sha256sums_sha256"],
        "candidate_supercell": core.sha256_path(paths["candidate_supercell"]),
    }
    for name, path in paths.items():
        _match(path, expected[name], f"archived {name}")
    _require(manifest["scope_gates"]["force_pilot_authorized"] is False
             and manifest["scope_gates"]["production_fc3_eligible"] is False,
             "archived manifest authorization gates changed")
    return paths


def validate_released_candidate_files(release: Mapping[str, Any],
                                      candidate_dir: str | Path) -> None:
    """Bind the live/copy source candidate to all 787 archived input checksums."""
    candidate = Path(candidate_dir).resolve()
    source = release["source"]
    checksum_path = Path(source["generated_input_checksums_path"])
    _match(checksum_path, source["generated_input_checksums_sha256"],
           "released generated-input checksum list")
    rows: list[tuple[str, str]] = []
    for line in checksum_path.read_text().splitlines():
        parts = line.split(maxsplit=1)
        _require(len(parts) == 2, "invalid released generated-input checksum row")
        rows.append((_digest(parts[0], "generated input digest"), parts[1].strip()))
    _require(len(rows) == 787, "released generated-input checksum count changed")
    expected_names = {name for _, name in rows}
    actual_names = {path.name for path in candidate.glob("supercell-*.in")}
    _require(actual_names == expected_names,
             "candidate generated-input names differ from released inventory")
    for digest, name in rows:
        _require(Path(name).name == name, "generated input checksum name escapes candidate")
        _match(candidate / name, digest, f"released candidate input {name}")
    _match(candidate / "phono3py_disp.yaml", source["yaml_sha256"],
           "released candidate YAML")
    _match(candidate / "supercell.in", source["candidate_supercell_sha256"],
           "released candidate pristine supercell")
    _match(candidate / "unitcell.in", source["accepted_unitcell_sha256"],
           "released candidate unitcell")


def _validate_yaml_mapping(yaml_path: Path, unitcell_path: Path,
                           contract: Mapping[str, Any]) -> None:
    from pilot_dataset import minimum_image_bohr

    data = core.parse_phono3py_type1_yaml(yaml_path.read_text())
    _require(core.required(data, "physical_unit.length") == "au",
             "source YAML length unit must be au")
    _require(data["supercell_matrix"] == [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
             "source YAML supercell matrix changed")
    points = data["supercell"]["points"]
    _require(len(points) == 40, "source YAML must contain 40 supercell atoms")
    a, b = (int(value) for value in contract["atom_1_based"])
    _require([points[a-1]["symbol"], points[b-1]["symbol"]] == ["S", "S"],
             "source YAML cutoff-edge species/order changed")
    delta = [y-x for x, y in zip(points[a-1]["coordinates"], points[b-1]["coordinates"])]
    vector = minimum_image_bohr(delta, data["supercell"]["lattice"])
    distance = math.hypot(*vector)
    unit = [value/distance for value in vector]
    _require(_close(distance, contract["pair_distance_bohr"]),
             "source YAML cutoff-edge distance changed")
    _require(_vector_close(unit, contract["unit_vector_33_to_35"]),
             "source YAML cutoff-edge direction changed")
    groups = [group for first in data["displacement_pairs"]
              if first.get("atom") == a for group in first.get("paired_with", [])
              if group.get("atom") == b and group.get("included") is True
              and _close(group.get("pair_distance"), distance)]
    _require(bool(groups), "source YAML no longer contains the included atom-33/35 cutoff-edge pair")

    accepted = parse_qe_input(unitcell_path.read_text())
    yaml_cell = data["unit_cell"]["lattice"]
    accepted_bohr = [[value/core.BOHR_TO_ANGSTROM for value in row]
                     for row in accepted.cell_parameters]
    _require(len(yaml_cell) == 3 and all(_vector_close(x, y)
             for x, y in zip(yaml_cell, accepted_bohr)),
             "YAML unit lattice differs from archived accepted unitcell")
    yaml_points = data["unit_cell"]["points"]
    _require(len(yaml_points) == accepted.nat, "YAML unit-cell atom count changed")
    for point, atom in zip(yaml_points, accepted.atomic_positions):
        mapped = minimum_image_bohr(
            [x-y for x, y in zip(point["coordinates"], atom.coordinates)], yaml_cell)
        _require(point["symbol"] == atom.label and math.hypot(*mapped) <= ABS_TOL_BOHR,
                 "YAML unit-cell atom order/mapping differs from accepted unitcell")


def expected_probe_spec(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the one signed geometry specification authorized by the contract."""
    unit = list(contract["unit_vector_33_to_35"])
    minus = [-value for value in unit]
    return {
        "schema_version": 1,
        "rationale": "SrZrS3 exact-six initial timing/noise and resolvable incremental-force pilot only",
        "supercell_id": contract["source_supercell_id"],
        "cutoff_id": contract["source_cutoff_id"],
        "amplitude_angstrom": contract["amplitude_angstrom"],
        "amplitude_bohr": contract["amplitude_bohr"],
        "singles": [{"id": "sr-s33-plus-u", "atom": 33,
                     "direction_cartesian": unit}],
        "mixed": [{"id": "sr-s33-plus-u-s35-minus-u",
                   "first": {"atom": 33, "direction_cartesian": unit},
                   "second": {"atom": 35, "direction_cartesian": minus},
                   "pair_shell_id": "S-S"}],
        "coverage": {
            "site_ids": {"site-00001": "not_covered", "site-00005": "not_covered",
                         "site-00009": "not_covered", "site-00013": "not_covered",
                         "site-00017": "covered"},
            "pair_shell_ids": {"Sr-S": "not_covered", "Zr-S": "not_covered",
                               "S-S": "covered"},
        },
    }


def expected_force_spec(contract: Mapping[str, Any]) -> dict[str, Any]:
    settings = contract["settings"]
    return {
        "rationale": "SrZrS3 exact-six initial timing/noise and resolvable incremental-force pilot only",
        "supercell_id": contract["source_supercell_id"],
        "cutoff_id": contract["source_cutoff_id"],
        "amplitude_angstrom": contract["amplitude_angstrom"],
        "amplitude_bohr": contract["amplitude_bohr"],
        "ecutwfc_Ry": settings["ecutwfc_Ry"],
        "ecutrho_Ry": settings["ecutrho_Ry"],
        "conv_thr_Ry": settings["conv_thr_Ry"],
        "kmesh": settings["kmesh"],
        "kshift": settings["kshift"],
        "displacement_ids": [1, 3],
        "duplicate_displacement_ids": [1, 3],
        "pristine_repetitions": 2,
    }


def _run_binding(config: Mapping[str, Any], config_path: Path, run_dir: Path) -> dict[str, Any]:
    run_manifest_path = run_dir / core.RUN_MANIFEST
    gate_path = run_dir / "relax" / "final" / "gate.json"
    provenance_path = run_dir / "relax" / "final" / "provenance.json"
    unitcell_path = run_dir / "relax" / "final" / "unitcell.in"
    for path in (run_manifest_path, gate_path, provenance_path, unitcell_path):
        _require(path.is_file(), f"initial pilot run evidence is missing: {path}")
    run_manifest = core.load_json(run_manifest_path)
    gate = core.load_json(gate_path)
    _require(run_manifest.get("schema_version") == 2
             and run_manifest.get("material") == config["material"]["formula"],
             "initial pilot run manifest mismatch")
    _require(run_manifest.get("preflight_policy_sha256") == core.policy_sha256(config, "preflight"),
             "initial pilot run preflight policy mismatch")
    _require(isinstance(run_manifest.get("accepted_structure_import"), Mapping),
             "initial pilot requires a fully replayable accepted-structure import")
    from accepted_structure_import import verify_imported_acceptance
    imported = verify_imported_acceptance(config_path, run_dir)
    _require(imported.get("healthy") is True
             and imported.get("kind") == "imported_accepted_structure"
             and imported.get("run_dir") == str(run_dir)
             and imported.get("preflight_policy_sha256") == core.policy_sha256(config, "preflight"),
             "accepted-structure import replay did not establish this RUN_DIR lineage")
    _require(gate.get("pass") is True, "accepted tight-relax gate is required")
    _match(unitcell_path, gate.get("final_unitcell_sha256"), "accepted run unitcell")
    _require(imported.get("accepted_unitcell_sha256") == core.sha256_path(unitcell_path),
             "accepted-structure import replay differs from RUN_DIR unitcell")
    return {
        "config_path": str(config_path),
        "config_sha256": core.sha256_path(config_path),
        "run_dir": str(run_dir),
        "run_manifest_path": str(run_manifest_path),
        "run_manifest_sha256": core.sha256_path(run_manifest_path),
        "accepted_gate_path": str(gate_path),
        "accepted_gate_sha256": core.sha256_path(gate_path),
        "accepted_provenance_path": str(provenance_path),
        "accepted_provenance_sha256": core.sha256_path(provenance_path),
        "accepted_unitcell_path": str(unitcell_path),
        "accepted_unitcell_sha256": core.sha256_path(unitcell_path),
        "accepted_structure_import_receipt_sha256": imported["receipt_sha256"],
        "preflight_policy_sha256": core.policy_sha256(config, "preflight"),
    }


def _stable_release(config_path: Path, run_dir: Path, *,
                    workflow_dir: Path | None = None,
                    source_repo_root: Path | None = None) -> dict[str, Any]:
    config, _ = core.validate_config(config_path)
    contract = _contract(config)
    _require(config["material"]["formula"] == "SrZrS3", "release is material-specific")
    paths = _evidence_paths(config, contract, source_repo_root=source_repo_root)
    _validate_yaml_mapping(paths["yaml"], paths["accepted_unitcell"], contract)
    archived_manifest = core.load_json(paths["manifest"])
    source = {f"{name}_path": str(path) for name, path in paths.items()}
    source.update({f"{name}_sha256": core.sha256_path(path) for name, path in paths.items()})
    source.update({
        "archived_config_sha256": archived_manifest["provenance"]["config_sha256"],
        "archived_preflight_policy_sha256": archived_manifest["provenance"]["preflight_policy_sha256"],
        "archived_workflow_sha256": dict(archived_manifest["provenance"]["workflow_sha256"]),
    })
    run = _run_binding(config, config_path, run_dir)
    _require(run["accepted_unitcell_sha256"] == source["accepted_unitcell_sha256"],
             "pilot RUN_DIR accepted structure differs from archived count-only source")
    workflow_root = (Path(__file__).resolve().parent if workflow_dir is None
                     else Path(workflow_dir).resolve())
    workflow = {str(workflow_root / name): core.sha256_path(workflow_root / name)
                for name in WORKFLOW_FILES}
    identity = core.canonical_sha256({"contract": contract, "source": source,
                                      "run": run, "workflow_sha256": workflow})
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "initial_pilot_release",
        "material": "SrZrS3",
        "scope": {"mode": "pilot", "phase": "initial", "task_count": 6,
                  "task_displacement_ids": EXPECTED_TASK_IDS,
                  "validation_authorized": False, "production_authorized": False},
        "contract": dict(contract),
        "probe_spec": expected_probe_spec(contract),
        "force_pilot_spec": expected_force_spec(contract),
        "source": source,
        "run_binding": run,
        "workflow_sha256": workflow,
        "consumption_identity": identity,
        "limitations": [
            "Authorizes one exact-six initial pilot consumption only.",
            "Tests only timing, repeatability, and resolvable incremental force response.",
            "Does not validate D2, FC3, amplitude, cutoff, kappa, or production.",
        ],
    }


def prepare_initial_pilot_release(config_path: str | Path, run_dir: str | Path,
                                  output_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    run_dir = core.safe_run_dir(Path(run_dir))
    output = core.strict_run_descendant(
        run_dir, Path(output_path), "pilot release", require_exists=False
    )
    stable = _stable_release(config_path, run_dir)
    release = {**stable, "created_utc": core.utc_now()}
    core.write_json_immutable(output, release)
    return {"healthy": True, "release": str(output),
            "release_sha256": core.sha256_path(output),
            "consumption_identity": release["consumption_identity"]}


def replay_initial_pilot_release(release_path: str | Path, *, config_path: str | Path,
                                 run_dir: str | Path,
                                 expected_release_sha256: str,
                                 historical_workflow_dir: str | Path | None = None,
                                 historical_source_repo_root: str | Path | None = None,
                                 ) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    run_dir = core.safe_run_dir(Path(run_dir))
    release_path = core.strict_run_descendant(
        run_dir, Path(release_path), "pilot release"
    )
    _match(release_path, expected_release_sha256, "pilot release")
    release = core.load_json(release_path)
    stable = _stable_release(
        config_path, run_dir,
        workflow_dir=(Path(historical_workflow_dir)
                      if historical_workflow_dir is not None else None),
        source_repo_root=(Path(historical_source_repo_root)
                          if historical_source_repo_root is not None else None),
    )
    _require(isinstance(release.get("created_utc"), str) and release["created_utc"],
             "pilot release creation time is missing")
    for key, value in stable.items():
        _require(release.get(key) == value, f"pilot release replay mismatch: {key}")
    return release


def validate_release_use(release: Mapping[str, Any], *, probe_spec: Mapping[str, Any] | None = None,
                         force_spec: Mapping[str, Any] | None = None,
                         resource_request: Mapping[str, Any] | None = None) -> None:
    _require(release["scope"] == {"mode": "pilot", "phase": "initial", "task_count": 6,
             "task_displacement_ids": EXPECTED_TASK_IDS,
             "validation_authorized": False, "production_authorized": False},
             "pilot release scope changed")
    if probe_spec is not None:
        _require(dict(probe_spec) == release["probe_spec"],
                 "probe specification differs from exact-six release")
    if force_spec is not None:
        _require(dict(force_spec) == release["force_pilot_spec"],
                 "force pilot specification differs from exact-six release")
    if resource_request is not None:
        expected = release["contract"]["resources"]
        _require(set(resource_request) <= {"phase", "mpi_ranks", "walltime_hours",
                                          "max_concurrency", "timing_evidence",
                                          "usage_evidence"},
                 "initial pilot resource request contains an unauthorized field")
        _require(resource_request.get("phase") == "initial"
                 and resource_request.get("mpi_ranks") == expected["mpi_ranks"]
                 and resource_request.get("walltime_hours") == expected["walltime_hours"]
                 and resource_request.get("max_concurrency") == expected["max_concurrency"],
                 "resource request differs from exact-six release")
        _require(not resource_request.get("timing_evidence")
                 and not resource_request.get("usage_evidence"),
                 "initial exact-six release cannot consume prior timing/usage evidence")


def consumption_path(run_dir: str | Path, release: Mapping[str, Any]) -> Path:
    return Path(run_dir).resolve() / ".initial_pilot_releases" / (
        str(release["consumption_identity"]) + ".json")


def claim_release_consumption(run_dir: str | Path, release_path: str | Path,
                              release_sha256: str, release: Mapping[str, Any],
                              dataset_dir: str | Path) -> Path:
    claim_path = consumption_path(run_dir, release)
    claims = claim_path.parent
    if claims.exists():
        _require(claims.is_dir() and not claims.is_symlink(),
                 "initial pilot consumption directory is unsafe")
    else:
        claims.mkdir()
        _require(claims.is_dir() and not claims.is_symlink(),
                 "initial pilot consumption directory creation is unsafe")
    _require(not os.path.lexists(claim_path), "initial pilot release was already consumed")
    core.write_json_immutable(claim_path, {
        "schema_version": 1,
        "stage": "initial_pilot_release_consumption",
        "consumption_identity": release["consumption_identity"],
        "release_path": str(Path(release_path).resolve()),
        "release_sha256": release_sha256,
        "dataset_dir": str(Path(dataset_dir).resolve()),
        "created_utc": core.utc_now(),
    })
    return claim_path


def _rms_difference(left: Sequence[Sequence[float]],
                    right: Sequence[Sequence[float]]) -> float:
    _require(len(left) == len(right) == 40, "initial pilot force arrays must have 40 atoms")
    values = [float(x)-float(y) for a, b in zip(left, right) for x, y in zip(a, b)]
    _require(len(values) == 120 and all(math.isfinite(x) for x in values),
             "initial pilot requires 120 finite raw force components")
    return math.sqrt(sum(value*value for value in values) / 120)


def _mean_pair(left: Sequence[Sequence[float]],
               right: Sequence[Sequence[float]]) -> list[list[float]]:
    _require(len(left) == len(right) == 40, "initial pilot force arrays must have 40 atoms")
    return [[(float(x)+float(y))/2 for x, y in zip(a, b)] for a, b in zip(left, right)]


def evaluate_initial_forces(forces: Sequence[Sequence[Sequence[float]]],
                            acceptance: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate six ordered force arrays; RMS uses 120 raw components, no centering."""
    _require(len(forces) == 6, "initial pilot requires exactly six force arrays")
    p1, p2, s1, d1, s2, d2 = forces
    d_p, d_s, d_d = (_rms_difference(p1, p2), _rms_difference(s1, s2),
                      _rms_difference(d1, d2))
    pbar, sbar, dbar = _mean_pair(p1, p2), _mean_pair(s1, s2), _mean_pair(d1, d2)
    i_sp, i_ds = _rms_difference(sbar, pbar), _rms_difference(dbar, sbar)
    epsilon = float(acceptance["epsilon_Ry_per_bohr"])
    factor = float(acceptance["minimum_incremental_signal_to_propagated_noise"])
    maximum = float(acceptance["maximum_each_duplicate_rms_Ry_per_bohr"])
    eta_sp = math.hypot(max(d_s, epsilon), max(d_p, epsilon))
    eta_ds = math.hypot(max(d_d, epsilon), max(d_s, epsilon))
    duplicate_pass = all(value <= maximum for value in (d_p, d_s, d_d))
    def meets(signal: float, propagated: float) -> bool:
        threshold = factor * propagated
        return signal > epsilon and (signal >= threshold or math.isclose(
            signal, threshold, rel_tol=1e-12, abs_tol=0.0))

    signal_sp_pass = meets(i_sp, eta_sp)
    signal_ds_pass = meets(i_ds, eta_ds)
    if not duplicate_pass:
        status = "noise_gate_failed"
    elif not (signal_sp_pass and signal_ds_pass):
        status = "below_resolution"
    else:
        status = "accepted_initial_timing_noise"
    return {
        "duplicate_rms_Ry_per_bohr": {"pristine": d_p, "single": d_s, "double": d_d},
        "incremental_signal_rms_Ry_per_bohr": {"single_minus_pristine": i_sp,
                                                "double_minus_single": i_ds},
        "propagated_noise_Ry_per_bohr": {"single_minus_pristine": eta_sp,
                                          "double_minus_single": eta_ds},
        "duplicate_noise_pass": duplicate_pass,
        "incremental_signal_pass": {"single_minus_pristine": signal_sp_pass,
                                     "double_minus_single": signal_ds_pass},
        "status": status,
        "pass": status == "accepted_initial_timing_noise",
    }


def _scheduler_success(entry: Mapping[str, Any], job_id: str, task_id: int,
                       raw_job_id: str) -> bool:
    expected = f"{job_id}_{task_id}"
    allocations = []
    for row in entry.get("scheduler_records", []):
        state = str(row.get("State", "")).strip().upper().split()
        if (row.get("JobID") == expected and state and state[0].rstrip("+") == "COMPLETED"
                and row.get("ExitCode") == "0:0"
                and row.get("JobIDRaw") == raw_job_id):
            allocations.append(row)
    return len(allocations) == 1


def audit_actual_initial_input(input_path: str | Path, expected_text: str,
                               task: Mapping[str, Any],
                               artifact_manifest: Mapping[str, Any], *,
                               prior_settings_sha256: str | None = None,
                               prior_atom_order: Sequence[str] | None = None
                               ) -> tuple[str, list[str]]:
    """Reparse one real scf.in and bind physics, geometry, order, and settings hash."""
    from postprocess_backend import qe_settings

    path = Path(input_path)
    text = path.read_text()
    _require(text == expected_text and core.sha256_path(path) == task.get("input_sha256"),
             "actual QE input geometry/settings differ from released dataset")
    parsed = parse_qe_input(text)
    actual_settings = qe_settings(text)
    conv = str(actual_settings.get("electrons.conv_thr", "")).replace("d", "e")
    try:
        conv_value = float(conv)
    except ValueError as exc:
        raise InitialPilotError("actual QE input has invalid conv_thr") from exc
    _require(parsed.nat == 40 and parsed.ecutwfc_ry == 80
             and parsed.ecutrho_ry == 640 and conv_value == 1e-10
             and actual_settings.get("kmesh") == [3, 3, 3]
             and actual_settings.get("kshift") == [0, 0, 0]
             and actual_settings.get("system.nosym") == ".true."
             and actual_settings.get("system.noinv") == ".true.",
             "actual QE settings differ from exact-six release")
    settings_sha = core.canonical_sha256(actual_settings)
    order = list(actual_settings["atom_order"])
    _require(artifact_manifest.get("settings_sha256") == settings_sha,
             "actual QE settings hash mismatch")
    _require(order == task.get("atom_labels"), "actual QE atom order differs from task")
    if prior_settings_sha256 is not None:
        _require(settings_sha == prior_settings_sha256,
                 "actual QE settings differ across exact-six batch")
    if prior_atom_order is not None:
        _require(order == list(prior_atom_order),
                 "actual QE atom order differs across exact-six batch")
    return settings_sha, order


def _historical_workflow(root: str | Path, expected_digest: str) -> tuple[Path, dict[str, str]]:
    """Hash the only old-checkout files a failed-collector replay may use."""
    supplied = Path(root)
    _require(supplied.is_absolute() and supplied.is_dir()
             and not any(candidate.is_symlink() for candidate in (supplied, *supplied.parents)),
             "historical workflow root is unsafe")
    folder = supplied.resolve()
    files = {name: folder / name for name in HISTORICAL_WORKFLOW_FILES}
    _require(all(path.is_file() and not path.is_symlink() for path in files.values()),
             "historical workflow file is missing or symlinked")
    hashes = {name: core.sha256_path(path) for name, path in files.items()}
    _require(core.canonical_sha256(hashes) == _digest(expected_digest, "historical workflow"),
             "historical workflow hash mismatch")
    return folder, hashes


def recover_failed_initial_pilot_collector(
        config_path: str | Path, run_dir: str | Path, *,
        failed_collector_attempt: str | Path,
        primary_attempt_id: str, primary_job_id: str,
        force_manifest_path: str | Path, force_manifest_sha256: str,
        task_map_path: str | Path, task_map_sha256: str,
        primary_request_sha256: str, primary_result_sha256: str,
        primary_stage_script_sha256: str,
        accounting_sha256: str, accounting_status_sha256: str,
        failed_stdout_sha256: str, historical_workflow_dir: str | Path,
        historical_workflow_sha256: str, output_path: str | Path) -> dict[str, Any]:
    """Recover exactly one known failed Sr exact-six collector offline.

    This is deliberately not a generic collection bypass: it accepts only the
    historical exporter truncation signature, replays the original afterany
    records, and reconstructs all six logical receipts from the already-written
    task files and accounting records.  It never says the Slurm collector ran
    successfully.
    """
    config_path = Path(config_path).resolve()
    run_dir = core.safe_run_dir(Path(run_dir))
    failed = core.strict_run_descendant(
        run_dir, Path(failed_collector_attempt), "failed initial collector")
    _require(failed.parent == run_dir / "slurm_attempts" / "collect"
             and failed.is_dir(), "failed collector is not an exact collect attempt")
    core.reject_symlinks_below(run_dir, failed, "failed initial collector")
    context, context_errors = core._read_context_tsv(failed / "context.tsv")
    exit_code, exit_errors = core._read_exit_code(failed)
    finished = failed / "finished_utc.txt"
    stdout = failed / "stdout.log"
    stderr = failed / "stderr.log"
    _require(not context_errors and not exit_errors and exit_code == 2
             and context.get("stage") == "collect"
             and context.get("attempt_id") == failed.name
             and isinstance(context.get("slurm_job_id"), str)
             and context["slurm_job_id"].isdigit()
             and context.get("primary_stage") == "force"
             and context.get("primary_attempt_id") == primary_attempt_id
             and context.get("primary_job_id") == primary_job_id
             and context.get("primary_request_sha256") == primary_request_sha256
             and context.get("primary_result_sha256") == primary_result_sha256
             and context.get("primary_stage_script_sha256") == primary_stage_script_sha256
             and context.get("config") == str(config_path)
             and context.get("config_sha256") == core.sha256_path(config_path)
             and (not context.get("git_commit")
                  or re.fullmatch(r"[0-9a-f]{40}", context["git_commit"]) is not None),
             "failed collector context/exit identity is not the known failure")
    _require(finished.is_file() and re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n?", finished.read_text()),
             "failed collector finished timestamp is invalid")
    _match(stdout, failed_stdout_sha256, "failed collector stdout")
    _require(stderr.is_file() and stderr.read_bytes() == b"",
             "failed collector stderr must be empty")
    try:
        stdout_payload = json.loads(stdout.read_text())
    except (OSError, ValueError) as exc:
        raise InitialPilotError("failed collector stdout is not JSON") from exc
    _require(stdout_payload == {
        "command": "collect", "error": FAILED_COLLECTOR_IDENTITY_ERROR,
        "healthy": False,
    }, "failed collector stdout is not the exact known task-selector identity mismatch")
    accounting = core.strict_run_descendant(
        run_dir, failed / "primary_sacct.psv", "failed collector accounting")
    accounting_status = core.strict_run_descendant(
        run_dir, failed / "primary_sacct_exit_code.txt",
        "failed collector accounting status")
    _match(accounting, accounting_sha256, "failed collector accounting")
    _match(accounting_status, accounting_status_sha256,
           "failed collector accounting status")
    force_manifest = core.strict_run_descendant(
        run_dir, Path(force_manifest_path), "initial pilot force manifest")
    task_map = core.strict_run_descendant(
        run_dir, Path(task_map_path), "initial pilot task map")
    _match(force_manifest, force_manifest_sha256, "initial pilot force manifest")
    _match(task_map, task_map_sha256, "initial pilot task map")
    historical_root, historical_hashes = _historical_workflow(
        historical_workflow_dir, historical_workflow_sha256)
    config, _ = core.validate_config(config_path)
    records, errors, metadata = core._read_sacct_records(
        accounting, accounting_status, fields=core.FORCE_SACCT_FIELDS)
    report = core._collect_force_batch(
        config=config, config_path=config_path, run_dir=run_dir,
        current_attempt=failed, primary_attempt_id=primary_attempt_id,
        primary_job_id=primary_job_id, force_manifest_path=force_manifest,
        task_map_path=task_map, expected_force_manifest_sha256=force_manifest_sha256,
        expected_task_map_sha256=task_map_sha256,
        submitted_task_ids=list(range(6)),
        expected_primary_request_sha256=primary_request_sha256,
        expected_primary_result_sha256=primary_result_sha256,
        expected_primary_stage_script_sha256=primary_stage_script_sha256,
        accounting_records=records, accounting_errors=errors,
        accounting_metadata=metadata, historical_workflow_dir=historical_root)
    _require(report.get("expected_task_count") == 6
             and report.get("submitted_task_ids") == list(range(6))
             and report.get("accepted_success_count") == 6
             and report.get("upstream_failure_count") == 0
             and report.get("unfinished_or_invalid_count") == 0
             and report.get("collection_integrity_complete") is True
             and report.get("batch_execution_complete") is True
             and len(report.get("entries", [])) == 6,
             "offline recovery did not reconstruct an exact complete six-task collection")
    _require(all(isinstance(entry, Mapping) and entry.get("task_id") == index
                 and entry.get("outcome") == "accepted_success"
                 and isinstance(entry.get("evidence"), Mapping)
                 for index, entry in enumerate(report["entries"])),
             "offline recovery collection lacks one of the six audited task artifacts")
    output = core.strict_run_descendant(run_dir, Path(output_path),
                                        "initial collector recovery", require_exists=False)
    artifact = {
        "schema_version": 1,
        "kind": "initial_pilot_failed_collector_offline_recovery",
        "material": "SrZrS3",
        "original_collector_failed": True,
        "slurm_collector_succeeded": False,
        "failed_collector": {
            "attempt": str(failed), "context": context, "exit_code": 2,
            "finished_utc": finished.read_text().strip(),
            "evidence": {
                name: {"sha256": core.sha256_path(path), "bytes": path.stat().st_size}
                for name, path in (("context.tsv", failed / "context.tsv"),
                                   ("exit_code.txt", failed / "exit_code.txt"),
                                   ("finished_utc.txt", finished),
                                   ("stdout.log", stdout), ("stderr.log", stderr))
            },
            "known_identity_error": FAILED_COLLECTOR_IDENTITY_ERROR,
        },
        "trusted_inputs": {
            "primary_sacct": {"path": str(accounting), "sha256": accounting_sha256},
            "primary_sacct_status": {"path": str(accounting_status), "sha256": accounting_status_sha256},
            "force_manifest": {"path": str(force_manifest), "sha256": force_manifest_sha256},
            "task_map": {"path": str(task_map), "sha256": task_map_sha256},
            "primary_request_sha256": primary_request_sha256,
            "primary_result_sha256": primary_result_sha256,
            "primary_stage_script_sha256": primary_stage_script_sha256,
            "historical_workflow": {"path": str(historical_root),
                                    "sha256": historical_workflow_sha256,
                                    "files_sha256": historical_hashes},
        },
        "reconstructed_collection": report,
        "reconstructed_collection_sha256": core.canonical_sha256(report),
        "limitations": [
            "The original Slurm afterany collector failed with exit 2 and is preserved as failed evidence.",
            "This offline replay reconstructs collection evidence only; it is not a Slurm collector success.",
            "The result remains initial timing/noise/repeatability evidence only and cannot authorize FC2, FC3, or kappa work.",
        ],
        "created_utc": core.utc_now(),
    }
    core.write_json_immutable(output, artifact)
    return {"healthy": True, "recovery": str(output),
            "recovery_sha256": core.sha256_path(output),
            "original_collector_failed": True,
            "slurm_collector_succeeded": False}


def _finalize_payload(config_path: Path, run_dir: Path, release_path: Path,
                      release_sha256: str, force_manifest_path: Path,
                      collection_path: Path, collection_sha256: str,
                      retry_collection_path: Path | None = None,
                      retry_collection_sha256: str | None = None) -> dict[str, Any]:
    import force_backend as fb
    from postprocess_backend import load_force_artifact

    release_path = core.strict_run_descendant(run_dir, release_path,
                                               "initial pilot release")
    force_manifest_path = core.strict_run_descendant(
        run_dir, force_manifest_path, "initial pilot force manifest")
    collection_path = core.strict_run_descendant(
        run_dir, collection_path, "initial pilot collection")
    config, _ = core.validate_config(config_path)
    _match(collection_path, collection_sha256, "initial pilot collection")
    collection_document = core.load_json(collection_path)
    preliminary_historical_workflow_dir = None
    if collection_document.get("kind") == "initial_pilot_failed_collector_offline_recovery":
        preliminary_trusted = collection_document.get("trusted_inputs")
        _require(isinstance(preliminary_trusted, Mapping),
                 "offline recovery trusted input set is missing")
        preliminary_reference = preliminary_trusted.get("historical_workflow")
        _require(isinstance(preliminary_reference, Mapping)
                 and set(preliminary_reference) == {"path", "sha256", "files_sha256"},
                 "offline recovery historical workflow reference is invalid")
        preliminary_historical_workflow_dir, preliminary_hashes = _historical_workflow(
            preliminary_reference["path"], preliminary_reference["sha256"])
        _require(preliminary_reference["files_sha256"] == preliminary_hashes,
                 "offline recovery historical workflow file set is altered")
    release = replay_initial_pilot_release(
        release_path, config_path=config_path, run_dir=run_dir,
        expected_release_sha256=release_sha256,
        historical_workflow_dir=preliminary_historical_workflow_dir,
        historical_source_repo_root=(
            preliminary_historical_workflow_dir.parents[2]
            if preliminary_historical_workflow_dir is not None else None),
    )
    recovery = None
    historical_workflow_dir = preliminary_historical_workflow_dir
    if collection_document.get("kind") == "initial_pilot_failed_collector_offline_recovery":
        recovery = collection_document
        _require(
            recovery.get("schema_version") == 1
            and recovery.get("material") == "SrZrS3"
            and recovery.get("original_collector_failed") is True
            and recovery.get("slurm_collector_succeeded") is False,
            "offline recovery does not preserve the failed collector limitation",
        )
        failed = recovery.get("failed_collector")
        _require(isinstance(failed, Mapping) and failed.get("exit_code") == 2
                 and failed.get("known_identity_error") == FAILED_COLLECTOR_IDENTITY_ERROR
                 and isinstance(failed.get("finished_utc"), str)
                 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", failed["finished_utc"]),
                 "offline recovery failed-collector identity is invalid")
        failed_attempt = core.strict_run_descendant(
            run_dir, Path(str(failed.get("attempt", ""))), "offline recovery failed collector")
        _require(failed_attempt.parent == run_dir / "slurm_attempts" / "collect",
                 "offline recovery failed collector path is not exact")
        core.reject_symlinks_below(run_dir, failed_attempt,
                                   "offline recovery failed collector")
        failed_evidence = failed.get("evidence")
        _require(isinstance(failed_evidence, Mapping),
                 "offline recovery failed collector evidence is missing")
        for name in ("context.tsv", "exit_code.txt", "finished_utc.txt", "stdout.log", "stderr.log"):
            reference = failed_evidence.get(name)
            path = core.strict_run_descendant(run_dir, failed_attempt / name,
                                              f"offline recovery failed collector {name}")
            _require(isinstance(reference, Mapping)
                     and reference.get("sha256") == core.sha256_path(path)
                     and reference.get("bytes") == path.stat().st_size,
                     "offline recovery failed collector evidence is altered")
        raw_context, raw_context_errors = core._read_context_tsv(failed_attempt / "context.tsv")
        raw_exit, raw_exit_errors = core._read_exit_code(failed_attempt)
        _require(not raw_context_errors and not raw_exit_errors and raw_context == failed["context"]
                 and raw_exit == 2 and (failed_attempt / "stderr.log").read_bytes() == b"",
                 "offline recovery failed collector raw context/exit/stderr is altered")
        _require((failed_attempt / "finished_utc.txt").read_text().strip()
                 == failed["finished_utc"],
                 "offline recovery failed collector timestamp is altered")
        try:
            raw_stdout = json.loads((failed_attempt / "stdout.log").read_text())
        except (OSError, ValueError) as exc:
            raise InitialPilotError("offline recovery failed collector stdout is invalid") from exc
        _require(raw_stdout == {"command": "collect", "error": FAILED_COLLECTOR_IDENTITY_ERROR,
                                "healthy": False},
                 "offline recovery failed collector stdout is altered")
        trusted = recovery.get("trusted_inputs")
        _require(isinstance(trusted, Mapping), "offline recovery trusted input set is missing")
        for name in ("primary_sacct", "primary_sacct_status", "force_manifest", "task_map"):
            reference = trusted.get(name)
            _require(isinstance(reference, Mapping),
                     "offline recovery trusted input reference is invalid")
            path = core.strict_run_descendant(run_dir, Path(str(reference.get("path", ""))),
                                              f"offline recovery {name}")
            _match(path, reference.get("sha256"), f"offline recovery {name}")
        historical_reference = trusted.get("historical_workflow")
        _require(isinstance(historical_reference, Mapping)
                 and set(historical_reference) == {"path", "sha256", "files_sha256"},
                 "offline recovery historical workflow reference is invalid")
        historical_workflow_dir, historical_hashes = _historical_workflow(
            historical_reference["path"], historical_reference["sha256"])
        _require(historical_reference["files_sha256"] == historical_hashes,
                 "offline recovery historical workflow file set is altered")
        collection = recovery.get("reconstructed_collection")
        _require(isinstance(collection, Mapping)
                 and recovery.get("reconstructed_collection_sha256")
                     == core.canonical_sha256(collection),
                 "offline recovery reconstructed collection is altered")
        recovery_primary = collection.get("primary")
        _require(isinstance(recovery_primary, Mapping)
                 and raw_context.get("primary_stage") == "force"
                 and raw_context.get("primary_attempt_id") == recovery_primary.get("attempt_id")
                 and raw_context.get("primary_job_id") == recovery_primary.get("job_id")
                 and raw_context.get("primary_request_sha256")
                     == trusted.get("primary_request_sha256")
                 and raw_context.get("primary_result_sha256")
                     == trusted.get("primary_result_sha256")
                 and raw_context.get("primary_stage_script_sha256")
                     == trusted.get("primary_stage_script_sha256")
                 and raw_context.get("config") == str(config_path)
                 and raw_context.get("config_sha256") == core.sha256_path(config_path)
                 and (not raw_context.get("git_commit")
                      or re.fullmatch(r"[0-9a-f]{40}", raw_context["git_commit"]) is not None),
                 "offline recovery failed collector context is not bound to its primary chain")
    else:
        collection = collection_document
    _require(collection.get("schema_version") == 1 and collection.get("stage") == "collect"
             and collection.get("collection_kind") == "force_array_batch"
             and collection.get("material") == "SrZrS3"
             and collection.get("force_mode") == "pilot",
             "invalid initial pilot collection schema/scope")
    submitted_ids = collection.get("submitted_task_ids")
    _require(submitted_ids == list(range(6)),
             "initial pilot primary collection must cover logical tasks 0..5")
    retry_collection = None
    if retry_collection_path is not None or retry_collection_sha256 is not None:
        _require(retry_collection_path is not None and retry_collection_sha256 is not None,
                 "retry collection path and SHA256 must be supplied together")
        retry_collection_path = core.strict_run_descendant(
            run_dir, retry_collection_path, "initial pilot retry collection")
        _match(retry_collection_path, retry_collection_sha256,
               "initial pilot retry collection")
        retry_collection = core.load_json(retry_collection_path)
    _require(collection.get("expected_task_count") == 6
             and collection.get("accepted_success_count", 0)
                 + collection.get("upstream_failure_count", 0) == 6
             and collection.get("unfinished_or_invalid_count") == 0
             and collection.get("collection_integrity_complete") is True
             and (collection.get("batch_execution_complete") is True
                  or retry_collection is not None)
             and collection.get("global_errors") == []
             and collection.get("scientific_gate_published") is False
             and collection.get("production_dataset_complete") is False
             and collection.get("scientific_dataset_incomplete") is True
             and collection.get("eligible_for_force_constant_construction") is False,
             "initial pilot collection is incomplete or invalid")
    primary = collection.get("primary")
    _require(isinstance(primary, Mapping), "initial pilot collection primary is missing")
    _require(primary.get("stage") == "force"
             and isinstance(primary.get("attempt_id"), str) and primary["attempt_id"]
             and isinstance(primary.get("job_id"), str) and primary["job_id"].isdigit(),
             "initial pilot collection primary identity is invalid")
    attempt_root = core.strict_run_descendant(
        run_dir, Path(str(primary.get("attempt_root", ""))),
        "initial pilot primary attempt root", require_exists=False)
    collector_attempt = core.strict_run_descendant(
        run_dir, Path(str(collection.get("collector_attempt", ""))),
        "initial pilot collector attempt")
    if attempt_root.is_dir():
        core.reject_symlinks_below(run_dir, attempt_root,
                                   "initial pilot primary attempt root")
    core.reject_symlinks_below(run_dir, collector_attempt,
                               "initial pilot collector attempt")
    records = primary.get("submission_records")
    _require(isinstance(records, Mapping),
             "initial pilot collection lacks submit.py afterany records")
    request_ref = records.get("primary_request")
    result_ref = records.get("primary_result")
    _require(isinstance(request_ref, Mapping) and isinstance(result_ref, Mapping),
             "initial pilot submission record references are incomplete")
    request_path = core.strict_run_descendant(
        run_dir, Path(str(request_ref.get("path", ""))),
        "initial pilot primary submission request")
    request = core.load_json(request_path)
    replayed_records = core._force_submission_binding(
        config_path=config_path, run_dir=run_dir, collector_attempt=collector_attempt,
        primary_attempt_id=primary["attempt_id"], primary_job_id=primary["job_id"],
        force_manifest_sha256=primary.get("force_manifest_sha256"),
        task_map_sha256=primary.get("task_map_sha256"),
        submitted_task_ids=submitted_ids,
        expected_primary_request_sha256=request_ref.get("sha256"),
        expected_primary_result_sha256=result_ref.get("sha256"),
        expected_primary_stage_script_sha256=request.get("stage_script_sha256"),
        require_held_primary=True,
        historical_workflow_dir=historical_workflow_dir,
    )
    _require(replayed_records == records,
             "initial pilot submission record replay differs from collection")
    _match(force_manifest_path, primary.get("force_manifest_sha256"), "force manifest")
    _require(Path(str(primary.get("force_manifest", ""))).resolve() == force_manifest_path,
             "collection force manifest path mismatch")
    _require(primary.get("submitted_force_manifest_sha256") == primary.get("force_manifest_sha256")
             and primary.get("submitted_task_map_sha256") == primary.get("task_map_sha256"),
             "collection submission hashes differ from collected force identity")
    manifest = core.load_json(force_manifest_path)
    task_map_path = core.strict_run_descendant(
        run_dir, Path(str(primary.get("task_map", ""))),
        "initial pilot task map")
    _require(task_map_path.parent == force_manifest_path.parent
             and task_map_path.name == "task_map.tsv",
             "collection task map is not adjacent to force manifest")
    _match(task_map_path, primary.get("task_map_sha256"), "initial pilot task map")
    _require(manifest.get("task_map_sha256") == primary.get("task_map_sha256"),
             "force manifest and collection task-map hashes differ")
    binding = manifest.get("initial_pilot_release")
    _require(isinstance(binding, Mapping)
             and Path(str(binding.get("path", ""))).resolve() == release_path
             and binding.get("sha256") == release_sha256
             and binding.get("consumption_identity") == release["consumption_identity"],
             "force manifest does not bind the initial pilot release")
    _require(manifest.get("schema_version") == 1 and manifest.get("stage") == "force"
             and manifest.get("mode") == "pilot" and manifest.get("material") == "SrZrS3",
             "force manifest scope differs from released initial pilot")
    _require(manifest.get("backend_sha256") == core.sha256_path(Path(fb.__file__))
             and manifest.get("selection_validation") is None
             and manifest.get("selection_evidence_sha256") == {},
             "force manifest backend or selection namespace is invalid")
    workflow = manifest.get("workflow_sha256")
    _require(isinstance(workflow, Mapping) and workflow,
             "force manifest workflow inventory is missing")
    release_workflow = {str(Path(raw_path).resolve()): digest for raw_path, digest
                        in release["workflow_sha256"].items()}
    force_workflow_root = (Path(__file__).resolve().parent
                           if historical_workflow_dir is None
                           else Path(historical_workflow_dir).resolve())
    expected_force_workflow = {
        str((force_workflow_root / name).resolve()) for name in
        ("campaign.py", "qe_input.py", "qe_output.py",
         "pilot_dataset.py", "initial_pilot.py")
    }
    _require({str(Path(raw_path).resolve()) for raw_path in workflow}
             == expected_force_workflow,
             "force workflow inventory differs from exact initial-pilot allowlist")
    for raw_path, digest in workflow.items():
        path = Path(str(raw_path)).resolve()
        _match(path, digest, "force workflow")
        _require(release_workflow.get(str(path)) == digest,
                 "force workflow is not bound by initial pilot release")
    _require(manifest.get("config_sha256") == core.sha256_path(config_path)
             and manifest.get("pilot_spec") == release["force_pilot_spec"],
             "force manifest config or pilot specification differs from release")
    _require(manifest.get("force_policy_sha256") == core.canonical_sha256({
        "production": config["production"],
        "force": config["force_and_amplitude_validation"],
    }), "force manifest policy hash differs from current config")
    expected_settings = fb._settings(config, "pilot", release["force_pilot_spec"],
                                     allow_count_only_initial=True)
    _require(manifest.get("settings") == expected_settings,
             "force manifest settings differ from exact released settings")
    budget_path = force_manifest_path.parent / "budget_receipt.json"
    _match(budget_path, manifest.get("budget_receipt_sha256"), "initial pilot budget receipt")
    budget = core.load_json(budget_path)
    resources = release["contract"]["resources"]
    _require(budget.get("phase") == "initial" and budget.get("task_count") == 6
             and budget.get("material") == "SrZrS3"
             and budget.get("task_map_sha256") == manifest["task_map_sha256"]
             and budget.get("resource_policy_sha256") == core.canonical_sha256(
                 config["resource_budget"])
             and budget.get("mpi_ranks") == resources["mpi_ranks"]
             and budget.get("maximum_concurrency") == resources["max_concurrency"]
             and budget.get("walltime_hours") == resources["walltime_hours"]
             and budget.get("maximum_technical_retries_per_task") == resources["maximum_technical_retries_per_task"]
             and budget.get("reserved_core_hours") == resources["maximum_reserved_core_hours"]
             and budget.get("approved_total_core_hours") is None,
             "force budget receipt differs from exact-six release")
    tasks = manifest.get("tasks")
    _require(isinstance(tasks, list) and len(tasks) == 6
             and [task.get("displacement_id") for task in tasks] == EXPECTED_TASK_IDS,
             "force manifest is not the released exact-six order")
    signed = manifest.get("signed_pilot_dataset")
    _require(isinstance(signed, Mapping) and isinstance(signed.get("dataset_dir"), str),
             "force manifest lacks a signed pilot dataset")
    dataset = core.strict_run_descendant(
        run_dir, Path(signed["dataset_dir"]), "signed pilot dataset")
    audited = fb.audit_signed_pilot_dataset(dataset, run_dir, config,
        expected_settings, release["force_pilot_spec"],
        expected_manifest_sha256=signed.get("expected_manifest_sha256"))
    _require(audited == signed, "signed pilot dataset replay differs from force manifest")
    pseudos = manifest.get("pseudopotentials")
    _require(isinstance(pseudos, Mapping) and pseudos,
             "force manifest pseudopotential inventory is missing")
    pseudo_parents = {Path(str(item.get("file", ""))).resolve().parent
                      for item in pseudos.values() if isinstance(item, Mapping)}
    _require(len(pseudo_parents) == 1 and all(isinstance(item, Mapping)
             and Path(str(item.get("file", ""))).is_absolute()
             for item in pseudos.values()),
             "force manifest pseudopotential directory is ambiguous")
    pseudo_dir = next(iter(pseudo_parents))
    expected_inputs, _ = fb._dataset_inputs(dataset, expected_settings,
                                            pseudo_dir, config)
    entries = collection.get("entries")
    _require(isinstance(entries, list) and len(entries) == 6,
             "collection does not contain six entries")
    if not attempt_root.is_dir():
        _require(
            not os.path.lexists(attempt_root)
            and all(
                isinstance(entry, Mapping)
                and entry.get("outcome") == "upstream_failed"
                and entry.get("technical_failure_source")
                == "authenticated_scheduler_pre_wrapper"
                for entry in entries
            ),
            "missing primary attempt root is not fully explained by authenticated pre-wrapper failures",
        )
    entry_sources = {
        entry.get("task_id"): (entry, primary, attempt_root)
        for entry in entries if isinstance(entry, Mapping)
    }
    if retry_collection is not None:
        retry_primary = retry_collection.get("primary")
        retry_entries = retry_collection.get("entries")
        retry_ids = retry_collection.get("submitted_task_ids")
        failed_ids = sorted(
            entry.get("task_id") for entry in entries
            if isinstance(entry, Mapping) and entry.get("outcome") == "upstream_failed"
        )
        _require(
            retry_collection.get("schema_version") == 1
            and retry_collection.get("stage") == "collect"
            and retry_collection.get("collection_kind") == "force_array_batch"
            and retry_collection.get("material") == "SrZrS3"
            and retry_collection.get("force_mode") == "pilot"
            and retry_collection.get("expected_task_count") == 6
            and retry_ids == failed_ids
            and isinstance(retry_primary, Mapping)
            and isinstance(retry_entries, list)
            and len(retry_entries) == len(retry_ids)
            and all(isinstance(entry, Mapping)
                    and entry.get("outcome") == "accepted_success"
                    and not entry.get("errors") for entry in retry_entries)
            and retry_collection.get("batch_execution_complete") is True,
            "retry collection is not the exact successful failed-task subset",
        )
        retry_root = core.strict_run_descendant(
            run_dir, Path(str(retry_primary.get("attempt_root", ""))),
            "initial pilot retry attempt root")
        retry_collector = core.strict_run_descendant(
            run_dir, Path(str(retry_collection.get("collector_attempt", ""))),
            "initial pilot retry collector attempt")
        retry_records = retry_primary.get("submission_records")
        _require(isinstance(retry_records, Mapping),
                 "retry collection lacks submit.py afterany records")
        retry_request_ref = retry_records.get("primary_request")
        retry_result_ref = retry_records.get("primary_result")
        _require(isinstance(retry_request_ref, Mapping)
                 and isinstance(retry_result_ref, Mapping),
                 "retry submission record references are incomplete")
        retry_request_path = core.strict_run_descendant(
            run_dir, Path(str(retry_request_ref.get("path", ""))),
            "retry primary submission request")
        retry_request = core.load_json(retry_request_path)
        replayed_retry = core._force_submission_binding(
            config_path=config_path, run_dir=run_dir,
            collector_attempt=retry_collector,
            primary_attempt_id=retry_primary["attempt_id"],
            primary_job_id=retry_primary["job_id"],
            force_manifest_sha256=retry_primary.get("force_manifest_sha256"),
            task_map_sha256=retry_primary.get("task_map_sha256"),
            submitted_task_ids=retry_ids,
            expected_primary_request_sha256=retry_request_ref.get("sha256"),
            expected_primary_result_sha256=retry_result_ref.get("sha256"),
            expected_primary_stage_script_sha256=retry_request.get("stage_script_sha256"),
            require_held_primary=True,
        )
        _require(replayed_retry == retry_records,
                 "retry submission record replay differs from collection")
        for entry in retry_entries:
            entry_sources[entry["task_id"]] = (entry, retry_primary, retry_root)
    _require(set(entry_sources) == set(range(6)),
             "merged collections do not provide exactly six logical tasks")
    resource_attempts = []
    collections_for_usage = [("primary", entries, primary)]
    if retry_collection is not None:
        collections_for_usage.append(("retry", retry_entries, retry_primary))
    for attempt_kind, collection_entries, source_primary in collections_for_usage:
        for entry in collection_entries:
            usage = entry.get("resource_usage") if isinstance(entry, Mapping) else None
            _require(isinstance(usage, Mapping),
                     "initial pilot collection lacks per-allocation resource usage")
            elapsed = usage.get("elapsed_seconds")
            cpus = usage.get("allocated_cpus")
            timelimit = usage.get("timelimit_minutes")
            core_hours = usage.get("core_hours")
            expected_core_hours = (
                elapsed * cpus / 3600
                if type(elapsed) is int and type(cpus) is int else None
            )
            _require(
                type(entry.get("task_id")) is int
                and cpus == 32
                and timelimit == 120
                and type(elapsed) is int
                and 0 <= elapsed <= 7200
                and isinstance(core_hours, (int, float))
                and not isinstance(core_hours, bool)
                and math.isclose(float(core_hours), float(expected_core_hours),
                                 rel_tol=0, abs_tol=1e-12)
                and 0 <= float(core_hours) <= 64,
                "initial pilot allocation resource evidence exceeds the released bounds",
            )
            resource_attempts.append({
                "attempt_kind": attempt_kind,
                "primary_attempt_id": source_primary["attempt_id"],
                "task_id": entry["task_id"],
                "outcome": entry.get("outcome"),
                **dict(usage),
            })
    observed_core_hours = sum(
        float(item["core_hours"]) for item in resource_attempts
    )
    _require(observed_core_hours <= 768,
             "observed initial pilot allocations exceed the 768 core-hour reserve")
    forces = []
    timings = []
    artifact_hashes: dict[str, str] = {}
    settings_hash = None
    atom_order = None
    for task_id, task in enumerate(tasks):
        entry, source_primary, source_root = entry_sources[task_id]
        _require(entry.get("task_id") == task_id
                 and entry.get("displacement_id") == task["displacement_id"]
                 and entry.get("role") == task.get("role")
                 and entry.get("outcome") == "accepted_success"
                 and entry.get("exit_code") == 0 and not entry.get("errors"),
                 f"initial pilot task {task_id} is not accepted-success evidence")
        expected_attempt = source_root / f"task-{task_id}"
        attempt = core.strict_run_descendant(
            run_dir, Path(str(entry.get("attempt_path", ""))),
            f"initial pilot task {task_id} attempt")
        _require(attempt == expected_attempt,
                 f"initial pilot task {task_id} attempt path differs from primary allocation")
        core.reject_symlinks_below(run_dir, attempt,
                                   f"initial pilot task {task_id} attempt")
        evidence = entry.get("evidence")
        required_evidence = {"context.tsv", "exit_code.txt", "finished_utc.txt",
                             "force_claim.json", "launch.json", "result.json",
                             "scf.process.json", "scf.in", "scf.out", "scf.err"}
        _require(isinstance(evidence, Mapping) and required_evidence <= set(evidence),
                 f"initial pilot task {task_id} collection evidence inventory is incomplete")
        for name, record in evidence.items():
            _require(Path(str(name)).name == name and isinstance(record, Mapping),
                     f"initial pilot task {task_id} has an unsafe evidence record")
            path = core.strict_run_descendant(
                run_dir, attempt / name, f"initial pilot task {task_id} evidence {name}")
            _require(record.get("sha256") == core.sha256_path(path)
                     and record.get("bytes") == path.stat().st_size,
                     f"initial pilot task {task_id} collection evidence hash/size mismatch")
        context = entry.get("context")
        actual_context, context_errors = core._read_context_tsv(attempt / "context.tsv")
        actual_exit, exit_errors = core._read_exit_code(attempt)
        _require(isinstance(context, Mapping)
                 and not context_errors and not exit_errors and actual_exit == 0
                 and dict(context) == actual_context
                 and context.get("stage") == "force"
                 and context.get("attempt_id") == source_primary["attempt_id"]
                 and context.get("slurm_array_job_id") == str(source_primary["job_id"])
                 and context.get("slurm_array_task_id") == str(task_id)
                 and Path(str(context.get("run_dir", ""))).resolve() == run_dir
                 and context.get("config_sha256") == core.sha256_path(config_path),
                 f"initial pilot task {task_id} context identity mismatch")
        _require(_scheduler_success(entry, str(source_primary["job_id"]), task_id,
                                    str(context.get("slurm_job_id", ""))),
                 f"initial pilot task {task_id} lacks one bound COMPLETED 0:0 allocation")
        artifact = load_force_artifact(force_manifest_path, attempt, task_id)
        input_path = core.strict_run_descendant(
            run_dir, Path(artifact.input_path), f"initial pilot task {task_id} input")
        output_path = core.strict_run_descendant(
            run_dir, Path(artifact.output_path), f"initial pilot task {task_id} output")
        stderr_path = core.strict_run_descendant(
            run_dir, Path(artifact.stderr_path), f"initial pilot task {task_id} stderr")
        _require(input_path == attempt / "scf.in" and output_path == attempt / "scf.out"
                 and stderr_path == attempt / "scf.err",
                 f"initial pilot task {task_id} artifact paths are noncanonical")
        current_settings_hash, current_order = audit_actual_initial_input(
            input_path, expected_inputs[task["displacement_id"]], task,
            artifact.manifest, prior_settings_sha256=settings_hash,
            prior_atom_order=atom_order)
        if settings_hash is None:
            settings_hash, atom_order = current_settings_hash, current_order
        health = inspect_output(artifact.output_path, 40)
        _require(health["healthy"] is True, f"unhealthy initial pilot SCF {task_id}")
        record = parse_last_force_block(artifact.output_path, expected_atoms=40)
        forces.append([list(row) for row in record.forces_ry_bohr])
        timing = entry.get("timing")
        _require(isinstance(timing, Mapping)
                 and timing.get("allocated_cpus") == 32
                 and timing.get("timelimit_minutes") == 120
                 and isinstance(timing.get("elapsed_seconds"), int)
                 and 0 < timing["elapsed_seconds"] <= 7200
                 and isinstance(timing.get("scf_iterations"), int)
                 and timing["scf_iterations"] > 0
                 and isinstance(timing.get("max_rss"), str)
                 and re.fullmatch(r"\d+(?:\.\d+)?[KMGT]", timing["max_rss"])
                 and math.isclose(float(timing.get("core_hours", -1)),
                                  timing["elapsed_seconds"] * 32 / 3600,
                                  rel_tol=0, abs_tol=1e-12),
                 f"initial pilot task {task_id} timing/resource evidence is invalid")
        timings.append(dict(timing))
        artifact_hashes[str(output_path)] = core.sha256_path(output_path)
    metrics = evaluate_initial_forces(forces, release["contract"]["acceptance"])
    return {
        "schema_version": 1,
        "stage": "initial_pilot_finalizer",
        "material": "SrZrS3",
        "status": metrics["status"],
        "pass": metrics["pass"],
        "metrics": metrics,
        "timing_resource_summary": {
            "logical_task_count": 6,
            "technical_retry_task_ids": (
                list(retry_collection.get("submitted_task_ids", []))
                if retry_collection is not None else []
            ),
            "mpi_ranks_each": 32,
            "walltime_hours_each_attempt": 2,
            "maximum_concurrency": 2,
            "maximum_technical_retries_per_task": 1,
            "reserved_core_hours_ceiling": 768,
            "observed_total_core_hours": observed_core_hours,
            "allocation_attempt_count": len(resource_attempts),
            "allocation_attempts": resource_attempts,
            "tasks": timings,
        },
        "release_path": str(release_path),
        "release_sha256": release_sha256,
        "consumption_identity": release["consumption_identity"],
        "force_manifest_path": str(force_manifest_path),
        "force_manifest_sha256": core.sha256_path(force_manifest_path),
        "collection_path": str(collection_path),
        "collection_sha256": collection_sha256,
        "offline_recovery_path": str(collection_path) if recovery is not None else None,
        "offline_recovery_sha256": collection_sha256 if recovery is not None else None,
        "original_collector_failed": True if recovery is not None else False,
        "retry_collection_path": (
            str(retry_collection_path) if retry_collection_path is not None else None
        ),
        "retry_collection_sha256": retry_collection_sha256,
        "artifact_output_sha256": artifact_hashes,
        "scope_claims": {
            "initial_timing_repeatability_and_incremental_response_only": True,
            "D2_validated": False, "FC3_validated": False,
            "amplitude_validated": False, "cutoff_validated": False,
            "kappa_validated": False, "production_authorized": False,
        },
        "production_budget": None,
        "workflow_sha256": {str(Path(__file__)): core.sha256_path(Path(__file__))},
        "limitations": release["limitations"] + (
            list(recovery["limitations"]) if recovery is not None else []
        ),
    }


def finalize_initial_pilot(config_path: str | Path, run_dir: str | Path, *,
                           release_path: str | Path, release_sha256: str,
                           force_manifest_path: str | Path,
                           collection_path: str | Path, collection_sha256: str,
                           retry_collection_path: str | Path | None = None,
                           retry_collection_sha256: str | None = None,
                           output_path: str | Path) -> dict[str, Any]:
    config_path, run_dir = Path(config_path).resolve(), core.safe_run_dir(Path(run_dir))
    release_path, force_manifest_path = Path(release_path).resolve(), Path(force_manifest_path).resolve()
    collection_path = Path(collection_path).resolve()
    output_path = core.strict_run_descendant(
        run_dir, Path(output_path), "initial pilot result", require_exists=False
    )
    payload = _finalize_payload(config_path, run_dir, release_path, release_sha256,
                                force_manifest_path, collection_path, collection_sha256,
                                (Path(retry_collection_path).resolve()
                                 if retry_collection_path is not None else None),
                                retry_collection_sha256)
    result = {**payload, "created_utc": core.utc_now()}
    core.write_json_immutable(output_path, result)
    return {"healthy": True, "status": result["status"], "pass": result["pass"],
            "result": str(output_path), "result_sha256": core.sha256_path(output_path)}


def replay_initial_pilot_result(result_path: str | Path, *, config_path: str | Path,
                                run_dir: str | Path,
                                expected_result_sha256: str) -> dict[str, Any]:
    run_dir = core.safe_run_dir(Path(run_dir))
    result_path = core.strict_run_descendant(
        run_dir, Path(result_path), "initial pilot result"
    )
    _match(result_path, expected_result_sha256, "initial pilot result")
    result = core.load_json(result_path)
    payload = _finalize_payload(Path(config_path).resolve(), run_dir,
        Path(result["release_path"]), result["release_sha256"],
        Path(result["force_manifest_path"]), Path(result["collection_path"]),
        result["collection_sha256"],
        (Path(result["retry_collection_path"])
         if result.get("retry_collection_path") is not None else None),
        result.get("retry_collection_sha256"))
    _require(isinstance(result.get("created_utc"), str) and result["created_utc"],
             "initial pilot result creation time is missing")
    for key, value in payload.items():
        _require(result.get(key) == value, f"initial pilot result replay mismatch: {key}")
    return result

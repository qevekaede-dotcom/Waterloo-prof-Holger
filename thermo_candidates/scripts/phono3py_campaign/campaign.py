#!/usr/bin/env python3
"""Fail-closed QE/phono3py campaign driver for the two pending materials.

Heavy subcommands refuse to run outside a SLURM allocation.  Material JSON is
the scientific authority; this shared driver supplies provenance, immutable
attempt handling, strict gates, and calculator orchestration without silently
borrowing settings from SrCu2SnS4.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from qe_input import (
    AtomicPosition,
    FinalCoordinates,
    QEInputError,
    build_fixed_cell_relax_input,
    build_pristine_scf_input,
    extract_final_coordinates,
    parse_qe_input,
    replace_geometry_from_final_coordinates,
    replace_qe_geometry,
)
from qe_output import QEOutputError, inspect_output


REPO_ROOT = Path(__file__).resolve().parents[3]
BOHR_TO_ANGSTROM = 0.529177210903
FLOAT_REL_TOL = 2e-10
RUN_MANIFEST = "run_manifest.json"
STRUCTURE_POLICY_FIELDS = (
    "document_type",
    "schema_version",
    "material",
    "source",
    "provenance",
    "units",
    "software",
    "electronic_model",
    "pseudopotentials",
    "tight_relax",
    "start_structure_standardization",
    "symmetry_validation",
)
PREFLIGHT_POLICY_FIELDS = STRUCTURE_POLICY_FIELDS + ("displacements",)


class CampaignError(RuntimeError):
    """Raised when a workflow or scientific gate fails closed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_immutable(path: Path, content: str) -> None:
    """Write once, or accept byte-identical content on resume."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    with lock_path.open("a") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if path.exists():
            if not path.is_file() or path.read_text() != content:
                raise CampaignError(f"refusing to overwrite non-identical record: {path}")
            return
        try:
            with path.open("x") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if not path.is_file() or path.read_text() != content:
                raise CampaignError(f"concurrent non-identical record: {path}")


def write_json_immutable(path: Path, value: object) -> None:
    write_immutable(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"JSON root must be an object: {path}")
    return value


def required(mapping: Mapping[str, Any], dotted_path: str) -> Any:
    value: Any = mapping
    for component in dotted_path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise CampaignError(f"missing required config field: {dotted_path}")
        value = value[component]
    return value


def positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampaignError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise CampaignError(f"{name} must be finite and positive")
    return number


def integer_triplet(value: Any, name: str, *, positive: bool = False) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise CampaignError(f"{name} must contain exactly three integers")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise CampaignError(f"{name} must contain integers")
    result = tuple(value)
    if positive and any(item <= 0 for item in result):
        raise CampaignError(f"{name} entries must be positive")
    return result  # type: ignore[return-value]


def matrix3(value: Any, name: str) -> tuple[tuple[int, int, int], ...]:
    if not isinstance(value, list) or len(value) != 3:
        raise CampaignError(f"{name} must be a 3x3 integer matrix")
    rows = tuple(integer_triplet(row, f"{name}[{index}]") for index, row in enumerate(value))
    return rows


def determinant(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def vector_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in vector))


def resolve_repo_source(config: Mapping[str, Any], field: str) -> Path:
    raw = required(config, field)
    if not isinstance(raw, str) or not raw:
        raise CampaignError(f"{field} must be a repository-relative path")
    candidate = (REPO_ROOT / raw).resolve()
    try:
        candidate.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise CampaignError(f"{field} escapes repository root: {raw}") from exc
    if not candidate.is_file():
        raise CampaignError(f"{field} does not exist: {candidate}")
    return candidate


def safe_run_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), REPO_ROOT.resolve()}
    if resolved in forbidden:
        raise CampaignError(f"run directory is too broad: {resolved}")
    if "READY_TO_ATTACH" in resolved.parts:
        raise CampaignError("run directory may not be inside READY_TO_ATTACH")
    return resolved


def validate_config(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config_path = config_path.resolve()
    config = load_json(config_path)
    errors: list[str] = []
    checks: dict[str, Any] = {}

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        check(required(config, "document_type") == "phono3py_qe_campaign", "wrong document_type")
        check(required(config, "schema_version") == 1, "unsupported schema_version")
        formula = required(config, "material.formula")
        nat = required(config, "material.unitcell_atoms")
        check(isinstance(formula, str) and bool(formula), "material.formula must be non-empty")
        check(isinstance(nat, int) and not isinstance(nat, bool) and nat > 0, "unitcell_atoms must be positive")
        check(required(config, "units.phono3py_calculator") == "qe", "calculator must be qe")
        check(required(config, "scheduler.cluster") == "nibi", "scheduler cluster must be nibi")
        scheduler_account = required(config, "scheduler.slurm_account")
        check(
            isinstance(scheduler_account, str)
            and bool(re.fullmatch(r"[A-Za-z0-9_.-]+", scheduler_account)),
            "scheduler.slurm_account is invalid",
        )
        factor = positive_number(required(config, "units.bohr_to_angstrom"), "units.bohr_to_angstrom")
        check(math.isclose(factor, BOHR_TO_ANGSTROM, rel_tol=0, abs_tol=1e-12), "unexpected bohr conversion constant")

        amplitude_a = positive_number(required(config, "displacements.amplitude_angstrom"), "amplitude_angstrom")
        amplitude_b = positive_number(required(config, "displacements.amplitude_bohr"), "amplitude_bohr")
        check(math.isclose(amplitude_a / factor, amplitude_b, rel_tol=FLOAT_REL_TOL), "amplitude Å/bohr mismatch")

        cutoff_ids: set[str] = set()
        for index, cutoff in enumerate(required(config, "displacements.cutoff_candidates")):
            cutoff_id = required(cutoff, "id")
            cutoff_a = positive_number(required(cutoff, "cutoff_pair_distance_angstrom"), f"cutoff[{index}] angstrom")
            cutoff_b = positive_number(required(cutoff, "cutoff_pair_distance_cli_bohr"), f"cutoff[{index}] bohr")
            check(isinstance(cutoff_id, str) and cutoff_id not in cutoff_ids, f"duplicate cutoff id {cutoff_id!r}")
            cutoff_ids.add(cutoff_id)
            check(math.isclose(cutoff_a / factor, cutoff_b, rel_tol=FLOAT_REL_TOL), f"cutoff conversion mismatch: {cutoff_id}")

        supercells: dict[str, dict[str, Any]] = {}
        for index, candidate in enumerate(required(config, "displacements.supercell_candidates")):
            candidate_id = required(candidate, "id")
            matrix = matrix3(required(candidate, "matrix"), f"supercell[{index}].matrix")
            det = round(abs(determinant(matrix)))
            check(det > 0, f"singular supercell matrix: {candidate_id}")
            check(required(candidate, "atoms") == nat * det, f"atom count/determinant mismatch: {candidate_id}")
            if "determinant" in candidate:
                check(candidate["determinant"] == det, f"stored determinant mismatch: {candidate_id}")
            check(isinstance(candidate_id, str) and candidate_id not in supercells, f"duplicate supercell id {candidate_id!r}")
            supercells[str(candidate_id)] = candidate

        for index, item in enumerate(required(config, "displacements.enumerate")):
            supercell_id = item.get("supercell_id", item.get("fc3_supercell_id"))
            cutoff_id = item.get("cutoff_pair_id")
            check(supercell_id in supercells, f"enumerate[{index}] unknown supercell {supercell_id!r}")
            check(cutoff_id is None or cutoff_id in cutoff_ids, f"enumerate[{index}] unknown cutoff {cutoff_id!r}")

        hard_cap = required(config, "displacements.hard_cap")
        check(isinstance(hard_cap, int) and not isinstance(hard_cap, bool) and hard_cap > 0, "hard_cap must be positive integer")
        integer_triplet(required(config, "tight_relax.kmesh"), "tight_relax.kmesh", positive=True)
        integer_triplet(required(config, "tight_relax.kmesh_shift"), "tight_relax.kmesh_shift")
        force_target = positive_number(required(config, "tight_relax.accept_max_force_ry_bohr"), "accept force")
        force_stop = positive_number(required(config, "tight_relax.hard_stop_max_force_ry_bohr"), "hard-stop force")
        check(force_target < force_stop, "accept force must be below hard-stop force")
        check(required(config, "tight_relax.cell_fixed") is True, "tight relax must keep cell fixed")
        selection_required = required(config, "production.selection_required")
        selected_supercell = required(config, "production.selected_supercell")
        selected_cutoff = required(config, "production.selected_cutoff")
        check(isinstance(selection_required, bool), "production.selection_required must be boolean")
        if selection_required:
            check(selected_supercell is None, "selected_supercell must be null while selection is required")
            check(selected_cutoff is None, "selected_cutoff must be null while selection is required")
        else:
            check(selected_supercell in supercells, "selected_supercell is not a configured candidate")
            check(selected_cutoff in cutoff_ids, "selected_cutoff is not a configured candidate")

        source_input = resolve_repo_source(config, "source.qe_scf_input")
        source_relax = resolve_repo_source(config, "source.original_relax_output")
        parsed = parse_qe_input(source_input.read_text())
        check(parsed.nat == nat, "source QE nat differs from material.unitcell_atoms")
        configured_pseudos = required(config, "pseudopotentials.files")
        check(
            {item.label: item.pseudopotential for item in parsed.atomic_species} == configured_pseudos,
            "QE ATOMIC_SPECIES pseudopotentials differ from config",
        )
        checks.update(
            {
                "material": formula,
                "unitcell_atoms": nat,
                "source_qe_sha256": sha256_path(source_input),
                "source_relax_sha256": sha256_path(source_relax),
                "supercell_candidates": sorted(supercells),
                "cutoff_candidates": sorted(cutoff_ids),
                "production_blocked_pending_selection": bool(selection_required),
            }
        )
    except (CampaignError, QEInputError, KeyError, TypeError) as exc:
        errors.append(str(exc))

    report = {
        "healthy": not errors,
        "config": str(config_path),
        "config_sha256": sha256_path(config_path),
        "checked_utc": utc_now(),
        "checks": checks,
        "errors": errors,
    }
    if errors:
        raise CampaignError("config validation failed: " + "; ".join(errors))
    return config, report


def require_compute_node() -> None:
    missing = [name for name in ("SLURM_JOB_ID", "SLURM_JOB_NODELIST") if not os.environ.get(name)]
    if missing:
        raise CampaignError("heavy stage requires a SLURM compute allocation; missing " + ", ".join(missing))


def attempt_dir(run_dir: Path) -> Path:
    raw = os.environ.get("P3_ATTEMPT_DIR")
    if not raw:
        raise CampaignError("P3_ATTEMPT_DIR is required for an immutable compute attempt")
    path = Path(raw).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError as exc:
        raise CampaignError(f"P3_ATTEMPT_DIR is outside RUN_DIR: {path}") from exc
    if not path.is_dir():
        raise CampaignError(f"P3_ATTEMPT_DIR does not exist: {path}")
    return path


def policy_sha256(config: Mapping[str, Any], stage: str) -> str:
    """Hash only the scientific policy consumed by a released stage.

    Production selection is intentionally excluded from the structure and
    preflight hashes. Filling that selection after successful pilots must not
    invalidate immutable evidence from these earlier stages.
    """

    if stage == "structure":
        fields = STRUCTURE_POLICY_FIELDS
    elif stage == "preflight":
        fields = PREFLIGHT_POLICY_FIELDS
    else:
        raise CampaignError(f"unknown manifest policy stage: {stage}")
    missing = [field for field in fields if field not in config]
    if missing:
        raise CampaignError("config lacks policy fields: " + ", ".join(missing))
    return canonical_sha256({field: config[field] for field in fields})


def manifest_for(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    source_qe = resolve_repo_source(config, "source.qe_scf_input")
    source_relax = resolve_repo_source(config, "source.original_relax_output")
    tracked = [Path(__file__).resolve(), Path(__file__).with_name("qe_input.py"), Path(__file__).with_name("qe_output.py")]
    return {
        "schema_version": 2,
        "material": required(config, "material.formula"),
        "created_utc": utc_now(),
        "config_path": str(config_path.resolve()),
        # Archival only: later production selections legitimately change this
        # full-file hash. Stage verification uses the policy hashes below.
        "config_sha256": sha256_path(config_path.resolve()),
        "structure_policy_sha256": policy_sha256(config, "structure"),
        "preflight_policy_sha256": policy_sha256(config, "preflight"),
        "source_qe_input": str(source_qe),
        "source_qe_sha256": sha256_path(source_qe),
        "source_relax_output": str(source_relax),
        "source_relax_sha256": sha256_path(source_relax),
        "workflow_files": {str(path.relative_to(REPO_ROOT)): sha256_path(path) for path in tracked},
        "git_commit": subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip(),
    }


def command_prepare_relax(config_path: Path, run_dir: Path) -> dict[str, Any]:
    config, validation = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(config, config_path)
    manifest_path = run_dir / RUN_MANIFEST
    if manifest_path.exists():
        previous = load_json(manifest_path)
        immutable_keys = (
            "schema_version",
            "material",
            "structure_policy_sha256",
            "preflight_policy_sha256",
            "source_qe_sha256",
            "source_relax_sha256",
            "workflow_files",
        )
        mismatches = [key for key in immutable_keys if previous.get(key) != manifest.get(key)]
        if mismatches:
            raise CampaignError("run manifest does not match current sources: " + ", ".join(mismatches))
        manifest = previous
    else:
        unexpected = [item.name for item in run_dir.iterdir()]
        if unexpected:
            raise CampaignError(f"new run directory is not empty: {unexpected}")
        write_json_immutable(manifest_path, manifest)
        write_immutable(run_dir / "config.snapshot.json", json.dumps(config, indent=2, sort_keys=True) + "\n")
        write_json_immutable(run_dir / "config_validation.json", validation)
        (run_dir / "relax").mkdir()
        (run_dir / "preflight").mkdir()
    return {
        "healthy": True,
        "stage": "prepare-relax",
        "material": manifest["material"],
        "run_dir": str(run_dir),
        "manifest": str(manifest_path),
        "config_sha256": manifest["config_sha256"],
        "next": "submit relax.sbatch with a new ATTEMPT_ID",
    }


def verify_manifest(
    config: Mapping[str, Any], config_path: Path, run_dir: Path, *, stage: str
) -> dict[str, Any]:
    manifest_path = run_dir / RUN_MANIFEST
    if not manifest_path.is_file():
        raise CampaignError(f"run was not prepared: {manifest_path}")
    saved = load_json(manifest_path)
    current = manifest_for(config, config_path)
    policy_key = f"{stage}_policy_sha256"
    if stage not in {"structure", "preflight"}:
        raise CampaignError(f"unsupported manifest verification stage: {stage}")
    for key in (
        "schema_version",
        "material",
        policy_key,
        "source_qe_sha256",
        "source_relax_sha256",
        "workflow_files",
    ):
        if saved.get(key) != current.get(key):
            raise CampaignError(f"immutable run provenance changed: {key}")
    return saved


def run_process(command: Sequence[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> dict[str, Any]:
    started = utc_now()
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if stdout_path.exists() or stderr_path.exists():
        raise CampaignError("attempt output already exists; retries require a new ATTEMPT_ID")
    # Stream directly so a timeout or node failure still leaves partial evidence.
    with stdout_path.open("x") as stdout_handle, stderr_path.open("x") as stderr_handle:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )
    report = {
        "command": list(command),
        "cwd": str(cwd),
        "started_utc": started,
        "finished_utc": utc_now(),
        "returncode": completed.returncode,
        "stdout_sha256": sha256_path(stdout_path),
        "stderr_sha256": sha256_path(stderr_path),
    }
    write_json_immutable(
        stdout_path.with_name(f"{stdout_path.stem}.process.json"), report
    )
    if completed.returncode:
        raise CampaignError(f"command failed with exit {completed.returncode}: {' '.join(command)}")
    return report


def qe_command(input_name: str) -> list[str]:
    launcher = os.environ.get("QE_MPI_LAUNCHER", "srun")
    executable = os.environ.get("QE_EXECUTABLE", "pw.x")
    nk = os.environ.get("QE_NK", "1")
    if not nk.isdigit() or int(nk) < 1:
        raise CampaignError("QE_NK must be a positive integer")
    return [launcher, executable, "-nk", nk, "-in", input_name]


def pseudopotential_hashes(config: Mapping[str, Any], pseudo_dir: Path) -> dict[str, dict[str, str]]:
    if not pseudo_dir.is_dir():
        raise CampaignError(f"pseudopotential directory does not exist: {pseudo_dir}")
    result: dict[str, dict[str, str]] = {}
    for species, filename in required(config, "pseudopotentials.files").items():
        path = pseudo_dir / filename
        if not path.is_file():
            raise CampaignError(f"missing pseudopotential for {species}: {path}")
        result[species] = {"file": str(path), "sha256": sha256_path(path)}
    return result


def symmetry_scan(
    cell: Sequence[Sequence[float]],
    positions: Sequence[Sequence[float]],
    labels: Sequence[str],
    tolerances_angstrom: Sequence[float],
) -> list[dict[str, Any]]:
    try:
        import spglib
    except ImportError as exc:
        raise CampaignError("spglib is required in the phono3py environment") from exc
    label_numbers = {label: index + 1 for index, label in enumerate(dict.fromkeys(labels))}
    numbers = [label_numbers[label] for label in labels]
    reports: list[dict[str, Any]] = []
    for tolerance in tolerances_angstrom:
        dataset = spglib.get_symmetry_dataset(
            (cell, positions, numbers), symprec=float(tolerance)
        )
        if dataset is None:
            reports.append(
                {
                    "symprec_angstrom": float(tolerance),
                    "spacegroup_number": None,
                    "spacegroup_symbol": None,
                }
            )
        else:
            reports.append(
                {
                    "symprec_angstrom": float(tolerance),
                    "spacegroup_number": int(dataset.number),
                    "spacegroup_symbol": str(dataset.international),
                }
            )
    return reports


def _standardization_distance_audit(
    raw_cell: Any,
    raw_positions: Any,
    raw_numbers: Any,
    ideal_cell: Any,
    ideal_positions: Any,
    ideal_numbers: Any,
) -> dict[str, Any]:
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
    except ImportError as exc:
        raise CampaignError("numpy and scipy are required for structure-standardization audit") from exc
    if sorted(int(value) for value in raw_numbers) != sorted(int(value) for value in ideal_numbers):
        raise CampaignError("standardization changed species multiplicities")
    best: tuple[float, float, Any, Any, Any] | None = None
    n_atoms = len(raw_numbers)
    for raw_anchor, raw_type in enumerate(raw_numbers):
        for ideal_anchor, ideal_type in enumerate(ideal_numbers):
            if int(raw_type) != int(ideal_type):
                continue
            origin = np.asarray(ideal_positions[ideal_anchor]) - np.asarray(raw_positions[raw_anchor])
            costs = np.full((n_atoms, n_atoms), 1e9, dtype=float)
            for raw_index, (raw_position, atom_type) in enumerate(zip(raw_positions, raw_numbers)):
                for ideal_index, (ideal_position, ideal_atom_type) in enumerate(zip(ideal_positions, ideal_numbers)):
                    if int(atom_type) != int(ideal_atom_type):
                        continue
                    delta = np.asarray(ideal_position) - np.asarray(raw_position) - origin
                    delta -= np.rint(delta)
                    costs[raw_index, ideal_index] = float(np.linalg.norm(delta @ ideal_cell))
            rows, columns = linear_sum_assignment(costs)
            distances = costs[rows, columns]
            candidate = (
                float(np.max(distances)),
                float(np.sqrt(np.mean(distances**2))),
                origin,
                columns,
                distances,
            )
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    if best is None:
        raise CampaignError("could not map standardized atoms")
    maximum, rms, origin, columns, distances = best
    deformation = np.asarray(ideal_cell).T @ np.linalg.inv(np.asarray(raw_cell).T)
    strain = (deformation.T @ deformation - np.eye(3)) / 2
    principal_strain = np.linalg.eigvalsh(strain)
    return {
        "origin_shift_fractional": [float(value) for value in origin],
        "raw_to_ideal_atom_mapping_1_based": [int(value) + 1 for value in columns],
        "per_atom_cartesian_displacement_angstrom": [float(value) for value in distances],
        "max_atom_displacement_angstrom": maximum,
        "rms_atom_displacement_angstrom": rms,
        "deformation_gradient": deformation.tolist(),
        "principal_strain": [float(value) for value in principal_strain],
        "max_absolute_principal_strain": float(np.max(np.abs(principal_strain))),
        "relative_volume_change": float(
            abs(np.linalg.det(ideal_cell)) / abs(np.linalg.det(raw_cell)) - 1
        ),
    }


def prepare_starting_geometry(
    config: Mapping[str, Any],
    source_text: str,
    archived_relax_text: str,
) -> tuple[str, dict[str, Any]]:
    nat = int(required(config, "material.unitcell_atoms"))
    injected = replace_geometry_from_final_coordinates(
        source_text, archived_relax_text, expected_atoms=nat, require_cell=True
    )
    parsed = parse_qe_input(injected)
    labels = [item.label for item in parsed.atomic_positions]
    positions = [item.coordinates for item in parsed.atomic_positions]
    tolerances = [
        float(item["symprec_angstrom"])
        for item in required(config, "symmetry_validation.scan_symprec_pairs")
    ]
    audit: dict[str, Any] = {
        "source": "last complete Begin/End final coordinates block",
        "archived_cell_vectors_angstrom": parsed.cell_parameters,
        "archived_geometry_sha256": hashlib.sha256(injected.encode()).hexdigest(),
        "spacegroup_scan_before_standardization": symmetry_scan(
            parsed.cell_parameters, positions, labels, tolerances
        ),
        "standardized": False,
    }
    policy = config.get("start_structure_standardization")
    if not isinstance(policy, Mapping) or not policy.get("symmetrize_start"):
        audit["accepted_starting_geometry_sha256"] = audit["archived_geometry_sha256"]
        audit["spacegroup_scan_after_standardization"] = audit[
            "spacegroup_scan_before_standardization"
        ]
        symmetry_policy = required(config, "symmetry_validation")
        strict_tolerance = float(
            required(symmetry_policy, "strictest_required_matching_symprec_angstrom")
        )
        expected_number = int(required(config, "material.expected_spacegroup_number"))
        audit["pass"] = any(
            math.isclose(item["symprec_angstrom"], strict_tolerance, rel_tol=0, abs_tol=1e-15)
            and item["spacegroup_number"] == expected_number
            for item in audit["spacegroup_scan_before_standardization"]
        )
        if not audit["pass"]:
            raise CampaignError("starting structure fails the strict space-group gate")
        return injected, audit

    try:
        import numpy as np
        import spglib
    except ImportError as exc:
        raise CampaignError("numpy and spglib are required for starting-structure standardization") from exc
    label_numbers = {label: index + 1 for index, label in enumerate(dict.fromkeys(labels))}
    number_labels = {number: label for label, number in label_numbers.items()}
    numbers = [label_numbers[label] for label in labels]
    symprec = float(required(policy, "symprec_angstrom"))
    cell_tuple = (np.asarray(parsed.cell_parameters), np.asarray(positions), np.asarray(numbers))
    dataset = spglib.get_symmetry_dataset(cell_tuple, symprec=symprec)
    if dataset is None or int(dataset.number) != int(required(policy, "expected_standardized_spacegroup_number")):
        raise CampaignError("archived structure does not reach the expected space group at standardization tolerance")
    primitive = spglib.standardize_cell(
        cell_tuple,
        to_primitive=bool(required(policy, "to_primitive")),
        no_idealize=bool(required(policy, "no_idealize")),
        symprec=symprec,
    )
    raw_conventional = spglib.standardize_cell(
        cell_tuple, to_primitive=False, no_idealize=True, symprec=symprec
    )
    ideal_conventional = spglib.standardize_cell(
        cell_tuple, to_primitive=False, no_idealize=False, symprec=symprec
    )
    if primitive is None or raw_conventional is None or ideal_conventional is None:
        raise CampaignError("spglib failed to return a complete standardized structure")
    standard_cell, standard_positions, standard_numbers = primitive
    standard_labels = [number_labels[int(number)] for number in standard_numbers]
    if standard_labels != labels:
        raise CampaignError(
            "standardized primitive atom order differs from QE source; explicit remapping is required"
        )
    final = FinalCoordinates(
        position_unit="crystal",
        atomic_positions=tuple(
            AtomicPosition(label, tuple(float(value) % 1.0 for value in position))
            for label, position in zip(standard_labels, standard_positions)
        ),
        cell_unit="angstrom",
        cell_parameters=tuple(
            tuple(float(value) for value in row) for row in standard_cell
        ),
    )
    standardized = replace_qe_geometry(source_text, final, require_cell=True)
    metrics = _standardization_distance_audit(*raw_conventional, *ideal_conventional)
    guardrails = required(policy, "guardrails")
    guardrail_checks = {
        "atom_displacement": metrics["max_atom_displacement_angstrom"]
        <= float(required(guardrails, "max_atom_displacement_angstrom")),
        "principal_strain": metrics["max_absolute_principal_strain"]
        <= float(required(guardrails, "max_absolute_principal_strain")),
        "relative_volume": abs(metrics["relative_volume_change"])
        <= float(required(guardrails, "max_relative_volume_change")),
    }
    after_parsed = parse_qe_input(standardized)
    after_scan = symmetry_scan(
        after_parsed.cell_parameters,
        [item.coordinates for item in after_parsed.atomic_positions],
        [item.label for item in after_parsed.atomic_positions],
        tolerances,
    )
    expected_number = int(required(policy, "expected_standardized_spacegroup_number"))
    strict_after = float(
        required(
            config,
            "symmetry_validation.post_standardization_strictest_required_matching_symprec_angstrom",
        )
    )
    strict_matches = any(
        math.isclose(item["symprec_angstrom"], strict_after, rel_tol=0, abs_tol=1e-15)
        and item["spacegroup_number"] == expected_number
        for item in after_scan
    )
    reference_cell = policy.get("reference_standardized_cell_vectors_angstrom")
    reference_match = True
    if reference_cell is not None:
        reference_match = all(
            math.isclose(float(value), float(reference), rel_tol=0, abs_tol=2e-7)
            for row, reference_row in zip(after_parsed.cell_parameters, reference_cell)
            for value, reference in zip(row, reference_row)
        )
    audit.update(
        {
            "standardized": True,
            "method": "spglib.standardize_cell",
            "standardization_symprec_angstrom": symprec,
            "standardized_cell_vectors_angstrom": after_parsed.cell_parameters,
            "standardized_geometry_sha256": hashlib.sha256(standardized.encode()).hexdigest(),
            "spglib_transformation_matrix": np.asarray(dataset.transformation_matrix).tolist(),
            "spglib_origin_shift": np.asarray(dataset.origin_shift).tolist(),
            "original_mapping_to_primitive_1_based": [
                int(value) + 1 for value in np.asarray(dataset.mapping_to_primitive)
            ],
            "spacegroup_scan_after_standardization": after_scan,
            "standardization_metrics": metrics,
            "guardrail_checks": guardrail_checks,
            "reference_cell_match": reference_match,
            "strict_spacegroup_match": strict_matches,
            "pass": all(guardrail_checks.values()) and reference_match and strict_matches,
        }
    )
    if not audit["pass"]:
        raise CampaignError("starting-structure standardization failed one or more guardrails")
    return standardized, audit


def command_run_relax(config_path: Path, run_dir: Path) -> dict[str, Any]:
    require_compute_node()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    run_manifest = verify_manifest(config, config_path, run_dir, stage="structure")
    attempt = attempt_dir(run_dir)
    pseudo_dir_raw = os.environ.get("P3_PSEUDO_DIR")
    if not pseudo_dir_raw:
        raise CampaignError("P3_PSEUDO_DIR is required")
    pseudo_dir = Path(pseudo_dir_raw).resolve()
    pseudo_hashes = pseudopotential_hashes(config, pseudo_dir)
    source_text = resolve_repo_source(config, "source.qe_scf_input").read_text()
    archived_relax_text = resolve_repo_source(config, "source.original_relax_output").read_text(errors="replace")
    starting_input, structure_audit = prepare_starting_geometry(
        config, source_text, archived_relax_text
    )
    write_json_immutable(attempt / "starting_structure_audit.json", structure_audit)
    write_immutable(attempt / "starting_unitcell.in", starting_input)

    settings = required(config, "tight_relax")
    formula = str(required(config, "material.formula"))
    relax_input = build_fixed_cell_relax_input(
        starting_input,
        outdir="./tmp-relax",
        prefix=f"{formula}_p3_relax",
        pseudo_dir=str(pseudo_dir),
        disk_io="low",
        tprnfor=True,
        conv_thr=float(required(settings, "conv_thr_ry")),
        forc_conv_thr=float(required(settings, "forc_conv_thr_ry_bohr")),
        ion_dynamics=str(required(settings, "ion_dynamics")),
        ecutwfc=float(required(settings, "ecutwfc_ry")),
        ecutrho=float(required(settings, "ecutrho_ry")),
        kmesh=required(settings, "kmesh"),
        kshift=required(settings, "kmesh_shift"),
        etot_conv_thr=float(required(settings, "etot_conv_thr_ry")),
        tstress=bool(required(settings, "tstress")),
        electron_maxstep=int(required(settings, "electron_maxstep")),
        mixing_beta=float(required(settings, "mixing_beta")),
    )
    write_immutable(attempt / "relax.in", relax_input)
    relax_command = qe_command("relax.in")
    write_json_immutable(
        attempt / "relax_launch.json",
        {
            "created_utc": utc_now(),
            "command": relax_command,
            "config_sha256": sha256_path(config_path.resolve()),
            "structure_policy_sha256": run_manifest["structure_policy_sha256"],
            "starting_structure_audit_sha256": sha256_path(
                attempt / "starting_structure_audit.json"
            ),
            "relax_input_sha256": sha256_path(attempt / "relax.in"),
            "pseudopotentials": pseudo_hashes,
        },
    )
    relax_process = run_process(
        relax_command, attempt, attempt / "relax.out", attempt / "relax.err"
    )
    relax_health = inspect_output(
        attempt / "relax.out", int(required(config, "material.unitcell_atoms"))
    )
    if not relax_health["healthy"]:
        raise CampaignError(f"tight relax output is unhealthy: {relax_health['errors']}")
    relax_text = (attempt / "relax.out").read_text(errors="replace")
    if "bfgs converged" not in relax_text.lower() or "End of BFGS Geometry Optimization" not in relax_text:
        raise CampaignError("tight relax did not record normal BFGS convergence")
    pristine_input = build_pristine_scf_input(
        relax_input,
        relax_text,
        outdir="./tmp-pristine",
        prefix=f"{formula}_p3_pristine",
        pseudo_dir=str(pseudo_dir),
        disk_io="low",
        tprnfor=True,
        conv_thr=float(required(settings, "conv_thr_ry")),
        ecutwfc=float(required(settings, "ecutwfc_ry")),
        ecutrho=float(required(settings, "ecutrho_ry")),
        kmesh=required(settings, "kmesh"),
        kshift=required(settings, "kmesh_shift"),
        nosym=True,
        noinv=True,
    )
    write_immutable(attempt / "pristine.in", pristine_input)
    pristine_command = qe_command("pristine.in")
    write_json_immutable(
        attempt / "pristine_launch.json",
        {
            "created_utc": utc_now(),
            "command": pristine_command,
            "config_sha256": sha256_path(config_path.resolve()),
            "structure_policy_sha256": run_manifest["structure_policy_sha256"],
            "relax_output_sha256": sha256_path(attempt / "relax.out"),
            "pristine_input_sha256": sha256_path(attempt / "pristine.in"),
            "pseudopotentials": pseudo_hashes,
        },
    )
    pristine_process = run_process(
        pristine_command,
        attempt,
        attempt / "pristine.out",
        attempt / "pristine.err",
    )
    execution = {
        "material": formula,
        "structure_policy_sha256": run_manifest["structure_policy_sha256"],
        "pseudopotentials": pseudo_hashes,
        "starting_unitcell_sha256": sha256_path(attempt / "starting_unitcell.in"),
        "relax_input_sha256": sha256_path(attempt / "relax.in"),
        "relax_output_sha256": sha256_path(attempt / "relax.out"),
        "pristine_input_sha256": sha256_path(attempt / "pristine.in"),
        "pristine_output_sha256": sha256_path(attempt / "pristine.out"),
        "relax_process": relax_process,
        "pristine_process": pristine_process,
        "finished_utc": utc_now(),
    }
    write_json_immutable(attempt / "execution_manifest.json", execution)
    return execution


def _position_shifts_angstrom(initial_text: str, final_text: str) -> list[float]:
    initial = parse_qe_input(initial_text)
    final = parse_qe_input(final_text)
    if initial.nat != final.nat or [item.label for item in initial.atomic_positions] != [
        item.label for item in final.atomic_positions
    ]:
        raise CampaignError("cannot compare geometry: atom mapping changed")
    if any(
        not math.isclose(left, right, rel_tol=0, abs_tol=1e-8)
        for left_row, right_row in zip(initial.cell_parameters, final.cell_parameters)
        for left, right in zip(left_row, right_row)
    ):
        raise CampaignError("tight relax changed the fixed cell")
    shifts: list[float] = []
    for left, right in zip(initial.atomic_positions, final.atomic_positions):
        delta = [b - a - round(b - a) for a, b in zip(left.coordinates, right.coordinates)]
        cartesian = [
            sum(delta[row] * initial.cell_parameters[row][axis] for row in range(3))
            for axis in range(3)
        ]
        shifts.append(vector_norm(cartesian))
    return shifts


def command_finalize_relax(config_path: Path, run_dir: Path) -> dict[str, Any]:
    require_compute_node()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    run_manifest = verify_manifest(config, config_path, run_dir, stage="structure")
    attempt = attempt_dir(run_dir)
    required_files = [
        attempt / "starting_unitcell.in",
        attempt / "relax.in",
        attempt / "relax.out",
        attempt / "pristine.in",
        attempt / "pristine.out",
        attempt / "relax_launch.json",
        attempt / "pristine_launch.json",
        attempt / "execution_manifest.json",
    ]
    missing = [str(path) for path in required_files if not path.is_file()]
    if missing:
        raise CampaignError("relax attempt is incomplete: " + ", ".join(missing))
    execution = load_json(attempt / "execution_manifest.json")
    for key, filename in (
        ("starting_unitcell_sha256", "starting_unitcell.in"),
        ("relax_input_sha256", "relax.in"),
        ("relax_output_sha256", "relax.out"),
        ("pristine_input_sha256", "pristine.in"),
        ("pristine_output_sha256", "pristine.out"),
    ):
        if execution.get(key) != sha256_path(attempt / filename):
            raise CampaignError(f"execution-manifest hash mismatch: {filename}")
    relax_launch = load_json(attempt / "relax_launch.json")
    pristine_launch = load_json(attempt / "pristine_launch.json")
    for record_name, record in (
        ("execution manifest", execution),
        ("relax launch", relax_launch),
        ("pristine launch", pristine_launch),
    ):
        if record.get("structure_policy_sha256") != run_manifest.get(
            "structure_policy_sha256"
        ):
            raise CampaignError(f"{record_name} structure-policy hash mismatch")
    if relax_launch.get("relax_input_sha256") != sha256_path(attempt / "relax.in"):
        raise CampaignError("relax launch/input hash mismatch")
    if pristine_launch.get("relax_output_sha256") != sha256_path(attempt / "relax.out"):
        raise CampaignError("pristine launch/relax-output hash mismatch")
    if pristine_launch.get("pristine_input_sha256") != sha256_path(attempt / "pristine.in"):
        raise CampaignError("pristine launch/input hash mismatch")
    nat = int(required(config, "material.unitcell_atoms"))
    relax_health = inspect_output(attempt / "relax.out", nat)
    pristine_health = inspect_output(attempt / "pristine.out", nat)
    relax_text = (attempt / "relax.out").read_text(errors="replace")
    bfgs_converged = (
        "bfgs converged" in relax_text.lower()
        and "End of BFGS Geometry Optimization" in relax_text
    )
    shifts = _position_shifts_angstrom(
        (attempt / "starting_unitcell.in").read_text(),
        (attempt / "pristine.in").read_text(),
    )
    final_input = parse_qe_input((attempt / "pristine.in").read_text())
    tolerances = [
        float(item["symprec_angstrom"])
        for item in required(config, "symmetry_validation.scan_symprec_pairs")
    ]
    scan = symmetry_scan(
        final_input.cell_parameters,
        [item.coordinates for item in final_input.atomic_positions],
        [item.label for item in final_input.atomic_positions],
        tolerances,
    )
    expected_number = int(required(config, "material.expected_spacegroup_number"))
    symmetry_policy = required(config, "symmetry_validation")
    strict_tolerance = symmetry_policy.get(
        "post_standardization_strictest_required_matching_symprec_angstrom",
        symmetry_policy.get("strictest_required_matching_symprec_angstrom"),
    )
    if strict_tolerance is None:
        raise CampaignError("symmetry policy lacks a strict acceptance tolerance")
    symmetry_pass = any(
        math.isclose(item["symprec_angstrom"], float(strict_tolerance), rel_tol=0, abs_tol=1e-15)
        and item["spacegroup_number"] == expected_number
        for item in scan
    )
    settings = required(config, "tight_relax")
    accept_force = float(required(settings, "accept_max_force_ry_bohr"))
    hard_stop_force = float(required(settings, "hard_stop_max_force_ry_bohr"))
    max_shift = max(shifts)
    checks = {
        "relax_output_healthy": bool(relax_health["healthy"]),
        "pristine_output_healthy": bool(pristine_health["healthy"]),
        "bfgs_converged": bfgs_converged,
        "relax_force_within_acceptance": float(relax_health["max_abs_force_ry_bohr"]) <= accept_force,
        "pristine_force_within_acceptance": float(pristine_health["max_abs_force_ry_bohr"]) <= accept_force,
        "position_shift_within_limit": max_shift <= float(required(settings, "max_position_shift_angstrom")),
        "spacegroup_at_strict_tolerance": symmetry_pass,
    }
    report = {
        "material": required(config, "material.formula"),
        "created_utc": utc_now(),
        "pass": all(checks.values()),
        "checks": checks,
        "relax_output": relax_health,
        "pristine_output": pristine_health,
        "force_acceptance_ry_bohr": accept_force,
        "hard_stop_force_ry_bohr": hard_stop_force,
        "hard_stop_exceeded": max(
            float(relax_health["max_abs_force_ry_bohr"]),
            float(pristine_health["max_abs_force_ry_bohr"]),
        ) > hard_stop_force,
        "per_atom_position_shift_angstrom": shifts,
        "max_position_shift_angstrom": max_shift,
        "spacegroup_scan": scan,
        "final_unitcell_sha256": sha256_path(attempt / "pristine.in"),
        "limitations": [
            "This gate qualifies a structure for displacement preflight only.",
            "Supercell-force, amplitude, cutoff, q-mesh, and NAC convergence remain untested.",
        ],
    }
    write_json_immutable(attempt / "relax_gate.json", report)
    if not report["pass"]:
        raise CampaignError("tight-relax gate failed; attempt preserved for review")
    final_dir = run_dir / "relax" / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    write_immutable(final_dir / "unitcell.in", (attempt / "pristine.in").read_text())
    write_json_immutable(final_dir / "gate.json", report)
    write_json_immutable(
        final_dir / "provenance.json",
        {
            "accepted_attempt": str(attempt),
            "execution_manifest_sha256": sha256_path(attempt / "execution_manifest.json"),
            "starting_structure_audit_sha256": sha256_path(attempt / "starting_structure_audit.json"),
        },
    )
    return report


def analyze_displacement_yaml(value: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the exact systematic-displacement IDs encoded by phono3py."""

    pairs = required(value, "displacement_pairs")
    if not isinstance(pairs, list) or not pairs:
        raise CampaignError("phono3py YAML has no displacement_pairs dataset")
    all_ids: list[int] = []
    included_ids: list[int] = []
    vectors: list[tuple[float, float, float]] = []
    singles = 0
    included_pair_groups = 0
    excluded_pair_groups = 0
    for first_index, first in enumerate(pairs):
        if not isinstance(first, Mapping):
            raise CampaignError(f"invalid displacement_pairs[{first_index}]")
        displacement_id = required(first, "displacement_id")
        displacement = required(first, "displacement")
        if not isinstance(displacement_id, int) or displacement_id <= 0:
            raise CampaignError("invalid first-displacement ID")
        if not isinstance(displacement, list) or len(displacement) != 3:
            raise CampaignError("invalid first-displacement vector")
        vectors.append(tuple(float(component) for component in displacement))
        all_ids.append(displacement_id)
        included_ids.append(displacement_id)
        singles += 1
        paired_with = required(first, "paired_with")
        if not isinstance(paired_with, list):
            raise CampaignError("paired_with must be a list")
        for second in paired_with:
            second_vectors = required(second, "displacements")
            second_ids = required(second, "displacement_ids")
            included = required(second, "included")
            if not isinstance(included, bool):
                raise CampaignError("paired_with.included must be boolean")
            if (
                not isinstance(second_vectors, list)
                or not isinstance(second_ids, list)
                or len(second_vectors) != len(second_ids)
            ):
                raise CampaignError("paired displacement vectors and IDs differ in length")
            for vector in second_vectors:
                if not isinstance(vector, list) or len(vector) != 3:
                    raise CampaignError("invalid paired displacement vector")
                vectors.append(tuple(float(component) for component in vector))
            for displacement_id in second_ids:
                if not isinstance(displacement_id, int) or displacement_id <= 0:
                    raise CampaignError("invalid paired displacement ID")
            all_ids.extend(second_ids)
            if included:
                included_ids.extend(second_ids)
                included_pair_groups += 1
            else:
                excluded_pair_groups += 1
    if len(set(all_ids)) != len(all_ids):
        raise CampaignError("duplicate displacement IDs in phono3py YAML")
    expected_domain = set(range(1, len(all_ids) + 1))
    if set(all_ids) != expected_domain:
        raise CampaignError("phono3py displacement IDs are not the complete 1..N domain")
    # phono3py groups each first displacement with its (usually much later)
    # paired IDs, so traversal order is intentionally not global ID order.
    # Generated QE filenames, however, are compared in numeric ID order.
    included_ids_sorted = sorted(included_ids)
    return {
        "all_displacement_ids": all_ids,
        "included_displacement_ids": included_ids_sorted,
        "vectors": vectors,
        "single_displacements": singles,
        "included_pair_groups": included_pair_groups,
        "excluded_pair_groups": excluded_pair_groups,
    }


def parse_fragment(path: Path) -> tuple[int, tuple[tuple[float, float, float], ...], str]:
    text = path.read_text()
    nat_match = re.search(r"\bnat\s*=\s*(\d+)", text.splitlines()[0] if text.splitlines() else "")
    if not nat_match:
        raise CampaignError(f"cannot read nat from phono3py fragment: {path}")
    card = re.search(r"(?im)^\s*CELL_PARAMETERS\s+(?:\(|\{)?\s*(\w+)", text)
    if not card:
        raise CampaignError(f"missing CELL_PARAMETERS in {path}")
    rows = text[card.end() :].strip().splitlines()[:3]
    if len(rows) != 3:
        raise CampaignError(f"incomplete CELL_PARAMETERS in {path}")
    try:
        cell = tuple(tuple(float(token.replace("D", "E")) for token in row.split()[:3]) for row in rows)
    except ValueError as exc:
        raise CampaignError(f"invalid CELL_PARAMETERS in {path}") from exc
    if any(len(row) != 3 for row in cell):
        raise CampaignError(f"invalid CELL_PARAMETERS row in {path}")
    return int(nat_match.group(1)), cell, card.group(1).lower()


def shortest_lattice_translation(cell: Sequence[Sequence[float]]) -> float:
    shortest = math.inf
    for i in range(-2, 3):
        for j in range(-2, 3):
            for k in range(-2, 3):
                if (i, j, k) == (0, 0, 0):
                    continue
                vector = [i * cell[0][axis] + j * cell[1][axis] + k * cell[2][axis] for axis in range(3)]
                shortest = min(shortest, vector_norm(vector))
    return shortest


def command_preflight(config_path: Path, run_dir: Path) -> dict[str, Any]:
    require_compute_node()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    run_manifest = verify_manifest(config, config_path, run_dir, stage="preflight")
    attempt = attempt_dir(run_dir)
    unitcell = run_dir / "relax" / "final" / "unitcell.in"
    gate_path = run_dir / "relax" / "final" / "gate.json"
    if not unitcell.is_file() or not gate_path.is_file():
        raise CampaignError("accepted tight-relax unitcell and gate are required before preflight")
    gate = load_json(gate_path)
    if not gate.get("pass"):
        raise CampaignError("tight-relax gate is not passing")
    if gate.get("final_unitcell_sha256") != sha256_path(unitcell):
        raise CampaignError("accepted unitcell hash differs from tight-relax gate")
    provenance_path = run_dir / "relax" / "final" / "provenance.json"
    if not provenance_path.is_file():
        raise CampaignError("accepted tight-relax provenance is missing")
    provenance = load_json(provenance_path)
    accepted_attempt = Path(str(required(provenance, "accepted_attempt"))).resolve()
    try:
        accepted_attempt.relative_to(run_dir)
    except ValueError as exc:
        raise CampaignError("accepted tight-relax attempt points outside RUN_DIR") from exc
    execution_path = accepted_attempt / "execution_manifest.json"
    structure_audit_path = accepted_attempt / "starting_structure_audit.json"
    if not execution_path.is_file() or not structure_audit_path.is_file():
        raise CampaignError("accepted tight-relax attempt evidence is incomplete")
    if provenance.get("execution_manifest_sha256") != sha256_path(execution_path):
        raise CampaignError("accepted execution-manifest hash mismatch")
    if provenance.get("starting_structure_audit_sha256") != sha256_path(structure_audit_path):
        raise CampaignError("accepted starting-structure audit hash mismatch")
    try:
        import yaml
    except ImportError as exc:
        raise CampaignError("PyYAML is required in the phono3py environment") from exc

    displacements = required(config, "displacements")
    supercells = {item["id"]: item for item in required(config, "displacements.supercell_candidates")}
    cutoffs = {item["id"]: item for item in required(config, "displacements.cutoff_candidates")}
    amplitude = float(required(config, "displacements.amplitude_bohr"))
    tolerance = float(required(config, "software.symmetry_tolerance_cli_bohr"))
    hard_cap = int(required(config, "displacements.hard_cap"))
    primitive_axes = str(required(config, "displacements.primitive_axes"))
    results: list[dict[str, Any]] = []
    uncontracted: dict[str, int] = {}
    deferred_no_cutoff: list[dict[str, Any]] = []

    for enumeration in required(config, "displacements.enumerate"):
        supercell_id = enumeration.get("supercell_id", enumeration.get("fc3_supercell_id"))
        cutoff_id = enumeration.get("cutoff_pair_id")
        if cutoff_id is None:
            deferred_no_cutoff.append(enumeration)
            continue
        candidate = supercells[supercell_id]
        cutoff = cutoffs[cutoff_id]
        work = attempt / "candidates" / f"{supercell_id}__{cutoff_id}"
        work.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(unitcell, work / "unitcell.in")
        dim = [str(value) for row in matrix3(candidate["matrix"], "matrix") for value in row]
        command = [
            "phono3py-init", "--qe", "-d", "-c", "unitcell.in", "--pa", primitive_axes,
            "--tolerance", f"{tolerance:.15g}", "--amplitude", f"{amplitude:.15g}",
            "--cutoff-pair", f"{float(cutoff['cutoff_pair_distance_cli_bohr']):.15g}", "--dim", *dim,
        ]
        process = run_process(command, work, work / "phono3py.stdout.log", work / "phono3py.stderr.log")
        stdout = (work / "phono3py.stdout.log").read_text()
        total_match = re.search(r"Number of displacements:\s*(\d+)", stdout)
        created_match = re.search(r"Number of displacement supercell files created:\s*(\d+)", stdout)
        files = sorted(work.glob("supercell-[0-9]*.in"))
        if not total_match or not created_match:
            raise CampaignError(f"phono3py count markers missing for {supercell_id}/{cutoff_id}")
        total_count = int(total_match.group(1))
        created_count = int(created_match.group(1))
        if created_count != len(files):
            raise CampaignError(f"generated file count mismatch for {supercell_id}/{cutoff_id}")
        uncontracted[supercell_id] = total_count
        yaml_path = work / "phono3py_disp.yaml"
        if not yaml_path.is_file():
            raise CampaignError(f"phono3py_disp.yaml missing for {supercell_id}/{cutoff_id}")
        yaml_data = yaml.safe_load(yaml_path.read_text())
        length_unit = required(yaml_data, "physical_unit.length")
        if length_unit != "au":
            raise CampaignError(f"unexpected phono3py QE length unit {length_unit!r}")
        yaml_cutoff = positive_number(
            required(yaml_data, "displacement_pair_info.cutoff_pair_distance"),
            "YAML cutoff",
        )
        if not math.isclose(yaml_cutoff, float(cutoff["cutoff_pair_distance_cli_bohr"]), rel_tol=2e-8):
            raise CampaignError(f"YAML cutoff mismatch for {supercell_id}/{cutoff_id}")
        yaml_inventory = analyze_displacement_yaml(yaml_data)
        vectors = yaml_inventory["vectors"]
        if not vectors or any(not math.isclose(vector_norm(vector), amplitude, rel_tol=2e-6, abs_tol=2e-8) for vector in vectors):
            raise CampaignError(f"YAML displacement amplitude mismatch for {supercell_id}/{cutoff_id}")
        yaml_all_ids = yaml_inventory["all_displacement_ids"]
        yaml_included_ids = yaml_inventory["included_displacement_ids"]
        file_ids = [int(path.stem.split("-")[-1]) for path in files]
        if len(yaml_all_ids) != total_count:
            raise CampaignError(f"uncontracted YAML ID count mismatch for {supercell_id}/{cutoff_id}")
        if yaml_included_ids != file_ids:
            raise CampaignError(f"generated file IDs differ from YAML included IDs for {supercell_id}/{cutoff_id}")
        pristine = work / "supercell.in"
        nat, cell, cell_unit = parse_fragment(pristine)
        if nat != candidate["atoms"]:
            raise CampaignError(f"generated atom count mismatch for {supercell_id}: {nat}")
        if cell_unit not in {"bohr", "au"}:
            raise CampaignError(f"unexpected QE fragment cell unit: {cell_unit}")
        stored_matrix = matrix3(required(yaml_data, "supercell_matrix"), "YAML supercell_matrix")
        configured_matrix = matrix3(candidate["matrix"], "configured supercell matrix")
        if stored_matrix != configured_matrix:
            raise CampaignError(f"YAML supercell matrix differs from config for {supercell_id}")
        accepted_cell_angstrom = parse_qe_input(unitcell.read_text()).cell_parameters
        expected_cell_bohr = tuple(
            tuple(
                sum(
                    configured_matrix[source_row][output_row]
                    * accepted_cell_angstrom[source_row][axis]
                    for source_row in range(3)
                )
                / BOHR_TO_ANGSTROM
                for axis in range(3)
            )
            for output_row in range(3)
        )
        if any(
            not math.isclose(generated, expected, rel_tol=0, abs_tol=2e-7)
            for generated_row, expected_row in zip(cell, expected_cell_bohr)
            for generated, expected in zip(generated_row, expected_row)
        ):
            raise CampaignError(
                f"generated lattice violates A_super=M^T A convention for {supercell_id}"
            )
        generated_lengths_angstrom = [
            vector_norm(row) * BOHR_TO_ANGSTROM for row in cell
        ]
        reference_lengths = candidate.get(
            "reference_generated_edge_lengths_angstrom",
            candidate.get("reference_edge_lengths_angstrom"),
        )
        reference_lengths_match = True
        if reference_lengths is not None:
            reference_lengths_match = all(
                math.isclose(generated, float(reference), rel_tol=0, abs_tol=5e-4)
                for generated, reference in zip(generated_lengths_angstrom, reference_lengths)
            )
            if not reference_lengths_match:
                raise CampaignError(f"generated edge lengths differ from config for {supercell_id}")
        volume_ratio = abs(determinant(cell)) / (
            abs(determinant(accepted_cell_angstrom)) / BOHR_TO_ANGSTROM**3
        )
        expected_det = abs(round(determinant(candidate["matrix"])))
        if not math.isclose(volume_ratio, expected_det, rel_tol=2e-6):
            raise CampaignError(f"generated volume ratio mismatch for {supercell_id}: {volume_ratio}")
        result = {
            "supercell_id": supercell_id,
            "cutoff_id": cutoff_id,
            "cutoff_pair_distance_angstrom": cutoff["cutoff_pair_distance_angstrom"],
            "cutoff_pair_distance_cli_bohr": cutoff["cutoff_pair_distance_cli_bohr"],
            "uncontracted_displacements": total_count,
            "generated_displacement_supercells": created_count,
            "single_displacements": yaml_inventory["single_displacements"],
            "included_pair_groups": yaml_inventory["included_pair_groups"],
            "excluded_pair_groups": yaml_inventory["excluded_pair_groups"],
            "generated_displacement_ids": yaml_included_ids,
            "hard_cap": hard_cap,
            "within_hard_cap": created_count <= hard_cap,
            "generated_atoms": nat,
            "cell_vectors_bohr": cell,
            "cell_edge_lengths_angstrom": generated_lengths_angstrom,
            "expected_cell_vectors_bohr_from_M_transpose_A": expected_cell_bohr,
            "reference_edge_lengths_match": reference_lengths_match,
            "shortest_lattice_translation_angstrom": shortest_lattice_translation(cell) * BOHR_TO_ANGSTROM,
            "inscribed_sphere_radius_angstrom": shortest_lattice_translation(cell) * BOHR_TO_ANGSTROM / 2,
            "volume_ratio": volume_ratio,
            "yaml_length_unit": length_unit,
            "yaml_sha256": sha256_path(yaml_path),
            "unitcell_sha256": sha256_path(work / "unitcell.in"),
            "process": process,
            "count_only": bool(enumeration.get("count_only")),
        }
        write_json_immutable(work / "preflight_result.json", result)
        results.append(result)

    for enumeration in deferred_no_cutoff:
        supercell_id = enumeration.get("supercell_id", enumeration.get("fc3_supercell_id"))
        if supercell_id not in uncontracted:
            raise CampaignError(f"no cutoff run supplied uncontracted count for {supercell_id}")
        results.append(
            {
                "supercell_id": supercell_id,
                "cutoff_id": None,
                "count_only_no_cutoff": True,
                "uncontracted_displacements": uncontracted[supercell_id],
                "generated_displacement_supercells": None,
                "derivation": "Number of displacements printed by a cutoff-pair run for the same supercell; no uncut file explosion was generated.",
                "within_hard_cap": uncontracted[supercell_id] <= hard_cap,
                "hard_cap": hard_cap,
            }
        )

    passed = all(item.get("within_hard_cap", False) for item in results if item.get("cutoff_id") is not None)
    inventory = {
        "stage": "preflight",
        "material": required(config, "material.formula"),
        "created_utc": utc_now(),
        "preflight_policy_sha256": run_manifest["preflight_policy_sha256"],
        "accepted_unitcell_sha256": sha256_path(unitcell),
        "accepted_relax_provenance_sha256": sha256_path(provenance_path),
        "pass_hard_caps": passed,
        "production_selection_still_required": True,
        "results": results,
        "limitations": [
            "Counts and geometry checks are preflight results, not force convergence.",
            "No force-array or thermal-conductivity calculation was submitted by this command.",
        ],
    }
    write_json_immutable(attempt / "preflight_inventory.json", inventory)
    if not passed:
        raise CampaignError("one or more preflight candidates exceed the configured hard cap")
    return inventory


def command_status(config_path: Path, run_dir: Path) -> dict[str, Any]:
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    status: dict[str, Any] = {
        "material": required(config, "material.formula"),
        "run_dir": str(run_dir),
        "prepared": (run_dir / RUN_MANIFEST).is_file(),
        "tight_relax_accepted": False,
        "preflight_attempts": 0,
        "production_selection_required": required(config, "production.selection_required"),
        "selected_supercell": required(config, "production.selected_supercell"),
        "selected_cutoff": required(config, "production.selected_cutoff"),
    }
    gate = run_dir / "relax" / "final" / "gate.json"
    if gate.is_file():
        gate_data = load_json(gate)
        status["tight_relax_accepted"] = bool(gate_data.get("pass"))
        status["tight_relax_gate"] = gate_data
    attempts = run_dir / "slurm_attempts" / "preflight"
    if attempts.is_dir():
        inventories = list(attempts.glob("*/preflight_inventory.json"))
        status["preflight_attempts"] = len(inventories)
        status["preflight_inventories"] = [str(path) for path in sorted(inventories)]
    return status


def command_collect(config_path: Path, run_dir: Path) -> dict[str, Any]:
    """Collect immutable attempt evidence without rerunning failed science."""

    require_compute_node()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    verify_manifest(config, config_path, run_dir, stage="preflight")
    current_attempt = attempt_dir(run_dir)
    attempts_root = run_dir / "slurm_attempts"
    entries: list[dict[str, Any]] = []
    if attempts_root.is_dir():
        for context_path in sorted(attempts_root.glob("**/context.tsv")):
            parent = context_path.parent
            if parent == current_attempt:
                continue
            relative = parent.relative_to(attempts_root)
            parts = relative.parts
            entry: dict[str, Any] = {
                "attempt_path": str(parent),
                "stage": parts[0] if parts else None,
                "attempt_id": parts[1] if len(parts) > 1 else None,
                "task": parts[2] if len(parts) > 2 else None,
                "context_sha256": sha256_path(context_path),
            }
            exit_code = parent / "exit_code.txt"
            entry["finished"] = exit_code.is_file()
            if exit_code.is_file():
                try:
                    entry["exit_code"] = int(exit_code.read_text().strip())
                except ValueError:
                    entry["exit_code"] = None
                    entry["exit_code_error"] = "not an integer"
            evidence: dict[str, Any] = {}
            for name in (
                "starting_structure_audit.json",
                "relax_launch.json",
                "relax.process.json",
                "relax.out",
                "pristine_launch.json",
                "pristine.process.json",
                "pristine.out",
                "execution_manifest.json",
                "relax_gate.json",
                "preflight_inventory.json",
            ):
                path = parent / name
                if path.is_file():
                    evidence[name] = {"sha256": sha256_path(path), "bytes": path.stat().st_size}
            entry["evidence"] = evidence
            if (parent / "relax.out").is_file():
                try:
                    entry["relax_health"] = inspect_output(
                        parent / "relax.out",
                        int(required(config, "material.unitcell_atoms")),
                    )
                except (QEOutputError, OSError, ValueError) as exc:
                    entry["relax_health"] = {"healthy": False, "error": str(exc)}
            if (parent / "pristine.out").is_file():
                try:
                    entry["pristine_health"] = inspect_output(
                        parent / "pristine.out",
                        int(required(config, "material.unitcell_atoms")),
                    )
                except (QEOutputError, OSError, ValueError) as exc:
                    entry["pristine_health"] = {"healthy": False, "error": str(exc)}
            entries.append(entry)
    report = {
        "material": required(config, "material.formula"),
        "collected_utc": utc_now(),
        "collector_attempt": str(current_attempt),
        "upstream_attempt_count": len(entries),
        "upstream_failures_or_unfinished": sum(
            1 for entry in entries if entry.get("exit_code") != 0
        ),
        "entries": entries,
        "note": "Collection is evidentiary and succeeds even when an upstream afterany dependency failed.",
    }
    write_json_immutable(current_attempt / "collection.json", report)
    return report


def command_not_ready(name: str, config: Mapping[str, Any]) -> None:
    if required(config, "production.selection_required"):
        raise CampaignError(
            f"{name} is blocked: production selection is intentionally null until tight-relax, "
            "preflight, and force/amplitude pilots pass"
        )
    raise CampaignError(f"{name} implementation is not yet released for production use")


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "validate-config",
        "prepare-relax",
        "run-relax",
        "finalize-relax",
        "preflight",
        "prepare-force",
        "collect",
        "postprocess",
        "audit",
        "status",
    ):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--config", type=Path, required=True)
        subparser.add_argument("--run-dir", type=Path, required=name != "validate-config")
        if name == "run-relax":
            pass
    force_task = subparsers.add_parser("run-force-task")
    force_task.add_argument("--config", type=Path, required=True)
    force_task.add_argument("--run-dir", type=Path, required=True)
    force_task.add_argument("--task-map", type=Path, required=True)
    force_task.add_argument("--task-id", type=int, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "validate-config":
            _, report = validate_config(args.config)
            print_json(report)
            return 0
        run_dir = safe_run_dir(args.run_dir)
        if args.command == "prepare-relax":
            result = command_prepare_relax(args.config, run_dir)
        elif args.command == "preflight":
            result = command_preflight(args.config, run_dir)
        elif args.command == "status":
            result = command_status(args.config, run_dir)
        elif args.command == "collect":
            result = command_collect(args.config, run_dir)
        elif args.command == "run-relax":
            result = command_run_relax(args.config, run_dir)
        elif args.command == "finalize-relax":
            result = command_finalize_relax(args.config, run_dir)
        else:
            config, _ = validate_config(args.config)
            command_not_ready(args.command, config)
            raise AssertionError("unreachable")
        print_json(result)
        return 0
    except (CampaignError, QEInputError, QEOutputError, OSError, ValueError) as exc:
        print_json({"healthy": False, "command": args.command, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed QE/phono3py campaign driver for the two pending materials.

Heavy subcommands refuse to run outside a SLURM allocation.  Material JSON is
the scientific authority; this shared driver supplies provenance, immutable
attempt handling, strict gates, and calculator orchestration without silently
borrowing settings from SrCu2SnS4.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
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
    validate_bfgs_parameters,
)
from qe_output import QEOutputError, inspect_output


# When this file is executed as a script, downstream backends import it by the
# stable module name ``campaign``.  Reuse this already-running module so its
# exception classes and immutable-write helpers are not loaded a second time.
sys.modules.setdefault("campaign", sys.modules[__name__])


REPO_ROOT = Path(__file__).resolve().parents[3]
BOHR_TO_ANGSTROM = 0.529177210903
# phonopy/phono3py 4.4.0 writes QE cells using an older CODATA Bohr value
# (0.529177207423948 A).  Compare generated and independently reconstructed
# supercell vectors tightly enough to reject a wrong matrix, while allowing
# that harmless ~6.6e-9 relative unit-conversion difference.
SUPERCELL_LATTICE_REL_TOL = 1e-8
SUPERCELL_LATTICE_ABS_TOL_BOHR = 2e-8
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


def preflight_candidate_id(enumeration: Mapping[str, Any]) -> str:
    """Return the stable public identity of one configured preflight row."""

    supercell_id = enumeration.get(
        "supercell_id", enumeration.get("fc3_supercell_id")
    )
    cutoff_id = enumeration.get("cutoff_pair_id")
    if not isinstance(supercell_id, str) or not supercell_id:
        raise CampaignError("preflight enumeration has no valid supercell id")
    if cutoff_id is not None and (not isinstance(cutoff_id, str) or not cutoff_id):
        raise CampaignError("preflight enumeration has an invalid cutoff id")
    suffix = cutoff_id if cutoff_id is not None else "no_cutoff"
    candidate_id = f"{supercell_id}__{suffix}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", candidate_id) is None:
        raise CampaignError(f"unsafe preflight candidate id: {candidate_id!r}")
    return candidate_id


def select_preflight_candidates(
    config: Mapping[str, Any], candidate_ids: Sequence[str] | None
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Resolve and sign an all-candidate or explicit subset preflight plan."""

    enumerations = required(config, "displacements.enumerate")
    if not isinstance(enumerations, list) or not enumerations:
        raise CampaignError("displacements.enumerate must be a nonempty list")
    configured: dict[str, Mapping[str, Any]] = {}
    configured_order: list[str] = []
    for enumeration in enumerations:
        if not isinstance(enumeration, Mapping):
            raise CampaignError("preflight enumeration rows must be objects")
        candidate_id = preflight_candidate_id(enumeration)
        if candidate_id in configured:
            raise CampaignError(
                f"preflight candidate is not unique in config enumerate: {candidate_id}"
            )
        configured[candidate_id] = enumeration
        configured_order.append(candidate_id)

    explicit_subset = candidate_ids is not None
    if explicit_subset:
        requested = list(candidate_ids)
        if not requested:
            raise CampaignError("explicit preflight candidate subset must be nonempty")
        if any(not isinstance(item, str) or not item for item in requested):
            raise CampaignError("preflight candidate ids must be nonempty strings")
        if len(set(requested)) != len(requested):
            raise CampaignError("preflight candidate subset contains duplicates")
        unknown = [item for item in requested if item not in configured]
        if unknown:
            raise CampaignError(
                "preflight candidate subset is not uniquely present in config enumerate: "
                + ", ".join(unknown)
            )
        requested_set = set(requested)
        selected_ids = [item for item in configured_order if item in requested_set]
    else:
        selected_ids = configured_order

    signature_payload = {
        "schema_version": 1,
        "mode": "explicit_subset" if explicit_subset else "all_configured",
        "candidate_ids": selected_ids,
        "preflight_policy_sha256": policy_sha256(config, "preflight"),
    }
    selection = {
        **signature_payload,
        "candidate_subset_sha256": canonical_sha256(signature_payload),
        "configured_candidate_count": len(configured_order),
    }
    return [configured[item] for item in selected_ids], selection


def derive_no_cutoff_preflight_results(
    enumerations: Sequence[Mapping[str, Any]],
    uncontracted: Mapping[str, int],
    hard_cap: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Derive no-cutoff count bounds only from selected, completed parents."""

    results: list[dict[str, Any]] = []
    skipped: list[str] = []
    for enumeration in enumerations:
        supercell_id = enumeration.get(
            "supercell_id", enumeration.get("fc3_supercell_id")
        )
        candidate_id = preflight_candidate_id(enumeration)
        if supercell_id not in uncontracted:
            skipped.append(candidate_id)
            continue
        results.append(
            {
                "candidate_id": candidate_id,
                "supercell_id": supercell_id,
                "cutoff_id": None,
                "count_only_no_cutoff": True,
                "uncontracted_displacements": uncontracted[supercell_id],
                "generated_displacement_supercells": None,
                "derivation": "Number of displacements printed by a selected cutoff-pair run for the same supercell; no uncut file explosion was generated.",
                "within_hard_cap": uncontracted[supercell_id] <= hard_cap,
                "hard_cap": hard_cap,
            }
        )
    return results, skipped


def preflight_completion_fields(selection: Mapping[str, Any]) -> dict[str, bool]:
    """Keep targeted count evidence distinct from a full configured preflight."""

    mode = selection.get("mode")
    if mode not in {"all_configured", "explicit_subset"}:
        raise CampaignError("preflight candidate selection mode is invalid")
    full = mode == "all_configured"
    return {
        # Compatibility alias retains its historical full-enumeration meaning.
        "preflight_complete": full,
        "requested_scope_complete": True,
        "full_config_preflight_complete": full,
    }


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


def strict_run_descendant(
    run_dir: Path,
    path: Path,
    label: str,
    *,
    require_exists: bool = True,
) -> Path:
    """Prove strict RUN_DIR containment while lstat-rejecting every symlink."""

    lexical_root = Path(os.path.abspath(run_dir))
    root = safe_run_dir(run_dir).resolve(strict=True)
    candidate_input = Path(os.path.abspath(path))
    if candidate_input.is_relative_to(lexical_root):
        relative = candidate_input.relative_to(lexical_root)
    elif candidate_input.is_relative_to(root):
        relative = candidate_input.relative_to(root)
    else:
        alias_root = None
        for ancestor in (candidate_input, *candidate_input.parents):
            try:
                if stat.S_ISLNK(os.lstat(ancestor).st_mode):
                    raise CampaignError(
                        f"{label} path contains a symlink: {ancestor}"
                    )
                if os.path.samefile(ancestor, root):
                    alias_root = ancestor
                    break
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
        if alias_root is None:
            raise CampaignError(f"{label} must be a strict descendant of RUN_DIR")
        relative = candidate_input.relative_to(alias_root)
    if not relative.parts:
        raise CampaignError(f"{label} must be a strict descendant of RUN_DIR")
    candidate = root / relative
    current = root
    missing = False
    for part in candidate.relative_to(root).parts:
        current = current / part
        if missing:
            continue
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            missing = True
            continue
        if stat.S_ISLNK(mode):
            raise CampaignError(f"{label} path contains a symlink: {current}")
    if require_exists and missing:
        raise CampaignError(f"{label} does not exist: {candidate}")
    resolved = candidate.resolve(strict=require_exists)
    if resolved == root or not resolved.is_relative_to(root):
        raise CampaignError(f"{label} resolves outside RUN_DIR")
    if "READY_TO_ATTACH" in resolved.parts:
        raise CampaignError(f"{label} may not use frozen attachment evidence")
    return candidate


def reject_symlinks_below(run_dir: Path, root: Path, label: str) -> None:
    root = strict_run_descendant(run_dir, root, label, require_exists=True)
    if not root.is_dir():
        raise CampaignError(f"{label} is not a directory: {root}")
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            strict_run_descendant(
                run_dir,
                Path(parent) / name,
                label,
                require_exists=True,
            )


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

        enumeration_ids: set[str] = set()
        enumerations = required(config, "displacements.enumerate")
        check(
            isinstance(enumerations, list) and bool(enumerations),
            "displacements.enumerate must be a nonempty list",
        )
        for index, item in enumerate(enumerations):
            check(isinstance(item, Mapping), f"enumerate[{index}] must be an object")
            if not isinstance(item, Mapping):
                continue
            supercell_id = item.get("supercell_id", item.get("fc3_supercell_id"))
            cutoff_id = item.get("cutoff_pair_id")
            check(supercell_id in supercells, f"enumerate[{index}] unknown supercell {supercell_id!r}")
            check(cutoff_id is None or cutoff_id in cutoff_ids, f"enumerate[{index}] unknown cutoff {cutoff_id!r}")
            candidate_id = preflight_candidate_id(item)
            check(
                candidate_id not in enumeration_ids,
                f"duplicate preflight candidate id {candidate_id!r}",
            )
            enumeration_ids.add(candidate_id)

        hard_cap = required(config, "displacements.hard_cap")
        check(isinstance(hard_cap, int) and not isinstance(hard_cap, bool) and hard_cap > 0, "hard_cap must be positive integer")

        force_policy = required(config, "force_and_amplitude_validation")
        check(isinstance(force_policy, Mapping), "force_and_amplitude_validation must be an object")
        force_selection_required = required(
            config, "force_and_amplitude_validation.selection_required"
        )
        check(
            isinstance(force_selection_required, bool),
            "force_and_amplitude_validation.selection_required must be boolean",
        )
        symmetry_flags = required(
            config, "force_and_amplitude_validation.production_symmetry_flags"
        )
        check(
            isinstance(symmetry_flags, Mapping)
            and symmetry_flags.get("nosym") is True
            and symmetry_flags.get("noinv") is True
            and symmetry_flags.get(
                "use_identically_for_pristine_pilots_and_all_displacements"
            )
            is True,
            "force calculations and matched pristine must use nosym/noinv identically",
        )
        amplitude_policy = required(
            config, "force_and_amplitude_validation.amplitude_pilot"
        )
        candidates = required(
            config,
            "force_and_amplitude_validation.amplitude_pilot.displacement_distance_candidates",
        )
        check(
            isinstance(candidates, list) and len(candidates) >= 3,
            "amplitude pilot must contain at least three displacement candidates",
        )
        seen_amplitudes: set[float] = set()
        for index, candidate in enumerate(candidates):
            candidate_a = positive_number(
                required(candidate, "displacement_distance_angstrom"),
                f"amplitude candidate[{index}] angstrom",
            )
            candidate_b = positive_number(
                required(candidate, "displacement_distance_cli_bohr"),
                f"amplitude candidate[{index}] bohr",
            )
            check(
                math.isclose(candidate_a / factor, candidate_b, rel_tol=FLOAT_REL_TOL),
                f"amplitude candidate conversion mismatch: {candidate_a}",
            )
            check(candidate_a not in seen_amplitudes, "duplicate amplitude candidate")
            seen_amplitudes.add(candidate_a)
        check(
            amplitude_policy.get("positive_and_negative_displacements_required") is True,
            "amplitude pilot must require positive and negative displacements",
        )
        check(
            amplitude_policy.get("double_displacement_four_sign_combinations_required")
            is True,
            "amplitude pilot must require all four double-displacement signs",
        )
        check(
            amplitude_policy.get("symmetry_inequivalent_site_coverage_required") is True,
            "amplitude pilot must require symmetry-inequivalent site coverage",
        )
        representative_species = amplitude_policy.get("representative_species")
        representative_pairs = amplitude_policy.get("representative_pair_shells")
        check(
            isinstance(representative_species, list)
            and representative_species
            and all(isinstance(item, str) and item for item in representative_species),
            "amplitude pilot representative_species must be a nonempty string list",
        )
        check(
            isinstance(representative_pairs, list)
            and representative_pairs
            and all(isinstance(item, str) and item for item in representative_pairs),
            "amplitude pilot representative_pair_shells must be a nonempty string list",
        )
        amplitude_acceptance = required(
            config, "force_and_amplitude_validation.amplitude_pilot.acceptance"
        )
        for key in (
            "minimum_induced_force_signal_to_duplicate_noise",
            "maximum_relative_change_of_central_force_slope",
            "maximum_relative_change_of_mixed_second_force_derivative",
            "minimum_mixed_difference_numerator_signal_to_propagated_duplicate_noise",
            "maximum_duplicate_RMS_force_difference_Ry_per_bohr",
        ):
            positive_number(required(amplitude_acceptance, key), key)
        check(
            amplitude_acceptance.get("below_resolution_action")
            == "choose_a_nonzero_signal_probe_or_require_scientific_review; do_not_pass_or_fail_by_relative_error",
            "below-resolution amplitude policy must fail closed",
        )

        budget = required(config, "resource_budget")
        check(isinstance(budget, Mapping), "resource_budget must be an object")
        budget_selection_required = required(
            config, "resource_budget.selection_required_before_force_submission"
        )
        check(
            isinstance(budget_selection_required, bool),
            "resource budget selection flag must be boolean",
        )
        approved_core_hours = required(
            config, "resource_budget.approved_total_core_hours_per_material"
        )
        if budget_selection_required:
            check(
                approved_core_hours is None,
                "approved core hours must be null while budget selection is required",
            )
        else:
            positive_number(approved_core_hours, "approved total core hours")
        initial_batch = required(config, "resource_budget.initial_timing_and_noise_batch")
        for mapping, key, label in (
            (initial_batch, "maximum_new_scf_tasks", "initial timing task limit"),
            (
                initial_batch,
                "maximum_concurrent_force_tasks_per_material",
                "initial timing concurrency limit",
            ),
            (budget, "pilot_batch_maximum_new_scf_tasks", "pilot task limit"),
            (budget, "production_first_batch_maximum_tasks", "first production batch limit"),
            (budget, "production_later_batch_maximum_tasks", "later production batch limit"),
        ):
            value = required(mapping, key)
            check(
                isinstance(value, int) and not isinstance(value, bool) and value > 0,
                f"{label} must be a positive integer",
            )
        retry_limit = required(config, "resource_budget.maximum_technical_retries_per_task")
        check(
            isinstance(retry_limit, int)
            and not isinstance(retry_limit, bool)
            and retry_limit == 1,
            "campaign permits exactly one technical retry per force task",
        )
        required_measured = required(config, "resource_budget.required_measured_fields")
        expected_measured = {
            "elapsed_seconds",
            "max_rss",
            "scf_iterations",
            "mpi_ranks",
            "raw_max_force",
            "total_scf_correction",
        }
        check(
            isinstance(required_measured, list)
            and set(required_measured) == expected_measured,
            "resource budget measured-field contract is incomplete",
        )
        check(
            budget.get("budget_exceedance_action")
            == "stop_and_require_explicit_budget_review",
            "budget exceedance must stop for explicit review",
        )

        integer_triplet(required(config, "tight_relax.kmesh"), "tight_relax.kmesh", positive=True)
        integer_triplet(required(config, "tight_relax.kmesh_shift"), "tight_relax.kmesh_shift")
        force_target = positive_number(required(config, "tight_relax.accept_max_force_ry_bohr"), "accept force")
        force_stop = positive_number(required(config, "tight_relax.hard_stop_max_force_ry_bohr"), "hard-stop force")
        check(force_target < force_stop, "accept force must be below hard-stop force")
        check(required(config, "tight_relax.cell_fixed") is True, "tight relax must keep cell fixed")
        polish_policy = config.get("reviewed_bfgs_polish")
        if polish_policy is not None:
            check(isinstance(polish_policy, Mapping), "reviewed_bfgs_polish must be an object")
            if not isinstance(polish_policy, Mapping):
                raise CampaignError("reviewed_bfgs_polish must be an object")
            check(
                polish_policy.get("status")
                == "reviewed_planned_hypothesis_not_validated",
                "BFGS polish settings must remain labeled as a reviewed, unvalidated hypothesis",
            )
            check(polish_policy.get("automatic_submission_allowed") is False,
                  "BFGS polish automatic submission must be false")
            check(polish_policy.get("maximum_polish_attempts") == 1,
                  "BFGS polish must allow exactly one attempt")
            check(
                polish_policy.get("source_requirement")
                == "terminal_one_reset_BFGS_failure_with_original_recovery_lineage",
                "BFGS polish must require the terminal one-reset lineage",
            )
            check(polish_policy.get("fresh_run_dir_required") is True,
                  "BFGS polish must require a fresh RUN_DIR")
            check(polish_policy.get("fresh_qe_scratch_required") is True,
                  "BFGS polish must require fresh QE scratch")
            check(
                polish_policy.get("preserve_original_standardized_geometry_as_cumulative_shift_reference") is True,
                "BFGS polish must preserve the original cumulative-shift reference",
            )
            parameters = required(polish_policy, "bfgs_parameters")
            if not isinstance(parameters, Mapping):
                raise CampaignError("reviewed_bfgs_polish.bfgs_parameters must be an object")
            validate_bfgs_parameters(
                bfgs_ndim=parameters.get("bfgs_ndim"),
                trust_radius_ini=parameters.get("trust_radius_ini"),
                trust_radius_min=parameters.get("trust_radius_min"),
                trust_radius_max=parameters.get("trust_radius_max"),
            )
            check(parameters.get("units") == "bohr", "BFGS trust radii must be labeled in bohr")
            check(
                parameters.get("validation_status")
                == "reviewed_planned_values_not_calculated_results",
                "BFGS polish values must remain labeled as planned, not results",
            )
            diagnostic = required(polish_policy, "force_consistency_diagnostic")
            check(isinstance(diagnostic, Mapping), "force-consistency diagnostic must be an object")
            if not isinstance(diagnostic, Mapping):
                raise CampaignError("force-consistency diagnostic must be an object")
            check(diagnostic.get("baseline_repetitions") == 2,
                  "force-consistency diagnostic requires exactly two baseline SCFs")
            baseline_rho = positive_number(
                diagnostic.get("baseline_ecutrho_ry"), "diagnostic baseline ecutrho"
            )
            higher_rho = positive_number(
                diagnostic.get("higher_ecutrho_ry"), "diagnostic higher ecutrho"
            )
            check(
                math.isclose(baseline_rho, float(required(config, "tight_relax.ecutrho_ry")), rel_tol=0, abs_tol=1e-12),
                "diagnostic baseline ecutrho must equal tight-relax ecutrho",
            )
            check(higher_rho > baseline_rho,
                  "diagnostic higher ecutrho must exceed its baseline")
            diagnostic_ecutwfc = positive_number(
                diagnostic.get("ecutwfc_ry"), "diagnostic ecutwfc"
            )
            check(
                math.isclose(diagnostic_ecutwfc, float(required(config, "tight_relax.ecutwfc_ry")), rel_tol=0, abs_tol=1e-12),
                "diagnostic ecutwfc must equal tight-relax ecutwfc",
            )
            check(
                integer_triplet(diagnostic.get("kmesh"), "diagnostic kmesh", positive=True)
                == integer_triplet(required(config, "tight_relax.kmesh"), "tight_relax.kmesh", positive=True),
                "diagnostic kmesh must equal tight-relax kmesh",
            )
            diagnostic_conv = positive_number(
                diagnostic.get("conv_thr_ry"), "diagnostic conv_thr"
            )
            check(
                math.isclose(diagnostic_conv, float(required(config, "tight_relax.conv_thr_ry")), rel_tol=0, abs_tol=0),
                "diagnostic conv_thr must equal tight-relax conv_thr",
            )
            check(diagnostic.get("nosym") is True and diagnostic.get("noinv") is True,
                  "diagnostic SCFs must use nosym/noinv")
            check(diagnostic.get("fresh_scratch_per_scf") is True,
                  "diagnostic SCFs must each use fresh scratch")
            check(diagnostic.get("all_criteria_required") is True,
                  "all force-consistency diagnostic criteria must be required")
            check(
                diagnostic.get("acceptance_scope")
                == "diagnostic_release_only_never_structure_acceptance_or_preflight",
                "force-consistency diagnostic must not accept a structure or preflight",
            )
            positive_number(
                diagnostic.get("maximum_duplicate_rms_difference_ry_bohr"),
                "diagnostic duplicate-noise threshold",
            )
            positive_number(
                diagnostic.get("maximum_higher_ecutrho_component_difference_ry_bohr"),
                "diagnostic higher-ecutrho component threshold",
            )
            positive_number(
                diagnostic.get("maximum_higher_ecutrho_rms_difference_ry_bohr"),
                "diagnostic higher-ecutrho RMS threshold",
            )
            resources = required(config, "scheduler.diagnostic_resources")
            check(
                isinstance(resources, Mapping),
                "scheduler.diagnostic_resources must be an object",
            )
            if not isinstance(resources, Mapping):
                raise CampaignError("scheduler.diagnostic_resources must be an object")
            partition = resources.get("partition")
            check(
                isinstance(partition, str)
                and re.fullmatch(r"[A-Za-z0-9_.-]+", partition) is not None,
                "diagnostic partition is invalid",
            )
            for key in ("nodes", "ntasks", "cpus_per_task", "mem_per_cpu_mb"):
                value = resources.get(key)
                check(
                    isinstance(value, int) and not isinstance(value, bool) and value > 0,
                    f"diagnostic {key} must be a positive integer",
                )
            walltime_hours = positive_number(
                resources.get("walltime_hours"), "diagnostic walltime hours"
            )
            check(
                math.isclose(
                    walltime_hours * 60,
                    round(walltime_hours * 60),
                    rel_tol=0,
                    abs_tol=1e-12,
                ),
                "diagnostic walltime must be exactly representable in whole minutes",
            )
            maximum_core_hours = positive_number(
                resources.get("maximum_core_hours"), "diagnostic maximum core hours"
            )
            if all(
                isinstance(resources.get(key), int)
                and not isinstance(resources.get(key), bool)
                for key in ("ntasks", "cpus_per_task")
            ):
                check(
                    math.isclose(
                        maximum_core_hours,
                        float(resources["ntasks"])
                        * float(resources["cpus_per_task"])
                        * walltime_hours,
                        rel_tol=0,
                        abs_tol=1e-12,
                    ),
                    "diagnostic maximum_core_hours must equal ntasks * cpus_per_task * walltime_hours",
                )
            check(
                resources.get("basis")
                == "conservative_bound_from_nibi_job_21656285_not_a_scientific_result",
                "diagnostic resource basis must preserve its measured-job provenance and non-result label",
            )
        selection_required = required(config, "production.selection_required")
        selected_supercell = required(config, "production.selected_supercell")
        selected_cutoff = required(config, "production.selected_cutoff")
        check(isinstance(selection_required, bool), "production.selection_required must be boolean")
        if selection_required:
            check(selected_supercell is None, "selected_supercell must be null while selection is required")
            check(selected_cutoff is None, "selected_cutoff must be null while selection is required")
            check(
                required(config, "production.automatic_submission_allowed") is False,
                "automatic production submission must be false while selection is required",
            )
        else:
            check(selected_supercell in supercells, "selected_supercell is not a configured candidate")
            check(selected_cutoff in cutoff_ids, "selected_cutoff is not a configured candidate")
            check(
                required(config, "production.automatic_submission_allowed") is True,
                "automatic production submission must be explicitly true after selection",
            )
        selected_force_fields = (
            "selected_displacement_distance_angstrom",
            "selected_displacement_distance_cli_bohr",
            "selected_ecutwfc_Ry",
            "selected_ecutrho_Ry",
            "selected_conv_thr_Ry",
            "selected_k_points",
        )
        if force_selection_required:
            check(
                all(force_policy.get(key) is None for key in selected_force_fields),
                "selected force settings must be null while force selection is required",
            )
        else:
            selected_a = positive_number(
                force_policy.get("selected_displacement_distance_angstrom"),
                "selected force amplitude angstrom",
            )
            selected_b = positive_number(
                force_policy.get("selected_displacement_distance_cli_bohr"),
                "selected force amplitude bohr",
            )
            check(
                math.isclose(selected_a / factor, selected_b, rel_tol=FLOAT_REL_TOL),
                "selected force amplitude conversion mismatch",
            )
            positive_number(force_policy.get("selected_ecutwfc_Ry"), "selected ecutwfc")
            selected_ecutrho = positive_number(
                force_policy.get("selected_ecutrho_Ry"), "selected ecutrho"
            )
            check(
                selected_ecutrho >= float(force_policy["selected_ecutwfc_Ry"]),
                "selected ecutrho must be at least selected ecutwfc",
            )
            positive_number(force_policy.get("selected_conv_thr_Ry"), "selected conv_thr")
            integer_triplet(
                force_policy.get("selected_k_points"),
                "selected force k points",
                positive=True,
            )
        check(
            force_selection_required == selection_required,
            "production and force selections must remain gated together",
        )
        if required(config, "nac.enabled_for_first_pass") is False:
            check(
                required(config, "nac.no_nac_branch_requires_explicit_cli_flag")
                == "--nonac",
                "phono3py v4 no-NAC branch must use --nonac",
            )
            check(
                required(config, "nac.reject_BORN_or_yaml_nac_params_in_no_nac_branch")
                is True,
                "no-NAC branch must reject BORN and YAML nac_params",
            )

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
    path = strict_run_descendant(
        run_dir, Path(raw), "P3_ATTEMPT_DIR", require_exists=True
    )
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
    tracked = [
        Path(__file__).resolve(),
        Path(__file__).with_name("qe_input.py"),
        Path(__file__).with_name("qe_output.py"),
    ]
    if config.get("reviewed_bfgs_polish") is not None:
        tracked.append(Path(__file__).with_name("polish_recovery.py"))
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


def verify_upstream_manifest(
    config: Mapping[str, Any], config_path: Path, run_dir: Path, *, stage: str
) -> dict[str, Any]:
    """Verify an accepted older stage without requiring its code to be current.

    A run records the exact workflow hashes that created its evidence. Released
    downstream code is allowed to evolve after that evidence is complete, so
    it must compare the saved scientific policy and source inputs, not demand
    that today's ``campaign.py`` still has the upstream byte hash. The later
    stage creates and verifies its own immutable code manifest.
    """

    del config_path  # The validated config object is the policy authority.
    run_dir = safe_run_dir(run_dir)
    manifest_path = run_dir / RUN_MANIFEST
    if not manifest_path.is_file():
        raise CampaignError(f"run was not prepared: {manifest_path}")
    saved = load_json(manifest_path)
    if stage not in {"structure", "preflight"}:
        raise CampaignError(f"unsupported upstream manifest stage: {stage}")
    policy_key = f"{stage}_policy_sha256"
    expected = {
        "schema_version": 2,
        "material": required(config, "material.formula"),
        policy_key: policy_sha256(config, stage),
        "source_qe_sha256": sha256_path(
            resolve_repo_source(config, "source.qe_scf_input")
        ),
        "source_relax_sha256": sha256_path(
            resolve_repo_source(config, "source.original_relax_output")
        ),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise CampaignError(f"upstream run provenance changed: {key}")
    workflow = saved.get("workflow_files")
    if (
        not isinstance(workflow, Mapping)
        or not workflow
        or any(
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for path, digest in workflow.items()
        )
    ):
        raise CampaignError("upstream run has an invalid archived workflow hash set")
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


def relax_input_for(
    config: Mapping[str, Any],
    starting_input: str,
    pseudo_dir: Path,
    *,
    bfgs_parameters: Mapping[str, Any] | None = None,
) -> str:
    """Build the exact policy-matched fixed-cell input for any fresh attempt."""

    settings = required(config, "tight_relax")
    formula = str(required(config, "material.formula"))
    return build_fixed_cell_relax_input(
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
        bfgs_ndim=None if bfgs_parameters is None else bfgs_parameters.get("bfgs_ndim"),
        trust_radius_ini=None if bfgs_parameters is None else bfgs_parameters.get("trust_radius_ini"),
        trust_radius_min=None if bfgs_parameters is None else bfgs_parameters.get("trust_radius_min"),
        trust_radius_max=None if bfgs_parameters is None else bfgs_parameters.get("trust_radius_max"),
    )


def command_run_relax(config_path: Path, run_dir: Path) -> dict[str, Any]:
    require_compute_node()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    run_manifest = verify_manifest(config, config_path, run_dir, stage="structure")
    if run_manifest.get("accepted_structure_import") is not None:
        raise CampaignError(
            "an imported accepted-structure RUN_DIR cannot execute a relax stage"
        )
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
    recovery = None
    polish = None
    if run_manifest.get("relax_recovery") is not None and run_manifest.get("relax_polish") is not None:
        raise CampaignError("run manifest cannot combine automatic recovery and reviewed polish")
    if run_manifest.get("relax_recovery") is not None:
        from relax_recovery import load_recovery_start

        reference_input = starting_input
        starting_input, recovery = load_recovery_start(
            config, run_dir, run_manifest, reference_input, pseudo_hashes
        )
        write_immutable(attempt / "reference_unitcell.in", reference_input)
        structure_audit = {
            **structure_audit,
            "recovery": recovery,
            "reference_unitcell_sha256": sha256_path(attempt / "reference_unitcell.in"),
            "accepted_starting_geometry_sha256": hashlib.sha256(starting_input.encode()).hexdigest(),
            "source": "hashed failed BFGS attempt final coordinates; fresh BFGS history",
        }
    elif run_manifest.get("relax_polish") is not None:
        from polish_recovery import load_polish_start

        reference_input = starting_input
        starting_input, polish = load_polish_start(
            config, run_dir, run_manifest, reference_input, pseudo_hashes
        )
        write_immutable(attempt / "reference_unitcell.in", reference_input)
        structure_audit = {
            **structure_audit,
            "polish": polish,
            "reference_unitcell_sha256": sha256_path(attempt / "reference_unitcell.in"),
            "accepted_starting_geometry_sha256": hashlib.sha256(starting_input.encode()).hexdigest(),
            "source": "hashed one-reset terminal BFGS geometry after passing force-consistency diagnostic; one reviewed polish only",
        }
    write_json_immutable(attempt / "starting_structure_audit.json", structure_audit)
    write_immutable(attempt / "starting_unitcell.in", starting_input)

    settings = required(config, "tight_relax")
    formula = str(required(config, "material.formula"))
    polish_parameters = (
        required(config, "reviewed_bfgs_polish.bfgs_parameters")
        if polish is not None else None
    )
    relax_input = relax_input_for(
        config, starting_input, pseudo_dir, bfgs_parameters=polish_parameters
    )
    if recovery is not None or polish is not None:
        from qe_input import _set_namelist_values

        relax_input = _set_namelist_values(relax_input, "CONTROL", {"restart_mode": "'from_scratch'"})
        relax_input = _set_namelist_values(relax_input, "ELECTRONS", {"startingpot": "'atomic'", "startingwfc": "'atomic+random'"})
        if (attempt / "tmp-relax").exists() or (attempt / "tmp-pristine").exists():
            raise CampaignError("recovery/polish requires empty, fresh QE scratch directories")
    if polish is not None:
        relax_attempts = run_dir / "slurm_attempts" / "relax"
        attempt_directories = [path for path in relax_attempts.iterdir() if path.is_dir()]
        if attempt_directories != [attempt]:
            raise CampaignError("reviewed BFGS polish permits exactly one immutable relax attempt")
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
            "recovery": recovery,
            "polish": polish,
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
        "recovery": recovery,
        "polish": polish,
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
    if run_manifest.get("accepted_structure_import") is not None:
        raise CampaignError(
            "an imported accepted-structure RUN_DIR cannot finalize a relax stage"
        )
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
    reference_path = attempt / "starting_unitcell.in"
    if run_manifest.get("relax_recovery") is not None and run_manifest.get("relax_polish") is not None:
        raise CampaignError("run manifest cannot combine automatic recovery and reviewed polish")
    if run_manifest.get("relax_recovery") is not None:
        from relax_recovery import load_recovery_start

        reference_path = attempt / "reference_unitcell.in"
        starting_input, recovery = load_recovery_start(
            config, run_dir, run_manifest, reference_path.read_text(),
            execution["pseudopotentials"],
        )
        if starting_input != (attempt / "starting_unitcell.in").read_text():
            raise CampaignError("recovery starting unitcell differs from its frozen seed")
        if any(record.get("recovery") != recovery for record in (execution, relax_launch)):
            raise CampaignError("recovery launch/execution receipt mismatch")
        audit = load_json(attempt / "starting_structure_audit.json")
        if audit.get("reference_unitcell_sha256") != sha256_path(reference_path):
            raise CampaignError("recovery cumulative-position reference hash mismatch")
    elif run_manifest.get("relax_polish") is not None:
        from polish_recovery import load_polish_start

        reference_path = attempt / "reference_unitcell.in"
        starting_input, polish = load_polish_start(
            config, run_dir, run_manifest, reference_path.read_text(),
            execution["pseudopotentials"],
        )
        if starting_input != (attempt / "starting_unitcell.in").read_text():
            raise CampaignError("polish starting unitcell differs from its frozen seed")
        if any(record.get("polish") != polish for record in (execution, relax_launch)):
            raise CampaignError("polish launch/execution receipt mismatch")
        audit = load_json(attempt / "starting_structure_audit.json")
        if audit.get("reference_unitcell_sha256") != sha256_path(reference_path):
            raise CampaignError("polish cumulative-position reference hash mismatch")
    shifts = _position_shifts_angstrom(
        reference_path.read_text(),
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
        "position_shift_reference": str(reference_path),
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
    included_pair_distances: list[float] = []
    excluded_pair_distances: list[float] = []
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
            pair_distance = float(required(second, "pair_distance"))
            if not math.isfinite(pair_distance) or pair_distance < 0:
                raise CampaignError("paired_with.pair_distance must be finite and non-negative")
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
                included_pair_distances.append(pair_distance)
            else:
                excluded_pair_groups += 1
                excluded_pair_distances.append(pair_distance)
    if len(set(all_ids)) != len(all_ids):
        raise CampaignError("duplicate displacement IDs in phono3py YAML")
    expected_domain = set(range(1, len(all_ids) + 1))
    if set(all_ids) != expected_domain:
        raise CampaignError("phono3py displacement IDs are not the complete 1..N domain")
    # phono3py groups each first displacement with its (usually much later)
    # paired IDs, so traversal order is intentionally not global ID order.
    # Generated QE filenames and FORCES blocks use numeric ID order. Preserve
    # the grouped traversal separately for diagnostics, never force collection.
    included_ids_sorted = sorted(included_ids)
    return {
        "all_displacement_ids": sorted(all_ids),
        "grouped_traversal_displacement_ids": all_ids,
        "included_displacement_ids": included_ids_sorted,
        "vectors": vectors,
        "single_displacements": singles,
        "included_pair_groups": included_pair_groups,
        "excluded_pair_groups": excluded_pair_groups,
        "included_pair_distances": included_pair_distances,
        "excluded_pair_distances": excluded_pair_distances,
        "nonzero_included_pair_groups": sum(
            distance > 1e-10 for distance in included_pair_distances
        ),
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


def supercell_lattices_match(
    generated: Sequence[Sequence[float]],
    expected: Sequence[Sequence[float]],
) -> bool:
    return all(
        math.isclose(
            generated_value,
            expected_value,
            rel_tol=SUPERCELL_LATTICE_REL_TOL,
            abs_tol=SUPERCELL_LATTICE_ABS_TOL_BOHR,
        )
        for generated_row, expected_row in zip(generated, expected)
        for generated_value, expected_value in zip(generated_row, expected_row)
    )


def verify_imported_structure_if_present(
    config_path: Path,
    run_dir: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Replay a destination-owned accepted-structure import, when declared."""

    if manifest.get("accepted_structure_import") is None:
        return None
    from accepted_structure_import import verify_imported_acceptance

    return verify_imported_acceptance(config_path, run_dir)


def command_preflight(
    config_path: Path,
    run_dir: Path,
    *,
    candidate_ids: Sequence[str] | None = None,
    expected_candidate_subset_sha256: str | None = None,
) -> dict[str, Any]:
    require_compute_node()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    # The accepted structure is immutable upstream evidence.  A later
    # preflight bug fix may change campaign.py; verify the saved scientific
    # policy and source hashes, while the Slurm attempt records the exact
    # current campaign.py hash that performs this preflight.
    run_manifest = verify_upstream_manifest(
        config, config_path, run_dir, stage="preflight"
    )
    imported_acceptance = verify_imported_structure_if_present(
        config_path, run_dir, run_manifest
    )
    selected_enumerations, candidate_selection = select_preflight_candidates(
        config, candidate_ids
    )
    if candidate_ids is None and expected_candidate_subset_sha256 is not None:
        raise CampaignError(
            "--expect-candidate-subset-sha is valid only with an explicit candidate subset"
        )
    if candidate_ids is not None:
        if (
            not isinstance(expected_candidate_subset_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_candidate_subset_sha256)
            is None
        ):
            raise CampaignError(
                "explicit preflight subset requires a 64-character --expect-candidate-subset-sha"
            )
        if (
            expected_candidate_subset_sha256
            != candidate_selection["candidate_subset_sha256"]
        ):
            raise CampaignError(
                "preflight candidate subset SHA256 differs from the reviewed submission plan"
            )
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

    for enumeration in selected_enumerations:
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
        if not supercell_lattices_match(cell, expected_cell_bohr):
            raise CampaignError(
                "generated lattice violates A_super=M^T A beyond the allowed "
                f"unit-conversion tolerance for {supercell_id}"
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
            "candidate_id": preflight_candidate_id(enumeration),
            "supercell_id": supercell_id,
            "cutoff_id": cutoff_id,
            "cutoff_pair_distance_angstrom": cutoff["cutoff_pair_distance_angstrom"],
            "cutoff_pair_distance_cli_bohr": cutoff["cutoff_pair_distance_cli_bohr"],
            "uncontracted_displacements": total_count,
            "generated_displacement_supercells": created_count,
            "single_displacements": yaml_inventory["single_displacements"],
            "included_pair_groups": yaml_inventory["included_pair_groups"],
            "excluded_pair_groups": yaml_inventory["excluded_pair_groups"],
            "nonzero_included_pair_groups": yaml_inventory[
                "nonzero_included_pair_groups"
            ],
            "included_pair_distances_bohr": yaml_inventory[
                "included_pair_distances"
            ],
            "excluded_pair_distances_bohr": yaml_inventory[
                "excluded_pair_distances"
            ],
            "generated_displacement_ids": yaml_included_ids,
            "hard_cap": hard_cap,
            "within_hard_cap": created_count <= hard_cap,
            "generated_atoms": nat,
            "cell_vectors_bohr": cell,
            "cell_edge_lengths_angstrom": generated_lengths_angstrom,
            "expected_cell_vectors_bohr_from_M_transpose_A": expected_cell_bohr,
            "lattice_comparison_tolerance": {
                "relative": SUPERCELL_LATTICE_REL_TOL,
                "absolute_bohr": SUPERCELL_LATTICE_ABS_TOL_BOHR,
                "reason": "allow phonopy/phono3py versus configured CODATA Bohr rounding only",
            },
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
        result["selection_eligible"] = bool(
            not result["count_only"]
            and result["within_hard_cap"]
            and result["nonzero_included_pair_groups"] > 0
        )
        result["requires_budget_or_scientific_review"] = not result[
            "selection_eligible"
        ]
        write_json_immutable(work / "preflight_result.json", result)
        results.append(result)

    derived_no_cutoff, skipped_no_cutoff = derive_no_cutoff_preflight_results(
        deferred_no_cutoff, uncontracted, hard_cap
    )
    results.extend(derived_no_cutoff)

    routine_results = [
        item
        for item in results
        if item.get("cutoff_id") is not None and not item.get("count_only")
    ]
    all_routine_within_cap = bool(routine_results) and all(
        item.get("within_hard_cap", False) for item in routine_results
    )
    eligible_candidates = [
        item
        for item in routine_results
        if item.get("selection_eligible") is True
    ]
    inventory = {
        "stage": "preflight",
        "material": required(config, "material.formula"),
        "created_utc": utc_now(),
        "preflight_policy_sha256": run_manifest["preflight_policy_sha256"],
        "accepted_unitcell_sha256": sha256_path(unitcell),
        "accepted_relax_provenance_sha256": sha256_path(provenance_path),
        "accepted_structure_import_receipt_sha256": (
            None if imported_acceptance is None
            else imported_acceptance["receipt_sha256"]
        ),
        **preflight_completion_fields(candidate_selection),
        "candidate_selection": candidate_selection,
        "candidate_subset_sha256": candidate_selection[
            "candidate_subset_sha256"
        ],
        "selected_candidate_ids": candidate_selection["candidate_ids"],
        "skipped_no_cutoff_candidate_ids": skipped_no_cutoff,
        "all_routine_candidates_within_hard_cap": all_routine_within_cap,
        "eligible_candidate_count": len(eligible_candidates),
        "requires_budget_or_scientific_review": (
            not all_routine_within_cap or not eligible_candidates
        ),
        "production_selection_still_required": True,
        "results": results,
        "limitations": [
            "Counts and geometry checks are preflight results, not force convergence.",
            "No force-array or thermal-conductivity calculation was submitted by this command.",
            "A no-cutoff derived row is omitted when this attempt did not run a cutoff-pair parent for the same supercell.",
        ],
    }
    write_json_immutable(attempt / "preflight_inventory.json", inventory)
    return inventory


def command_status(config_path: Path, run_dir: Path) -> dict[str, Any]:
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    status: dict[str, Any] = {
        "material": required(config, "material.formula"),
        "run_dir": str(run_dir),
        "prepared": (run_dir / RUN_MANIFEST).is_file(),
        "tight_relax_accepted": False,
        "accepted_structure_origin": None,
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
        status["accepted_structure_origin"] = "calculated_in_run"
    manifest_path = run_dir / RUN_MANIFEST
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        if manifest.get("accepted_structure_import") is not None:
            status["accepted_structure_origin"] = "imported_accepted_structure"
            try:
                status["accepted_structure_import"] = (
                    verify_imported_structure_if_present(
                        config_path, run_dir, manifest
                    )
                )
            except (CampaignError, OSError, ValueError, KeyError) as exc:
                status["tight_relax_accepted"] = False
                status["accepted_structure_import_error"] = str(exc)
    attempts = run_dir / "slurm_attempts" / "preflight"
    if attempts.is_dir():
        inventories = list(attempts.glob("*/preflight_inventory.json"))
        status["preflight_attempts"] = len(inventories)
        status["preflight_inventories"] = [str(path) for path in sorted(inventories)]
    return status


FORCE_TASK_MAP_FIELDS = (
    "task_id",
    "displacement_id",
    "role",
    "input_path",
    "input_sha256",
)
SACCT_FIELDS = (
    "JobID",
    "JobIDRaw",
    "State",
    "ExitCode",
    "ElapsedRaw",
    "AllocCPUS",
    "MaxRSS",
)
DIAGNOSTIC_SACCT_FIELDS = SACCT_FIELDS + (
    "Account",
    "Partition",
    "NNodes",
    "NCPUS",
    "ReqMem",
    "TimelimitRaw",
)


def _strict_evidence_path(path: Path, root: Path, label: str) -> Path:
    """Resolve one evidence path and reject broad, escaped, or frozen paths."""

    return strict_run_descendant(root, path, label, require_exists=True)


def _read_context_tsv(path: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    values: dict[str, str] = {}
    if not path.is_file():
        return values, [f"missing context record: {path}"]
    try:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            fields = line.split("\t", 1)
            if len(fields) != 2 or not fields[0]:
                errors.append(f"malformed context line {line_number}")
                continue
            key, value = fields
            if key in values:
                errors.append(f"duplicate context key: {key}")
            else:
                values[key] = value
    except OSError as exc:
        errors.append(f"cannot read context record: {exc}")
    return values, errors


def _read_sacct_records(
    accounting_path: Path,
    accounting_status_path: Path,
    fields: Sequence[str] = SACCT_FIELDS,
) -> tuple[list[dict[str, str]], list[str], dict[str, Any]]:
    """Read the collector-created sacct record without treating absence as success."""

    errors: list[str] = []
    metadata: dict[str, Any] = {
        "path": str(accounting_path),
        "status_path": str(accounting_status_path),
    }
    records: list[dict[str, str]] = []
    if accounting_path.is_file():
        metadata["sha256"] = sha256_path(accounting_path)
        metadata["bytes"] = accounting_path.stat().st_size
        try:
            with accounting_path.open(newline="") as handle:
                reader = csv.DictReader(handle, delimiter="|")
                if tuple(reader.fieldnames or ()) != tuple(fields):
                    errors.append("scheduler accounting has an unexpected field schema")
                else:
                    for index, row in enumerate(reader, 1):
                        if None in row or any(row.get(field) is None for field in fields):
                            errors.append(f"scheduler accounting row {index} is malformed")
                            continue
                        records.append(
                            {field: str(row[field]).strip() for field in fields}
                        )
        except (OSError, csv.Error) as exc:
            errors.append(f"cannot parse scheduler accounting: {exc}")
    else:
        errors.append(f"missing scheduler accounting: {accounting_path}")
    if accounting_status_path.is_file():
        metadata["status_sha256"] = sha256_path(accounting_status_path)
        try:
            status_text = accounting_status_path.read_text().strip()
            status = int(status_text)
            metadata["sacct_exit_code"] = status
            if status != 0:
                errors.append(f"sacct exited with code {status}")
        except (OSError, ValueError) as exc:
            errors.append(f"invalid sacct exit-code record: {exc}")
    else:
        errors.append(f"missing sacct exit-code record: {accounting_status_path}")
    return records, errors, metadata


def _load_force_collection_contract(
    config: Mapping[str, Any],
    config_path: Path,
    run_dir: Path,
    force_manifest_path: Path,
    task_map_path: Path,
    expected_force_manifest_sha256: str,
    expected_task_map_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate the exact manifest/map/input bytes even when every task failed."""

    manifest_path = _strict_evidence_path(
        force_manifest_path, run_dir, "force manifest"
    )
    task_map = _strict_evidence_path(task_map_path, run_dir, "force task map")
    if (
        manifest_path.name != "force_manifest.json"
        or task_map.name != "task_map.tsv"
        or manifest_path.parent != task_map.parent
        or not manifest_path.is_file()
        or not task_map.is_file()
    ):
        raise CampaignError("force collection requires one adjacent manifest/task map")
    for label, expected, path in (
        ("force manifest", expected_force_manifest_sha256, manifest_path),
        ("force task map", expected_task_map_sha256, task_map),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise CampaignError(f"expected {label} SHA256 is invalid")
        if sha256_path(path) != expected:
            raise CampaignError(f"{label} differs from the submitted primary plan")
    manifest = load_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("stage") != "force"
        or manifest.get("mode") not in {"pilot", "production"}
        or manifest.get("material") != required(config, "material.formula")
        or manifest.get("config_sha256") != sha256_path(config_path.resolve())
        or manifest.get("task_map_sha256") != sha256_path(task_map)
    ):
        raise CampaignError("force manifest does not match the selected run/config/task map")
    tasks = manifest.get("tasks")
    task_count = manifest.get("task_count")
    if (
        isinstance(task_count, bool)
        or not isinstance(task_count, int)
        or task_count < 1
        or not isinstance(tasks, list)
        or len(tasks) != task_count
    ):
        raise CampaignError("force manifest has an invalid task domain")
    try:
        with task_map.open(newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if tuple(reader.fieldnames or ()) != FORCE_TASK_MAP_FIELDS:
                raise CampaignError("force task map has an unexpected field schema")
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        raise CampaignError(f"cannot parse force task map: {exc}") from exc
    if len(rows) != task_count:
        raise CampaignError("force task map count differs from its manifest")
    if any(
        None in row or any(row.get(field) is None for field in FORCE_TASK_MAP_FIELDS)
        for row in rows
    ):
        raise CampaignError("force task map contains a malformed row")
    bundle = manifest_path.parent
    for task_id, (task, row) in enumerate(zip(tasks, rows)):
        if (
            not isinstance(task, Mapping)
            or isinstance(task.get("task_id"), bool)
            or not isinstance(task.get("task_id"), int)
            or task.get("task_id") != task_id
        ):
            raise CampaignError("force manifest task IDs must be contiguous map indices")
        if any(str(task.get(field)) != row.get(field) for field in FORCE_TASK_MAP_FIELDS):
            raise CampaignError("force manifest task row differs from task_map.tsv")
        displacement_id = task.get("displacement_id")
        expected_role = "pristine" if displacement_id == 0 else "displacement"
        if (
            isinstance(displacement_id, bool)
            or not isinstance(displacement_id, int)
            or displacement_id < 0
            or task.get("role") != expected_role
        ):
            raise CampaignError("force manifest contains an invalid displacement role")
        input_path = Path(str(task.get("input_path", ""))).resolve()
        if (
            input_path == bundle
            or not input_path.is_relative_to(bundle)
            or not input_path.is_file()
            or sha256_path(input_path) != task.get("input_sha256")
        ):
            raise CampaignError("force task input is missing, escaped, or altered")
    return manifest, [dict(task) for task in tasks]


def _hash_present_evidence(parent: Path, names: Sequence[str]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for name in names:
        path = parent / name
        if path.is_file():
            evidence[name] = {
                "sha256": sha256_path(path),
                "bytes": path.stat().st_size,
            }
    return evidence


def _read_exit_code(parent: Path) -> tuple[int | None, list[str]]:
    path = parent / "exit_code.txt"
    if not path.is_file():
        return None, ["missing upstream exit_code.txt"]
    try:
        return int(path.read_text().strip()), []
    except (OSError, ValueError) as exc:
        return None, [f"invalid upstream exit_code.txt: {exc}"]


def _accounting_for_force_task(
    records: Sequence[Mapping[str, str]],
    primary_job_id: str,
    task_id: int,
    raw_job_id: str,
) -> tuple[list[dict[str, str]], Mapping[str, str] | None, list[str]]:
    display_id = f"{primary_job_id}_{task_id}"
    related = [
        dict(row)
        for row in records
        if row.get("JobID") == display_id
        or str(row.get("JobID", "")).startswith(display_id + ".")
    ]
    allocations = [row for row in related if row["JobID"] == display_id]
    errors: list[str] = []
    if len(allocations) != 1:
        errors.append(
            f"expected one sacct allocation row for {display_id}; found {len(allocations)}"
        )
    elif allocations[0].get("JobIDRaw") != raw_job_id:
        errors.append(
            f"sacct does not bind {display_id} to context raw job {raw_job_id}"
        )
    if raw_job_id and any(
        row["JobIDRaw"] != raw_job_id
        and not row["JobIDRaw"].startswith(raw_job_id + ".")
        for row in related
    ):
        errors.append("sacct step JobIDRaw values disagree with the allocation raw job")
    return related, allocations[0] if len(allocations) == 1 else None, errors


def _normalized_slurm_state(value: str) -> str:
    return value.strip().upper().split()[0].rstrip("+") if value.strip() else ""


def _diagnostic_reqmem_total_mb(
    raw: str, *, allocated_cpus: int, nodes: int
) -> float:
    """Normalize Slurm ReqMem, including per-CPU/per-node suffixes, to MiB."""

    matched = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTP]?)([cn]?)", raw.strip(), re.I)
    if matched is None:
        raise CampaignError(f"diagnostic sacct ReqMem is invalid: {raw!r}")
    value = float(matched.group(1))
    unit = matched.group(2).upper() or "M"
    factor = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2, "P": 1024**3}[unit]
    total = value * factor
    suffix = matched.group(3).lower()
    if suffix == "c":
        total *= allocated_cpus
    elif suffix == "n":
        total *= nodes
    return total


def _collect_diagnostic_attempt(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    run_dir: Path,
    current_attempt: Path,
    primary_attempt_id: str,
    primary_job_id: str,
    expected_primary_request_sha256: str,
    expected_primary_result_sha256: str,
    expected_primary_stage_script_sha256: str,
    accounting_records: Sequence[Mapping[str, str]],
    accounting_errors: Sequence[str],
    accounting_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect one diagnostic without interpreting its force comparison."""

    from polish_recovery import DIAGNOSTIC_EXECUTION, LINEAGE_RECEIPT, _load_lineage

    lineage = _load_lineage(config, run_dir)
    config_sha = sha256_path(config_path)
    lineage_path = strict_run_descendant(
        run_dir, run_dir / LINEAGE_RECEIPT, "diagnostic lineage"
    )
    lineage_sha = sha256_path(lineage_path)
    resources = required(config, "scheduler.diagnostic_resources")
    resource_sha = canonical_sha256(resources)
    errors = list(accounting_errors)

    submission_dir = strict_run_descendant(
        run_dir,
        run_dir / "submissions/diagnostic" / primary_attempt_id,
        "diagnostic submission record",
    )
    reject_symlinks_below(
        run_dir, submission_dir, "diagnostic submission record"
    )
    request_path = strict_run_descendant(
        run_dir, submission_dir / "request.json", "diagnostic submission request"
    )
    result_path = strict_run_descendant(
        run_dir,
        submission_dir / "primary_result.json",
        "diagnostic submission response",
    )
    for label, expected, path in (
        ("primary request", expected_primary_request_sha256, request_path),
        ("primary response", expected_primary_result_sha256, result_path),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", expected or "") is None:
            raise CampaignError(f"diagnostic collector {label} hash is invalid")
        if sha256_path(path) != expected:
            raise CampaignError(f"diagnostic collector {label} hash mismatch")
    request = load_json(request_path)
    response = load_json(result_path)
    if (
        request.get("stage") != "diagnostic"
        or request.get("attempt_id") != primary_attempt_id
        or request.get("config_sha256") != config_sha
        or request.get("run_dir") != str(run_dir)
        or request.get("polish_lineage_sha256") != lineage_sha
        or request.get("diagnostic_lineage_sha256") != lineage_sha
        or request.get("diagnostic_resource_sha256") != resource_sha
        or request.get("slurm_account") != required(config, "scheduler.slurm_account")
        or request.get("stage_script_sha256")
        != expected_primary_stage_script_sha256
    ):
        errors.append("diagnostic submission request identity/hash mismatch")
    if (
        response.get("stage") != "diagnostic"
        or response.get("attempt_id") != primary_attempt_id
        or response.get("job_id") != primary_job_id
        or response.get("config_sha256") != config_sha
        or response.get("returncode") != 0
    ):
        errors.append("diagnostic submission response identity mismatch")

    wrapper = strict_run_descendant(
        run_dir,
        run_dir / "slurm_attempts/diagnostic" / primary_attempt_id,
        "diagnostic Slurm wrapper attempt",
        require_exists=False,
    )
    if wrapper.is_dir():
        reject_symlinks_below(
            run_dir, wrapper, "diagnostic Slurm wrapper attempt"
        )
        wrapper_context_path = strict_run_descendant(
            run_dir,
            wrapper / "context.tsv",
            "diagnostic wrapper context",
            require_exists=False,
        )
        wrapper_context, context_errors = _read_context_tsv(wrapper_context_path)
        errors.extend(context_errors)
    else:
        wrapper_context = {}
        errors.append("diagnostic Slurm wrapper attempt is missing")
    workflow = request.get("workflow_sha256")
    if not isinstance(workflow, Mapping):
        errors.append("diagnostic request has no workflow hash inventory")
        workflow = {}
    expected_context = {
        "stage": "diagnostic",
        "attempt_id": primary_attempt_id,
        "slurm_job_id": primary_job_id,
        "run_dir": str(run_dir),
        "config_sha256": config_sha,
        "diagnostic_resource_sha256": resource_sha,
        "diagnostic_lineage_sha256": lineage_sha,
        "diagnostic_backend_sha256": str(workflow.get("polish_recovery.py", "")),
    }
    for key, expected in expected_context.items():
        if wrapper_context.get(key) != expected:
            errors.append(f"diagnostic wrapper context mismatch for {key}")
    for context_key, workflow_key in (
        ("submit_script_sha256", "submit.py"),
        ("campaign_cli_sha256", "campaign.py"),
        ("cluster_env_sha256", "cluster.env"),
        ("stage_script_sha256", "diagnostic.sbatch"),
    ):
        if wrapper_context.get(context_key) != workflow.get(workflow_key):
            errors.append(f"diagnostic wrapper workflow mismatch for {workflow_key}")
    if lineage.get("backend_sha256") != workflow.get("polish_recovery.py"):
        errors.append("diagnostic lineage/backend workflow mismatch")

    claim = strict_run_descendant(
        run_dir,
        run_dir / "diagnostic/dispatch_claim",
        "diagnostic dispatch claim",
        require_exists=False,
    )
    if claim.is_dir():
        reject_symlinks_below(run_dir, claim, "diagnostic dispatch claim")
        claim_context_path = strict_run_descendant(
            run_dir,
            claim / "context.tsv",
            "diagnostic dispatch claim context",
            require_exists=False,
        )
        claim_context, claim_errors = _read_context_tsv(claim_context_path)
        errors.extend(claim_errors)
    else:
        claim_context = {}
        errors.append("diagnostic dispatch claim is missing")
    claim_expected = {
        "attempt_id": primary_attempt_id,
        "slurm_job_id": primary_job_id,
        "config_sha256": config_sha,
        "lineage_sha256": lineage_sha,
        "resource_sha256": resource_sha,
    }
    for key, expected in claim_expected.items():
        if claim_context.get(key) != expected:
            errors.append(f"diagnostic dispatch claim mismatch for {key}")

    if wrapper.is_dir():
        wrapper_exit_path = strict_run_descendant(
            run_dir,
            wrapper / "exit_code.txt",
            "diagnostic wrapper exit code",
            require_exists=False,
        )
        wrapper_exit, exit_errors = _read_exit_code(wrapper)
        errors.extend(exit_errors)
        if wrapper_exit_path.is_symlink():  # defensive; strict path already rejects this
            raise CampaignError("diagnostic wrapper exit code is symlinked")
    else:
        wrapper_exit = None
    execution_path = strict_run_descendant(
        run_dir,
        run_dir / "diagnostic/attempts" / primary_attempt_id / DIAGNOSTIC_EXECUTION,
        "diagnostic execution",
        require_exists=False,
    )
    execution_sha = sha256_path(execution_path) if execution_path.is_file() else None
    if execution_sha is None:
        errors.append("diagnostic execution is missing")

    related = [
        dict(row)
        for row in accounting_records
        if row.get("JobIDRaw") == primary_job_id
        or str(row.get("JobIDRaw", "")).startswith(primary_job_id + ".")
    ]
    allocations = [row for row in related if row.get("JobIDRaw") == primary_job_id]
    allocation = allocations[0] if len(allocations) == 1 else None
    if len(allocations) != 1:
        errors.append(
            f"expected one diagnostic sacct allocation row for {primary_job_id}; found {len(allocations)}"
        )
    allocation_matches = False
    if allocation is not None:
        try:
            allocated_cpus = int(allocation["AllocCPUS"])
            ncpus = int(allocation["NCPUS"])
            nodes = int(allocation["NNodes"])
            elapsed = int(allocation["ElapsedRaw"])
            time_limit = int(allocation["TimelimitRaw"])
            requested_total_mb = _diagnostic_reqmem_total_mb(
                allocation["ReqMem"], allocated_cpus=allocated_cpus, nodes=nodes
            )
            configured_total_mb = (
                int(resources["mem_per_cpu_mb"])
                * int(resources["ntasks"])
                * int(resources["cpus_per_task"])
            )
            allocation_matches = (
                allocation["Account"] == required(config, "scheduler.slurm_account")
                and allocation["Partition"] == resources["partition"]
                and nodes == resources["nodes"]
                and allocated_cpus == resources["ntasks"] * resources["cpus_per_task"]
                and ncpus == allocated_cpus
                and time_limit == int(float(resources["walltime_hours"]) * 60)
                and 0 <= elapsed <= time_limit * 60
                and math.isclose(
                    requested_total_mb,
                    configured_total_mb,
                    rel_tol=0,
                    abs_tol=0.01,
                )
            )
        except (KeyError, TypeError, ValueError, CampaignError):
            allocation_matches = False
        if not allocation_matches:
            errors.append("diagnostic sacct allocation differs from configured resources")
    scheduler_success = bool(
        allocation is not None
        and _normalized_slurm_state(allocation.get("State", "")) == "COMPLETED"
        and allocation.get("ExitCode") == "0:0"
    )
    wrapper_success = wrapper_exit == 0
    integrity = not errors
    complete = integrity and scheduler_success and wrapper_success and execution_sha is not None
    evidence = _hash_present_evidence(
        wrapper,
        ("context.tsv", "exit_code.txt", "finished_utc.txt", "stdout.log", "stderr.log"),
    )
    return {
        "schema_version": 1,
        "stage": "collect",
        "collection_kind": "diagnostic_single_attempt",
        "material": required(config, "material.formula"),
        "collected_utc": utc_now(),
        "collector_attempt": str(current_attempt),
        "submission": {
            "record_dir": str(submission_dir),
            "request_sha256": sha256_path(request_path),
            "primary_result_sha256": sha256_path(result_path),
        },
        "primary": {
            "stage": "diagnostic",
            "attempt_id": primary_attempt_id,
            "job_id": primary_job_id,
            "wrapper_attempt": str(wrapper),
            "diagnostic_execution": str(execution_path),
            "diagnostic_execution_sha256": execution_sha,
            "scheduler_accounting": dict(accounting_metadata),
        },
        "entry": {
            "context": wrapper_context,
            "dispatch_claim": claim_context,
            "wrapper_exit_code": wrapper_exit,
            "scheduler_records": related,
            "allocation": dict(allocation) if allocation is not None else None,
            "evidence": evidence,
            "errors": errors,
        },
        "collection_integrity_complete": integrity,
        "scheduler_completed_successfully": scheduler_success,
        "wrapper_completed_successfully": wrapper_success,
        "diagnostic_execution_present": execution_sha is not None,
        "diagnostic_execution_complete": complete,
        "incomplete": not complete,
        "scientific_gate_published": False,
        "structure_accepted": False,
        "preflight_unlocked": False,
    }


def _collect_force_batch(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    run_dir: Path,
    current_attempt: Path,
    primary_attempt_id: str,
    primary_job_id: str,
    force_manifest_path: Path,
    task_map_path: Path,
    expected_force_manifest_sha256: str,
    expected_task_map_sha256: str,
    accounting_records: Sequence[Mapping[str, str]],
    accounting_errors: Sequence[str],
    accounting_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    from postprocess_backend import PostprocessError, load_force_artifact

    manifest, tasks = _load_force_collection_contract(
        config,
        config_path,
        run_dir,
        force_manifest_path,
        task_map_path,
        expected_force_manifest_sha256,
        expected_task_map_sha256,
    )
    force_manifest_path = force_manifest_path.resolve()
    primary_root = run_dir / "slurm_attempts" / "force" / primary_attempt_id
    entries: list[dict[str, Any]] = []
    expected_directories = {f"task-{task['task_id']}" for task in tasks}
    actual_directories = (
        {item.name for item in primary_root.iterdir() if item.is_dir()}
        if primary_root.is_dir()
        else set()
    )
    global_errors = list(accounting_errors)
    if not primary_root.is_dir():
        global_errors.append(f"missing primary force attempt root: {primary_root}")
    extra = sorted(actual_directories - expected_directories)
    if extra:
        global_errors.append(f"unexpected task directories in primary attempt: {extra}")
    accounting_task_ids: list[int] = []
    allocation_pattern = re.compile(rf"^{re.escape(primary_job_id)}_(\d+)$")
    for row in accounting_records:
        matched = allocation_pattern.fullmatch(row.get("JobID", ""))
        if matched:
            accounting_task_ids.append(int(matched.group(1)))
    unexpected_accounting = sorted(set(accounting_task_ids) - set(range(len(tasks))))
    if unexpected_accounting:
        global_errors.append(
            f"sacct contains out-of-domain array task IDs: {unexpected_accounting}"
        )

    for task in tasks:
        task_id = int(task["task_id"])
        parent = primary_root / f"task-{task_id}"
        errors: list[str] = []
        context_path = parent / "context.tsv"
        context, context_errors = _read_context_tsv(context_path)
        errors.extend(context_errors)
        expected_context = {
            "stage": "force",
            "attempt_id": primary_attempt_id,
            "slurm_array_job_id": primary_job_id,
            "slurm_array_task_id": str(task_id),
            "run_dir": str(run_dir),
            "config_sha256": manifest["config_sha256"],
        }
        for key, expected in expected_context.items():
            if context.get(key) != expected:
                errors.append(f"context mismatch for {key}")
        exit_code, exit_errors = _read_exit_code(parent)
        errors.extend(exit_errors)
        raw_job_id = context.get("slurm_job_id", "")
        if not raw_job_id.isdigit():
            errors.append("context has an invalid raw Slurm task job ID")
        scheduler_records, allocation, scheduler_errors = _accounting_for_force_task(
            accounting_records, primary_job_id, task_id, raw_job_id
        )
        errors.extend(scheduler_errors)
        if allocation is not None:
            try:
                elapsed = int(allocation["ElapsedRaw"])
                allocated_cpus = int(allocation["AllocCPUS"])
                if elapsed < 0 or allocated_cpus < 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append("sacct allocation has invalid ElapsedRaw or AllocCPUS")
            if exit_code is not None:
                try:
                    scheduler_exit_code = int(allocation["ExitCode"].split(":", 1)[0])
                except (AttributeError, TypeError, ValueError):
                    errors.append("sacct allocation has an invalid ExitCode")
                else:
                    if scheduler_exit_code != exit_code:
                        errors.append(
                            "upstream exit_code.txt disagrees with the sacct allocation"
                        )
        evidence = _hash_present_evidence(
            parent,
            (
                "context.tsv",
                "exit_code.txt",
                "finished_utc.txt",
                "force_claim.json",
                "launch.json",
                "result.json",
                "failure.json",
                "scf.process.json",
                "scf.in",
                "scf.out",
                "scf.err",
                "stdout.log",
                "stderr.log",
            ),
        )
        entry: dict[str, Any] = {
            "task_id": task_id,
            "displacement_id": task["displacement_id"],
            "role": task["role"],
            "attempt_path": str(parent),
            "context": context,
            "exit_code": exit_code,
            "scheduler_records": scheduler_records,
            "evidence": evidence,
            "errors": errors,
        }
        failure_path = parent / "failure.json"
        if failure_path.is_file():
            try:
                failure = load_json(failure_path)
                entry["failure_receipt"] = failure
                if failure.get("task_id") != task_id:
                    entry["errors"].append("failure receipt has the wrong task ID")
                if not isinstance(failure.get("error"), str) or not failure.get("error"):
                    entry["errors"].append("failure receipt has no error message")
                if not isinstance(failure.get("error_type"), str) or not failure.get(
                    "error_type"
                ):
                    entry["errors"].append("failure receipt has no error type")
            except CampaignError as exc:
                entry["errors"].append(f"invalid failure receipt: {exc}")
        elif exit_code not in (None, 0):
            entry["errors"].append("nonzero task exit lacks failure.json")
        if exit_code == 0:
            try:
                artifact = load_force_artifact(force_manifest_path, parent, task_id)
                launch = load_json(parent / "launch.json")
                if launch.get("job_id") != context.get("slurm_job_id"):
                    raise CampaignError("launch job ID differs from immutable task context")
                if allocation is None:
                    raise CampaignError("successful task lacks its scheduler allocation row")
                if (
                    _normalized_slurm_state(allocation["State"]) != "COMPLETED"
                    or allocation["ExitCode"] != "0:0"
                ):
                    raise CampaignError(
                        "successful raw force receipt disagrees with scheduler completion"
                    )
                entry["artifact"] = {
                    "input_path": artifact.input_path,
                    "output_path": artifact.output_path,
                    "stderr_path": artifact.stderr_path,
                    "receipt": dict(artifact.manifest),
                }
                entry["outcome"] = "accepted_success"
            except (CampaignError, PostprocessError, OSError, ValueError) as exc:
                entry["errors"].append(f"successful-task evidence audit failed: {exc}")
                entry["outcome"] = "invalid_success_evidence"
        elif exit_code is None:
            entry["outcome"] = "missing_or_unfinished"
        else:
            if allocation is not None and (
                _normalized_slurm_state(allocation["State"]) == "COMPLETED"
                and allocation["ExitCode"] == "0:0"
            ):
                entry["errors"].append(
                    "nonzero task exit code disagrees with scheduler success"
                )
            entry["outcome"] = "upstream_failed"
        entries.append(entry)

    accepted = sum(entry["outcome"] == "accepted_success" for entry in entries)
    failed = sum(entry["outcome"] == "upstream_failed" for entry in entries)
    unfinished_or_invalid = len(entries) - accepted - failed
    collection_integrity_complete = not global_errors and all(
        not entry["errors"] for entry in entries
    )
    batch_execution_complete = (
        collection_integrity_complete and accepted == len(tasks)
    )
    mode = str(manifest["mode"])
    return {
        "schema_version": 1,
        "stage": "collect",
        "collection_kind": "force_array_batch",
        "material": required(config, "material.formula"),
        "collected_utc": utc_now(),
        "collector_attempt": str(current_attempt),
        "primary": {
            "stage": "force",
            "attempt_id": primary_attempt_id,
            "job_id": primary_job_id,
            "attempt_root": str(primary_root),
            "force_manifest": str(force_manifest_path),
            "force_manifest_sha256": sha256_path(force_manifest_path),
            "submitted_force_manifest_sha256": expected_force_manifest_sha256,
            "task_map": str(task_map_path.resolve()),
            "task_map_sha256": sha256_path(task_map_path.resolve()),
            "submitted_task_map_sha256": expected_task_map_sha256,
            "scheduler_accounting": dict(accounting_metadata),
        },
        "force_mode": mode,
        "expected_task_count": len(tasks),
        "accepted_success_count": accepted,
        "upstream_failure_count": failed,
        "unfinished_or_invalid_count": unfinished_or_invalid,
        "collection_integrity_complete": collection_integrity_complete,
        "batch_execution_complete": batch_execution_complete,
        "incomplete": not batch_execution_complete,
        "status": (
            "collected_successful_batch_no_scientific_gate"
            if batch_execution_complete
            else "collected_incomplete_force_batch"
        ),
        "global_errors": global_errors,
        "entries": entries,
        "scientific_gate_published": False,
        "production_dataset_complete": False,
        "scientific_dataset_incomplete": True,
        "eligible_for_force_constant_construction": False,
        "limitations": [
            "This receipt covers exactly one immutable force-array submission.",
            "A pilot collection can support later audited selection but is never a production gate.",
            "A successful production batch is not proof that all selected displacement IDs are complete.",
            "No FC2/FC3 construction or thermal-conductivity postprocessing is performed here.",
        ],
    }


def _collect_single_attempt(
    *,
    config: Mapping[str, Any],
    run_dir: Path,
    current_attempt: Path,
    primary_stage: str,
    primary_attempt_id: str,
    primary_job_id: str,
    accounting_records: Sequence[Mapping[str, str]],
    accounting_errors: Sequence[str],
    accounting_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    parent = run_dir / "slurm_attempts" / primary_stage / primary_attempt_id
    context, errors = _read_context_tsv(parent / "context.tsv")
    errors.extend(accounting_errors)
    expected_context = {
        "stage": primary_stage,
        "attempt_id": primary_attempt_id,
        "slurm_job_id": primary_job_id,
        "run_dir": str(run_dir),
    }
    for key, expected in expected_context.items():
        if context.get(key) != expected:
            errors.append(f"context mismatch for {key}")
    exit_code, exit_errors = _read_exit_code(parent)
    errors.extend(exit_errors)
    scheduler_records = [
        dict(row)
        for row in accounting_records
        if row.get("JobIDRaw") == primary_job_id
        or str(row.get("JobIDRaw", "")).startswith(primary_job_id + ".")
    ]
    allocation = [row for row in scheduler_records if row["JobIDRaw"] == primary_job_id]
    if len(allocation) != 1:
        errors.append(
            f"expected one sacct allocation row for {primary_job_id}; found {len(allocation)}"
        )
    evidence = _hash_present_evidence(
        parent,
        (
            "context.tsv",
            "exit_code.txt",
            "finished_utc.txt",
            "starting_structure_audit.json",
            "relax_launch.json",
            "relax.process.json",
            "relax.out",
            "relax.err",
            "pristine_launch.json",
            "pristine.process.json",
            "pristine.out",
            "pristine.err",
            "execution_manifest.json",
            "relax_gate.json",
            "stdout.log",
            "stderr.log",
        ),
    )
    entry: dict[str, Any] = {
        "attempt_path": str(parent),
        "stage": primary_stage,
        "attempt_id": primary_attempt_id,
        "context": context,
        "exit_code": exit_code,
        "finished": exit_code is not None,
        "scheduler_records": scheduler_records,
        "evidence": evidence,
        "errors": errors,
    }
    nat = int(required(config, "material.unitcell_atoms"))
    for label, filename in (("relax_health", "relax.out"), ("pristine_health", "pristine.out")):
        path = parent / filename
        if path.is_file():
            try:
                entry[label] = inspect_output(path, nat)
            except (QEOutputError, OSError, ValueError) as exc:
                entry[label] = {"healthy": False, "error": str(exc)}
    return {
        "schema_version": 1,
        "stage": "collect",
        "collection_kind": "single_stage_attempt",
        "material": required(config, "material.formula"),
        "collected_utc": utc_now(),
        "collector_attempt": str(current_attempt),
        "primary": {
            "stage": primary_stage,
            "attempt_id": primary_attempt_id,
            "job_id": primary_job_id,
            "scheduler_accounting": dict(accounting_metadata),
        },
        "upstream_attempt_count": 1,
        "upstream_failures_or_unfinished": int(exit_code != 0),
        "incomplete": exit_code != 0 or bool(errors),
        "entries": [entry],
        "note": "Collection is evidentiary and succeeds even when the explicit afterany upstream failed.",
    }


def command_collect(
    config_path: Path,
    run_dir: Path,
    *,
    primary_stage: str,
    primary_attempt_id: str,
    primary_job_id: str,
    scheduler_accounting: Path,
    scheduler_accounting_status: Path,
    force_manifest: Path | None = None,
    task_map: Path | None = None,
    expected_force_manifest_sha256: str | None = None,
    expected_task_map_sha256: str | None = None,
    expected_primary_request_sha256: str | None = None,
    expected_primary_result_sha256: str | None = None,
    expected_primary_stage_script_sha256: str | None = None,
) -> dict[str, Any]:
    """Collect one explicitly identified upstream attempt without rerunning it."""

    require_compute_node()
    if primary_stage not in {"diagnostic", "relax", "force"}:
        raise CampaignError("collector primary stage must be diagnostic, relax, or force")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", primary_attempt_id) is None:
        raise CampaignError("invalid primary attempt ID")
    if not primary_job_id.isdigit():
        raise CampaignError("primary Slurm job ID must contain only digits")
    config_path = config_path.resolve()
    config, _ = validate_config(config_path)
    run_dir = safe_run_dir(run_dir)
    if primary_stage == "diagnostic":
        from polish_recovery import _load_lineage

        if os.path.lexists(run_dir / RUN_MANIFEST):
            raise CampaignError(
                "diagnostic collection must precede polish manifest release"
            )
        _load_lineage(config, run_dir)
    else:
        verify_upstream_manifest(
            config,
            config_path,
            run_dir,
            stage="preflight" if primary_stage == "force" else "structure",
        )
    current_attempt = attempt_dir(run_dir)
    reject_symlinks_below(run_dir, current_attempt, "collector Slurm attempt")
    accounting_path = strict_run_descendant(
        run_dir,
        scheduler_accounting,
        "scheduler accounting",
        require_exists=False,
    )
    accounting_status_path = strict_run_descendant(
        run_dir,
        scheduler_accounting_status,
        "scheduler accounting status",
        require_exists=False,
    )
    if accounting_path.parent != current_attempt or accounting_status_path.parent != current_attempt:
        raise CampaignError("scheduler accounting must be created inside this collector attempt")
    accounting_records, accounting_errors, accounting_metadata = _read_sacct_records(
        accounting_path,
        accounting_status_path,
        DIAGNOSTIC_SACCT_FIELDS if primary_stage == "diagnostic" else SACCT_FIELDS,
    )
    if primary_stage == "force":
        if any(
            value is not None
            for value in (
                expected_primary_request_sha256,
                expected_primary_result_sha256,
                expected_primary_stage_script_sha256,
            )
        ):
            raise CampaignError(
                "force collection must not receive diagnostic submission hashes"
            )
        if (
            force_manifest is None
            or task_map is None
            or expected_force_manifest_sha256 is None
            or expected_task_map_sha256 is None
        ):
            raise CampaignError(
                "force collection requires the exact submitted manifest/task map hashes"
            )
        report = _collect_force_batch(
            config=config,
            config_path=config_path,
            run_dir=run_dir,
            current_attempt=current_attempt,
            primary_attempt_id=primary_attempt_id,
            primary_job_id=primary_job_id,
            force_manifest_path=force_manifest,
            task_map_path=task_map,
            expected_force_manifest_sha256=expected_force_manifest_sha256,
            expected_task_map_sha256=expected_task_map_sha256,
            accounting_records=accounting_records,
            accounting_errors=accounting_errors,
            accounting_metadata=accounting_metadata,
        )
    elif primary_stage == "diagnostic":
        if (
            expected_primary_request_sha256 is None
            or expected_primary_result_sha256 is None
            or expected_primary_stage_script_sha256 is None
        ):
            raise CampaignError(
                "diagnostic collection requires primary request/result/stage hashes"
            )
        if any(
            value is not None
            for value in (
                force_manifest,
                task_map,
                expected_force_manifest_sha256,
                expected_task_map_sha256,
            )
        ):
            raise CampaignError(
                "diagnostic collection must not receive force-bundle paths"
            )
        report = _collect_diagnostic_attempt(
            config=config,
            config_path=config_path,
            run_dir=run_dir,
            current_attempt=current_attempt,
            primary_attempt_id=primary_attempt_id,
            primary_job_id=primary_job_id,
            expected_primary_request_sha256=expected_primary_request_sha256,
            expected_primary_result_sha256=expected_primary_result_sha256,
            expected_primary_stage_script_sha256=expected_primary_stage_script_sha256,
            accounting_records=accounting_records,
            accounting_errors=accounting_errors,
            accounting_metadata=accounting_metadata,
        )
    else:
        if (
            force_manifest is not None
            or task_map is not None
            or expected_force_manifest_sha256 is not None
            or expected_task_map_sha256 is not None
        ):
            raise CampaignError("relax collection must not receive force-bundle paths")
        if any(
            value is not None
            for value in (
                expected_primary_request_sha256,
                expected_primary_result_sha256,
                expected_primary_stage_script_sha256,
            )
        ):
            raise CampaignError(
                "relax collection must not receive diagnostic submission hashes"
            )
        report = _collect_single_attempt(
            config=config,
            run_dir=run_dir,
            current_attempt=current_attempt,
            primary_stage=primary_stage,
            primary_attempt_id=primary_attempt_id,
            primary_job_id=primary_job_id,
            accounting_records=accounting_records,
            accounting_errors=accounting_errors,
            accounting_metadata=accounting_metadata,
        )
    write_json_immutable(current_attempt / "collection.json", report)
    if primary_stage == "diagnostic":
        write_json_immutable(current_attempt / "collection_receipt.json", report)
    return report


def command_not_ready(name: str, config: Mapping[str, Any]) -> None:
    if required(config, "production.selection_required"):
        raise CampaignError(
            f"{name} is blocked: production selection is intentionally null until tight-relax, "
            "preflight, and force/amplitude pilots pass"
        )
    raise CampaignError(f"{name} implementation is not yet released for production use")


def command_prepare_pilot_dataset(
    config_path: Path,
    run_dir: Path,
    *,
    candidate_dir: Path,
    preflight_inventory: Path,
    output_dir: Path,
    probe_spec_path: Path,
) -> dict[str, Any]:
    """Prepare and immediately re-audit one immutable signed pilot dataset."""

    from pilot_dataset import prepare_pilot_dataset

    probe_spec = load_json(probe_spec_path.resolve())
    return prepare_pilot_dataset(
        config_path,
        run_dir,
        candidate_dir=candidate_dir,
        preflight_inventory=preflight_inventory,
        output_dir=output_dir,
        probe_spec=probe_spec,
    )


def command_audit_pilot_dataset(
    dataset_dir: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    """Re-audit a pilot bundle against a caller-supplied trusted digest."""

    if re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None:
        raise CampaignError("--expect-manifest-sha must be 64 lowercase hex characters")
    from pilot_dataset import audit_pilot_dataset

    return audit_pilot_dataset(
        dataset_dir, expected_manifest_sha256=expected_manifest_sha256
    )


def command_prepare_force(
    config_path: Path,
    run_dir: Path,
    *,
    preflight_inventory: Path,
    dataset_dir: Path,
    output_dir: Path,
    pseudo_dir: Path,
    mode: str,
    pilot_spec_path: Path | None,
    pilot_dataset_manifest_sha256: str | None,
    selection_evidence: Path | None,
    resource_request_path: Path,
) -> dict[str, Any]:
    """Prepare one budgeted immutable force bundle; never launch a calculation."""

    if mode == "pilot":
        if (
            pilot_dataset_manifest_sha256 is None
            or re.fullmatch(r"[0-9a-f]{64}", pilot_dataset_manifest_sha256) is None
        ):
            raise CampaignError(
                "pilot prepare-force requires --expect-pilot-manifest-sha as 64 lowercase hex characters"
            )
    elif pilot_dataset_manifest_sha256 is not None:
        raise CampaignError(
            "production prepare-force must not receive --expect-pilot-manifest-sha"
        )
    from force_backend import prepare_force

    pilot_spec = load_json(pilot_spec_path.resolve()) if pilot_spec_path else None
    resource_request = load_json(resource_request_path.resolve())
    return prepare_force(
        config_path,
        run_dir,
        preflight_inventory=preflight_inventory,
        dataset_dir=dataset_dir,
        output_dir=output_dir,
        pseudo_dir=pseudo_dir,
        mode=mode,
        pilot_spec=pilot_spec,
        pilot_dataset_manifest_sha256=pilot_dataset_manifest_sha256,
        selection_evidence=selection_evidence,
        resource_request=resource_request,
    )


def command_run_force_task(
    config_path: Path,
    run_dir: Path,
    *,
    task_map: Path,
    task_id: int,
    retry_evidence: Path | None,
) -> dict[str, Any]:
    """Execute one force-map row in the current immutable Slurm attempt."""

    from force_backend import run_force_task

    return run_force_task(
        config_path,
        run_dir,
        task_map=task_map,
        task_id=task_id,
        attempt_path=attempt_dir(run_dir),
        retry_evidence=retry_evidence,
    )


def command_audit_pilot_evidence(
    config_path: Path, run_dir: Path, *, study_path: Path
) -> dict[str, Any]:
    """Reparse a study's original pilot files without evaluating a pass claim."""

    from pilot_evidence import audit_pilot_samples

    study = load_json(study_path.resolve())
    return audit_pilot_samples(
        config_path,
        run_dir,
        dataset_manifests=required(study, "dataset_manifests"),
        sample_references=required(study, "samples"),
        target_preflight=study.get("target_preflight"),
        selected_settings=study.get("selected_settings"),
    )


def command_analyze_pilot(
    config_path: Path, run_dir: Path, *, study_path: Path, output_path: Path
) -> dict[str, Any]:
    """Replay raw evidence, evaluate explicit gates, and write one receipt."""

    from pilot_evidence import write_selection_receipt

    return write_selection_receipt(
        config_path,
        run_dir,
        study=load_json(study_path.resolve()),
        output_path=output_path,
    )


def command_replay_pilot_selection(
    config_path: Path,
    run_dir: Path,
    *,
    receipt_path: Path,
    expected_receipt_sha256: str | None,
) -> dict[str, Any]:
    """Recompute a saved pilot receipt from its immutable original evidence."""

    if expected_receipt_sha256 is not None and re.fullmatch(
        r"[0-9a-f]{64}", expected_receipt_sha256
    ) is None:
        raise CampaignError("--expect-receipt-sha must be 64 lowercase hex characters")
    from pilot_evidence import replay_selection_receipt

    return replay_selection_receipt(
        config_path,
        run_dir,
        receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
    )


def _force_finalize_ref(path: Path, run_dir: Path, label: str) -> dict[str, str]:
    """Return one strict, live path/hash reference for the standalone finalizer."""

    from force_finalize import ForceFinalizeError, _safe_descendant

    try:
        resolved = _safe_descendant(Path(path), run_dir, label, file=True)
    except ForceFinalizeError as exc:
        raise CampaignError(str(exc)) from exc
    return {"path": str(resolved), "sha256": sha256_path(resolved)}


def _force_finalize_tolerances(config: Mapping[str, Any]) -> dict[str, float]:
    """Read the two cross-batch pristine tolerances without supplying defaults."""

    production = required(config, "production")
    if (
        not isinstance(production, Mapping)
        or production.get("selection_required") is not False
        or production.get("automatic_submission_allowed") is not True
    ):
        raise CampaignError("production selection has not been released")
    value = required(config, "production.pristine_comparison_tolerances_ry_bohr")
    if not isinstance(value, Mapping) or set(value) != {
        "maximum_component",
        "rms_component",
    }:
        raise CampaignError(
            "production.pristine_comparison_tolerances_ry_bohr must explicitly "
            "contain maximum_component and rms_component"
        )
    result: dict[str, float] = {}
    for name in ("maximum_component", "rms_component"):
        raw = value[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise CampaignError(f"pristine {name} tolerance must be numeric")
        number = float(raw)
        if not math.isfinite(number) or number < 0:
            raise CampaignError(
                f"pristine {name} tolerance must be finite and non-negative"
            )
        result[name] = number
    return result


def _unique_manifest_evidence(
    manifest: Mapping[str, Any], run_dir: Path, filename: str
) -> Path:
    evidence = manifest.get("evidence_sha256")
    if not isinstance(evidence, Mapping):
        raise CampaignError("production force manifest lacks source hashes")
    matches = [
        Path(raw_path)
        for raw_path, digest in evidence.items()
        if isinstance(raw_path, str)
        and Path(raw_path).name == filename
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest)
    ]
    if len(matches) != 1:
        raise CampaignError(
            f"production force manifest must bind exactly one {filename}; "
            f"found {len(matches)}"
        )
    path = _strict_evidence_path(matches[0], run_dir, filename)
    if not path.is_file() or sha256_path(path) != evidence[str(matches[0])]:
        raise CampaignError(f"production force manifest {filename} hash mismatch")
    return path


def _force_finalize_batch(
    collection_path: Path, run_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Translate one explicit completed collection into a fully hashed plan batch."""

    collection_ref = _force_finalize_ref(
        collection_path, run_dir, "production collection"
    )
    collection = load_json(Path(collection_ref["path"]))
    if (
        collection.get("schema_version") != 1
        or collection.get("stage") != "collect"
        or collection.get("collection_kind") != "force_array_batch"
        or collection.get("force_mode") != "production"
        or collection.get("collection_integrity_complete") is not True
        or collection.get("batch_execution_complete") is not True
        or collection.get("incomplete") is not False
    ):
        raise CampaignError("force-finalize requires a completed production collection")
    primary = collection.get("primary")
    if not isinstance(primary, Mapping):
        raise CampaignError("production collection lacks primary submission metadata")
    attempt_id = primary.get("attempt_id")
    if not isinstance(attempt_id, str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id
    ) is None:
        raise CampaignError("production collection has an invalid submission attempt ID")
    manifest_path = Path(str(primary.get("force_manifest", "")))
    task_map_path = Path(str(primary.get("task_map", "")))
    manifest_ref = _force_finalize_ref(manifest_path, run_dir, "force manifest")
    task_map_ref = _force_finalize_ref(task_map_path, run_dir, "force task map")
    if (
        manifest_ref["sha256"] != primary.get("force_manifest_sha256")
        or manifest_ref["sha256"] != primary.get("submitted_force_manifest_sha256")
        or task_map_ref["sha256"] != primary.get("task_map_sha256")
        or task_map_ref["sha256"] != primary.get("submitted_task_map_sha256")
    ):
        raise CampaignError("production collection does not bind submitted force inputs")
    manifest = load_json(Path(manifest_ref["path"]))
    if manifest.get("mode") != "production" or manifest.get("stage") != "force":
        raise CampaignError("collection force manifest is not a production manifest")
    budget_path = Path(manifest_ref["path"]).parent / "budget_receipt.json"
    budget_ref = _force_finalize_ref(budget_path, run_dir, "force budget receipt")
    if budget_ref["sha256"] != manifest.get("budget_receipt_sha256"):
        raise CampaignError("force budget receipt hash differs from its manifest")

    from force_backend import replay_budget_ledger
    reservation_matches = [
        item["path"] for item in replay_budget_ledger(run_dir)
        if item["record"]["receipt_path"] == budget_ref["path"]
        and item["record"]["receipt_sha256"] == budget_ref["sha256"]
    ]
    if len(reservation_matches) != 1:
        raise CampaignError(
            "budget receipt must be anchored by exactly one force-budget ledger reservation"
        )

    submission_dir = run_dir / "submissions" / "force" / attempt_id
    references = {
        "submission_request": _force_finalize_ref(
            submission_dir / "request.json", run_dir, "force submission request"
        ),
        "submission_result": _force_finalize_ref(
            submission_dir / "primary_result.json", run_dir, "force submission result"
        ),
        "submission_summary": _force_finalize_ref(
            submission_dir / "submission.json", run_dir, "force submission summary"
        ),
        "collector_request": _force_finalize_ref(
            submission_dir / "collector_request.json", run_dir, "collector request"
        ),
        "collector_result": _force_finalize_ref(
            submission_dir / "collector_result.json", run_dir, "collector result"
        ),
    }
    summary = load_json(Path(references["submission_summary"]["path"]))
    collector = summary.get("collector")
    if not isinstance(collector, Mapping):
        raise CampaignError("force submission summary lacks its collector identity")
    expected_collection = (
        run_dir
        / "slurm_attempts"
        / "collect"
        / str(collector.get("attempt_id", ""))
        / "collection.json"
    )
    if Path(collection_ref["path"]) != expected_collection:
        raise CampaignError("explicit collection is not the submitted collector output")

    scheduler = primary.get("scheduler_accounting")
    if not isinstance(scheduler, Mapping):
        raise CampaignError("production collection lacks scheduler accounting references")
    accounting_ref = _force_finalize_ref(
        Path(str(scheduler.get("path", ""))), run_dir, "scheduler accounting"
    )
    accounting_status_ref = _force_finalize_ref(
        Path(str(scheduler.get("status_path", ""))),
        run_dir,
        "scheduler accounting status",
    )
    if (
        accounting_ref["sha256"] != scheduler.get("sha256")
        or accounting_status_ref["sha256"] != scheduler.get("status_sha256")
        or scheduler.get("sacct_exit_code") != 0
    ):
        raise CampaignError("production collection scheduler accounting is not hash-bound")

    entries = collection.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CampaignError("production collection has no force-task entries")
    raw_artifacts: list[dict[str, Any]] = []
    raw_names = (
        "context.tsv",
        "exit_code.txt",
        "finished_utc.txt",
        "force_claim.json",
        "launch.json",
        "result.json",
        "scf.process.json",
        "scf.in",
        "scf.out",
        "scf.err",
    )
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise CampaignError("production collection has a malformed force-task entry")
        task_id = entry.get("task_id")
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0:
            raise CampaignError("production collection has an invalid force-task ID")
        attempt_path = Path(str(entry.get("attempt_path", "")))
        evidence = entry.get("evidence")
        if not isinstance(evidence, Mapping):
            raise CampaignError(f"force task {task_id} lacks collected raw hashes")
        hashes: dict[str, str] = {}
        for name in raw_names:
            item = evidence.get(name)
            if not isinstance(item, Mapping):
                raise CampaignError(f"force task {task_id} lacks raw evidence {name}")
            reference = _force_finalize_ref(
                attempt_path / name, run_dir, f"force task {task_id} {name}"
            )
            if reference["sha256"] != item.get("sha256"):
                raise CampaignError(f"force task {task_id} {name} hash mismatch")
            hashes[name] = reference["sha256"]
        raw_artifacts.append(
            {
                "task_id": task_id,
                "attempt_path": str(attempt_path.resolve()),
                "files_sha256": hashes,
            }
        )

    batch = {
        "batch_id": attempt_id,
        "collection": collection_ref,
        "force_manifest": manifest_ref,
        "task_map": task_map_ref,
        "budget_receipt": budget_ref,
        "budget_ledger_reservation": _force_finalize_ref(
            reservation_matches[0], run_dir, "force-budget ledger reservation"
        ),
        **references,
        "scheduler_accounting": accounting_ref,
        "scheduler_accounting_status": accounting_status_ref,
        "raw_artifacts": sorted(raw_artifacts, key=lambda item: item["task_id"]),
    }
    return batch, manifest


def command_plan_force_finalize(
    config_path: Path,
    run_dir: Path,
    *,
    output_path: Path,
    collection_paths: Sequence[Path] | None,
    submission_attempt_ids: Sequence[str] | None,
    canonical_pristine_batch_id: str,
) -> dict[str, Any]:
    """Create and fully replay one explicit local production-force plan."""

    from force_finalize import ForceFinalizeError, _audit

    config_path = Path(config_path).resolve()
    run_dir = safe_run_dir(Path(run_dir))
    config, _ = validate_config(config_path)
    tolerances = _force_finalize_tolerances(config)
    explicit_collections = list(collection_paths or ())
    attempt_ids = list(submission_attempt_ids or ())
    if bool(explicit_collections) == bool(attempt_ids):
        raise CampaignError(
            "supply exactly one source mode: one or more --collection values or "
            "one or more --submission-attempt-id values"
        )
    if attempt_ids:
        if len(set(attempt_ids)) != len(attempt_ids):
            raise CampaignError("submission attempt IDs must be unique")
        explicit_collections = []
        for attempt_id in attempt_ids:
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id) is None:
                raise CampaignError(f"invalid submission attempt ID: {attempt_id}")
            summary_path = (
                run_dir / "submissions" / "force" / attempt_id / "submission.json"
            )
            summary_path = Path(
                _force_finalize_ref(
                    summary_path, run_dir, f"submission attempt {attempt_id} summary"
                )["path"]
            )
            summary = load_json(summary_path)
            collector = summary.get("collector")
            if summary.get("attempt_id") != attempt_id or not isinstance(
                collector, Mapping
            ):
                raise CampaignError(
                    f"submission attempt {attempt_id} lacks one exact collector"
                )
            collector_attempt = collector.get("attempt_id")
            if not isinstance(collector_attempt, str) or not collector_attempt:
                raise CampaignError(
                    f"submission attempt {attempt_id} has no collector attempt ID"
                )
            explicit_collections.append(
                run_dir
                / "slurm_attempts"
                / "collect"
                / collector_attempt
                / "collection.json"
            )
    resolved_collections = [
        Path(_force_finalize_ref(path, run_dir, "production collection")["path"])
        for path in explicit_collections
    ]
    if len(set(resolved_collections)) != len(resolved_collections):
        raise CampaignError("production collections must be unique")

    built = [_force_finalize_batch(path, run_dir) for path in resolved_collections]
    batches = [item[0] for item in built]
    manifests = [item[1] for item in built]
    if len({batch["batch_id"] for batch in batches}) != len(batches):
        raise CampaignError("multiple collections claim the same production submission")
    if canonical_pristine_batch_id not in {batch["batch_id"] for batch in batches}:
        raise CampaignError("canonical pristine batch ID is absent from explicit collections")

    canonical_index = next(
        index
        for index, batch in enumerate(batches)
        if batch["batch_id"] == canonical_pristine_batch_id
    )
    canonical_manifest = manifests[canonical_index]
    pristine_tasks = [
        task
        for task in canonical_manifest.get("tasks", [])
        if isinstance(task, Mapping)
        and task.get("displacement_id") == 0
        and task.get("role") == "pristine"
    ]
    if len(pristine_tasks) != 1:
        raise CampaignError(
            "canonical production batch must contain exactly one pristine task"
        )
    pristine_task_id = pristine_tasks[0].get("task_id")
    canonical_raw = next(
        (
            item
            for item in batches[canonical_index]["raw_artifacts"]
            if item["task_id"] == pristine_task_id
        ),
        None,
    )
    if canonical_raw is None:
        raise CampaignError("canonical pristine raw artifact is absent")

    first_manifest = manifests[0]
    dataset = _unique_manifest_evidence(
        first_manifest, run_dir, "phono3py_disp.yaml"
    )
    inventory = _unique_manifest_evidence(
        first_manifest, run_dir, "preflight_inventory.json"
    )
    preflight_result = _unique_manifest_evidence(
        first_manifest, run_dir, "preflight_result.json"
    )
    accepted_paths = {
        "gate": run_dir / "relax" / "final" / "gate.json",
        "provenance": run_dir / "relax" / "final" / "provenance.json",
        "unitcell": run_dir / "relax" / "final" / "unitcell.in",
    }
    selection = first_manifest.get("selection_validation")
    if not isinstance(selection, Mapping):
        raise CampaignError("production force manifest lacks selection validation")
    selection_path = Path(str(selection.get("selection_receipt_path", "")))

    fixed_hashes = {
        str(path.resolve()): sha256_path(path.resolve())
        for path in (*accepted_paths.values(), inventory, preflight_result, dataset)
    }
    selection_ref = _force_finalize_ref(
        selection_path, run_dir, "selection receipt"
    )
    for manifest in manifests:
        evidence = manifest.get("evidence_sha256")
        validation = manifest.get("selection_validation")
        if not isinstance(evidence, Mapping) or any(
            evidence.get(path) != digest for path, digest in fixed_hashes.items()
        ):
            raise CampaignError(
                "production batches do not bind identical accepted sources"
            )
        if (
            not isinstance(validation, Mapping)
            or validation.get("selection_receipt_path") != selection_ref["path"]
            or validation.get("selection_receipt_sha256") != selection_ref["sha256"]
        ):
            raise CampaignError(
                "production batches do not bind one selection receipt"
            )
        for filename, expected in (
            ("phono3py_disp.yaml", dataset),
            ("preflight_inventory.json", inventory),
            ("preflight_result.json", preflight_result),
        ):
            if _unique_manifest_evidence(manifest, run_dir, filename) != expected:
                raise CampaignError(
                    "production batches refer to different preflight evidence"
                )

    plan = {
        "schema_version": 1,
        "stage": "force_finalize_plan",
        "material": required(config, "material.formula"),
        "config_sha256": sha256_path(config_path),
        "accepted_structure": {
            name: _force_finalize_ref(path, run_dir, f"accepted structure {name}")
            for name, path in accepted_paths.items()
        },
        "selected_preflight": {
            "inventory": _force_finalize_ref(
                inventory, run_dir, "preflight inventory"
            ),
            "result": _force_finalize_ref(
                preflight_result, run_dir, "preflight result"
            ),
            "dataset": _force_finalize_ref(
                dataset, run_dir, "phono3py displacement dataset"
            ),
        },
        "selection_receipt": selection_ref,
        "pristine_comparison_tolerances_ry_bohr": tolerances,
        "canonical_pristine": {
            "batch_id": canonical_pristine_batch_id,
            "task_id": pristine_task_id,
            "output_sha256": canonical_raw["files_sha256"]["scf.out"],
        },
        "batches": batches,
    }
    output_path = Path(os.path.abspath(output_path))
    if output_path.exists():
        raise CampaignError(f"force-finalize plan output already exists: {output_path}")
    output_parent = output_path.parent
    if (
        not output_parent.resolve().is_relative_to(run_dir)
        or "READY_TO_ATTACH" in output_path.parts
    ):
        raise CampaignError(
            "force-finalize plan output must be below RUN_DIR in a non-symlink directory"
        )
    current = output_parent
    while True:
        if current.is_symlink():
            raise CampaignError(
                "force-finalize plan output path may not contain a symlink"
            )
        if current.resolve() == run_dir:
            break
        parent = current.parent
        if parent == current:
            raise CampaignError("force-finalize plan output path does not reach RUN_DIR")
        current = parent
    output_parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix=".force-finalize-plan-audit-",
            suffix=".json",
            dir=output_parent,
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        _audit(config_path, run_dir, temporary_path, sha256_path(temporary_path))
    except ForceFinalizeError as exc:
        raise CampaignError(f"force-finalize plan audit failed: {exc}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    write_immutable(output_path, payload)
    return {
        "healthy": True,
        "stage": "force_finalize_plan",
        "plan": str(output_path),
        "plan_sha256": sha256_path(output_path),
        "batch_count": len(batches),
        "canonical_pristine": plan["canonical_pristine"],
        "finalize_requirement": (
            "Run finalize-force with --expect-plan-sha exactly equal to plan_sha256."
        ),
    }


def command_finalize_force(
    config_path: Path,
    run_dir: Path,
    *,
    plan_path: Path,
    expected_plan_sha256: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Call the standalone force finalizer locally with one explicit plan digest."""

    from force_finalize import ForceFinalizeError, finalize_force_dataset

    run_dir = safe_run_dir(Path(run_dir))
    if re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256) is None:
        raise CampaignError("--expect-plan-sha must be 64 lowercase hex characters")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id) is None:
        raise CampaignError("invalid force-finalize attempt ID")
    plan_path = Path(os.path.abspath(plan_path))
    plan_ref = _force_finalize_ref(plan_path, run_dir, "force-finalize plan")
    if plan_ref["sha256"] != expected_plan_sha256:
        raise CampaignError("force-finalize plan hash mismatch")
    plan = load_json(Path(plan_ref["path"]))
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        raise CampaignError("force-finalize plan has no production batches")
    for batch in batches:
        if not isinstance(batch, Mapping):
            raise CampaignError("force-finalize plan contains a malformed batch")
        budget_ref = batch.get("budget_receipt")
        ledger_ref = batch.get("budget_ledger_reservation")
        if not isinstance(budget_ref, Mapping) or not isinstance(ledger_ref, Mapping):
            raise CampaignError(
                "force-finalize plan must bind each budget receipt to its ledger reservation"
            )
        checked_budget = _force_finalize_ref(
            Path(str(budget_ref.get("path", ""))), run_dir, "force budget receipt"
        )
        checked_ledger = _force_finalize_ref(
            Path(str(ledger_ref.get("path", ""))),
            run_dir,
            "force-budget ledger reservation",
        )
        if checked_budget != dict(budget_ref) or checked_ledger != dict(ledger_ref):
            raise CampaignError("force-finalize budget or ledger reference hash mismatch")
        reservation = load_json(Path(checked_ledger["path"]))
        if (
            reservation.get("receipt_path") != checked_budget["path"]
            or reservation.get("receipt_sha256") != checked_budget["sha256"]
        ):
            raise CampaignError("force-finalize ledger does not bind its budget receipt")
    attempt = run_dir / "slurm_attempts" / "force-finalize" / attempt_id
    try:
        attempt.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CampaignError(f"force-finalize attempt already exists: {attempt}") from exc
    try:
        return finalize_force_dataset(
            Path(config_path).resolve(),
            run_dir,
            plan_path,
            expected_plan_sha256=expected_plan_sha256,
            attempt_dir=attempt,
        )
    except ForceFinalizeError as exc:
        raise CampaignError(f"force finalization failed: {exc}") from exc


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
        "collect",
        "postprocess",
        "audit",
        "status",
    ):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--config", type=Path, required=True)
        subparser.add_argument("--run-dir", type=Path, required=name != "validate-config")
        if name == "preflight":
            subparser.add_argument("--candidate-id", action="append", dest="candidate_ids")
            subparser.add_argument("--expect-candidate-subset-sha")
        if name == "collect":
            subparser.add_argument(
                "--primary-stage", choices=("diagnostic", "relax", "force"), required=True
            )
            subparser.add_argument("--primary-attempt-id", required=True)
            subparser.add_argument("--primary-job-id", required=True)
            subparser.add_argument(
                "--scheduler-accounting", type=Path, required=True
            )
            subparser.add_argument(
                "--scheduler-accounting-status", type=Path, required=True
            )
            subparser.add_argument("--force-manifest", type=Path)
            subparser.add_argument("--task-map", type=Path)
            subparser.add_argument("--expect-force-manifest-sha")
            subparser.add_argument("--expect-task-map-sha")
            subparser.add_argument("--expect-primary-request-sha")
            subparser.add_argument("--expect-primary-result-sha")
            subparser.add_argument("--expect-primary-stage-script-sha")
    pilot_dataset = subparsers.add_parser("prepare-pilot-dataset")
    pilot_dataset.add_argument("--config", type=Path, required=True)
    pilot_dataset.add_argument("--run-dir", type=Path, required=True)
    pilot_dataset.add_argument("--candidate-dir", type=Path, required=True)
    pilot_dataset.add_argument("--preflight-inventory", type=Path, required=True)
    pilot_dataset.add_argument("--output-dir", type=Path, required=True)
    pilot_dataset.add_argument("--probe-spec", type=Path, required=True)

    pilot_audit = subparsers.add_parser("audit-pilot-dataset")
    pilot_audit.add_argument("--config", type=Path, required=True)
    pilot_audit.add_argument("--run-dir", type=Path, required=True)
    pilot_audit.add_argument("--dataset-dir", type=Path, required=True)
    pilot_audit.add_argument("--expect-manifest-sha", required=True)

    prepare_force = subparsers.add_parser("prepare-force")
    prepare_force.add_argument("--config", type=Path, required=True)
    prepare_force.add_argument("--run-dir", type=Path, required=True)
    prepare_force.add_argument("--preflight-inventory", type=Path, required=True)
    prepare_force.add_argument("--dataset-dir", type=Path, required=True)
    prepare_force.add_argument("--output-dir", type=Path, required=True)
    prepare_force.add_argument("--pseudo-dir", type=Path, required=True)
    prepare_force.add_argument("--mode", choices=("pilot", "production"), required=True)
    prepare_force.add_argument("--pilot-spec", type=Path)
    prepare_force.add_argument("--expect-pilot-manifest-sha")
    prepare_force.add_argument("--selection-evidence", type=Path)
    prepare_force.add_argument("--resource-request", type=Path, required=True)

    pilot_evidence = subparsers.add_parser("audit-pilot-evidence")
    pilot_evidence.add_argument("--config", type=Path, required=True)
    pilot_evidence.add_argument("--run-dir", type=Path, required=True)
    pilot_evidence.add_argument("--study", type=Path, required=True)

    analyze_pilot = subparsers.add_parser("analyze-pilot")
    analyze_pilot.add_argument("--config", type=Path, required=True)
    analyze_pilot.add_argument("--run-dir", type=Path, required=True)
    analyze_pilot.add_argument("--study", type=Path, required=True)
    analyze_pilot.add_argument("--output", type=Path, required=True)

    replay_pilot = subparsers.add_parser("replay-pilot-selection")
    replay_pilot.add_argument("--config", type=Path, required=True)
    replay_pilot.add_argument("--run-dir", type=Path, required=True)
    replay_pilot.add_argument("--receipt", type=Path, required=True)
    replay_pilot.add_argument("--expect-receipt-sha")

    force_finalize_plan = subparsers.add_parser("plan-force-finalize")
    force_finalize_plan.add_argument("--config", type=Path, required=True)
    force_finalize_plan.add_argument("--run-dir", type=Path, required=True)
    force_finalize_plan.add_argument("--output", type=Path, required=True)
    sources = force_finalize_plan.add_mutually_exclusive_group(required=True)
    sources.add_argument(
        "--collection", type=Path, action="append", dest="collections"
    )
    sources.add_argument(
        "--submission-attempt-id", action="append", dest="submission_attempt_ids"
    )
    force_finalize_plan.add_argument(
        "--canonical-pristine-batch-id", required=True
    )

    force_finalize = subparsers.add_parser("finalize-force")
    force_finalize.add_argument("--config", type=Path, required=True)
    force_finalize.add_argument("--run-dir", type=Path, required=True)
    force_finalize.add_argument("--plan", type=Path, required=True)
    force_finalize.add_argument("--expect-plan-sha", required=True)
    force_finalize.add_argument("--attempt-id", required=True)

    force_task = subparsers.add_parser("run-force-task")
    force_task.add_argument("--config", type=Path, required=True)
    force_task.add_argument("--run-dir", type=Path, required=True)
    force_task.add_argument("--task-map", type=Path, required=True)
    force_task.add_argument("--task-id", type=int, required=True)
    force_task.add_argument("--retry-evidence", type=Path)
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
            result = command_preflight(
                args.config,
                run_dir,
                candidate_ids=args.candidate_ids,
                expected_candidate_subset_sha256=args.expect_candidate_subset_sha,
            )
        elif args.command == "status":
            result = command_status(args.config, run_dir)
        elif args.command == "collect":
            result = command_collect(
                args.config,
                run_dir,
                primary_stage=args.primary_stage,
                primary_attempt_id=args.primary_attempt_id,
                primary_job_id=args.primary_job_id,
                scheduler_accounting=args.scheduler_accounting,
                scheduler_accounting_status=args.scheduler_accounting_status,
                force_manifest=args.force_manifest,
                task_map=args.task_map,
                expected_force_manifest_sha256=args.expect_force_manifest_sha,
                expected_task_map_sha256=args.expect_task_map_sha,
                expected_primary_request_sha256=args.expect_primary_request_sha,
                expected_primary_result_sha256=args.expect_primary_result_sha,
                expected_primary_stage_script_sha256=args.expect_primary_stage_script_sha,
            )
        elif args.command == "run-relax":
            result = command_run_relax(args.config, run_dir)
        elif args.command == "finalize-relax":
            result = command_finalize_relax(args.config, run_dir)
        elif args.command == "prepare-pilot-dataset":
            result = command_prepare_pilot_dataset(
                args.config,
                run_dir,
                candidate_dir=args.candidate_dir,
                preflight_inventory=args.preflight_inventory,
                output_dir=args.output_dir,
                probe_spec_path=args.probe_spec,
            )
        elif args.command == "audit-pilot-dataset":
            # Validate the material config too; the pilot manifest then provides
            # the exact snapshot and source hashes used by the geometry audit.
            validate_config(args.config)
            result = command_audit_pilot_dataset(
                args.dataset_dir,
                expected_manifest_sha256=args.expect_manifest_sha,
            )
        elif args.command == "prepare-force":
            result = command_prepare_force(
                args.config,
                run_dir,
                preflight_inventory=args.preflight_inventory,
                dataset_dir=args.dataset_dir,
                output_dir=args.output_dir,
                pseudo_dir=args.pseudo_dir,
                mode=args.mode,
                pilot_spec_path=args.pilot_spec,
                pilot_dataset_manifest_sha256=args.expect_pilot_manifest_sha,
                selection_evidence=args.selection_evidence,
                resource_request_path=args.resource_request,
            )
        elif args.command == "run-force-task":
            result = command_run_force_task(
                args.config,
                run_dir,
                task_map=args.task_map,
                task_id=args.task_id,
                retry_evidence=args.retry_evidence,
            )
        elif args.command == "audit-pilot-evidence":
            result = command_audit_pilot_evidence(
                args.config, run_dir, study_path=args.study
            )
        elif args.command == "analyze-pilot":
            result = command_analyze_pilot(
                args.config,
                run_dir,
                study_path=args.study,
                output_path=args.output,
            )
        elif args.command == "replay-pilot-selection":
            result = command_replay_pilot_selection(
                args.config,
                run_dir,
                receipt_path=args.receipt,
                expected_receipt_sha256=args.expect_receipt_sha,
            )
        elif args.command == "plan-force-finalize":
            result = command_plan_force_finalize(
                args.config,
                run_dir,
                output_path=args.output,
                collection_paths=args.collections,
                submission_attempt_ids=args.submission_attempt_ids,
                canonical_pristine_batch_id=args.canonical_pristine_batch_id,
            )
        elif args.command == "finalize-force":
            result = command_finalize_force(
                args.config,
                run_dir,
                plan_path=args.plan,
                expected_plan_sha256=args.expect_plan_sha,
                attempt_id=args.attempt_id,
            )
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

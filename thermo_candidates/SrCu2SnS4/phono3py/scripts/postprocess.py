#!/usr/bin/env python
"""Strict read-only gate for the retired SrCu2SnS4 legacy postprocessor.

This script never constructs force constants or writes kappa products.  After
auditing the preserved QE evidence it stops and directs a future campaign to
the v2 postprocessor, which must use a new empty output directory and a
run-bound fingerprint.  That separation prevents the archived pre- and
post-residual-correction HDF5 files from being reused as convergence evidence.

``select_converged_qmesh`` records the required v2 convergence policy: every
mesh must provide 300--900 K in 100-K steps; xx, yy, and zz must each change
by less than 5% for two consecutive trailing mesh steps.  Failure to meet the
policy returns no selected mesh.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # phono3py/
SHARED_CAMPAIGN = ROOT.parents[1] / "scripts" / "phono3py_campaign"
sys.path.insert(0, str(SHARED_CAMPAIGN))
from postprocess_backend import PostprocessError, canonical_hash, qe_settings
from qe_output import QEOutputError, inspect_force_run

EXPECTED_ATOMS = 96
EXPECTED_DISPLACEMENTS = 168
TARGET_CUTOFF_ANGSTROM = 4.0
BOHR_PER_ANGSTROM = 1.0 / 0.529177210903
QMESH_RELATIVE_TOLERANCE = 0.05
QMESH_TEMPERATURES = tuple(range(300, 901, 100))


class LegacyGateError(ValueError):
    """Historical force evidence cannot support a new FC construction."""


def legacy_cutoff_inventory(dataset: Path) -> dict[str, float | int | str]:
    """Read the small, stable YAML subset needed for the legacy cutoff gate.

    This deliberately does not reinterpret an old 4.0-bohr dataset as a 4-A
    dataset.  phono3py stores its length unit in the YAML, so the requested
    4.0 A cutoff must be represented by about 7.5589045 bohr.
    """
    text = dataset.read_text(errors="replace")
    unit = re.search(r"(?m)^physical_unit:\s*$\n(?:^[ \t].*$\n?)*?^[ \t]+length:\s*[\"']?([^\s\"']+)", text)
    cutoff = re.search(r"(?m)^displacement_pair_info:\s*$\n(?:^[ \t].*$\n?)*?^[ \t]+cutoff_pair_distance:\s*([0-9.eE+-]+)", text)
    pair_count = re.search(r"(?m)^\s+number_of_pairs_in_cutoff:\s*(\d+)\s*$", text)
    pairs = [
        (float(distance), included == "true")
        for distance, included in re.findall(
            r"(?m)^\s+pair_distance:\s*([0-9.eE+-]+)\s*$\n^\s+included:\s*(true|false)\s*$",
            text,
        )
    ]
    if unit is None or cutoff is None or pair_count is None or not pairs:
        raise LegacyGateError("phono3py_disp.yaml is missing a required cutoff field")
    included = [distance for distance, enabled in pairs if enabled]
    nonzero = [distance for distance in included if distance > 1e-10]
    positive = [distance for distance, _ in pairs if distance > 1e-10]
    if not positive:
        raise LegacyGateError("phono3py_disp.yaml has no positive pair distance")
    return {
        "length_unit": unit.group(1),
        "cutoff_pair_distance_bohr": float(cutoff.group(1)),
        "number_of_pairs_in_cutoff": int(pair_count.group(1)),
        "included_pair_groups": len(included),
        "nonzero_included_pair_groups": len(nonzero),
        "shortest_nonzero_pair_distance_bohr": min(positive),
    }


def _legacy_force_paths(root: Path) -> list[tuple[str, Path, Path, Path]]:
    displaced = sorted(root.glob("fc_calcs/disp-*/scf.out"))
    entries = [
        ("pristine", root / "checks/pristine/scf.out", root / "checks/pristine/scf.err",
         root / "checks/pristine/scf.in")
    ]
    entries.extend(
        (output.parent.name, output, output.with_name("scf.err"), output.with_name("scf.in"))
        for output in displaced
    )
    return entries


def audit_legacy_evidence(root: Path) -> dict[str, object]:
    """Audit every preserved force run before any FC construction.

    The audit collects all failures rather than stopping at the first one, so
    a historical run cannot hide a second terminal or settings problem behind
    the first failure.  It is intentionally strict: fresh data must have one
    canonical QE settings fingerprint, including nosym/noinv.
    """
    entries = _legacy_force_paths(root)
    errors: list[str] = []
    if len(entries) != EXPECTED_DISPLACEMENTS + 1:
        errors.append(
            f"expected pristine plus {EXPECTED_DISPLACEMENTS} displaced runs, found {len(entries)}"
        )
    settings_by_label: dict[str, str] = {}
    force_reports: dict[str, dict[str, object]] = {}
    for label, output, stderr, input_path in entries:
        try:
            report = inspect_force_run(output, stderr, EXPECTED_ATOMS)
            force_reports[label] = report
            if not report["healthy"]:
                errors.append(f"{label} terminal state: {', '.join(report['errors'])}")
        except (OSError, QEOutputError, ValueError) as exc:
            errors.append(f"{label} force audit failed: {exc}")
        try:
            settings_by_label[label] = canonical_hash(qe_settings(input_path.read_text()))
        except (OSError, PostprocessError, ValueError) as exc:
            errors.append(f"{label} QE settings rejected: {exc}")
    unique_settings = set(settings_by_label.values())
    if len(settings_by_label) != len(entries):
        errors.append("all pristine/displaced inputs must have current nosym/noinv QE settings")
    elif len(unique_settings) != 1:
        errors.append("pristine/displaced QE settings are mixed")

    try:
        cutoff = legacy_cutoff_inventory(root / "phono3py_disp.yaml")
        expected_bohr = TARGET_CUTOFF_ANGSTROM * BOHR_PER_ANGSTROM
        if cutoff["length_unit"] != "au":
            errors.append("phono3py_disp.yaml length unit must be au")
        if not math.isclose(float(cutoff["cutoff_pair_distance_bohr"]), expected_bohr,
                            rel_tol=0.0, abs_tol=1e-6):
            errors.append(
                "cutoff_pair_distance must be 4.0 A = "
                f"{expected_bohr:.7f} bohr, not {cutoff['cutoff_pair_distance_bohr']:.7f} bohr"
            )
        if int(cutoff["nonzero_included_pair_groups"]) < 1:
            errors.append("cutoff includes no nonzero-distance displacement pair")
    except (OSError, LegacyGateError, ValueError) as exc:
        cutoff = None
        errors.append(f"phono3py cutoff audit failed: {exc}")

    report = {
        "force_reports": force_reports,
        "settings_sha256": settings_by_label,
        "cutoff": cutoff,
        "healthy": not errors,
        "errors": errors,
    }
    if errors:
        raise LegacyGateError("; ".join(errors))
    return report


def _validate_qmesh_observation(
    temperatures: object, kappa: object
) -> tuple[tuple[float, ...], tuple[tuple[float, float, float], ...]]:
    """Validate a full-temperature xx/yy/zz mesh observation without NumPy."""
    try:
        observed_temps = tuple(float(value) for value in temperatures)
        observed_kappa = tuple(
            tuple(float(value) for value in row[:3]) for row in kappa
        )
    except (TypeError, ValueError) as exc:
        raise LegacyGateError(f"invalid q-mesh observation: {exc}") from exc
    if observed_temps != QMESH_TEMPERATURES:
        raise LegacyGateError(
            "q-mesh observation must contain exactly 300--900 K in 100-K steps"
        )
    if len(observed_kappa) != len(QMESH_TEMPERATURES) or any(
        len(row) != 3 for row in observed_kappa
    ):
        raise LegacyGateError("q-mesh observation must provide xx, yy and zz at every temperature")
    if not all(math.isfinite(value) for row in observed_kappa for value in row):
        raise LegacyGateError("q-mesh observation contains a non-finite tensor component")
    return observed_temps, observed_kappa


def qmesh_step_passes(
    previous_temperatures: object,
    previous_kappa: object,
    current_temperatures: object,
    current_kappa: object,
) -> bool:
    """Return whether one refinement step passes every T and xx/yy/zz check."""
    _, previous = _validate_qmesh_observation(previous_temperatures, previous_kappa)
    _, current = _validate_qmesh_observation(current_temperatures, current_kappa)
    for old_row, new_row in zip(previous, current):
        for old, new in zip(old_row, new_row):
            if abs(new) <= 1e-12 or abs(new - old) / abs(new) >= QMESH_RELATIVE_TOLERANCE:
                return False
    return True


def select_converged_qmesh(
    observations: object,
) -> tuple[int, int, int] | None:
    """Select only after two consecutive full-tensor refinement steps pass.

    Each observation is ``(mesh, temperatures, kappa)``.  Returning ``None``
    is intentional: callers must fail closed rather than choose the largest
    mesh after an unproven ladder.
    """
    previous = None
    trailing_passes = 0
    selected = None
    for item in observations:
        try:
            mesh, temperatures, kappa = item
            mesh = tuple(int(value) for value in mesh)
        except (TypeError, ValueError) as exc:
            raise LegacyGateError(f"invalid q-mesh observation entry: {exc}") from exc
        if len(mesh) != 3 or any(value <= 0 for value in mesh):
            raise LegacyGateError("q-mesh must be three positive integers")
        _validate_qmesh_observation(temperatures, kappa)
        current = (mesh, temperatures, kappa)
        if previous is not None:
            if qmesh_step_passes(previous[1], previous[2], temperatures, kappa):
                trailing_passes += 1
                if trailing_passes >= 2:
                    selected = mesh
            else:
                trailing_passes = 0
                selected = None
        previous = current
    return selected


def main():
    try:
        audit_legacy_evidence(ROOT)
    except LegacyGateError as exc:
        sys.exit(f"[postprocess] strict evidence gate failed: {exc}")
    sys.exit(
        "[postprocess] legacy FC/kappa execution is retired: use the v2 "
        "postprocessor with a new empty output directory, a run-bound "
        "fingerprint, and the full 300--900 K xx/yy/zz q-mesh policy."
    )


if __name__ == "__main__":
    main()

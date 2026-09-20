#!/usr/bin/env python3
"""Build SrZrS3 FC2/FC3 and run the declared first-pass RTA q-mesh ladder."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import h5py
import numpy as np
import yaml

from audit_firstpass_forces import (
    dataset_ids,
    expected_fc_dataset_name,
    last_force_block,
    phono3py_drift_subtracted_quantized,
    sha256,
    structure_fingerprint,
)


MESHES = [(12, 5, 3), (16, 7, 4), (20, 9, 5), (23, 10, 6), (27, 12, 8)]
TEMPERATURES = [300.0, 600.0, 900.0]
TRACE_TOL = 0.03
DIAGONAL_TOL = 0.05
IMAGINARY_TOL_THZ = -0.1


class PostprocessError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PostprocessError(message)


def run_command(argv: list[str], cwd: Path, log: Path, records: Path) -> None:
    record = {"argv": argv, "cwd": str(cwd), "started_utc": subprocess.check_output(
        ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()}
    with log.open("w") as handle:
        process = subprocess.run(argv, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    record["returncode"] = process.returncode
    record["finished_utc"] = subprocess.check_output(
        ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], text=True).strip()
    record["log"] = str(log)
    record["log_sha256"] = sha256(log)
    with records.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    require(process.returncode == 0, f"command failed; see {log}")


def force_product_audit(product: Path, all_ids: list[int], included_ids: list[int],
                        run_dir: Path) -> dict[str, object]:
    residual = last_force_block(run_dir / "tasks/task-0000/scf.out", [1] * 8 + [2] * 8 + [3] * 24)["forces"]
    by_id = {}
    with (run_dir / "task_map.tsv").open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            by_id[int(row["displacement_id"])] = int(row["task_id"])
    require(set(by_id) == {0, *included_ids}, "task map changed after force audit")
    expected = []
    for identifier in all_ids:
        if identifier in by_id:
            task = by_id[identifier]
            observed = last_force_block(run_dir / f"tasks/task-{task:04d}/scf.out",
                                        [1] * 8 + [2] * 8 + [3] * 24)["forces"]
            expected.extend(phono3py_drift_subtracted_quantized(observed, residual))
        else:
            expected.extend([[0.0, 0.0, 0.0] for _ in residual])
    actual = []
    for line in product.read_text().splitlines():
        body = line.split("#", 1)[0].strip()
        if body:
            fields = body.replace("D", "E").replace("d", "e").split()
            require(len(fields) == 3, "FORCES_FC3 is not three-column type-I data")
            actual.append([float(x) for x in fields])
    require(len(actual) == len(expected), "FORCES_FC3 block/atom count mismatch")
    maximum = max(abs(x - y) for row, ref in zip(actual, expected) for x, y in zip(row, ref))
    require(maximum <= 2e-10,
            "FORCES_FC3 differs from drift-corrected, pristine-subtracted, quantized forces")
    return {"sha256": sha256(product), "rows": len(actual), "atom_blocks": len(all_ids),
            "included_blocks": len(included_ids), "excluded_zero_blocks": len(all_ids) - len(included_ids),
            "maximum_difference_Ry_per_bohr": maximum,
            "absolute_tolerance_Ry_per_bohr": 2e-10,
            "tolerance_basis": "two 10-decimal force-write quantizations plus floating-point roundoff; tighter than 1e-9 Ry/bohr",
            "per_file_translational_drift_removal_reproduced": True,
            "output_quantization_decimal_places": 10,
            "pristine_subtraction": True, "pristine_task_id": 0}


def fc_summary(path: Path, order: int) -> dict[str, object]:
    with h5py.File(path) as handle:
        array = np.asarray(handle[expected_fc_dataset_name(order, handle.keys())])
    expected = (40, 40, 3, 3) if order == 2 else (40, 40, 40, 3, 3, 3)
    require(array.shape == expected, f"fc{order} is not full 40-atom shape: {array.shape}")
    require(np.isfinite(array).all(), f"fc{order} contains non-finite values")
    if order == 2:
        asr = float(np.max(np.abs(np.sum(array, axis=1))))
        permutation = float(np.max(np.abs(array - array.transpose(1, 0, 3, 2))))
        units = "eV angstrom^-2"
    else:
        asr = float(max(np.max(np.abs(np.sum(array, axis=axis))) for axis in (0, 1, 2)))
        p12 = array.transpose(1, 0, 2, 4, 3, 5)
        p13 = array.transpose(2, 1, 0, 5, 4, 3)
        permutation = float(max(np.max(np.abs(array - p12)), np.max(np.abs(array - p13))))
        units = "eV angstrom^-3"
    return {"sha256": sha256(path), "shape": list(array.shape), "all_finite": True,
            "units": units, "acoustic_sum_rule_max_abs": asr,
            "permutation_max_abs": permutation,
            "note": "Residuals are measured integrity diagnostics, not convergence gates; no arbitrary tolerance was invented."}


def kappa_summary(path: Path, mesh: tuple[int, int, int], index: int) -> dict[str, object]:
    with h5py.File(path) as handle:
        keys = sorted(handle.keys())
        temperatures = np.asarray(handle["temperature"], dtype=float)
        kappa = np.asarray(handle["kappa"], dtype=float)
        frequency = np.asarray(handle["frequency"], dtype=float)
        weights = np.asarray(handle["weight"], dtype=float)
        qpoints = np.asarray(handle["qpoint"], dtype=float)
        stored_mesh = np.asarray(handle["mesh"], dtype=int).tolist() if "mesh" in handle else list(mesh)
    require(temperatures.tolist() == TEMPERATURES, f"temperature grid mismatch for {mesh}")
    require(kappa.shape == (3, 6) and np.isfinite(kappa).all(), f"bad kappa array for {mesh}")
    require(frequency.ndim == 2 and frequency.shape[1] == 60 and np.isfinite(frequency).all(),
            f"bad frequency array for {mesh}")
    require(weights.ndim == 1 and len(weights) == len(frequency) == len(qpoints),
            f"qpoint/weight/frequency mismatch for {mesh}")
    require(qpoints.shape[1:] == (3,), f"bad qpoint shape for {mesh}")
    require(np.all(weights > 0) and np.all(weights == np.rint(weights)), f"bad weights for {mesh}")
    require(int(np.sum(weights)) == math.prod(mesh), f"weights do not cover full mesh {mesh}")
    require(stored_mesh == list(mesh), f"stored mesh mismatch for {mesh}: {stored_mesh}")
    canonical = {tuple(np.round(np.mod(row, 1.0), 9)) for row in qpoints}
    require(len(canonical) == len(qpoints), f"duplicate irreducible q points for {mesh}")
    require(np.all(kappa[:, :3] > 0), f"nonpositive kappa diagonal for {mesh}")
    tensors = []
    positive_semidefinite = True
    for row in kappa:
        xx, yy, zz, yz, xz, xy = map(float, row)
        tensor = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
        positive_semidefinite &= bool(np.min(np.linalg.eigvalsh(tensor)) >= -1e-10 * np.max(np.abs(tensor)))
        tensors.append(tensor.tolist())
    require(positive_semidefinite, f"kappa tensor is not positive semidefinite for {mesh}")
    minimum = float(np.min(frequency))
    require(minimum >= IMAGINARY_TOL_THZ,
            f"frequency integrity gate failed for {mesh}: minimum {minimum} THz")
    return {"ladder_index": index, "mesh": list(mesh), "grid_points": math.prod(mesh),
            "hdf5_path": str(path), "hdf5_sha256": sha256(path), "hdf5_keys": keys,
            "temperatures_K": temperatures.tolist(), "kappa_six_W_mK": kappa.tolist(),
            "tensors_W_mK": tensors, "minimum_frequency_THz": minimum,
            "harmonic_stability_passed": minimum >= IMAGINARY_TOL_THZ,
            "imaginary_frequency_tolerance_THz": IMAGINARY_TOL_THZ,
            "irreducible_qpoints": len(qpoints), "weight_sum": int(np.sum(weights)),
            "positive_semidefinite": True,
            "units": {"temperature": "K", "kappa": "W m^-1 K^-1", "frequency": "THz"}}


def convergence(reports: list[dict[str, object]]) -> dict[str, object]:
    steps = []
    trailing = 0
    for previous, current in zip(reports, reports[1:]):
        temperature_changes = []
        passed = bool(previous["harmonic_stability_passed"] and current["harmonic_stability_passed"])
        for left, right in zip(previous["kappa_six_W_mK"], current["kappa_six_W_mK"]):
            diag_left = np.asarray(left[:3], dtype=float)
            diag_right = np.asarray(right[:3], dtype=float)
            diag_change = np.abs(diag_right - diag_left) / diag_right
            trace_change = abs(float(np.sum(diag_right - diag_left) / np.sum(diag_right)))
            temperature_changes.append({"trace_over_3_relative_change": trace_change,
                                        "diagonal_relative_changes": diag_change.tolist()})
            passed &= trace_change < TRACE_TOL and bool(np.max(diag_change) < DIAGONAL_TOL)
        trailing = trailing + 1 if passed else 0
        steps.append({"from_mesh": previous["mesh"], "to_mesh": current["mesh"],
                      "passed": bool(passed), "temperature_changes": temperature_changes})
    converged = trailing >= 2
    return {"qmesh_converged": converged, "trailing_passing_steps": trailing,
            "required_trailing_passing_steps": 2, "steps": steps,
            "label": "qmesh_converged_first_pass" if converged else "first_pass_unconverged",
            "scope": "q-mesh convergence only; cutoff, supercell, force setting, SOC and NAC convergence remain unestablished"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--phono3py", type=Path, required=True)
    parser.add_argument("--phono3py-init", type=Path, required=True)
    parser.add_argument("--force-audit", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    work_dir = args.work_dir
    require(run_dir.is_dir() and not run_dir.is_symlink(), "invalid run directory")
    require(not work_dir.exists(), "postprocess attempt directory already exists")
    audit = json.loads(args.force_audit.read_text())
    require(audit["status"] == "accepted_for_first_pass_postprocessing", "force audit did not pass")
    require(audit["run_dir"] == str(run_dir), "force audit is for another run directory")
    require(sha256(run_dir / "task_map.tsv") == audit["mapping"]["task_map_sha256"],
            "task map changed after audit")
    require(sha256(run_dir / "generation/phono3py_disp.yaml") ==
            audit["dataset"]["phono3py_disp_yaml_sha256"], "dataset changed after audit")
    work_dir.mkdir(parents=True)
    command_records = work_dir / "commands.jsonl"
    dataset_path = run_dir / "generation/phono3py_disp.yaml"
    dataset = yaml.safe_load(dataset_path.read_text())
    require("nac_params" not in dataset, "YAML contains nac_params in explicit no-NAC branch")
    require(not (run_dir / "generation/BORN").exists() and not (work_dir / "BORN").exists(),
            "BORN file present in explicit no-NAC branch")
    shutil.copy2(dataset_path, work_dir / "phono3py_disp.yaml")

    all_ids, included_ids = dataset_ids(dataset)
    by_displacement = {}
    with (run_dir / "task_map.tsv").open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            by_displacement[int(row["displacement_id"])] = int(row["task_id"])
    outputs = [str(run_dir / f"tasks/task-{by_displacement[i]:04d}/scf.out") for i in included_ids]
    collect_argv = [str(args.phono3py_init), "--qe", "--cf3", *outputs,
                    "--cfz", str(run_dir / "tasks/task-0000/scf.out")]
    run_command(collect_argv, work_dir, work_dir / "collect_forces.log", command_records)
    force_product = force_product_audit(work_dir / "FORCES_FC3", all_ids, included_ids, run_dir)

    reports = []
    fc2 = work_dir / "fc2.hdf5"
    fc3 = work_dir / "fc3.hdf5"
    fc2_report = None
    fc3_report = None
    for index, mesh in enumerate(MESHES):
        argv = [str(args.phono3py), "--mesh", *map(str, mesh), "--br", "--ts",
                *[str(int(t)) for t in TEMPERATURES], "--nonac", "--full-fc"]
        if index == 0:
            argv += ["--fc-calc", "symfc"]
        argv += ["phono3py_disp.yaml"]
        run_command(argv, work_dir, work_dir / f"kappa-m{''.join(map(str, mesh))}.log", command_records)
        require(fc2.is_file() and fc3.is_file(), "phono3py did not create explicit FC2/FC3 HDF5")
        if index == 0:
            # Stop before extending the ladder if the newly built FC arrays do
            # not pass shape/finiteness integrity checks.
            fc2_report = fc_summary(fc2, 2)
            fc3_report = fc_summary(fc3, 3)
        kappa_path = work_dir / f"kappa-m{''.join(map(str, mesh))}.hdf5"
        require(kappa_path.is_file(), f"missing kappa HDF5 for {mesh}")
        reports.append(kappa_summary(kappa_path, mesh, index))
        if len(reports) >= 3 and convergence(reports)["qmesh_converged"]:
            break

    require(fc2_report is not None and fc3_report is not None, "force-constant audit did not run")
    qmesh = convergence(reports)
    selected = reports[-1]
    qmesh["criterion_label_before_pristine_exception"] = qmesh["label"]
    qmesh["label"] = "first_pass_unconverged"
    qmesh["forced_by_pristine_exception"] = True
    status = "first_pass_unconverged"
    result = {
        "schema_version": 1, "material": "SrZrS3", "status": status,
        "calculation": {"exchange_correlation": "PBE", "solver": "phono3py BTE-RTA",
                        "explicit_SOC": False, "NAC": False, "isotope_scattering": False,
                        "boundary_scattering": False, "supercell_matrix": [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "pair_cutoff_angstrom": 3.5541348625,
                        "pair_cutoff_cli_bohr": 6.71634150010947,
                        "force_settings": audit["qe"]["settings"], "temperatures_K": TEMPERATURES},
        "software": {"phono3py": subprocess.check_output(
                         [str(args.phono3py.parent / "python"), "-c",
                          "import phono3py; print(phono3py.__version__)"], text=True).strip(),
                     "python": subprocess.check_output([str(args.phono3py.parent / "python"), "--version"],
                                                       text=True, stderr=subprocess.STDOUT).strip()},
        "provenance": {"run_dir": str(run_dir), "force_audit_path": str(args.force_audit),
                       "force_audit_sha256": sha256(args.force_audit),
                       "dataset_sha256": sha256(work_dir / "phono3py_disp.yaml"),
                       "commands_jsonl": str(command_records)},
        "FORCES_FC3": force_product, "fc2": fc2_report, "fc3": fc3_report,
        "qmesh": qmesh, "mesh_reports": reports, "selected_mesh": selected["mesh"],
        "selected_hdf5_sha256": selected["hdf5_sha256"],
        "limitations": ["time-bounded first pass", "2x1x1 supercell convergence not established",
                        "3.5541348625-A pair-cutoff convergence not established",
                        "force-basis and force-k-mesh convergence not established",
                        "RTA", "PBE", "no explicit SOC", "no NAC",
                        "no isotope or boundary scattering", "finite sampled q meshes",
                        "does not make electronic-only zT_e a final thermoelectric zT"],
    }
    (work_dir / "postprocess_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    with (work_dir / "kappa_mesh_summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["mesh", "T_K", "kappa_xx_W_mK", "kappa_yy_W_mK", "kappa_zz_W_mK",
                         "kappa_yz_W_mK", "kappa_xz_W_mK", "kappa_xy_W_mK", "kappa_trace_over_3_W_mK"])
        for report in reports:
            tag = "x".join(map(str, report["mesh"]))
            for temperature, row in zip(TEMPERATURES, report["kappa_six_W_mK"]):
                writer.writerow([tag, int(temperature), *[f"{x:.10g}" for x in row],
                                 f"{sum(row[:3]) / 3:.10g}"])
    print(json.dumps({"status": status, "selected_mesh": selected["mesh"],
                      "postprocess_result_sha256": sha256(work_dir / "postprocess_result.json")}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PostprocessError, KeyError, OSError, ValueError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        raise SystemExit(2)

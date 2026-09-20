#!/usr/bin/env python3
"""Build Rb FC2/FC3 and run an explicit no-NAC RTA q-mesh ladder."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import h5py
import numpy as np
import phono3py
from phonopy.phonon.grid import BZGrid


LENGTH_LADDER_ANGSTROM = (45.0, 60.0, 75.0, 90.0, 105.0)
TEMPERATURES_K = (300.0, 600.0, 900.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], cwd: Path, name: str) -> None:
    (cwd / f"{name}.command.json").write_text(json.dumps(command, indent=2) + "\n")
    with (cwd / f"{name}.stdout").open("w") as stdout, (cwd / f"{name}.stderr").open("w") as stderr:
        completed = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr, check=False)
    (cwd / f"{name}.exit_code.txt").write_text(f"{completed.returncode}\n")
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with exit {completed.returncode}")


def tensor_from_six(values: np.ndarray) -> np.ndarray:
    xx, yy, zz, yz, xz, xy = [float(value) for value in values]
    return np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]], dtype=float)


def tensor_six(tensor: np.ndarray) -> list[float]:
    return [
        float(tensor[0, 0]), float(tensor[1, 1]), float(tensor[2, 2]),
        float(tensor[1, 2]), float(tensor[0, 2]), float(tensor[0, 1]),
    ]


def hdf_report(path: Path, length_angstrom: float, p3) -> dict[str, object]:
    grid = BZGrid(
        length_angstrom,
        lattice=p3.primitive.cell,
        symmetry_dataset=p3.primitive_symmetry.dataset,
        use_grg=True,
    )
    with h5py.File(path) as handle:
        required = ("temperature", "kappa", "mesh", "frequency", "weight", "qpoint")
        missing = [key for key in required if key not in handle]
        if missing:
            raise ValueError(f"{path.name} lacks HDF5 keys: {missing}")
        temperature = np.asarray(handle["temperature"], dtype=float)
        kappa = np.asarray(handle["kappa"], dtype=float)
        mesh = np.asarray(handle["mesh"], dtype=int)
        frequency = np.asarray(handle["frequency"], dtype=float)
        weight = np.asarray(handle["weight"], dtype=int)
        qpoint = np.asarray(handle["qpoint"], dtype=float)
    if list(temperature) != list(TEMPERATURES_K):
        raise ValueError(f"unexpected temperature grid in {path.name}: {temperature}")
    if kappa.shape != (len(TEMPERATURES_K), 6) or not np.isfinite(kappa).all():
        raise ValueError(f"invalid kappa shape or non-finite values in {path.name}")
    if not np.isfinite(frequency).all() or qpoint.shape[0] != frequency.shape[0]:
        raise ValueError(f"invalid frequency/q-point arrays in {path.name}")
    if weight.shape[0] != frequency.shape[0] or int(weight.sum()) != int(np.prod(mesh)):
        raise ValueError(f"mesh weights do not cover the full grid in {path.name}")
    if not np.array_equal(mesh, grid.D_diag):
        raise ValueError(f"HDF5 mesh {mesh} differs from reconstructed GRG {grid.D_diag}")

    transform = np.array([[0, 1, 1], [1, 0, 1], [1, 1, 0]], dtype=float)
    conventional = transform @ np.asarray(p3.primitive.cell, dtype=float)
    left, _, right = np.linalg.svd(conventional)
    rotation = left @ right
    if np.linalg.det(rotation) < 0:
        raise ValueError("conventional tensor rotation is not right handed")
    raw = [tensor_from_six(row) for row in kappa]
    rotated = [rotation @ tensor @ rotation.T for tensor in raw]
    if any(np.min(np.linalg.eigvalsh(tensor)) < -1e-10 for tensor in rotated):
        raise ValueError(f"conductivity tensor is not positive semidefinite in {path.name}")
    offdiag_fraction = [
        max(abs(tensor[i, j]) for i in range(3) for j in range(i))
        / (float(np.trace(tensor)) / 3.0)
        for tensor in rotated
    ]
    return {
        "mesh_length_angstrom": length_angstrom,
        "mesh_length_cli_angstrom": length_angstrom,
        "hdf5": str(path.resolve()),
        "hdf5_sha256": sha256(path),
        "mesh_D_diag": mesh.tolist(),
        "grid_matrix": np.asarray(grid.grid_matrix, dtype=int).tolist(),
        "grid_count": int(np.prod(mesh)),
        "irreducible_qpoint_count": int(len(weight)),
        "weight_sum": int(weight.sum()),
        "minimum_frequency_THz": float(np.min(frequency)),
        "raw_kappa_W_mK": [tensor_six(tensor) for tensor in raw],
        "conventional_kappa_W_mK": [tensor_six(tensor) for tensor in rotated],
        "maximum_offdiagonal_fraction_of_trace_over_3": max(offdiag_fraction),
        "conventional_cell_angstrom": conventional.tolist(),
        "rotation_rows": rotation.tolist(),
    }


def convergence(previous: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    rows = []
    for temperature, old, new in zip(
        TEMPERATURES_K,
        previous["conventional_kappa_W_mK"],
        current["conventional_kappa_W_mK"],
    ):
        old_diag = np.array(old[:3], dtype=float)
        new_diag = np.array(new[:3], dtype=float)
        if np.any(new_diag <= 0):
            raise ValueError("non-positive q-mesh convergence denominator")
        diagonal = np.abs(new_diag - old_diag) / new_diag
        average = abs(float(np.sum(new_diag - old_diag))) / float(np.sum(new_diag))
        rows.append({
            "temperature_K": temperature,
            "trace_over_3_relative_change": average,
            "diagonal_relative_changes": diagonal.tolist(),
        })
    passed = all(
        row["trace_over_3_relative_change"] < 0.03
        and max(row["diagonal_relative_changes"]) < 0.05
        for row in rows
    )
    return {"passed": passed, "temperature_changes": rows}


def scan_force_constants(path: Path) -> dict[str, object]:
    with h5py.File(path) as handle:
        if "force_constants" not in handle:
            raise ValueError(f"{path.name} lacks force_constants")
        values = handle["force_constants"]
        all_finite = all(np.isfinite(values[index]).all() for index in range(values.shape[0]))
        mapping = np.asarray(handle["p2s_map"], dtype=int).tolist() if "p2s_map" in handle else None
        shape = list(values.shape)
    if not all_finite:
        raise ValueError(f"{path.name} contains non-finite force constants")
    return {"path": str(path.resolve()), "sha256": sha256(path), "shape": shape,
            "all_finite": all_finite, "p2s_map": mapping}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-dir", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to reuse {args.output_dir}")
    audit = json.loads((args.production_dir / "production_audit.json").read_text())
    if audit.get("pass") is not True:
        raise ValueError("production force audit did not pass")
    args.output_dir.mkdir(parents=True)
    dataset = args.dataset_dir / "phono3py_disp.yaml"
    shutil.copyfile(dataset, args.output_dir / "phono3py_disp.yaml")
    if (args.dataset_dir / "BORN").exists() or (args.output_dir / "BORN").exists():
        raise ValueError("BORN is forbidden in the explicit no-NAC first pass")

    manifest = json.loads((args.production_dir / "force_manifest.json").read_text())
    pristine = Path(manifest["tasks"][0]["input"]).parent / "scf.out"
    displaced = [Path(task["input"]).parent / "scf.out" for task in manifest["tasks"][1:]]
    cf_command = ["phono3py-init", "--qe", "--cf3", *[str(path.resolve()) for path in displaced], "--cfz", str(pristine.resolve())]
    run(cf_command, args.output_dir, "collect_forces_fc3")
    forces = args.output_dir / "FORCES_FC3"
    if not forces.is_file():
        raise FileNotFoundError("phono3py-init did not create FORCES_FC3")

    p3 = phono3py.load(
        args.output_dir / "phono3py_disp.yaml",
        produce_fc=False,
        is_nac=False,
        use_grg=True,
    )
    reports: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    trailing = 0
    for ladder_index, length_angstrom in enumerate(LENGTH_LADDER_ANGSTROM):
        before = set(args.output_dir.glob("kappa-*.hdf5"))
        command = [
            "phono3py", "--mesh", f"{length_angstrom:.15g}", "--grg", "--br",
            "--ts", *[f"{temperature:g}" for temperature in TEMPERATURES_K],
            "--nonac", "--full-fc",
        ]
        if ladder_index == 0:
            command.extend(["--fc-calc", "symfc"])
        command.append("phono3py_disp.yaml")
        run(command, args.output_dir, f"qmesh_{ladder_index:02d}_{length_angstrom:g}A")
        after = set(args.output_dir.glob("kappa-*.hdf5"))
        new_files = sorted(after - before)
        if len(new_files) != 1:
            raise ValueError(f"expected one new kappa HDF5, got {[p.name for p in new_files]}")
        report = hdf_report(new_files[0], length_angstrom, p3)
        report["ladder_index"] = ladder_index
        report["harmonic_stability_pass"] = report["minimum_frequency_THz"] >= -0.1
        report["offdiagonal_check_pass"] = report[
            "maximum_offdiagonal_fraction_of_trace_over_3"
        ] <= 0.05
        reports.append(report)
        if len(reports) > 1:
            step = convergence(reports[-2], reports[-1])
            step["from_ladder_index"] = ladder_index - 1
            step["to_ladder_index"] = ladder_index
            steps.append(step)
            trailing = trailing + 1 if step["passed"] else 0
        if trailing >= 2:
            break

    qmesh_converged = trailing >= 2
    chosen = reports[-1]
    stability_pass = all(report["harmonic_stability_pass"] for report in reports)
    offdiagonal_pass = all(report["offdiagonal_check_pass"] for report in reports)
    # The q mesh may converge, but amplitude, pair-cutoff and supercell
    # convergence are intentionally outside this time-bounded first pass.
    label = "first_pass_unconverged"
    if not stability_pass:
        label = "workflow_only_harmonic_instability_gate_failed"
    fc2 = args.output_dir / "fc2.hdf5"
    fc3 = args.output_dir / "fc3.hdf5"
    if not fc2.is_file() or not fc3.is_file():
        raise FileNotFoundError("RTA construction did not produce both fc2.hdf5 and fc3.hdf5")

    summary = {
        "document_type": "rb_kappa_L_firstpass_summary",
        "label": label,
        "software": {
            "phono3py": phono3py.__version__,
        },
        "provenance_sha256": {
            "postprocess_script": sha256(Path(__file__).resolve(strict=True)),
            "production_audit": sha256(args.production_dir / "production_audit.json"),
            "production_manifest": sha256(args.production_dir / "force_manifest.json"),
            "production_task_map": sha256(args.production_dir / "task_map.tsv"),
            "copied_dataset": sha256(args.output_dir / "phono3py_disp.yaml"),
        },
        "model": {
            "exchange_correlation": "PBE",
            "solver": "phono3py BTE-RTA (--br)",
            "explicit_SOC": False,
            "NAC": False,
            "NAC_cli_flag": "--nonac",
            "isotope_scattering": False,
            "boundary_scattering": False,
            "temperature_K": list(TEMPERATURES_K),
        },
        "force_dataset": {
            "supercell_matrix": [[0, 1, 1], [2, 0, 1], [2, 1, 0]],
            "supercell_atoms": manifest["tasks"][0]["expected_atoms"],
            "cutoff_pair_distance_angstrom": 3.70,
            "cutoff_pair_distance_cli_bohr": 6.991986661115,
            "displacement_distance_angstrom": 0.03,
            "displacement_distance_cli_bohr": 0.0566917837388,
            "force_kmesh": manifest["tasks"][0]["kmesh"],
            "ecutwfc_Ry": 100,
            "ecutrho_Ry": 800,
            "conv_thr_Ry": 1e-10,
            "nosym": True,
            "noinv": True,
            "pristine_subtraction": "--cfz",
            "dataset_sha256": sha256(dataset),
            "FORCES_FC3_sha256": sha256(forces),
            "fc2": scan_force_constants(fc2),
            "fc3": scan_force_constants(fc3),
        },
        "qmesh_ladder": reports,
        "qmesh_steps": steps,
        "qmesh_converged": qmesh_converged,
        "required_consecutive_passing_steps": 2,
        "trace_over_3_relative_gate": 0.03,
        "each_diagonal_relative_gate": 0.05,
        "harmonic_stability_pass": stability_pass,
        "minimum_frequency_gate_THz": -0.1,
        "offdiagonal_check_pass": offdiagonal_pass,
        "selected_ladder_index": chosen["ladder_index"],
        "selected_hdf5": chosen["hdf5"],
        "limitations": [
            "first-pass finite-displacement result; not a final physical uncertainty bound",
            "pair-cutoff, supercell, and displacement-amplitude convergence are not established",
            "force-constant acoustic-sum-rule and permutation residual thresholds are not established",
            "no NAC, explicit SOC, isotope scattering, or boundary scattering",
            "RTA rather than iterative LBTE",
            "sampled-mesh stability is not proof of stability everywhere",
        ],
    }
    (args.output_dir / "kappa_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    with (args.output_dir / "kappa_L_first_pass.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "T_K", "kappa_xx_W_mK", "kappa_yy_W_mK", "kappa_zz_W_mK",
            "kappa_yz_W_mK", "kappa_xz_W_mK", "kappa_xy_W_mK",
            "kappa_trace_over_3_W_mK",
        ])
        for temperature, tensor in zip(TEMPERATURES_K, chosen["conventional_kappa_W_mK"]):
            writer.writerow([
                f"{temperature:.0f}", *[f"{value:.10g}" for value in tensor],
                f"{sum(tensor[:3]) / 3:.10g}",
            ])
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if stability_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())

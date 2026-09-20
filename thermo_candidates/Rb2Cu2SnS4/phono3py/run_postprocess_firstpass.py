#!/usr/bin/env python3
"""Run Rb FC2/FC3/q-mesh work or validate and finalize its existing artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import phono3py
from phonopy.phonon.grid import BZGrid


LENGTH_LADDER_ANGSTROM = (45.0, 60.0, 75.0, 90.0, 105.0)
TEMPERATURES_K = (300.0, 600.0, 900.0)
FC_DATASET_BY_ORDER = {2: "force_constants", 3: "fc3"}
WORKFLOW_GATE_EXIT_BITS = {
    "qmesh_converged": 1,
    "harmonic_stability_pass": 2,
    "offdiagonal_check_pass": 4,
}


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


def require_regular_file(path: Path, label: str, *, nonempty: bool = True) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is missing, not a regular file, or is a symlink: {path}")
    if nonempty and path.stat().st_size == 0:
        raise ValueError(f"{label} is empty: {path}")


def read_json(path: Path, label: str) -> Any:
    require_regular_file(path, label)
    try:
        return json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {path}") from exc


def expected_qmesh_command(ladder_index: int, length_angstrom: float) -> list[str]:
    command = [
        "phono3py", "--mesh", f"{length_angstrom:.15g}", "--grg", "--br",
        "--ts", *[f"{temperature:g}" for temperature in TEMPERATURES_K],
        "--nonac", "--full-fc",
    ]
    if ladder_index == 0:
        command.extend(["--fc-calc", "symfc"])
    command.append("phono3py_disp.yaml")
    return command


def validate_command_evidence(
    output_dir: Path,
    name: str,
    expected_command: list[str],
) -> dict[str, object]:
    paths = {
        "command": output_dir / f"{name}.command.json",
        "exit_code": output_dir / f"{name}.exit_code.txt",
        "stdout": output_dir / f"{name}.stdout",
        "stderr": output_dir / f"{name}.stderr",
    }
    for kind, path in paths.items():
        require_regular_file(path, f"{name} {kind}", nonempty=kind != "stderr")
    command = read_json(paths["command"], f"{name} command")
    if command != expected_command:
        raise ValueError(
            f"{name} command mismatch: expected {expected_command!r}, found {command!r}"
        )
    if paths["exit_code"].read_text() != "0\n":
        raise ValueError(f"{name} does not have the exact successful exit record")
    if paths["stderr"].stat().st_size != 0:
        raise ValueError(f"{name} stderr is not empty")
    return {
        "command": command,
        "artifacts": {
            kind: {
                "path": str(path.resolve()),
                "sha256": sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for kind, path in paths.items()
        },
    }


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


def evaluate_workflow_gate(
    *,
    qmesh_converged: bool,
    harmonic_stability_pass: bool,
    offdiagonal_check_pass: bool,
) -> dict[str, object]:
    """Keep the numerical, stability, and tensor-review gates independent."""
    gates = {
        "qmesh_converged": qmesh_converged,
        "harmonic_stability_pass": harmonic_stability_pass,
        "offdiagonal_check_pass": offdiagonal_check_pass,
    }
    failed = [name for name, passed in gates.items() if not passed]
    exit_code = sum(WORKFLOW_GATE_EXIT_BITS[name] for name in failed)
    return {
        "pass": not failed,
        "gates": gates,
        "failed_gates": failed,
        "exit_code": exit_code,
        "exit_code_bit_values": dict(WORKFLOW_GATE_EXIT_BITS),
        "exit_code_semantics": "bitwise OR of the listed failed-gate values; zero means all gates passed",
    }


def validate_supercell_atom_count(p3, expected_atoms: int) -> int:
    """Bind the manifest atom count to phono3py's loaded displacement supercell."""
    supercell = getattr(p3, "supercell", None)
    if supercell is None:
        raise ValueError("loaded phono3py dataset does not expose a supercell")
    try:
        loaded_atoms = len(supercell)
    except TypeError:
        positions = getattr(supercell, "scaled_positions", None)
        if positions is None:
            raise ValueError("loaded phono3py supercell does not expose its atom count")
        loaded_atoms = len(positions)
    if not isinstance(loaded_atoms, int) or loaded_atoms <= 0:
        raise ValueError("loaded phono3py supercell has an invalid atom count")
    if loaded_atoms != expected_atoms:
        raise ValueError(
            f"loaded phono3py supercell has {loaded_atoms} atoms; "
            f"force manifest expects {expected_atoms}"
        )
    return loaded_atoms


def embedded_hdf5_version(handle: h5py.File) -> str | None:
    """Return a scalar embedded version as text when the file provides one."""
    if "version" not in handle or not isinstance(handle["version"], h5py.Dataset):
        return None
    raw = handle["version"][()]
    if isinstance(raw, np.ndarray):
        if raw.size != 1:
            return None
        raw = raw.reshape(()).item()
    elif isinstance(raw, np.generic):
        raw = raw.item()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return raw
    return None


def scan_force_constants(path: Path, *, order: int, expected_atoms: int) -> dict[str, object]:
    if order not in FC_DATASET_BY_ORDER:
        raise ValueError("force-constant order must be 2 or 3")
    require_regular_file(path, f"FC{order} HDF5")
    dataset_name = FC_DATASET_BY_ORDER[order]
    with h5py.File(path) as handle:
        keys = sorted(handle.keys())
        if dataset_name not in handle:
            raise ValueError(f"{path.name} lacks documented FC{order} dataset {dataset_name!r}")
        other_force_dataset = FC_DATASET_BY_ORDER[3 if order == 2 else 2]
        if other_force_dataset in handle:
            raise ValueError(
                f"{path.name} is ambiguous: contains both {dataset_name!r} and "
                f"{other_force_dataset!r}"
            )
        values = handle[dataset_name]
        if not isinstance(values, h5py.Dataset) or not np.issubdtype(values.dtype, np.number):
            raise ValueError(f"{path.name}:{dataset_name} is not a numeric HDF5 dataset")
        expected_shape = (
            (expected_atoms, expected_atoms, 3, 3)
            if order == 2
            else (expected_atoms, expected_atoms, expected_atoms, 3, 3, 3)
        )
        if values.shape != expected_shape:
            raise ValueError(
                f"{path.name}:{dataset_name} shape {values.shape} differs from "
                f"expected full FC{order} shape {expected_shape}"
            )
        all_finite = all(np.isfinite(values[index]).all() for index in range(values.shape[0]))
        if "p2s_map" not in handle or not isinstance(handle["p2s_map"], h5py.Dataset):
            raise ValueError(f"{path.name} lacks required p2s_map dataset")
        raw_mapping = np.asarray(handle["p2s_map"])
        if (
            raw_mapping.ndim != 1
            or raw_mapping.size == 0
            or not np.issubdtype(raw_mapping.dtype, np.integer)
            or len(set(int(value) for value in raw_mapping)) != raw_mapping.size
            or np.any(raw_mapping < 0)
            or np.any(raw_mapping >= expected_atoms)
        ):
            raise ValueError(f"{path.name} has an invalid or empty p2s_map")
        mapping = raw_mapping.astype(int).tolist()
        embedded_version = embedded_hdf5_version(handle)
        shape = list(values.shape)
    if not all_finite:
        raise ValueError(f"{path.name} contains non-finite force constants")
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "order": order,
        "dataset": dataset_name,
        "hdf5_root_datasets": keys,
        "hdf5_embedded_version": embedded_version,
        "shape": shape,
        "all_finite": all_finite,
        "p2s_map": mapping,
    }


def scan_force_constant_pair(fc2: Path, fc3: Path, expected_atoms: int) -> dict[str, object]:
    reports = {
        "fc2": scan_force_constants(fc2, order=2, expected_atoms=expected_atoms),
        "fc3": scan_force_constants(fc3, order=3, expected_atoms=expected_atoms),
    }
    if reports["fc2"]["p2s_map"] != reports["fc3"]["p2s_map"]:
        raise ValueError("fc2.hdf5 and fc3.hdf5 p2s_map datasets differ")
    return reports


def expected_collect_command(manifest: dict[str, object]) -> list[str]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) < 2:
        raise ValueError("force manifest has no pristine-plus-displacement task list")
    inputs = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict) or not isinstance(task.get("input"), str):
            raise ValueError(f"force manifest task {index} lacks an input path")
        inputs.append(Path(task["input"]).parent / "scf.out")
    pristine, *displaced = inputs
    return [
        "phono3py-init", "--qe", "--cf3",
        *[str(path.resolve()) for path in displaced],
        "--cfz", str(pristine.resolve()),
    ]


def discover_qmesh_stage_count(output_dir: Path) -> int:
    present = {path.name for path in output_dir.glob("qmesh_*.command.json")}
    expected_names = [
        f"qmesh_{index:02d}_{length:g}A.command.json"
        for index, length in enumerate(LENGTH_LADDER_ANGSTROM)
    ]
    indices = [index for index, name in enumerate(expected_names) if name in present]
    if not indices:
        raise ValueError("existing postprocess directory has no q-mesh command evidence")
    if indices != list(range(indices[-1] + 1)):
        raise ValueError("q-mesh command evidence is not a contiguous ladder prefix")
    if present != set(expected_names[: indices[-1] + 1]):
        raise ValueError(f"unexpected or ambiguous q-mesh command evidence: {sorted(present)}")
    return indices[-1] + 1


def match_kappa_hdf5(
    output_dir: Path,
    lengths: tuple[float, ...],
    p3,
) -> list[Path]:
    paths = sorted(output_dir.glob("kappa-*.hdf5"))
    if len(paths) != len(lengths):
        raise ValueError(
            f"expected {len(lengths)} kappa HDF5 files, found {[path.name for path in paths]}"
        )
    by_mesh: dict[tuple[int, ...], Path] = {}
    for path in paths:
        require_regular_file(path, "kappa HDF5")
        with h5py.File(path) as handle:
            if "mesh" not in handle:
                raise ValueError(f"{path.name} lacks mesh")
            mesh = tuple(int(value) for value in np.asarray(handle["mesh"], dtype=int))
        if mesh in by_mesh:
            raise ValueError(
                f"ambiguous kappa HDF5 files for mesh {mesh}: "
                f"{by_mesh[mesh].name}, {path.name}"
            )
        by_mesh[mesh] = path

    matched = []
    expected_meshes = []
    for length_angstrom in lengths:
        grid = BZGrid(
            length_angstrom,
            lattice=p3.primitive.cell,
            symmetry_dataset=p3.primitive_symmetry.dataset,
            use_grg=True,
        )
        mesh = tuple(int(value) for value in grid.D_diag)
        if mesh in expected_meshes:
            raise ValueError(f"q-mesh ladder has duplicate reconstructed mesh {mesh}")
        expected_meshes.append(mesh)
        if mesh not in by_mesh:
            raise ValueError(f"no kappa HDF5 matches reconstructed mesh {mesh}")
        matched.append(by_mesh[mesh])
    if set(by_mesh) != set(expected_meshes):
        raise ValueError("one or more kappa HDF5 meshes do not belong to the executed ladder")
    return matched


def snapshot_output_artifacts(output_dir: Path) -> dict[str, str]:
    snapshot = {}
    for path in sorted(output_dir.iterdir()):
        if path.name in {
            "kappa_summary.json",
            "kappa_L_first_pass.csv",
            "kappa_L_first_pass_rejected_diagnostic.csv",
        }:
            continue
        require_regular_file(path, "postprocess artifact", nonempty=False)
        snapshot[path.name] = sha256(path)
    return snapshot


def write_missing_or_verify(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        require_regular_file(path, "existing summary", nonempty=False)
        if path.read_bytes() != content:
            raise ValueError(f"refusing to overwrite non-identical existing summary {path}")
        return
    with path.open("xb") as stream:
        stream.write(content)


def make_csv(chosen: dict[str, object], *, status: str) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([
        "status", "T_K", "kappa_xx_W_mK", "kappa_yy_W_mK", "kappa_zz_W_mK",
        "kappa_yz_W_mK", "kappa_xz_W_mK", "kappa_xy_W_mK",
        "kappa_trace_over_3_W_mK",
    ])
    for temperature, tensor in zip(TEMPERATURES_K, chosen["conventional_kappa_W_mK"]):
        writer.writerow([
            status, f"{temperature:.0f}", *[f"{value:.10g}" for value in tensor],
            f"{sum(tensor[:3]) / 3:.10g}",
        ])
    return stream.getvalue().encode()


def finalize_existing(
    production_dir: Path,
    dataset_dir: Path,
    output_dir: Path,
    audit: dict[str, object],
    manifest: dict[str, object],
) -> int:
    if audit.get("pass") is not True:
        raise ValueError("production force audit did not pass")
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError(f"invalid existing postprocess directory: {output_dir}")
    if (dataset_dir / "BORN").exists() or (output_dir / "BORN").exists():
        raise ValueError("BORN is forbidden in the explicit no-NAC first pass")
    dataset = dataset_dir / "phono3py_disp.yaml"
    copied_dataset = output_dir / "phono3py_disp.yaml"
    require_regular_file(dataset, "source displacement dataset")
    require_regular_file(copied_dataset, "copied displacement dataset")
    if sha256(dataset) != sha256(copied_dataset):
        raise ValueError("copied displacement dataset differs from the source dataset")

    initial_snapshot = snapshot_output_artifacts(output_dir)
    collection_evidence = validate_command_evidence(
        output_dir, "collect_forces_fc3", expected_collect_command(manifest)
    )
    forces = output_dir / "FORCES_FC3"
    require_regular_file(forces, "FORCES_FC3")
    require_regular_file(output_dir / "phono3py.yaml", "phono3py summary YAML")

    expected_atoms = manifest["tasks"][0]["expected_atoms"]
    if not isinstance(expected_atoms, int) or expected_atoms <= 0:
        raise ValueError("force manifest has invalid expected_atoms")
    p3 = phono3py.load(copied_dataset, produce_fc=False, is_nac=False, use_grg=True)
    loaded_supercell_atoms = validate_supercell_atom_count(p3, expected_atoms)
    stage_count = discover_qmesh_stage_count(output_dir)
    lengths = LENGTH_LADDER_ANGSTROM[:stage_count]
    kappa_paths = match_kappa_hdf5(output_dir, lengths, p3)
    reports: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    qmesh_evidence = []
    trailing = 0
    first_converged_stage = None
    expected_names = {
        "FORCES_FC3", "fc2.hdf5", "fc3.hdf5", "phono3py.yaml", "phono3py_disp.yaml",
        "collect_forces_fc3.command.json", "collect_forces_fc3.exit_code.txt",
        "collect_forces_fc3.stdout", "collect_forces_fc3.stderr",
        *[path.name for path in kappa_paths],
    }
    for ladder_index, (length_angstrom, kappa_path) in enumerate(zip(lengths, kappa_paths)):
        name = f"qmesh_{ladder_index:02d}_{length_angstrom:g}A"
        evidence = validate_command_evidence(
            output_dir, name, expected_qmesh_command(ladder_index, length_angstrom)
        )
        stdout_path = output_dir / f"{name}.stdout"
        if f'"{kappa_path.name}"' not in stdout_path.read_text(errors="replace"):
            raise ValueError(f"{name} stdout does not identify {kappa_path.name}")
        evidence["kappa_hdf5"] = {
            "path": str(kappa_path.resolve()),
            "sha256": sha256(kappa_path),
            "size_bytes": kappa_path.stat().st_size,
        }
        qmesh_evidence.append(evidence)
        expected_names.update({
            f"{name}.command.json", f"{name}.exit_code.txt", f"{name}.stdout", f"{name}.stderr",
        })
        report = hdf_report(kappa_path, length_angstrom, p3)
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
            if trailing >= 2 and first_converged_stage is None:
                first_converged_stage = ladder_index

    qmesh_converged = trailing >= 2
    if first_converged_stage is not None and stage_count != first_converged_stage + 1:
        raise ValueError(
            "q-mesh evidence continues after the runner's convergence stop condition"
        )
    if stage_count < len(LENGTH_LADDER_ANGSTROM) and not qmesh_converged:
        raise ValueError("q-mesh ladder is partial and has not met the two-step convergence gate")
    actual_names = set(initial_snapshot)
    if actual_names != expected_names:
        raise ValueError(
            "unexpected, missing, or ambiguous postprocess artifacts: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"unexpected={sorted(actual_names - expected_names)}"
        )

    fc2 = output_dir / "fc2.hdf5"
    fc3 = output_dir / "fc3.hdf5"
    force_constants = scan_force_constant_pair(fc2, fc3, expected_atoms)

    chosen = reports[-1]
    stability_pass = all(report["harmonic_stability_pass"] for report in reports)
    offdiagonal_pass = all(report["offdiagonal_check_pass"] for report in reports)
    workflow_gate = evaluate_workflow_gate(
        qmesh_converged=qmesh_converged,
        harmonic_stability_pass=stability_pass,
        offdiagonal_check_pass=offdiagonal_pass,
    )
    label = "first_pass_unconverged"
    if not stability_pass:
        label = "workflow_only_harmonic_instability_gate_failed"
    tensor_status = (
        "accepted_first_pass" if workflow_gate["pass"] else "rejected_diagnostic_only"
    )
    csv_name = (
        "kappa_L_first_pass.csv"
        if workflow_gate["pass"]
        else "kappa_L_first_pass_rejected_diagnostic.csv"
    )

    production_audit = production_dir / "production_audit.json"
    production_manifest = production_dir / "force_manifest.json"
    production_task_map = production_dir / "task_map.tsv"
    require_regular_file(production_task_map, "production task map")
    summary = {
        "document_type": "rb_kappa_L_firstpass_summary",
        "label": label,
        "software": {"phono3py": phono3py.__version__},
        "provenance_sha256": {
            "postprocess_script": sha256(Path(__file__).resolve(strict=True)),
            "production_audit": sha256(production_audit),
            "production_manifest": sha256(production_manifest),
            "production_task_map": sha256(production_task_map),
            "copied_dataset": sha256(copied_dataset),
        },
        "postprocess_artifacts_sha256": initial_snapshot,
        "execution_evidence": {
            "force_collection": collection_evidence,
            "qmesh_stages": qmesh_evidence,
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
            "supercell_atoms": expected_atoms,
            "loaded_supercell_atoms": loaded_supercell_atoms,
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
            **force_constants,
        },
        "qmesh_ladder": reports,
        "qmesh_steps": steps,
        "qmesh_converged": qmesh_converged,
        "first_pass_workflow_gate": workflow_gate,
        "required_consecutive_passing_steps": 2,
        "trace_over_3_relative_gate": 0.03,
        "each_diagonal_relative_gate": 0.05,
        "harmonic_stability_pass": stability_pass,
        "minimum_frequency_gate_THz": -0.1,
        "offdiagonal_check_pass": offdiagonal_pass,
        "selected_ladder_index": chosen["ladder_index"],
        "selected_hdf5": chosen["hdf5"],
        "selected_tensor_status": tensor_status,
        "csv_output": csv_name,
        "limitations": [
            "first-pass finite-displacement result; not a final physical uncertainty bound",
            "pair-cutoff, supercell, and displacement-amplitude convergence are not established",
            "force-constant acoustic-sum-rule and permutation residual thresholds are not established",
            "no NAC, explicit SOC, isotope scattering, or boundary scattering",
            "RTA rather than iterative LBTE",
            "sampled-mesh stability is not proof of stability everywhere",
        ],
    }
    if snapshot_output_artifacts(output_dir) != initial_snapshot:
        raise ValueError("postprocess artifacts changed while they were being validated")
    summary_bytes = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()
    csv_bytes = make_csv(chosen, status=tensor_status)
    conflicting_csv = output_dir / (
        "kappa_L_first_pass_rejected_diagnostic.csv"
        if workflow_gate["pass"]
        else "kappa_L_first_pass.csv"
    )
    if conflicting_csv.exists() or conflicting_csv.is_symlink():
        raise ValueError(f"conflicting conductivity CSV exists: {conflicting_csv}")
    write_missing_or_verify(output_dir / "kappa_summary.json", summary_bytes)
    write_missing_or_verify(output_dir / csv_name, csv_bytes)
    print(summary_bytes.decode(), end="")
    return int(workflow_gate["exit_code"])


def main() -> int:
    parser = argparse.ArgumentParser(
        epilog=(
            "Summary-only compute-node example (after separate execution authorization): "
            "python /path/to/fixed/run_postprocess_firstpass.py "
            "--production-dir /absolute/run/production "
            "--dataset-dir /absolute/run/preflight/M72_cutoff_3p70A "
            "--output-dir /absolute/run/postprocess --finalize-existing"
        ),
    )
    parser.add_argument("--production-dir", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--finalize-existing",
        action="store_true",
        help=(
            "validate a complete existing postprocess directory and create only "
            "missing summaries; never rerun force collection or q-mesh calculations"
        ),
    )
    args = parser.parse_args()
    audit_path = args.production_dir / "production_audit.json"
    manifest_path = args.production_dir / "force_manifest.json"
    audit = read_json(audit_path, "production force audit")
    if not isinstance(audit, dict):
        raise ValueError("production force audit is not a JSON object")
    if audit.get("pass") is not True:
        raise ValueError("production force audit did not pass")
    manifest = read_json(manifest_path, "production force manifest")
    if not isinstance(manifest, dict):
        raise ValueError("production force manifest is not a JSON object")
    dataset = args.dataset_dir / "phono3py_disp.yaml"
    require_regular_file(dataset, "source displacement dataset")
    if (args.dataset_dir / "BORN").exists():
        raise ValueError("BORN is forbidden in the explicit no-NAC first pass")
    if args.finalize_existing:
        if not args.output_dir.exists():
            raise FileNotFoundError(
                f"--finalize-existing requires an existing directory: {args.output_dir}"
            )
        return finalize_existing(
            args.production_dir, args.dataset_dir, args.output_dir, audit, manifest
        )
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to reuse {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    shutil.copyfile(dataset, args.output_dir / "phono3py_disp.yaml")

    cf_command = expected_collect_command(manifest)
    run(cf_command, args.output_dir, "collect_forces_fc3")
    forces = args.output_dir / "FORCES_FC3"
    require_regular_file(forces, "FORCES_FC3")

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
        command = expected_qmesh_command(ladder_index, length_angstrom)
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
    return finalize_existing(
        args.production_dir, args.dataset_dir, args.output_dir, audit, manifest
    )


if __name__ == "__main__":
    raise SystemExit(main())

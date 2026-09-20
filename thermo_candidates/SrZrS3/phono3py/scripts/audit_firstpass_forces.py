#!/usr/bin/env python3
"""Audit the immutable SrZrS3 first-pass QE force array.

This material-scoped checker intentionally does not trust directory counts or
``JOB DONE`` alone.  It binds every task to the archived displacement YAML and
task map, checks the exact QE input geometry/settings/species order, selects
the last complete main QE force block, and emits SHA-256 provenance suitable
for later force collection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
FORCE_LINE = re.compile(
    rf"^\s*atom\s+(\d+)\s+type\s+(\d+)\s+force\s*=\s*"
    rf"({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$"
)
RUN_START = re.compile(r"^\s*Program PWSCF\b", re.MULTILINE)
FORCE_HEADER = re.compile(r"^\s*Forces acting on atoms.*$", re.MULTILINE)
TOTAL_FORCE = re.compile(
    rf"Total force\s*=\s*({FLOAT}).*?Total SCF correction\s*=\s*({FLOAT})",
    re.DOTALL,
)
ALLOWED_STDERR = (
    "Note: The following floating-point exceptions are signalling: "
    "IEEE_UNDERFLOW_FLAG IEEE_DENORMAL"
)


class AuditError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def f64(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def parse_card(text: str, name: str) -> list[str]:
    match = re.search(rf"(?im)^\s*{re.escape(name)}(?:\s+\w+)?\s*$", text)
    require(match is not None, f"missing {name}")
    lines: list[str] = []
    for line in text[match.end() :].splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if re.match(r"^[A-Z_]+(?:\s+\w+)?$", stripped) or stripped.startswith("&"):
            break
        lines.append(" ".join(stripped.split()))
    return lines


def structure_fingerprint(path: Path) -> dict[str, object]:
    text = path.read_text(errors="strict")
    cell_header = re.search(r"(?im)^\s*CELL_PARAMETERS(?:\s+(\w+))?\s*$", text)
    require(cell_header is not None, f"missing CELL_PARAMETERS in {path}")
    cell_unit = (cell_header.group(1) or "alat").lower()
    require(cell_unit in {"bohr", "angstrom"}, f"unsupported cell unit in {path}: {cell_unit}")
    cell = parse_card(text, "CELL_PARAMETERS")
    species = parse_card(text, "ATOMIC_SPECIES")
    positions = parse_card(text, "ATOMIC_POSITIONS")
    require(len(cell) == 3, f"bad cell in {path}")
    require(len(species) == 3, f"bad species card in {path}")
    require(len(positions) == 40, f"bad atom count in {path}")
    labels = [line.split()[0] for line in positions]
    species_rows = [line.split() for line in species]
    require(all(len(row) == 3 for row in species_rows), f"bad species row in {path}")
    factor = 0.529177210903 if cell_unit == "bohr" else 1.0
    return {
        "cell": [[f64(x) * factor for x in row.split()] for row in cell],
        "species": {row[0]: [f64(row[1]), row[2]] for row in species_rows},
        "species_order": [row[0] for row in species_rows],
        "positions": [[row.split()[0], *[f64(x) for x in row.split()[1:4]]] for row in positions],
        "atom_order": labels,
    }


def setting_fingerprint(path: Path) -> dict[str, object]:
    text = path.read_text(errors="strict")
    # The generated fragment starts with a phono3py comment that repeats
    # ``ibrav``, ``nat``, and ``ntyp``.  Settings are authoritative only in
    # the QE namelists preceding that fragment.
    namelist_text = text.split("!    ibrav", 1)[0]
    def value(key: str) -> str:
        matches = re.findall(rf"(?i)\b{re.escape(key)}\s*=\s*([^,\n/]+)", namelist_text)
        require(len(matches) == 1, f"expected one {key} in {path}")
        return matches[0].strip().lower()
    kpoints = parse_card(text, "K_POINTS")
    require(len(kpoints) == 1, f"bad K_POINTS in {path}")
    return {
        "calculation": value("calculation").replace('"', "'"),
        "nat": int(value("nat")),
        "ntyp": int(value("ntyp")),
        "ecutwfc_Ry": f64(value("ecutwfc")),
        "ecutrho_Ry": f64(value("ecutrho")),
        "conv_thr_Ry": f64(value("conv_thr")),
        "occupations": value("occupations").replace('"', "'"),
        "nspin": int(value("nspin")),
        "tot_charge": f64(value("tot_charge")),
        "nosym": value("nosym"),
        "noinv": value("noinv"),
        "tprnfor": value("tprnfor"),
        "tstress": value("tstress"),
        "verbosity": value("verbosity").replace('"', "'"),
        "kmesh_and_shift": [int(x) for x in kpoints[0].split()],
    }


def dataset_ids(data: dict[str, object]) -> tuple[list[int], list[int]]:
    pairs = data["displacement_pairs"]
    require(isinstance(pairs, list), "displacement_pairs must be a list")
    all_ids: list[int] = []
    included: list[int] = []
    for first in pairs:
        first_id = first["displacement_id"]
        all_ids.append(first_id)
        included.append(first_id)
        for paired in first["paired_with"]:
            ids = paired["displacement_ids"]
            all_ids.extend(ids)
            if paired["included"]:
                included.extend(ids)
    require(len(all_ids) == len(set(all_ids)), "duplicate YAML displacement IDs")
    all_ids = sorted(all_ids)
    included = sorted(included)
    require(all_ids == list(range(1, len(all_ids) + 1)), "YAML IDs are not the exact 1..N set")
    require(len(included) == len(set(included)), "duplicate included YAML IDs")
    return all_ids, included


def last_force_block(path: Path, expected_types: list[int]) -> dict[str, object]:
    text = path.read_text(errors="replace")
    starts = list(RUN_START.finditer(text))
    run = text[starts[-1].start() :] if starts else text
    located: list[tuple[int, int, list[tuple[int, int, float, float, float]], float, float]] = []
    headers = list(FORCE_HEADER.finditer(run))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(run)
        cursor = header.end()
        rows = []
        for line in run[cursor:end].splitlines(keepends=True):
            match = FORCE_LINE.fullmatch(line.rstrip("\r\n"))
            if match:
                rows.append((int(match[1]), int(match[2]), *(f64(match[i]) for i in (3, 4, 5))))
                cursor += len(line)
                continue
            if not rows and not line.strip():
                cursor += len(line)
                continue
            break
        total = TOTAL_FORCE.search(run, cursor, end)
        if rows and total:
            located.append((header.start(), total.end(), rows, f64(total[1]), f64(total[2])))
    require(located, f"no complete main force block: {path}")
    header_start, block_end, rows, total_force, correction = located[-1]
    require([row[0] for row in rows] == list(range(1, 41)), f"bad force atom indices: {path}")
    require([row[1] for row in rows] == expected_types, f"force atom types differ from input: {path}")
    trailing = run[block_end:]
    require("JOB DONE" in trailing, f"missing JOB DONE after selected force block: {path}")
    prefix = run[:header_start]
    require(prefix.rfind("convergence has been achieved") > prefix.rfind("convergence NOT achieved"),
            f"no achieved SCF before selected force block: {path}")
    require(not any(h.start() > header_start for h in headers), f"later incomplete force block: {path}")
    forbidden = ("Error in routine", "%%%%%%%%", "convergence NOT achieved")
    require(not any(token in trailing for token in forbidden), f"fatal/nonconverged trailing text: {path}")
    forces = [[row[2], row[3], row[4]] for row in rows]
    require(all(math.isfinite(x) for row in forces for x in row), f"non-finite force: {path}")
    return {
        "forces": forces,
        "max_abs_force_Ry_per_bohr": max(abs(x) for row in forces for x in row),
        "rms_force_Ry_per_bohr": math.sqrt(sum(x * x for row in forces for x in row) / 120),
        "total_force_Ry_per_bohr": total_force,
        "scf_correction_Ry_per_bohr": correction,
    }


def pilot_signal_audit(attempt: Path) -> dict[str, object]:
    require(attempt.is_dir() and not attempt.is_symlink(), "missing immutable pilot attempt")
    identities = [0, 0, 1, 3, 1, 3]
    force_sets = []
    for task_id, displacement_id in enumerate(identities):
        task = attempt / f"task-{task_id}"
        structure = structure_fingerprint(task / "scf.in")
        types = {label: index + 1 for index, label in enumerate(structure["species_order"])}
        expected_types = [types[label] for label in structure["atom_order"]]
        require((task / "result.json").is_file(), f"pilot task {task_id}: missing result receipt")
        result = json.loads((task / "result.json").read_text())
        require(result["healthy"] is True and result["displacement_id"] == displacement_id,
                f"pilot task {task_id}: unhealthy or wrong displacement identity")
        force_sets.append(last_force_block(task / "scf.out", expected_types)["forces"])

    arrays = [[[float(x) for x in row] for row in forces] for forces in force_sets]
    def rms_difference(left, right) -> float:
        values = [x - y for row_a, row_b in zip(left, right) for x, y in zip(row_a, row_b)]
        return math.sqrt(sum(x * x for x in values) / len(values))
    def average(left, right):
        return [[(x + y) / 2 for x, y in zip(row_a, row_b)] for row_a, row_b in zip(left, right)]
    pristine_noise = rms_difference(arrays[0], arrays[1])
    single_noise = rms_difference(arrays[2], arrays[4])
    double_noise = rms_difference(arrays[3], arrays[5])
    pristine_average = average(arrays[0], arrays[1])
    single_average = average(arrays[2], arrays[4])
    double_average = average(arrays[3], arrays[5])
    single_signal = rms_difference(single_average, pristine_average)
    double_incremental_signal = rms_difference(double_average, single_average)
    single_propagated_noise = math.sqrt(pristine_noise ** 2 + single_noise ** 2)
    double_propagated_noise = math.sqrt(single_noise ** 2 + double_noise ** 2)
    require(max(pristine_noise, single_noise, double_noise) <= 5e-6,
            "pilot duplicate noise exceeds 5e-6 Ry/bohr")
    require(single_signal > 5e-5 and single_signal > 10 * single_propagated_noise,
            "pilot single-displacement signal is not distinguishable")
    require(double_incremental_signal > 5e-5 and
            double_incremental_signal > 10 * double_propagated_noise,
            "pilot double-displacement incremental signal is not distinguishable")
    return {"accepted_for_first_pass_force_signal_only": True, "attempt": str(attempt),
            "task_displacement_ids": identities,
            "duplicate_rms_Ry_per_bohr": {"pristine": pristine_noise, "single": single_noise,
                                            "double": double_noise},
            "incremental_rms_signal_Ry_per_bohr": {"single_minus_pristine": single_signal,
                                                     "double_minus_single": double_incremental_signal},
            "propagated_noise_Ry_per_bohr": {"single_minus_pristine": single_propagated_noise,
                                               "double_minus_single": double_propagated_noise},
            "scope": "distinguishable first-pass signal only; not amplitude, cutoff, supercell, FC3, phonon, or kappa convergence"}


def phono3py_drift_subtracted_quantized(displaced, pristine):
    """Reproduce phono3py's per-file drift removal and 10-decimal writer."""
    require(len(displaced) == len(pristine) and bool(displaced), "force block size mismatch")
    count = len(displaced)
    displaced_drift = [sum(row[axis] for row in displaced) / count for axis in range(3)]
    pristine_drift = [sum(row[axis] for row in pristine) / count for axis in range(3)]
    result = []
    for displaced_row, pristine_row in zip(displaced, pristine):
        row = [displaced_row[axis] - displaced_drift[axis]
               - pristine_row[axis] + pristine_drift[axis] for axis in range(3)]
        result.append([float(f"{value:.10f}") for value in row])
    return result


def expected_fc_dataset_name(order: int, keys) -> str:
    """Return the documented phono3py HDF5 array key for FC2 or FC3."""
    expected = "force_constants" if order == 2 else "fc3" if order == 3 else None
    require(expected is not None, "force-constant order must be 2 or 3")
    require(expected in set(keys), f"missing documented {expected} HDF5 dataset")
    return expected


def main() -> int:
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--sacct", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hashes", type=Path, required=True)
    parser.add_argument("--pilot-attempt", type=Path, required=True)
    parser.add_argument("--allow-pristine-firstpass-exception", action="store_true")
    parser.add_argument("--exception-output", type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    require(root.is_dir() and not root.is_symlink(), "invalid run directory")
    require(not any(path.is_symlink() for path in root.rglob("*")), "run tree contains symlinks")

    provenance_path = root / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    task_map_path = root / "task_map.tsv"
    dataset_path = root / "generation/phono3py_disp.yaml"
    require(sha256(task_map_path) == provenance["task_map_sha256"], "task-map provenance mismatch")
    require(sha256(dataset_path) == provenance["phono3py_disp_yaml_sha256"], "YAML provenance mismatch")
    require(provenance["task_count"] == 788 and provenance["displacement_task_count"] == 787,
            "unexpected provenance task count")
    require(provenance["settings"] == {"conv_thr_Ry": 1e-10, "ecutrho_Ry": 640.0,
            "ecutwfc_Ry": 80.0, "kmesh": [3, 3, 3], "kshift": [0, 0, 0]},
            "unexpected provenance settings")

    dataset = yaml.safe_load(dataset_path.read_text())
    require(dataset["physical_unit"]["length"] == "au", "YAML length unit is not au")
    require(dataset["supercell_matrix"] == [[2, 0, 0], [0, 1, 0], [0, 0, 1]],
            "unexpected supercell matrix")
    all_ids, included_ids = dataset_ids(dataset)
    require(len(all_ids) == 4025 and len(included_ids) == 787, "unexpected YAML displacement counts")

    with task_map_path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames == ["task_id", "displacement_id", "input_path", "input_sha256"],
                "unexpected task-map schema")
        rows = list(reader)
    require(len(rows) == 788, "task-map row count mismatch")
    require([int(row["task_id"]) for row in rows] == list(range(788)), "task IDs are not 0..787")
    require([int(row["displacement_id"]) for row in rows] == [0, *included_ids],
            "task map does not exactly match YAML included-ID order")

    expected_settings = {"calculation": "'scf'", "nat": 40, "ntyp": 3,
        "ecutwfc_Ry": 80.0, "ecutrho_Ry": 640.0, "conv_thr_Ry": 1e-10,
        "occupations": "'fixed'", "nspin": 1, "tot_charge": 0.0,
        "nosym": ".true.", "noinv": ".true.", "tprnfor": ".true.",
        "tstress": ".true.", "verbosity": "'high'", "kmesh_and_shift": [3, 3, 3, 0, 0, 0]}
    input_hashes: list[tuple[str, str]] = []
    output_hashes: list[tuple[str, str]] = []
    stderr_hashes: list[tuple[str, str]] = []
    force_stats = []
    atom_order_reference = None
    species_reference = None
    cell_reference = None
    stderr_line_counts: dict[str, int] = {}
    maximum_source_cell_difference_angstrom = 0.0
    maximum_source_position_difference_fractional = 0.0
    for row in rows:
        task_id = int(row["task_id"])
        displacement_id = int(row["displacement_id"])
        task_dir = root / f"tasks/task-{task_id:04d}"
        input_path = task_dir / "scf.in"
        require(Path(row["input_path"]) == input_path, f"task {task_id}: input path mismatch")
        require(sha256(input_path) == row["input_sha256"], f"task {task_id}: input hash mismatch")
        source = root / ("generation/supercell.in" if displacement_id == 0
                         else f"generation/supercell-{displacement_id:05d}.in")
        require(source.is_file(), f"task {task_id}: missing generated source")
        observed_structure = structure_fingerprint(input_path)
        source_structure = structure_fingerprint(source)
        require(observed_structure["species"] == source_structure["species"],
                f"task {task_id}: generated/input species mismatch")
        require(observed_structure["species_order"] == source_structure["species_order"],
                f"task {task_id}: generated/input species order mismatch")
        require(observed_structure["atom_order"] == source_structure["atom_order"],
                f"task {task_id}: generated/input atom order mismatch")
        cell_difference = max(abs(x - y) for row_a, row_b in
                              zip(observed_structure["cell"], source_structure["cell"])
                              for x, y in zip(row_a, row_b))
        position_difference = max(abs(x - y) for row_a, row_b in
                                  zip(observed_structure["positions"], source_structure["positions"])
                                  for x, y in zip(row_a[1:], row_b[1:]))
        require(cell_difference <= 1e-12, f"task {task_id}: generated/input cell mismatch")
        require(position_difference <= 1e-14, f"task {task_id}: generated/input position mismatch")
        maximum_source_cell_difference_angstrom = max(maximum_source_cell_difference_angstrom,
                                                      cell_difference)
        maximum_source_position_difference_fractional = max(
            maximum_source_position_difference_fractional, position_difference)
        require(setting_fingerprint(input_path) == expected_settings, f"task {task_id}: QE setting mismatch")
        atom_order_reference = atom_order_reference or observed_structure["atom_order"]
        species_reference = species_reference or observed_structure["species"]
        cell_reference = cell_reference or observed_structure["cell"]
        require(observed_structure["atom_order"] == atom_order_reference,
                f"task {task_id}: atom order differs from pristine")
        require(observed_structure["species"] == species_reference,
                f"task {task_id}: species mapping differs from pristine")
        require(observed_structure["cell"] == cell_reference,
                f"task {task_id}: cell differs from pristine")
        species_order = observed_structure["species_order"]
        type_by_label = {label: index + 1 for index, label in enumerate(species_order)}
        expected_types = [type_by_label[label] for label in observed_structure["atom_order"]]

        require((task_dir / "exit_code.txt").read_text().strip() == "0", f"task {task_id}: nonzero receipt")
        require((task_dir / "task_identity.tsv").read_text().strip() == f"{task_id}\t{displacement_id}",
                f"task {task_id}: identity mismatch")
        require((task_dir / "started_utc.txt").read_text().strip()
                and (task_dir / "finished_utc.txt").read_text().strip(), f"task {task_id}: missing timestamps")
        stderr_path = task_dir / "scf.err"
        stderr_lines = [line for line in stderr_path.read_text(errors="replace").splitlines() if line]
        require(all(line == ALLOWED_STDERR for line in stderr_lines),
                f"task {task_id}: unexpected stderr content")
        stderr_line_counts[str(len(stderr_lines))] = stderr_line_counts.get(str(len(stderr_lines)), 0) + 1
        output_path = task_dir / "scf.out"
        record = last_force_block(output_path, expected_types)
        force_stats.append((task_id, displacement_id, record))
        input_hashes.append((sha256(input_path), str(input_path.relative_to(root))))
        output_hashes.append((sha256(output_path), str(output_path.relative_to(root))))
        stderr_hashes.append((sha256(stderr_path), str(stderr_path.relative_to(root))))

    pristine = force_stats[0][2]
    pristine_passed = pristine["max_abs_force_Ry_per_bohr"] <= 5e-5
    if not pristine_passed:
        require(args.allow_pristine_firstpass_exception and args.exception_output is not None,
                "pristine maximum force exceeds 5e-5 Ry/bohr gate")
        require(pristine["max_abs_force_Ry_per_bohr"] <= 1e-4,
                "pristine maximum force exceeds explicit first-pass exception ceiling")
        exception = {"schema_version": 1, "material": "SrZrS3",
                     "configured_pristine_gate_Ry_per_bohr": 5e-5,
                     "configured_gate_passed": False,
                     "observed_max_abs_force_Ry_per_bohr": pristine["max_abs_force_Ry_per_bohr"],
                     "exception_ceiling_Ry_per_bohr": 1e-4,
                     "exception_authorization": "explicit_time_bounded_first_pass_only",
                     "required_handling": "strict_per_atom_pristine_subtraction",
                     "required_final_label": "first_pass_unconverged",
                     "scientific_limitation": "The preferred pristine-force threshold was not met."}
        args.exception_output.write_text(json.dumps(exception, indent=2, sort_keys=True) + "\n")
    pilot_signal = pilot_signal_audit(args.pilot_attempt.resolve())
    sacct_lines = [line.split("|") for line in args.sacct.read_text().splitlines() if line.strip()]
    require(len(sacct_lines) == 788, "scheduler row count is not 788")
    require(all(row[0] == "COMPLETED" and row[1] == "0:0" for row in sacct_lines),
            "scheduler accounting is not uniformly COMPLETED/0:0")

    def write_hash_rows(rows_to_write: list[tuple[str, str]], handle) -> None:
        for digest, relative in rows_to_write:
            handle.write(f"{digest}  {relative}\n")

    args.hashes.parent.mkdir(parents=True, exist_ok=True)
    with args.hashes.open("w") as handle:
        write_hash_rows([(sha256(provenance_path), "provenance.json"),
                         (sha256(task_map_path), "task_map.tsv"),
                         (sha256(dataset_path), "generation/phono3py_disp.yaml")], handle)
        write_hash_rows(input_hashes, handle)
        write_hash_rows(output_hashes, handle)
        write_hash_rows(stderr_hashes, handle)

    summary = {
        "schema_version": 1,
        "status": "accepted_for_first_pass_postprocessing",
        "run_dir": str(root),
        "scheduler": {"job_id": "21888373", "rows": 788,
                      "state": "COMPLETED", "exit_code": "0:0",
                      "sacct_sha256": sha256(args.sacct)},
        "mapping": {"task_count": 788, "pristine_task_id": 0,
                    "all_yaml_displacement_ids": len(all_ids),
                    "included_yaml_displacement_ids": len(included_ids),
                    "excluded_zero_force_blocks": len(all_ids) - len(included_ids),
                    "task_map_sha256": sha256(task_map_path),
                    "included_id_list_sha256": hashlib.sha256(
                        ("\n".join(map(str, included_ids)) + "\n").encode()).hexdigest()},
        "dataset": {"phono3py_disp_yaml_sha256": sha256(dataset_path),
                    "length_unit": "au", "supercell_matrix": dataset["supercell_matrix"],
                    "unitcell_atoms": 20, "supercell_atoms": 40,
                    "pair_cutoff_angstrom": 3.5541348625,
                    "pair_cutoff_cli_bohr": 6.71634150010947},
        "qe": {"settings": expected_settings, "atom_order": atom_order_reference,
               "species_by_label": species_reference, "cell_angstrom": cell_reference,
               "maximum_generated_input_cell_difference_angstrom": maximum_source_cell_difference_angstrom,
               "maximum_generated_input_position_difference_fractional": maximum_source_position_difference_fractional,
               "all_exit_code_receipts_zero": True, "all_strict_last_force_blocks_complete": True,
               "all_output_atom_types_match_input": True,
               "stderr_only_ieee_underflow_denormal": True,
               "stderr_allowed_line_count_distribution": stderr_line_counts,
               "pristine_force": {**{key: value for key, value in pristine.items() if key != "forces"},
                                  "configured_gate_Ry_per_bohr": 5e-5,
                                  "configured_gate_passed": pristine_passed,
                                  "firstpass_exception_used": not pristine_passed,
                                  "exception_record": str(args.exception_output) if not pristine_passed else None}},
        "pilot_signal": pilot_signal,
        "hash_inventory": {"path": str(args.hashes), "sha256": None,
                           "input_rows": len(input_hashes), "output_rows": len(output_hashes),
                           "stderr_rows": len(stderr_hashes)},
        "limitations": ["time-bounded first pass", "2x1x1 supercell is not converged",
                        "3.5541348625-A pair cutoff is not converged",
                        "80/640-Ry and 3x3x3 force settings are not general defaults"],
    }
    summary["hash_inventory"]["sha256"] = sha256(args.hashes)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, KeyError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        raise SystemExit(2)

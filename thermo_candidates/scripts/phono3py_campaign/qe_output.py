#!/usr/bin/env python3
"""Strict Quantum ESPRESSO force-output parsing for phonon campaigns.

The legacy SrCu2SnS4 driver used an awk range that also consumed QE's
``Total SCF correction`` text.  On some awk implementations that converted a
real residual force to zero.  This module is the single parser used by the v2
workflow.  It reads only explicit ``atom ... force =`` records from the last
complete force block and treats malformed or incomplete output as an error.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
FORCE_LINE = re.compile(
    rf"^\s*atom\s+(\d+)\s+type\s+\d+\s+force\s*=\s*"
    rf"({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$",
    re.MULTILINE,
)
RUN_START = re.compile(r"^\s*Program PWSCF\b", re.MULTILINE)
FORCE_HEADER = re.compile(r"^\s*Forces acting on atoms.*$", re.MULTILINE)
TOTAL_FORCE = re.compile(
    rf"Total force\s*=\s*({FLOAT}).*?Total SCF correction\s*=\s*({FLOAT})",
    re.DOTALL,
)


class QEOutputError(ValueError):
    """Raised when a QE output is not a valid force record."""


@dataclass(frozen=True)
class ForceRecord:
    atom_indices: tuple[int, ...]
    forces_ry_bohr: tuple[tuple[float, float, float], ...]
    total_force_ry_bohr: float | None
    scf_correction_ry_bohr: float | None

    @property
    def max_abs_ry_bohr(self) -> float:
        return max(abs(value) for row in self.forces_ry_bohr for value in row)

    @property
    def rms_ry_bohr(self) -> float:
        values = [value for row in self.forces_ry_bohr for value in row]
        return math.sqrt(sum(value * value for value in values) / len(values))

    @property
    def vector_sum_ry_bohr(self) -> tuple[float, float, float]:
        return tuple(sum(row[axis] for row in self.forces_ry_bohr) for axis in range(3))


@dataclass(frozen=True)
class _LocatedForceRecord:
    header_start: int
    block_end: int
    record: ForceRecord


def _float(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def _force_records(run_text: str) -> list[_LocatedForceRecord]:
    """Return QE's main force block after each explicit force header.

    With ``verbosity='high'`` QE prints several per-term force decompositions
    after the physical total forces.  Those lines repeat atom indices and must
    not be consumed.  The main block is therefore defined as the first
    contiguous sequence of atom-force lines following the header, with blank
    lines allowed only before the first atom.
    """

    headers = list(FORCE_HEADER.finditer(run_text))
    records: list[_LocatedForceRecord] = []
    for header_number, header in enumerate(headers):
        segment_end = (
            headers[header_number + 1].start()
            if header_number + 1 < len(headers)
            else len(run_text)
        )
        position = header.end()
        matches: list[re.Match[str]] = []
        for line in run_text[position:segment_end].splitlines(keepends=True):
            stripped = line.strip()
            match = FORCE_LINE.fullmatch(line.rstrip("\r\n"))
            if match:
                matches.append(match)
                position += len(line)
                continue
            if not matches and not stripped:
                position += len(line)
                continue
            break
        if not matches:
            continue
        total_match = TOTAL_FORCE.search(run_text, position, segment_end)
        if not total_match:
            continue
        atom_indices = tuple(int(match.group(1)) for match in matches)
        expected_indices = tuple(range(1, len(atom_indices) + 1))
        if atom_indices != expected_indices:
            raise QEOutputError(
                "non-contiguous atom indices after force header: "
                f"got {atom_indices[:5]}...{atom_indices[-5:]}"
            )
        forces = tuple(
            tuple(_float(match.group(column)) for column in (2, 3, 4))
            for match in matches
        )
        if not all(math.isfinite(value) for row in forces for value in row):
            raise QEOutputError("non-finite force in main force block")
        records.append(
            _LocatedForceRecord(
                header_start=header.start(),
                block_end=total_match.end(),
                record=ForceRecord(
                    atom_indices,
                    forces,
                    _float(total_match.group(1)),
                    _float(total_match.group(2)),
                ),
            )
        )
    return records


def parse_last_force_block(path: str | Path, expected_atoms: int | None = None) -> ForceRecord:
    output_path = Path(path)
    text = output_path.read_text(errors="replace")
    run_starts = list(RUN_START.finditer(text))
    run_text = text[run_starts[-1].start() :] if run_starts else text
    records = _force_records(run_text)
    if not records:
        raise QEOutputError(f"no complete force block in {output_path}")
    record = records[-1].record
    if expected_atoms is not None and len(record.atom_indices) != expected_atoms:
        raise QEOutputError(
            f"atom count mismatch in {output_path}: "
            f"{len(record.atom_indices)} vs {expected_atoms}"
        )
    return record


def inspect_output(path: str | Path, expected_atoms: int) -> dict[str, object]:
    output_path = Path(path)
    text = output_path.read_text(errors="replace")
    run_starts = list(RUN_START.finditer(text))
    run_text = text[run_starts[-1].start() :] if run_starts else text
    record = parse_last_force_block(output_path, expected_atoms)
    located_records = _force_records(run_text)
    selected = located_records[-1]
    errors: list[str] = []
    trailing = run_text[selected.block_end :]
    if "JOB DONE." not in trailing and "JOB DONE" not in trailing:
        errors.append("missing JOB DONE")
    prefix = run_text[: selected.header_start]
    achieved = prefix.rfind("convergence has been achieved")
    not_achieved = prefix.rfind("convergence NOT achieved")
    if achieved < 0 or not_achieved > achieved:
        errors.append("missing SCF convergence marker")
    headers = list(FORCE_HEADER.finditer(run_text))
    if headers and headers[-1].start() > selected.header_start:
        errors.append("incomplete force block follows the selected block")
    if "convergence NOT achieved" in trailing:
        errors.append("non-converged SCF follows the selected force block")
    if "convergence has been achieved" in trailing:
        errors.append("later SCF cycle follows the selected force block")
    if "Error in routine" in run_text:
        errors.append("QE Error in routine")
    if "%%%%%%" in run_text:
        errors.append("QE fatal error banner")
    return {
        "path": str(output_path),
        "healthy": not errors,
        "errors": errors,
        "atom_count": len(record.forces_ry_bohr),
        "max_abs_force_ry_bohr": record.max_abs_ry_bohr,
        "rms_force_ry_bohr": record.rms_ry_bohr,
        "force_vector_sum_ry_bohr": list(record.vector_sum_ry_bohr),
        "total_force_ry_bohr": record.total_force_ry_bohr,
        "scf_correction_ry_bohr": record.scf_correction_ry_bohr,
    }


def subtract_forces(
    displaced: Sequence[Sequence[float]], pristine: Sequence[Sequence[float]]
) -> tuple[tuple[float, float, float], ...]:
    if len(displaced) != len(pristine):
        raise QEOutputError(f"force count mismatch: {len(displaced)} vs {len(pristine)}")
    return tuple(
        tuple(float(d) - float(p) for d, p in zip(displaced_row, pristine_row))
        for displaced_row, pristine_row in zip(displaced, pristine)
    )


def compare_force_records(
    reference: ForceRecord,
    candidate: ForceRecord,
    reference_pristine: ForceRecord | None = None,
    candidate_pristine: ForceRecord | None = None,
) -> dict[str, float | int | bool]:
    if len(reference.forces_ry_bohr) != len(candidate.forces_ry_bohr):
        raise QEOutputError(
            f"force count mismatch: {len(reference.forces_ry_bohr)} vs "
            f"{len(candidate.forces_ry_bohr)}"
        )
    ref = reference.forces_ry_bohr
    cand = candidate.forces_ry_bohr
    if (reference_pristine is None) != (candidate_pristine is None):
        raise QEOutputError("both pristine force records are required for induced-force comparison")
    if reference_pristine is not None and candidate_pristine is not None:
        ref = subtract_forces(ref, reference_pristine.forces_ry_bohr)
        cand = subtract_forces(cand, candidate_pristine.forces_ry_bohr)

    differences = [
        float(candidate_value) - float(reference_value)
        for reference_row, candidate_row in zip(ref, cand)
        for reference_value, candidate_value in zip(reference_row, candidate_row)
    ]
    ref_values = [value for row in ref for value in row]
    max_abs = max(abs(value) for value in differences)
    rms = math.sqrt(sum(value * value for value in differences) / len(differences))
    ref_rms = math.sqrt(sum(value * value for value in ref_values) / len(ref_values))
    return {
        "atom_count": len(ref),
        "max_abs_difference_ry_bohr": max_abs,
        "rms_difference_ry_bohr": rms,
        "reference_rms_ry_bohr": ref_rms,
        "relative_rms_difference": rms / ref_rms if ref_rms else math.inf,
        "pristine_subtracted": reference_pristine is not None,
    }


def _write_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("output", type=Path)
    inspect_parser.add_argument("--expected-atoms", type=int, required=True)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("reference", type=Path)
    compare_parser.add_argument("candidate", type=Path)
    compare_parser.add_argument("--expected-atoms", type=int, required=True)
    compare_parser.add_argument("--reference-pristine", type=Path)
    compare_parser.add_argument("--candidate-pristine", type=Path)
    compare_parser.add_argument("--max-threshold", type=float)
    compare_parser.add_argument("--rms-threshold", type=float)
    compare_parser.add_argument("--relative-rms-threshold", type=float)

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "inspect":
            report = inspect_output(args.output, args.expected_atoms)
            _write_json(report)
            return 0 if report["healthy"] else 2

        input_paths = [args.reference, args.candidate]
        if args.reference_pristine:
            input_paths.append(args.reference_pristine)
        if args.candidate_pristine:
            input_paths.append(args.candidate_pristine)
        unhealthy = [
            report
            for report in (inspect_output(path, args.expected_atoms) for path in input_paths)
            if not report["healthy"]
        ]
        if unhealthy:
            raise QEOutputError(
                "unhealthy comparison input(s): "
                + "; ".join(
                    f"{report['path']}: {', '.join(report['errors'])}" for report in unhealthy
                )
            )
        reference = parse_last_force_block(args.reference, args.expected_atoms)
        candidate = parse_last_force_block(args.candidate, args.expected_atoms)
        reference_pristine = parse_last_force_block(
            args.reference_pristine, args.expected_atoms
        ) if args.reference_pristine else None
        candidate_pristine = parse_last_force_block(
            args.candidate_pristine, args.expected_atoms
        ) if args.candidate_pristine else None
        report = compare_force_records(
            reference, candidate, reference_pristine, candidate_pristine
        )
        checks = []
        if args.max_threshold is not None:
            checks.append(report["max_abs_difference_ry_bohr"] <= args.max_threshold)
        if args.rms_threshold is not None:
            checks.append(report["rms_difference_ry_bohr"] <= args.rms_threshold)
        if args.relative_rms_threshold is not None:
            checks.append(report["relative_rms_difference"] <= args.relative_rms_threshold)
        report["pass"] = all(checks) if checks else True
        _write_json(report)
        return 0 if report["pass"] else 3
    except (OSError, QEOutputError, ValueError) as exc:
        _write_json({"healthy": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

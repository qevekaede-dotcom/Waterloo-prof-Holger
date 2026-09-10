#!/usr/bin/env python3
"""Strict Quantum ESPRESSO input preparation for phonon campaigns.

Only the deliberately narrow input dialect used by this repository is
accepted: ``ibrav = 0``, crystal fractional coordinates, an Angstrom cell,
and an automatic k-point grid.  Refusing ambiguous cards or duplicate
assignments is preferable to silently preparing a scientifically different
calculation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_%]*")
_NAMELIST_HEADER = r"(?im)^[ \t]*&{name}\b[^\r\n]*(?:\r?\n|$)"
_NAMELIST_END = re.compile(
    r"(?m)^[ \t]*/[ \t]*(?:![^\r\n]*)?(?:\r?\n|$)"
)
_CARD_NAMES = (
    "ATOMIC_SPECIES",
    "ATOMIC_POSITIONS",
    "K_POINTS",
    "CELL_PARAMETERS",
    "ATOMIC_FORCES",
    "CONSTRAINTS",
    "OCCUPATIONS",
    "SOLVENTS",
    "HUBBARD",
)
_FINAL_MARKER = re.compile(
    r"(?im)^[ \t]*(Begin final coordinates|End final coordinates)[ \t]*$"
)


class QEInputError(ValueError):
    """Raised when an input or final-coordinate record is unsafe to use."""


@dataclass(frozen=True)
class AtomicSpecies:
    label: str
    mass_amu: float
    pseudopotential: str


@dataclass(frozen=True)
class AtomicPosition:
    label: str
    coordinates: tuple[float, float, float]
    coordinate_tokens: tuple[str, ...] = ()
    constraints: tuple[int, ...] = ()


@dataclass(frozen=True)
class AutomaticKPoints:
    grid: tuple[int, int, int]
    shift: tuple[int, int, int]


@dataclass(frozen=True)
class QEInput:
    text: str
    nat: int
    ntyp: int
    ibrav: int
    ecutwfc_ry: float
    ecutrho_ry: float
    atomic_species: tuple[AtomicSpecies, ...]
    position_unit: str
    atomic_positions: tuple[AtomicPosition, ...]
    cell_unit: str
    cell_parameters: tuple[tuple[float, float, float], ...]
    k_points: AutomaticKPoints
    position_rows_span: tuple[int, int]
    cell_rows_span: tuple[int, int]
    k_point_row_span: tuple[int, int]


@dataclass(frozen=True)
class FinalCoordinates:
    position_unit: str
    atomic_positions: tuple[AtomicPosition, ...]
    cell_unit: str | None = None
    cell_parameters: tuple[tuple[float, float, float], ...] | None = None
    cell_parameter_tokens: tuple[tuple[str, str, str], ...] | None = None


@dataclass(frozen=True)
class _Namelist:
    name: str
    body_start: int
    body_end: int
    close_start: int


@dataclass(frozen=True)
class _Card:
    name: str
    qualifier: str
    header_start: int
    header_end: int


@dataclass(frozen=True)
class _Assignment:
    key: str
    value_start: int
    value_end: int
    value: str


def _as_float(token: str, context: str) -> float:
    if not re.fullmatch(FLOAT, token):
        raise QEInputError(f"invalid floating-point value for {context}: {token!r}")
    value = float(token.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise QEInputError(f"non-finite value for {context}: {token!r}")
    return value


def _strip_comment(line: str) -> str:
    """Remove a QE ``!`` comment while respecting quoted strings."""

    quote: str | None = None
    index = 0
    while index < len(line):
        character = line[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(line) and line[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif character in "'\"":
            quote = character
        elif character == "!":
            return line[:index]
        index += 1
    return line


def _find_namelist(text: str, name: str) -> _Namelist:
    headers = list(re.finditer(_NAMELIST_HEADER.format(name=re.escape(name)), text))
    if len(headers) != 1:
        raise QEInputError(
            f"expected exactly one &{name.upper()} namelist, found {len(headers)}"
        )
    header = headers[0]
    closing = _NAMELIST_END.search(text, header.end())
    if closing is None:
        raise QEInputError(f"missing closing '/' for &{name.upper()}")
    nested = re.search(r"(?im)^[ \t]*&[A-Za-z_]", text[header.end() : closing.start()])
    if nested:
        raise QEInputError(f"missing unambiguous closing '/' for &{name.upper()}")
    return _Namelist(name.upper(), header.end(), closing.start(), closing.start())


def _scan_assignments(text: str, namelist: _Namelist) -> tuple[_Assignment, ...]:
    assignments: list[_Assignment] = []
    index = namelist.body_start
    end = namelist.body_end
    while index < end:
        character = text[index]
        if character == "!":
            newline = text.find("\n", index, end)
            index = end if newline < 0 else newline + 1
            continue
        if character in "'\"":
            quote = character
            index += 1
            while index < end:
                if text[index] == quote:
                    if index + 1 < end and text[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        identifier = _IDENTIFIER.match(text, index)
        if identifier is None:
            index += 1
            continue
        key = identifier.group(0).lower()
        cursor = identifier.end()
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor >= end or text[cursor] != "=":
            index = identifier.end()
            continue
        cursor += 1
        while cursor < end and text[cursor].isspace():
            cursor += 1
        value_start = cursor
        quote = None
        while cursor < end:
            current = text[cursor]
            if quote is not None:
                if current == quote:
                    if cursor + 1 < end and text[cursor + 1] == quote:
                        cursor += 2
                        continue
                    quote = None
                cursor += 1
                continue
            if current in "'\"":
                quote = current
                cursor += 1
                continue
            if current in ",\n\r!":
                break
            cursor += 1
        if quote is not None:
            raise QEInputError(f"unterminated quoted value for {key} in &{namelist.name}")
        value_end = cursor
        while value_end > value_start and text[value_end - 1].isspace():
            value_end -= 1
        if value_start == value_end:
            raise QEInputError(f"missing value for {key} in &{namelist.name}")
        assignments.append(
            _Assignment(key, value_start, value_end, text[value_start:value_end])
        )
        index = max(cursor + 1, identifier.end())
    return tuple(assignments)


def _unique_assignment(text: str, namelist_name: str, key: str) -> _Assignment:
    namelist = _find_namelist(text, namelist_name)
    matches = [item for item in _scan_assignments(text, namelist) if item.key == key.lower()]
    if len(matches) != 1:
        raise QEInputError(
            f"expected exactly one {key} assignment in &{namelist_name.upper()}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _parse_integer_assignment(text: str, namelist: str, key: str) -> int:
    value = _unique_assignment(text, namelist, key).value.strip()
    if not re.fullmatch(r"[+-]?\d+", value):
        raise QEInputError(f"{key} in &{namelist.upper()} is not an integer: {value!r}")
    return int(value)


def _parse_float_assignment(text: str, namelist: str, key: str) -> float:
    assignment = _unique_assignment(text, namelist, key)
    return _as_float(assignment.value.strip(), f"{key} in &{namelist.upper()}")


def _find_card(
    text: str,
    name: str,
    *,
    required: bool = True,
    qualifier_required: bool = True,
) -> _Card | None:
    matches = list(
        re.finditer(
            rf"(?im)^[ \t]*{re.escape(name)}\b[^\r\n]*(?:\r?\n|$)",
            text,
        )
    )
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise QEInputError(f"expected exactly one {name} card, found {len(matches)}")
    match = matches[0]
    header = _strip_comment(match.group(0).rstrip("\r\n")).strip()
    qualifier = header[len(name) :].strip()
    if (qualifier.startswith("(") and qualifier.endswith(")")) or (
        qualifier.startswith("{") and qualifier.endswith("}")
    ):
        qualifier = qualifier[1:-1].strip()
    elif qualifier.startswith(("(", "{")) or qualifier.endswith((")", "}")):
        raise QEInputError(f"mismatched qualifier delimiters on {name} card")
    if (qualifier_required and not qualifier) or len(qualifier.split()) > 1:
        raise QEInputError(f"missing or ambiguous qualifier on {name} card")
    return _Card(name, qualifier.lower(), match.start(), match.end())


def _line_records(text: str, start: int) -> Iterable[tuple[int, int, str]]:
    cursor = start
    for line in text[start:].splitlines(keepends=True):
        end = cursor + len(line)
        yield cursor, end, line.rstrip("\r\n")
        cursor = end
    if cursor == start and start == len(text):
        return


def _parse_rows(
    text: str,
    card: _Card,
    count: int,
    row_parser,
) -> tuple[tuple[object, ...], tuple[int, int]]:
    if count <= 0:
        raise QEInputError(f"invalid expected row count for {card.name}: {count}")
    rows: list[object] = []
    row_start: int | None = None
    row_end: int | None = None
    iterator = iter(_line_records(text, card.header_end))
    for start, end, line in iterator:
        content = _strip_comment(line).strip()
        if not content and not rows:
            continue
        if not content:
            raise QEInputError(f"blank row inside {card.name} card")
        if row_start is None:
            row_start = start
        rows.append(row_parser(content, len(rows) + 1))
        row_end = end
        if len(rows) == count:
            break
    if len(rows) != count or row_start is None or row_end is None:
        raise QEInputError(
            f"{card.name} has {len(rows)} rows; expected exactly {count}"
        )

    for _, _, line in iterator:
        content = _strip_comment(line).strip()
        if not content:
            continue
        first = content.split()[0].upper()
        if first not in _CARD_NAMES and not first.startswith("&"):
            raise QEInputError(f"extra or ambiguous row after {card.name}: {content!r}")
        break
    return tuple(rows), (row_start, row_end)


def _species_row(content: str, row_number: int) -> AtomicSpecies:
    fields = content.split()
    if len(fields) != 3:
        raise QEInputError(
            f"ATOMIC_SPECIES row {row_number} must have label, mass, and pseudopotential"
        )
    mass = _as_float(fields[1], f"ATOMIC_SPECIES row {row_number} mass")
    if mass <= 0:
        raise QEInputError(f"non-positive mass in ATOMIC_SPECIES row {row_number}")
    return AtomicSpecies(fields[0], mass, fields[2])


def _position_row(content: str, row_number: int) -> AtomicPosition:
    fields = content.split()
    if len(fields) not in (4, 7):
        raise QEInputError(
            f"ATOMIC_POSITIONS row {row_number} must contain 4 or 7 fields"
        )
    coordinates = tuple(
        _as_float(fields[index], f"ATOMIC_POSITIONS row {row_number}")
        for index in (1, 2, 3)
    )
    constraints: tuple[int, ...] = ()
    if len(fields) == 7:
        if not all(re.fullmatch(r"[01]", value) for value in fields[4:]):
            raise QEInputError(
                f"ATOMIC_POSITIONS row {row_number} has invalid movement constraints"
            )
        constraints = tuple(int(value) for value in fields[4:])
    return AtomicPosition(
        fields[0],
        coordinates,  # type: ignore[arg-type]
        (fields[1], fields[2], fields[3]),
        constraints,
    )


def _cell_row(content: str, row_number: int) -> tuple[float, float, float]:
    fields = content.split()
    if len(fields) != 3:
        raise QEInputError(f"CELL_PARAMETERS row {row_number} must contain 3 values")
    return tuple(
        _as_float(value, f"CELL_PARAMETERS row {row_number}") for value in fields
    )  # type: ignore[return-value]


def _cell_row_with_tokens(
    content: str, row_number: int
) -> tuple[tuple[float, float, float], tuple[str, str, str]]:
    fields = content.split()
    values = _cell_row(content, row_number)
    return values, (fields[0], fields[1], fields[2])


def _k_point_row(content: str, row_number: int) -> AutomaticKPoints:
    fields = content.split()
    if len(fields) != 6 or not all(re.fullmatch(r"[+-]?\d+", item) for item in fields):
        raise QEInputError("automatic K_POINTS row must contain exactly six integers")
    values = tuple(int(item) for item in fields)
    if any(value <= 0 for value in values[:3]):
        raise QEInputError("automatic K_POINTS grid values must be positive")
    if any(value not in (0, 1) for value in values[3:]):
        raise QEInputError("automatic K_POINTS shifts must be 0 or 1")
    return AutomaticKPoints(values[:3], values[3:])  # type: ignore[arg-type]


def _cell_determinant(cell: Sequence[Sequence[float]]) -> float:
    a, b, c = cell
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def parse_qe_input(text: str) -> QEInput:
    """Parse and validate the strict QE unit-cell input used by this workflow."""

    if not isinstance(text, str) or not text.strip():
        raise QEInputError("QE input is empty")
    for name in ("CONTROL", "SYSTEM", "ELECTRONS", "IONS", "CELL"):
        _find_namelist(text, name)

    nat = _parse_integer_assignment(text, "SYSTEM", "nat")
    ntyp = _parse_integer_assignment(text, "SYSTEM", "ntyp")
    ibrav = _parse_integer_assignment(text, "SYSTEM", "ibrav")
    if nat <= 0 or ntyp <= 0:
        raise QEInputError(f"nat and ntyp must be positive, got {nat} and {ntyp}")
    if ibrav != 0:
        raise QEInputError("campaign inputs require ibrav = 0 and an explicit cell")
    ecutwfc = _parse_float_assignment(text, "SYSTEM", "ecutwfc")
    ecutrho = _parse_float_assignment(text, "SYSTEM", "ecutrho")
    if ecutwfc <= 0 or ecutrho < ecutwfc:
        raise QEInputError("invalid ecutwfc/ecutrho values")

    species_card = _find_card(text, "ATOMIC_SPECIES", qualifier_required=False)
    position_card = _find_card(text, "ATOMIC_POSITIONS")
    cell_card = _find_card(text, "CELL_PARAMETERS")
    k_card = _find_card(text, "K_POINTS")
    assert species_card and position_card and cell_card and k_card
    if position_card.qualifier != "crystal":
        raise QEInputError("campaign inputs require ATOMIC_POSITIONS crystal")
    if cell_card.qualifier not in ("angstrom", "ang"):
        raise QEInputError("campaign inputs require CELL_PARAMETERS angstrom")
    if k_card.qualifier != "automatic":
        raise QEInputError("campaign inputs require K_POINTS automatic")

    species_rows, _ = _parse_rows(text, species_card, ntyp, _species_row)
    position_rows, position_span = _parse_rows(text, position_card, nat, _position_row)
    cell_rows, cell_span = _parse_rows(text, cell_card, 3, _cell_row)
    k_rows, k_span = _parse_rows(text, k_card, 1, _k_point_row)
    species = tuple(species_rows)  # type: ignore[assignment]
    positions = tuple(position_rows)  # type: ignore[assignment]
    cell = tuple(cell_rows)  # type: ignore[assignment]
    k_points = k_rows[0]
    assert isinstance(k_points, AutomaticKPoints)

    labels = [item.label for item in species]
    if len(set(labels)) != len(labels):
        raise QEInputError("duplicate ATOMIC_SPECIES labels")
    position_labels = [item.label for item in positions]
    if set(position_labels) != set(labels):
        raise QEInputError(
            "ATOMIC_POSITIONS species do not match ATOMIC_SPECIES exactly"
        )
    if abs(_cell_determinant(cell)) < 1e-12:
        raise QEInputError("CELL_PARAMETERS is singular")

    return QEInput(
        text=text,
        nat=nat,
        ntyp=ntyp,
        ibrav=ibrav,
        ecutwfc_ry=ecutwfc,
        ecutrho_ry=ecutrho,
        atomic_species=species,  # type: ignore[arg-type]
        position_unit=position_card.qualifier,
        atomic_positions=positions,  # type: ignore[arg-type]
        cell_unit="angstrom",
        cell_parameters=cell,  # type: ignore[arg-type]
        k_points=k_points,
        position_rows_span=position_span,
        cell_rows_span=cell_span,
        k_point_row_span=k_span,
    )


def read_qe_input(path: str | Path) -> QEInput:
    return parse_qe_input(Path(path).read_text())


def _fortran_string(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise QEInputError(f"{name} must be a non-empty single-line string")
    return "'" + value.replace("'", "''") + "'"


def _fortran_float(value: float, name: str, *, scientific: bool = False) -> str:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise QEInputError(f"{name} must be finite and positive")
    if scientific:
        return f"{number:.12e}".replace("e", "d")
    return f"{number:.15g}"


def _fortran_bool(value: bool) -> str:
    if not isinstance(value, bool):
        raise QEInputError("Fortran logical settings must be bool values")
    return ".true." if value else ".false."


def _set_namelist_values(
    text: str,
    namelist_name: str,
    updates: Mapping[str, str],
) -> str:
    namelist = _find_namelist(text, namelist_name)
    assignments = _scan_assignments(text, namelist)
    edits: list[tuple[int, int, str]] = []
    missing: list[tuple[str, str]] = []
    for key, value in updates.items():
        matches = [item for item in assignments if item.key == key.lower()]
        if len(matches) > 1:
            raise QEInputError(
                f"ambiguous duplicate {key} assignments in &{namelist_name.upper()}"
            )
        if matches:
            edits.append((matches[0].value_start, matches[0].value_end, value))
        else:
            missing.append((key, value))
    if missing:
        insertion = "".join(f"  {key} = {value},\n" for key, value in missing)
        edits.append((namelist.close_start, namelist.close_start, insertion))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _validate_kmesh(
    kmesh: Sequence[int], kshift: Sequence[int]
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if len(kmesh) != 3 or len(kshift) != 3:
        raise QEInputError("kmesh and kshift must each contain exactly three integers")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in (*kmesh, *kshift)):
        raise QEInputError("kmesh and kshift values must be integers")
    grid = tuple(kmesh)
    shift = tuple(kshift)
    if any(value <= 0 for value in grid):
        raise QEInputError("kmesh values must be positive")
    if any(value not in (0, 1) for value in shift):
        raise QEInputError("kshift values must be 0 or 1")
    return grid, shift  # type: ignore[return-value]


def _replace_k_points(
    text: str, kmesh: Sequence[int], kshift: Sequence[int]
) -> str:
    parsed = parse_qe_input(text)
    grid, shift = _validate_kmesh(kmesh, kshift)
    start, end = parsed.k_point_row_span
    line_ending = "\r\n" if "\r\n" in text[start:end] else "\n"
    replacement = "  " + " ".join(str(value) for value in (*grid, *shift)) + line_ending
    return text[:start] + replacement + text[end:]


def _source_is_fixed_cell_safe(parsed: QEInput) -> None:
    cell_namelist = _find_namelist(parsed.text, "CELL")
    cell_dynamics = [
        item for item in _scan_assignments(parsed.text, cell_namelist)
        if item.key == "cell_dynamics"
    ]
    if len(cell_dynamics) > 1:
        raise QEInputError("ambiguous duplicate cell_dynamics assignments in &CELL")
    if cell_dynamics:
        value = cell_dynamics[0].value.strip().strip("'\"").lower()
        if value != "none":
            raise QEInputError(
                "source contains active cell_dynamics; refusing fixed-cell preparation"
            )


def build_fixed_cell_relax_input(
    source_text: str,
    *,
    calculation: str = "relax",
    outdir: str,
    prefix: str,
    pseudo_dir: str,
    disk_io: str = "low",
    tprnfor: bool = True,
    conv_thr: float,
    forc_conv_thr: float,
    ion_dynamics: str = "bfgs",
    ecutwfc: float,
    ecutrho: float,
    kmesh: Sequence[int],
    kshift: Sequence[int] = (0, 0, 0),
    etot_conv_thr: float | None = None,
    tstress: bool = True,
    electron_maxstep: int | None = None,
    mixing_beta: float | None = None,
) -> str:
    """Return a fixed-cell, phonon-grade ionic-relaxation QE input."""

    source = parse_qe_input(source_text)
    _source_is_fixed_cell_safe(source)
    if calculation.lower() != "relax":
        raise QEInputError("fixed-cell campaign preparation requires calculation='relax'")
    if ion_dynamics.lower() != "bfgs":
        raise QEInputError("phonon-grade relax preparation requires ion_dynamics='bfgs'")
    if tprnfor is not True:
        raise QEInputError("phonon-grade relax preparation requires tprnfor=True")
    ecutwfc_value = float(ecutwfc)
    ecutrho_value = float(ecutrho)
    if ecutrho_value < ecutwfc_value:
        raise QEInputError("ecutrho must be greater than or equal to ecutwfc")

    control_updates = {
        "calculation": _fortran_string(calculation.lower(), "calculation"),
        "outdir": _fortran_string(outdir, "outdir"),
        "prefix": _fortran_string(prefix, "prefix"),
        "pseudo_dir": _fortran_string(pseudo_dir, "pseudo_dir"),
        "disk_io": _fortran_string(disk_io, "disk_io"),
        "tprnfor": _fortran_bool(tprnfor),
        "tstress": _fortran_bool(tstress),
        "forc_conv_thr": _fortran_float(
            forc_conv_thr, "forc_conv_thr", scientific=True
        ),
    }
    if etot_conv_thr is not None:
        control_updates["etot_conv_thr"] = _fortran_float(
            etot_conv_thr, "etot_conv_thr", scientific=True
        )
    result = _set_namelist_values(
        source_text,
        "CONTROL",
        control_updates,
    )
    electron_updates = {
        "conv_thr": _fortran_float(conv_thr, "conv_thr", scientific=True)
    }
    if electron_maxstep is not None:
        if (
            isinstance(electron_maxstep, bool)
            or not isinstance(electron_maxstep, int)
            or electron_maxstep <= 0
        ):
            raise QEInputError("electron_maxstep must be a positive integer")
        electron_updates["electron_maxstep"] = str(electron_maxstep)
    if mixing_beta is not None:
        beta = float(mixing_beta)
        if not math.isfinite(beta) or not 0 < beta <= 1:
            raise QEInputError("mixing_beta must be in (0, 1]")
        electron_updates["mixing_beta"] = _fortran_float(beta, "mixing_beta")
    result = _set_namelist_values(
        result,
        "ELECTRONS",
        electron_updates,
    )
    result = _set_namelist_values(
        result,
        "IONS",
        {"ion_dynamics": _fortran_string(ion_dynamics.lower(), "ion_dynamics")},
    )
    result = _set_namelist_values(
        result,
        "SYSTEM",
        {
            "ecutwfc": _fortran_float(ecutwfc_value, "ecutwfc"),
            "ecutrho": _fortran_float(ecutrho_value, "ecutrho"),
        },
    )
    result = _replace_k_points(result, kmesh, kshift)

    prepared = parse_qe_input(result)
    if prepared.cell_parameters != source.cell_parameters:
        raise QEInputError("internal error: fixed-cell preparation changed CELL_PARAMETERS")
    if prepared.atomic_positions != source.atomic_positions:
        raise QEInputError("internal error: relax preparation changed atomic positions")
    return result


def _parse_final_block_positions(block: str) -> tuple[AtomicPosition, ...]:
    card = _find_card(block, "ATOMIC_POSITIONS")
    assert card is not None
    if card.qualifier != "crystal":
        raise QEInputError("final coordinates require ATOMIC_POSITIONS crystal")
    positions: list[AtomicPosition] = []
    for _, _, line in _line_records(block, card.header_end):
        content = _strip_comment(line).strip()
        if not content:
            if positions:
                break
            continue
        first = content.split()[0].upper()
        if first in _CARD_NAMES:
            break
        positions.append(_position_row(content, len(positions) + 1))
    if not positions:
        raise QEInputError("final coordinate block has no atomic positions")
    return tuple(positions)


def _parse_optional_final_cell(
    block: str,
) -> tuple[
    str | None,
    tuple[tuple[float, float, float], ...] | None,
    tuple[tuple[str, str, str], ...] | None,
]:
    card = _find_card(block, "CELL_PARAMETERS", required=False)
    if card is None:
        return None, None, None
    if card.qualifier not in ("angstrom", "ang"):
        raise QEInputError("final coordinates require CELL_PARAMETERS angstrom when present")
    rows, _ = _parse_rows(block, card, 3, _cell_row_with_tokens)
    cell = tuple(row[0] for row in rows)
    tokens = tuple(row[1] for row in rows)
    if abs(_cell_determinant(cell)) < 1e-12:
        raise QEInputError("final CELL_PARAMETERS is singular")
    return "angstrom", cell, tokens  # type: ignore[return-value]


def extract_final_coordinates(
    output_text: str, *, expected_atoms: int | None = None
) -> FinalCoordinates:
    """Extract the last complete, unambiguous QE final-coordinate block."""

    if not isinstance(output_text, str) or not output_text.strip():
        raise QEInputError("QE output is empty")
    pairs: list[tuple[int, int]] = []
    begin_end: int | None = None
    for marker in _FINAL_MARKER.finditer(output_text):
        label = marker.group(1).lower()
        if label.startswith("begin"):
            if begin_end is not None:
                raise QEInputError("nested Begin final coordinates markers")
            begin_end = marker.end()
        else:
            if begin_end is None:
                raise QEInputError("End final coordinates without matching Begin")
            pairs.append((begin_end, marker.start()))
            begin_end = None
    if begin_end is not None:
        raise QEInputError("trailing incomplete final-coordinate block")
    if not pairs:
        raise QEInputError("no complete Begin/End final coordinates block")

    block = output_text[pairs[-1][0] : pairs[-1][1]]
    positions = _parse_final_block_positions(block)
    if expected_atoms is not None and len(positions) != expected_atoms:
        raise QEInputError(
            f"final coordinate atom count mismatch: {len(positions)} vs {expected_atoms}"
        )
    cell_unit, cell, cell_tokens = _parse_optional_final_cell(block)
    return FinalCoordinates("crystal", positions, cell_unit, cell, cell_tokens)


def read_final_coordinates(
    path: str | Path, *, expected_atoms: int | None = None
) -> FinalCoordinates:
    return extract_final_coordinates(
        Path(path).read_text(errors="replace"), expected_atoms=expected_atoms
    )


def _cells_match(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    *,
    absolute_tolerance: float = 1e-8,
) -> bool:
    return all(
        abs(float(left_value) - float(right_value)) <= absolute_tolerance
        for left_row, right_row in zip(left, right)
        for left_value, right_value in zip(left_row, right_row)
    )


def _tokens_for_values(
    values: Sequence[float],
    tokens: Sequence[str] | None,
    context: str,
) -> tuple[str, str, str]:
    if len(values) != 3 or not all(math.isfinite(float(value)) for value in values):
        raise QEInputError(f"{context} must contain exactly three finite values")
    if not tokens:
        return tuple(f"{float(value):.16g}" for value in values)  # type: ignore[return-value]
    if len(tokens) != 3:
        raise QEInputError(f"{context} token record must contain exactly three values")
    parsed_tokens = tuple(
        _as_float(str(token), f"{context} token") for token in tokens
    )
    if not all(
        math.isclose(float(value), parsed, rel_tol=1e-13, abs_tol=1e-14)
        for value, parsed in zip(values, parsed_tokens)
    ):
        raise QEInputError(f"{context} numeric values and source tokens disagree")
    return tuple(str(token) for token in tokens)  # type: ignore[return-value]


def replace_qe_geometry(
    source_text: str,
    final: FinalCoordinates,
    *,
    require_cell: bool = True,
) -> str:
    """Replace a unit cell's positions and, when supplied, lattice vectors.

    This is the auditable bridge both for archived ``vc-relax`` coordinates
    and for a separately symmetry-standardized geometry.  Unlike the
    tight-relax-to-pristine path, a changed lattice is intentionally allowed.
    """

    source = parse_qe_input(source_text)
    if final.position_unit.lower() != "crystal":
        raise QEInputError("replacement geometry requires crystal positions")
    if len(final.atomic_positions) != source.nat:
        raise QEInputError(
            f"final coordinate atom count mismatch: {len(final.atomic_positions)} vs {source.nat}"
        )
    source_labels = tuple(item.label for item in source.atomic_positions)
    final_labels = tuple(item.label for item in final.atomic_positions)
    if final_labels != source_labels:
        raise QEInputError("final coordinate atom ordering/species differs from source input")
    if require_cell and final.cell_parameters is None:
        raise QEInputError("replacement geometry is missing CELL_PARAMETERS")
    if final.cell_parameters is not None:
        if final.cell_unit is None or final.cell_unit.lower() not in ("angstrom", "ang"):
            raise QEInputError("replacement geometry requires an Angstrom cell")
        if len(final.cell_parameters) != 3 or any(
            len(row) != 3 for row in final.cell_parameters
        ):
            raise QEInputError("replacement CELL_PARAMETERS must be a 3x3 matrix")
        if abs(_cell_determinant(final.cell_parameters)) < 1e-12:
            raise QEInputError("replacement CELL_PARAMETERS is singular")

    position_start, position_end = source.position_rows_span
    position_eol = "\r\n" if "\r\n" in source.text[position_start:position_end] else "\n"
    position_lines: list[str] = []
    for old, new in zip(source.atomic_positions, final.atomic_positions):
        coordinate_tokens = _tokens_for_values(
            new.coordinates, new.coordinate_tokens, f"{new.label} coordinates"
        )
        fields = [new.label, *coordinate_tokens]
        if old.constraints:
            fields.extend(str(value) for value in old.constraints)
        position_lines.append("  " + " ".join(fields) + position_eol)

    edits: list[tuple[int, int, str]] = [
        (position_start, position_end, "".join(position_lines))
    ]
    if final.cell_parameters is not None:
        cell_start, cell_end = source.cell_rows_span
        cell_eol = "\r\n" if "\r\n" in source.text[cell_start:cell_end] else "\n"
        supplied_tokens = final.cell_parameter_tokens
        if supplied_tokens is not None and len(supplied_tokens) != 3:
            raise QEInputError("CELL_PARAMETERS token record must have three rows")
        cell_lines: list[str] = []
        for index, row in enumerate(final.cell_parameters):
            row_tokens = None if supplied_tokens is None else supplied_tokens[index]
            rendered = _tokens_for_values(row, row_tokens, f"CELL_PARAMETERS row {index + 1}")
            cell_lines.append("  " + " ".join(rendered) + cell_eol)
        edits.append((cell_start, cell_end, "".join(cell_lines)))

    result = source.text
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    replaced = parse_qe_input(result)
    if tuple(item.label for item in replaced.atomic_positions) != source_labels:
        raise QEInputError("internal error: geometry replacement changed atom ordering")
    if not all(
        math.isclose(old, new, rel_tol=1e-13, abs_tol=1e-14)
        for parsed_position, final_position in zip(
            replaced.atomic_positions, final.atomic_positions
        )
        for old, new in zip(parsed_position.coordinates, final_position.coordinates)
    ):
        raise QEInputError("internal error: replacement atomic coordinates changed")
    if final.cell_parameters is not None and not _cells_match(
        replaced.cell_parameters,
        final.cell_parameters,
        absolute_tolerance=1e-12,
    ):
        raise QEInputError("internal error: replacement CELL_PARAMETERS changed")
    return result


def replace_geometry_from_final_coordinates(
    source_text: str,
    output_text: str,
    expected_atoms: int,
    require_cell: bool = True,
) -> str:
    """Inject the last high-precision QE final geometry into a unit-cell input."""

    source = parse_qe_input(source_text)
    if expected_atoms != source.nat:
        raise QEInputError(
            f"expected_atoms {expected_atoms} does not match source nat {source.nat}"
        )
    final = extract_final_coordinates(output_text, expected_atoms=expected_atoms)
    return replace_qe_geometry(source_text, final, require_cell=require_cell)


def build_pristine_scf_input(
    source_text: str,
    relax_output_text: str,
    *,
    calculation: str = "scf",
    outdir: str,
    prefix: str,
    pseudo_dir: str,
    disk_io: str = "low",
    tprnfor: bool = True,
    conv_thr: float,
    ecutwfc: float,
    ecutrho: float,
    kmesh: Sequence[int],
    kshift: Sequence[int] = (0, 0, 0),
    nosym: bool = True,
    noinv: bool = True,
) -> str:
    """Build a production-matched pristine SCF from the last relaxed positions."""

    source = parse_qe_input(source_text)
    if calculation.lower() != "scf":
        raise QEInputError("pristine force preparation requires calculation='scf'")
    if tprnfor is not True:
        raise QEInputError("pristine force preparation requires tprnfor=True")
    ecutwfc_value = float(ecutwfc)
    ecutrho_value = float(ecutrho)
    if ecutrho_value < ecutwfc_value:
        raise QEInputError("ecutrho must be greater than or equal to ecutwfc")
    final = extract_final_coordinates(relax_output_text, expected_atoms=source.nat)
    if final.cell_parameters is not None and not _cells_match(
        source.cell_parameters, final.cell_parameters
    ):
        raise QEInputError("fixed-cell relax output CELL_PARAMETERS differs from source")
    result = replace_qe_geometry(source_text, final, require_cell=False)
    result = _set_namelist_values(
        result,
        "CONTROL",
        {
            "calculation": _fortran_string(calculation.lower(), "calculation"),
            "outdir": _fortran_string(outdir, "outdir"),
            "prefix": _fortran_string(prefix, "prefix"),
            "pseudo_dir": _fortran_string(pseudo_dir, "pseudo_dir"),
            "disk_io": _fortran_string(disk_io, "disk_io"),
            "tprnfor": _fortran_bool(tprnfor),
        },
    )
    result = _set_namelist_values(
        result,
        "ELECTRONS",
        {"conv_thr": _fortran_float(conv_thr, "conv_thr", scientific=True)},
    )
    result = _set_namelist_values(
        result,
        "SYSTEM",
        {
            "ecutwfc": _fortran_float(ecutwfc_value, "ecutwfc"),
            "ecutrho": _fortran_float(ecutrho_value, "ecutrho"),
            "nosym": _fortran_bool(nosym),
            "noinv": _fortran_bool(noinv),
        },
    )
    result = _replace_k_points(result, kmesh, kshift)

    prepared = parse_qe_input(result)
    if prepared.cell_parameters != source.cell_parameters:
        raise QEInputError("internal error: pristine preparation changed CELL_PARAMETERS")
    if tuple(item.label for item in prepared.atomic_positions) != tuple(
        item.label for item in source.atomic_positions
    ):
        raise QEInputError("internal error: pristine preparation changed atom ordering")
    return result


__all__ = [
    "AtomicPosition",
    "AtomicSpecies",
    "AutomaticKPoints",
    "FinalCoordinates",
    "QEInput",
    "QEInputError",
    "build_fixed_cell_relax_input",
    "build_pristine_scf_input",
    "extract_final_coordinates",
    "parse_qe_input",
    "read_final_coordinates",
    "read_qe_input",
    "replace_geometry_from_final_coordinates",
    "replace_qe_geometry",
]

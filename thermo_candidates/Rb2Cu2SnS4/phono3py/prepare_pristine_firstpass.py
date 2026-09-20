#!/usr/bin/env python3
"""Build the independent setting-matched pristine SCF from FIRE output."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def block(text: str, start: str, lines: int) -> str:
    match = re.search(
        rf"^{re.escape(start)}\s*$\n(?P<body>(?:.*\n){{{lines}}})",
        text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(f"missing {start} block with {lines} rows")
    return match.group("body")


def final_positions(text: str) -> str:
    starts = list(re.finditer(r"^\s*Begin final coordinates\s*$", text, re.MULTILINE))
    ends = list(re.finditer(r"^\s*End final coordinates\s*$", text, re.MULTILINE))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() <= starts[0].end():
        raise ValueError("expected exactly one 18-atom final-coordinate block")
    final_block = text[starts[0].end():ends[0].start()]
    match = re.search(
        r"^ATOMIC_POSITIONS\s*\(crystal\)\s*$\n(?P<body>(?:.*\n){18})",
        final_block,
        re.MULTILINE,
    )
    if not match:
        raise ValueError("final-coordinate block lacks 18 crystal-coordinate rows")
    return match.group("body")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fire-input", type=Path, required=True)
    parser.add_argument("--fire-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pseudo-dir", type=Path, required=True)
    args = parser.parse_args()

    fire_input = args.fire_input.read_text(errors="strict")
    fire_output = args.fire_output.read_text(errors="replace")
    species = block(fire_input, "ATOMIC_SPECIES", 4)
    positions = final_positions(fire_output)
    kpoints = block(fire_input, "K_POINTS automatic", 1)
    cell = block(fire_input, "CELL_PARAMETERS angstrom", 3)
    pseudo_dir = args.pseudo_dir.resolve(strict=True)

    text = f"""&CONTROL
  calculation = 'scf',
  disk_io = 'low',
  outdir = './tmp',
  prefix = 'Rb2Cu2SnS4_pristine_firstpass',
  pseudo_dir = '{pseudo_dir}',
  restart_mode = 'from_scratch',
  verbosity = 'high',
  tprnfor = .true.,
  tstress = .true.,
/
&SYSTEM
  ecutrho = 800,
  ecutwfc = 100,
  occupations = 'fixed',
  ibrav = 0,
  nat = 18,
  ntyp = 4,
  nosym = .true.,
  noinv = .true.,
/
&ELECTRONS
  conv_thr = 1.000000000000d-10,
  diagonalization = 'david',
  electron_maxstep = 300,
  mixing_beta = 0.3,
  startingpot = 'atomic',
  startingwfc = 'atomic+random',
  scf_must_converge = .true.,
/
ATOMIC_SPECIES
{species}ATOMIC_POSITIONS (crystal)
{positions}K_POINTS automatic
{kpoints}CELL_PARAMETERS angstrom
{cell}"""
    args.output.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

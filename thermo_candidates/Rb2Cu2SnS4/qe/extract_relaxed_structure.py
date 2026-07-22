#!/usr/bin/env python3
"""Extract the last QE vc-relax frame into a CIF file."""

from pathlib import Path

from ase.io import read
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.cif import CifWriter


QE_DIR = Path(__file__).resolve().parent
OUTPUT = QE_DIR.parent / "logs" / "Rb2Cu2SnS4.relax.out"
RELAXED_CIF = QE_DIR.parent / "structures" / "Rb2Cu2SnS4.relaxed.cif"


def main() -> None:
    frames = read(OUTPUT, index=":", format="espresso-out")
    if not frames:
        raise SystemExit(f"No structures found in {OUTPUT}")
    structure = AseAtomsAdaptor.get_structure(frames[-1])
    if structure.composition.reduced_formula != "Rb2Cu2SnS4":
        raise ValueError(f"Unexpected formula: {structure.composition.reduced_formula}")
    CifWriter(structure, symprec=0.01, refine_struct=False).write_file(
        RELAXED_CIF
    )
    print(f"Extracted {len(frames)} frames")
    print(f"Wrote {RELAXED_CIF}")


if __name__ == "__main__":
    main()

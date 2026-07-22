#!/usr/bin/env python3
"""Prepare the dense NSCF input used by BoltzTraP2 (SrZrS3).

Sizing:
  - 160 electrons -> 80 occupied bands (final SCF log); nbnd = 108 gives
    28 empty bands (~35% headroom, same ratio as SrCu2SnS4's 105 -> 140).
  - mesh 20x10x6 -> k-spacing 0.082/0.073/0.075 A^-1 on the relaxed
    3.8385 x 8.6412 x 14.0030 A cell, matching the spacing standard of the
    SrCu2SnS4 dense NSCF (12x12x6 -> 0.082/0.082/0.067 A^-1).
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


QE_DIR = Path(__file__).resolve().parent
CANDIDATE = QE_DIR.parent
CIF = CANDIDATE / "structures" / "SrZrS3.relaxed.cif"
OUTPUT = QE_DIR / "02_nscf" / "SrZrS3.nscf.in"
PSEUDOS = {
    "Sr": "Sr_pbe_v1.uspp.F.UPF",
    "Zr": "Zr_pbe_v1.uspp.F.UPF",
    "S": "s_pbe_v1.4.uspp.F.UPF",
}


def main() -> None:
    structure = Structure.from_file(CIF)
    pseudo_dir = os.environ.get(
        "QE_PSEUDO_SSSP_PBE_PRECISION",
        str(
            Path.home()
            / "scientific-tools/pseudopotentials/SSSP/1.3.0/PBE/precision"
        ),
    )
    pw = PWInput(
        structure,
        pseudo=PSEUDOS,
        control={
            "calculation": "nscf",
            "prefix": "SrZrS3",
            "outdir": "./tmp/final",
            "pseudo_dir": pseudo_dir,
            "verbosity": "high",
            "disk_io": "nowf",
        },
        system={
            "ecutwfc": 50,
            "ecutrho": 400,
            "occupations": "fixed",
            "nbnd": 108,
        },
        electrons={
            "conv_thr": 1e-8,
            "diagonalization": "david",
            "diago_full_acc": True,
            "startingpot": "file",
        },
        kpoints_mode="automatic",
        kpoints_grid=(20, 10, 6),
        kpoints_shift=(0, 0, 0),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pw.write_file(OUTPUT)
    print(f"Prepared {OUTPUT.relative_to(QE_DIR)}")


if __name__ == "__main__":
    main()

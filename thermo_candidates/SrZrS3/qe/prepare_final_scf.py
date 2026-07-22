#!/usr/bin/env python3
"""Prepare the final SCF input from the relaxed SrZrS3 structure.

Converged settings from this material's own tests: 50/400 Ry, 8x4x2 mesh.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


QE_DIR = Path(__file__).resolve().parent
CANDIDATE = QE_DIR.parent
CIF = CANDIDATE / "structures" / "SrZrS3.relaxed.cif"
OUTPUT = QE_DIR / "01_scf" / "SrZrS3.scf.in"
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
            "calculation": "scf",
            "restart_mode": "from_scratch",
            "prefix": "SrZrS3",
            "outdir": "./tmp/final",
            "pseudo_dir": pseudo_dir,
            "verbosity": "high",
            "disk_io": "medium",
        },
        system={
            "ecutwfc": 50,
            "ecutrho": 400,
            "occupations": "fixed",
        },
        electrons={
            "conv_thr": 1e-8,
            "electron_maxstep": 200,
            "mixing_beta": 0.3,
            "diagonalization": "david",
        },
        kpoints_mode="automatic",
        kpoints_grid=(8, 4, 2),
        kpoints_shift=(0, 0, 0),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pw.write_file(OUTPUT)
    print(f"Prepared {OUTPUT.relative_to(QE_DIR)}")


if __name__ == "__main__":
    main()

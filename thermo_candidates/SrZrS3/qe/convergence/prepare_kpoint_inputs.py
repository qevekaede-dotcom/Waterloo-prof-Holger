#!/usr/bin/env python3
"""Prepare fixed-structure SCF inputs for the SrZrS3 k-point test.

Runs at the cutoff selected by the cutoff test (50/400 Ry, 0.160 meV/atom from
the 60 Ry reference, pressure on the 3.4-3.55 kbar plateau).

Meshes are scaled to the 3.84 x 8.59 x 14.00 A Pnma cell (reciprocal spans
~3.6 : 1.6 : 1), from coarse to dense:
  4x2x1  (~0.41/0.37/0.45 A^-1 spacing)
  6x3x2  (~0.27/0.24/0.22 A^-1)
  8x4x2  (~0.20/0.18/0.22 A^-1)
  10x5x3 (~0.16/0.15/0.15 A^-1, reference)
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
CIF = CANDIDATE / "structures" / "SrZrS3.cif"
ECUTWFC = 50
ECUTRHO = 400
MESHES = ((4, 2, 1), (6, 3, 2), (8, 4, 2), (10, 5, 3))
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
    input_dir = HERE / "kpoints" / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    for mesh in MESHES:
        tag = "x".join(str(n) for n in mesh)
        pw = PWInput(
            structure,
            pseudo=PSEUDOS,
            control={
                "calculation": "scf",
                "prefix": f"SrZrS3_k_{tag}",
                "outdir": f"./tmp/k_{tag}",
                "pseudo_dir": pseudo_dir,
                "verbosity": "high",
                "tstress": True,
                "disk_io": "low",
            },
            system={
                "ecutwfc": ECUTWFC,
                "ecutrho": ECUTRHO,
                "occupations": "fixed",
            },
            electrons={
                "conv_thr": 1e-8,
                "electron_maxstep": 200,
                "mixing_beta": 0.3,
            },
            kpoints_mode="automatic",
            kpoints_grid=mesh,
            kpoints_shift=(0, 0, 0),
        )
        output = input_dir / f"k_{tag}.in"
        pw.write_file(output)
        print(f"Prepared {output.relative_to(HERE)}")


if __name__ == "__main__":
    main()

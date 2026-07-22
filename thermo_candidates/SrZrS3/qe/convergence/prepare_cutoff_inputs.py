#!/usr/bin/env python3
"""Prepare fixed-structure SCF inputs for the SrZrS3 plane-wave cutoff test.

Design (this material's own test; nothing reused from SrCu2SnS4 as final):
  - structure: experimentally observed mp-558760 needle phase (Pnma, 20 atoms,
    a=3.84, b=8.59, c=14.00 A). Do not substitute the mp-5193 polymorph.
  - SSSP 1.3.0 PBE precision suggests 40/320 Ry for {Sr, Zr, S}; all three
    pseudos are ultrasoft, so ecutrho = 8 x ecutwfc throughout.
  - cutoffs tested: 30-60 Ry with the 60 Ry run as the reference, mirroring the
    SrCu2SnS4 protocol (band around the SSSP suggestion plus headroom above).
  - fixed 4x2x1 Monkhorst-Pack mesh (k-spacing 0.37-0.45 A^-1 on this cell,
    comparable to the 2x2x2 used for the SrCu2SnS4 cutoff test); the k error
    cancels in the energy differences between cutoffs.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
CIF = CANDIDATE / "structures" / "SrZrS3.cif"
CUTOFFS_RY = (30, 35, 40, 45, 50, 60)
KMESH = (4, 2, 1)
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
    input_dir = HERE / "cutoff" / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    for cutoff in CUTOFFS_RY:
        pw = PWInput(
            structure,
            pseudo=PSEUDOS,
            control={
                "calculation": "scf",
                "prefix": f"SrZrS3_ecut_{cutoff}",
                "outdir": f"./tmp/ecut_{cutoff}",
                "pseudo_dir": pseudo_dir,
                "verbosity": "high",
                "tstress": True,
                "disk_io": "low",
            },
            system={
                "ecutwfc": cutoff,
                "ecutrho": cutoff * 8,
                "occupations": "fixed",
            },
            electrons={
                "conv_thr": 1e-8,
                "electron_maxstep": 200,
                "mixing_beta": 0.3,
            },
            kpoints_mode="automatic",
            kpoints_grid=KMESH,
            kpoints_shift=(0, 0, 0),
        )
        output = input_dir / f"ecut_{cutoff}.in"
        pw.write_file(output)
        print(f"Prepared {output.relative_to(HERE)}")


if __name__ == "__main__":
    main()

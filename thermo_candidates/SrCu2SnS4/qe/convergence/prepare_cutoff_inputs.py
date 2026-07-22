#!/usr/bin/env python3
"""Prepare fixed-structure SCF inputs for the plane-wave cutoff test."""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
CIF = CANDIDATE / "structures" / "SrCu2SnS4.cif"
CUTOFFS_RY = (50, 60, 70, 80, 90, 100)
PSEUDOS = {
    "Sr": "Sr_pbe_v1.uspp.F.UPF",
    "Cu": "Cu.paw.z_11.ld1.psl.v1.0.0-low.upf",
    "Sn": "Sn_pbe_v1.uspp.F.UPF",
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
                "prefix": f"SrCu2SnS4_ecut_{cutoff}",
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
            kpoints_grid=(2, 2, 2),
            kpoints_shift=(0, 0, 0),
        )
        output = input_dir / f"ecut_{cutoff}.in"
        pw.write_file(output)
        print(f"Prepared {output.relative_to(HERE)}")


if __name__ == "__main__":
    main()

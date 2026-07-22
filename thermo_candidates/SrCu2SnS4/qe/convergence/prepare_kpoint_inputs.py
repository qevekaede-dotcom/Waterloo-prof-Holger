#!/usr/bin/env python3
"""Prepare fixed-structure SCF inputs for the k-point convergence test."""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
CIF = CANDIDATE / "structures" / "SrCu2SnS4.cif"
K_MESHES = ((2, 2, 1), (3, 3, 2), (4, 4, 2), (5, 5, 3))
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
    input_dir = HERE / "kpoints" / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    for mesh in K_MESHES:
        label = "x".join(str(value) for value in mesh)
        pw = PWInput(
            structure,
            pseudo=PSEUDOS,
            control={
                "calculation": "scf",
                "prefix": f"SrCu2SnS4_k_{label}",
                "outdir": f"./tmp/k_{label}",
                "pseudo_dir": pseudo_dir,
                "verbosity": "high",
                "tstress": True,
                "disk_io": "low",
            },
            system={
                "ecutwfc": 90,
                "ecutrho": 720,
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
        output = input_dir / f"k_{label}.in"
        pw.write_file(output)
        print(f"Prepared {output.relative_to(HERE)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prepare fixed-structure SCF inputs for the Rb2Cu2SnS4 k-point test.

Runs at the cutoff selected by the cutoff test (90/720 Ry, 0.0896 meV/atom
from the 100 Ry reference, pressure on the 2.5-2.7 kbar plateau).

Meshes are scaled to the primitive-cell reciprocal lattice
(0.70/1.23/1.26 A^-1, ratios ~1 : 1.76 : 1.81), coarse to dense:
  2x4x4  (~0.35/0.31/0.32 A^-1 spacing; the cutoff-test mesh)
  3x5x5  (~0.23/0.25/0.25 A^-1)
  4x7x7  (~0.18/0.18/0.18 A^-1)
  5x9x9  (~0.14/0.14/0.14 A^-1, reference)
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
CIF = CANDIDATE / "structures" / "Rb2Cu2SnS4.cif"
ECUTWFC = 90
ECUTRHO = 720
MESHES = ((2, 4, 4), (3, 5, 5), (4, 7, 7), (5, 9, 9))
PSEUDOS = {
    "Rb": "Rb_ONCV_PBE-1.0.oncvpsp.upf",
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

    for mesh in MESHES:
        tag = "x".join(str(n) for n in mesh)
        pw = PWInput(
            structure,
            pseudo=PSEUDOS,
            control={
                "calculation": "scf",
                "prefix": f"Rb2Cu2SnS4_k_{tag}",
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

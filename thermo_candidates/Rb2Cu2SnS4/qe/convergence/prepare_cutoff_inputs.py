#!/usr/bin/env python3
"""Prepare fixed-structure SCF inputs for the Rb2Cu2SnS4 plane-wave cutoff test.

Design (this material's own test; nothing reused from other materials):
  - structure: experimentally observed mp-18006 (Ibam), 18-atom primitive
    cell (Rb4 Cu4 Sn2 S8), reciprocal lattice lengths 0.70/1.23/1.26 A^-1.
  - pseudos are mixed (Rb norm-conserving ONCV, Cu PAW, Sn/S ultrasoft);
    the Cu PAW and ultrasofts require ecutrho = 8 x ecutwfc.
  - SSSP suggests 90/720 Ry (Cu-driven, as for SrCu2SnS4); cutoffs tested
    50-100 Ry with the 100 Ry run as reference, mirroring the SrCu2SnS4
    protocol.
  - fixed 2x4x4 Monkhorst-Pack mesh (k-spacing 0.35/0.31/0.32 A^-1, balanced
    for this cell shape); the k error cancels in differences between cutoffs.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parents[1]
CIF = CANDIDATE / "structures" / "Rb2Cu2SnS4.cif"
CUTOFFS_RY = (50, 60, 70, 80, 90, 100)
KMESH = (2, 4, 4)
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
    input_dir = HERE / "cutoff" / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)

    for cutoff in CUTOFFS_RY:
        pw = PWInput(
            structure,
            pseudo=PSEUDOS,
            control={
                "calculation": "scf",
                "prefix": f"Rb2Cu2SnS4_ecut_{cutoff}",
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

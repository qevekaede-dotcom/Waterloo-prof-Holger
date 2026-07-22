#!/usr/bin/env python3
"""Prepare the converged-parameter vc-relax input for SrZrS3.

Converged settings from this material's own tests (qe/convergence/):
  ecutwfc/ecutrho = 50/400 Ry   (0.160 meV/atom vs the 60 Ry reference)
  relax k mesh    = 6x3x2       (0.286 meV/atom vs the 10x5x3 reference)
Thresholds mirror the SrCu2SnS4 protocol.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


QE_DIR = Path(__file__).resolve().parent
CANDIDATE = QE_DIR.parent
CIF = CANDIDATE / "structures" / "SrZrS3.cif"
OUTPUT = QE_DIR / "00_relax" / "SrZrS3.relax.in"
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
            "calculation": "vc-relax",
            "restart_mode": "from_scratch",
            "prefix": "SrZrS3_relax",
            "outdir": "./tmp/relax",
            "pseudo_dir": pseudo_dir,
            "verbosity": "high",
            "nstep": 100,
            "etot_conv_thr": 1e-5,
            "forc_conv_thr": 1e-3,
            "tstress": True,
            "tprnfor": True,
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
        ions={"ion_dynamics": "bfgs"},
        cell={
            "cell_dynamics": "bfgs",
            "press_conv_thr": 0.5,
            "cell_dofree": "all",
        },
        kpoints_mode="automatic",
        kpoints_grid=(6, 3, 2),
        kpoints_shift=(0, 0, 0),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pw.write_file(OUTPUT)
    print(f"Prepared {OUTPUT.relative_to(QE_DIR)}")


if __name__ == "__main__":
    main()

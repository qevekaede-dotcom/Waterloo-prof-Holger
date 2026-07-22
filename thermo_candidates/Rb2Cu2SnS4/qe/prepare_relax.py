#!/usr/bin/env python3
"""Prepare the converged-parameter vc-relax input for Rb2Cu2SnS4.

Converged settings from this material's own tests (qe/convergence/):
  ecutwfc/ecutrho = 90/720 Ry   (0.0896 meV/atom vs the 100 Ry reference)
  relax k mesh    = 2x4x4       (0.175 meV/atom vs the 5x9x9 reference)
Thresholds mirror the SrCu2SnS4/SrZrS3 protocol.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


QE_DIR = Path(__file__).resolve().parent
CANDIDATE = QE_DIR.parent
CIF = CANDIDATE / "structures" / "Rb2Cu2SnS4.cif"
OUTPUT = QE_DIR / "00_relax" / "Rb2Cu2SnS4.relax.in"
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
    pw = PWInput(
        structure,
        pseudo=PSEUDOS,
        control={
            "calculation": "vc-relax",
            "restart_mode": "from_scratch",
            "prefix": "Rb2Cu2SnS4_relax",
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
            "ecutwfc": 90,
            "ecutrho": 720,
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
        kpoints_grid=(2, 4, 4),
        kpoints_shift=(0, 0, 0),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pw.write_file(OUTPUT)
    print(f"Prepared {OUTPUT.relative_to(QE_DIR)}")


if __name__ == "__main__":
    main()

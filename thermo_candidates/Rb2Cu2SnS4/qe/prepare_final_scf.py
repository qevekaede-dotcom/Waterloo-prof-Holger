#!/usr/bin/env python3
"""Prepare the final SCF input from the relaxed Rb2Cu2SnS4 structure.

Converged settings from this material's own tests: 90/720 Ry, 3x5x5 mesh.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


QE_DIR = Path(__file__).resolve().parent
CANDIDATE = QE_DIR.parent
CIF = CANDIDATE / "structures" / "Rb2Cu2SnS4.relaxed.cif"
OUTPUT = QE_DIR / "01_scf" / "Rb2Cu2SnS4.scf.in"
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
            "calculation": "scf",
            "restart_mode": "from_scratch",
            "prefix": "Rb2Cu2SnS4",
            "outdir": "./tmp/final",
            "pseudo_dir": pseudo_dir,
            "verbosity": "high",
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
        kpoints_mode="automatic",
        kpoints_grid=(3, 5, 5),
        kpoints_shift=(0, 0, 0),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pw.write_file(OUTPUT)
    print(f"Prepared {OUTPUT.relative_to(QE_DIR)}")


if __name__ == "__main__":
    main()

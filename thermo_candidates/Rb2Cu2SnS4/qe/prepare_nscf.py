#!/usr/bin/env python3
"""Prepare the dense NSCF input used by BoltzTraP2 (Rb2Cu2SnS4).

Sizing:
  - 156 electrons -> 78 occupied bands (final SCF log); nbnd = 105 gives
    27 empty bands (~35% headroom, same ratio as the other two materials).
  - mesh 8x14x14 -> k-spacing 0.088/0.088/0.090 A^-1 on the relaxed
    primitive cell (reciprocal lengths ~0.70/1.23/1.26 A^-1). This is ~10%
    coarser than the 0.08 A^-1 standard used for SrCu2SnS4/SrZrS3: in this
    primitive-cell orientation QE's automatic grids only reduce ~2x by
    symmetry, so matching 0.08 exactly (9x16x16, ~1150 irreducible points)
    would roughly double the cost for a marginal spacing gain. The standing
    transport-mesh-convergence caveat applies to all three materials.
"""

from pathlib import Path
import os

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


QE_DIR = Path(__file__).resolve().parent
CANDIDATE = QE_DIR.parent
CIF = CANDIDATE / "structures" / "Rb2Cu2SnS4.relaxed.cif"
OUTPUT = QE_DIR / "02_nscf" / "Rb2Cu2SnS4.nscf.in"
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
            "calculation": "nscf",
            "prefix": "Rb2Cu2SnS4",
            "outdir": "./tmp/final",
            "pseudo_dir": pseudo_dir,
            "verbosity": "high",
            "disk_io": "nowf",
        },
        system={
            "ecutwfc": 90,
            "ecutrho": 720,
            "occupations": "fixed",
            "nbnd": 105,
        },
        electrons={
            "conv_thr": 1e-8,
            "diagonalization": "david",
            "diago_full_acc": True,
            "startingpot": "file",
        },
        kpoints_mode="automatic",
        kpoints_grid=(8, 14, 14),
        kpoints_shift=(0, 0, 0),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pw.write_file(OUTPUT)
    print(f"Prepared {OUTPUT.relative_to(QE_DIR)}")


if __name__ == "__main__":
    main()

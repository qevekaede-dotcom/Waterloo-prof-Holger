#!/usr/bin/env python
"""Merge phono3py supercell fragments with the QE header -> full pw.x inputs.

Each supercell-XXXXX.in from phono3py contains only:
  comment (nat/ntyp), CELL_PARAMETERS bohr, ATOMIC_SPECIES, ATOMIC_POSITIONS.
This script wraps each fragment with &CONTROL/&SYSTEM/&ELECTRONS namelists and
K_POINTS, writing fc_calcs/disp-XXXXX/scf.in. Idempotent: existing inputs are
rewritten only with --force.

Settings follow the SrCu2SnS4 converged parameters (90/720 Ry, fixed
occupations) with force-calculation specifics: tprnfor, conv_thr=1e-9,
disk_io='none'. K-mesh is a parameter (default 3 3 3; see k-mesh force
convergence check in the WORKLOG).
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # phono3py/
PSEUDO_DIR = "/Users/kaede/scientific-tools/pseudopotentials/SSSP/1.3.0/PBE/precision"

HEADER = """&CONTROL
  calculation = 'scf',
  tprnfor = .true.,
  disk_io = 'none',
  outdir = './tmp',
  prefix = 'sc',
  pseudo_dir = '{pseudo_dir}',
  restart_mode = 'from_scratch',
  verbosity = 'low',
/
&SYSTEM
  ecutrho = {ecutrho},
  ecutwfc = {ecutwfc},
  occupations = 'fixed',
  ibrav = 0,
  nat = {nat},
  ntyp = {ntyp},
/
&ELECTRONS
  conv_thr = 1d-09,
  diagonalization = 'david',
  electron_maxstep = 200,
  mixing_beta = 0.3,
/
"""

KPOINTS = """K_POINTS automatic
  {kx} {ky} {kz} 0 0 0
"""


def parse_fragment(path: Path):
    text = path.read_text()
    first = text.splitlines()[0]
    # "!    ibrav = 0, nat = 96, ntyp = 4"
    nat = int(first.split("nat =")[1].split(",")[0])
    ntyp = int(first.split("ntyp =")[1].split()[0])
    body = "\n".join(text.splitlines()[1:]) + "\n"
    return nat, ntyp, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kmesh", nargs=3, type=int, default=[3, 3, 3])
    ap.add_argument("--ecutwfc", type=int, default=90)
    ap.add_argument("--ecutrho", type=int, default=720)
    ap.add_argument("--only", nargs="*", help="supercell IDs, e.g. 00001")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--pristine", action="store_true",
        help="write checks/pristine/scf.in from the undisplaced supercell.in",
    )
    args = ap.parse_args()

    if args.pristine:
        nat, ntyp, body = parse_fragment(HERE / "supercell.in")
        run_dir = HERE / "checks" / "pristine"
        run_dir.mkdir(parents=True, exist_ok=True)
        kx, ky, kz = args.kmesh
        (run_dir / "scf.in").write_text(
            HEADER.format(
                pseudo_dir=PSEUDO_DIR, nat=nat, ntyp=ntyp,
                ecutwfc=args.ecutwfc, ecutrho=args.ecutrho,
            )
            + body
            + KPOINTS.format(kx=kx, ky=ky, kz=kz)
        )
        print("wrote checks/pristine/scf.in")
        return

    fragments = sorted(HERE.glob("supercell-*.in"))
    if args.only:
        keep = {f"supercell-{i}.in" for i in args.only}
        fragments = [f for f in fragments if f.name in keep]
    if not fragments:
        sys.exit("no supercell fragments found")

    written = skipped = 0
    for frag in fragments:
        disp_id = frag.stem.split("-")[1]
        run_dir = HERE / "fc_calcs" / f"disp-{disp_id}"
        target = run_dir / "scf.in"
        if target.exists() and not args.force:
            skipped += 1
            continue
        nat, ntyp, body = parse_fragment(frag)
        run_dir.mkdir(parents=True, exist_ok=True)
        kx, ky, kz = args.kmesh
        target.write_text(
            HEADER.format(
                pseudo_dir=PSEUDO_DIR, nat=nat, ntyp=ntyp,
                ecutwfc=args.ecutwfc, ecutrho=args.ecutrho,
            )
            + body
            + KPOINTS.format(kx=kx, ky=ky, kz=kz)
        )
        written += 1
    print(f"wrote {written} inputs, skipped {skipped} existing")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Stage 2: collect forces, build FC2/FC3, converge the q-mesh, compute kappa_L.

Steps (idempotent — each is skipped if its product already exists):
  1. FORCES_FC3 via `phono3py-init --cf3 <all healthy scf.out in ID order>`.
  2. q-mesh convergence at 300 K: run RTA (--br) on a mesh ladder until the
     averaged kappa changes < CONV_TOL between consecutive meshes.
  3. Final RTA run on the converged mesh, 300-900 K step 100.
  4. Write derived tables to ../results/ and a summary with sanity checks
     (minimum phonon frequency = imaginary-mode check).

fc3 build: default (traditional) solver first; falls back to --fc-calc symfc
if the traditional solver rejects the cutoff-pair dataset.
All phono3py invocations use --tolerance 1e-3 (see WORKLOG: 6-decimal
coordinates in unitcell.in need a loosened symmetry tolerance).
"""

import csv
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parent.parent  # phono3py/
RESULTS = ROOT.parent / "results"
TOL = "1e-3"
MESH_LADDER = [(7, 7, 3), (9, 9, 4), (11, 11, 5), (13, 13, 6), (15, 15, 7)]
CONV_TOL = 0.03  # relative change in kappa_avg(300 K)
TEMPS = "--tmin 300 --tmax 900 --tstep 100"


def sh(cmd, log_name):
    """Run a shell command from ROOT, tee output to a log file."""
    log = ROOT / log_name
    print(f"[postprocess] $ {cmd}")
    with open(log, "a") as f:
        f.write(f"\n$ {cmd}\n")
        p = subprocess.run(
            cmd, shell=True, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT
        )
    if p.returncode != 0:
        print(f"[postprocess] FAILED (see {log})")
    return p.returncode


def kappa_file(mesh):
    return ROOT / f"kappa-m{mesh[0]}{mesh[1]}{mesh[2]}.hdf5"


def read_kappa(mesh):
    with h5py.File(kappa_file(mesh)) as f:
        temps = np.array(f["temperature"])
        kappa = np.array(f["kappa"])  # (T, 6) Voigt: xx yy zz yz xz xy
        freq_min = float(np.min(f["frequency"]))
    return temps, kappa, freq_min


def main():
    # ---- 1. FORCES_FC3 ----
    if not (ROOT / "FORCES_FC3").exists():
        outs = sorted(ROOT.glob("fc_calcs/disp-*/scf.out"))
        frags = sorted(ROOT.glob("supercell-*.in"))
        if len(outs) != len(frags):
            sys.exit(
                f"[postprocess] {len(outs)} outputs vs {len(frags)} supercells"
            )
        files = " ".join(str(o.relative_to(ROOT)) for o in outs)
        # --cfz subtracts the measured residual forces of the undisplaced
        # supercell (checks/pristine, nosym run) from every displaced-cell
        # force before fitting: the pristine check measured max 5.5e-4
        # Ry/bohr, above the 1e-4 guideline, so it is corrected, not just
        # flagged.
        cfz = "checks/pristine/scf.out"
        cfz_arg = f" --cfz {cfz}" if (ROOT / cfz).exists() else ""
        if sh(f"phono3py-init --cf3 {files}{cfz_arg}", "log_cf3.txt") != 0:
            sys.exit("[postprocess] --cf3 failed")
    print("[postprocess] FORCES_FC3 ready")

    # ---- 2. mesh ladder at 300 K ----
    prev = None
    chosen = None
    fc_flags = ""  # set to "--fc-calc symfc" if traditional solver fails
    for mesh in MESH_LADDER:
        if not kappa_file(mesh).exists():
            m = f"{mesh[0]} {mesh[1]} {mesh[2]}"
            cmd = (
                f"phono3py --mesh {m} --br --ts 300 "
                f"--tolerance {TOL} {fc_flags} phono3py_disp.yaml"
            )
            if sh(cmd, "log_kappa.txt") != 0 and not fc_flags:
                print("[postprocess] retrying fc build with symfc")
                for f in ("fc2.hdf5", "fc3.hdf5"):
                    (ROOT / f).unlink(missing_ok=True)
                fc_flags = "--fc-calc symfc"
                cmd = (
                    f"phono3py --mesh {m} --br --ts 300 "
                    f"--tolerance {TOL} {fc_flags} phono3py_disp.yaml"
                )
                if sh(cmd, "log_kappa.txt") != 0:
                    sys.exit("[postprocess] kappa run failed on both solvers")
        _, kappa, _ = read_kappa(mesh)
        k_avg = float(np.mean(kappa[0][:3]))
        print(f"[postprocess] mesh {mesh}: kappa_avg(300K) = {k_avg:.3f} W/m/K")
        if prev is not None and prev[1] > 0 and \
                abs(k_avg - prev[1]) / prev[1] < CONV_TOL:
            chosen = mesh
            break
        prev = (mesh, k_avg)
    if chosen is None:
        chosen = MESH_LADDER[-1]
        print("[postprocess] WARNING: mesh ladder did not converge to "
              f"{CONV_TOL:.0%}; using largest mesh {chosen} — flag this in "
              "the writeup")

    # ---- 3. final run, full temperature range ----
    final_tag = f"final-m{chosen[0]}{chosen[1]}{chosen[2]}"
    m = f"{chosen[0]} {chosen[1]} {chosen[2]}"
    cmd = (
        f"phono3py --mesh {m} --br {TEMPS} "
        f"--tolerance {TOL} {fc_flags} phono3py_disp.yaml"
    )
    if sh(cmd, "log_kappa.txt") != 0:
        sys.exit("[postprocess] final kappa run failed")
    temps, kappa, freq_min = read_kappa(chosen)

    # ---- 4. derived tables + summary ----
    RESULTS.mkdir(exist_ok=True)
    csv_path = RESULTS / "kappa_L_first_pass.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "T (K)", "kappa_xx (W m^-1 K^-1)", "kappa_yy (W m^-1 K^-1)",
            "kappa_zz (W m^-1 K^-1)", "kappa_avg (W m^-1 K^-1)",
        ])
        for t, k in zip(temps, kappa):
            if 300 <= t <= 900:
                w.writerow([
                    f"{t:.0f}", f"{k[0]:.4f}", f"{k[1]:.4f}", f"{k[2]:.4f}",
                    f"{np.mean(k[:3]):.4f}",
                ])
    summary = RESULTS / "kappa_L_summary.md"
    with open(summary, "w") as f:
        f.write("# SrCu2SnS4 lattice thermal conductivity — first pass "
                "[calculated]\n\n")
        f.write("phono3py RTA (--br), 2x2x1 supercell, cutoff-pair 4.0 A, "
                f"q-mesh {chosen}, PBE, no SOC, no NAC.\n\n")
        solver = "symfc" if fc_flags else "traditional"
        if freq_min > -0.1:
            freq_status = "OK"
        else:
            freq_status = ("IMAGINARY MODES — structure/supercell must be "
                           "re-examined before trusting kappa")
        f.write(f"- solver for fc3: {solver}\n")
        f.write(f"- minimum phonon frequency on mesh: {freq_min:.4f} THz "
                f"({freq_status})\n")
        f.write(f"- table: `{csv_path.name}`\n\n")
        f.write("kappa_L here is a first-pass value under the documented "
                "cutoffs; it is NOT yet combined with any electronic zT_e. "
                "Full zT still needs a relaxation-time model for the "
                "electronic side.\n")
    print(f"[postprocess] wrote {csv_path} and {summary}")
    print(f"[postprocess] min phonon frequency: {freq_min:.4f} THz")
    print(f"[postprocess] done: {final_tag}")


if __name__ == "__main__":
    main()

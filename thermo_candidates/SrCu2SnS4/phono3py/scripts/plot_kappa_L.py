#!/usr/bin/env python3
"""Plot the first-pass lattice thermal conductivity kappa_L(T).

Inputs (read only, all pre-existing):
  ../results/kappa_L_first_pass.csv - curated table written by postprocess.py
                                      (the authoritative derived record)
  ../kappa-m13136.hdf5              - phono3py output of the final 13x13x6
                                      full-temperature RTA run (cross-check)

The CSV is plotted; the hdf5 is only used to verify the CSV still matches the
raw phono3py output (same guard as the other plot scripts: trace every number
back to the original output before presenting it).

kappa_xx = kappa_yy is the in-plane value and kappa_zz the c-axis value for
the trigonal P3_121 cell; the average is the scalar (2*xx + zz)/3. First-pass
approximations (documented in the WORKLOG): RTA, 2x2x1 supercell, 4.0 A pair
cutoff, no NAC, scalar-relativistic PBE without SOC.

Output -> ../results/: kappa_L_first_pass.png
"""
from pathlib import Path
import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
P3 = HERE.parent                      # .../SrCu2SnS4/phono3py
RESULTS = P3.parent / "results"

COLOR_INPLANE = "#3B6FD4"             # palette validated (CVD-safe pair)
COLOR_CAXIS = "#EE6677"
COLOR_AVG = "0.35"                    # reference line, dashed (not a hue ID)


def main():
    with open(RESULTS / "kappa_L_first_pass.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    header, data = rows[0], np.array(rows[1:], dtype=float)
    t, kxx, kyy, kzz, kavg = data.T
    print(f"read {RESULTS/'kappa_L_first_pass.csv'}: "
          f"{len(t)} temperatures, columns: {header}")

    # --- check 1: CSV still matches the raw phono3py hdf5 -------------------
    try:
        import h5py
        with h5py.File(P3 / "kappa-m13136.hdf5", "r") as h5:
            h5_t = np.asarray(h5["temperature"])
            h5_k = np.asarray(h5["kappa"])       # columns xx,yy,zz,yz,xz,xy
        assert np.allclose(h5_t, t), "temperature grids differ"
        for name, csv_col, h5_col in (("xx", kxx, h5_k[:, 0]),
                                      ("yy", kyy, h5_k[:, 1]),
                                      ("zz", kzz, h5_k[:, 2])):
            diff = np.max(np.abs(csv_col - h5_col))
            assert diff < 5e-5, f"kappa_{name} differs from hdf5 by {diff}"
        print("check 1: CSV == kappa-m13136.hdf5 (xx, yy, zz) "
              "to the CSV's 4-decimal rounding")
    except (ImportError, FileNotFoundError) as exc:
        print(f"check 1 SKIPPED (no cross-check possible here): {exc}")

    # --- check 2: internal consistency --------------------------------------
    # columns are rounded to 4 decimals independently, so the recomputed
    # average can differ from the rounded avg column by up to ~1e-4
    assert np.allclose(kxx, kyy, atol=5e-5), "xx != yy (trigonal symmetry?)"
    assert np.allclose(kavg, (2 * kxx + kzz) / 3, atol=1.5e-4), "avg != trace/3"
    print("check 2: kappa_xx == kappa_yy and kappa_avg == (2*xx + zz)/3")

    # --- plot ----------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.plot(t, kxx, "o-", color=COLOR_INPLANE, lw=1.8, ms=5,
            label=r"in-plane ($\kappa_{xx}=\kappa_{yy}$)")
    ax.plot(t, kzz, "s-", color=COLOR_CAXIS, lw=1.8, ms=5,
            label=r"c-axis ($\kappa_{zz}$)")
    ax.plot(t, kavg, "--", color=COLOR_AVG, lw=1.4,
            label="scalar average (trace/3)")
    ax.set_xlim(250, 950)
    ax.set_ylim(0, 1.1 * kxx.max())
    ax.set_xticks(t)
    ax.set_xlabel(r"$T$  (K)")
    ax.set_ylabel(r"$\kappa_\mathrm{L}$  (W m$^{-1}$ K$^{-1}$)")
    ax.set_title("SrCu$_2$SnS$_4$ lattice thermal conductivity — "
                 "phono3py RTA, first pass\n"
                 r"(2$\times$2$\times$1 supercell, 4.0 $\AA$ pair cutoff, "
                 r"13$\times$13$\times$6 q-mesh; PBE, no SOC)",
                 fontsize=10)
    ax.grid(color="0.92", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, loc="upper right", framealpha=0.9)
    fig.tight_layout()
    out = RESULTS / "kappa_L_first_pass.png"
    fig.savefig(out, dpi=160)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

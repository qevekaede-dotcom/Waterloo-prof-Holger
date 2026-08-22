#!/usr/bin/env python3
"""Regenerate the kappa_L(T) figure from the authoritative CSV.

Reads  thermo_candidates/SrCu2SnS4/results/kappa_L_first_pass.csv
Writes SrCu2SnS4_kappa_L_vs_T.png next to this script's parent results/ and
READY_TO_ATTACH/ folders. Direct labels on both series (colorblind-safe
blue/orange pair); the CSV itself is the table view of the same numbers.
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent          # reproducibility/
PKG = HERE.parent                               # the fourth-step package
REPO = PKG.parent                               # repo root
SRC = REPO / "thermo_candidates/SrCu2SnS4/results/kappa_L_first_pass.csv"

T, kxx, kzz, kavg = [], [], [], []
with open(SRC) as f:
    for row in csv.DictReader(f):
        T.append(float(row["T (K)"]))
        kxx.append(float(row["kappa_xx (W m^-1 K^-1)"]))
        kzz.append(float(row["kappa_zz (W m^-1 K^-1)"]))
        kavg.append(float(row["kappa_avg (W m^-1 K^-1)"]))

BLUE, ORANGE = "#1f77b4", "#ff7f0e"
fig, ax = plt.subplots(figsize=(6.0, 4.2), dpi=200)
ax.plot(T, kxx, "o-", color=BLUE, lw=2, ms=5, label="in-plane (xx = yy)")
ax.plot(T, kzz, "s-", color=ORANGE, lw=2, ms=5, label="c-axis (zz)")
ax.plot(T, kavg, "--", color="0.35", lw=1.5, label="isotropic average")
ax.annotate("in-plane (xx = yy)", (T[1], kxx[1]), xytext=(8, 8),
            textcoords="offset points", color="0.15", fontsize=9)
ax.annotate("c-axis (zz)", (T[2], kzz[2]), xytext=(8, -14),
            textcoords="offset points", color="0.15", fontsize=9)
ax.set_xlabel("Temperature (K)")
ax.set_ylabel(r"$\kappa_L$ (W m$^{-1}$ K$^{-1}$)")
ax.set_ylim(0, 0.45)
ax.set_xlim(280, 920)
ax.set_title("SrCu2SnS4 lattice thermal conductivity — first pass [calculated]",
             fontsize=10.5)
ax.text(0.98, 0.96,
        "phono3py RTA, 2x2x1 supercell, cutoff-pair 4.0 $\\AA$,\n"
        "q-mesh 15x15x7, PBE, no SOC, no NAC",
        transform=ax.transAxes, ha="right", va="top", fontsize=8, color="0.35")
ax.grid(alpha=0.25, lw=0.5)
ax.legend(loc="center right", fontsize=8.5, framealpha=0.9)
fig.tight_layout()
for dest in (PKG / "results", PKG / "READY_TO_ATTACH"):
    dest.mkdir(exist_ok=True)
    fig.savefig(dest / "SrCu2SnS4_kappa_L_vs_T.png")
    print("wrote", dest / "SrCu2SnS4_kappa_L_vs_T.png")

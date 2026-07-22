#!/usr/bin/env python3
"""Plot the Seebeck coefficient vs chemical potential, centered on E_F (SrZrS3).

Inputs (read only, all pre-existing BoltzTraP2 outputs):
  boltztrap2/SrZrS3.trace      - btp2 integrate mu scan, 300-900 K
  boltztrap2/SrZrS3.condtens   - full tensors (cross-check of the scalar S)
  boltztrap2/SrZrS3.dope.trace - fixed-density run (consistency check)
  boltztrap2/SrZrS3.bt2        - E_F
  structures/SrZrS3.relaxed.cif- cell volume for density conversion

The scalar S in the trace files is the orientational average of the tensor
diagonal, (S_xx + S_yy + S_zz)/3; this script verifies that against condtens.
Within the constant-relaxation-time approximation S is independent of tau, so
unlike sigma/tau and PF/tau these values are absolute (QE-PBE, no SOC).

Outputs -> results/: seebeck_vs_mu.png, seebeck_vs_mu.csv
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from BoltzTraP2 import serialization
from pymatgen.core import Structure

HA_TO_EV = 27.211386245988
RY_TO_EV = HA_TO_EV / 2.0
GAP_EV = 0.6096                      # QE-PBE sampled gap; VBM at E - E_F = 0

CAND = Path(__file__).resolve().parents[1]
BT = CAND / "boltztrap2"
RESULTS = CAND / "results"


def main():
    data, *_ = serialization.load_calculation(str(BT / "SrZrS3.bt2"))
    fermi_ry = data.fermi * 2.0          # Ha -> Ry
    nelect = data.nelect                 # electrons in BoltzTraP2's band window
    volume_cm3 = Structure.from_file(
        CAND / "structures" / "SrZrS3.relaxed.cif").volume * 1e-24

    trace = np.loadtxt(BT / "SrZrS3.trace", comments="#")
    cond = np.loadtxt(BT / "SrZrS3.condtens", comments="#")
    dope = np.loadtxt(BT / "SrZrS3.dope.trace", comments="#")

    mu_ev = (trace[:, 0] - fermi_ry) * RY_TO_EV
    temps = np.unique(trace[:, 1]).astype(int)
    s_uv = trace[:, 4] * 1e6             # V/K -> uV/K

    # --- check 1: scalar S in trace == diagonal average of condtens S -------
    s_diag_avg = cond[:, [12, 16, 20]].mean(axis=1) * 1e6
    sel = np.abs(s_uv) > 5.0             # avoid 0/0 near the sign change
    rel = np.max(np.abs(s_diag_avg[sel] - s_uv[sel]) / np.abs(s_uv[sel]))
    print(f"check 1: trace S vs condtens diag average, max rel diff = {rel:.2e}")

    # --- check 2: charge neutrality at E_F ----------------------------------
    row300 = trace[trace[:, 1] == 300]
    n_at_ef = np.interp(fermi_ry, row300[:, 0], row300[:, 2])
    print(f"check 2: N(mu=E_F, 300 K) = {n_at_ef:+.3f} e/uc (expected ~0; "
          f"band window holds {nelect:.0f} electrons)")

    # --- check 3: consistency with the doped run (300 K, n-type 1e20) ------
    target_n = -1e20 * volume_cm3        # n-type (electrons added)
    d300 = dope[dope[:, 1] == 300]
    row = d300[np.argmin(np.abs(d300[:, 2] - target_n))]
    s_dope = row[4] * 1e6
    s_scan = np.interp(row[0], row300[:, 0], row300[:, 4]) * 1e6
    print(f"check 3: 300 K n-type 1e20 cm^-3 -> dope S = {s_dope:.1f} uV/K, "
          f"mu-scan interp = {s_scan:.1f} uV/K")

    # --- plot ---------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.axvspan(0, GAP_EV, color="0.9", zorder=0)
    ax.axvline(0, color="k", lw=0.8, ls="--", zorder=1)
    ax.axhline(0, color="0.5", lw=0.8, zorder=1)
    colors = plt.cm.plasma(np.linspace(0.10, 0.85, len(temps)))
    win = 1.2
    ymax = 0.0
    for temp, color in zip(temps, colors):
        m = trace[:, 1] == temp
        order = np.argsort(mu_ev[m])
        x, y = mu_ev[m][order], s_uv[m][order]
        ax.plot(x, y, color=color, lw=1.5, label=f"{temp} K")
        inwin = np.abs(x) <= win
        ymax = max(ymax, np.abs(y[inwin]).max())
    ax.set_xlim(-win, win)
    ax.set_ylim(-1.1 * ymax, 1.1 * ymax)
    ax.set_xlabel(r"$\mu - E_\mathrm{F}$  (eV)")
    ax.set_ylabel(r"$S$  ($\mu$V K$^{-1}$)")
    ax.set_title(r"SrZrS$_3$ Seebeck coefficient, centered on $E_\mathrm{F}$"
                 "\n(BoltzTraP2 rigid band; $S$ is $\\tau$-independent under CRTA)",
                 fontsize=10)
    ax.text(-0.95 * win, 0.9 * ymax, "p-type side\n(S > 0)", fontsize=8, va="top")
    ax.text(0.95 * win, -0.9 * ymax, "n-type side\n(S < 0)", fontsize=8,
            ha="right", va="bottom")
    ax.legend(fontsize=8, loc="upper right", ncol=2, framealpha=0.9)
    fig.tight_layout()
    RESULTS.mkdir(exist_ok=True)
    fig.savefig(RESULTS / "seebeck_vs_mu.png", dpi=160)

    # --- CSV: pivot to one column per temperature ---------------------------
    mus = np.unique(trace[:, 0])
    keep = np.abs((mus - fermi_ry) * RY_TO_EV) <= 1.5
    mus = mus[keep]
    table = [(mus - fermi_ry) * RY_TO_EV]
    header = ["mu_minus_EF_eV"]
    for temp in temps:
        m = trace[:, 1] == temp
        sub = trace[m]
        order = np.argsort(sub[:, 0])
        table.append(np.interp(mus, sub[order, 0], sub[order, 4]) * 1e6)
        header.append(f"S_{temp}K_uV_K-1")
    np.savetxt(RESULTS / "seebeck_vs_mu.csv", np.column_stack(table),
               header=",".join(header), delimiter=",", comments="")

    # peak values inside the window at 300 K, for the summary
    m = trace[:, 1] == 300
    x, y = mu_ev[m], s_uv[m]
    inwin = np.abs(x) <= win
    print(f"300 K extrema in window: S_max = +{y[inwin].max():.0f} uV/K at "
          f"mu-E_F = {x[inwin][np.argmax(y[inwin])]:+.3f} eV; "
          f"S_min = {y[inwin].min():.0f} uV/K at "
          f"mu-E_F = {x[inwin][np.argmin(y[inwin])]:+.3f} eV")
    print(f"wrote {RESULTS/'seebeck_vs_mu.png'}")
    print(f"wrote {RESULTS/'seebeck_vs_mu.csv'}")


if __name__ == "__main__":
    main()

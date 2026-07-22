#!/usr/bin/env python3
"""Two-panel comparison figure of the three candidates' sampled transport.

Reads each material's results/transport_best_power_factor.csv (the best
PF/tau point per temperature and carrier sign on the shared sampled grid,
300-900 K x 1e19-1e21 cm^-3) and plots:

  left:  best sampled PF/tau vs T   (log scale; per unknown tau - NOT absolute)
  right: zT_e at those same points  (electronic-only upper bound; no kappa_L)

Solid = p-type, dashed = n-type; one color per material. QE-PBE, scalar-
relativistic, no SOC, CRTA, rigid band, polycrystalline average.

Usage:
  python thermo_candidates/scripts/plot_three_material_transport.py OUTPUT.png
"""

import sys
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TC = Path(__file__).resolve().parents[1]
MATERIALS = (
    ("SrCu2SnS4", r"SrCu$_2$SnS$_4$", "tab:blue"),
    ("SrZrS3", r"SrZrS$_3$", "tab:orange"),
    ("Rb2Cu2SnS4", r"Rb$_2$Cu$_2$SnS$_4$", "tab:green"),
)


def load(material):
    rows = []
    path = TC / material / "results" / "transport_best_power_factor.csv"
    with path.open() as handle:
        for row in csv.DictReader(handle):
            rows.append(
                (
                    int(row["temperature_K"]),
                    row["carrier_type"],
                    float(row["power_factor_over_tau_W_m-1_K-2_s-1"]),
                    float(row["electronic_zT_no_lattice"]),
                )
            )
    return rows


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("three_material_transport_comparison.png")
    fig, (ax_pf, ax_zt) = plt.subplots(1, 2, figsize=(11.0, 4.6))

    for material, label, color in MATERIALS:
        rows = load(material)
        for carrier, style in (("p", "-"), ("n", "--")):
            pts = sorted(r for r in rows if r[1] == carrier)
            temps = [r[0] for r in pts]
            ax_pf.plot(temps, [r[2] for r in pts], style, color=color, lw=1.8,
                       marker="o", ms=3.5,
                       label=f"{label} ({carrier})")
            ax_zt.plot(temps, [r[3] for r in pts], style, color=color, lw=1.8,
                       marker="o", ms=3.5)

    ax_pf.set_yscale("log")
    ax_pf.set_xlabel("T (K)")
    ax_pf.set_ylabel(r"best sampled PF/$\tau$  (W m$^{-1}$ K$^{-2}$ s$^{-1}$)")
    ax_pf.set_title(r"Best sampled PF/$\tau$ vs T"
                    "\n(per unknown relaxation time $\\tau$ - not an absolute PF)",
                    fontsize=10)
    ax_pf.legend(fontsize=7.5, ncol=1, framealpha=0.9)

    ax_zt.set_xlabel("T (K)")
    ax_zt.set_ylabel(r"$zT_e$ at the best-PF/$\tau$ point  (-)")
    ax_zt.set_title(r"Electronic-only $zT_e$ at those points"
                    "\n(upper bound: lattice $\\kappa_L$ not included)",
                    fontsize=10)

    for ax in (ax_pf, ax_zt):
        ax.grid(alpha=0.3)
    fig.suptitle("Three-candidate first pass, shared sampled grid "
                 r"(300-900 K, 10$^{19}$-10$^{21}$ cm$^{-3}$; QE-PBE + BoltzTraP2,"
                 " CRTA, rigid band, no SOC)", fontsize=9.5, y=1.00)
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

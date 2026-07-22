#!/usr/bin/env python3
"""Compare the QE dos.x DOS with the BoltzTraP2 interpolated DOS for SrCu2SnS4.

Inputs (read only):
  - qe/dos/SrCu2SnS4.dos          : QE dos.x output (states/eV/cell, Int DOS)
  - boltztrap2/SrCu2SnS4.bt2      : BoltzTraP2 interpolation of the dense NSCF

Both DOS are referenced to the QE Fermi level (the VBM, since the NSCF used
fixed occupations for an insulator). The BoltzTraP2 DOS is also Gaussian-
broadened to the same width as the dos.x smearing so the two methods are
compared on equal footing.

Derived outputs -> results/:
  - dos_qe_vs_boltztrap2.csv
  - dos_qe_vs_boltztrap2.png

Nothing here modifies raw QE or BoltzTraP2 records.
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from BoltzTraP2 import serialization, fite, bandlib

HA_TO_EV = 27.211386245988
GAP_EV = 0.3445           # QE-PBE indirect gap (VBM at E-E_F = 0)
QE_DEGAUSS_EV = 0.068     # dos.x Gaussian width used (0.005 Ry)

CAND = Path(__file__).resolve().parents[1]
BT2 = CAND / "boltztrap2" / "SrCu2SnS4.bt2"
QE_DOS = CAND / "qe" / "dos" / "SrCu2SnS4.dos"
RESULTS = CAND / "results"

_trapz = np.trapezoid if hasattr(np, "trapezoid") else np.trapz


def main():
    # --- BoltzTraP2 interpolated DOS --------------------------------------
    data, equivalences, coeffs, metadata = serialization.load_calculation(str(BT2))
    btp = fite.getBTPbands(equivalences, coeffs, data.get_lattvec())
    eband, vvband = btp[0], btp[1]
    fermi_ev = data.fermi * HA_TO_EV
    epsilon, dos, vvdos, cdos = bandlib.BTPDOS(eband, vvband, npts=4000)
    bt2_e = epsilon * HA_TO_EV - fermi_ev
    bt2_dos = dos * data.dosweight / HA_TO_EV      # states / eV / cell

    n_bt2 = _trapz(bt2_dos[bt2_e <= 0], bt2_e[bt2_e <= 0])

    # --- QE dos.x DOS -----------------------------------------------------
    qe = np.loadtxt(QE_DOS, comments="#")
    qe_e = qe[:, 0] - fermi_ev
    qe_dos = qe[:, 1]
    n_qe = np.interp(0.0, qe_e, qe[:, 2])

    # --- common grid + matched broadening of BoltzTraP2 -------------------
    grid = np.arange(-6.0, 6.0 + 1e-9, 0.02)
    qe_i = np.interp(grid, qe_e, qe_dos)
    bt_i = np.interp(grid, bt2_e, bt2_dos)
    sigma, dx = QE_DEGAUSS_EV, grid[1] - grid[0]
    kx = np.arange(-int(round(4 * sigma / dx)), int(round(4 * sigma / dx)) + 1) * dx
    kernel = np.exp(-0.5 * (kx / sigma) ** 2)
    kernel /= kernel.sum()
    bt_broad = np.convolve(bt_i, kernel, mode="same")

    w = (grid >= -5.0) & (grid <= 5.0)
    rel_l2 = np.linalg.norm(qe_i[w] - bt_broad[w]) / np.linalg.norm(qe_i[w])
    corr = np.corrcoef(qe_i[w], bt_broad[w])[0, 1]

    RESULTS.mkdir(exist_ok=True)
    header = ("E_minus_EF_eV,QE_dosx_DOS_states_eV-1_cell-1,"
              "BoltzTraP2_DOS_states_eV-1_cell-1,"
              "BoltzTraP2_DOS_broadened_states_eV-1_cell-1")
    np.savetxt(RESULTS / "dos_qe_vs_boltztrap2.csv",
               np.column_stack([grid, qe_i, bt_i, bt_broad]),
               header=header, delimiter=",", comments="")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6),
                                   gridspec_kw={"width_ratios": [1.5, 1]})
    for ax in (ax1, ax2):
        ax.axvspan(0, GAP_EV, color="0.9", zorder=0)
        ax.axvline(0, color="k", lw=0.8, ls="--", zorder=1)
        ax.plot(grid, qe_i, color="#1f77b4", lw=1.6,
                label=f"QE dos.x ({QE_DEGAUSS_EV:.3f} eV Gauss, 12x12x6)")
        ax.plot(grid, bt_i, color="#d62728", lw=1.2, alpha=0.55,
                label="BoltzTraP2 (native, x5 interp.)")
        ax.plot(grid, bt_broad, color="#d62728", lw=1.8, ls=":",
                label=f"BoltzTraP2 (broadened to {QE_DEGAUSS_EV:.3f} eV)")
        ax.set_xlabel(r"$E - E_\mathrm{F}$  (eV)")
        ax.set_ylabel("DOS  (states eV$^{-1}$ cell$^{-1}$)")
    ax1.set_xlim(-6, 6)
    ax1.set_ylim(0, max(qe_i.max(), bt_i.max()) * 1.05)
    ax1.set_title(r"SrCu$_2$SnS$_4$ DOS:  QE dos.x vs BoltzTraP2")
    ax1.legend(fontsize=8, loc="upper right")
    ax2.set_xlim(-1.5, 1.8)
    m = (grid > -1.5) & (grid < 1.8)
    ax2.set_ylim(0, max(qe_i[m].max(), bt_i[m].max()) * 1.05)
    ax2.set_title("Zoom on the gap")
    fig.tight_layout()
    fig.savefig(RESULTS / "dos_qe_vs_boltztrap2.png", dpi=160)

    print(f"E_F (QE, = VBM) = {fermi_ev:.4f} eV")
    print(f"electrons below E_F:  QE dos.x = {n_qe:.1f}  |  BoltzTraP2 = {n_bt2:.1f} "
          f"(BoltzTraP2 drops deep semicore bands)")
    print(f"matched-broadening agreement, |E-E_F|<5 eV: "
          f"relative L2 diff = {rel_l2:.3f}, Pearson r = {corr:.4f}")
    print(f"wrote {RESULTS/'dos_qe_vs_boltztrap2.csv'}")
    print(f"wrote {RESULTS/'dos_qe_vs_boltztrap2.png'}")


if __name__ == "__main__":
    main()

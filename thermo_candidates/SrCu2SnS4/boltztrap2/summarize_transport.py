#!/usr/bin/env python3
"""Create compact transport summaries from the BoltzTraP2 dope trace."""

from pathlib import Path
import csv

import numpy as np
from BoltzTraP2.dft import ESPRESSOLoader
from pymatgen.core import Structure


CANDIDATE = Path(__file__).resolve().parents[1]
BT2_DIR = CANDIDATE / "boltztrap2"
RESULTS = CANDIDATE / "results"
TRACE = BT2_DIR / "SrCu2SnS4.dope.trace"
QE_SOURCE = CANDIDATE / "qe" / "tmp" / "final" / "SrCu2SnS4.save"
RELAXED_CIF = CANDIDATE / "structures" / "SrCu2SnS4.relaxed.cif"
HARTREE_TO_EV = 27.211386245988


def main() -> None:
    raw = np.loadtxt(TRACE, comments="#")
    structure = Structure.from_file(RELAXED_CIF)
    volume_cm3 = structure.volume * 1e-24
    rows = []

    for values in raw:
        ef_ry, temperature, carriers_uc, dos, seebeck, sigma_tau, hall, kappa_tau, cv, chi = values
        signed_density = carriers_uc / volume_cm3
        power_factor_tau = seebeck**2 * sigma_tau
        electronic_zt = power_factor_tau * temperature / kappa_tau
        rows.append(
            {
                "temperature_K": int(temperature),
                "carrier_type": "n" if signed_density < 0 else "p",
                "carrier_density_cm-3": abs(signed_density),
                "signed_density_cm-3": signed_density,
                "chemical_potential_Ry": ef_ry,
                "seebeck_uV_K": seebeck * 1e6,
                "sigma_over_tau_ohm-1_m-1_s-1": sigma_tau,
                "kappa_e_over_tau_W_m-1_K-1_s-1": kappa_tau,
                "power_factor_over_tau_W_m-1_K-2_s-1": power_factor_tau,
                "electronic_zT_no_lattice": electronic_zt,
                "hall_m3_C": hall,
                "smoothed_DOS_Ha-1_uc-1": dos,
                "cv_J_mol-1_K-1": cv,
                "chi_m3_mol-1": chi,
            }
        )

    RESULTS.mkdir(parents=True, exist_ok=True)
    full_csv = RESULTS / "transport_full.csv"
    with full_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    best = []
    for temperature in sorted({row["temperature_K"] for row in rows}):
        for carrier_type in ("n", "p"):
            subset = [
                row
                for row in rows
                if row["temperature_K"] == temperature
                and row["carrier_type"] == carrier_type
            ]
            best.append(
                max(
                    subset,
                    key=lambda row: row[
                        "power_factor_over_tau_W_m-1_K-2_s-1"
                    ],
                )
            )

    best_csv = RESULTS / "transport_best_power_factor.csv"
    with best_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=best[0].keys())
        writer.writeheader()
        writer.writerows(best)

    data = ESPRESSOLoader(str(QE_SOURCE))
    occupied = int(round(data.nelect / data.dosweight))
    vbm = float(np.max(data.ebands[occupied - 1]))
    cbm = float(np.min(data.ebands[occupied]))
    gap_ev = (cbm - vbm) * HARTREE_TO_EV

    summary = RESULTS / "workflow_summary.md"
    lines = [
        "# SrCu2SnS4 Workflow Summary",
        "",
        "## DFT",
        "",
        "- Materials Project structure: `mp-16988`",
        "- QE-relaxed space group: `P3_121` (No. 152)",
        "- Cutoffs: `90/720 Ry`",
        "- Relaxation k mesh: `4x4x2`",
        "- Final SCF k mesh: `5x5x3`",
        "- Dense NSCF k mesh: `12x12x6` (100 irreducible points)",
        "- Bands: 140 total, 105 occupied",
        f"- QE-PBE indirect gap: `{gap_ev:.4f} eV`",
        "",
        "## Best Sampled Power Factor",
        "",
        "| T (K) | Type | Density (cm^-3) | S (uV/K) | PF/tau | zT_e |",
        "|---:|:---:|---:|---:|---:|---:|",
    ]
    for row in best:
        lines.append(
            f"| {row['temperature_K']} | {row['carrier_type']} | "
            f"{row['carrier_density_cm-3']:.2e} | "
            f"{row['seebeck_uV_K']:.1f} | "
            f"{row['power_factor_over_tau_W_m-1_K-2_s-1']:.3e} | "
            f"{row['electronic_zT_no_lattice']:.3f} |"
        )
    lines.extend(
        [
            "",
            "`PF/tau` is reported in `W m^-1 K^-2 s^-1`. `zT_e` uses only",
            "electronic thermal conductivity, so it is an upper bound rather than",
            "the full thermoelectric zT. A relaxation time and lattice thermal",
            "conductivity are still required for absolute conductivity and full zT.",
            "",
        ]
    )
    summary.write_text("\n".join(lines))

    print(f"Wrote {full_csv.relative_to(CANDIDATE)} ({len(rows)} rows)")
    print(f"Wrote {best_csv.relative_to(CANDIDATE)} ({len(best)} rows)")
    print(f"Wrote {summary.relative_to(CANDIDATE)}")


if __name__ == "__main__":
    main()

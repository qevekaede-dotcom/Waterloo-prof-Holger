#!/usr/bin/env python3
"""Replot saved Rb tensors; no FC, phonon, transport calculation or extrapolation."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json"
COMPONENTS = ("xx", "yy", "zz", "trace/3")
THRESHOLDS = (0.05, 0.05, 0.05, 0.03)  # Existing Rb rules, not new tolerances.


def extract(audit: dict) -> list[dict]:
    ladder = sorted(audit["qmesh_ladder"], key=lambda item: item["length_angstrom"])
    stored = {(s["from"], s["to"]): s for s in audit["qmesh_steps"]}
    rows = []
    for old, new in zip(ladder, ladder[1:]):
        if old["temperature_K"] != new["temperature_K"]:
            raise ValueError("Temperature grids differ: positional comparison is invalid")
        key = (old["length_angstrom"], new["length_angstrom"])
        saved_rows = {r["temperature_K"]: r for r in stored[key]["rows"]}
        for index, temperature in enumerate(new["temperature_K"]):
            a = list(old["conventional_kappa_W_mK"][index][:3])
            b = list(new["conventional_kappa_W_mK"][index][:3])
            a.append(sum(a) / 3)
            b.append(sum(b) / 3)
            saved = saved_rows[temperature]
            recorded = saved["diagonal_relative_changes"] + [saved["trace_over_3_relative_change"]]
            all_pass = True
            for comp, prior, current, threshold, archived in zip(COMPONENTS, a, b, THRESHOLDS, recorded):
                if not math.isfinite(prior) or not math.isfinite(current) or current <= 0:
                    raise ValueError("Saved positive finite diagonal/trace values required")
                signed = (current - prior) / current
                change = abs(signed)
                if not math.isclose(change, archived, abs_tol=1e-13, rel_tol=1e-12):
                    raise ValueError("Recalculation differs from saved audit")
                passed = change < threshold
                all_pass = all_pass and passed
                rows.append(dict(from_density_length_A=key[0], to_density_length_A=key[1],
                                 temperature_K=temperature, component=comp,
                                 previous_kappa_W_mK=prior, current_kappa_W_mK=current,
                                 signed_change_over_current=signed, absolute_change_over_current=change,
                                 existing_strict_limit=threshold, change_over_limit=change / threshold,
                                 component_only_pass=passed))
            if all_pass != saved["passed"]:
                raise ValueError("Recomputed joint verdict differs from saved audit")
    return rows


def draw(rows: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    import numpy as np

    matplotlib.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none",
                               "svg.hashsalt": "rb-saved-component-diagnostics-v1"})
    temperatures = sorted({r["temperature_K"] for r in rows})
    transitions = sorted({(r["from_density_length_A"], r["to_density_length_A"]) for r in rows})
    cmap = ListedColormap(["#d9eee7", "#f5d9c7", "#df997c", "#b65248"])
    norm = BoundaryNorm([0, 1, 2, 3, 5], cmap.N)
    fig, axes = plt.subplots(1, len(temperatures), figsize=(13.6, 5.1), facecolor="#fafaf5")
    fig.subplots_adjust(left=.065, right=.91, top=.73, bottom=.27, wspace=.36)
    fig.text(.04, .93, "Rb2Cu2SnS4 | What the average conceals", size=21, weight="bold", color="#17363b")
    fig.text(.04, .86, "SAVED DIAGNOSTIC  /  NOT ACCEPTED LATTICE THERMAL CONDUCTIVITY", size=10, color="#a14b3b")
    for ax, temp in zip(axes, temperatures):
        selected = {(r["component"], (r["from_density_length_A"], r["to_density_length_A"])): r for r in rows if r["temperature_K"] == temp}
        ratios = np.array([[selected[(c, t)]["change_over_limit"] for t in transitions] for c in COMPONENTS])
        im = ax.imshow(ratios, cmap=cmap, norm=norm, aspect="auto")
        ax.set_title(f"{temp:g} K", loc="left", fontsize=14, color="#17363b", pad=14)
        ax.set_xticks(range(4), [f"{a:g}→{b:g}" for a, b in transitions], fontsize=10)
        ax.set_yticks(range(4), ["xx", "yy", "zz", "trace/3"], fontsize=10)
        ax.tick_params(length=0, pad=8)
        ax.set_xticks(np.arange(-.5, 4, 1), minor=True)
        ax.set_yticks(np.arange(-.5, 4, 1), minor=True)
        ax.grid(which="minor", color="#fafaf5", linewidth=3)
        ax.tick_params(which="minor", bottom=False, left=False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for i, comp in enumerate(COMPONENTS):
            for j, transition in enumerate(transitions):
                r = selected[(comp, transition)]
                ax.text(j, i, f'{100*r["absolute_change_over_current"]:.2f}%', ha="center", va="center",
                        fontsize=11, color="white" if r["change_over_limit"] >= 3 else "#17363b")
    cax = fig.add_axes([.93, .30, .014, .37])
    cb = fig.colorbar(im, cax=cax, ticks=[.5, 1.5, 2.5, 4])
    cb.ax.set_yticklabels(["<1", "1–2", "2–3", "3–5"])
    cb.ax.tick_params(labelsize=8, length=0)
    cb.outline.set_visible(False)
    fig.text(.925, .73, "Change /\ncriterion", size=9, color="#52696b")
    fig.text(.04, .16, "Columns: q-mesh density length (Å), not real-space cutoff or supercell size.", size=10, color="#52696b")
    fig.text(.04, .105, "Cell values: |new − old| / |new|. Strict limits: each diagonal <5%; trace/3 <3%.", size=10, color="#52696b")
    fig.text(.04, .05, "All 12 zz checks fail. A green cell alone is not acceptance: all temperatures and two consecutive joint passes are required.", size=10, color="#17363b")
    fig.savefig(HERE / "rb_component_changes.svg", facecolor=fig.get_facecolor(), metadata={"Date": None})
    svg = HERE / "rb_component_changes.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    fig.savefig(HERE / "rb_component_changes.png", dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    rows = extract(json.loads(SOURCE.read_text()))
    with (HERE / "component_changes.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {"source_path": str(SOURCE.relative_to(ROOT)),
               "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               "scope": "reanalysis_of_saved_audit_only; no new calculation or HDF5 verification",
               "scientific_acceptance": False, "recomputed_and_crosschecked_values": len(rows),
               "zz_checks": sum(r["component"] == "zz" for r in rows),
               "zz_passing_checks": sum(r["component"] == "zz" and r["component_only_pass"] for r in rows),
               "trace_only_passing_checks": sum(r["component"] == "trace/3" and r["component_only_pass"] for r in rows)}
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    draw(rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

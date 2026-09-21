#!/usr/bin/env python3
"""Build the offline phonon evidence-dashboard data from saved repository evidence.

This script deliberately reads the compact Rb HDF5 audit rather than reopening
large HDF5 files.  The audit is the saved, bounded read-only artifact record.
It creates no scientific result: it preserves the audit's rejected status.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "experiments/phonon_research_sandbox/results"
AUDIT = ROOT / (
    "thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/"
    "production/postprocess_22312417_hdf5_readonly_audit_20260920.json"
)
SUMMARY = ROOT / (
    "thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/"
    "production/postprocess_22312417_evidence_summary_20260920.json"
)

COMPONENTS = ("xx", "yy", "zz", "yz", "xz", "xy")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_over_3(values: list[float]) -> float:
    return sum(values[:3]) / 3.0


def write_chart_svg(ladder: list[dict]) -> None:
    """Write a standalone 300 K diagnostic SVG suitable for slide placement."""
    def x(index: int) -> float:
        return 75 + index * 150

    def y(value: float) -> float:
        return 263 - value / 0.16 * 215

    colours = ("#257278", "#c66a3d", "#72578c", "#3c8d63")
    labels = ("kappa xx", "kappa yy", "kappa zz", "trace/3")
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="500" viewBox="0 0 760 315" role="img">',
        '<rect width="760" height="315" fill="#fbfcf9"/>',
        '<text x="18" y="30" fill="#597177" font-family="Arial, sans-serif" font-size="12">Rb2Cu2SnS4 · 300 K saved q-mesh diagnostic · rejected, not accepted kappa_L</text>',
        '<text x="10" y="150" fill="#597177" font-family="Arial, sans-serif" font-size="11" transform="rotate(-90 10 150)">kappa (W m-1 K-1)</text>',
        '<text x="205" y="302" fill="#597177" font-family="Arial, sans-serif" font-size="10">mesh density length (A); this is not a pair cutoff</text>',
    ]
    for value in (0, .04, .08, .12, .16):
        parts.append(f'<line x1="65" y1="{y(value):.2f}" x2="730" y2="{y(value):.2f}" stroke="#dde5df"/>')
        parts.append(f'<text x="25" y="{y(value)+4:.2f}" fill="#597177" font-family="Arial, sans-serif" font-size="11">{value:.2f}</text>')
    for index, level in enumerate(ladder):
        parts.append(f'<text x="{x(index)-14:.2f}" y="285" fill="#597177" font-family="Arial, sans-serif" font-size="11">{level["length_angstrom"]:.0f} A</text>')
    for comp_index, (colour, label) in enumerate(zip(colours, labels)):
        values = []
        for index, level in enumerate(ladder):
            tensor = level["conventional_kappa_W_mK"][0]
            value = trace_over_3(tensor) if comp_index == 3 else tensor[comp_index]
            values.append((x(index), y(value)))
        points = " ".join(f"{px:.2f},{py:.2f}" for px, py in values)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2.5"/>')
        parts.append(f'<text x="{75 + comp_index * 125}" y="307" fill="{colour}" font-family="Arial, sans-serif" font-size="11">{label}</text>')
        parts.extend(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3.5" fill="{colour}"/>' for px, py in values)
    parts.append('</svg>\n')
    (ROOT / "experiments/phonon_research_sandbox/dashboard/rb_qmesh_diagnostic_300K.svg").write_text("".join(parts))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    audit = json.loads(AUDIT.read_text())
    summary = json.loads(SUMMARY.read_text())
    ladder = sorted(audit["qmesh_ladder"], key=lambda row: row["length_angstrom"])
    steps = {(row["from"], row["to"]): row for row in audit["qmesh_steps"]}
    rows: list[dict] = []
    for i, level in enumerate(ladder):
        previous = ladder[i - 1] if i else None
        for temp_i, temp in enumerate(level["temperature_K"]):
            values = level["conventional_kappa_W_mK"][temp_i]
            prior_values = previous["conventional_kappa_W_mK"][temp_i] if previous else None
            for comp_i, component in enumerate(COMPONENTS):
                value = values[comp_i]
                prior = prior_values[comp_i] if prior_values else None
                # Off-diagonal terms are numerical near-zero values. Their relative
                # changes have no useful interpretation because the denominator is near zero.
                near_zero = component in ("yz", "xz", "xy")
                # This follows the archived gate: |new - old| / |new|.
                # The explicit denominator makes this convention reviewable.
                rel = None if prior is None or near_zero else abs(value - prior) / abs(value)
                rows.append({
                    "length_angstrom": level["length_angstrom"], "mesh": "x".join(map(str, level["mesh"])),
                    "temperature_K": temp, "component": component,
                    "kappa_W_mK": value, "previous_length_angstrom": previous["length_angstrom"] if previous else None,
                    "previous_kappa_W_mK": prior, "relative_change_abs_over_abs_current": rel,
                    "denominator_abs_current_W_mK": abs(value) if prior is not None else None,
                    "relative_change_note": "not evaluated: off-diagonal value is numerical near-zero" if near_zero and prior is not None else "",
                })
            current_trace = trace_over_3(values)
            prior_trace = trace_over_3(prior_values) if prior_values else None
            rows.append({
                "length_angstrom": level["length_angstrom"], "mesh": "x".join(map(str, level["mesh"])),
                "temperature_K": temp, "component": "trace_over_3",
                "kappa_W_mK": current_trace, "previous_length_angstrom": previous["length_angstrom"] if previous else None,
                "previous_kappa_W_mK": prior_trace,
                "relative_change_abs_over_abs_current": abs(current_trace - prior_trace) / abs(current_trace) if prior_trace else None,
                "denominator_abs_current_W_mK": abs(current_trace) if prior_trace is not None else None,
                "relative_change_note": "",
            })

    csv_path = OUT / "rb_qmesh_ladder_all_tensors.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    stage_rows = []
    for (from_length, to_length), step in steps.items():
        for row in step["rows"]:
            stage_rows.append({
                "from_angstrom": from_length, "to_angstrom": to_length,
                "temperature_K": row["temperature_K"], "passed": row["passed"],
                "xx_relative_change": row["diagonal_relative_changes"][0],
                "yy_relative_change": row["diagonal_relative_changes"][1],
                "zz_relative_change": row["diagonal_relative_changes"][2],
                "trace_over_3_relative_change": row["trace_over_3_relative_change"],
                "denominator": "absolute value at current mesh",
            })

    data = {
        "generated_from": "saved repository evidence only; no live cluster query",
        "rb_qmesh_status": "rejected_diagnostic_only",
        "qmesh_converged": audit["qmesh_converged"],
        "temperatures_K": ladder[0]["temperature_K"],
        "components": list(COMPONENTS) + ["trace_over_3"],
        "ladder": ladder,
        "consecutive_changes": stage_rows,
        "scientific_boundary": summary["interpretation_boundary"],
        "audit_metadata": {
            "collected_utc": audit["collected_utc"],
            "fc2_sha256": audit["force_constants"]["fc2"]["sha256"],
            "fc3_sha256": audit["force_constants"]["fc3"]["sha256"],
            "audit_sha256": sha256(AUDIT),
            "summary_sha256": sha256(SUMMARY),
            "csv_sha256": sha256(csv_path),
        },
    }
    data_path = OUT / "dashboard_data.json"
    data_path.write_text(json.dumps(data, indent=2) + "\n")
    write_chart_svg(ladder)
    # Keep the reader genuinely offline: browsers can open index.html directly
    # without fetch/file-URL restrictions or any network access.
    page = ROOT / "experiments/phonon_research_sandbox/dashboard/index.html"
    text = page.read_text()
    replacement = "window.DASHBOARD_DATA = " + json.dumps(data, ensure_ascii=False) + ";</script>"
    rebuilt, count = re.subn(r"window\.DASHBOARD_DATA = .*?;</script>", replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"dashboard data marker missing from {page}")
    page.write_text(rebuilt)


if __name__ == "__main__":
    main()

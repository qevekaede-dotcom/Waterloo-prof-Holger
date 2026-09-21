#!/usr/bin/env python3
"""Regenerate the Rb2Cu2SnS4 saved-data reuse inventory without reading HDF5.

This script deliberately consumes only small, committed manifests/audits.  A
hash recorded by a past remote audit is evidence about that audit date; it is
not a claim that the corresponding remote file exists in this checkout today.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914"
OUT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(relative: str) -> tuple[Path, dict]:
    path = ROOT / relative
    return path, json.loads(path.read_text())


def source(path: Path, recorded_sha256: str | None = None) -> dict:
    actual = sha256(path)
    return {
        "path": str(path.relative_to(ROOT)),
        "local_present": path.is_file(),
        "local_sha256": actual,
        "recorded_sha256": recorded_sha256,
        "matches_recorded_sha256": None if recorded_sha256 is None else actual == recorded_sha256,
    }


def local_candidate_artifacts() -> list[dict]:
    """Inventory only explicit checkout locations; do not turn remote paths into files."""
    candidates = ["production/FORCES_FC3", "production/fc2.hdf5", "production/fc3.hdf5"]
    return [
        {
            "artifact": Path(relative).name,
            "local_candidate_path": str((EVIDENCE / relative).relative_to(ROOT)),
            "local_present": (EVIDENCE / relative).is_file(),
        }
        for relative in candidates
    ]


def qmesh_reuse_ready_now(local_sources: list[dict], local_artifacts: list[dict], settings_uniform: bool) -> bool:
    """Never promote readiness here: this inventory does not validate FC bytes/schema."""
    del local_sources, local_artifacts, settings_uniform
    return False


def yaml_supercell_and_amplitude(path: Path) -> tuple[list[list[int]], float, str]:
    """Extract only values literally present in the archived YAML, in atomic units."""
    text = path.read_text()
    unit = re.search(r"^physical_unit:\n(?:.*\n)*?\s+length:\s*([^\s#]+)", text, re.MULTILINE)
    matrix_text = re.search(r"supercell_matrix:\n((?:- \[.*\]\n){3})", text)
    displacement = re.search(r"displacement:\n\s*\[\s*([^,]+),\s*([^,]+),\s*([^\]]+)\]", text)
    if not unit or unit.group(1).strip('"').lower() not in {"au", "bohr"}:
        raise ValueError("archived YAML must explicitly declare physical_unit.length as au or bohr")
    if not matrix_text or not displacement:
        raise ValueError("expected supercell matrix or first displacement is absent from archived YAML")
    matrix = [[int(x) for x in re.findall(r"-?\d+", row)] for row in matrix_text.group(1).splitlines()]
    vector = [float(displacement.group(i)) for i in range(1, 4)]
    return matrix, math.sqrt(sum(component * component for component in vector)), unit.group(1).strip('"')


def main() -> None:
    manifest_path, manifest = load("thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/force_manifest.json")
    audit_path, audit = load("thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json")
    summary_path, summary = load("thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_evidence_summary_20260920.json")
    preflight_path, preflight = load("thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/preflight/preflight_summary.json")
    yaml_path = ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/preflight/phono3py_disp.yaml"
    pilot_sacct = EVIDENCE / "pilot/sacct.txt"

    campaign_path, campaign = load("thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json")
    tasks = manifest["tasks"]
    settings = {json.dumps({k: t[k] for k in ("ecutwfc_Ry", "ecutrho_Ry", "kmesh", "conv_thr_Ry", "nosym", "noinv", "expected_atoms")}, sort_keys=True) for t in tasks}
    fc = audit["force_constants"]
    dataset = audit["dataset"]

    local_sources = [
        source(manifest_path, audit["production"]["manifest_sha256"]),
        source(audit_path),
        source(summary_path),
        source(yaml_path, manifest["dataset_sha256"]),
        source(pilot_sacct),
        source(campaign_path),
        source(preflight_path),
    ]
    local_artifacts = local_candidate_artifacts()
    supercell_matrix, amplitude_bohr, yaml_length_unit = yaml_supercell_and_amplitude(yaml_path)
    settings_variants = [json.loads(x) for x in sorted(settings)]
    settings_uniform = len(settings_variants) == 1
    matching_preflight = [candidate for candidate in preflight["candidates"] if candidate["phono3py_disp_sha256"] == sha256(yaml_path)]
    if len(matching_preflight) != 1:
        raise ValueError("expected exactly one preflight candidate bound to the local YAML hash")
    saved_generation = matching_preflight[0]
    historic_remote = [
        {"artifact": "FORCES_FC3", "status": "historical_record_only", "why": "The local failure capture records a remote size, but no local bytes or SHA-256 are saved."},
        {"artifact": "fc2.hdf5", "status": "historical_remote_hash_verified", "sha256": fc["fc2"]["sha256"], "shape": fc["fc2"]["shape"], "dataset": fc["fc2"]["dataset"]},
        {"artifact": "fc3.hdf5", "status": "historical_remote_hash_verified", "sha256": fc["fc3"]["sha256"], "shape": fc["fc3"]["shape"], "dataset": fc["fc3"]["dataset"]},
    ]

    decisions = [
        {
            "change": "只改 q 网格（FC2/FC3 完全相同）",
            "classification": "conditional_reuse_after_one_bounded_remote_identity_check",
            "can_reuse": "保存审计所指的 fc2.hdf5、fc3.hdf5；已有五个 q-mesh HDF5 仅可作 rejected diagnostic。",
            "must_match": ["FC2/FC3 SHA-256", "phono3py 4.4.0", "18 primitive / 72 supercell", "p2s_map", "无 NAC 参数"],
            "missing_or_unverified": "本 checkout 没有 FC 本体；当前远端存在性和待计算 q 网格命令/版本未核实。",
        },
        {
            "change": "同一 M72 下把 FC3 cutoff 从 3.70 A 改大",
            "classification": "subset_reuse_unproven",
            "can_reuse": "只有未来更大-cutoff 数据集可把每个旧 displacement/configuration 的内容（原子、位移向量、pair、符号组合）映射到新数据集，并逐项核对结构/输入/输出/力哈希时，较大集合才可向小 cutoff 派生；数字 ID 本身可重编号，不能单独证明对应。",
            "must_match": ["内容级 displacement/configuration mapping（非仅数字 ID）", "72 atoms", "atom order/p2s_map", "pristine subtraction", "结构、赝势、100/800 Ry、2x2x2、conv_thr、nosym/noinv"],
            "missing_or_unverified": "本地没有 4.25/5.00 A YAML、ID 清单、pair-shell 映射或力本体；不能证明包含关系。",
        },
        {
            "change": "几何、超胞、DFT 设置、赝势、位移幅度或 displacement 定义改变",
            "classification": "incompatible_by_construction_new_forces_required",
            "can_reuse": "可复用方法、输入模板和这份证据；不可复用现有生产力作新 FC 数据。",
            "must_match": ["不适用：响应函数的定义已改变"],
            "missing_or_unverified": "M108/M216、0.02/0.04 A、不同 cutoff 新 pair 均需要各自 pristine 和新 force dataset。",
        },
    ]

    timing = []
    for line in pilot_sacct.read_text().splitlines():
        cols = line.split("|")
        if len(cols) == 10:
            timing.append({"job_id": cols[0], "state": cols[2], "elapsed": cols[4], "alloc_cpus": int(cols[7]), "requested_memory": cols[8], "node": cols[9]})

    result = {
        "schema": "rb_saved_data_reuse_inventory/v1",
        "generated_from_small_local_records_only": True,
        "no_hdf5_read": True,
        "production_status": summary["interpretation_boundary"]["campaign_status"],
        "no_production": {
            "production_authorized": False,
            "accepted_kappa_L": False,
            "qmesh_reuse_ready_now": qmesh_reuse_ready_now(local_sources, local_artifacts, settings_uniform),
            "why_not_ready_now": ["FC identity verification not performed by this local inventory", "saved q-mesh ladder is rejected diagnostic"],
        },
        "local_sources": local_sources,
        "local_candidate_artifacts": local_artifacts,
        "force_dataset_schema": {
            "dataset_yaml_sha256": manifest["dataset_sha256"],
            "tasks": manifest["task_count"],
            "labels": {"first": tasks[0]["label"], "last": tasks[-1]["label"]},
            "unique_force_input_hashes": len({t["input_sha256"] for t in tasks}),
            "unique_source_structure_hashes": len({t["source_sha256"] for t in tasks}),
            "settings_variants": settings_variants,
            "settings_uniform": settings_uniform,
            "recorded_pseudopotential_sha256_not_local_bytes": manifest["pseudopotential_sha256"],
            "atom_mapping": {"primitive_atoms": dataset["primitive_atoms"], "supercell_atoms": dataset["supercell_atoms"], "fc_p2s_map": fc["fc2"]["p2s_map"]},
        },
        "historic_remote_artifacts": historic_remote,
        "geometry_and_settings_provenance": {
            "local_yaml": str(yaml_path.relative_to(ROOT)), "yaml_sha256": sha256(yaml_path),
            "supercell_matrix_from_yaml": supercell_matrix,
            "physical_unit_length_from_yaml": yaml_length_unit,
            "amplitude_bohr_from_first_yaml_displacement": amplitude_bohr,
            "amplitude_angstrom_derived_from_bohr": amplitude_bohr * campaign["units"]["bohr_to_angstrom"],
            "saved_generation_record_bound_by_yaml_hash": {
                "source": str(preflight_path.relative_to(ROOT)),
                "source_sha256": sha256(preflight_path),
                "candidate": saved_generation["candidate"],
                "phono3py_disp_sha256": saved_generation["phono3py_disp_sha256"],
                "manifest_dataset_sha256": manifest["dataset_sha256"],
                "generation_argv": saved_generation["command"],
                "cutoff_pair_distance_angstrom": saved_generation["cutoff_pair_distance_angstrom"],
                "cutoff_pair_distance_bohr": saved_generation["cutoff_pair_distance_bohr"],
                "displacement_supercells": saved_generation["displacement_supercells"],
                "caveat": "This saved generation record binds the cutoff to the archived YAML; it does not prove current remote FC/FORCES bytes or scientific convergence.",
            },
            "production_settings": settings_variants[0] if settings_uniform else None,
            "phono3py_version": audit["phono3py_version"],
        },
        "reuse_decisions": decisions,
        "one_bounded_future_remote_check": [
            "Minimal q-mesh-only FC identity check: stat and SHA-256 FC2, FC3, phono3py_disp.yaml, and production force manifest; no q-mesh solve and no full kappa-HDF5 reread.",
            "Read (do not solve) FC2/FC3 keys, shapes, dtype, p2s_map, version and confirm 18/72 atom binding; compare to this JSON.",
            "Optional lineage/archival checks: hash FORCES_FC3 when re-establishing force provenance, and hash the five saved kappa HDF5 files only if preserving historical diagnostics; neither is a q-mesh-only prerequisite.",
            "For a proposed larger cutoff: generate count-only YAML and an explicit content-level old-to-new displacement/configuration mapping plus per-item input/source/output/force hashes. Do not claim subset reuse if any item is unavailable.",
        ],
        "recorded_timing_only": {
            "source": str(pilot_sacct.relative_to(ROOT)),
            "column_interpretation": {
                "status": "inferred_not_header_preserved",
                "pilot_columns": ["JobIDRaw", "JobName", "State", "ExitCode", "Elapsed", "Start", "End", "AllocCPUS", "ReqMem", "NodeList"],
                "basis": "The current postprocess sbatch explicitly records the same ordered sacct fields with MaxRSS inserted before NodeList; pilot capture has ten columns and no header, so MaxRSS is absent from this capture.",
                "documented_schema_source": "thermo_candidates/Rb2Cu2SnS4/phono3py/run_postprocess_firstpass.sbatch:26-29",
            },
            "records": timing,
            "applicability": "Seven-task M72 pilot scheduler records; not a core-hour forecast for cutoff, supercell, or production.",
        },
        "scientific_boundary": "No accepted kappa_L: every saved q-mesh transition failed, and FC physical convergence is not established.",
    }
    (OUT / "rb_reuse_inventory.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    with (OUT / "rb_reuse_decisions.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["change", "classification", "can_reuse", "must_match", "missing_or_unverified"], lineterminator="\n")
        writer.writeheader()
        for row in decisions:
            writer.writerow({**row, "must_match": "; ".join(row["must_match"])})


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Strictly audit an Rb first-pass pilot or production force set."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


BENIGN_STDERR_LINES = {
    "Note: The following floating-point exceptions are signalling: "
    "IEEE_UNDERFLOW_FLAG IEEE_DENORMAL",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_qe_output(path: Path):
    spec = importlib.util.spec_from_file_location("qe_output", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import strict parser from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-dir", type=Path, required=True)
    parser.add_argument("--qe-output-parser", type=Path, required=True)
    parser.add_argument("--mode", choices=("pilot", "production"), required=True)
    args = parser.parse_args()
    qe = load_qe_output(args.qe_output_parser)
    force_dir = args.force_dir.resolve(strict=True)
    manifest_path = force_dir / "force_manifest.json"
    task_map_path = force_dir / "task_map.tsv"
    manifest = json.loads(manifest_path.read_text())
    global_errors: list[str] = []
    tasks = manifest.get("tasks", [])
    if manifest.get("task_count") != len(tasks):
        global_errors.append("manifest task count mismatch")
    if len({task.get("label") for task in tasks}) != len(tasks):
        global_errors.append("manifest task labels are not unique")
    dataset_path = Path(manifest["dataset"])
    if sha256(dataset_path) != manifest["dataset_sha256"]:
        global_errors.append("dataset SHA-256 differs from manifest")
    if len(task_map_path.read_text().splitlines()) != len(tasks) + 1:
        global_errors.append("task-map row count mismatch")
    reports: dict[str, dict[str, object]] = {}
    records = {}
    failures: list[str] = []
    for task in tasks:
        label = task["label"]
        input_path = Path(task["input"])
        source_path = Path(task["source"])
        task_dir = input_path.parent
        output = task_dir / "scf.out"
        stderr = task_dir / "scf.err"
        exit_code = task_dir / "exit_code.txt"
        try:
            report = qe.inspect_output(output, int(task["expected_atoms"]))
            record = qe.parse_last_force_block(output, int(task["expected_atoms"]))
            if task_dir.resolve().parent != force_dir:
                report["errors"].append("task directory escapes force directory")
            input_hash = sha256(input_path)
            source_hash = sha256(source_path)
            if input_hash != task["input_sha256"]:
                report["errors"].append("input SHA-256 differs from manifest")
            if source_hash != task["source_sha256"]:
                report["errors"].append("source SHA-256 differs from manifest")
            if exit_code.read_text().strip() != "0":
                report["errors"].append("nonzero pw.x exit")
            stderr_lines = [
                line.strip()
                for line in stderr.read_text().splitlines()
                if line.strip()
            ]
            unknown_stderr = sorted(set(stderr_lines) - BENIGN_STDERR_LINES)
            report["stderr_lines"] = stderr_lines
            report["benign_stderr_only"] = bool(stderr_lines) and not unknown_stderr
            report["provenance_sha256"] = {
                "input": input_hash,
                "source": source_hash,
                "output": sha256(output),
                "stderr": sha256(stderr),
                "exit_code": sha256(exit_code),
            }
            if unknown_stderr:
                report["errors"].append(
                    "unknown stderr: " + " | ".join(unknown_stderr)
                )
            report["healthy"] = not report["errors"]
            reports[label] = report
            records[label] = record
            if not report["healthy"]:
                failures.append(label)
        except Exception as exc:
            reports[label] = {"healthy": False, "error": str(exc)}
            failures.append(label)

    comparisons = {}
    if args.mode == "pilot" and not failures:
        comparisons["k222_to_k333_induced_force"] = qe.compare_force_records(
            records["disp00001_k222_hi"], records["disp00001_k333_hi"],
            records["pristine_k222_hi"], records["pristine_k333_hi"],
        )
        comparisons["80_640_to_100_800_induced_force"] = qe.compare_force_records(
            records["disp00001_k222_lo"], records["disp00001_k222_hi"],
            records["pristine_k222_lo"], records["pristine_k222_hi"],
        )
        comparisons["duplicate_raw_force"] = qe.compare_force_records(
            records["disp00001_k222_hi"], records["disp00001_k222_hi_dup"]
        )
        for comparison in comparisons.values():
            if comparison is comparisons["duplicate_raw_force"]:
                comparison["pass"] = bool(
                    comparison["rms_difference_ry_bohr"] <= 5e-6
                )
            else:
                comparison["pass"] = bool(
                    comparison["max_abs_difference_ry_bohr"] <= 5e-5
                    and comparison["rms_difference_ry_bohr"] <= 1e-5
                    and comparison["relative_rms_difference"] <= 0.02
                )
        pristine_pass = all(
            reports[label]["max_abs_force_ry_bohr"] <= 5e-5
            for label in ("pristine_k222_hi", "pristine_k333_hi", "pristine_k222_lo")
        )
        passed = (
            not global_errors
            and pristine_pass
            and all(item["pass"] for item in comparisons.values())
        )
    else:
        pristine = reports.get("pristine", {})
        pristine_pass = bool(pristine.get("healthy")) and pristine.get(
            "max_abs_force_ry_bohr", float("inf")
        ) <= 5e-5
        passed = not global_errors and not failures and pristine_pass

    result = {
        "document_type": f"rb_firstpass_{args.mode}_force_audit",
        "strict_parser": str(args.qe_output_parser.resolve(strict=True)),
        "provenance_sha256": {
            "audit_script": sha256(Path(__file__).resolve(strict=True)),
            "strict_parser": sha256(args.qe_output_parser.resolve(strict=True)),
            "force_manifest": sha256(manifest_path),
            "task_map": sha256(task_map_path),
            "dataset": sha256(Path(manifest["dataset"])),
        },
        "task_count": manifest["task_count"],
        "global_errors": global_errors,
        "failed_labels": failures,
        "reports": reports,
        "comparisons": comparisons,
        "pristine_residual_gate_ry_bohr": 5e-5,
        "comparison_max_gate_ry_bohr": 5e-5,
        "comparison_rms_gate_ry_bohr": 1e-5,
        "comparison_relative_rms_gate": 0.02,
        "duplicate_rms_gate_ry_bohr": 5e-6,
        "pass": passed,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

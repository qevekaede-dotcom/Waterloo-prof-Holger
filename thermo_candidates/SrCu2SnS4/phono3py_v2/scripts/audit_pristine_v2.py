#!/usr/bin/env python3
"""Bind shared QE parser health evidence to one v2 pristine input."""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
CAMPAIGN_SCRIPTS = PACKAGE.parents[1] / "scripts" / "phono3py_campaign"
CONFIG = json.loads((PACKAGE / "campaign.json").read_text())
sys.path.insert(0, str(CAMPAIGN_SCRIPTS))
from qe_output import QEOutputError, inspect_force_run  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_nat(path: Path) -> int:
    match = re.search(r"^\s*nat\s*=\s*(\d+)", path.read_text(), re.MULTILINE)
    if not match:
        raise ValueError("cannot read nat from pristine input")
    return int(match.group(1))


def read_exit_code(path: Path) -> int:
    text = path.read_text().strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError("exit-code evidence must contain one non-negative integer")
    return int(text)


def validate_expected_manifest_sha256(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("--expected-manifest-sha256 must be exactly 64 lowercase hexadecimal characters")
    return value


def validate_manifest_anchor(manifest_path: Path, expected: str) -> None:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("run manifest must be a regular in-run file")
    if sha256(manifest_path) != expected:
        raise ValueError("run manifest SHA-256 does not match the reviewed expected anchor")


def validate_pristine_manifest_binding(manifest_path: Path, pristine: Path) -> None:
    """Reject a changed or substituted pristine input before writing an audit."""
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or manifest.get("document_type") != "srcu_v2_run_manifest":
        raise ValueError("run manifest document type mismatch")
    input_hashes = manifest.get("input_sha256")
    if not isinstance(input_hashes, dict):
        raise ValueError("run manifest input fingerprint map is missing")
    if pristine.is_symlink() or not pristine.is_file():
        raise ValueError("pristine input must be a regular non-symlink file")
    if input_hashes.get("pristine/scf.in") != sha256(pristine):
        raise ValueError("pristine input fingerprint differs from the reviewed run manifest")
    if input_nat(pristine) != CONFIG["qe_force_input_contract"]["nat"]:
        raise ValueError("pristine input atom count differs from the v2 force contract")


def reject_unsafe_health_destinations(run_dir: Path) -> None:
    """Check every path this audit could create before creating any of them."""
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("RUN_DIR must be a real directory")
    for destination in (run_dir / "health", run_dir / "health/evidence"):
        if destination.is_symlink():
            raise ValueError(f"symlink is forbidden in audit destination: {destination}")
        if destination.exists() and not destination.is_dir():
            raise ValueError(f"audit destination is not a directory: {destination}")
    for target in (run_dir / "health/pristine_health.json",
                   run_dir / "health/evidence/pristine.stdout",
                   run_dir / "health/evidence/pristine.stderr",
                   run_dir / "health/evidence/pristine.exit_code"):
        if target.is_symlink():
            raise ValueError(f"symlink is forbidden in audit destination: {target}")
        if target.exists():
            raise ValueError(f"audit destination already exists; records are immutable: {target}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--qe-output", type=Path, required=True)
    ap.add_argument("--qe-stderr", type=Path, required=True)
    ap.add_argument("--exit-code", type=Path, required=True)
    ap.add_argument("--expected-manifest-sha256", required=True,
                    help="64-lowercase-hex digest retained from reviewed prepare_v2 output")
    args = ap.parse_args()
    run_dir = args.run_dir.absolute()
    expected_manifest_sha256 = validate_expected_manifest_sha256(args.expected_manifest_sha256)
    # This must precede every mkdir/write so health -> outside cannot receive evidence.
    reject_unsafe_health_destinations(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    validate_manifest_anchor(manifest_path, expected_manifest_sha256)
    pristine = run_dir / "forces/pristine/scf.in"
    validate_pristine_manifest_binding(manifest_path, pristine)
    raw_evidence = (args.qe_output.absolute(), args.qe_stderr.absolute(), args.exit_code.absolute())
    if any(path.is_symlink() for path in raw_evidence):
        raise ValueError("source evidence arguments must not be symlinks")
    output, stderr, exit_code = raw_evidence
    if not all(path.is_file() for path in (output, stderr, exit_code)):
        raise ValueError("QE output, stderr, and exit-code evidence are all required")
    evidence_dir = run_dir / "health/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for label, source in (("stdout", output), ("stderr", stderr), ("exit_code", exit_code)):
        target = evidence_dir / f"pristine.{label}"
        if target.exists() or target.is_symlink() or source.is_symlink():
            raise ValueError("evidence target exists or source is symlink")
        shutil.copyfile(source, target)
        copied[label] = target
    parser_path = CAMPAIGN_SCRIPTS / "qe_output.py"
    report = {"document_type": "srcu_v2_pristine_health", "input_sha256": sha256(pristine),
              "qe_output_sha256": sha256(copied["stdout"]), "qe_stderr_sha256": sha256(copied["stderr"]),
              "exit_code_sha256": sha256(copied["exit_code"]), "parser_sha256": sha256(parser_path),
              "evidence": {key: str(path.relative_to(run_dir)) for key, path in copied.items()},
              "manifest_sha256_anchor": expected_manifest_sha256,
              "execution_provenance_verified": False,
              "audit_scope": "terminal parser status for supplied QE logs; input-to-execution provenance is not verified",
              "exit_code": read_exit_code(copied["exit_code"])}
    try:
        report["parser_report"] = inspect_force_run(copied["stdout"], copied["stderr"], input_nat(pristine))
        report["healthy"] = report["parser_report"]["healthy"]
        report["errors"] = report["parser_report"]["errors"]
    except (QEOutputError, ValueError) as exc:
        report.update({"healthy": False, "errors": [f"shared parser failure: {exc}"]})
    if report["exit_code"] != 0:
        report["healthy"] = False
        report.setdefault("errors", []).append("nonzero process exit code")
    target = run_dir / "health/pristine_health.json"
    if target.exists() or target.is_symlink():
        raise ValueError("pristine health record already exists; records are immutable")
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"pristine_health": report, "pristine_health_sha256": sha256(target)},
                     indent=2, sort_keys=True))
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(f"FAIL-CLOSED: {exc}")

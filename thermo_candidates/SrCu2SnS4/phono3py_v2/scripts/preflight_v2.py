#!/usr/bin/env python3
"""Fail-closed input-contract preflight. It never executes or submits work."""
import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from dataset_semantics import inspect_dataset
import sys

PACKAGE = Path(__file__).resolve().parents[1]
CAMPAIGN_SCRIPTS = PACKAGE.parents[1] / "scripts" / "phono3py_campaign"
sys.path.insert(0, str(CAMPAIGN_SCRIPTS))
from qe_output import inspect_force_run

CONFIG = json.loads((PACKAGE / "campaign.json").read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_exit_code(path: Path) -> int:
    text = path.read_text().strip()
    require(re.fullmatch(r"[0-9]+", text) is not None,
            "retained exit-code evidence must contain one non-negative integer")
    return int(text)


def validate_expected_sha256(value: str, option: str) -> str:
    require(re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            f"{option} must be exactly 64 lowercase hexadecimal characters")
    return value


def validate_manifest_anchor(manifest_path: Path, expected: str) -> None:
    require(manifest_path.is_file() and not manifest_path.is_symlink(),
            "run manifest must be a regular in-run file")
    require(sha256(manifest_path) == expected,
            "run manifest SHA-256 does not match the reviewed expected anchor")


def settings_fingerprint(path: Path) -> str:
    text = path.read_text()
    required = {
        "ecutwfc": "90", "ecutrho": "720", "conv_thr": "1d-09",
        "occupations": "fixed", "tprnfor": ".true.", "nosym": ".true.", "noinv": ".true."
    }
    normalized = []
    for key, value in required.items():
        match = re.search(rf"^\s*{key}\s*=\s*'?([^,\n']+)'?", text, re.MULTILINE | re.IGNORECASE)
        require(match is not None and match.group(1).strip().lower() == value, f"{path}: {key} contract mismatch")
        normalized.append(f"{key}={value}")
    nat = re.search(r"^\s*nat\s*=\s*(\d+)", text, re.MULTILINE)
    ntyp = re.search(r"^\s*ntyp\s*=\s*(\d+)", text, re.MULTILINE)
    require(nat and int(nat.group(1)) == 96 and ntyp and int(ntyp.group(1)) == 4, f"{path}: nat/ntyp mismatch")
    k = re.search(r"K_POINTS automatic\s*\n\s*3\s+3\s+3\s+0\s+0\s+0", text, re.IGNORECASE)
    require(k is not None, f"{path}: k-point contract mismatch")
    require("CELL_PARAMETERS bohr" in text, f"{path}: QE cell length unit is not explicit bohr")
    require("ATOMIC_POSITIONS crystal" in text, f"{path}: missing crystal atomic positions")
    pseudo = re.search(r"^\s*pseudo_dir\s*=\s*'((?:''|[^'])*)'", text, re.MULTILINE)
    require(pseudo is not None and pseudo.group(1).replace("''", "'") == str(_MANIFEST_PSEUDO_DIR), f"{path}: pseudo_dir mismatch")
    species = re.search(r"ATOMIC_SPECIES\s*\n(.*?)(?=ATOMIC_POSITIONS)", text, re.IGNORECASE | re.DOTALL)
    require(species is not None, f"{path}: missing ATOMIC_SPECIES")
    filenames = []
    for line in species.group(1).splitlines():
        parts = line.split()
        require(len(parts) == 3, f"{path}: malformed ATOMIC_SPECIES entry")
        filenames.append(parts[2])
    expected = CONFIG["qe_force_input_contract"]["pseudopotential_files"]
    observed = {line.split()[0]: line.split()[2] for line in species.group(1).splitlines() if line.split()}
    require(observed == expected, f"{path}: pseudopotential element-to-filename mapping mismatch")
    return hashlib.sha256("\n".join(normalized + ["nat=96", "ntyp=4", "k=3,3,3,0,0,0"]).encode()).hexdigest()


def validate_live_pseudos(manifest: dict) -> None:
    pseudo_dir = Path(manifest["pseudo_dir"])
    require(pseudo_dir.is_absolute() and pseudo_dir.is_dir() and not pseudo_dir.is_symlink(), "stored pseudo_dir is not a real absolute directory")
    expected = CONFIG["qe_force_input_contract"]["pseudopotential_files"].values()
    for filename in expected:
        path = pseudo_dir / filename
        require(path.exists() and not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), f"configured pseudopotential is not a regular file: {filename}")
        require(sha256(path) == manifest["pseudopotential_sha256"][filename], f"pseudopotential fingerprint changed: {filename}")


def reject_symlinks(root: Path) -> None:
    require(not root.is_symlink(), "RUN_DIR must not be a symlink")
    for path in root.rglob("*"):
        require(not path.is_symlink(), f"symlink is forbidden in controlled evidence: {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--expected-manifest-sha256", required=True,
                    help="64-lowercase-hex digest retained from reviewed prepare_v2 output")
    ap.add_argument("--expected-health-sha256", required=True,
                    help="64-lowercase-hex digest retained from reviewed audit_pristine_v2 output")
    args = ap.parse_args()
    run_dir = args.run_dir.absolute()
    expected_manifest_sha256 = validate_expected_sha256(args.expected_manifest_sha256,
                                                        "--expected-manifest-sha256")
    expected_health_sha256 = validate_expected_sha256(args.expected_health_sha256,
                                                      "--expected-health-sha256")
    require(run_dir.is_dir() and not run_dir.is_symlink(), "RUN_DIR must be a real directory")
    reject_symlinks(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    pristine = run_dir / "forces/pristine/scf.in"
    health_path = run_dir / "health/pristine_health.json"
    require(manifest_path.is_file() and pristine.is_file() and health_path.is_file(), "manifest, pristine input, and healthy pristine audit are required")
    validate_manifest_anchor(manifest_path, expected_manifest_sha256)
    require(not health_path.is_symlink() and sha256(health_path) == expected_health_sha256,
            "pristine health SHA-256 does not match the reviewed expected anchor")
    manifest, health = json.loads(manifest_path.read_text()), json.loads(health_path.read_text())
    global _MANIFEST_PSEUDO_DIR
    _MANIFEST_PSEUDO_DIR = Path(manifest["pseudo_dir"])
    require(manifest["config_sha256"] == sha256(PACKAGE / "campaign.json"), "configuration fingerprint changed")
    require(manifest["source_unitcell_sha256"] == CONFIG["source_unitcell"]["sha256"], "source unitcell fingerprint changed")
    require(manifest["preparer_sha256"] == sha256(PACKAGE / "scripts/prepare_v2.py"), "preparer fingerprint changed")
    require(manifest["dataset_semantics_validator_sha256"] == sha256(PACKAGE / "scripts/dataset_semantics.py"), "dataset semantics validator fingerprint changed")
    require(set(manifest["pseudopotential_sha256"]) == set(CONFIG["qe_force_input_contract"]["pseudopotential_files"].values()), "pseudopotential manifest is incomplete")
    validate_live_pseudos(manifest)
    dataset = manifest["dataset_sha256"]
    require(set(dataset) == {"inputs/unitcell.in", "inputs/supercell.in", "inputs/phono3py_disp.yaml"}, "dataset manifest is incomplete")
    for relative, expected_hash in dataset.items():
        path = run_dir / relative
        require(path.is_file() and sha256(path) == expected_hash, f"dataset fingerprint changed: {relative}")
    semantic_path = run_dir / "dataset_semantics.json"
    require(semantic_path.is_file() and sha256(semantic_path) == manifest["dataset_semantics_sha256"], "dataset semantics fingerprint changed")
    require(json.loads(semantic_path.read_text()) == inspect_dataset(run_dir / "inputs"), "dataset semantics do not replay")
    require(manifest["qe_execution_released"] is False and manifest["slurm_submission_released"] is False, "manifest release state is unsafe")
    parser_path = PACKAGE.parents[1] / "scripts" / "phono3py_campaign" / "qe_output.py"
    require(health.get("document_type") == "srcu_v2_pristine_health", "pristine health document type mismatch")
    require(health.get("healthy") is True and health.get("input_sha256") == sha256(pristine), "pristine is not healthy for this exact input")
    require(health.get("manifest_sha256_anchor") == expected_manifest_sha256,
            "pristine health record does not agree with the reviewed manifest anchor")
    require(health.get("parser_sha256") == sha256(parser_path), "shared QE parser fingerprint changed")
    evidence = health.get("evidence")
    canonical_evidence = {
        "stdout": "health/evidence/pristine.stdout",
        "stderr": "health/evidence/pristine.stderr",
        "exit_code": "health/evidence/pristine.exit_code",
    }
    require(evidence == canonical_evidence,
            "pristine evidence paths must exactly equal the canonical in-run evidence mapping")
    evidence_paths = {key: run_dir / relative for key, relative in evidence.items()}
    require(all(path.is_file() and not path.is_symlink() for path in evidence_paths.values()), "pristine evidence must be regular in-run files")
    require(sha256(evidence_paths["stdout"]) == health["qe_output_sha256"] and sha256(evidence_paths["stderr"]) == health["qe_stderr_sha256"] and sha256(evidence_paths["exit_code"]) == health["exit_code_sha256"], "pristine evidence fingerprint changed")
    retained_exit_code = read_exit_code(evidence_paths["exit_code"])
    require(type(health.get("exit_code")) is int and health["exit_code"] == retained_exit_code,
            "retained exit-code evidence disagrees with the pristine health record")
    require(retained_exit_code == 0, "retained pristine process exit code is not zero")
    replay = inspect_force_run(evidence_paths["stdout"], evidence_paths["stderr"], 96)
    require(replay == health.get("parser_report") and replay["healthy"] is True, "pristine shared-parser replay differs")
    displacements = sorted((run_dir / "forces").glob("disp-*/scf.in"))
    minimum = CONFIG["qe_force_input_contract"]["minimum_displacement_inputs"]
    require(len(displacements) >= minimum, f"need at least {minimum} displacement inputs")
    paths = [pristine] + displacements
    observed_hashes = {str(path.relative_to(run_dir / "forces")): sha256(path) for path in paths}
    require(observed_hashes == manifest["input_sha256"], "input fingerprint mismatch or untracked input")
    setting_hashes = {settings_fingerprint(path) for path in paths}
    require(len(setting_hashes) == 1, "QE settings are not uniform")
    target = run_dir / "preflight_report.json"
    require(not target.exists(), "preflight report already exists; use a fresh RUN_DIR")
    report = {"document_type": "srcu_v2_preflight", "healthy_pristine": True,
              "displacement_input_count": len(displacements), "uniform_setting_fingerprint": setting_hashes.pop(),
              "input_sha256": observed_hashes, "force_execution_released": False,
              "slurm_submission_released": False, "manifest_sha256_anchor": expected_manifest_sha256,
              "pristine_health_sha256_anchor": expected_health_sha256,
              "preflight_passed": True}
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL-CLOSED: {exc}")

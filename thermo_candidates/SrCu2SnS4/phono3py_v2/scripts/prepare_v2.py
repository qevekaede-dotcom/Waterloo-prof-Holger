#!/usr/bin/env python3
"""Create an isolated v2 input tree; default is a non-mutating dry run."""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from dataset_semantics import inspect_dataset

PACKAGE = Path(__file__).resolve().parents[1]
REPOSITORY = PACKAGE.parents[2]
CONFIG_PATH = PACKAGE / "campaign.json"
DATASET_VALIDATOR_PATH = PACKAGE / "scripts/dataset_semantics.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def reject_unsafe_run_dir(run_dir: Path) -> None:
    if run_dir.is_symlink():
        raise ValueError("RUN_DIR must not be a symlink, including a dangling symlink")
    if run_dir.exists():
        raise ValueError("RUN_DIR must not already exist; use a fresh empty lineage")


def safe_qe_string(value: str) -> str:
    if any(character in value for character in "\r\n\x00"):
        raise ValueError("QE path contains a control character")
    return value.replace("'", "''")


def validate_pseudo_dir(argument: str, config: dict) -> tuple[Path, dict[str, str]]:
    raw = Path(argument)
    if not raw.is_absolute() or raw.is_symlink() or not raw.is_dir():
        raise ValueError("--pseudo-dir must be an absolute real directory, not a symlink")
    pseudo_dir = raw.resolve(strict=True)
    hashes: dict[str, str] = {}
    for filename in config["qe_force_input_contract"]["pseudopotential_files"].values():
        candidate = pseudo_dir / filename
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValueError(f"missing configured pseudopotential: {filename}") from exc
        if candidate.is_symlink() or not stat.S_ISREG(mode):
            raise ValueError(f"pseudopotential must be a regular non-symlink file: {filename}")
        hashes[filename] = sha256(candidate)
    return pseudo_dir, hashes


def resolve_generator(argument: str) -> Path:
    candidate = Path(argument) if "/" in argument else Path(shutil.which(argument) or "")
    if not candidate.is_absolute() or not candidate.exists():
        raise ValueError("phono3py-init executable cannot be resolved")
    resolved = candidate.resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode) or not os.access(resolved, os.X_OK):
        raise ValueError("phono3py-init must resolve to a regular executable file")
    return resolved


def qe_input(fragment: Path, config: dict, pseudo_dir: str) -> str:
    lines = fragment.read_text().splitlines()
    first = lines[0]
    nat = int(first.split("nat =")[1].split(",")[0])
    ntyp = int(first.split("ntyp =")[1].split()[0])
    contract = config["qe_force_input_contract"]
    if nat != contract["nat"] or ntyp != contract["ntyp"]:
        raise ValueError(f"{fragment.name}: expected nat/ntyp {contract['nat']}/{contract['ntyp']}")
    k = contract["k_points_automatic"]
    return f"""&CONTROL
  calculation = 'scf',
  tprnfor = .true.,
  disk_io = 'none',
  outdir = './tmp',
  prefix = 'srcu_v2',
  pseudo_dir = '{pseudo_dir}',
  restart_mode = 'from_scratch',
  verbosity = 'high',
/
&SYSTEM
  ecutrho = {contract['ecutrho_ry']},
  ecutwfc = {contract['ecutwfc_ry']},
  occupations = '{contract['occupations']}',
  nosym = .true.,
  noinv = .true.,
  ibrav = 0,
  nat = {nat},
  ntyp = {ntyp},
/
&ELECTRONS
  conv_thr = {contract['conv_thr']},
  diagonalization = 'david',
  electron_maxstep = 200,
  mixing_beta = 0.3,
/
""" + "\n".join(lines[1:]) + f"\nK_POINTS automatic\n  {' '.join(map(str, k))}\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--generate-displacements", action="store_true")
    ap.add_argument("--pseudo-dir", help="required only with --generate-displacements")
    ap.add_argument("--phono3py-init", default="phono3py-init", help="explicit phono3py-init executable for reviewed local generation")
    args = ap.parse_args()
    config = load_config()
    requested_run_dir = args.run_dir.absolute()
    reject_unsafe_run_dir(requested_run_dir)
    run_dir = requested_run_dir.resolve(strict=False)
    source = REPOSITORY / config["source_unitcell"]["repository_path"]
    if sha256(source) != config["source_unitcell"]["sha256"]:
        raise ValueError("source unitcell fingerprint mismatch; stop and investigate")
    plan = {
        "mode": "generate_displacements" if args.generate_displacements else "dry_run",
        "run_dir": str(run_dir), "source_unitcell_sha256": sha256(source),
        "phono3py_command": config["phono3py"]["generation_command_template"],
        "qe_or_slurm_execution": "not performed by this script"
    }
    if not args.generate_displacements:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if not args.pseudo_dir:
        raise ValueError("--pseudo-dir is required when generating inputs")
    pseudo_dir, pseudo_hashes = validate_pseudo_dir(args.pseudo_dir, config)
    generator = resolve_generator(args.phono3py_init)
    run_dir.mkdir(parents=True, exist_ok=False)
    inputs = run_dir / "inputs"
    inputs.mkdir()
    shutil.copy2(source, inputs / "unitcell.in")
    command = [str(generator), *config["phono3py"]["generation_command_template"][1:]]
    subprocess.run(command, cwd=inputs, check=True)
    fragments = sorted(inputs.glob("supercell-*.in"))
    if len(fragments) < config["qe_force_input_contract"]["minimum_displacement_inputs"]:
        raise RuntimeError("generated fewer than 168 displacement fragments; abandon this RUN_DIR")
    force_dir = run_dir / "forces"
    force_dir.mkdir()
    pristine_fragment = inputs / "supercell.in"
    if not pristine_fragment.is_file():
        raise RuntimeError("phono3py did not produce supercell.in; abandon this RUN_DIR")
    dataset_paths = [inputs / "unitcell.in", pristine_fragment, inputs / "phono3py_disp.yaml"]
    if not all(path.is_file() for path in dataset_paths):
        raise RuntimeError("missing required phono3py displacement dataset metadata; abandon this RUN_DIR")
    semantics = inspect_dataset(inputs)
    semantic_path = run_dir / "dataset_semantics.json"
    semantic_path.write_text(json.dumps(semantics, indent=2, sort_keys=True) + "\n")
    (force_dir / "pristine").mkdir()
    (force_dir / "pristine" / "scf.in").write_text(qe_input(pristine_fragment, config, safe_qe_string(str(pseudo_dir))))
    input_hashes = {"pristine/scf.in": sha256(force_dir / "pristine" / "scf.in")}
    for fragment in fragments:
        label = fragment.stem.replace("supercell-", "disp-")
        target_dir = force_dir / label
        target_dir.mkdir()
        target = target_dir / "scf.in"
        target.write_text(qe_input(fragment, config, safe_qe_string(str(pseudo_dir))))
        input_hashes[f"{label}/scf.in"] = sha256(target)
    manifest = {
        "document_type": "srcu_v2_run_manifest", "config_sha256": sha256(CONFIG_PATH),
        "source_unitcell_sha256": sha256(source), "preparer_sha256": sha256(Path(__file__)),
        "dataset_semantics_validator_sha256": sha256(DATASET_VALIDATOR_PATH),
        "phono3py_command": command, "phono3py_init_path": str(generator),
        "phono3py_init_sha256": sha256(generator),
        "phono3py_version": semantics["phono3py_version"],
        "displacement_input_count": len(fragments), "dataset_sha256": {str(path.relative_to(run_dir)): sha256(path) for path in dataset_paths},
        "dataset_semantics_sha256": sha256(semantic_path), "pseudo_dir": str(pseudo_dir), "pseudopotential_sha256": pseudo_hashes,
        "input_sha256": input_hashes, "qe_execution_released": False,
        "slurm_submission_released": False
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"prepared": str(run_dir), "displacements": len(fragments), "qe_execution_released": False,
                      "run_manifest_sha256": sha256(manifest_path)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"FAIL-CLOSED: {exc}")

#!/usr/bin/env python3
"""Prepare one fresh fixed-cell BFGS attempt from a terminal, hashed failure.

This copies only small immutable evidence and coordinates, never QE scratch.
It does not accept a structure, run QE, change numerical settings, or submit a
job. The ordinary relax/pristine/finalize pipeline still decides acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import campaign as core
from qe_input import FinalCoordinates, extract_final_coordinates, parse_qe_input, replace_qe_geometry
from qe_output import inspect_output


SOURCE_FILES = (
    "starting_unitcell.in", "starting_structure_audit.json", "relax.in",
    "relax.out", "relax.err", "relax_launch.json", "relax.process.json",
    "context.tsv", "exit_code.txt", "finished_utc.txt",
)
RECEIPT = "relax_recovery.json"


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise core.CampaignError(f"{label} must be a lowercase SHA256")
    return value


def _context(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] in result:
            raise core.CampaignError("source attempt has malformed/duplicate context fields")
        result[fields[0]] = fields[1]
    return result


def _pseudo_content(record: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    result = {}
    for species, item in record.items():
        if not isinstance(item, Mapping):
            raise core.CampaignError("source pseudopotential receipt is invalid")
        result[species] = {
            "filename": Path(str(item.get("file", ""))).name,
            "sha256": _digest(item.get("sha256"), "pseudopotential hash"),
        }
    return result


def _audit_source(
    config: Mapping[str, Any], evidence_dir: Path, manifest: Mapping[str, Any],
    source_attempt: Path, source_run_dir: Path,
) -> tuple[str, str, dict[str, Any]]:
    """Replay the raw failure-to-coordinate chain, also on archived copies."""

    if manifest.get("relax_recovery") is not None:
        raise core.CampaignError("a second automatic BFGS reset is not supported; scientific review required")
    policy = core.policy_sha256(config, "structure")
    if manifest.get("structure_policy_sha256") != policy:
        raise core.CampaignError("source structure policy differs from recovery policy")
    context = _context(evidence_dir / "context.tsv")
    if context.get("stage") != "relax" or context.get("run_dir") != str(source_run_dir):
        raise core.CampaignError("source attempt context/run identity mismatch")
    if context.get("attempt_id") != source_attempt.name:
        raise core.CampaignError("source attempt ID mismatch")
    workflow = manifest.get("workflow_files", {})
    campaign_hashes = [value for key, value in workflow.items() if key.endswith("/campaign.py")]
    if len(campaign_hashes) != 1 or context.get("campaign_cli_sha256") != campaign_hashes[0]:
        raise core.CampaignError("source execution does not match archived workflow hash")
    if context.get("config_sha256") != manifest.get("config_sha256"):
        raise core.CampaignError("source executed config differs from its run manifest")
    if not re.fullmatch(r"[1-9][0-9]*", context.get("slurm_job_id", "")):
        raise core.CampaignError("source attempt lacks a scheduler job identity")
    exit_text = (evidence_dir / "exit_code.txt").read_text().strip()
    if not re.fullmatch(r"[0-9]+", exit_text) or int(exit_text) == 0:
        raise core.CampaignError("source wrapper must have a recorded terminal failure")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", (evidence_dir / "finished_utc.txt").read_text().strip()):
        raise core.CampaignError("source wrapper lacks a terminal timestamp")

    launch = core.load_json(evidence_dir / "relax_launch.json")
    process = core.load_json(evidence_dir / "relax.process.json")
    audit = core.load_json(evidence_dir / "starting_structure_audit.json")
    if launch.get("structure_policy_sha256") != policy or launch.get("config_sha256") != manifest.get("config_sha256"):
        raise core.CampaignError("source relax launch/config provenance mismatch")
    for key, filename in (("relax_input_sha256", "relax.in"), ("starting_structure_audit_sha256", "starting_structure_audit.json")):
        if launch.get(key) != core.sha256_path(evidence_dir / filename):
            raise core.CampaignError(f"source launch hash mismatch: {filename}")
    if process.get("returncode") != 0 or process.get("cwd") != str(source_attempt):
        raise core.CampaignError("source QE process must have finished with exit 0 in its own attempt")
    if process.get("command") != launch.get("command") or not isinstance(process.get("command"), list) or process["command"][-2:] != ["-in", "relax.in"]:
        raise core.CampaignError("source QE process/launch command mismatch")
    for key, filename in (("stdout_sha256", "relax.out"), ("stderr_sha256", "relax.err")):
        if process.get(key) != core.sha256_path(evidence_dir / filename):
            raise core.CampaignError(f"source process hash mismatch: {filename}")
    if (evidence_dir / "relax.err").read_text().strip():
        raise core.CampaignError("source QE stderr is nonempty; review it before coordinate recovery")
    nat = int(core.required(config, "material.unitcell_atoms"))
    health = inspect_output(evidence_dir / "relax.out", nat)
    text = (evidence_dir / "relax.out").read_text()
    lower = text.lower()
    if len(re.findall(r"^\s*Program PWSCF\b", text, re.MULTILINE)) != 1:
        raise core.CampaignError("source output must contain exactly one QE process")
    if not health["healthy"] or "bfgs failed" not in lower or "convergence not achieved" not in lower or "bfgs converged" in lower:
        raise core.CampaignError("source is not a clean SCF completion with explicit BFGS nonconvergence")
    if "Error in routine" in text or "MPI_ABORT" in text:
        raise core.CampaignError("source output has an additional fatal error")
    if not (
        text.rfind("Forces acting on atoms") < text.rfind("Begin final coordinates")
        < text.rfind("End final coordinates") < text.rfind("JOB DONE")
    ):
        raise core.CampaignError("source final coordinates must follow its last force block and precede JOB DONE")
    if float(health["max_abs_force_ry_bohr"]) > float(core.required(config, "tight_relax.hard_stop_max_force_ry_bohr")):
        raise core.CampaignError("source force exceeds the recovery hard-stop threshold")

    reference = (evidence_dir / "starting_unitcell.in").read_text()
    recorded_start_hash = audit.get("standardized_geometry_sha256") if audit.get("standardized") else audit.get("accepted_starting_geometry_sha256")
    if audit.get("pass") is not True or recorded_start_hash != hashlib.sha256(reference.encode()).hexdigest():
        raise core.CampaignError("source starting geometry/audit mismatch")
    pseudos = launch.get("pseudopotentials")
    if not isinstance(pseudos, Mapping) or set(pseudos) != set(core.required(config, "pseudopotentials.files")):
        raise core.CampaignError("source pseudopotential species mismatch")
    pseudo_content = _pseudo_content(pseudos)
    for species, filename in core.required(config, "pseudopotentials.files").items():
        if pseudo_content[species]["filename"] != filename:
            raise core.CampaignError("source pseudopotential filename mismatch")
    pseudo_dirs = {str(Path(item["file"]).parent) for item in pseudos.values()}
    if len(pseudo_dirs) != 1:
        raise core.CampaignError("source pseudopotentials use inconsistent directories")
    source_input = (evidence_dir / "relax.in").read_text()
    if source_input != core.relax_input_for(config, reference, Path(pseudo_dirs.pop())):
        raise core.CampaignError("source relax input is not the exact policy-generated input")
    parsed = parse_qe_input(source_input)
    if parsed.nat != nat:
        raise core.CampaignError("source atom count differs from material")
    final = extract_final_coordinates(text, expected_atoms=nat)
    # replace_qe_geometry validates ordered labels; the displacement check below
    # also rejects a cell change. Preserve the original input cell tokens.
    seed = replace_qe_geometry(reference, final, require_cell=False)
    shifts = core._position_shifts_angstrom(reference, seed)
    if max(shifts) > float(core.required(config, "tight_relax.max_position_shift_angstrom")):
        raise core.CampaignError("failed-attempt displacement exceeds the original position-shift guardrail")
    seed = replace_qe_geometry(reference, FinalCoordinates("crystal", final.atomic_positions), require_cell=False)
    return seed, reference, {
        "source_job_id": context["slurm_job_id"],
        "source_qe_health": {key: value for key, value in health.items() if key != "path"},
        "source_max_position_shift_angstrom": max(shifts),
        "pseudopotentials": pseudo_content,
    }


def prepare_recovery(
    config_path: Path, run_dir: Path, *, source_run_dir: Path, source_attempt: Path,
    source_manifest_sha256: str, source_output_sha256: str,
) -> dict[str, Any]:
    """Prepare a new immutable run; source records are only read, never edited."""

    config, validation = core.validate_config(config_path)
    run_dir = core.safe_run_dir(run_dir)
    source_run_dir = core.safe_run_dir(source_run_dir)
    source_attempt = source_attempt.resolve()
    if source_attempt.parent != source_run_dir / "slurm_attempts" / "relax":
        raise core.CampaignError("source attempt must be an exact relax attempt under source RUN_DIR")
    if run_dir == source_run_dir or run_dir.is_relative_to(source_run_dir) or source_run_dir.is_relative_to(run_dir):
        raise core.CampaignError("recovery requires a separate new RUN_DIR")
    if run_dir.exists():
        raise core.CampaignError("recovery RUN_DIR already exists; never overwrite or reuse it")
    manifest_path = source_run_dir / core.RUN_MANIFEST
    if core.sha256_path(manifest_path) != _digest(source_manifest_sha256, "source manifest hash"):
        raise core.CampaignError("source manifest SHA256 mismatch")
    if core.sha256_path(source_attempt / "relax.out") != _digest(source_output_sha256, "source output hash"):
        raise core.CampaignError("source output SHA256 mismatch")
    manifest = core.verify_upstream_manifest(config, config_path, source_run_dir, stage="structure")
    snapshot = core.load_json(source_run_dir / "config.snapshot.json")
    if core.policy_sha256(snapshot, "structure") != manifest["structure_policy_sha256"]:
        raise core.CampaignError("source config snapshot/policy mismatch")
    forbidden = ("pristine.in", "pristine.out", "execution_manifest.json", "relax_gate.json")
    if any((source_attempt / item).exists() for item in forbidden) or (source_run_dir / "relax/final").exists():
        raise core.CampaignError("source already reached pristine/finalization; this recovery path is only for BFGS failure")
    paths = {name: source_attempt / name for name in SOURCE_FILES}
    paths.update({"source_run_manifest.json": manifest_path, "source_config.snapshot.json": source_run_dir / "config.snapshot.json"})
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise core.CampaignError(f"missing or symlinked source evidence: {name}")
    hashes = {name: core.sha256_path(path) for name, path in paths.items()}
    seed, reference, review = _audit_source(config, source_attempt, manifest, source_attempt, source_run_dir)
    receipt = {
        "schema_version": 1, "kind": "fresh_fixed_cell_bfgs_from_failed_attempt",
        "created_utc": core.utc_now(), "material": manifest["material"],
        "structure_policy_sha256": manifest["structure_policy_sha256"],
        "source_run_dir": str(source_run_dir), "source_attempt": str(source_attempt),
        "source_manifest_sha256": source_manifest_sha256, "source_output_sha256": source_output_sha256,
        "source_files": hashes,
        "seed_unitcell_sha256": hashlib.sha256(seed.encode()).hexdigest(),
        "reference_unitcell_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        "backend_sha256": core.sha256_path(Path(__file__)), "review": review,
        "reset_number": 1, "reuse_qe_scratch": False,
        "acceptance": "normal BFGS convergence and independent pristine SCF; unchanged original gates and cumulative displacement reference",
    }
    # All validation precedes the first write. A race or interrupted copy leaves
    # an incomplete new run which cannot launch, and never mutates the source.
    run_dir.mkdir(parents=True, exist_ok=False)
    archive = run_dir / "recovery_source"
    for name, path in paths.items():
        core.write_immutable(archive / name, path.read_text())
        if core.sha256_path(archive / name) != hashes[name] or core.sha256_path(path) != hashes[name]:
            raise core.CampaignError("source evidence changed while archiving; prepared run is incomplete")
    core.write_immutable(run_dir / "recovery_seed.in", seed)
    core.write_immutable(run_dir / "recovery_reference.in", reference)
    core.write_json_immutable(run_dir / RECEIPT, receipt)
    new_manifest = core.manifest_for(config, config_path)
    new_manifest["relax_recovery"] = {"receipt": RECEIPT, "sha256": core.sha256_path(run_dir / RECEIPT)}
    core.write_json_immutable(run_dir / core.RUN_MANIFEST, new_manifest)
    core.write_json_immutable(run_dir / "config.snapshot.json", config)
    core.write_json_immutable(run_dir / "config_validation.json", validation)
    (run_dir / "relax").mkdir()
    (run_dir / "preflight").mkdir()
    return {"healthy": True, "stage": "prepare-relax-recovery", "run_dir": str(run_dir), "receipt_sha256": new_manifest["relax_recovery"]["sha256"], "review": review, "next": "submit ordinary relax stage with a new ATTEMPT_ID"}


def load_recovery_start(
    config: Mapping[str, Any], run_dir: Path, manifest: Mapping[str, Any],
    expected_reference: str, pseudopotentials: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Revalidate frozen copies at launch and finalization, including code."""

    pointer = manifest.get("relax_recovery")
    if not isinstance(pointer, Mapping) or pointer.get("receipt") != RECEIPT:
        raise core.CampaignError("invalid recovery manifest pointer")
    receipt_path = run_dir / RECEIPT
    if core.sha256_path(receipt_path) != pointer.get("sha256"):
        raise core.CampaignError("recovery receipt hash mismatch")
    receipt = core.load_json(receipt_path)
    if receipt.get("backend_sha256") != core.sha256_path(Path(__file__)):
        raise core.CampaignError("recovery backend changed after preparation")
    archive = run_dir / "recovery_source"
    expected_names = set(SOURCE_FILES) | {"source_run_manifest.json", "source_config.snapshot.json"}
    if set(receipt.get("source_files", {})) != expected_names:
        raise core.CampaignError("recovery source inventory mismatch")
    for name, digest in receipt["source_files"].items():
        if core.sha256_path(archive / name) != digest:
            raise core.CampaignError(f"archived recovery source hash mismatch: {name}")
    source_manifest = core.load_json(archive / "source_run_manifest.json")
    if core.sha256_path(archive / "source_run_manifest.json") != receipt.get("source_manifest_sha256") or core.sha256_path(archive / "relax.out") != receipt.get("source_output_sha256"):
        raise core.CampaignError("recovery source anchor mismatch")
    seed, reference, review = _audit_source(config, archive, source_manifest, Path(receipt["source_attempt"]), Path(receipt["source_run_dir"]))
    if reference != expected_reference or reference != (run_dir / "recovery_reference.in").read_text() or seed != (run_dir / "recovery_seed.in").read_text():
        raise core.CampaignError("recovery seed/original geometry reference mismatch")
    if hashlib.sha256(seed.encode()).hexdigest() != receipt.get("seed_unitcell_sha256") or hashlib.sha256(reference.encode()).hexdigest() != receipt.get("reference_unitcell_sha256"):
        raise core.CampaignError("recovery seed/reference hash mismatch")
    if review != receipt.get("review") or _pseudo_content(pseudopotentials) != review["pseudopotentials"]:
        raise core.CampaignError("recovery source review/pseudopotential content mismatch")
    return seed, {"receipt_sha256": pointer["sha256"], "source_manifest_sha256": receipt["source_manifest_sha256"], "source_output_sha256": receipt["source_output_sha256"], "reference_unitcell_sha256": receipt["reference_unitcell_sha256"], "reset_number": 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "run-dir", "source-run-dir", "source-attempt"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--source-output-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_recovery(args.config, args.run_dir, source_run_dir=args.source_run_dir, source_attempt=args.source_attempt, source_manifest_sha256=args.source_manifest_sha256, source_output_sha256=args.source_output_sha256)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, core.CampaignError) as exc:
        print(json.dumps({"healthy": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

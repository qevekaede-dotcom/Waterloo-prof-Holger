#!/usr/bin/env python3
"""Prepare one reviewed BFGS polish after the one-reset path is exhausted.

This is deliberately separate from :mod:`relax_recovery`: it archives and
binds the terminal one-reset failure plus its original recovery lineage, runs
an independent three-SCF force-consistency diagnostic, and releases exactly
one fresh-scratch polish only after that diagnostic passes.  The diagnostic
never accepts a structure; the ordinary BFGS, pristine-SCF, and finalization
gate remains authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

import campaign as core
import relax_recovery
from qe_input import (
    FinalCoordinates,
    _set_namelist_values,
    build_pristine_scf_input,
    extract_final_coordinates,
    replace_qe_geometry,
)
from qe_output import compare_force_records, inspect_output, parse_last_force_block


LINEAGE_RECEIPT = "polish_lineage.json"
DIAGNOSTIC_EXECUTION = "diagnostic_execution.json"
DIAGNOSTIC_RECEIPT = "diagnostic_receipt.json"
UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
SLURM_NODELIST_RE = re.compile(r"[A-Za-z0-9_.\[\],-]+")


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise core.CampaignError(f"{label} must be a lowercase SHA256")
    return value


def _strict_run_path(
    run_dir: Path,
    path: Path,
    label: str,
    *,
    require_exists: bool = True,
) -> Path:
    """Use lstat on every RUN_DIR component and reject any symlink/escape."""

    lexical_root = Path(os.path.abspath(run_dir))
    root = run_dir.resolve(strict=True)
    candidate_input = Path(os.path.abspath(path))
    if candidate_input.is_relative_to(lexical_root):
        relative = candidate_input.relative_to(lexical_root)
    elif candidate_input.is_relative_to(root):
        relative = candidate_input.relative_to(root)
    else:
        alias_root = None
        for ancestor in (candidate_input, *candidate_input.parents):
            try:
                if stat.S_ISLNK(os.lstat(ancestor).st_mode):
                    raise core.CampaignError(
                        f"{label} path contains a symlink: {ancestor}"
                    )
                if os.path.samefile(ancestor, root):
                    alias_root = ancestor
                    break
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
        if alias_root is None:
            raise core.CampaignError(f"{label} must be a strict RUN_DIR descendant")
        relative = candidate_input.relative_to(alias_root)
    if not relative.parts:
        raise core.CampaignError(f"{label} must be a strict RUN_DIR descendant")
    candidate = root / relative
    current = root
    missing = False
    for part in candidate.relative_to(root).parts:
        current = current / part
        if missing:
            continue
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            missing = True
            continue
        if stat.S_ISLNK(mode):
            raise core.CampaignError(f"{label} path contains a symlink: {current}")
    if require_exists and missing:
        raise core.CampaignError(f"{label} is missing: {candidate}")
    resolved = candidate.resolve(strict=require_exists)
    if resolved == root or not resolved.is_relative_to(root):
        raise core.CampaignError(f"{label} resolves outside RUN_DIR")
    return candidate


def _copy_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _pseudopotential_archive_payload(
    config: Mapping[str, Any], pseudopotentials: Mapping[str, Any]
) -> tuple[dict[str, dict[str, str]], dict[str, bytes]]:
    """Read and hash the exact submitted UPF bytes before creating lineage."""

    configured = core.required(config, "pseudopotentials.files")
    if not isinstance(configured, Mapping) or set(pseudopotentials) != set(configured):
        raise core.CampaignError(
            "one-reset pseudopotential species differ from the campaign configuration"
        )
    if len(set(configured.values())) != len(configured):
        raise core.CampaignError("configured pseudopotential filenames are not unique")
    inventory: dict[str, dict[str, str]] = {}
    blobs: dict[str, bytes] = {}
    for species, filename_value in configured.items():
        filename = str(filename_value)
        item = pseudopotentials.get(species)
        if not isinstance(item, Mapping):
            raise core.CampaignError("one-reset pseudopotential receipt is invalid")
        source = Path(str(item.get("file", "")))
        if (
            not source.is_absolute()
            or source.name != filename
            or source.is_symlink()
            or not source.is_file()
        ):
            raise core.CampaignError(
                f"one-reset pseudopotential source is missing or unsafe: {species}"
            )
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != _digest(item.get("sha256"), "pseudopotential hash"):
            raise core.CampaignError(
                f"one-reset pseudopotential bytes differ from their launch hash: {species}"
            )
        relative = f"lineage_source/pseudopotentials/{filename}"
        inventory[str(species)] = {
            "filename": filename,
            "relative_path": relative,
            "sha256": digest,
        }
        blobs[filename] = data
    return inventory, blobs


def _context(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] in result:
            raise core.CampaignError("one-reset attempt has malformed/duplicate context fields")
        result[fields[0]] = fields[1]
    return result


def _pseudo_content(record: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for species, item in record.items():
        if not isinstance(item, Mapping):
            raise core.CampaignError("one-reset pseudopotential receipt is invalid")
        result[str(species)] = {
            "filename": Path(str(item.get("file", ""))).name,
            "sha256": _digest(item.get("sha256"), "pseudopotential hash"),
        }
    return result


def _source_paths(source_run_dir: Path, source_attempt: Path) -> dict[str, Path]:
    paths = {
        f"one_reset_attempt/{name}": source_attempt / name
        for name in relax_recovery.SOURCE_FILES
    }
    paths["one_reset_attempt/reference_unitcell.in"] = source_attempt / "reference_unitcell.in"
    paths.update(
        {
            "one_reset_run/run_manifest.json": source_run_dir / core.RUN_MANIFEST,
            "one_reset_run/config.snapshot.json": source_run_dir / "config.snapshot.json",
            f"one_reset_run/{relax_recovery.RECEIPT}": source_run_dir / relax_recovery.RECEIPT,
            "one_reset_run/recovery_seed.in": source_run_dir / "recovery_seed.in",
            "one_reset_run/recovery_reference.in": source_run_dir / "recovery_reference.in",
        }
    )
    receipt = core.load_json(source_run_dir / relax_recovery.RECEIPT)
    source_files = receipt.get("source_files")
    if not isinstance(source_files, Mapping):
        raise core.CampaignError("original recovery receipt lacks its source inventory")
    for name in source_files:
        if not isinstance(name, str) or Path(name).name != name:
            raise core.CampaignError("original recovery source inventory is unsafe")
        paths[f"original_recovery_source/{name}"] = source_run_dir / "recovery_source" / name
    return paths


def _audit_one_reset(
    config: Mapping[str, Any],
    config_path: Path,
    source_run_dir: Path,
    source_attempt: Path,
) -> tuple[str, str, dict[str, Any], dict[str, Path]]:
    manifest = core.verify_upstream_manifest(
        config, config_path, source_run_dir, stage="structure"
    )
    if not isinstance(manifest.get("relax_recovery"), Mapping):
        raise core.CampaignError("polish source must be the terminal one-reset run")
    if manifest.get("relax_polish") is not None:
        raise core.CampaignError("a BFGS polish cannot be chained into another polish")
    snapshot = core.load_json(source_run_dir / "config.snapshot.json")
    if core.policy_sha256(snapshot, "structure") != manifest["structure_policy_sha256"]:
        raise core.CampaignError("one-reset config snapshot/policy mismatch")
    forbidden = ("pristine.in", "pristine.out", "execution_manifest.json", "relax_gate.json")
    if any((source_attempt / name).exists() for name in forbidden):
        raise core.CampaignError("one-reset source already reached pristine/finalization")
    if (source_run_dir / "relax/final").exists():
        raise core.CampaignError("one-reset source already has an accepted structure")

    paths = _source_paths(source_run_dir, source_attempt)
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise core.CampaignError(f"missing or symlinked polish-lineage evidence: {name}")

    context = _context(source_attempt / "context.tsv")
    if (
        context.get("stage") != "relax"
        or context.get("run_dir") != str(source_run_dir)
        or context.get("attempt_id") != source_attempt.name
        or re.fullmatch(r"[1-9][0-9]*", context.get("slurm_job_id", "")) is None
    ):
        raise core.CampaignError("one-reset attempt context/run identity is invalid")
    workflow = manifest.get("workflow_files", {})
    campaign_hashes = [value for key, value in workflow.items() if key.endswith("/campaign.py")]
    if len(campaign_hashes) != 1 or context.get("campaign_cli_sha256") != campaign_hashes[0]:
        raise core.CampaignError("one-reset execution differs from its archived workflow hash")
    if context.get("config_sha256") != manifest.get("config_sha256"):
        raise core.CampaignError("one-reset execution/config identity mismatch")
    exit_text = (source_attempt / "exit_code.txt").read_text().strip()
    if re.fullmatch(r"[0-9]+", exit_text) is None or int(exit_text) == 0:
        raise core.CampaignError("one-reset wrapper must record a terminal failure")
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
        (source_attempt / "finished_utc.txt").read_text().strip(),
    ) is None:
        raise core.CampaignError("one-reset wrapper lacks a terminal timestamp")

    launch = core.load_json(source_attempt / "relax_launch.json")
    process = core.load_json(source_attempt / "relax.process.json")
    if launch.get("structure_policy_sha256") != manifest.get("structure_policy_sha256"):
        raise core.CampaignError("one-reset launch policy hash mismatch")
    for key, filename in (
        ("relax_input_sha256", "relax.in"),
        ("starting_structure_audit_sha256", "starting_structure_audit.json"),
    ):
        if launch.get(key) != core.sha256_path(source_attempt / filename):
            raise core.CampaignError(f"one-reset launch hash mismatch: {filename}")
    if (
        process.get("returncode") != 0
        or process.get("cwd") != str(source_attempt)
        or process.get("command") != launch.get("command")
        or not isinstance(process.get("command"), list)
        or process["command"][-2:] != ["-in", "relax.in"]
    ):
        raise core.CampaignError("one-reset QE process identity is invalid")
    for key, filename in (("stdout_sha256", "relax.out"), ("stderr_sha256", "relax.err")):
        if process.get(key) != core.sha256_path(source_attempt / filename):
            raise core.CampaignError(f"one-reset process hash mismatch: {filename}")
    if (source_attempt / "relax.err").read_text().strip():
        raise core.CampaignError("one-reset QE stderr is nonempty")

    nat = int(core.required(config, "material.unitcell_atoms"))
    output_path = source_attempt / "relax.out"
    health = inspect_output(output_path, nat)
    output_text = output_path.read_text()
    lower = output_text.lower()
    if (
        not health["healthy"]
        or "bfgs failed" not in lower
        or "convergence not achieved" not in lower
        or "bfgs converged" in lower
        or "history already reset at previous step" not in lower
    ):
        raise core.CampaignError("source is not the reviewed terminal one-reset BFGS failure")
    if "Error in routine" in output_text or "MPI_ABORT" in output_text:
        raise core.CampaignError("one-reset output has an additional fatal error")
    if not (
        output_text.rfind("Forces acting on atoms")
        < output_text.rfind("Begin final coordinates")
        < output_text.rfind("End final coordinates")
        < output_text.rfind("JOB DONE")
    ):
        raise core.CampaignError(
            "one-reset final coordinates must follow its last force block and precede JOB DONE"
        )
    if float(health["max_abs_force_ry_bohr"]) > float(
        core.required(config, "tight_relax.hard_stop_max_force_ry_bohr")
    ):
        raise core.CampaignError("one-reset force exceeds the configured hard stop")

    pseudos = launch.get("pseudopotentials")
    if not isinstance(pseudos, Mapping):
        raise core.CampaignError("one-reset launch lacks pseudopotential evidence")
    reference = (source_run_dir / "recovery_reference.in").read_text()
    recovery_seed, recovery_review = relax_recovery.load_recovery_start(
        config, source_run_dir, manifest, reference, pseudos
    )
    if recovery_seed != (source_attempt / "starting_unitcell.in").read_text():
        raise core.CampaignError("one-reset attempt did not start from its frozen recovery seed")
    if reference != (source_attempt / "reference_unitcell.in").read_text():
        raise core.CampaignError("one-reset attempt lost the original cumulative-shift reference")
    if launch.get("recovery") != recovery_review:
        raise core.CampaignError("one-reset launch/recovery lineage mismatch")

    pseudo_dirs = {str(Path(str(item.get("file", ""))).parent) for item in pseudos.values()}
    if len(pseudo_dirs) != 1:
        raise core.CampaignError("one-reset pseudopotential directories are inconsistent")
    expected_input = core.relax_input_for(config, recovery_seed, Path(pseudo_dirs.pop()))
    expected_input = _set_namelist_values(
        expected_input, "CONTROL", {"restart_mode": "'from_scratch'"}
    )
    expected_input = _set_namelist_values(
        expected_input,
        "ELECTRONS",
        {"startingpot": "'atomic'", "startingwfc": "'atomic+random'"},
    )
    if expected_input != (source_attempt / "relax.in").read_text():
        raise core.CampaignError("one-reset input is not the exact fresh-history policy input")

    final = extract_final_coordinates(output_text, expected_atoms=nat)
    polish_seed = replace_qe_geometry(
        recovery_seed, FinalCoordinates("crystal", final.atomic_positions), require_cell=False
    )
    shifts = core._position_shifts_angstrom(reference, polish_seed)
    if max(shifts) > float(core.required(config, "tight_relax.max_position_shift_angstrom")):
        raise core.CampaignError("one-reset final geometry exceeds the cumulative-shift guardrail")
    review = {
        "one_reset_job_id": context["slurm_job_id"],
        "one_reset_qe_health": {key: value for key, value in health.items() if key != "path"},
        "maximum_cumulative_shift_angstrom": max(shifts),
        "pseudopotentials": _pseudo_content(pseudos),
        "original_recovery": recovery_review,
    }
    return polish_seed, reference, review, paths


def _diagnostic_inputs(
    config: Mapping[str, Any], source_relax_input: str, source_relax_output: str, pseudo_dir: Path
) -> tuple[str, str]:
    settings = core.required(config, "tight_relax")
    diagnostic = core.required(config, "reviewed_bfgs_polish.force_consistency_diagnostic")
    formula = str(core.required(config, "material.formula"))
    common = dict(
        outdir="./tmp-diagnostic",
        prefix=f"{formula}_p3_polish_diagnostic",
        pseudo_dir=str(pseudo_dir),
        disk_io="low",
        tprnfor=True,
        conv_thr=float(core.required(settings, "conv_thr_ry")),
        ecutwfc=float(core.required(settings, "ecutwfc_ry")),
        kmesh=core.required(settings, "kmesh"),
        kshift=core.required(settings, "kmesh_shift"),
        nosym=True,
        noinv=True,
    )
    baseline = build_pristine_scf_input(
        source_relax_input,
        source_relax_output,
        ecutrho=float(core.required(diagnostic, "baseline_ecutrho_ry")),
        **common,
    )
    higher = build_pristine_scf_input(
        source_relax_input,
        source_relax_output,
        ecutrho=float(core.required(diagnostic, "higher_ecutrho_ry")),
        **common,
    )
    if baseline == higher:
        raise core.CampaignError("higher-ecutrho diagnostic input is not distinct")
    return baseline, higher


def prepare_lineage(
    config_path: Path,
    run_dir: Path,
    *,
    source_run_dir: Path,
    source_attempt: Path,
    source_manifest_sha256: str,
    source_output_sha256: str,
) -> dict[str, Any]:
    config, validation = core.validate_config(config_path)
    if "reviewed_bfgs_polish" not in config:
        raise core.CampaignError("config has no reviewed BFGS-polish proposal")
    run_dir = core.safe_run_dir(run_dir)
    source_run_dir = core.safe_run_dir(source_run_dir)
    source_attempt = source_attempt.resolve()
    if source_attempt.parent != source_run_dir / "slurm_attempts" / "relax":
        raise core.CampaignError("source attempt must be an exact relax attempt under source RUN_DIR")
    if run_dir == source_run_dir or run_dir.is_relative_to(source_run_dir) or source_run_dir.is_relative_to(run_dir):
        raise core.CampaignError("reviewed polish requires a separate new RUN_DIR")
    if run_dir.exists():
        raise core.CampaignError("polish RUN_DIR already exists; never overwrite or reuse it")
    manifest_path = source_run_dir / core.RUN_MANIFEST
    if core.sha256_path(manifest_path) != _digest(source_manifest_sha256, "source manifest hash"):
        raise core.CampaignError("source manifest SHA256 mismatch")
    if core.sha256_path(source_attempt / "relax.out") != _digest(source_output_sha256, "source output hash"):
        raise core.CampaignError("source output SHA256 mismatch")

    seed, reference, review, paths = _audit_one_reset(
        config, config_path.resolve(), source_run_dir, source_attempt
    )
    hashes = {name: core.sha256_path(path) for name, path in paths.items()}
    policy = core.required(config, "reviewed_bfgs_polish")
    # Validate and materialize diagnostic inputs before the first write.
    source_launch = core.load_json(source_attempt / "relax_launch.json")
    source_pseudos = source_launch.get("pseudopotentials")
    if not isinstance(source_pseudos, Mapping):
        raise core.CampaignError("one-reset launch lacks pseudopotential evidence")
    pseudo_inventory, pseudo_blobs = _pseudopotential_archive_payload(
        config, source_pseudos
    )
    archived_pseudo_dir = run_dir / "lineage_source/pseudopotentials"
    baseline, higher = _diagnostic_inputs(
        config,
        (source_attempt / "relax.in").read_text(),
        (source_attempt / "relax.out").read_text(),
        archived_pseudo_dir,
    )
    lineage = {
        "schema_version": 1,
        "kind": "reviewed_single_bfgs_polish_after_terminal_one_reset",
        "created_utc": core.utc_now(),
        "material": core.required(config, "material.formula"),
        "structure_policy_sha256": core.policy_sha256(config, "structure"),
        "polish_policy_sha256": core.canonical_sha256(policy),
        "config_canonical_sha256": core.canonical_sha256(config),
        "source_run_dir": str(source_run_dir),
        "source_attempt": str(source_attempt),
        "source_manifest_sha256": source_manifest_sha256,
        "source_output_sha256": source_output_sha256,
        "source_files": hashes,
        "seed_unitcell_sha256": hashlib.sha256(seed.encode()).hexdigest(),
        "reference_unitcell_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        "backend_sha256": core.sha256_path(Path(__file__)),
        "diagnostic_input_sha256": {
            "baseline.in": hashlib.sha256(baseline.encode()).hexdigest(),
            "higher_ecutrho.in": hashlib.sha256(higher.encode()).hexdigest(),
        },
        "pseudopotential_archive": pseudo_inventory,
        "review": review,
        "automatic_reset": False,
        "maximum_polish_attempts": 1,
        "reuse_qe_scratch": False,
        "acceptance": "diagnostic cannot accept structure; normal BFGS plus independent pristine SCF and ordinary final gate remain mandatory",
    }

    run_dir.mkdir(parents=True, exist_ok=False)
    archive = run_dir / "lineage_source"
    for name, path in paths.items():
        core.write_immutable(archive / name, path.read_text())
        if core.sha256_path(archive / name) != hashes[name] or core.sha256_path(path) != hashes[name]:
            raise core.CampaignError("source evidence changed while archiving; prepared lineage is incomplete")
    for filename, data in pseudo_blobs.items():
        archived = archived_pseudo_dir / filename
        _copy_bytes_exclusive(archived, data)
        if core.sha256_path(archived) != hashlib.sha256(data).hexdigest():
            raise core.CampaignError(
                f"archived pseudopotential hash mismatch after copy: {filename}"
            )
    core.write_immutable(run_dir / "polish_seed.in", seed)
    core.write_immutable(run_dir / "polish_reference.in", reference)
    core.write_json_immutable(run_dir / LINEAGE_RECEIPT, lineage)
    core.write_json_immutable(run_dir / "config_validation.json", validation)
    core.write_immutable(run_dir / "diagnostic/inputs/baseline.in", baseline)
    core.write_immutable(run_dir / "diagnostic/inputs/higher_ecutrho.in", higher)
    (run_dir / "diagnostic/attempts").mkdir(parents=True)
    return {
        "healthy": True,
        "stage": "prepare-polish-lineage",
        "run_dir": str(run_dir),
        "lineage_sha256": core.sha256_path(run_dir / LINEAGE_RECEIPT),
        "baseline_input_sha256": core.sha256_path(run_dir / "diagnostic/inputs/baseline.in"),
        "higher_ecutrho_input_sha256": core.sha256_path(run_dir / "diagnostic/inputs/higher_ecutrho.in"),
        "structure_accepted": False,
        "next": "run exactly two fresh baseline SCFs and one fresh higher-ecutrho SCF; no polish is released yet",
    }


def _load_lineage(config: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    receipt_path = _strict_run_path(
        run_dir, run_dir / LINEAGE_RECEIPT, "polish lineage receipt"
    )
    receipt = core.load_json(receipt_path)
    if receipt.get("backend_sha256") != core.sha256_path(Path(__file__)):
        raise core.CampaignError("polish-lineage backend changed after preparation")
    if receipt.get("polish_policy_sha256") != core.canonical_sha256(
        core.required(config, "reviewed_bfgs_polish")
    ):
        raise core.CampaignError("reviewed polish policy differs from frozen lineage")
    if receipt.get("config_canonical_sha256") != core.canonical_sha256(config):
        raise core.CampaignError("campaign config differs from the frozen polish lineage")
    source_files = receipt.get("source_files")
    if not isinstance(source_files, Mapping) or not source_files:
        raise core.CampaignError("polish lineage source inventory is invalid")
    for name, digest in source_files.items():
        relative = Path(str(name))
        if relative.is_absolute() or ".." in relative.parts:
            raise core.CampaignError("polish lineage source inventory path is unsafe")
        _digest(digest, "polish lineage source hash")
        archived_source = _strict_run_path(
            run_dir,
            run_dir / "lineage_source" / relative,
            f"archived polish-lineage evidence {name}",
        )
        if core.sha256_path(archived_source) != digest:
            raise core.CampaignError(f"archived polish-lineage hash mismatch: {name}")
    for name, key in (
        ("polish_seed.in", "seed_unitcell_sha256"),
        ("polish_reference.in", "reference_unitcell_sha256"),
    ):
        geometry = _strict_run_path(run_dir, run_dir / name, f"polish lineage {name}")
        if core.sha256_path(geometry) != receipt.get(key):
            raise core.CampaignError(f"polish lineage geometry hash mismatch: {name}")
    configured_pseudos = core.required(config, "pseudopotentials.files")
    pseudo_inventory = receipt.get("pseudopotential_archive")
    if (
        not isinstance(configured_pseudos, Mapping)
        or not isinstance(pseudo_inventory, Mapping)
        or set(pseudo_inventory) != set(configured_pseudos)
    ):
        raise core.CampaignError("polish lineage pseudopotential inventory is invalid")
    pseudo_root = _strict_run_path(
        run_dir,
        run_dir / "lineage_source/pseudopotentials",
        "archived pseudopotential directory",
    )
    if not pseudo_root.is_dir():
        raise core.CampaignError("archived pseudopotential path is not a directory")
    expected_pseudo_names = {str(value) for value in configured_pseudos.values()}
    if {path.name for path in pseudo_root.iterdir()} != expected_pseudo_names:
        raise core.CampaignError("archived pseudopotential directory has unexpected entries")
    for species, filename_value in configured_pseudos.items():
        filename = str(filename_value)
        record = pseudo_inventory.get(species)
        relative = f"lineage_source/pseudopotentials/{filename}"
        if (
            not isinstance(record, Mapping)
            or record.get("filename") != filename
            or record.get("relative_path") != relative
        ):
            raise core.CampaignError(
                f"archived pseudopotential identity mismatch: {species}"
            )
        archived = _strict_run_path(
            run_dir, run_dir / relative, f"archived pseudopotential {species}"
        )
        if not archived.is_file() or core.sha256_path(archived) != _digest(
            record.get("sha256"), "archived pseudopotential hash"
        ):
            raise core.CampaignError(
                f"archived pseudopotential hash mismatch: {species}"
            )
    archived_launch_path = _strict_run_path(
        run_dir,
        run_dir / "lineage_source/one_reset_attempt/relax_launch.json",
        "archived one-reset launch",
    )
    archived_launch = core.load_json(archived_launch_path)
    launch_pseudos = archived_launch.get("pseudopotentials")
    review = receipt.get("review")
    if not isinstance(launch_pseudos, Mapping) or not isinstance(review, Mapping):
        raise core.CampaignError(
            "polish lineage lacks archived launch pseudopotential evidence"
        )
    archived_pseudo_content = {
        str(species): {
            "filename": str(record["filename"]),
            "sha256": str(record["sha256"]),
        }
        for species, record in pseudo_inventory.items()
    }
    if (
        _pseudo_content(launch_pseudos) != archived_pseudo_content
        or review.get("pseudopotentials") != archived_pseudo_content
    ):
        raise core.CampaignError(
            "archived pseudopotentials differ from the one-reset launch lineage"
        )
    diagnostic_inputs = receipt.get("diagnostic_input_sha256")
    if not isinstance(diagnostic_inputs, Mapping) or set(diagnostic_inputs) != {
        "baseline.in",
        "higher_ecutrho.in",
    }:
        raise core.CampaignError("polish diagnostic input inventory is invalid")
    for name, digest in diagnostic_inputs.items():
        diagnostic_input = _strict_run_path(
            run_dir,
            run_dir / "diagnostic/inputs" / name,
            f"polish diagnostic input {name}",
        )
        if core.sha256_path(diagnostic_input) != digest:
            raise core.CampaignError(f"polish diagnostic input hash mismatch: {name}")
    expected_baseline, expected_higher = _diagnostic_inputs(
        config,
        (run_dir / "lineage_source/one_reset_attempt/relax.in").read_text(),
        (run_dir / "lineage_source/one_reset_attempt/relax.out").read_text(),
        pseudo_root,
    )
    if (
        (run_dir / "diagnostic/inputs/baseline.in").read_text()
        != expected_baseline
        or (run_dir / "diagnostic/inputs/higher_ecutrho.in").read_text()
        != expected_higher
    ):
        raise core.CampaignError(
            "polish diagnostic inputs do not reference the immutable pseudopotential archive"
        )
    return receipt


def verify_diagnostic_submission_ready(
    config_path: Path, run_dir: Path
) -> dict[str, Any]:
    """Replay the prepared lineage and prove that diagnostic remains one-shot."""

    config, validation = core.validate_config(config_path)
    run_dir = core.safe_run_dir(run_dir)
    if not run_dir.is_dir():
        raise core.CampaignError(f"prepared polish RUN_DIR does not exist: {run_dir}")
    if config.get("reviewed_bfgs_polish") is None:
        raise core.CampaignError(
            "diagnostic stage is valid only for a reviewed_bfgs_polish campaign"
        )
    manifest_path = _strict_run_path(
        run_dir,
        run_dir / core.RUN_MANIFEST,
        "polish run manifest",
        require_exists=False,
    )
    if os.path.lexists(manifest_path):
        raise core.CampaignError(
            "polish manifest is already released; diagnostic submission is closed"
        )
    diagnostic_root = _strict_run_path(
        run_dir, run_dir / "diagnostic", "diagnostic root"
    )
    lineage_path = _strict_run_path(
        run_dir, run_dir / LINEAGE_RECEIPT, "polish lineage receipt"
    )
    attempts_root = _strict_run_path(
        run_dir, diagnostic_root / "attempts", "diagnostic attempts root"
    )
    dispatch_claim = _strict_run_path(
        run_dir,
        diagnostic_root / "dispatch_claim",
        "diagnostic dispatch claim",
        require_exists=False,
    )
    submission_root = _strict_run_path(
        run_dir,
        run_dir / "submissions/diagnostic",
        "diagnostic submission root",
        require_exists=False,
    )
    slurm_attempts_root = _strict_run_path(
        run_dir,
        run_dir / "slurm_attempts/diagnostic",
        "diagnostic Slurm attempts root",
        require_exists=False,
    )
    if not attempts_root.is_dir():
        raise core.CampaignError(
            "prepare-lineage has not created the diagnostic attempt root"
        )
    lineage = _load_lineage(config, run_dir)
    if any(attempts_root.iterdir()):
        raise core.CampaignError(
            "the single reviewed diagnostic attempt has already been consumed"
        )
    if os.path.lexists(dispatch_claim):
        raise core.CampaignError(
            "the single reviewed diagnostic dispatch has already been consumed"
        )
    if os.path.lexists(submission_root) and not submission_root.is_dir():
        raise core.CampaignError("diagnostic submission root is not a directory")
    if submission_root.is_dir() and any(
        path.name != ".submission.lock" for path in submission_root.iterdir()
    ):
        raise core.CampaignError(
            "the single reviewed diagnostic submission has already been consumed"
        )
    if os.path.lexists(slurm_attempts_root) and not slurm_attempts_root.is_dir():
        raise core.CampaignError("diagnostic Slurm attempts root is not a directory")
    if slurm_attempts_root.is_dir() and any(slurm_attempts_root.iterdir()):
        raise core.CampaignError(
            "the single reviewed diagnostic Slurm attempt has already been consumed"
        )
    final_path = _strict_run_path(
        run_dir,
        diagnostic_root / "final",
        "diagnostic final evidence",
        require_exists=False,
    )
    if os.path.lexists(final_path):
        raise core.CampaignError("diagnostic final evidence already exists")
    config_sha = validation.get("config_sha256")
    if config_sha != core.sha256_path(config_path.resolve()):
        raise core.CampaignError("diagnostic config SHA256 changed during validation")
    return {
        "schema_version": 1,
        "material": core.required(config, "material.formula"),
        "config_sha256": config_sha,
        "lineage": str(lineage_path),
        "lineage_sha256": core.sha256_path(lineage_path),
        "polish_policy_sha256": lineage["polish_policy_sha256"],
        "structure_accepted": False,
        "preflight_unlocked": False,
        "maximum_diagnostic_attempts": 1,
    }


def _diagnostic_resource_record(config: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the live allocation against the signed configured request."""

    resources = core.required(config, "scheduler.diagnostic_resources")
    if not isinstance(resources, Mapping):
        raise core.CampaignError("diagnostic resource policy must be an object")
    expected_sha = core.canonical_sha256(resources)
    if os.environ.get("P3_DIAGNOSTIC_RESOURCE_SHA256") != expected_sha:
        raise core.CampaignError(
            "diagnostic resource-policy SHA256 differs from the submitted config"
        )

    observed: dict[str, Any] = {}
    for config_key, environment_key in (
        ("nodes", "SLURM_JOB_NUM_NODES"),
        ("ntasks", "SLURM_NTASKS"),
        ("cpus_per_task", "SLURM_CPUS_PER_TASK"),
    ):
        raw = os.environ.get(environment_key, "")
        if re.fullmatch(r"[1-9][0-9]*", raw) is None:
            raise core.CampaignError(
                f"diagnostic allocation lacks valid {environment_key}"
            )
        observed[config_key] = int(raw)
        if observed[config_key] != resources.get(config_key):
            raise core.CampaignError(
                f"diagnostic allocation differs from configured {config_key}"
            )

    partition = os.environ.get("SLURM_JOB_PARTITION", "")
    if partition != resources.get("partition"):
        raise core.CampaignError(
            "diagnostic allocation differs from configured partition"
        )
    observed["partition"] = partition

    account = os.environ.get("SLURM_JOB_ACCOUNT", "")
    if account != core.required(config, "scheduler.slurm_account"):
        raise core.CampaignError(
            "diagnostic allocation differs from configured Slurm account"
        )
    observed["account"] = account

    memory = os.environ.get("SLURM_MEM_PER_CPU", "")
    memory_match = re.fullmatch(r"([1-9][0-9]*)([Mm]?)", memory)
    if memory_match is None:
        raise core.CampaignError(
            "diagnostic allocation lacks valid SLURM_MEM_PER_CPU"
        )
    memory_mb = int(memory_match.group(1))
    if memory_mb != resources.get("mem_per_cpu_mb"):
        raise core.CampaignError(
            "diagnostic allocation differs from configured mem_per_cpu_mb"
        )
    observed["mem_per_cpu_mb"] = memory_mb

    expected_minutes = int(float(resources.get("walltime_hours")) * 60)
    requested_minutes = os.environ.get("P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES", "")
    if (
        re.fullmatch(r"[1-9][0-9]*", requested_minutes) is None
        or int(requested_minutes) != expected_minutes
    ):
        raise core.CampaignError(
            "diagnostic submitted walltime differs from configured walltime_hours"
        )
    raw_time = os.environ.get("SLURM_TIMELIMIT", "")
    if raw_time:
        time_limit_minutes = _slurm_time_minutes(raw_time, "diagnostic SLURM_TIMELIMIT")
        time_limit_source = "native_slurm_timelimit"
    else:
        # Nibi does not always expose SLURM_TIMELIMIT inside an allocation.
        # This signed, allow-listed request enables only the diagnostic to run;
        # finalization still requires the authoritative sacct TimelimitRaw.
        time_limit_minutes = int(requested_minutes)
        time_limit_source = "submitted_request_export"
    if time_limit_minutes != expected_minutes:
        raise core.CampaignError(
            "diagnostic allocation differs from configured walltime_hours"
        )
    observed["time_limit_minutes"] = time_limit_minutes
    observed["time_limit_source"] = time_limit_source
    return {
        "policy_sha256": expected_sha,
        "configured": dict(resources),
        "observed_allocation": observed,
    }


def run_diagnostic(config_path: Path, run_dir: Path, *, attempt_id: str) -> dict[str, Any]:
    core.require_compute_node()
    slurm_job_id = os.environ["SLURM_JOB_ID"]
    slurm_nodelist = os.environ["SLURM_JOB_NODELIST"]
    if re.fullmatch(r"[1-9][0-9]*", slurm_job_id) is None:
        raise core.CampaignError("diagnostic SLURM_JOB_ID is invalid")
    if SLURM_NODELIST_RE.fullmatch(slurm_nodelist) is None:
        raise core.CampaignError("diagnostic SLURM_JOB_NODELIST is invalid")
    config, _ = core.validate_config(config_path)
    run_dir = core.safe_run_dir(run_dir)
    lineage = _load_lineage(config, run_dir)
    expected_lineage_sha = core.sha256_path(run_dir / LINEAGE_RECEIPT)
    if os.environ.get("P3_DIAGNOSTIC_LINEAGE_SHA256") != expected_lineage_sha:
        raise core.CampaignError(
            "diagnostic prepared-lineage hash differs from the submitted request"
        )
    backend_sha = core.sha256_path(Path(__file__))
    if os.environ.get("P3_DIAGNOSTIC_BACKEND_SHA256") != backend_sha:
        raise core.CampaignError(
            "diagnostic backend hash differs from the submitted workflow"
        )
    resources = _diagnostic_resource_record(config)
    manifest_path = _strict_run_path(
        run_dir,
        run_dir / core.RUN_MANIFEST,
        "polish run manifest",
        require_exists=False,
    )
    if os.path.lexists(manifest_path):
        raise core.CampaignError("polish is already released; diagnostic cannot be rerun")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id) is None:
        raise core.CampaignError("invalid diagnostic attempt ID")
    attempts_root = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/attempts",
        "diagnostic attempts root",
    )
    if not attempts_root.is_dir():
        raise core.CampaignError("diagnostic attempts root is not a directory")
    if any(attempts_root.iterdir()):
        raise core.CampaignError(
            "the single reviewed diagnostic attempt has already been consumed"
        )
    dispatch_claim = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/dispatch_claim",
        "diagnostic dispatch claim",
    )
    claim_context = _context(
        _strict_run_path(
            run_dir,
            dispatch_claim / "context.tsv",
            "diagnostic dispatch claim context",
        )
    )
    if (
        claim_context.get("attempt_id") != attempt_id
        or claim_context.get("slurm_job_id") != slurm_job_id
    ):
        raise core.CampaignError("diagnostic dispatch claim identity mismatch")
    wrapper_attempt = _strict_run_path(
        run_dir,
        run_dir / "slurm_attempts/diagnostic" / attempt_id,
        "diagnostic Slurm wrapper attempt",
    )
    if not wrapper_attempt.is_dir():
        raise core.CampaignError("diagnostic Slurm wrapper attempt is not a directory")
    if os.environ.get("P3_ATTEMPT_DIR") != str(wrapper_attempt):
        raise core.CampaignError("diagnostic Slurm wrapper environment identity mismatch")
    attempt = _strict_run_path(
        run_dir,
        attempts_root / attempt_id,
        "diagnostic scientific attempt",
        require_exists=False,
    )
    if os.path.lexists(attempt):
        raise core.CampaignError("diagnostic scientific attempt already exists")
    attempt.mkdir(parents=False, exist_ok=False)
    attempt = _strict_run_path(
        run_dir, attempt, "diagnostic scientific attempt", require_exists=True
    )
    baseline_source = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/inputs/baseline.in",
        "baseline diagnostic input",
    )
    higher_source = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/inputs/higher_ecutrho.in",
        "higher-ecutrho diagnostic input",
    )
    inputs = (baseline_source, baseline_source, higher_source)
    labels = ("baseline-a", "baseline-b", "higher-ecutrho")
    executions: dict[str, Any] = {}
    started_utc = core.utc_now()
    for label, source in zip(labels, inputs):
        work = attempt / label
        work.mkdir()
        work = _strict_run_path(
            run_dir, work, f"diagnostic work directory {label}"
        )
        core.write_immutable(work / "scf.in", source.read_text())
        if (work / "tmp-diagnostic").exists():
            raise core.CampaignError("diagnostic requires fresh QE scratch")
        command = core.qe_command("scf.in")
        process = core.run_process(command, work, work / "scf.out", work / "scf.err")
        process_path = work / "scf.process.json"
        executions[label] = {
            "command": command,
            "input_sha256": core.sha256_path(work / "scf.in"),
            "output_sha256": core.sha256_path(work / "scf.out"),
            "stderr_sha256": core.sha256_path(work / "scf.err"),
            "process": process,
            "process_record_sha256": core.sha256_path(process_path),
            "fresh_scratch": True,
        }
    execution = {
        "schema_version": 1,
        "created_utc": core.utc_now(),
        "started_utc": started_utc,
        "finished_utc": core.utc_now(),
        "slurm": {
            "job_id": slurm_job_id,
            "node_list": slurm_nodelist,
        },
        "context": {
            "run_dir": str(run_dir),
            "attempt_id": attempt_id,
            "config_canonical_sha256": core.canonical_sha256(config),
        },
        "lineage_sha256": core.sha256_path(run_dir / LINEAGE_RECEIPT),
        "polish_policy_sha256": lineage["polish_policy_sha256"],
        "resources": resources,
        "workflow_sha256": {
            "submit.py": os.environ.get("P3_SUBMIT_SCRIPT_SHA256"),
            "campaign.py": os.environ.get("P3_CAMPAIGN_CLI_SHA256"),
            "cluster.env": os.environ.get("P3_CLUSTER_ENV_SHA256"),
            "diagnostic.sbatch": os.environ.get("P3_STAGE_SCRIPT_SHA256"),
            "polish_recovery.py": backend_sha,
        },
        "runs": executions,
        "structure_accepted": False,
    }
    core.write_json_immutable(attempt / DIAGNOSTIC_EXECUTION, execution)
    return execution


def _audit_diagnostic_attempt(
    config: Mapping[str, Any],
    run_dir: Path,
    attempt: Path,
    *,
    expected_execution_sha256: str,
    expected_slurm_job_id: str,
    expected_command: Sequence[str],
) -> dict[str, Any]:
    """Replay exact diagnostic execution, process, and force evidence."""

    lineage = _load_lineage(config, run_dir)
    execution_path = attempt / DIAGNOSTIC_EXECUTION
    if core.sha256_path(execution_path) != _digest(
        expected_execution_sha256, "diagnostic execution hash"
    ):
        raise core.CampaignError("diagnostic execution SHA256 mismatch")
    execution = core.load_json(execution_path)
    if (
        execution.get("schema_version") != 1
        or execution.get("structure_accepted") is not False
    ):
        raise core.CampaignError(
            "diagnostic execution must be schema version 1 and structure-neutral"
        )
    for field in ("created_utc", "started_utc", "finished_utc"):
        if UTC_RE.fullmatch(str(execution.get(field, ""))) is None:
            raise core.CampaignError(f"diagnostic execution has invalid {field}")
    slurm = execution.get("slurm")
    if (
        not isinstance(slurm, Mapping)
        or re.fullmatch(r"[1-9][0-9]*", str(slurm.get("job_id", ""))) is None
        or SLURM_NODELIST_RE.fullmatch(str(slurm.get("node_list", ""))) is None
    ):
        raise core.CampaignError("diagnostic execution has invalid Slurm identity")
    if str(slurm.get("job_id")) != expected_slurm_job_id:
        raise core.CampaignError(
            "diagnostic execution Slurm job ID differs from the submitted primary job"
        )
    context = execution.get("context")
    if (
        not isinstance(context, Mapping)
        or context.get("run_dir") != str(run_dir)
        or context.get("attempt_id") != attempt.name
        or context.get("config_canonical_sha256") != core.canonical_sha256(config)
    ):
        raise core.CampaignError("diagnostic execution context identity mismatch")
    if execution.get("lineage_sha256") != core.sha256_path(run_dir / LINEAGE_RECEIPT):
        raise core.CampaignError("diagnostic execution/lineage mismatch")
    if execution.get("polish_policy_sha256") != lineage.get("polish_policy_sha256"):
        raise core.CampaignError("diagnostic execution/polish-policy mismatch")
    resources = execution.get("resources")
    configured_resources = core.required(config, "scheduler.diagnostic_resources")
    if (
        not isinstance(resources, Mapping)
        or resources.get("policy_sha256")
        != core.canonical_sha256(configured_resources)
        or resources.get("configured") != configured_resources
    ):
        raise core.CampaignError("diagnostic execution/resource-policy mismatch")
    observed_resources = resources.get("observed_allocation")
    expected_observed = {
        key: configured_resources[key]
        for key in ("partition", "nodes", "ntasks", "cpus_per_task")
    }
    expected_observed["mem_per_cpu_mb"] = configured_resources["mem_per_cpu_mb"]
    expected_observed["account"] = core.required(config, "scheduler.slurm_account")
    expected_observed["time_limit_minutes"] = int(
        float(configured_resources["walltime_hours"]) * 60
    )
    if (
        not isinstance(observed_resources, Mapping)
        or {
            key: value
            for key, value in observed_resources.items()
            if key != "time_limit_source"
        }
        != expected_observed
        or observed_resources.get("time_limit_source")
        not in {"native_slurm_timelimit", "submitted_request_export"}
    ):
        raise core.CampaignError("diagnostic execution/allocation mismatch")
    expected_workflow = {
        "submit.py": core.sha256_path(Path(__file__).with_name("submit.py")),
        "campaign.py": core.sha256_path(Path(__file__).with_name("campaign.py")),
        "cluster.env": core.sha256_path(
            Path(__file__).with_name("slurm") / "cluster.env"
        ),
        "diagnostic.sbatch": core.sha256_path(
            Path(__file__).with_name("slurm") / "diagnostic.sbatch"
        ),
        "polish_recovery.py": core.sha256_path(Path(__file__)),
    }
    if execution.get("workflow_sha256") != expected_workflow:
        raise core.CampaignError("diagnostic execution/workflow hash mismatch")
    labels = ("baseline-a", "baseline-b", "higher-ecutrho")
    runs = execution.get("runs")
    if not isinstance(runs, Mapping) or set(runs) != set(labels):
        raise core.CampaignError("diagnostic execution has an invalid run inventory")
    expected_input_hashes = {
        "baseline-a": core.sha256_path(run_dir / "diagnostic/inputs/baseline.in"),
        "baseline-b": core.sha256_path(run_dir / "diagnostic/inputs/baseline.in"),
        "higher-ecutrho": core.sha256_path(run_dir / "diagnostic/inputs/higher_ecutrho.in"),
    }
    output_hashes: dict[str, str] = {}
    health: dict[str, Any] = {}
    nat = int(core.required(config, "material.unitcell_atoms"))
    expected_command = list(expected_command)
    for label in labels:
        record = runs.get(label)
        work = attempt / label
        if (
            not isinstance(record, Mapping)
            or record.get("input_sha256") != expected_input_hashes[label]
            or record.get("fresh_scratch") is not True
        ):
            raise core.CampaignError(f"diagnostic input identity mismatch: {label}")
        for key, filename in (
            ("input_sha256", "scf.in"),
            ("output_sha256", "scf.out"),
            ("stderr_sha256", "scf.err"),
        ):
            if record.get(key) != core.sha256_path(work / filename):
                raise core.CampaignError(f"diagnostic exact hash mismatch: {label}/{filename}")
        process = record.get("process")
        process_path = work / "scf.process.json"
        if (
            not isinstance(process, Mapping)
            or process.get("returncode") != 0
            or process.get("cwd") != str(work)
            or record.get("command") != expected_command
            or process.get("command") != expected_command
            or process.get("stdout_sha256") != record.get("output_sha256")
            or process.get("stderr_sha256") != record.get("stderr_sha256")
            or record.get("process_record_sha256") != core.sha256_path(process_path)
            or core.load_json(process_path) != process
        ):
            raise core.CampaignError(f"diagnostic process identity/hash mismatch: {label}")
        for field in ("started_utc", "finished_utc"):
            if UTC_RE.fullmatch(str(process.get(field, ""))) is None:
                raise core.CampaignError(
                    f"diagnostic process has invalid {field}: {label}"
                )
        if (work / "scf.err").read_text().strip():
            raise core.CampaignError(f"diagnostic stderr is nonempty: {label}")
        health[label] = inspect_output(work / "scf.out", nat)
        if not health[label]["healthy"]:
            raise core.CampaignError(f"diagnostic output is unhealthy: {label}")
        output_hashes[label] = core.sha256_path(work / "scf.out")
    if expected_input_hashes["baseline-a"] != expected_input_hashes["baseline-b"]:
        raise core.CampaignError("baseline diagnostic SCFs are not byte-identical")

    baseline_a = parse_last_force_block(attempt / "baseline-a/scf.out", nat)
    baseline_b = parse_last_force_block(attempt / "baseline-b/scf.out", nat)
    higher = parse_last_force_block(attempt / "higher-ecutrho/scf.out", nat)
    duplicate = compare_force_records(baseline_a, baseline_b)
    density = compare_force_records(baseline_a, higher)
    policy = core.required(config, "reviewed_bfgs_polish.force_consistency_diagnostic")
    checks = {
        "two_baseline_inputs_byte_identical": True,
        "all_three_outputs_healthy": True,
        "duplicate_noise_within_limit": float(duplicate["rms_difference_ry_bohr"])
        <= float(core.required(policy, "maximum_duplicate_rms_difference_ry_bohr")),
        "higher_ecutrho_component_difference_within_limit": float(density["max_abs_difference_ry_bohr"])
        <= float(core.required(policy, "maximum_higher_ecutrho_component_difference_ry_bohr")),
        "higher_ecutrho_rms_difference_within_limit": float(density["rms_difference_ry_bohr"])
        <= float(core.required(policy, "maximum_higher_ecutrho_rms_difference_ry_bohr")),
    }
    return {
        "execution": execution,
        "checks": checks,
        "input_sha256": expected_input_hashes,
        "output_sha256": output_hashes,
        "output_health": health,
        "duplicate_noise_comparison": duplicate,
        "higher_ecutrho_comparison": density,
    }


def _strict_json(run_dir: Path, path: Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = _strict_run_path(run_dir, path, label)
    if not path.is_file():
        raise core.CampaignError(f"{label} is not a regular file")
    value = core.load_json(path)
    if not isinstance(value, dict):
        raise core.CampaignError(f"{label} is not a JSON object")
    return path, value


def _strict_text(run_dir: Path, path: Path, label: str) -> tuple[Path, str]:
    path = _strict_run_path(run_dir, path, label)
    if not path.is_file():
        raise core.CampaignError(f"{label} is not a regular file")
    return path, path.read_text()


def _reject_symlinks_below(run_dir: Path, root: Path, label: str) -> None:
    root = _strict_run_path(run_dir, root, label)
    if not root.is_dir():
        raise core.CampaignError(f"{label} is not a directory")
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            _strict_run_path(run_dir, Path(parent) / name, label)


def _slurm_time_minutes(raw: str, label: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", raw):
        return int(raw)
    matched = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", raw)
    if matched is None:
        raise core.CampaignError(f"{label} is invalid")
    days = int(matched.group(1) or 0)
    hours, minutes, seconds = map(int, matched.groups()[1:])
    if minutes >= 60 or seconds != 0:
        raise core.CampaignError(f"{label} is not minute-exact")
    return days * 1440 + hours * 60 + minutes


def _command_exports(command: Any, label: str) -> dict[str, str]:
    if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
        raise core.CampaignError(f"{label} command is invalid")
    export_args = [item for item in command if item.startswith("--export=")]
    if len(export_args) != 1:
        raise core.CampaignError(f"{label} must contain exactly one Slurm export argument")
    payload = export_args[0].removeprefix("--export=")
    if not payload or payload == "ALL" or payload.startswith("ALL,"):
        raise core.CampaignError(f"{label} inherited an unreviewed submission environment")
    result: dict[str, str] = {}
    for pair in payload.split(","):
        if "=" not in pair:
            raise core.CampaignError(f"{label} export is not an explicit assignment")
        name, value = pair.split("=", 1)
        if not name or name in result:
            raise core.CampaignError(f"{label} export contains a duplicate/empty name")
        result[name] = value
    return result


def _audit_diagnostic_dispatch_chain(
    config: Mapping[str, Any],
    config_path: Path,
    run_dir: Path,
    attempt_id: str,
    expected_execution_sha256: str,
) -> dict[str, Any]:
    """Replay the unique submit, wrapper, collector, and accounting chain."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id) is None:
        raise core.CampaignError("invalid diagnostic attempt ID")
    config_path = config_path.resolve(strict=True)
    config_sha = core.sha256_path(config_path)
    lineage = _load_lineage(config, run_dir)
    lineage_path = _strict_run_path(
        run_dir, run_dir / LINEAGE_RECEIPT, "diagnostic lineage receipt"
    )
    lineage_sha = core.sha256_path(lineage_path)
    resources = core.required(config, "scheduler.diagnostic_resources")
    resource_sha = core.canonical_sha256(resources)
    account = str(core.required(config, "scheduler.slurm_account"))
    expected_minutes = int(float(resources["walltime_hours"]) * 60)

    submission_root = _strict_run_path(
        run_dir, run_dir / "submissions/diagnostic", "diagnostic submission root"
    )
    if not submission_root.is_dir():
        raise core.CampaignError("diagnostic submission root is not a directory")
    submission_lock = submission_root / ".submission.lock"
    if os.path.lexists(submission_lock):
        submission_lock = _strict_run_path(
            run_dir, submission_lock, "diagnostic submission lock"
        )
        if not stat.S_ISREG(os.lstat(submission_lock).st_mode):
            raise core.CampaignError(
                "diagnostic submission lock is not a regular non-symlink file"
            )
    submission_entries = {
        item.name for item in submission_root.iterdir() if item.name != ".submission.lock"
    }
    if submission_entries != {attempt_id}:
        raise core.CampaignError(
            "diagnostic finalization requires exactly one same-ID submission record"
        )
    submission_dir = _strict_run_path(
        run_dir, submission_root / attempt_id, "diagnostic submission attempt"
    )
    diagnostic_attempts = _strict_run_path(
        run_dir, run_dir / "diagnostic/attempts", "diagnostic attempts root"
    )
    if not diagnostic_attempts.is_dir():
        raise core.CampaignError("diagnostic attempts root is not a directory")
    if {item.name for item in diagnostic_attempts.iterdir()} != {attempt_id}:
        raise core.CampaignError(
            "diagnostic finalization requires exactly one same-ID scientific attempt"
        )
    diagnostic_attempt = _strict_run_path(
        run_dir,
        diagnostic_attempts / attempt_id,
        "diagnostic scientific attempt",
    )
    slurm_root = _strict_run_path(
        run_dir, run_dir / "slurm_attempts/diagnostic", "diagnostic Slurm root"
    )
    if not slurm_root.is_dir():
        raise core.CampaignError("diagnostic Slurm root is not a directory")
    if {item.name for item in slurm_root.iterdir()} != {attempt_id}:
        raise core.CampaignError(
            "diagnostic finalization requires exactly one same-ID Slurm attempt"
        )
    wrapper = _strict_run_path(
        run_dir, slurm_root / attempt_id, "diagnostic Slurm attempt"
    )
    claim = _strict_run_path(
        run_dir, run_dir / "diagnostic/dispatch_claim", "diagnostic dispatch claim"
    )
    for root, label in (
        (submission_dir, "diagnostic submission attempt"),
        (diagnostic_attempt, "diagnostic scientific attempt"),
        (wrapper, "diagnostic Slurm attempt"),
        (claim, "diagnostic dispatch claim"),
    ):
        _reject_symlinks_below(run_dir, root, label)

    request_path, request = _strict_json(
        run_dir, submission_dir / "request.json", "diagnostic submission request"
    )
    primary_result_path, primary_result = _strict_json(
        run_dir,
        submission_dir / "primary_result.json",
        "diagnostic submission response",
    )
    summary_path, summary = _strict_json(
        run_dir, submission_dir / "submission.json", "diagnostic submission summary"
    )
    collector_request_path, collector_request = _strict_json(
        run_dir,
        submission_dir / "collector_request.json",
        "diagnostic collector request",
    )
    collector_result_path, collector_result = _strict_json(
        run_dir,
        submission_dir / "collector_result.json",
        "diagnostic collector response",
    )
    expected_submission_files = {
        "request.json",
        "primary_result.json",
        "submission.json",
        "collector_request.json",
        "collector_result.json",
    }
    if {item.name for item in submission_dir.iterdir()} != expected_submission_files:
        raise core.CampaignError(
            "diagnostic submission record has an ambiguous file inventory"
        )

    campaign_dir = Path(__file__).resolve().parent
    workflow = {
        "submit.py": core.sha256_path(campaign_dir / "submit.py"),
        "campaign.py": core.sha256_path(campaign_dir / "campaign.py"),
        "cluster.env": core.sha256_path(campaign_dir / "slurm/cluster.env"),
        "diagnostic.sbatch": core.sha256_path(
            campaign_dir / "slurm/diagnostic.sbatch"
        ),
        "polish_recovery.py": core.sha256_path(Path(__file__)),
    }
    scheduler_options = [
        f"--partition={resources['partition']}",
        f"--nodes={resources['nodes']}",
        f"--ntasks={resources['ntasks']}",
        f"--cpus-per-task={resources['cpus_per_task']}",
        f"--mem-per-cpu={resources['mem_per_cpu_mb']}M",
        f"--time={expected_minutes // 60:02d}:{expected_minutes % 60:02d}:00",
    ]
    request_command = request.get("command")
    exports = _command_exports(request_command, "diagnostic submission")
    expected_exports = {
        "CAMPAIGN_CONFIG": str(config_path),
        "RUN_DIR": str(run_dir),
        "ATTEMPT_ID": attempt_id,
        "P3_SLURM_DIR": str(campaign_dir / "slurm"),
        "P3_EXPECTED_CONFIG_SHA256": config_sha,
        "P3_SUBMIT_SCRIPT_SHA256": workflow["submit.py"],
        "P3_STAGE_SCRIPT_SHA256": workflow["diagnostic.sbatch"],
        "P3_CLUSTER_ENV_SHA256": workflow["cluster.env"],
        "P3_CAMPAIGN_CLI_SHA256": workflow["campaign.py"],
        "P3_DIAGNOSTIC_RESOURCE_SHA256": resource_sha,
        "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES": str(expected_minutes),
        "P3_DIAGNOSTIC_LINEAGE_SHA256": lineage_sha,
        "P3_DIAGNOSTIC_BACKEND_SHA256": workflow["polish_recovery.py"],
    }
    if exports != expected_exports:
        raise core.CampaignError("diagnostic submission export allow-list mismatch")
    expected_command_without_export = [
        "sbatch",
        "--parsable",
        f"--account={account}",
        *scheduler_options,
    ]
    export_index = request_command.index(
        next(item for item in request_command if item.startswith("--export="))
    )
    if (
        request_command[:export_index] != expected_command_without_export
        or request_command[export_index + 1 :]
        != [str(campaign_dir / "slurm/diagnostic.sbatch")]
    ):
        raise core.CampaignError("diagnostic submission command/resource mismatch")
    if (
        request.get("stage") != "diagnostic"
        or request.get("attempt_id") != attempt_id
        or request.get("slurm_account") != account
        or request.get("config") != str(config_path)
        or request.get("config_sha256") != config_sha
        or request.get("run_dir") != str(run_dir)
        or request.get("run_manifest_sha256") is not None
        or request.get("polish_lineage_sha256") != lineage_sha
        or request.get("diagnostic_lineage_sha256") != lineage_sha
        or request.get("diagnostic_resource_sha256") != resource_sha
        or request.get("diagnostic_requested_walltime_minutes") != str(expected_minutes)
        or request.get("scheduler_options") != scheduler_options
        or request.get("workflow_sha256") != workflow
        or request.get("submit_script_sha256") != workflow["submit.py"]
        or request.get("stage_script_sha256") != workflow["diagnostic.sbatch"]
        or request.get("cluster_env_sha256") != workflow["cluster.env"]
    ):
        raise core.CampaignError("diagnostic submission request evidence mismatch")

    primary_job_id = str(primary_result.get("job_id", ""))
    primary_stdout = str(primary_result.get("stdout", ""))
    primary_stdout_line = next(
        (line.strip() for line in primary_stdout.splitlines() if line.strip()), ""
    )
    if (
        re.fullmatch(r"[1-9][0-9]*", primary_job_id) is None
        or primary_result.get("stage") != "diagnostic"
        or primary_result.get("attempt_id") != attempt_id
        or primary_result.get("config_sha256") != config_sha
        or primary_result.get("returncode") != 0
        or primary_result.get("command") != request_command
        or re.fullmatch(rf"{re.escape(primary_job_id)}(?:;[^\s;]+)?", primary_stdout_line)
        is None
        or UTC_RE.fullmatch(str(primary_result.get("finished_utc", ""))) is None
    ):
        raise core.CampaignError("diagnostic primary submission response mismatch")

    collector = summary.get("collector")
    if (
        summary.get("healthy") is not True
        or summary.get("mode") != "execute"
        or summary.get("stage") != "diagnostic"
        or summary.get("attempt_id") != attempt_id
        or summary.get("primary_job_id") != primary_job_id
        or summary.get("primary_command") != request_command
        or summary.get("config_sha256") != config_sha
        or summary.get("slurm_account") != account
        or summary.get("polish_lineage_sha256") != lineage_sha
        or summary.get("diagnostic_resource_sha256") != resource_sha
        or summary.get("diagnostic_requested_walltime_minutes") != str(expected_minutes)
        or summary.get("scheduler_options") != scheduler_options
        or summary.get("workflow_sha256") != workflow
        or summary.get("record_dir") != str(submission_dir)
        or not isinstance(collector, Mapping)
    ):
        raise core.CampaignError("diagnostic submission summary mismatch")

    collector_attempt_id = str(collector.get("attempt_id", ""))
    collector_job_id = str(collector.get("job_id", ""))
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", collector_attempt_id)
        is None
        or re.fullmatch(r"[1-9][0-9]*", collector_job_id) is None
        or collector_attempt_id == attempt_id
        or collector_job_id == primary_job_id
        or collector.get("primary_stage") != "diagnostic"
        or collector.get("primary_attempt_id") != attempt_id
        or collector.get("primary_job_id") != primary_job_id
        or collector.get("dependency") != f"afterany:{primary_job_id}"
        or collector.get("command") != collector_request.get("command")
        or collector.get("request_sha256") != core.sha256_path(collector_request_path)
        or collector.get("result_sha256") != core.sha256_path(collector_result_path)
    ):
        raise core.CampaignError("diagnostic collector summary identity mismatch")
    if (
        collector_request.get("stage") != "collect"
        or collector_request.get("attempt_id") != collector_attempt_id
        or collector_request.get("slurm_account") != account
        or collector_request.get("config_sha256") != config_sha
        or collector_request.get("primary_stage") != "diagnostic"
        or collector_request.get("primary_attempt_id") != attempt_id
        or collector_request.get("primary_job_id") != primary_job_id
        or collector_request.get("primary_request_sha256")
        != core.sha256_path(request_path)
        or collector_request.get("primary_result_sha256")
        != core.sha256_path(primary_result_path)
        or collector_request.get("primary_stage_script_sha256")
        != workflow["diagnostic.sbatch"]
        or collector_request.get("collector_script_sha256")
        != core.sha256_path(campaign_dir / "slurm/collect.sbatch")
        or collector_request.get("cluster_env_sha256") != workflow["cluster.env"]
        or collector_request.get("campaign_cli_sha256") != workflow["campaign.py"]
        or collector_request.get("diagnostic_lineage_sha256") != lineage_sha
        or collector_request.get("diagnostic_resource_sha256") != resource_sha
        or collector_request.get("diagnostic_requested_walltime_minutes") != str(expected_minutes)
        or collector_request.get("dependency") != f"afterany:{primary_job_id}"
    ):
        raise core.CampaignError("diagnostic collector request evidence mismatch")
    collector_command = collector_request.get("command")
    collector_exports = _command_exports(collector_command, "diagnostic collector")
    collect_script = campaign_dir / "slurm/collect.sbatch"
    expected_collector_exports = {
        **expected_exports,
        "ATTEMPT_ID": collector_attempt_id,
        "P3_STAGE_SCRIPT_SHA256": core.sha256_path(collect_script),
        "PRIMARY_STAGE": "diagnostic",
        "PRIMARY_ATTEMPT_ID": attempt_id,
        "PRIMARY_JOB_ID": primary_job_id,
        "PRIMARY_REQUEST_SHA256": core.sha256_path(request_path),
        "PRIMARY_RESULT_SHA256": core.sha256_path(primary_result_path),
        "PRIMARY_STAGE_SCRIPT_SHA256": workflow["diagnostic.sbatch"],
    }
    collector_export_arg = next(
        item for item in collector_command if item.startswith("--export=")
    )
    collector_export_index = collector_command.index(collector_export_arg)
    if (
        collector_exports != expected_collector_exports
        or collector_command[:collector_export_index]
        != ["sbatch", "--parsable", f"--account={account}"]
        or collector_command[collector_export_index + 1 :]
        != [f"--dependency=afterany:{primary_job_id}", str(collect_script)]
    ):
        raise core.CampaignError("diagnostic collector dispatch command mismatch")
    collector_stdout = str(collector_result.get("stdout", ""))
    collector_stdout_line = next(
        (line.strip() for line in collector_stdout.splitlines() if line.strip()), ""
    )
    if (
        collector_result.get("stage") != "collect"
        or collector_result.get("attempt_id") != collector_attempt_id
        or collector_result.get("job_id") != collector_job_id
        or collector_result.get("primary_stage") != "diagnostic"
        or collector_result.get("primary_attempt_id") != attempt_id
        or collector_result.get("primary_job_id") != primary_job_id
        or collector_result.get("config_sha256") != config_sha
        or collector_result.get("returncode") != 0
        or collector_result.get("command") != collector_command
        or re.fullmatch(
            rf"{re.escape(collector_job_id)}(?:;[^\s;]+)?", collector_stdout_line
        )
        is None
        or UTC_RE.fullmatch(str(collector_result.get("finished_utc", ""))) is None
    ):
        raise core.CampaignError("diagnostic collector submission response mismatch")

    collector_root = _strict_run_path(
        run_dir, run_dir / "slurm_attempts/collect", "diagnostic collector root"
    )
    if not collector_root.is_dir() or {
        item.name for item in collector_root.iterdir()
    } != {collector_attempt_id}:
        raise core.CampaignError(
            "diagnostic finalization requires exactly one referenced collector attempt"
        )

    claim_context = _context(
        _strict_run_path(
            run_dir, claim / "context.tsv", "diagnostic dispatch claim context"
        )
    )
    wrapper_context = _context(
        _strict_run_path(
            run_dir, wrapper / "context.tsv", "diagnostic wrapper context"
        )
    )
    claim_expected = {
        "attempt_id": attempt_id,
        "slurm_job_id": primary_job_id,
        "config_sha256": config_sha,
        "lineage_sha256": lineage_sha,
        "resource_sha256": resource_sha,
        "requested_walltime_minutes": str(expected_minutes),
        "submit_script_sha256": workflow["submit.py"],
        "stage_script_sha256": workflow["diagnostic.sbatch"],
        "cluster_env_sha256": workflow["cluster.env"],
        "campaign_cli_sha256": workflow["campaign.py"],
        "diagnostic_backend_sha256": workflow["polish_recovery.py"],
    }
    if any(claim_context.get(key) != value for key, value in claim_expected.items()):
        raise core.CampaignError("diagnostic dispatch claim evidence mismatch")
    wrapper_expected = {
        "stage": "diagnostic",
        "attempt_id": attempt_id,
        "slurm_job_id": primary_job_id,
        "slurm_job_account": account,
        "slurm_job_partition": str(resources["partition"]),
        "slurm_job_num_nodes": str(resources["nodes"]),
        "slurm_ntasks": str(resources["ntasks"]),
        "slurm_cpus_per_task": str(resources["cpus_per_task"]),
        "config": str(config_path),
        "config_sha256": config_sha,
        "campaign_cli": str(campaign_dir / "campaign.py"),
        "campaign_cli_sha256": workflow["campaign.py"],
        "submit_script_sha256": workflow["submit.py"],
        "stage_script_sha256": workflow["diagnostic.sbatch"],
        "cluster_env_sha256": workflow["cluster.env"],
        "run_dir": str(run_dir),
        "diagnostic_resource_sha256": resource_sha,
        "diagnostic_requested_walltime_minutes": str(expected_minutes),
        "diagnostic_lineage_sha256": lineage_sha,
        "diagnostic_backend_sha256": workflow["polish_recovery.py"],
    }
    if any(wrapper_context.get(key) != value for key, value in wrapper_expected.items()):
        raise core.CampaignError("diagnostic Slurm wrapper context mismatch")
    runtime_expected = {
        "stdenv_module": "StdEnv/2023",
        "qe_module": "quantumespresso/7.3.1",
        "qe_executable": "pw.x",
        "qe_mpi_launcher": "srun",
        "qe_nk": "1",
        "omp_num_threads": str(resources["cpus_per_task"]),
    }
    if any(
        wrapper_context.get(key) != value
        for key, value in runtime_expected.items()
    ):
        raise core.CampaignError("diagnostic fixed runtime context mismatch")
    p3_account_uid = str(wrapper_context.get("p3_account_uid", ""))
    p3_account_home_raw = str(wrapper_context.get("p3_account_home", ""))
    p3_account_home = Path(p3_account_home_raw)
    p3_venv = Path(wrapper_context.get("p3_venv", ""))
    p3_pseudo_dir = Path(wrapper_context.get("p3_pseudo_dir", ""))
    if (
        re.fullmatch(r"[1-9][0-9]*", p3_account_uid) is None
        or not p3_account_home.is_absolute()
        or p3_account_home == Path("/")
        or str(p3_account_home) != p3_account_home_raw
        or p3_venv != p3_account_home / "venvs/p3"
        or p3_pseudo_dir
        != p3_account_home / "pseudos/SSSP-1.3.0-PBE-precision"
    ):
        raise core.CampaignError("diagnostic derived runtime path mismatch")
    if wrapper_context.get("slurm_mem_per_cpu") not in {
        str(resources["mem_per_cpu_mb"]),
        f"{resources['mem_per_cpu_mb']}M",
        f"{resources['mem_per_cpu_mb']}m",
    }:
        raise core.CampaignError("diagnostic wrapper memory allocation mismatch")
    wrapper_native_time = str(wrapper_context.get("slurm_timelimit", ""))
    wrapper_time_source = wrapper_context.get("diagnostic_time_limit_source")
    if wrapper_native_time:
        if (
            wrapper_time_source != "native_slurm_timelimit"
            or _slurm_time_minutes(wrapper_native_time, "diagnostic wrapper time limit")
            != expected_minutes
        ):
            raise core.CampaignError("diagnostic wrapper walltime mismatch")
    elif (
        wrapper_time_source != "submitted_request_export"
        or wrapper_context.get("diagnostic_requested_walltime_minutes")
        != str(expected_minutes)
    ):
        raise core.CampaignError("diagnostic wrapper walltime fallback mismatch")
    exit_path, exit_text = _strict_text(
        run_dir, wrapper / "exit_code.txt", "diagnostic wrapper exit code"
    )
    finished_path, finished_text = _strict_text(
        run_dir, wrapper / "finished_utc.txt", "diagnostic wrapper finish time"
    )
    if exit_text.strip() != "0" or UTC_RE.fullmatch(finished_text.strip()) is None:
        raise core.CampaignError("diagnostic Slurm wrapper did not complete successfully")

    execution_path = _strict_run_path(
        run_dir,
        diagnostic_attempt / DIAGNOSTIC_EXECUTION,
        "diagnostic execution record",
    )
    if core.sha256_path(execution_path) != _digest(
        expected_execution_sha256, "diagnostic execution hash"
    ):
        raise core.CampaignError("diagnostic execution/submission chain hash mismatch")

    collector_wrapper = _strict_run_path(
        run_dir,
        run_dir / "slurm_attempts/collect" / collector_attempt_id,
        "diagnostic collector Slurm attempt",
    )
    _reject_symlinks_below(
        run_dir, collector_wrapper, "diagnostic collector Slurm attempt"
    )
    collector_context = _context(
        _strict_run_path(
            run_dir, collector_wrapper / "context.tsv", "diagnostic collector context"
        )
    )
    collector_context_expected = {
        "stage": "collect",
        "attempt_id": collector_attempt_id,
        "slurm_job_id": collector_job_id,
        "slurm_job_account": account,
        "config_sha256": config_sha,
        "run_dir": str(run_dir),
        "primary_stage": "diagnostic",
        "primary_attempt_id": attempt_id,
        "primary_job_id": primary_job_id,
        "primary_request_sha256": core.sha256_path(request_path),
        "primary_result_sha256": core.sha256_path(primary_result_path),
        "primary_stage_script_sha256": workflow["diagnostic.sbatch"],
        "campaign_cli_sha256": workflow["campaign.py"],
        "submit_script_sha256": workflow["submit.py"],
        "cluster_env_sha256": workflow["cluster.env"],
        "stage_script_sha256": core.sha256_path(
            campaign_dir / "slurm/collect.sbatch"
        ),
        "diagnostic_resource_sha256": resource_sha,
        "diagnostic_lineage_sha256": lineage_sha,
        "diagnostic_backend_sha256": workflow["polish_recovery.py"],
        "p3_account_uid": p3_account_uid,
        "p3_account_home": p3_account_home_raw,
        **runtime_expected,
        "p3_venv": str(p3_venv),
        "p3_pseudo_dir": str(p3_pseudo_dir),
    }
    if any(
        collector_context.get(key) != value
        for key, value in collector_context_expected.items()
    ):
        raise core.CampaignError("diagnostic collector Slurm context mismatch")
    collector_exit_path, collector_exit = _strict_text(
        run_dir,
        collector_wrapper / "exit_code.txt",
        "diagnostic collector wrapper exit code",
    )
    collector_finished_path, collector_finished = _strict_text(
        run_dir,
        collector_wrapper / "finished_utc.txt",
        "diagnostic collector wrapper finish time",
    )
    if collector_exit.strip() != "0" or UTC_RE.fullmatch(
        collector_finished.strip()
    ) is None:
        raise core.CampaignError("diagnostic collector wrapper did not succeed")

    collection_path, collection = _strict_json(
        run_dir,
        collector_wrapper / "collection.json",
        "diagnostic collection",
    )
    collection_receipt_path, collection_receipt = _strict_json(
        run_dir,
        collector_wrapper / "collection_receipt.json",
        "diagnostic collection receipt",
    )
    if collection != collection_receipt:
        raise core.CampaignError("diagnostic collection and receipt differ")
    primary_collection = collection.get("primary")
    submission_collection = collection.get("submission")
    entry = collection.get("entry")
    if (
        collection.get("schema_version") != 1
        or collection.get("stage") != "collect"
        or collection.get("collection_kind") != "diagnostic_single_attempt"
        or collection.get("material") != core.required(config, "material.formula")
        or UTC_RE.fullmatch(str(collection.get("collected_utc", ""))) is None
        or collection.get("collector_attempt") != str(collector_wrapper)
        or collection.get("collection_integrity_complete") is not True
        or collection.get("scheduler_completed_successfully") is not True
        or collection.get("wrapper_completed_successfully") is not True
        or collection.get("diagnostic_execution_present") is not True
        or collection.get("diagnostic_execution_complete") is not True
        or collection.get("incomplete") is not False
        or collection.get("scientific_gate_published") is not False
        or collection.get("structure_accepted") is not False
        or collection.get("preflight_unlocked") is not False
        or not isinstance(primary_collection, Mapping)
        or primary_collection.get("stage") != "diagnostic"
        or primary_collection.get("attempt_id") != attempt_id
        or primary_collection.get("job_id") != primary_job_id
        or primary_collection.get("wrapper_attempt") != str(wrapper)
        or primary_collection.get("diagnostic_execution") != str(execution_path)
        or primary_collection.get("diagnostic_execution_sha256")
        != expected_execution_sha256
        or not isinstance(submission_collection, Mapping)
        or submission_collection.get("record_dir") != str(submission_dir)
        or submission_collection.get("request_sha256")
        != core.sha256_path(request_path)
        or submission_collection.get("primary_result_sha256")
        != core.sha256_path(primary_result_path)
        or not isinstance(entry, Mapping)
        or entry.get("errors") != []
        or entry.get("wrapper_exit_code") != 0
        or entry.get("context") != wrapper_context
        or entry.get("dispatch_claim") != claim_context
        or entry.get("evidence")
        != core._hash_present_evidence(
            wrapper,
            (
                "context.tsv",
                "exit_code.txt",
                "finished_utc.txt",
                "stdout.log",
                "stderr.log",
            ),
        )
    ):
        raise core.CampaignError("diagnostic collection receipt evidence mismatch")
    accounting = primary_collection.get("scheduler_accounting")
    if not isinstance(accounting, Mapping):
        raise core.CampaignError("diagnostic collection lacks scheduler accounting")
    accounting_path = _strict_run_path(
        run_dir,
        Path(str(accounting.get("path", ""))),
        "diagnostic raw scheduler accounting",
    )
    accounting_status_path = _strict_run_path(
        run_dir,
        Path(str(accounting.get("status_path", ""))),
        "diagnostic scheduler accounting status",
    )
    if (
        accounting_path.parent != collector_wrapper
        or accounting_status_path.parent != collector_wrapper
        or accounting.get("sha256") != core.sha256_path(accounting_path)
        or accounting.get("status_sha256")
        != core.sha256_path(accounting_status_path)
        or accounting.get("sacct_exit_code") != 0
    ):
        raise core.CampaignError("diagnostic scheduler accounting hash/status mismatch")
    records, accounting_errors, metadata = core._read_sacct_records(
        accounting_path,
        accounting_status_path,
        core.DIAGNOSTIC_SACCT_FIELDS,
    )
    if accounting_errors or metadata != accounting:
        raise core.CampaignError("diagnostic raw scheduler accounting replay failed")
    related = [
        row
        for row in records
        if row.get("JobIDRaw") == primary_job_id
        or row.get("JobIDRaw", "").startswith(primary_job_id + ".")
    ]
    allocations = [row for row in related if row.get("JobIDRaw") == primary_job_id]
    if len(allocations) != 1 or entry.get("scheduler_records") != related:
        raise core.CampaignError("diagnostic scheduler accounting identity mismatch")
    allocation = allocations[0]
    try:
        allocated_cpus = int(allocation["AllocCPUS"])
        nodes = int(allocation["NNodes"])
        ncpus = int(allocation["NCPUS"])
        elapsed = int(allocation["ElapsedRaw"])
        time_limit = int(allocation["TimelimitRaw"])
        total_memory = core._diagnostic_reqmem_total_mb(
            allocation["ReqMem"], allocated_cpus=allocated_cpus, nodes=nodes
        )
    except (KeyError, TypeError, ValueError, core.CampaignError) as exc:
        raise core.CampaignError("diagnostic scheduler allocation is invalid") from exc
    if (
        entry.get("allocation") != allocation
        or core._normalized_slurm_state(allocation["State"]) != "COMPLETED"
        or allocation["ExitCode"] != "0:0"
        or allocation["Account"] != account
        or allocation["Partition"] != resources["partition"]
        or nodes != resources["nodes"]
        or allocated_cpus != resources["ntasks"] * resources["cpus_per_task"]
        or ncpus != allocated_cpus
        or time_limit != expected_minutes
        or not 0 <= elapsed <= expected_minutes * 60
        or not abs(
            total_memory
            - resources["mem_per_cpu_mb"]
            * resources["ntasks"]
            * resources["cpus_per_task"]
        )
        <= 0.01
    ):
        raise core.CampaignError("diagnostic scheduler resource/completion mismatch")

    return {
        "attempt_id": attempt_id,
        "primary_job_id": primary_job_id,
        "collector_attempt_id": collector_attempt_id,
        "collector_job_id": collector_job_id,
        "config_sha256": config_sha,
        "lineage_sha256": lineage_sha,
        "resource_sha256": resource_sha,
        "workflow_sha256": workflow,
        "submission_request_sha256": core.sha256_path(request_path),
        "submission_result_sha256": core.sha256_path(primary_result_path),
        "submission_summary_sha256": core.sha256_path(summary_path),
        "dispatch_claim_sha256": core.sha256_path(claim / "context.tsv"),
        "wrapper_context_sha256": core.sha256_path(wrapper / "context.tsv"),
        "wrapper_exit_code_sha256": core.sha256_path(exit_path),
        "wrapper_finished_utc_sha256": core.sha256_path(finished_path),
        "diagnostic_execution_sha256": expected_execution_sha256,
        "collector_request_sha256": core.sha256_path(collector_request_path),
        "collector_result_sha256": core.sha256_path(collector_result_path),
        "collector_context_sha256": core.sha256_path(
            collector_wrapper / "context.tsv"
        ),
        "collector_exit_code_sha256": core.sha256_path(collector_exit_path),
        "collector_finished_utc_sha256": core.sha256_path(
            collector_finished_path
        ),
        "collection_sha256": core.sha256_path(collection_path),
        "collection_receipt_sha256": core.sha256_path(collection_receipt_path),
        "scheduler_accounting_sha256": core.sha256_path(accounting_path),
        "scheduler_accounting_status_sha256": core.sha256_path(
            accounting_status_path
        ),
        "scheduler_allocation": allocation,
        "qe_command": [
            runtime_expected["qe_mpi_launcher"],
            runtime_expected["qe_executable"],
            "-nk",
            runtime_expected["qe_nk"],
            "-in",
            "scf.in",
        ],
    }


def _require_gate_matches_audit(gate: Mapping[str, Any], audit: Mapping[str, Any]) -> None:
    for key in (
        "checks",
        "input_sha256",
        "output_sha256",
        "output_health",
        "duplicate_noise_comparison",
        "higher_ecutrho_comparison",
    ):
        if gate.get(key) != audit.get(key):
            raise core.CampaignError(f"diagnostic gate differs from replayed evidence: {key}")
    checks = audit["checks"]
    if not isinstance(checks, Mapping) or gate.get("pass") is not all(checks.values()):
        raise core.CampaignError("diagnostic gate pass value differs from replayed checks")


def finalize_diagnostic(
    config_path: Path,
    run_dir: Path,
    *,
    attempt_id: str,
    expected_execution_sha256: str,
) -> dict[str, Any]:
    config, _ = core.validate_config(config_path)
    config_path = config_path.resolve(strict=True)
    run_dir = core.safe_run_dir(run_dir)
    attempt = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/attempts" / attempt_id,
        "diagnostic scientific attempt",
    )
    submission_chain = _audit_diagnostic_dispatch_chain(
        config,
        config_path,
        run_dir,
        attempt_id,
        expected_execution_sha256,
    )
    audit = _audit_diagnostic_attempt(
        config,
        run_dir,
        attempt,
        expected_execution_sha256=expected_execution_sha256,
        expected_slurm_job_id=submission_chain["primary_job_id"],
        expected_command=submission_chain["qe_command"],
    )
    checks = audit["checks"]
    policy = core.required(config, "reviewed_bfgs_polish.force_consistency_diagnostic")
    receipt = {
        "schema_version": 1,
        "created_utc": core.utc_now(),
        "pass": all(checks.values()),
        "checks": checks,
        "lineage_sha256": core.sha256_path(run_dir / LINEAGE_RECEIPT),
        "execution_sha256": expected_execution_sha256,
        "submission_chain": submission_chain,
        "input_sha256": audit["input_sha256"],
        "output_sha256": audit["output_sha256"],
        "output_health": audit["output_health"],
        "duplicate_noise_comparison": audit["duplicate_noise_comparison"],
        "higher_ecutrho_comparison": audit["higher_ecutrho_comparison"],
        "thresholds": dict(policy),
        "structure_accepted": False,
        "preflight_unlocked": False,
        "limitations": [
            "This diagnostic compares force repeatability and ecutrho sensitivity only.",
            "It does not establish ionic convergence, accept a structure, or replace the independent pristine SCF gate.",
        ],
    }
    receipt_path = _strict_run_path(
        run_dir,
        attempt / DIAGNOSTIC_RECEIPT,
        "diagnostic attempt receipt",
        require_exists=False,
    )
    core.write_json_immutable(receipt_path, receipt)
    if not receipt["pass"]:
        raise core.CampaignError("force-consistency diagnostic failed; polish remains blocked")
    final = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/final",
        "diagnostic final directory",
        require_exists=False,
    )
    if final.exists():
        raise core.CampaignError("diagnostic final directory already exists")
    final.mkdir(exist_ok=False)
    _strict_run_path(run_dir, final, "diagnostic final directory")
    core.write_json_immutable(final / "gate.json", receipt)
    core.write_json_immutable(
        final / "provenance.json",
        {
            "attempt": str(attempt),
            "attempt_id": attempt_id,
            "receipt_sha256": core.sha256_path(receipt_path),
            "execution_sha256": expected_execution_sha256,
            "submission_chain_sha256": core.canonical_sha256(submission_chain),
        },
    )
    return receipt


def _audit_final_diagnostic(
    config: Mapping[str, Any], config_path: Path, run_dir: Path, gate_path: Path
) -> dict[str, Any]:
    """Replay the finalized diagnostic from raw files and immutable records."""

    config_path = config_path.resolve(strict=True)
    gate_path, gate = _strict_json(run_dir, gate_path, "diagnostic final gate")
    provenance_path, provenance = _strict_json(
        run_dir,
        run_dir / "diagnostic/final/provenance.json",
        "diagnostic final provenance",
    )
    if (
        gate.get("pass") is not True
        or gate.get("structure_accepted") is not False
        or gate.get("preflight_unlocked") is not False
    ):
        raise core.CampaignError("a passing diagnostic-only gate is required before polish release")
    attempt_id = str(provenance.get("attempt_id", ""))
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id) is None:
        raise core.CampaignError("diagnostic final provenance attempt ID is invalid")
    diagnostic_attempt = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/attempts" / attempt_id,
        "diagnostic final scientific attempt",
    )
    if provenance.get("attempt") != str(diagnostic_attempt):
        raise core.CampaignError("diagnostic final provenance attempt path mismatch")
    receipt_path = _strict_run_path(
        run_dir,
        diagnostic_attempt / DIAGNOSTIC_RECEIPT,
        "diagnostic final attempt receipt",
    )
    if core.sha256_path(receipt_path) != provenance.get("receipt_sha256"):
        raise core.CampaignError("diagnostic final provenance hash mismatch")
    if core.load_json(receipt_path) != gate:
        raise core.CampaignError("diagnostic final gate differs from its immutable attempt receipt")
    execution_sha256 = _digest(gate.get("execution_sha256"), "diagnostic gate execution hash")
    if provenance.get("execution_sha256") != execution_sha256:
        raise core.CampaignError("diagnostic provenance/execution hash mismatch")
    submission_chain = _audit_diagnostic_dispatch_chain(
        config,
        config_path,
        run_dir,
        attempt_id,
        execution_sha256,
    )
    if (
        gate.get("submission_chain") != submission_chain
        or provenance.get("submission_chain_sha256")
        != core.canonical_sha256(submission_chain)
    ):
        raise core.CampaignError("diagnostic final submission chain differs from replay")
    audit = _audit_diagnostic_attempt(
        config,
        run_dir,
        diagnostic_attempt,
        expected_execution_sha256=execution_sha256,
        expected_slurm_job_id=submission_chain["primary_job_id"],
        expected_command=submission_chain["qe_command"],
    )
    _require_gate_matches_audit(gate, audit)
    return gate


def release_polish(config_path: Path, run_dir: Path) -> dict[str, Any]:
    config, _ = core.validate_config(config_path)
    config_path = config_path.resolve(strict=True)
    run_dir = core.safe_run_dir(run_dir)
    lineage = _load_lineage(config, run_dir)
    manifest_path = _strict_run_path(
        run_dir,
        run_dir / core.RUN_MANIFEST,
        "polish run manifest",
        require_exists=False,
    )
    if os.path.lexists(manifest_path):
        raise core.CampaignError("reviewed polish has already been released; only one is allowed")
    snapshot_path = _strict_run_path(
        run_dir,
        run_dir / "config.snapshot.json",
        "polish config snapshot",
        require_exists=False,
    )
    release_directories = [
        _strict_run_path(
            run_dir,
            run_dir / name,
            f"polish {name} directory",
            require_exists=False,
        )
        for name in ("relax", "preflight")
    ]
    if os.path.lexists(snapshot_path) or any(
        os.path.lexists(directory) for directory in release_directories
    ):
        raise core.CampaignError("polish release targets already exist")
    gate_path = _strict_run_path(
        run_dir,
        run_dir / "diagnostic/final/gate.json",
        "diagnostic final gate",
    )
    _audit_final_diagnostic(config, config_path, run_dir, gate_path)
    manifest = core.manifest_for(config, config_path)
    manifest["relax_polish"] = {
        "kind": "single_reviewed_bfgs_polish",
        "lineage_receipt": LINEAGE_RECEIPT,
        "lineage_sha256": core.sha256_path(run_dir / LINEAGE_RECEIPT),
        "diagnostic_gate": str(gate_path.relative_to(run_dir)),
        "diagnostic_gate_sha256": core.sha256_path(gate_path),
        "maximum_attempts": 1,
        "automatic_submission_allowed": False,
    }
    core.write_json_immutable(manifest_path, manifest)
    core.write_json_immutable(snapshot_path, config)
    for directory in release_directories:
        directory.mkdir(exist_ok=False)
    return {
        "healthy": True,
        "stage": "release-single-reviewed-polish",
        "run_dir": str(run_dir),
        "manifest_sha256": core.sha256_path(run_dir / core.RUN_MANIFEST),
        "polish_policy_sha256": lineage["polish_policy_sha256"],
        "automatic_submission": False,
        "maximum_attempts": 1,
        "structure_accepted": False,
        "preflight_unlocked": False,
        "next": "review submit.py plan for the single relax attempt; ordinary BFGS/pristine/final gate remains mandatory",
    }


def load_polish_start(
    config: Mapping[str, Any],
    run_dir: Path,
    manifest: Mapping[str, Any],
    expected_reference: str,
    pseudopotentials: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    pointer = manifest.get("relax_polish")
    if not isinstance(pointer, Mapping) or pointer.get("maximum_attempts") != 1:
        raise core.CampaignError("invalid single-polish manifest pointer")
    lineage = _load_lineage(config, run_dir)
    if pointer.get("lineage_sha256") != core.sha256_path(run_dir / LINEAGE_RECEIPT):
        raise core.CampaignError("polish manifest/lineage hash mismatch")
    gate_path = _strict_run_path(
        run_dir,
        run_dir / str(pointer.get("diagnostic_gate", "")),
        "polish diagnostic gate",
    )
    if core.sha256_path(gate_path) != pointer.get("diagnostic_gate_sha256"):
        raise core.CampaignError("polish diagnostic gate hash mismatch")
    config_path_raw = manifest.get("config_path")
    if not isinstance(config_path_raw, str):
        raise core.CampaignError("polish manifest lacks its campaign config path")
    _audit_final_diagnostic(config, Path(config_path_raw), run_dir, gate_path)
    seed_path = _strict_run_path(run_dir, run_dir / "polish_seed.in", "polish seed")
    reference_path = _strict_run_path(
        run_dir, run_dir / "polish_reference.in", "polish reference"
    )
    seed = seed_path.read_text()
    reference = reference_path.read_text()
    if reference != expected_reference:
        raise core.CampaignError("polish original cumulative-shift reference mismatch")
    if _pseudo_content(pseudopotentials) != lineage["review"]["pseudopotentials"]:
        raise core.CampaignError("polish pseudopotential content differs from its lineage")
    return seed, {
        "lineage_sha256": pointer["lineage_sha256"],
        "diagnostic_gate_sha256": pointer["diagnostic_gate_sha256"],
        "reference_unitcell_sha256": lineage["reference_unitcell_sha256"],
        "maximum_attempts": 1,
        "automatic_reset": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-lineage")
    for name in ("config", "run-dir", "source-run-dir", "source-attempt"):
        prepare.add_argument(f"--{name}", required=True, type=Path)
    prepare.add_argument("--source-manifest-sha256", required=True)
    prepare.add_argument("--source-output-sha256", required=True)
    run = subparsers.add_parser("run-diagnostic")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--run-dir", required=True, type=Path)
    run.add_argument("--attempt-id", required=True)
    finalize = subparsers.add_parser("finalize-diagnostic")
    finalize.add_argument("--config", required=True, type=Path)
    finalize.add_argument("--run-dir", required=True, type=Path)
    finalize.add_argument("--attempt-id", required=True)
    finalize.add_argument("--expect-execution-sha", required=True)
    release = subparsers.add_parser("release-polish")
    release.add_argument("--config", required=True, type=Path)
    release.add_argument("--run-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare-lineage":
            result = prepare_lineage(
                args.config,
                args.run_dir,
                source_run_dir=args.source_run_dir,
                source_attempt=args.source_attempt,
                source_manifest_sha256=args.source_manifest_sha256,
                source_output_sha256=args.source_output_sha256,
            )
        elif args.command == "run-diagnostic":
            result = run_diagnostic(args.config, args.run_dir, attempt_id=args.attempt_id)
        elif args.command == "finalize-diagnostic":
            result = finalize_diagnostic(
                args.config,
                args.run_dir,
                attempt_id=args.attempt_id,
                expected_execution_sha256=args.expect_execution_sha,
            )
        else:
            result = release_polish(args.config, args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, core.CampaignError) as exc:
        print(json.dumps({"healthy": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

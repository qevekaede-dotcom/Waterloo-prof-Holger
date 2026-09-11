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
from pathlib import Path
from typing import Any, Mapping

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
    pseudo_dirs = {str(Path(str(item["file"])).parent) for item in source_launch["pseudopotentials"].values()}
    if len(pseudo_dirs) != 1:
        raise core.CampaignError("one-reset pseudopotential directories are inconsistent")
    baseline, higher = _diagnostic_inputs(
        config,
        (source_attempt / "relax.in").read_text(),
        (source_attempt / "relax.out").read_text(),
        Path(pseudo_dirs.pop()),
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
    receipt_path = run_dir / LINEAGE_RECEIPT
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
        if core.sha256_path(run_dir / "lineage_source" / relative) != digest:
            raise core.CampaignError(f"archived polish-lineage hash mismatch: {name}")
    for name, key in (
        ("polish_seed.in", "seed_unitcell_sha256"),
        ("polish_reference.in", "reference_unitcell_sha256"),
    ):
        if core.sha256_path(run_dir / name) != receipt.get(key):
            raise core.CampaignError(f"polish lineage geometry hash mismatch: {name}")
    diagnostic_inputs = receipt.get("diagnostic_input_sha256")
    if not isinstance(diagnostic_inputs, Mapping) or set(diagnostic_inputs) != {
        "baseline.in",
        "higher_ecutrho.in",
    }:
        raise core.CampaignError("polish diagnostic input inventory is invalid")
    for name, digest in diagnostic_inputs.items():
        if core.sha256_path(run_dir / "diagnostic/inputs" / name) != digest:
            raise core.CampaignError(f"polish diagnostic input hash mismatch: {name}")
    return receipt


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
    if (run_dir / core.RUN_MANIFEST).exists():
        raise core.CampaignError("polish is already released; diagnostic cannot be rerun")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_id) is None:
        raise core.CampaignError("invalid diagnostic attempt ID")
    attempts_root = run_dir / "diagnostic/attempts"
    if any(path.is_dir() for path in attempts_root.iterdir()):
        raise core.CampaignError(
            "the single reviewed diagnostic attempt has already been consumed"
        )
    attempt = attempts_root / attempt_id
    attempt.mkdir(parents=False, exist_ok=False)
    baseline_source = run_dir / "diagnostic/inputs/baseline.in"
    higher_source = run_dir / "diagnostic/inputs/higher_ecutrho.in"
    inputs = (baseline_source, baseline_source, higher_source)
    labels = ("baseline-a", "baseline-b", "higher-ecutrho")
    executions: dict[str, Any] = {}
    started_utc = core.utc_now()
    for label, source in zip(labels, inputs):
        work = attempt / label
        work.mkdir()
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
) -> dict[str, Any]:
    """Replay exact diagnostic execution, process, and force evidence."""

    lineage = _load_lineage(config, run_dir)
    execution_path = attempt / DIAGNOSTIC_EXECUTION
    if core.sha256_path(execution_path) != _digest(
        expected_execution_sha256, "diagnostic execution hash"
    ):
        raise core.CampaignError("diagnostic execution SHA256 mismatch")
    execution = core.load_json(execution_path)
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
    expected_command = core.qe_command("scf.in")
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
    run_dir = core.safe_run_dir(run_dir)
    attempt = run_dir / "diagnostic/attempts" / attempt_id
    audit = _audit_diagnostic_attempt(
        config,
        run_dir,
        attempt,
        expected_execution_sha256=expected_execution_sha256,
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
    core.write_json_immutable(attempt / DIAGNOSTIC_RECEIPT, receipt)
    if not receipt["pass"]:
        raise core.CampaignError("force-consistency diagnostic failed; polish remains blocked")
    final = run_dir / "diagnostic/final"
    final.mkdir(parents=True, exist_ok=False)
    core.write_json_immutable(final / "gate.json", receipt)
    core.write_json_immutable(
        final / "provenance.json",
        {
            "attempt": str(attempt),
            "receipt_sha256": core.sha256_path(attempt / DIAGNOSTIC_RECEIPT),
            "execution_sha256": expected_execution_sha256,
        },
    )
    return receipt


def _audit_final_diagnostic(
    config: Mapping[str, Any], run_dir: Path, gate_path: Path
) -> dict[str, Any]:
    """Replay the finalized diagnostic from raw files and immutable records."""

    provenance_path = run_dir / "diagnostic/final/provenance.json"
    gate = core.load_json(gate_path)
    provenance = core.load_json(provenance_path)
    if (
        gate.get("pass") is not True
        or gate.get("structure_accepted") is not False
        or gate.get("preflight_unlocked") is not False
    ):
        raise core.CampaignError("a passing diagnostic-only gate is required before polish release")
    diagnostic_attempt = Path(str(provenance.get("attempt", ""))).resolve()
    try:
        diagnostic_attempt.relative_to((run_dir / "diagnostic/attempts").resolve())
    except ValueError as exc:
        raise core.CampaignError("diagnostic final provenance attempt escapes RUN_DIR") from exc
    receipt_path = diagnostic_attempt / DIAGNOSTIC_RECEIPT
    if core.sha256_path(receipt_path) != provenance.get("receipt_sha256"):
        raise core.CampaignError("diagnostic final provenance hash mismatch")
    if core.load_json(receipt_path) != gate:
        raise core.CampaignError("diagnostic final gate differs from its immutable attempt receipt")
    execution_sha256 = _digest(gate.get("execution_sha256"), "diagnostic gate execution hash")
    if provenance.get("execution_sha256") != execution_sha256:
        raise core.CampaignError("diagnostic provenance/execution hash mismatch")
    audit = _audit_diagnostic_attempt(
        config,
        run_dir,
        diagnostic_attempt,
        expected_execution_sha256=execution_sha256,
    )
    _require_gate_matches_audit(gate, audit)
    return gate


def release_polish(config_path: Path, run_dir: Path) -> dict[str, Any]:
    config, _ = core.validate_config(config_path)
    run_dir = core.safe_run_dir(run_dir)
    lineage = _load_lineage(config, run_dir)
    if (run_dir / core.RUN_MANIFEST).exists():
        raise core.CampaignError("reviewed polish has already been released; only one is allowed")
    gate_path = run_dir / "diagnostic/final/gate.json"
    _audit_final_diagnostic(config, run_dir, gate_path)
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
    core.write_json_immutable(run_dir / core.RUN_MANIFEST, manifest)
    core.write_json_immutable(run_dir / "config.snapshot.json", config)
    (run_dir / "relax").mkdir(exist_ok=False)
    (run_dir / "preflight").mkdir(exist_ok=False)
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
    gate_path = run_dir / str(pointer.get("diagnostic_gate", ""))
    if core.sha256_path(gate_path) != pointer.get("diagnostic_gate_sha256"):
        raise core.CampaignError("polish diagnostic gate hash mismatch")
    _audit_final_diagnostic(config, run_dir, gate_path)
    seed = (run_dir / "polish_seed.in").read_text()
    reference = (run_dir / "polish_reference.in").read_text()
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

#!/usr/bin/env python3
"""Fork a fully accepted relax structure into a fresh, self-contained RUN_DIR.

This is a preparation-node operation.  It never runs QE or phono3py and never
modifies the source run.  The source relax, pristine SCF, recovery lineage, and
published gate are replayed before any destination path is created.  Only the
accepted structure is carried forward; stale preflight output and QE scratch
are deliberately excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import campaign as core
from qe_input import parse_qe_input
from qe_output import inspect_output


RECEIPT = "accepted_structure_import.json"
ARCHIVE = "accepted_structure_source"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ATTEMPT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

ROOT_FILES = (
    "run_manifest.json",
    "config.snapshot.json",
    "config_validation.json",
    "source_qe_input",
    "source_original_relax_output",
)
FINAL_FILES = ("unitcell.in", "gate.json", "provenance.json")
ATTEMPT_FILES = (
    "context.tsv",
    "exit_code.txt",
    "finished_utc.txt",
    "stdout.log",
    "stderr.log",
    "starting_unitcell.in",
    "starting_structure_audit.json",
    "relax.in",
    "relax.out",
    "relax.err",
    "relax_launch.json",
    "relax.process.json",
    "pristine.in",
    "pristine.out",
    "pristine.err",
    "pristine_launch.json",
    "pristine.process.json",
    "execution_manifest.json",
    "relax_gate.json",
)
RECOVERY_ATTEMPT_FILES = ("reference_unitcell.in",)
RECOVERY_ROOT_FILES = (
    "relax_recovery.json",
    "recovery_seed.in",
    "recovery_reference.in",
)
RECOVERY_SOURCE_FILES = (
    "starting_unitcell.in",
    "starting_structure_audit.json",
    "relax.in",
    "relax.out",
    "relax.err",
    "relax_launch.json",
    "relax.process.json",
    "context.tsv",
    "exit_code.txt",
    "finished_utc.txt",
    "source_run_manifest.json",
    "source_config.snapshot.json",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise core.CampaignError(message)


def _digest(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
             f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _has_symlink_below(path: Path, root: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current == root:
            return False
        parent = current.parent
        if parent == current:
            return True
        current = parent


def _source_root(path: Path) -> Path:
    raw = Path(path)
    _require(raw.is_absolute(), "source RUN_DIR must be absolute")
    _require("READY_TO_ATTACH" not in raw.parts,
             "source RUN_DIR may not be inside READY_TO_ATTACH")
    _require(not raw.is_symlink(), "source RUN_DIR may not be a symlink")
    resolved = raw.resolve()
    _require(raw == resolved, "source RUN_DIR path may not contain a symlink")
    _require(resolved.is_dir(), f"source RUN_DIR does not exist: {resolved}")
    return resolved


def _destination(path: Path, source: Path) -> Path:
    raw = Path(path)
    _require(raw.is_absolute(), "destination RUN_DIR must be absolute")
    _require("READY_TO_ATTACH" not in raw.parts,
             "destination RUN_DIR may not be inside READY_TO_ATTACH")
    resolved = raw.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), core.REPO_ROOT.resolve()}
    _require(resolved not in forbidden, f"destination RUN_DIR is too broad: {resolved}")
    _require(not raw.exists() and not raw.is_symlink(),
             "destination RUN_DIR already exists; never overwrite or resume an import")
    _require(raw.parent.resolve() == raw.parent,
             "destination RUN_DIR parent path may not contain a symlink")
    _require(resolved != source and not resolved.is_relative_to(source)
             and not source.is_relative_to(resolved),
             "source and destination RUN_DIRs must be separate and non-nested")
    return resolved


def _regular(path: Path, root: Path, label: str) -> Path:
    raw = Path(path)
    _require(not _has_symlink_below(raw, root), f"{label} may not contain a symlink")
    resolved = raw.resolve()
    _require(resolved != root and resolved.is_relative_to(root),
             f"{label} must be a strict descendant of source RUN_DIR")
    _require(resolved.is_file(), f"missing {label}: {resolved}")
    return resolved


def _archive_regular(path: Path, root: Path, label: str) -> Path:
    raw = Path(path)
    _require(not _has_symlink_below(raw, root), f"{label} may not contain a symlink")
    resolved = raw.resolve()
    _require(resolved != root and resolved.is_relative_to(root),
             f"{label} must be a strict descendant of imported RUN_DIR")
    _require(resolved.is_file(), f"missing {label}: {resolved}")
    return resolved


def _context(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        _require(len(fields) == 2 and fields[0] not in result,
                 "accepted attempt has malformed or duplicate context fields")
        result[fields[0]] = fields[1]
    return result


def _pseudo_content(value: Any) -> dict[str, dict[str, str]]:
    _require(isinstance(value, Mapping) and bool(value),
             "accepted attempt has no pseudopotential receipt")
    result: dict[str, dict[str, str]] = {}
    for species, item in value.items():
        _require(isinstance(species, str) and isinstance(item, Mapping),
                 "accepted pseudopotential receipt is malformed")
        result[species] = {
            "filename": Path(str(item.get("file", ""))).name,
            "sha256": _digest(item.get("sha256"), "pseudopotential SHA256"),
        }
    return result


def _same_pseudos(left: Any, right: Any) -> bool:
    try:
        return _pseudo_content(left) == _pseudo_content(right)
    except core.CampaignError:
        return False


def _verify_process(
    attempt: Path,
    identity_attempt: Path,
    stem: str,
    launch: Mapping[str, Any],
) -> dict[str, Any]:
    record = core.load_json(attempt / f"{stem}.process.json")
    command = record.get("command")
    _require(record.get("returncode") == 0, f"accepted {stem} process did not return zero")
    _require(record.get("cwd") == str(identity_attempt),
             f"accepted {stem} process cwd differs from source attempt identity")
    _require(command == launch.get("command") and isinstance(command, list)
             and command[-2:] == ["-in", f"{stem}.in"],
             f"accepted {stem} process/launch command mismatch")
    for key, name in (("stdout_sha256", f"{stem}.out"),
                      ("stderr_sha256", f"{stem}.err")):
        _require(record.get(key) == core.sha256_path(attempt / name),
                 f"accepted {stem} process hash mismatch: {name}")
    _require(not (attempt / f"{stem}.err").read_text().strip(),
             f"accepted {stem} stderr is nonempty")
    return record


def _health_without_path(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "path"}


def _audit_source_acceptance(
    config: Mapping[str, Any],
    physical_run: Path,
    identity_run: Path,
) -> dict[str, Any]:
    """Replay the source gate using raw files; write nothing."""

    manifest = core.load_json(physical_run / core.RUN_MANIFEST)
    structure_policy = core.policy_sha256(config, "structure")
    _require(manifest.get("schema_version") == 2,
             "accepted source uses an unsupported run-manifest schema")
    _require(manifest.get("material") == core.required(config, "material.formula"),
             "accepted source belongs to another material")
    _require(manifest.get("structure_policy_sha256") == structure_policy,
             "source structure policy differs from current structure policy")
    snapshot = core.load_json(physical_run / "config.snapshot.json")
    _require(core.policy_sha256(snapshot, "structure") == structure_policy,
             "source config snapshot/structure policy mismatch")

    final = physical_run / "relax" / "final"
    unitcell = final / "unitcell.in"
    gate_path = final / "gate.json"
    provenance_path = final / "provenance.json"
    gate = core.load_json(gate_path)
    provenance = core.load_json(provenance_path)
    _require(gate.get("pass") is True, "source tight-relax gate is not passing")
    _require(gate.get("final_unitcell_sha256") == core.sha256_path(unitcell),
             "source final unitcell differs from its gate")

    raw_identity_attempt = Path(str(provenance.get("accepted_attempt", "")))
    _require(raw_identity_attempt.is_absolute(),
             "source accepted-attempt identity must be absolute")
    identity_attempt = raw_identity_attempt.resolve()
    expected_parent = identity_run / "slurm_attempts" / "relax"
    _require(identity_attempt.parent == expected_parent
             and ATTEMPT_ID_RE.fullmatch(identity_attempt.name) is not None,
             "source accepted attempt is not an exact relax attempt under source RUN_DIR")
    attempt = physical_run / "slurm_attempts" / "relax" / identity_attempt.name

    execution_path = attempt / "execution_manifest.json"
    audit_path = attempt / "starting_structure_audit.json"
    _require(provenance.get("execution_manifest_sha256") == core.sha256_path(execution_path),
             "source accepted execution-manifest hash mismatch")
    _require(provenance.get("starting_structure_audit_sha256") == core.sha256_path(audit_path),
             "source accepted starting-structure audit hash mismatch")
    _require((attempt / "relax_gate.json").read_bytes() == gate_path.read_bytes(),
             "attempt and published relax gates are not byte-identical")
    _require((attempt / "pristine.in").read_bytes() == unitcell.read_bytes(),
             "accepted pristine input and published unitcell are not byte-identical")

    context = _context(attempt / "context.tsv")
    _require(context.get("stage") == "relax"
             and context.get("attempt_id") == identity_attempt.name
             and context.get("run_dir") == str(identity_run),
             "accepted attempt context/run identity mismatch")
    _require(re.fullmatch(r"[1-9][0-9]*", context.get("slurm_job_id", "")) is not None,
             "accepted attempt lacks a scheduler job identity")
    _require(context.get("config_sha256") == manifest.get("config_sha256"),
             "accepted attempt config differs from source run manifest")
    workflow = manifest.get("workflow_files")
    _require(isinstance(workflow, Mapping) and bool(workflow),
             "source workflow hash inventory is missing")
    campaign_hashes = [value for name, value in workflow.items()
                       if isinstance(name, str) and name.endswith("/campaign.py")]
    _require(len(campaign_hashes) == 1
             and context.get("campaign_cli_sha256") == campaign_hashes[0],
             "accepted attempt campaign hash differs from source manifest")
    _require((attempt / "exit_code.txt").read_text().strip() == "0",
             "accepted attempt wrapper did not finish successfully")
    _require(TIMESTAMP_RE.fullmatch((attempt / "finished_utc.txt").read_text().strip()) is not None,
             "accepted attempt lacks a terminal timestamp")

    execution = core.load_json(execution_path)
    relax_launch = core.load_json(attempt / "relax_launch.json")
    pristine_launch = core.load_json(attempt / "pristine_launch.json")
    for label, record in (("execution manifest", execution),
                          ("relax launch", relax_launch),
                          ("pristine launch", pristine_launch)):
        _require(record.get("structure_policy_sha256") == structure_policy,
                 f"{label} structure-policy hash mismatch")
    _require(execution.get("material") == manifest.get("material"),
             "execution manifest material mismatch")
    _require(relax_launch.get("config_sha256") == manifest.get("config_sha256")
             and pristine_launch.get("config_sha256") == manifest.get("config_sha256"),
             "accepted launch config hash differs from source run manifest")
    for key, name in (
        ("starting_unitcell_sha256", "starting_unitcell.in"),
        ("relax_input_sha256", "relax.in"),
        ("relax_output_sha256", "relax.out"),
        ("pristine_input_sha256", "pristine.in"),
        ("pristine_output_sha256", "pristine.out"),
    ):
        _require(execution.get(key) == core.sha256_path(attempt / name),
                 f"execution-manifest hash mismatch: {name}")
    _require(relax_launch.get("relax_input_sha256") == core.sha256_path(attempt / "relax.in")
             and relax_launch.get("starting_structure_audit_sha256") == core.sha256_path(audit_path),
             "relax launch/input or structure-audit hash mismatch")
    _require(pristine_launch.get("relax_output_sha256") == core.sha256_path(attempt / "relax.out")
             and pristine_launch.get("pristine_input_sha256") == core.sha256_path(attempt / "pristine.in"),
             "pristine launch input/output lineage mismatch")
    relax_process = _verify_process(attempt, identity_attempt, "relax", relax_launch)
    pristine_process = _verify_process(attempt, identity_attempt, "pristine", pristine_launch)
    _require(execution.get("relax_process") == relax_process
             and execution.get("pristine_process") == pristine_process,
             "execution manifest nested process receipts differ from raw process records")
    _require(_same_pseudos(execution.get("pseudopotentials"), relax_launch.get("pseudopotentials"))
             and _same_pseudos(execution.get("pseudopotentials"), pristine_launch.get("pseudopotentials")),
             "accepted launch/execution pseudopotential receipts differ")
    pseudo_content = _pseudo_content(execution["pseudopotentials"])
    configured_pseudos = core.required(config, "pseudopotentials.files")
    _require(set(pseudo_content) == set(configured_pseudos)
             and all(pseudo_content[species]["filename"] == filename
                     for species, filename in configured_pseudos.items()),
             "accepted pseudopotential filenames/species differ from current policy")
    pseudo_dirs = {str(Path(item["file"]).parent) for item in execution["pseudopotentials"].values()}
    _require(len(pseudo_dirs) == 1,
             "accepted pseudopotentials use inconsistent source directories")
    pseudo_dir = Path(pseudo_dirs.pop())

    reference = attempt / "starting_unitcell.in"
    recovery_summary = None
    if manifest.get("relax_recovery") is not None:
        from relax_recovery import load_recovery_start

        reference = attempt / "reference_unitcell.in"
        seed, recovery_summary = load_recovery_start(
            config,
            physical_run,
            manifest,
            reference.read_text(),
            execution["pseudopotentials"],
        )
        _require(seed == (attempt / "starting_unitcell.in").read_text(),
                 "accepted recovery starting unitcell differs from its frozen seed")
        _require(execution.get("recovery") == recovery_summary
                 and relax_launch.get("recovery") == recovery_summary,
                 "accepted recovery launch/execution receipt mismatch")
        starting_audit = core.load_json(audit_path)
        _require(starting_audit.get("pass") is True
                 and starting_audit.get("reference_unitcell_sha256") == core.sha256_path(reference)
                 and starting_audit.get("recovery") == recovery_summary,
                 "accepted recovery cumulative-position reference hash mismatch")
    else:
        _require(execution.get("recovery") is None and relax_launch.get("recovery") is None,
                 "non-recovery accepted run claims recovery evidence")

    nat = int(core.required(config, "material.unitcell_atoms"))
    relax_health = inspect_output(attempt / "relax.out", nat)
    pristine_health = inspect_output(attempt / "pristine.out", nat)
    relax_text = (attempt / "relax.out").read_text(errors="replace")
    pristine_text = (attempt / "pristine.out").read_text(errors="replace")
    expected_relax = core.relax_input_for(
        config, (attempt / "starting_unitcell.in").read_text(), pseudo_dir
    )
    if recovery_summary is not None:
        from qe_input import _set_namelist_values

        expected_relax = _set_namelist_values(
            expected_relax, "CONTROL", {"restart_mode": "'from_scratch'"}
        )
        expected_relax = _set_namelist_values(
            expected_relax,
            "ELECTRONS",
            {"startingpot": "'atomic'", "startingwfc": "'atomic+random'"},
        )
    _require((attempt / "relax.in").read_text() == expected_relax,
             "accepted relax input is not the exact current structure-policy input")
    settings = core.required(config, "tight_relax")
    expected_pristine = core.build_pristine_scf_input(
        expected_relax,
        relax_text,
        outdir="./tmp-pristine",
        prefix=f"{core.required(config, 'material.formula')}_p3_pristine",
        pseudo_dir=str(pseudo_dir),
        disk_io="low",
        tprnfor=True,
        conv_thr=float(core.required(settings, "conv_thr_ry")),
        ecutwfc=float(core.required(settings, "ecutwfc_ry")),
        ecutrho=float(core.required(settings, "ecutrho_ry")),
        kmesh=core.required(settings, "kmesh"),
        kshift=core.required(settings, "kmesh_shift"),
        nosym=True,
        noinv=True,
    )
    _require((attempt / "pristine.in").read_text() == expected_pristine,
             "accepted pristine input is not exactly setting-matched to relax")
    _require(len(re.findall(r"^\s*Program PWSCF\b", relax_text, re.MULTILINE)) == 1
             and len(re.findall(r"^\s*Program PWSCF\b", pristine_text, re.MULTILINE)) == 1,
             "accepted relax/pristine output must contain exactly one QE process each")
    _require(
        relax_text.count("Begin final coordinates") == 1
        and relax_text.count("End final coordinates") == 1
        and relax_text.count("JOB DONE") == 1,
        "accepted relax output must contain exactly one final-coordinate block "
        "and one terminal JOB DONE marker",
    )
    last_force = relax_text.rfind("Forces acting on atoms")
    begin_final = relax_text.find("Begin final coordinates")
    end_final = relax_text.find("End final coordinates")
    job_done = relax_text.find("JOB DONE")
    _require(
        0 <= last_force < begin_final < end_final < job_done,
        "accepted relax output must order its last force block before one final-coordinate "
        "block and terminal JOB DONE",
    )
    bfgs = "bfgs converged" in relax_text.lower() \
        and "End of BFGS Geometry Optimization" in relax_text
    shifts = core._position_shifts_angstrom(reference.read_text(), unitcell.read_text())
    final_input = parse_qe_input(unitcell.read_text())
    tolerances = [float(item["symprec_angstrom"])
                  for item in core.required(config, "symmetry_validation.scan_symprec_pairs")]
    scan = core.symmetry_scan(
        final_input.cell_parameters,
        [item.coordinates for item in final_input.atomic_positions],
        [item.label for item in final_input.atomic_positions],
        tolerances,
    )
    symmetry_policy = core.required(config, "symmetry_validation")
    strict = symmetry_policy.get(
        "post_standardization_strictest_required_matching_symprec_angstrom",
        symmetry_policy.get("strictest_required_matching_symprec_angstrom"),
    )
    _require(strict is not None, "symmetry policy lacks a strict acceptance tolerance")
    expected_number = int(core.required(config, "material.expected_spacegroup_number"))
    symmetry_pass = any(
        math.isclose(item["symprec_angstrom"], float(strict), rel_tol=0, abs_tol=1e-15)
        and item["spacegroup_number"] == expected_number
        for item in scan
    )
    accept_force = float(core.required(settings, "accept_max_force_ry_bohr"))
    hard_stop = float(core.required(settings, "hard_stop_max_force_ry_bohr"))
    max_shift = max(shifts)
    checks = {
        "relax_output_healthy": bool(relax_health["healthy"]),
        "pristine_output_healthy": bool(pristine_health["healthy"]),
        "bfgs_converged": bfgs,
        "relax_force_within_acceptance": float(relax_health["max_abs_force_ry_bohr"]) <= accept_force,
        "pristine_force_within_acceptance": float(pristine_health["max_abs_force_ry_bohr"]) <= accept_force,
        "position_shift_within_limit": max_shift <= float(core.required(settings, "max_position_shift_angstrom")),
        "spacegroup_at_strict_tolerance": symmetry_pass,
    }
    _require(all(checks.values()), "raw accepted structure no longer replays to a passing gate")
    replay = {
        "pass": True,
        "checks": checks,
        "relax_output": _health_without_path(relax_health),
        "pristine_output": _health_without_path(pristine_health),
        "force_acceptance_ry_bohr": accept_force,
        "hard_stop_force_ry_bohr": hard_stop,
        "hard_stop_exceeded": max(float(relax_health["max_abs_force_ry_bohr"]),
                                  float(pristine_health["max_abs_force_ry_bohr"])) > hard_stop,
        "per_atom_position_shift_angstrom": shifts,
        "max_position_shift_angstrom": max_shift,
        "spacegroup_scan": scan,
        "final_unitcell_sha256": core.sha256_path(unitcell),
    }
    for key in ("pass", "checks", "force_acceptance_ry_bohr",
                "hard_stop_force_ry_bohr", "hard_stop_exceeded",
                "per_atom_position_shift_angstrom", "max_position_shift_angstrom",
                "spacegroup_scan", "final_unitcell_sha256"):
        _require(gate.get(key) == replay[key], f"source gate replay mismatch: {key}")
    _require(_health_without_path(gate.get("relax_output", {})) == replay["relax_output"]
             and _health_without_path(gate.get("pristine_output", {})) == replay["pristine_output"],
             "source gate output-health replay mismatch")
    _require(Path(str(gate.get("position_shift_reference", ""))).resolve() == identity_attempt / reference.name,
             "source gate cumulative-position reference identity mismatch")

    return {
        "manifest": manifest,
        "attempt_id": identity_attempt.name,
        "identity_attempt": str(identity_attempt),
        "physical_attempt": str(attempt),
        "gate": gate,
        "replay": replay,
        "pseudopotentials": pseudo_content,
        "recovery": recovery_summary,
        "source_structure_policy_sha256": structure_policy,
        "source_preflight_policy_sha256": manifest.get("preflight_policy_sha256"),
        "audit_sha256": core.canonical_sha256(replay),
    }


def _workflow_blob(repo_relative: str, digest: str, git_commit: str) -> bytes:
    relative = Path(repo_relative)
    _require(not relative.is_absolute() and ".." not in relative.parts
             and relative.parts and relative.name,
             f"invalid source workflow path: {repo_relative}")
    current = (core.REPO_ROOT / relative).resolve()
    if current.is_file() and core.sha256_path(current) == digest:
        return current.read_bytes()
    _require(re.fullmatch(r"[0-9a-f]{40}", git_commit or "") is not None,
             "source workflow bytes changed and manifest has no usable Git commit")
    completed = subprocess.run(
        ["git", "-C", str(core.REPO_ROOT), "show", f"{git_commit}:{repo_relative}"],
        capture_output=True,
        check=False,
    )
    _require(completed.returncode == 0,
             f"cannot recover source workflow bytes from Git: {repo_relative}")
    _require(hashlib.sha256(completed.stdout).hexdigest() == digest,
             f"archived Git workflow hash mismatch: {repo_relative}")
    return completed.stdout


def _copy_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _source_inventory(source: Path, audit: Mapping[str, Any]) -> tuple[dict[str, Path], dict[str, bytes]]:
    """Return fixed-path source files and reconstructed workflow blobs."""

    manifest = audit["manifest"]
    attempt_id = str(audit["attempt_id"])
    paths: dict[str, Path] = {
        "source_run/run_manifest.json": source / "run_manifest.json",
        "source_run/config.snapshot.json": source / "config.snapshot.json",
        "source_run/config_validation.json": source / "config_validation.json",
        "source_run/source_qe_input": Path(str(manifest["source_qe_input"])),
        "source_run/source_original_relax_output": Path(str(manifest["source_relax_output"])),
    }
    for name in FINAL_FILES:
        paths[f"source_run/relax/final/{name}"] = source / "relax" / "final" / name
    for name in ATTEMPT_FILES:
        paths[f"source_run/slurm_attempts/relax/{attempt_id}/{name}"] = (
            source / "slurm_attempts" / "relax" / attempt_id / name
        )
    if manifest.get("relax_recovery") is not None:
        for name in RECOVERY_ATTEMPT_FILES:
            paths[f"source_run/slurm_attempts/relax/{attempt_id}/{name}"] = (
                source / "slurm_attempts" / "relax" / attempt_id / name
            )
        for name in RECOVERY_ROOT_FILES:
            paths[f"source_run/{name}"] = source / name
        for name in RECOVERY_SOURCE_FILES:
            paths[f"source_run/recovery_source/{name}"] = source / "recovery_source" / name

    execution = core.load_json(source / "slurm_attempts" / "relax" / attempt_id / "execution_manifest.json")
    for species, item in execution["pseudopotentials"].items():
        filename = Path(str(item["file"])).name
        paths[f"pseudopotentials/{filename}"] = Path(str(item["file"]))

    blobs: dict[str, bytes] = {}
    git_commit = str(manifest.get("git_commit", ""))
    for repo_relative, digest in manifest["workflow_files"].items():
        digest = _digest(digest, "source workflow SHA256")
        archive_name = f"workflow/accepted_run/{repo_relative}"
        _require(archive_name not in blobs, "duplicate source workflow archive path")
        blobs[archive_name] = _workflow_blob(repo_relative, digest, git_commit)
    if manifest.get("relax_recovery") is not None:
        recovery_receipt = core.load_json(source / "relax_recovery.json")
        recovery_relative = str(
            Path(__file__).with_name("relax_recovery.py").resolve().relative_to(
                core.REPO_ROOT.resolve()
            )
        )
        recovery_digest = _digest(
            recovery_receipt.get("backend_sha256"), "source recovery backend SHA256"
        )
        archive_name = f"workflow/recovery_backend/{recovery_relative}"
        blobs.setdefault(
            archive_name,
            _workflow_blob(recovery_relative, recovery_digest, git_commit),
        )
        failed_manifest = core.load_json(
            source / "recovery_source" / "source_run_manifest.json"
        )
        failed_workflow = failed_manifest.get("workflow_files")
        _require(isinstance(failed_workflow, Mapping) and bool(failed_workflow),
                 "recovery source workflow hash inventory is missing")
        failed_commit = str(failed_manifest.get("git_commit", ""))
        for repo_relative, digest in failed_workflow.items():
            digest = _digest(digest, "recovery source workflow SHA256")
            archive_name = f"workflow/recovery_source_run/{repo_relative}"
            _require(archive_name not in blobs,
                     "duplicate recovery source workflow archive path")
            blobs[archive_name] = _workflow_blob(
                repo_relative, digest, failed_commit
            )
    return paths, blobs


def _validate_inventory_paths(source: Path, paths: Mapping[str, Path], audit: Mapping[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    external_allowed = {
        "source_run/source_qe_input",
        "source_run/source_original_relax_output",
    }
    external_allowed.update(name for name in paths if name.startswith("pseudopotentials/"))
    for archive_name, raw_path in paths.items():
        if archive_name in external_allowed:
            _require(raw_path.is_absolute() and "READY_TO_ATTACH" not in raw_path.parts
                     and not raw_path.is_symlink() and raw_path.resolve() == raw_path
                     and raw_path.is_file(),
                     f"missing or unsafe external source evidence: {archive_name}")
            path = raw_path.resolve()
        else:
            path = _regular(raw_path, source, archive_name)
        hashes[archive_name] = core.sha256_path(path)
    manifest = audit["manifest"]
    _require(hashes["source_run/source_qe_input"] == manifest.get("source_qe_sha256"),
             "source QE input hash differs from run manifest")
    _require(hashes["source_run/source_original_relax_output"] == manifest.get("source_relax_sha256"),
             "source original relax-output hash differs from run manifest")
    for species, item in audit["pseudopotentials"].items():
        _require(hashes[f"pseudopotentials/{item['filename']}"] == item["sha256"],
                 f"pseudopotential content hash mismatch: {species}")
    return hashes


def prepare_import(
    config_path: Path,
    run_dir: Path,
    *,
    source_run_dir: Path,
    source_manifest_sha256: str,
    source_gate_sha256: str,
    source_provenance_sha256: str,
    source_unitcell_sha256: str,
) -> dict[str, Any]:
    """Audit and archive an accepted structure into a new current-policy run."""

    config_path = Path(config_path).resolve()
    config, validation = core.validate_config(config_path)
    source = _source_root(source_run_dir)
    destination = _destination(run_dir, source)
    anchors = {
        "source_run_manifest_sha256": _digest(source_manifest_sha256, "source manifest SHA256"),
        "source_final_gate_sha256": _digest(source_gate_sha256, "source gate SHA256"),
        "source_final_provenance_sha256": _digest(source_provenance_sha256, "source provenance SHA256"),
        "source_final_unitcell_sha256": _digest(source_unitcell_sha256, "source unitcell SHA256"),
    }
    anchor_paths = {
        "source_run_manifest_sha256": source / "run_manifest.json",
        "source_final_gate_sha256": source / "relax" / "final" / "gate.json",
        "source_final_provenance_sha256": source / "relax" / "final" / "provenance.json",
        "source_final_unitcell_sha256": source / "relax" / "final" / "unitcell.in",
    }
    for label, path in anchor_paths.items():
        _regular(path, source, label)
        _require(core.sha256_path(path) == anchors[label], f"{label} mismatch")

    audit = _audit_source_acceptance(config, source, source)
    source_paths, workflow_blobs = _source_inventory(source, audit)
    source_hashes = _validate_inventory_paths(source, source_paths, audit)
    workflow_hashes = {name: hashlib.sha256(data).hexdigest()
                       for name, data in workflow_blobs.items()}

    # All source validation is complete.  Claim a new directory exactly once.
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / ARCHIVE
    for name, path in source_paths.items():
        _copy_bytes_exclusive(archive / name, path.resolve().read_bytes())
        _require(core.sha256_path(archive / name) == source_hashes[name]
                 and core.sha256_path(path.resolve()) == source_hashes[name],
                 f"source evidence changed while archiving: {name}")
    for name, data in workflow_blobs.items():
        _copy_bytes_exclusive(archive / name, data)
        _require(core.sha256_path(archive / name) == workflow_hashes[name],
                 f"workflow archive hash mismatch: {name}")

    receipt = {
        "schema_version": 1,
        "kind": "imported_accepted_structure",
        "created_utc": core.utc_now(),
        "material": core.required(config, "material.formula"),
        "source_run_identity": str(source),
        "source_attempt_identity": audit["identity_attempt"],
        "source_attempt_id": audit["attempt_id"],
        "anchors": anchors,
        "source_files": source_hashes,
        "workflow_files": workflow_hashes,
        "pseudopotentials": audit["pseudopotentials"],
        "source_structure_policy_sha256": audit["source_structure_policy_sha256"],
        "source_preflight_policy_sha256": audit["source_preflight_policy_sha256"],
        "destination_structure_policy_sha256": core.policy_sha256(config, "structure"),
        "destination_preflight_policy_sha256": core.policy_sha256(config, "preflight"),
        "destination_config_sha256": core.sha256_path(config_path),
        "source_acceptance_audit_sha256": audit["audit_sha256"],
        "backend_sha256": core.sha256_path(Path(__file__)),
        "source_paths_archived": True,
        "external_source_paths_required": False,
        "excluded": ["QE scratch", "old preflight evidence", "old submissions", "collector evidence"],
        "limitations": [
            "This import preserves an accepted structure for a new preflight policy only.",
            "It is not new relaxation, force, cutoff, supercell, phonon, or kappa evidence.",
        ],
    }
    core.write_json_immutable(destination / RECEIPT, receipt)
    receipt_sha = core.sha256_path(destination / RECEIPT)

    current_manifest = core.manifest_for(config, config_path)
    current_manifest["source_qe_input"] = str(archive / "source_run" / "source_qe_input")
    current_manifest["source_relax_output"] = str(
        archive / "source_run" / "source_original_relax_output"
    )
    current_manifest["accepted_structure_import"] = {
        "receipt": RECEIPT,
        "sha256": receipt_sha,
        "source_structure_policy_sha256": audit["source_structure_policy_sha256"],
        "source_preflight_policy_sha256": audit["source_preflight_policy_sha256"],
    }
    core.write_json_immutable(destination / core.RUN_MANIFEST, current_manifest)
    core.write_json_immutable(destination / "config.snapshot.json", config)
    core.write_json_immutable(destination / "config_validation.json", validation)

    archived_attempt = archive / "source_run" / "slurm_attempts" / "relax" / audit["attempt_id"]
    archived_reference = archived_attempt / (
        "reference_unitcell.in" if audit["recovery"] is not None else "starting_unitcell.in"
    )
    final = destination / "relax" / "final"
    _copy_bytes_exclusive(
        final / "unitcell.in",
        (archive / "source_run" / "relax" / "final" / "unitcell.in").read_bytes(),
    )
    destination_gate = {
        **audit["gate"],
        "schema_version": 2,
        "gate_kind": "imported_accepted_structure",
        "created_utc": core.utc_now(),
        "position_shift_reference": str(archived_reference),
        "relax_output": {**audit["gate"]["relax_output"], "path": str(archived_attempt / "relax.out")},
        "pristine_output": {**audit["gate"]["pristine_output"], "path": str(archived_attempt / "pristine.out")},
        "structure_policy_sha256": core.policy_sha256(config, "structure"),
        "source_gate_sha256": anchors["source_final_gate_sha256"],
        "accepted_structure_import_receipt_sha256": receipt_sha,
    }
    core.write_json_immutable(final / "gate.json", destination_gate)
    core.write_json_immutable(
        final / "provenance.json",
        {
            "schema_version": 2,
            "kind": "imported_accepted_structure",
            "accepted_attempt": str(archived_attempt),
            "execution_manifest_sha256": core.sha256_path(archived_attempt / "execution_manifest.json"),
            "starting_structure_audit_sha256": core.sha256_path(archived_attempt / "starting_structure_audit.json"),
            "accepted_structure_import_receipt": str(destination / RECEIPT),
            "accepted_structure_import_receipt_sha256": receipt_sha,
            "source_run_manifest_sha256": anchors["source_run_manifest_sha256"],
            "source_gate_sha256": anchors["source_final_gate_sha256"],
            "source_provenance_sha256": anchors["source_final_provenance_sha256"],
            "source_unitcell_sha256": anchors["source_final_unitcell_sha256"],
            "source_structure_policy_sha256": audit["source_structure_policy_sha256"],
            "destination_structure_policy_sha256": core.policy_sha256(config, "structure"),
            "destination_preflight_policy_sha256": core.policy_sha256(config, "preflight"),
            "source_paths_archived": True,
            "external_source_paths_required": False,
        },
    )
    (destination / "preflight").mkdir()

    verified = verify_imported_acceptance(config_path, destination)
    return {
        "healthy": True,
        "stage": "prepare-accepted-structure-import",
        "run_dir": str(destination),
        "receipt_sha256": receipt_sha,
        "source_structure_policy_sha256": audit["source_structure_policy_sha256"],
        "source_preflight_policy_sha256": audit["source_preflight_policy_sha256"],
        "destination_preflight_policy_sha256": current_manifest["preflight_policy_sha256"],
        "accepted_unitcell_sha256": verified["accepted_unitcell_sha256"],
        "next": "submit a fresh current-policy preflight; do not submit relax in this imported RUN_DIR",
    }


def verify_imported_acceptance(config_path: Path, run_dir: Path) -> dict[str, Any]:
    """Re-audit a prepared import using destination-owned evidence only."""

    config_path = Path(config_path).resolve()
    config, _ = core.validate_config(config_path)
    run_dir = core.safe_run_dir(Path(run_dir))
    _require(run_dir.is_dir() and not run_dir.is_symlink(), "imported RUN_DIR is missing or symlinked")
    manifest = core.load_json(run_dir / core.RUN_MANIFEST)
    pointer = manifest.get("accepted_structure_import")
    _require(isinstance(pointer, Mapping) and pointer.get("receipt") == RECEIPT,
             "run manifest has no valid accepted-structure import pointer")
    receipt_path = _archive_regular(run_dir / RECEIPT, run_dir, "import receipt")
    _require(core.sha256_path(receipt_path) == pointer.get("sha256"),
             "accepted-structure import receipt hash mismatch")
    receipt = core.load_json(receipt_path)
    _require(receipt.get("schema_version") == 1
             and receipt.get("kind") == "imported_accepted_structure",
             "unsupported accepted-structure import receipt")
    _require(receipt.get("backend_sha256") == core.sha256_path(Path(__file__)),
             "accepted-structure import backend changed after preparation")
    structure_policy = core.policy_sha256(config, "structure")
    preflight_policy = core.policy_sha256(config, "preflight")
    _require(manifest.get("material") == core.required(config, "material.formula")
             and manifest.get("structure_policy_sha256") == structure_policy
             and manifest.get("preflight_policy_sha256") == preflight_policy,
             "imported run manifest does not match current material/policies")
    _require(receipt.get("destination_structure_policy_sha256") == structure_policy
             and receipt.get("destination_preflight_policy_sha256") == preflight_policy
             and receipt.get("destination_config_sha256") == manifest.get("config_sha256"),
             "import receipt does not match current config/policies")
    _require(pointer.get("source_structure_policy_sha256") == structure_policy
             and receipt.get("source_structure_policy_sha256") == structure_policy,
             "import source structure policy mismatch")
    _require(receipt.get("source_paths_archived") is True
             and receipt.get("external_source_paths_required") is False,
             "import receipt permits an external source dependency")

    archive = run_dir / ARCHIVE
    source_files = receipt.get("source_files")
    workflow_files = receipt.get("workflow_files")
    _require(isinstance(source_files, Mapping) and isinstance(workflow_files, Mapping),
             "import receipt has no archived-file inventories")
    for collection, label in ((source_files, "source"), (workflow_files, "workflow")):
        for relative, digest in collection.items():
            _digest(digest, f"archived {label} SHA256")
            rel = Path(str(relative))
            _require(not rel.is_absolute() and ".." not in rel.parts and rel.parts,
                     f"invalid archived {label} path")
            path = _archive_regular(archive / rel, run_dir, f"archived {label} evidence")
            _require(core.sha256_path(path) == digest,
                     f"archived {label} evidence hash mismatch: {relative}")

    source_run = archive / "source_run"
    source_manifest = core.load_json(source_run / core.RUN_MANIFEST)
    attempt_id = receipt.get("source_attempt_id")
    _require(isinstance(attempt_id, str) and ATTEMPT_ID_RE.fullmatch(attempt_id) is not None,
             "import receipt has invalid source attempt ID")
    expected_source_names = set(ROOT_FILES)
    expected_source_names.update(f"relax/final/{name}" for name in FINAL_FILES)
    expected_source_names.update(f"slurm_attempts/relax/{attempt_id}/{name}" for name in ATTEMPT_FILES)
    if source_manifest.get("relax_recovery") is not None:
        expected_source_names.update(
            f"slurm_attempts/relax/{attempt_id}/{name}"
            for name in RECOVERY_ATTEMPT_FILES
        )
        expected_source_names.update(RECOVERY_ROOT_FILES)
        expected_source_names.update(f"recovery_source/{name}" for name in RECOVERY_SOURCE_FILES)
    actual_source_names = {
        str(Path(name).relative_to("source_run"))
        for name in source_files
        if Path(name).parts and Path(name).parts[0] == "source_run"
    }
    _require(actual_source_names == expected_source_names,
             "accepted-structure source inventory differs from the fixed allowlist")
    expected_pseudos = {f"pseudopotentials/{name}"
                        for name in core.required(config, "pseudopotentials.files").values()}
    _require({name for name in source_files if str(name).startswith("pseudopotentials/")}
             == expected_pseudos,
             "archived pseudopotential inventory differs from current policy")
    expected_workflow = {
        f"workflow/accepted_run/{name}"
        for name in source_manifest.get("workflow_files", {})
    }
    if source_manifest.get("relax_recovery") is not None:
        expected_workflow.add(
            "workflow/recovery_backend/thermo_candidates/scripts/phono3py_campaign/relax_recovery.py"
        )
        failed_manifest = core.load_json(
            source_run / "recovery_source/source_run_manifest.json"
        )
        expected_workflow.update(
            f"workflow/recovery_source_run/{name}"
            for name in failed_manifest.get("workflow_files", {})
        )
    _require(set(workflow_files) == expected_workflow,
             "archived workflow inventory differs from source manifest")

    anchors = receipt.get("anchors")
    _require(isinstance(anchors, Mapping), "import receipt has no source anchors")
    anchored = {
        "source_run_manifest_sha256": source_run / "run_manifest.json",
        "source_final_gate_sha256": source_run / "relax/final/gate.json",
        "source_final_provenance_sha256": source_run / "relax/final/provenance.json",
        "source_final_unitcell_sha256": source_run / "relax/final/unitcell.in",
    }
    for label, path in anchored.items():
        _require(core.sha256_path(path) == anchors.get(label), f"archived {label} mismatch")

    identity_run = Path(str(receipt.get("source_run_identity", ""))).resolve()
    audit = _audit_source_acceptance(config, source_run, identity_run)
    _require(audit["attempt_id"] == attempt_id
             and audit["identity_attempt"] == receipt.get("source_attempt_identity")
             and audit["audit_sha256"] == receipt.get("source_acceptance_audit_sha256"),
             "imported source acceptance replay differs from receipt")

    for species, item in audit["pseudopotentials"].items():
        archived = archive / "pseudopotentials" / item["filename"]
        _require(core.sha256_path(archived) == item["sha256"],
                 f"archived pseudopotential differs from accepted run: {species}")
    _require(Path(str(manifest.get("source_qe_input", ""))).resolve()
             == (source_run / "source_qe_input").resolve()
             and Path(str(manifest.get("source_relax_output", ""))).resolve()
             == (source_run / "source_original_relax_output").resolve(),
             "fresh manifest retains an external source path")
    _require(manifest.get("source_qe_sha256") == core.sha256_path(source_run / "source_qe_input")
             and manifest.get("source_relax_sha256") == core.sha256_path(source_run / "source_original_relax_output"),
             "fresh manifest archived source hash mismatch")

    final = run_dir / "relax" / "final"
    unitcell = _archive_regular(final / "unitcell.in", run_dir, "imported final unitcell")
    gate = core.load_json(_archive_regular(final / "gate.json", run_dir, "imported final gate"))
    provenance = core.load_json(_archive_regular(final / "provenance.json", run_dir, "imported final provenance"))
    archived_attempt = source_run / "slurm_attempts" / "relax" / attempt_id
    _require(gate.get("pass") is True and gate.get("gate_kind") == "imported_accepted_structure"
             and gate.get("final_unitcell_sha256") == core.sha256_path(unitcell)
             and gate.get("accepted_structure_import_receipt_sha256") == core.sha256_path(receipt_path),
             "destination imported gate is invalid")
    for key in ("pass", "checks", "force_acceptance_ry_bohr",
                "hard_stop_force_ry_bohr", "hard_stop_exceeded",
                "per_atom_position_shift_angstrom", "max_position_shift_angstrom",
                "spacegroup_scan", "final_unitcell_sha256"):
        _require(gate.get(key) == audit["replay"][key],
                 f"destination imported gate replay mismatch: {key}")
    _require(_health_without_path(gate.get("relax_output", {}))
             == audit["replay"]["relax_output"]
             and _health_without_path(gate.get("pristine_output", {}))
             == audit["replay"]["pristine_output"],
             "destination imported gate output-health replay mismatch")
    expected_reference = archived_attempt / (
        "reference_unitcell.in" if audit["recovery"] is not None
        else "starting_unitcell.in"
    )
    _require(Path(str(gate.get("position_shift_reference", ""))).resolve()
             == expected_reference.resolve(),
             "destination imported gate reference path mismatch")
    _require(provenance.get("kind") == "imported_accepted_structure"
             and Path(str(provenance.get("accepted_attempt", ""))).resolve() == archived_attempt.resolve()
             and provenance.get("execution_manifest_sha256") == core.sha256_path(archived_attempt / "execution_manifest.json")
             and provenance.get("starting_structure_audit_sha256") == core.sha256_path(archived_attempt / "starting_structure_audit.json")
             and provenance.get("accepted_structure_import_receipt_sha256") == core.sha256_path(receipt_path)
             and provenance.get("source_run_manifest_sha256") == anchors.get("source_run_manifest_sha256")
             and provenance.get("source_gate_sha256") == anchors.get("source_final_gate_sha256")
             and provenance.get("source_provenance_sha256") == anchors.get("source_final_provenance_sha256")
             and provenance.get("source_unitcell_sha256") == anchors.get("source_final_unitcell_sha256")
             and provenance.get("source_structure_policy_sha256") == structure_policy
             and provenance.get("destination_structure_policy_sha256") == structure_policy
             and provenance.get("destination_preflight_policy_sha256") == preflight_policy
             and provenance.get("source_paths_archived") is True
             and provenance.get("external_source_paths_required") is False,
             "destination imported provenance is invalid")
    _require(unitcell.read_bytes() == (source_run / "relax/final/unitcell.in").read_bytes(),
             "destination unitcell differs from archived accepted structure")
    _require(not (run_dir / "slurm_attempts" / "relax").exists(),
             "imported RUN_DIR must not claim a locally executed relax attempt")
    _require(not any((run_dir / name).exists() for name in ("tmp-relax", "tmp-pristine")),
             "imported RUN_DIR contains forbidden QE scratch")

    return {
        "healthy": True,
        "kind": "imported_accepted_structure",
        "run_dir": str(run_dir),
        "receipt_sha256": core.sha256_path(receipt_path),
        "accepted_unitcell_sha256": core.sha256_path(unitcell),
        "structure_policy_sha256": structure_policy,
        "preflight_policy_sha256": preflight_policy,
        "source_preflight_policy_sha256": receipt.get("source_preflight_policy_sha256"),
        "external_source_paths_required": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--source-run-dir", required=True, type=Path)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--source-gate-sha256", required=True)
    parser.add_argument("--source-provenance-sha256", required=True)
    parser.add_argument("--source-unitcell-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_import(
            args.config,
            args.run_dir,
            source_run_dir=args.source_run_dir,
            source_manifest_sha256=args.source_manifest_sha256,
            source_gate_sha256=args.source_gate_sha256,
            source_provenance_sha256=args.source_provenance_sha256,
            source_unitcell_sha256=args.source_unitcell_sha256,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, core.CampaignError) as exc:
        print(json.dumps({"healthy": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

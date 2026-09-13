#!/usr/bin/env python3
"""Dedicated, fail-closed Rb2Cu2SnS4 FIRE recovery lineage.

This module intentionally does not call the BFGS recovery/finalizer.  QE 7.3.1
``PW/src/dynamics_module.f90`` prints the two required normal FIRE terminal
records, ``FIRE: convergence achieved in`` and ``End of FIRE minimization``;
``JOB DONE`` alone is deliberately insufficient here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

import campaign as core
from qe_input import build_fixed_cell_relax_input, parse_qe_input

POLICY = "reviewed_fire_recovery"
LINEAGE = "fire_lineage_receipt.json"
REQUIRED_SEED_FILES = (
    "polish_reference.in",
    "lineage_source/one_reset_attempt/reference_unitcell.in",
    "lineage_source/one_reset_run/recovery_reference.in",
)
STANDARDIZATION_AUDIT = "lineage_source/one_reset_attempt/starting_structure_audit.json"
FIRE_MARKERS = ("FIRE: convergence achieved in", "End of FIRE minimization")
_FORBIDDEN_BFGS = {"bfgs_ndim", "trust_radius_ini", "trust_radius_min", "trust_radius_max"}
_TRUSTED_HISTORICAL_CONFIG_SHA256 = "1e6f09fd5cbd26308143ed2f095bbfcadb76ff2d1b114b6b13c3edb5627a33a1"
_TRUSTED_HISTORICAL_CONFIG_CANONICAL_SHA256 = "655cfa0efd216faf5a0ce35e73cf271d32a9fb64d3aac4807a965d71f9921bad"

# Code-owned trust root for the one real Rb lineage already replayed on Nibi.
# A mutable campaign file may not redefine which historical run or evidence
# digests are allowed to seed this separate recovery hypothesis.
TRUSTED_OLD_LINEAGE: dict[str, str] = {
    "run_dir": "/scratch/yuhansun/phono3py-runs/20260911-continuation-cf0b1d1/Rb2Cu2SnS4",
    "reference_sha256": "b2f919f7af04a0fd93400e2e5cd021bb489947e245e3d834694167bf2ded714f",
    "standardization_audit_sha256": "cf78d8a24cb8e0d8547321b6e7cfd26677cd3872a52797842f602fcf621ba1ad",
    "failed_relax_output_sha256": "f486cbab5b743ab28df1a492bd32b84b283a9f67e7ffdb9418764a9e238c2de2",
    "failed_relax_context_sha256": "1a9559670e04d43e0555b966698e34e93918a302b867e1711900bb80f4eab8d7",
    "later_collector_collection_sha256": "d5b4e87c8c69dddb5f1ba484d0a6d2f2dc618be6ec55f8d3e7b8d4611f4d2c83",
    "later_collector_context_sha256": "fa4690608472e086c8d76a5aa249c312505b8aa01fca3a80a7d1fe2bbd645ed6",
    "diagnostic_primary_job_id": "21732222",
    "diagnostic_collector_job_id": "21732223",
    "failed_relax_job_id": "21848175",
    "failed_relax_collector_job_id": "21848176",
}
TRUSTED_FAILED_RELAX_OUTPUT = (
    "slurm_attempts/relax/20260913T133538Z-relax-2d3fd832/relax.out"
)
TRUSTED_LATER_COLLECTION = (
    "slurm_attempts/collect/20260913T133539Z-collect-6d5ba984/collection.json"
)


def _archived_source_relative(name: str) -> str:
    """Map old-lineage evidence into one, and only one, source archive root."""
    prefix = "lineage_source/"
    return name[len(prefix):] if name.startswith(prefix) else name


def _strict(root: Path, relative: str) -> Path:
    path = root / relative
    current = root
    for part in Path(relative).parts:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise core.CampaignError(f"FIRE lineage path contains a symlink: {current}")
        except FileNotFoundError as exc:
            raise core.CampaignError(f"FIRE lineage source is missing: {current}") from exc
    if not path.is_file():
        raise core.CampaignError(f"FIRE lineage source is not a regular file: {path}")
    return path


def _strict_dir(root: Path, relative: str) -> Path:
    """Return a directory only when every component is a real directory."""
    try:
        root_mode = os.lstat(root).st_mode
    except FileNotFoundError as exc:
        raise core.CampaignError(f"FIRE lineage root is missing: {root}") from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise core.CampaignError(f"FIRE lineage root is unsafe: {root}")
    path = root / relative
    current = root
    for part in Path(relative).parts:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as exc:
            raise core.CampaignError(f"FIRE lineage directory is missing: {current}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise core.CampaignError(f"FIRE lineage directory is unsafe: {current}")
    return path


def _strict_regular(root: Path, relative: str) -> Path:
    path = _strict(root, relative)
    if stat.S_ISLNK(os.lstat(path).st_mode) or not stat.S_ISREG(os.lstat(path).st_mode):
        raise core.CampaignError(f"FIRE lineage receipt/source is unsafe: {path}")
    return path


def _write_json(path: Path, value: object) -> None:
    core.write_json_immutable(path, value)


def _policy(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get(POLICY)
    if not isinstance(value, Mapping):
        raise core.CampaignError("campaign has no reviewed FIRE recovery policy")
    return value


def validate_fire_policy(config: Mapping[str, Any]) -> None:
    """Validate the deliberately narrow policy without weakening old BFGS checks."""
    policy = _policy(config)
    expected_top = {"status", "purpose", "seed_contract", "trusted_old_lineage", "settings", "pilot", "full", "resources", "structure_gate"}
    if set(policy) != expected_top:
        raise core.CampaignError("FIRE policy key set is incomplete or contains an unreviewed field")
    if policy.get("status") != "reviewed_planned_hypothesis_not_validated":
        raise core.CampaignError("FIRE recovery must remain a reviewed, unvalidated hypothesis")
    if policy.get("purpose") != "A separate one-shot FIRE recovery lineage after the terminal BFGS lineage. It is not an extension, retry, or acceptance of the BFGS final state.":
        raise core.CampaignError("FIRE recovery purpose/value drift")
    for stage, expected_steps, expected_seconds in (("pilot", 8, 6300), ("full", 100, 39600)):
        spec = policy.get(stage)
        if not isinstance(spec, Mapping):
            raise core.CampaignError(f"FIRE {stage} policy is missing")
        if spec.get("nstep") != expected_steps or spec.get("max_seconds") != expected_seconds:
            raise core.CampaignError(f"FIRE {stage} nstep/max_seconds policy drift")
        if spec.get("calculation") != "relax" or spec.get("ion_dynamics") != "fire":
            raise core.CampaignError(f"FIRE {stage} must be a fixed-cell ion_dynamics='fire' relax")
        if any(key in spec for key in _FORBIDDEN_BFGS):
            raise core.CampaignError(f"FIRE {stage} may not contain BFGS trust parameters")
    if set(policy["pilot"]) != {"calculation", "ion_dynamics", "nstep", "max_seconds", "fresh_scratch_required", "final_state_is_accepted", "may_seed_full", "release_conditions"}:
        raise core.CampaignError("FIRE pilot schema drift")
    if set(policy["full"]) != {"calculation", "ion_dynamics", "nstep", "max_seconds", "fresh_scratch_required", "seed", "normal_convergence_markers", "JOB_DONE_alone_is_invalid", "timeout_nstep_or_failure_is_terminal_for_lineage"}:
        raise core.CampaignError("FIRE full schema drift")
    settings = policy.get("settings")
    if not isinstance(settings, Mapping):
        raise core.CampaignError("FIRE settings are missing")
    expected = {
        "ecutwfc_ry": 100, "ecutrho_ry": 800, "kmesh": [4, 7, 7],
        "occupations": "fixed", "conv_thr_ry": 1e-10, "electron_maxstep": 300,
        "mixing_beta": 0.3, "scf_must_converge": True, "etot_conv_thr_ry": 1e-8,
        "forc_conv_thr_ry_bohr": 1e-5, "dt_au": 10, "fire_alpha_init": 0.2,
        "fire_falpha": 0.99, "fire_nmin": 5, "fire_f_inc": 1.1,
        "fire_f_dec": 0.5, "fire_dtmax": 2.0, "pot_extrapolation": "atomic",
        "wfc_extrapolation": "none",
    }
    if set(settings) != set(expected):
        raise core.CampaignError("FIRE settings schema drift")
    for key, value in expected.items():
        if settings.get(key) != value:
            raise core.CampaignError(f"FIRE settings drift: {key}")
    if any(key in settings for key in _FORBIDDEN_BFGS):
        raise core.CampaignError("FIRE settings may not contain BFGS trust parameters")
    resources = policy.get("resources")
    if not isinstance(resources, Mapping) or resources.get("partition") != "cpubase_bycore_b2":
        raise core.CampaignError("FIRE resources must use cpubase_bycore_b2")
    if resources.get("ntasks") != 32 or resources.get("mem_per_cpu_mb") != 2000:
        raise core.CampaignError("FIRE resources must request 32 ranks and 2GB/rank")
    if resources.get("pilot_walltime_hours") != 2 or resources.get("full_walltime_hours") != 12:
        raise core.CampaignError("FIRE walltime policy drift")
    if resources.get("full_core_hours") != 384:
        raise core.CampaignError("FIRE full allocation must be 384 core-hours")
    if set(resources) != {"partition", "ntasks", "mem_per_cpu_mb", "pilot_walltime_hours", "full_walltime_hours", "full_core_hours"}:
        raise core.CampaignError("FIRE resources schema drift")
    seed = policy.get("seed_contract")
    if not isinstance(seed, Mapping) or set(seed) != {"required_source", "forbidden_sources", "cross_checks", "require_byte_identical", "required_atom_count", "required_spacegroup", "seed_is_accepted_structure"}:
        raise core.CampaignError("FIRE seed-contract schema drift")
    if dict(seed) != {
        "required_source": "old_real_lineage/polish_reference.in",
        "forbidden_sources": ["polish_seed.in", "21848175_failed_terminal_state"],
        "cross_checks": ["lineage_source/one_reset_attempt/reference_unitcell.in", "lineage_source/one_reset_run/recovery_reference.in"],
        "require_byte_identical": True, "required_atom_count": 18,
        "required_spacegroup": "Ibam No.72 at 1e-6 angstrom",
        "seed_is_accepted_structure": False,
    }:
        raise core.CampaignError("FIRE seed-contract value drift")
    binding = policy.get("trusted_old_lineage")
    if not isinstance(binding, Mapping) or set(binding) != {"run_dir", "reference_sha256", "standardization_audit_sha256", "failed_relax_output_sha256", "failed_relax_context_sha256", "later_collector_collection_sha256", "later_collector_context_sha256", "diagnostic_primary_job_id", "diagnostic_collector_job_id", "failed_relax_job_id", "failed_relax_collector_job_id"}:
        raise core.CampaignError("FIRE trusted-old-lineage schema drift")
    if dict(binding) != TRUSTED_OLD_LINEAGE:
        raise core.CampaignError("FIRE trusted-old-lineage trust root drift")
    expected_pilot_release = ["all_scf_converged", "no_fatal_nan_or_oom", "cell_and_atom_order_unchanged", "final_max_component_below_initial", "final_max_component_le_1e-4_Ry_per_bohr", "cumulative_shift_le_0p02A", "Ibam_at_1e-6A"]
    if policy["pilot"].get("fresh_scratch_required") is not True or policy["pilot"].get("final_state_is_accepted") is not False or policy["pilot"].get("may_seed_full") is not False or policy["pilot"].get("release_conditions") != expected_pilot_release:
        raise core.CampaignError("FIRE pilot release contract drift")
    if policy["full"].get("fresh_scratch_required") is not True or policy["full"].get("seed") != "same_frozen_fire_seed_not_pilot_terminal_state" or policy["full"].get("normal_convergence_markers") != list(FIRE_MARKERS) or policy["full"].get("JOB_DONE_alone_is_invalid") is not True or policy["full"].get("timeout_nstep_or_failure_is_terminal_for_lineage") is not True:
        raise core.CampaignError("FIRE full release contract drift")
    gate = policy.get("structure_gate")
    if not isinstance(gate, Mapping) or set(gate) != {"fire_force_threshold_ry_bohr", "fire_and_pristine_max_component_ry_bohr", "hard_stop_max_component_ry_bohr", "max_shift_angstrom", "strict_spacegroup", "pristine", "finalizer", "preflight_release_requires", "preflight_release_scope"}:
        raise core.CampaignError("FIRE structure-gate schema drift")
    if gate.get("fire_force_threshold_ry_bohr") != 1e-5 or gate.get("fire_and_pristine_max_component_ry_bohr") != 5e-5 or gate.get("hard_stop_max_component_ry_bohr") != 1e-4 or gate.get("max_shift_angstrom") != .02 or gate.get("strict_spacegroup") != "Ibam No.72 at 1e-6 angstrom" or gate.get("pristine") != {"fresh_scratch": True, "nosym": True, "noinv": True, "startingpot": "atomic", "startingwfc": "atomic+random"} or gate.get("finalizer") != {"structure_accepted": True, "preflight_unlocked": False} or gate.get("preflight_release_requires") != "independent_read_only_replay_and_review" or gate.get("preflight_release_scope") != "count_only_only_no_automatic_submission_force_or_production_unlock":
        raise core.CampaignError("FIRE structure-gate value drift")
    if config.get("resource_budget", {}).get("approved_total_core_hours_per_material") is not None:
        raise core.CampaignError("FIRE recovery cannot lift the null production budget")
    if config.get("production", {}).get("selection_required") is not True:
        raise core.CampaignError("FIRE recovery cannot unlock production")


def _fire_params(settings: Mapping[str, Any]) -> dict[str, object]:
    return {
        "dt": settings["dt_au"], "fire_alpha_init": settings["fire_alpha_init"],
        "fire_falpha": settings["fire_falpha"], "fire_nmin": settings["fire_nmin"],
        "fire_f_inc": settings["fire_f_inc"], "fire_f_dec": settings["fire_f_dec"],
        "fire_dtmax": settings["fire_dtmax"], "pot_extrapolation": settings["pot_extrapolation"],
        "wfc_extrapolation": settings["wfc_extrapolation"],
    }


def _workflow_hashes() -> dict[str, str]:
    base = Path(__file__).resolve().parent
    names = ("fire_recovery.py", "polish_recovery.py", "campaign.py", "qe_input.py", "qe_output.py", "submit.py", "slurm/fire_pilot.sbatch", "slurm/fire_full.sbatch", "slurm/collect.sbatch", "slurm/cluster.env")
    return {name: core.sha256_path(base / name) for name in names}


def _current_config_binding(config_path: Path, config: Mapping[str, Any], validation: Mapping[str, Any]) -> dict[str, str]:
    config_path = config_path.resolve(strict=True)
    return {
        "config_path_sha256": core.sha256_path(config_path),
        "config_canonical_sha256": core.canonical_sha256(config),
        "validation_config_sha256": str(validation["config_sha256"]),
    }


def _historical_config_view(config: Mapping[str, Any]) -> Mapping[str, Any]:
    historical = dict(config)
    historical.pop(POLICY, None)
    if core.canonical_sha256(historical) != _TRUSTED_HISTORICAL_CONFIG_CANONICAL_SHA256:
        raise core.CampaignError("current config minus FIRE policy is not the exact trusted historical mapping")
    return historical


def _replay_trusted_old_lineage(config: Mapping[str, Any], config_path: Path, binding: Mapping[str, Any]) -> tuple[Path, Mapping[str, Any], Path, Path]:
    """Replay the old diagnostic/collector chain, not a caller-created lookalike."""
    old = Path(str(binding["run_dir"]))
    if os.path.lexists(old) and stat.S_ISLNK(os.lstat(old).st_mode):
        raise core.CampaignError("trusted old FIRE lineage root may not be a symlink")
    old = core.safe_run_dir(old)
    if str(old) != binding["run_dir"]:
        raise core.CampaignError("trusted old FIRE lineage path normalization drift")
    from polish_recovery import _audit_final_diagnostic
    gate = _audit_final_diagnostic(
        _historical_config_view(config), config_path, old,
        old / "diagnostic/final/gate.json",
        expected_config_sha256=_TRUSTED_HISTORICAL_CONFIG_SHA256,
    )
    chain = gate.get("submission_chain")
    if not isinstance(chain, Mapping) or chain.get("primary_job_id") != binding["diagnostic_primary_job_id"] or chain.get("collector_job_id") != binding["diagnostic_collector_job_id"]:
        raise core.CampaignError("trusted old FIRE diagnostic/collector job identities differ from anchors")
    failed = _strict_regular(old, TRUSTED_FAILED_RELAX_OUTPUT)
    collection = _strict_regular(old, TRUSTED_LATER_COLLECTION)
    if core.sha256_path(failed) != binding["failed_relax_output_sha256"]:
        raise core.CampaignError("trusted failed BFGS output hash differs from code-owned path")
    if core.sha256_path(collection) != binding["later_collector_collection_sha256"]:
        raise core.CampaignError("trusted later collector hash differs from code-owned path")
    failed_context_path = _strict_regular(old, str((failed.parent / "context.tsv").relative_to(old)))
    collector_context_path = _strict_regular(old, str((collection.parent / "context.tsv").relative_to(old)))
    if core.sha256_path(failed_context_path) != binding["failed_relax_context_sha256"]:
        raise core.CampaignError("trusted failed BFGS context hash differs from code-owned path")
    if core.sha256_path(collector_context_path) != binding["later_collector_context_sha256"]:
        raise core.CampaignError("trusted later collector context hash differs from code-owned path")
    failed_context = _context_fields(failed_context_path)
    collector_context = _context_fields(collector_context_path)
    # The whole context byte stream is pinned above.  Check the identities that
    # relate the two attempts explicitly, while retaining the additional real
    # Nibi resource/workflow fields carried by these historical context files.
    if failed_context.get("stage") != "relax" or failed_context.get("attempt_id") != "20260913T133538Z-relax-2d3fd832" or failed_context.get("slurm_job_id") != binding["failed_relax_job_id"] or failed_context.get("config_sha256") != _TRUSTED_HISTORICAL_CONFIG_SHA256 or failed_context.get("run_dir") != str(old) or failed_context.get("git_commit") != "":
        raise core.CampaignError("trusted failed BFGS output context/job identity drift")
    if collector_context.get("stage") != "collect" or collector_context.get("attempt_id") != "20260913T133539Z-collect-6d5ba984" or collector_context.get("slurm_job_id") != binding["failed_relax_collector_job_id"] or collector_context.get("config_sha256") != _TRUSTED_HISTORICAL_CONFIG_SHA256 or collector_context.get("primary_stage") != "relax" or collector_context.get("primary_attempt_id") != "20260913T133538Z-relax-2d3fd832" or collector_context.get("primary_job_id") != binding["failed_relax_job_id"] or collector_context.get("run_dir") != str(old) or collector_context.get("git_commit") != "":
        raise core.CampaignError("trusted later collector context/job identity drift")
    return old, gate, failed, collection


def _input(config: Mapping[str, Any], seed: str, pseudo_dir: Path, stage: str) -> str:
    settings = _policy(config)["settings"]
    assert isinstance(settings, Mapping)
    text = build_fixed_cell_relax_input(
        seed, outdir=f"./tmp-fire-{stage}", prefix=f"Rb2Cu2SnS4_fire_{stage}",
        pseudo_dir=str(pseudo_dir), conv_thr=float(settings["conv_thr_ry"]),
        forc_conv_thr=float(settings["forc_conv_thr_ry_bohr"]), ion_dynamics="fire",
        ecutwfc=float(settings["ecutwfc_ry"]), ecutrho=float(settings["ecutrho_ry"]),
        kmesh=settings["kmesh"], kshift=(0, 0, 0),
        etot_conv_thr=float(settings["etot_conv_thr_ry"]), electron_maxstep=int(settings["electron_maxstep"]),
        mixing_beta=float(settings["mixing_beta"]), fire_parameters=_fire_params(settings),
    )
    from qe_input import _set_namelist_values
    spec = _policy(config)[stage]
    assert isinstance(spec, Mapping)
    text = _set_namelist_values(text, "CONTROL", {"nstep": str(spec["nstep"]), "max_seconds": str(spec["max_seconds"]), "restart_mode": "'from_scratch'"})
    text = _set_namelist_values(text, "ELECTRONS", {"startingpot": "'atomic'", "startingwfc": "'atomic+random'", "scf_must_converge": ".true."})
    text = _set_namelist_values(text, "SYSTEM", {"occupations": "'fixed'"})
    if any(re.search(rf"(?im)^\s*{name}\s*=", text) for name in _FORBIDDEN_BFGS):
        raise core.CampaignError("generated FIRE input contains forbidden BFGS trust controls")
    return text


def _context_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "\t" not in line:
            raise core.CampaignError(f"FIRE historical context is malformed: {path}")
        key, value = line.split("\t", 1)
        if not key or key in fields:
            raise core.CampaignError(f"FIRE historical context has duplicate/empty key: {path}")
        fields[key] = value
    return fields


def _reject_existing_ancestor_symlinks(raw_path: Path, label: str) -> None:
    """Inspect lexical existing components before any resolve/safe_run_dir call."""
    lexical = Path(raw_path)
    # ``safe_run_dir`` expands ``~`` later.  Do it here too, before any
    # normalization, so an alias in $HOME cannot bypass this lexical walk.
    candidate = lexical.expanduser()
    if ".." in lexical.parts or ".." in candidate.parts:
        raise core.CampaignError(f"FIRE {label} may not contain an unresolved '..' path component")
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise core.CampaignError(f"FIRE {label} has a symlinked existing path component: {current}")
        if current != candidate and not stat.S_ISDIR(mode):
            raise core.CampaignError(f"FIRE {label} has a non-directory ancestor: {current}")


def prepare_lineage(config_path: Path, run_dir: Path, old_lineage_run: Path) -> dict[str, Any]:
    config_path = config_path.resolve(strict=True)
    config, validation = core.validate_config(config_path)
    validate_fire_policy(config)
    _reject_existing_ancestor_symlinks(run_dir, "RUN_DIR")
    _reject_existing_ancestor_symlinks(old_lineage_run, "old-lineage root")
    if os.path.lexists(run_dir) or os.path.lexists(old_lineage_run) and stat.S_ISLNK(os.lstat(old_lineage_run).st_mode):
        raise core.CampaignError("FIRE RUN_DIR must be absent and old-lineage root may not be a symlink")
    run_dir = core.safe_run_dir(run_dir)
    old_lineage_run = core.safe_run_dir(old_lineage_run)
    if run_dir.exists():
        raise core.CampaignError("FIRE RUN_DIR must be new, non-nested, and never previously existing")
    if run_dir in old_lineage_run.parents or old_lineage_run in run_dir.parents:
        raise core.CampaignError("FIRE RUN_DIR must not nest the old lineage")
    binding = _policy(config)["trusted_old_lineage"]
    assert isinstance(binding, Mapping)
    if str(old_lineage_run) != binding["run_dir"]:
        raise core.CampaignError("FIRE prepare must use the predeclared real old lineage only")
    # Reuse the reviewed BFGS replay machinery before accepting even a seed.
    # The diagnostic records were emitted under the exact HEAD configuration,
    # while the current mapping adds only this FIRE policy.  The shared helper
    # validates that view, dispatch/collector identities, and later evidence.
    replayed_old, _, failed_output, later_collection = _replay_trusted_old_lineage(config, config_path, binding)
    if replayed_old != old_lineage_run:
        raise core.CampaignError("trusted old lineage replay root differs from requested root")
    seed_files = {name: _strict(old_lineage_run, name) for name in REQUIRED_SEED_FILES}
    audit_path = _strict(old_lineage_run, STANDARDIZATION_AUDIT)
    audit = core.load_json(audit_path)
    if audit.get("pass") is not True or audit.get("standardized") is not True or audit.get("strict_spacegroup_match") is not True or audit.get("reference_cell_match") is not True:
        raise core.CampaignError("FIRE seed lacks a passing strict original Ibam standardization audit")
    payloads = {name: path.read_bytes() for name, path in seed_files.items()}
    if any(hashlib.sha256(data).hexdigest() != binding["reference_sha256"] for data in payloads.values()):
        raise core.CampaignError("FIRE reference hashes differ from the predeclared real lineage")
    if core.sha256_path(audit_path) != binding["standardization_audit_sha256"]:
        raise core.CampaignError("FIRE standardization audit hash differs from the predeclared lineage")
    if len(set(payloads.values())) != 1:
        raise core.CampaignError("FIRE seed references differ; polish_seed/failed final state are forbidden")
    seed = payloads["polish_reference.in"].decode()
    parsed = parse_qe_input(seed)
    nat = int(core.required(config, "material.unitcell_atoms"))
    if parsed.nat != nat or len(parsed.atomic_positions) != nat:
        raise core.CampaignError("FIRE seed does not preserve the 18-atom audited unit cell")
    # Byte identity to the archived standardization record is stronger than a
    # proximity test and excludes the BFGS failed terminal geometry.
    if "polish_seed.in" in {path.name for path in old_lineage_run.rglob("*") if path.is_file()}:
        old_seed = old_lineage_run / "polish_seed.in"
        if old_seed.is_file() and old_seed.read_bytes() == payloads["polish_reference.in"]:
            raise core.CampaignError("FIRE seed unexpectedly equals prohibited polish_seed.in")
    run_dir.mkdir(parents=True)
    for name, data in payloads.items():
        destination = run_dir / "lineage_source" / _archived_source_relative(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    audit_destination = run_dir / "lineage_source" / _archived_source_relative(STANDARDIZATION_AUDIT)
    audit_destination.parent.mkdir(parents=True, exist_ok=True)
    audit_destination.write_bytes(audit_path.read_bytes())
    core.write_immutable(run_dir / "fire_seed.in", seed)
    receipt = {
        "schema_version": 2, "kind": "reviewed_fire_recovery_from_audited_polish_reference_only",
        "material": config["material"]["formula"], "structure_accepted": False,
        "preflight_unlocked": False, "seed_path": "fire_seed.in",
        "seed_sha256": core.sha256_path(run_dir / "fire_seed.in"),
        "source_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        "original_standardization_audit_sha256": core.sha256_path(audit_destination),
        "current_config_binding": _current_config_binding(config_path, config, validation),
        "trusted_old_lineage": dict(binding),
        "trusted_failed_output": str(failed_output.relative_to(old_lineage_run)),
        "trusted_later_collection": str(later_collection.relative_to(old_lineage_run)),
        "atom_count": nat, "atom_labels": [item.label for item in parsed.atomic_positions],
        "fixed_cell": [list(row) for row in parsed.cell_parameters],
        "spacegroup_requirement": "Ibam No.72 at 1e-6 angstrom; replayed in final gate",
        "policy_sha256": core.canonical_sha256(_policy(config)),
        "workflow_sha256": _workflow_hashes(),
    }
    _write_json(run_dir / LINEAGE, receipt)
    for name in ("slurm_attempts/fire-pilot", "slurm_attempts/fire-full", "slurm_attempts/fire-pristine", "submissions/fire-pilot", "submissions/fire-full"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    return {"healthy": True, "run_dir": str(run_dir), "seed_sha256": receipt["seed_sha256"], "structure_accepted": False, "preflight_unlocked": False}


def verify_fire_submission_ready(config_path: Path, run_dir: Path, stage: str) -> dict[str, Any]:
    """Read-only submission gate; never prepares or consumes an attempt."""
    if stage not in {"fire-pilot", "fire-full"}:
        raise core.CampaignError("invalid FIRE submission stage")
    config_path = config_path.resolve(strict=True)
    config, validation = core.validate_config(config_path); validate_fire_policy(config)
    if stage == "fire-full":
        raise core.CampaignError(
            "FIRE full planning is locked until a trusted pilot collector and independent replay are implemented"
        )
    if os.path.lexists(run_dir) and stat.S_ISLNK(os.lstat(run_dir).st_mode):
        raise core.CampaignError("FIRE RUN_DIR may not be a symlink")
    run_dir = core.safe_run_dir(run_dir)
    if not run_dir.is_dir() or stat.S_ISLNK(os.lstat(run_dir).st_mode):
        raise core.CampaignError("FIRE RUN_DIR is unsafe")
    receipt_path = _strict_regular(run_dir, LINEAGE)
    receipt = core.load_json(receipt_path)
    receipt_fields = {
        "schema_version", "kind", "material", "structure_accepted", "preflight_unlocked",
        "seed_path", "seed_sha256", "source_hashes", "original_standardization_audit_sha256",
        "current_config_binding", "trusted_old_lineage", "trusted_failed_output",
        "trusted_later_collection", "atom_count", "atom_labels", "fixed_cell",
        "spacegroup_requirement", "policy_sha256", "workflow_sha256",
    }
    if set(receipt) != receipt_fields or receipt.get("schema_version") != 2 or receipt.get("kind") != "reviewed_fire_recovery_from_audited_polish_reference_only":
        raise core.CampaignError("FIRE lineage receipt schema is incomplete or drifted")
    if receipt.get("structure_accepted") is not False or receipt.get("preflight_unlocked") is not False:
        raise core.CampaignError("FIRE plan receipt may not claim structure acceptance or release")
    if receipt.get("material") != config["material"]["formula"] or receipt.get("current_config_binding") != _current_config_binding(config_path, config, validation):
        raise core.CampaignError("FIRE lineage receipt current config binding drift")
    binding = _policy(config)["trusted_old_lineage"]
    if receipt.get("trusted_old_lineage") != dict(binding):
        raise core.CampaignError("FIRE lineage receipt trusted historical anchor drift")
    replayed_old, _, failed_output, later_collection = _replay_trusted_old_lineage(config, config_path, binding)
    if receipt.get("trusted_failed_output") != str(failed_output.relative_to(replayed_old)) or receipt.get("trusted_later_collection") != str(later_collection.relative_to(replayed_old)):
        raise core.CampaignError("FIRE lineage receipt does not bind replayed old failed/collector evidence")
    if receipt.get("policy_sha256") != core.canonical_sha256(_policy(config)):
        raise core.CampaignError("FIRE lineage policy/config drift")
    seed_path = _strict_regular(run_dir, "fire_seed.in")
    if receipt.get("seed_path") != "fire_seed.in" or receipt.get("seed_sha256") != core.sha256_path(seed_path):
        raise core.CampaignError("FIRE frozen seed hash mismatch")
    if receipt.get("workflow_sha256") != _workflow_hashes():
        raise core.CampaignError("FIRE workflow source has drifted from the frozen lineage")
    # The copied provenance records are part of the frozen source contract, not
    # merely an initial prepare-time convenience.  Rehash them for every plan.
    source_root = _strict_dir(run_dir, "lineage_source")
    source_hashes = receipt.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or set(source_hashes) != set(REQUIRED_SEED_FILES):
        raise core.CampaignError("FIRE lineage source receipt is incomplete")
    if any(source_hashes[name] != binding["reference_sha256"] for name in REQUIRED_SEED_FILES):
        raise core.CampaignError("FIRE lineage source receipt is not bound to old reference anchor")
    copied_payloads: list[bytes] = []
    for name in REQUIRED_SEED_FILES:
        source = _strict_regular(source_root, _archived_source_relative(name))
        if core.sha256_path(source) != source_hashes[name]:
            raise core.CampaignError("FIRE copied source reference hash mismatch")
        copied_payloads.append(source.read_bytes())
    if seed_path.read_bytes() != copied_payloads[0] or len(set(copied_payloads)) != 1:
        raise core.CampaignError("FIRE frozen seed no longer equals all archived source references")
    parsed = parse_qe_input(seed_path.read_text())
    if receipt.get("atom_count") != int(config["material"]["unitcell_atoms"]) or receipt.get("atom_labels") != [item.label for item in parsed.atomic_positions] or receipt.get("fixed_cell") != [list(row) for row in parsed.cell_parameters] or receipt.get("spacegroup_requirement") != "Ibam No.72 at 1e-6 angstrom; replayed in final gate":
        raise core.CampaignError("FIRE receipt geometry identity drift")
    audit_copy = _strict_regular(source_root, _archived_source_relative(STANDARDIZATION_AUDIT))
    if receipt.get("original_standardization_audit_sha256") != binding["standardization_audit_sha256"] or core.sha256_path(audit_copy) != binding["standardization_audit_sha256"]:
        raise core.CampaignError("FIRE copied standardization audit hash mismatch")
    attempt_root = _strict_dir(run_dir, f"slurm_attempts/{stage}")
    submission_root = _strict_dir(run_dir, f"submissions/{stage}")
    if any(attempt_root.iterdir()) or any(submission_root.iterdir()):
        raise core.CampaignError("FIRE stage has already consumed its sole attempt/submission slot")
    return {"material": config["material"]["formula"], "config_sha256": validation["config_sha256"], "lineage_sha256": core.sha256_path(run_dir / LINEAGE), "stage": stage}


def run_stage(config_path: Path, run_dir: Path, stage: str) -> dict[str, Any]:
    """Mechanical stop retained for callers of an older draft API."""
    raise core.CampaignError("FIRE execution is not released; reviewed lineage is plan-only")


def finalize_stage(config_path: Path, run_dir: Path, stage: str) -> dict[str, Any]:
    """Mechanical stop retained for callers of an older draft API."""
    raise core.CampaignError("FIRE finalization is not released; reviewed lineage is plan-only")


def release_preflight(*_: object, **__: object) -> dict[str, Any]:
    """Reserved future boundary; arbitrary review JSON must never unlock work."""
    raise core.CampaignError("independent replay not implemented; FIRE preflight remains locked")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-lineage"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--old-lineage-run", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-lineage": result = prepare_lineage(args.config,args.run_dir,args.old_lineage_run)
    except (core.CampaignError, OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())

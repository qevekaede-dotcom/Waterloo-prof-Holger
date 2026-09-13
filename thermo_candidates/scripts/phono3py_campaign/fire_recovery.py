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
import math
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import campaign as core
from qe_input import (
    _set_namelist_values,
    build_fixed_cell_relax_input,
    extract_final_coordinates,
    parse_qe_input,
    replace_qe_geometry,
)
from qe_output import FORCE_HEADER, RUN_START, _force_records

POLICY = "reviewed_fire_recovery"
LINEAGE = "fire_lineage_receipt.json"
PILOT_RELEASE = "fire_pilot_execution_release.json"
PILOT_GATE = "fire_pilot_gate.json"
PILOT_PROVENANCE = "fire_pilot_provenance.json"
GLOBAL_CLAIM_DIRECTORY = ".p3-fire-pilot-claims-v1"
INFRASTRUCTURE_REPLACEMENT = "infrastructure_replacement_authorization_v1.json"
REPLACEMENT_SUBMISSION_STAGE = "fire-pilot-infrastructure-replacement"
EXECUTION_POLICY_VERSION = 1
REQUIRED_SEED_FILES = (
    "polish_reference.in",
    "lineage_source/one_reset_attempt/reference_unitcell.in",
    "lineage_source/one_reset_run/recovery_reference.in",
)
STANDARDIZATION_AUDIT = "lineage_source/one_reset_attempt/starting_structure_audit.json"
FIRE_MARKERS = ("FIRE: convergence achieved in", "End of FIRE minimization")
PWSCF_VERSION_HEADER = re.compile(
    r"^\s*Program PWSCF\s+v\.([^\s]+)\s+starts(?:\s|$)", re.MULTILINE
)
_FORBIDDEN_BFGS = {"bfgs_ndim", "trust_radius_ini", "trust_radius_min", "trust_radius_max"}
_TRUSTED_HISTORICAL_CONFIG_SHA256 = "1e6f09fd5cbd26308143ed2f095bbfcadb76ff2d1b114b6b13c3edb5627a33a1"
_TRUSTED_HISTORICAL_CONFIG_CANONICAL_SHA256 = "655cfa0efd216faf5a0ce35e73cf271d32a9fb64d3aac4807a965d71f9921bad"
_TRUSTED_HISTORICAL_COMMIT = "cf0b1d1be318725015ed5d05f4ee3fb63d0fb89d"
_POLISH_LINEAGE_RECEIPT = "polish_lineage.json"
_OLD_RUN_MANIFEST = "run_manifest.json"
_PINNED_NIBI_GIT = "/cvmfs/soft.computecanada.ca/gentoo/2023/x86-64-v3/usr/bin/git"
_PINNED_NIBI_GIT_SHA256 = "fee0fa5192046d970b854cc2a99a6c7fcc50d8ffedb453ad0c1f9294a2d796ea"
_PINNED_NIBI_GIT_VERSION = "git version 2.41.0"
_NIBI_4G_MEMORY_NOTE = (
    "sbatch: NOTE: Your memory request of 4096.0M was likely submitted as 4.0G. "
    "Please note that Slurm interprets memory requests denominated in G as "
    "multiples of 1024M, not 1000M.\n"
)

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
    "polish_lineage_sha256": "c28d1f118fbbb16b54c0d341e0796441e4b1414ad30a71ba6e46e1cf503ed34d",
    "run_manifest_sha256": "84dc0fcf47b719f12738a77dc7ff0903458e82dfcb10d894ef3ed51f2ea48de3",
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

# Code-owned incident record for the sole Nibi FIRE submission.  It reached
# neither p3_begin_attempt nor QE because the batch PATH could not resolve git.
# These are raw readback digests, not values accepted from a caller JSON file.
TRUSTED_STARTUP_INCIDENT: dict[str, Any] = {
    "run_dir": "/scratch/yuhansun/phono3py-runs/20260914-rb-fire-pilot-a85bd00/Rb2Cu2SnS4",
    "checkout": "/scratch/yuhansun/codex-verify-a85bd00",
    "git_commit": "a85bd00941a8958568b0b8dfa656a5ef620eed3b",
    "config_relative": "thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json",
    "config_sha256": "d0ba760f3e65ba65044ccc6e5c3a1987a38014d3b4c1113ddb0ace58c9bcd0a3",
    "primary_attempt_id": "20260913T195903Z-fire-pilot-dc37f8bb",
    "primary_job_id": "21864180",
    "collector_attempt_id": "20260913T195903Z-collect-e4818b79",
    "collector_job_id": "21864181",
    "hashes": {
        "global_claim": "5bdbef2c526aec1fee263538040c2070c966239fe93ca5f7ae5b6296c99de493",
        "fire_lineage_receipt.json": "4f1b29ce0b400c409914ca1db6954b89738a2a2219da44ce12776bf3357cae18",
        "fire_pilot_execution_release.json": "347677c8c959b7dc337956bfc345227d5ce7e79ba47b29c5ee544f1d72ecba2d",
        "fire_seed.in": "b2f919f7af04a0fd93400e2e5cd021bb489947e245e3d834694167bf2ded714f",
        "request.json": "d689f6a82e1c11b8ae213bb0f3103236eccd62459e0e267f2d3a4663c3d50c93",
        "primary_result.json": "6a6175efd627f387897a49711cb2329b8e9d650d17f3a8dc84ab3f5cded2d044",
        "collector_request.json": "7d910a2efa1c13a8947545932edb0c5c03d3108a8b61a18e8cef9cd6cf50dd10",
        "collector_result.json": "79a943bd50be96687dc066dacfa44f3a770aeaedbe48751e25640bb4da48034b",
        "collector_attachment.json": "d162178848a323249be2ddb9cdd91d9ae6759a30af6190ebfb7ee020e4b9cf3e",
        "primary_release.json": "03111e053760603ba06d9e68adecbdd70c8b1323757aef0c8c1a828a22935cc1",
        "submission.json": "ae40fd87e330cd9016afc5d4a5345c930634710592415c70c6f0a18d10444632",
        "collector/context.tsv": "4c30ae4e5ebace93aac0f9dcbeac44f2c554f7c1e8413d1f7e766eccc6dee957",
        "collector/stdout.log": "b069c620b3e6c6a883e5cebd0b43ceb5649be63a84d2a37837a9f4f46222ebf9",
        "collector/stderr.log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "collector/exit_code.txt": "53c234e5e8472b6ac51c1ae1cab3fe06fad053beb8ebfd8977b010655bfdd3c3",
        "collector/finished_utc.txt": "bec78859d13f59c2c00b67a442a7ff76002f51d3083af5bcd475d785fc13f1b7",
        "collector/primary_sacct.psv": "41918bc8091a1502f8755a550aa94bd1ef3b3a80c8b47fabbebd387a10ddee10",
        "collector/primary_sacct-query-01.psv": "41918bc8091a1502f8755a550aa94bd1ef3b3a80c8b47fabbebd387a10ddee10",
        "collector/primary_sacct.err": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "collector/primary_sacct-query-01.err": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "collector/primary_sacct_exit_code.txt": "9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa",
        "collector/primary_sacct_query_count.txt": "4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865",
        "primary_scheduler_log": "8b0f19ae5ceef8971891d101eb6664291d7e033923753268500c44028a6553d5",
        "collector_scheduler_log": "b069c620b3e6c6a883e5cebd0b43ceb5649be63a84d2a37837a9f4f46222ebf9",
    },
    "primary_allocation": "21864180|FAILED|2:0|4|32||def-kleinke_cpu|cpubase_bycore_b2|1|32|62.50G|120",
    "primary_collector_allocation": "21864180|21864180|FAILED|2:0|4|32||def-kleinke_cpu|cpubase_bycore_b2|1|32|62.50G|120",
    "collector_allocation": "21864181|FAILED|2:0|5|1||def-kleinke_cpu|cpubase_bycore_b2|1|1|4G|30",
    "primary_scheduler_text": "/var/spool/slurmd/job21864180/slurm_script: line 32: git: command not found\nERROR: FIRE pilot checkout commit differs from the released lineage\n",
}
if any(
    re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
    for value in TRUSTED_STARTUP_INCIDENT["hashes"].values()
):
    raise RuntimeError("TRUSTED_STARTUP_INCIDENT contains a non-SHA256 digest")


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


def _load_strict_bytes_snapshot(
    root: Path, relative: str, label: str
) -> tuple[bytes, str]:
    """Hash one immutable byte snapshot from one no-follow fd."""
    path = _strict_regular(root, relative)
    try:
        path_before = os.lstat(path)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise core.CampaignError(f"cannot open trusted {label} safely: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino) != (path_before.st_dev, path_before.st_ino)
        ):
            raise core.CampaignError(f"trusted {label} changed while opening: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
        if before_identity != after_identity:
            raise core.CampaignError(f"trusted {label} changed while reading: {path}")
    except OSError as exc:
        raise core.CampaignError(f"cannot read trusted {label} safely: {path}") from exc
    finally:
        os.close(descriptor)
    # Re-run the component-wise no-symlink check and prove the pathname still
    # names the inode whose bytes were read.  Hashing and parsing below never
    # reopen the pathname.
    _strict_regular(root, relative)
    try:
        path_after = os.lstat(path)
    except OSError as exc:
        raise core.CampaignError(f"trusted {label} disappeared after reading: {path}") from exc
    if (path_after.st_dev, path_after.st_ino) != (after.st_dev, after.st_ino):
        raise core.CampaignError(f"trusted {label} path changed while reading: {path}")
    data = b"".join(chunks)
    if len(data) != after.st_size:
        raise core.CampaignError(f"trusted {label} byte count changed while reading: {path}")
    return data, hashlib.sha256(data).hexdigest()


def _load_strict_json_snapshot(
    root: Path, relative: str, label: str
) -> tuple[dict[str, Any], str]:
    """Hash and parse the same strict single-open byte snapshot."""
    data, digest = _load_strict_bytes_snapshot(root, relative, label)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise core.CampaignError(f"trusted {label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise core.CampaignError(f"trusted {label} JSON root is not an object")
    return value, digest


def _write_json(path: Path, value: object) -> None:
    core.write_json_immutable(path, value)


def _write_bytes_immutable(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise core.CampaignError(f"refusing to overwrite immutable FIRE file: {path}") from exc


def _policy(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get(POLICY)
    if not isinstance(value, Mapping):
        raise core.CampaignError("campaign has no reviewed FIRE recovery policy")
    return value


def validate_fire_policy(config: Mapping[str, Any]) -> None:
    """Validate the deliberately narrow policy without weakening old BFGS checks."""
    policy = _policy(config)
    expected_top = {"status", "purpose", "execution_policy", "seed_contract", "trusted_old_lineage", "settings", "pilot", "full", "resources", "structure_gate"}
    if set(policy) != expected_top:
        raise core.CampaignError("FIRE policy key set is incomplete or contains an unreviewed field")
    if policy.get("status") != "reviewed_planned_hypothesis_not_validated":
        raise core.CampaignError("FIRE recovery must remain a reviewed, unvalidated hypothesis")
    if policy.get("purpose") != "A separate one-shot FIRE recovery lineage after the terminal BFGS lineage. It is not an extension, retry, or acceptance of the BFGS final state.":
        raise core.CampaignError("FIRE recovery purpose/value drift")
    execution_policy = policy.get("execution_policy")
    expected_execution_policy = {
        "version": EXECUTION_POLICY_VERSION,
        "released_stages": ["fire-pilot"],
        "maximum_attempts": 1,
        "lineage_must_be_prepared_by_current_workflow": True,
        "release_receipt": PILOT_RELEASE,
        "collector_dependency": "afterany",
        "full_execution_released": False,
        "structure_accepted": False,
        "preflight_unlocked": False,
        "force_execution_released": False,
        "production_execution_released": False,
    }
    if not isinstance(execution_policy, Mapping) or dict(execution_policy) != expected_execution_policy:
        raise core.CampaignError("FIRE execution policy/version drift")
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
    if not isinstance(binding, Mapping) or set(binding) != {"run_dir", "reference_sha256", "standardization_audit_sha256", "failed_relax_output_sha256", "failed_relax_context_sha256", "later_collector_collection_sha256", "later_collector_context_sha256", "polish_lineage_sha256", "run_manifest_sha256", "diagnostic_primary_job_id", "diagnostic_collector_job_id", "failed_relax_job_id", "failed_relax_collector_job_id"}:
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


def _git_commit() -> str:
    executable = "git"
    if os.environ.get("SLURM_JOB_ID"):
        executable = os.environ.get("P3_GIT", "")
        if (
            executable != _PINNED_NIBI_GIT
            or os.environ.get("P3_GIT_SHA256") != _PINNED_NIBI_GIT_SHA256
            or os.environ.get("P3_GIT_VERSION") != _PINNED_NIBI_GIT_VERSION
        ):
            raise core.CampaignError("Slurm FIRE replay requires the exact pinned Nibi git")
        git_path = Path(executable)
        try:
            git_stat = os.lstat(git_path)
        except OSError as exc:
            raise core.CampaignError("pinned Nibi git is unavailable") from exc
        if (
            stat.S_ISLNK(git_stat.st_mode)
            or not stat.S_ISREG(git_stat.st_mode)
            or not os.access(git_path, os.X_OK)
        ):
            raise core.CampaignError("pinned Nibi git is unsafe or not executable")
        data, digest = _load_strict_bytes_snapshot(
            Path("/"), executable.lstrip("/"), "pinned Nibi git"
        )
        del data
        if digest != _PINNED_NIBI_GIT_SHA256:
            raise core.CampaignError("pinned Nibi git digest drift")
        version = subprocess.run(
            [executable, "--version"], text=True, capture_output=True, check=False
        )
        if (
            version.returncode != 0
            or version.stdout.strip() != _PINNED_NIBI_GIT_VERSION
            or version.stderr
        ):
            raise core.CampaignError("pinned Nibi git version drift")
    value = subprocess.run(
        [executable, "-C", str(core.REPO_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise core.CampaignError("cannot bind FIRE release to the current exact git commit")
    return value


def _global_claim_path(old_lineage: Path, binding: Mapping[str, Any]) -> Path:
    identity = hashlib.sha256(
        (
            "fire-pilot-v1\0"
            + str(binding["run_dir"])
            + "\0"
            + str(binding["reference_sha256"])
        ).encode()
    ).hexdigest()
    return old_lineage.parent / GLOBAL_CLAIM_DIRECTORY / identity / "claim.json"


def _create_global_claim(
    old_lineage: Path,
    binding: Mapping[str, Any],
    run_dir: Path,
    lineage_sha256: str,
    config: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Atomically consume the sole FIRE hypothesis across all RUN_DIRs."""
    claim_path = _global_claim_path(old_lineage, binding)
    registry = claim_path.parent.parent
    _reject_existing_ancestor_symlinks(registry, "global-claim registry")
    registry.mkdir(mode=0o750, exist_ok=True)
    if registry.is_symlink() or registry.resolve(strict=True) != registry:
        raise core.CampaignError("FIRE global-claim registry is unsafe")
    try:
        os.mkdir(claim_path.parent, 0o750)
    except FileExistsError as exc:
        raise core.CampaignError(
            "the globally unique FIRE pilot lineage has already been consumed"
        ) from exc
    claim = {
        "schema_version": 1,
        "kind": "global_fire_pilot_lineage_claim",
        "identity": claim_path.parent.name,
        "trusted_old_lineage": dict(binding),
        "authorized_run_dir": str(run_dir),
        "fire_lineage_sha256": lineage_sha256,
        "fire_policy_sha256": core.canonical_sha256(_policy(config)),
        "workflow_sha256": _workflow_hashes(),
        "git_commit": _git_commit(),
        "maximum_lineages": 1,
        "plan_only_aab9290_counts_as_consumed": False,
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
    }
    try:
        core.write_json_immutable(claim_path, claim)
    except Exception:
        # The atomic claim directory intentionally remains as fail-closed
        # evidence if writing is interrupted; it must never be reused.
        raise
    return claim_path, claim


def _verify_global_claim(
    run_dir: Path, binding: Mapping[str, Any], lineage: Mapping[str, Any]
) -> tuple[Path, dict[str, Any]]:
    old_lineage = Path(str(binding["run_dir"]))
    expected_path = _global_claim_path(old_lineage, binding)
    recorded = lineage.get("global_claim_path")
    if recorded != str(expected_path):
        raise core.CampaignError("FIRE lineage global-claim path drift")
    _reject_existing_ancestor_symlinks(expected_path, "global claim")
    if not expected_path.is_file() or expected_path.is_symlink():
        raise core.CampaignError("FIRE global claim is missing or unsafe")
    claim = core.load_json(expected_path)
    expected_keys = {
        "schema_version", "kind", "identity", "trusted_old_lineage",
        "authorized_run_dir", "fire_lineage_sha256", "fire_policy_sha256",
        "workflow_sha256", "git_commit", "maximum_lineages",
        "plan_only_aab9290_counts_as_consumed", "structure_accepted",
        "preflight_unlocked", "full_execution_released",
    }
    if set(claim) != expected_keys or claim.get("schema_version") != 1 or claim.get("kind") != "global_fire_pilot_lineage_claim":
        raise core.CampaignError("FIRE global claim schema drift")
    if (
        claim.get("identity") != expected_path.parent.name
        or claim.get("trusted_old_lineage") != dict(binding)
        or claim.get("authorized_run_dir") != str(run_dir)
        or claim.get("fire_lineage_sha256") != core.sha256_path(run_dir / LINEAGE)
        or claim.get("fire_policy_sha256") != lineage.get("policy_sha256")
        or claim.get("workflow_sha256") != _workflow_hashes()
        or claim.get("git_commit") != _git_commit()
        or claim.get("maximum_lineages") != 1
        or claim.get("plan_only_aab9290_counts_as_consumed") is not False
        or any(claim.get(key) is not False for key in ("structure_accepted", "preflight_unlocked", "full_execution_released"))
    ):
        raise core.CampaignError("FIRE global claim binding drift")
    return expected_path, dict(claim)


def _replacement_authorization_path(
    config: Mapping[str, Any], run_dir: Path
) -> Path:
    binding = _policy(config)["trusted_old_lineage"]
    assert isinstance(binding, Mapping)
    claim_path = _global_claim_path(Path(str(binding["run_dir"])), binding)
    return claim_path.parent / INFRASTRUCTURE_REPLACEMENT


def _require_snapshot_hash(
    root: Path,
    relative: str,
    label: str,
    expected_sha256: str,
    *,
    json_object: bool = False,
) -> bytes | dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise core.CampaignError(f"code-owned {label} SHA256 is invalid")
    if json_object:
        value, digest = _load_strict_json_snapshot(root, relative, label)
    else:
        value, digest = _load_strict_bytes_snapshot(root, relative, label)
    if digest != expected_sha256:
        raise core.CampaignError(f"trusted FIRE startup incident hash drift: {label}")
    return value


def _context_snapshot_fields(data: bytes, label: str) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise core.CampaignError(f"trusted {label} is not UTF-8") from exc
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "\t" not in line:
            raise core.CampaignError(f"trusted {label} is malformed")
        key, value = line.split("\t", 1)
        if not key or key in fields:
            raise core.CampaignError(f"trusted {label} has duplicate/empty keys")
        fields[key] = value
    return fields


def _query_exact_incident_scheduler_rows(
    incident: Mapping[str, Any],
) -> dict[str, str]:
    """Read-only reconciliation of the two terminal Nibi allocations."""
    primary_job_id = str(incident["primary_job_id"])
    collector_job_id = str(incident["collector_job_id"])
    command = [
        "/opt/software/slurm/bin/sacct", "--jobs",
        f"{primary_job_id},{collector_job_id}", "--noheader", "--parsable2",
        "--format=JobID,State,ExitCode,ElapsedRaw,AllocCPUS,MaxRSS,Account,Partition,NNodes,NCPUS,ReqMem,TimelimitRaw",
    ]
    try:
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
    except OSError as exc:
        raise core.CampaignError("cannot invoke pinned sacct for FIRE incident") from exc
    if completed.returncode != 0 or completed.stderr:
        raise core.CampaignError("pinned sacct could not reconcile the FIRE incident")
    rows: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        job_id = line.split("|", 1)[0]
        if job_id in {primary_job_id, collector_job_id}:
            if job_id in rows:
                raise core.CampaignError("duplicate FIRE incident allocation row")
            rows[job_id] = line
    expected = {
        primary_job_id: str(incident["primary_allocation"]),
        collector_job_id: str(incident["collector_allocation"]),
    }
    if rows != expected:
        raise core.CampaignError(
            "FIRE incident scheduler rows differ from reviewed terminal evidence"
        )
    return rows


def _authenticate_startup_incident(
    config_path: Path,
    run_dir: Path,
    *,
    query_scheduler: bool,
    replacement_attempt_id: str | None = None,
    allow_primary_attempt: bool = False,
    replacement_collector_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Replay the sole pre-QE Nibi failure from exact single-open evidence."""
    config_path = config_path.resolve(strict=True)
    config, validation = core.validate_config(config_path)
    validate_fire_policy(config)
    incident = TRUSTED_STARTUP_INCIDENT
    hashes = incident.get("hashes")
    if not isinstance(hashes, Mapping) or any(
        re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
        for value in hashes.values()
    ):
        raise core.CampaignError(
            "code-owned FIRE startup-incident hash inventory is invalid"
        )
    _reject_existing_ancestor_symlinks(run_dir, "incident RUN_DIR")
    run_dir = core.safe_run_dir(run_dir)
    if str(run_dir) != incident.get("run_dir"):
        raise core.CampaignError(
            "infrastructure replacement is restricted to the exact failed FIRE RUN_DIR"
        )
    if validation["config_sha256"] != incident.get("config_sha256"):
        raise core.CampaignError(
            "FIRE replacement config differs from the reviewed incident config"
        )

    binding = _policy(config)["trusted_old_lineage"]
    assert isinstance(binding, Mapping)
    claim_path = _global_claim_path(Path(str(binding["run_dir"])), binding)
    claim = _require_snapshot_hash(
        claim_path.parent, "claim.json", "global claim",
        str(hashes["global_claim"]), json_object=True,
    )
    lineage = _require_snapshot_hash(
        run_dir, LINEAGE, "FIRE lineage", str(hashes[LINEAGE]), json_object=True
    )
    release = _require_snapshot_hash(
        run_dir, PILOT_RELEASE, "FIRE pilot release",
        str(hashes[PILOT_RELEASE]), json_object=True,
    )
    seed = _require_snapshot_hash(
        run_dir, "fire_seed.in", "frozen FIRE seed",
        str(hashes["fire_seed.in"]),
    )
    assert isinstance(claim, dict) and isinstance(lineage, dict)
    assert isinstance(release, dict) and isinstance(seed, bytes)
    primary_attempt_id = str(incident["primary_attempt_id"])
    primary_job_id = str(incident["primary_job_id"])
    collector_attempt_id = str(incident["collector_attempt_id"])
    collector_job_id = str(incident["collector_job_id"])
    if (
        claim.get("authorized_run_dir") != str(run_dir)
        or claim.get("fire_lineage_sha256") != hashes[LINEAGE]
        or claim.get("trusted_old_lineage") != dict(binding)
        or claim.get("maximum_lineages") != 1
        or any(claim.get(key) is not False for key in (
            "structure_accepted", "preflight_unlocked", "full_execution_released"
        ))
        or lineage.get("trusted_old_lineage") != dict(binding)
        or lineage.get("seed_sha256") != hashes["fire_seed.in"]
        or hashes["fire_seed.in"] != binding["reference_sha256"]
        or lineage.get("global_claim_path") != str(claim_path)
        or release.get("fire_lineage_sha256") != hashes[LINEAGE]
        or release.get("global_claim_sha256") != hashes["global_claim"]
        or release.get("config_sha256") != incident["config_sha256"]
        or release.get("git_commit") != incident["git_commit"]
        or release.get("resources") != {
            "account": "def-kleinke_cpu", "partition": "cpubase_bycore_b2",
            "nodes": 1, "ntasks": 32, "cpus_per_task": 1,
            "mem_per_cpu_mb": 2000, "walltime_minutes": 120,
        }
        or any(release.get(name) is not False for name in (
            "structure_accepted", "preflight_unlocked", "full_execution_released",
            "force_execution_released", "production_execution_released",
        ))
    ):
        raise core.CampaignError("trusted FIRE claim/lineage/release relation drift")

    submission_root = _strict_dir(run_dir, "submissions/fire-pilot")
    submission_entries = {item.name for item in submission_root.iterdir()}
    allowed_submission_entries = {primary_attempt_id, ".submission.lock"}
    if replacement_attempt_id is not None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", replacement_attempt_id) is None:
            raise core.CampaignError("invalid FIRE replacement attempt identity")
        allowed_submission_entries.add(replacement_attempt_id)
    if submission_entries - allowed_submission_entries or primary_attempt_id not in submission_entries or (
        replacement_attempt_id is not None and replacement_attempt_id not in submission_entries
    ):
        raise core.CampaignError(
            "FIRE incident does not contain exactly one original submission"
        )
    submission = _strict_dir(
        run_dir, f"submissions/fire-pilot/{primary_attempt_id}"
    )
    submission_names = {
        "request.json", "primary_result.json", "collector_request.json",
        "collector_result.json", "collector_attachment.json",
        "primary_release.json", "submission.json",
    }
    if {item.name for item in submission.iterdir()} != submission_names:
        raise core.CampaignError("FIRE incident submission record schema drift")
    records: dict[str, dict[str, Any]] = {}
    for name in sorted(submission_names):
        value = _require_snapshot_hash(
            submission, name, f"original {name}", str(hashes[name]),
            json_object=True,
        )
        assert isinstance(value, dict)
        records[name] = value
    request = records["request.json"]
    primary_result = records["primary_result.json"]
    collector_request = records["collector_request.json"]
    collector_result = records["collector_result.json"]
    attachment = records["collector_attachment.json"]
    primary_release = records["primary_release.json"]
    summary = records["submission.json"]
    original_config_path = str(
        Path(str(incident["checkout"])) / str(incident["config_relative"])
    )
    if (
        request.get("stage") != "fire-pilot"
        or request.get("attempt_id") != primary_attempt_id
        or request.get("run_dir") != str(run_dir)
        or request.get("config_sha256") != incident["config_sha256"]
        or request.get("config") != original_config_path
        or request.get("git_commit") != incident["git_commit"]
        or primary_result.get("stage") != "fire-pilot"
        or primary_result.get("attempt_id") != primary_attempt_id
        or str(primary_result.get("job_id")) != primary_job_id
        or primary_result.get("returncode") != 0
        or not _sbatch_stdout_matches_job(primary_result.get("stdout"), primary_job_id)
        or primary_result.get("stderr") != ""
        or primary_result.get("command") != request.get("command")
        or collector_request.get("stage") != "collect"
        or collector_request.get("attempt_id") != collector_attempt_id
        or collector_request.get("primary_attempt_id") != primary_attempt_id
        or str(collector_request.get("primary_job_id")) != primary_job_id
        or collector_request.get("primary_request_sha256") != hashes["request.json"]
        or collector_request.get("primary_result_sha256") != hashes["primary_result.json"]
        or collector_request.get("dependency") != f"afterany:{primary_job_id}"
        or collector_request.get("git_commit") != incident["git_commit"]
        or collector_result.get("attempt_id") != collector_attempt_id
        or str(collector_result.get("job_id")) != collector_job_id
        or collector_result.get("primary_attempt_id") != primary_attempt_id
        or str(collector_result.get("primary_job_id")) != primary_job_id
        or collector_result.get("returncode") != 0
        or not _sbatch_stdout_matches_job(collector_result.get("stdout"), collector_job_id)
        or collector_result.get("stderr") != _NIBI_4G_MEMORY_NOTE
        or collector_result.get("command") != collector_request.get("command")
        or attachment.get("primary_attempt_id") != primary_attempt_id
        or str(attachment.get("primary_job_id")) != primary_job_id
        or attachment.get("collector_attempt_id") != collector_attempt_id
        or str(attachment.get("collector_job_id")) != collector_job_id
        or attachment.get("primary_request_sha256") != hashes["request.json"]
        or attachment.get("primary_result_sha256") != hashes["primary_result.json"]
        or attachment.get("collector_request_sha256") != hashes["collector_request.json"]
        or attachment.get("collector_result_sha256") != hashes["collector_result.json"]
        or attachment.get("collector_dependency") != f"afterany:{primary_job_id}"
        or attachment.get("primary_command") != request.get("command")
        or attachment.get("collector_command") != collector_request.get("command")
        or attachment.get("release_command") != ["scontrol", "release", primary_job_id]
        or primary_release.get("command") != ["scontrol", "release", primary_job_id]
        or primary_release.get("returncode") != 0
        or primary_release.get("collector_attachment_sha256")
        != hashes["collector_attachment.json"]
        or str(summary.get("primary_job_id")) != primary_job_id
        or summary.get("attempt_id") != primary_attempt_id
        or summary.get("stage") != "fire-pilot"
    ):
        raise core.CampaignError(
            "trusted FIRE original submission-chain identity drift"
        )
    if not isinstance(request.get("command"), list) or "--hold" not in request["command"]:
        raise core.CampaignError(
            "trusted FIRE original primary was not submitted held"
        )
    summary_collector = summary.get("collector")
    if not isinstance(summary_collector, Mapping) or (
        summary_collector.get("attempt_id") != collector_attempt_id
        or str(summary_collector.get("job_id")) != collector_job_id
        or summary_collector.get("dependency") != f"afterany:{primary_job_id}"
        or summary_collector.get("request_sha256") != hashes["collector_request.json"]
        or summary_collector.get("result_sha256") != hashes["collector_result.json"]
        or summary_collector.get("attachment_sha256") != hashes["collector_attachment.json"]
        or summary_collector.get("primary_release_sha256") != hashes["primary_release.json"]
    ):
        raise core.CampaignError("trusted FIRE original submission summary drift")

    primary_attempt_root = _strict_dir(run_dir, "slurm_attempts/fire-pilot")
    primary_entries = {item.name for item in primary_attempt_root.iterdir()}
    allowed_primary_entries = [set()]
    if allow_primary_attempt and replacement_attempt_id:
        allowed_primary_entries.append({replacement_attempt_id})
    if primary_entries not in allowed_primary_entries:
        raise core.CampaignError(
            "FIRE incident unexpectedly contains a scientific primary attempt"
        )
    collector_root = _strict_dir(run_dir, "slurm_attempts/collect")
    expected_collector_entries = {collector_attempt_id}
    if replacement_collector_attempt_id is not None:
        expected_collector_entries.add(replacement_collector_attempt_id)
    if {item.name for item in collector_root.iterdir()} != expected_collector_entries:
        raise core.CampaignError("FIRE incident collector-attempt inventory drift")
    collector = _strict_dir(
        run_dir, f"slurm_attempts/collect/{collector_attempt_id}"
    )
    collector_hash_names = {
        str(key)[len("collector/"):]: str(value)
        for key, value in hashes.items() if str(key).startswith("collector/")
    }
    if {item.name for item in collector.iterdir()} != set(collector_hash_names):
        raise core.CampaignError("FIRE incident collector raw-evidence schema drift")
    collector_bytes: dict[str, bytes] = {}
    for name, expected_sha in collector_hash_names.items():
        value = _require_snapshot_hash(
            collector, name, f"collector {name}", expected_sha
        )
        assert isinstance(value, bytes)
        collector_bytes[name] = value
    context = _context_snapshot_fields(collector_bytes["context.tsv"], "collector context")
    context_expected = {
        "stage": "collect", "attempt_id": collector_attempt_id,
        "slurm_job_id": collector_job_id, "slurm_job_account": "def-kleinke_cpu",
        "slurm_job_partition": "cpubase_bycore_b2", "slurm_job_num_nodes": "1",
        "slurm_ntasks": "1", "slurm_cpus_per_task": "",
        "slurm_mem_per_cpu": "", "slurm_timelimit": "",
        "run_dir": str(run_dir), "config_sha256": incident["config_sha256"],
        "primary_stage": "fire-pilot", "primary_attempt_id": primary_attempt_id,
        "primary_job_id": primary_job_id,
        "primary_request_sha256": hashes["request.json"],
        "primary_result_sha256": hashes["primary_result.json"],
        "fire_lineage_sha256": hashes[LINEAGE],
        "fire_release_sha256": hashes[PILOT_RELEASE], "git_commit": "",
    }
    if any(context.get(key) != str(value) for key, value in context_expected.items()):
        raise core.CampaignError(
            "trusted FIRE collector context identity/resource drift"
        )
    if (
        collector_bytes["exit_code.txt"] != b"2\n"
        or collector_bytes["primary_sacct_exit_code.txt"] != b"0\n"
        or collector_bytes["primary_sacct_query_count.txt"] != b"1\n"
    ):
        raise core.CampaignError("trusted FIRE collector exit/query evidence drift")
    try:
        sacct_text = collector_bytes["primary_sacct.psv"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise core.CampaignError(
            "trusted FIRE primary sacct evidence is not UTF-8"
        ) from exc
    if str(incident["primary_collector_allocation"]) not in sacct_text.splitlines():
        raise core.CampaignError(
            "trusted FIRE primary scheduler allocation row drift"
        )

    checkout = Path(str(incident["checkout"]))
    _reject_existing_ancestor_symlinks(checkout, "incident checkout")
    checkout = core.safe_run_dir(checkout)
    _require_snapshot_hash(
        checkout, str(incident["config_relative"]), "original incident config",
        str(incident["config_sha256"]),
    )
    primary_scheduler_relative = (
        f"thermo_candidates/scripts/phono3py_campaign/slurm-{primary_job_id}.out"
    )
    collector_scheduler_relative = (
        f"thermo_candidates/scripts/phono3py_campaign/slurm-p3-collect-{collector_job_id}.out"
    )
    primary_scheduler = _require_snapshot_hash(
        checkout, primary_scheduler_relative, "primary scheduler log",
        str(hashes["primary_scheduler_log"]),
    )
    collector_scheduler = _require_snapshot_hash(
        checkout, collector_scheduler_relative, "collector scheduler log",
        str(hashes["collector_scheduler_log"]),
    )
    assert isinstance(primary_scheduler, bytes) and isinstance(collector_scheduler, bytes)
    if primary_scheduler != str(incident["primary_scheduler_text"]).encode("utf-8"):
        raise core.CampaignError("FIRE primary scheduler failure text drift")
    if collector_scheduler != collector_bytes["stdout.log"]:
        raise core.CampaignError("FIRE collector scheduler/stdout evidence drift")
    scheduler_rows = (
        _query_exact_incident_scheduler_rows(incident) if query_scheduler else {
            primary_job_id: str(incident["primary_allocation"]),
            collector_job_id: str(incident["collector_allocation"]),
        }
    )
    return {
        "config": config, "validation": validation, "claim_path": claim_path,
        "claim": claim, "lineage": lineage, "release": release,
        "submission_dir": submission, "records": records,
        "scheduler_rows": scheduler_rows, "evidence_sha256": dict(hashes),
    }


def create_infrastructure_replacement_authorization(
    config_path: Path, run_dir: Path
) -> dict[str, Any]:
    """Consume the sole reviewed infrastructure replacement authorization."""
    from submit import require_nibi_login

    require_nibi_login()
    evidence = _authenticate_startup_incident(
        config_path, run_dir, query_scheduler=True
    )
    config = evidence["config"]
    validation = evidence["validation"]
    run_dir = core.safe_run_dir(run_dir)
    authorization_path = _replacement_authorization_path(config, run_dir)
    _reject_existing_ancestor_symlinks(
        authorization_path, "replacement authorization"
    )
    if os.path.lexists(authorization_path):
        raise core.CampaignError(
            "FIRE infrastructure replacement authorization is already consumed"
        )
    receipt = {
        "schema_version": 1,
        "kind": "single_fire_pilot_infrastructure_replacement_authorization",
        "created_utc": core.utc_now(),
        "authorized_run_dir": str(run_dir),
        "original_claim_path": str(evidence["claim_path"]),
        "original_claim_sha256": TRUSTED_STARTUP_INCIDENT["hashes"]["global_claim"],
        "original_lineage_sha256": TRUSTED_STARTUP_INCIDENT["hashes"][LINEAGE],
        "original_release_sha256": TRUSTED_STARTUP_INCIDENT["hashes"][PILOT_RELEASE],
        "original_primary_attempt_id": TRUSTED_STARTUP_INCIDENT["primary_attempt_id"],
        "original_primary_job_id": TRUSTED_STARTUP_INCIDENT["primary_job_id"],
        "original_collector_attempt_id": TRUSTED_STARTUP_INCIDENT["collector_attempt_id"],
        "original_collector_job_id": TRUSTED_STARTUP_INCIDENT["collector_job_id"],
        "original_evidence_sha256": dict(evidence["evidence_sha256"]),
        "terminal_scheduler_rows": dict(evidence["scheduler_rows"]),
        "incident_classification": "pinned_git_was_unavailable_before_p3_begin_attempt_or_qe",
        "original_global_claims_consumed": 1,
        "authorized_infrastructure_replacements": 1,
        "scientific_attempts_observed": 0,
        "maximum_scientific_attempts": 1,
        "new_lineage_created": False,
        "current_config_binding": _current_config_binding(
            config_path, config, validation
        ),
        "current_workflow_sha256": _workflow_hashes(),
        "current_git_commit": _git_commit(),
        "replacement_resources": {
            "primary": {
                "account": "def-kleinke_cpu", "partition": "cpubase_bycore_b2",
                "nodes": 1, "ntasks": 32, "cpus_per_task": 1,
                "mem_per_cpu_mb": 2000, "walltime_minutes": 120,
            },
            "collector": {
                "dependency": "afterany", "nodes": 1, "ntasks": 1,
                "cpus_per_task": 1, "memory": "4G", "walltime_minutes": 30,
            },
        },
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
        "force_execution_released": False,
        "production_execution_released": False,
    }
    _write_bytes_immutable(
        authorization_path,
        (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _, authorization_sha256 = _load_strict_json_snapshot(
        authorization_path.parent, authorization_path.name,
        "infrastructure replacement authorization",
    )
    return {
        "healthy": True, "authorization": str(authorization_path),
        "authorization_sha256": authorization_sha256,
        "authorized_run_dir": str(run_dir),
        "replacement_submission_released": True,
        "maximum_replacements": 1, "scientific_attempts_observed": 0,
        "structure_accepted": False, "preflight_unlocked": False,
        "full_execution_released": False,
    }


def verify_infrastructure_replacement_authorization(
    config_path: Path,
    run_dir: Path,
    *,
    require_unused: bool = True,
    expected_authorization_sha256: str | None = None,
    replacement_attempt_id: str | None = None,
    allow_primary_attempt: bool = False,
    replacement_collector_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Replay the immutable replacement authority without creating state."""
    evidence = _authenticate_startup_incident(
        config_path, run_dir, query_scheduler=False,
        replacement_attempt_id=replacement_attempt_id,
        allow_primary_attempt=allow_primary_attempt,
        replacement_collector_attempt_id=replacement_collector_attempt_id,
    )
    config = evidence["config"]
    validation = evidence["validation"]
    run_dir = core.safe_run_dir(run_dir)
    path = _replacement_authorization_path(config, run_dir)
    receipt, digest = _load_strict_json_snapshot(
        path.parent, path.name, "infrastructure replacement authorization"
    )
    if expected_authorization_sha256 is not None and (
        re.fullmatch(r"[0-9a-f]{64}", expected_authorization_sha256) is None
        or digest != expected_authorization_sha256
    ):
        raise core.CampaignError(
            "FIRE infrastructure replacement authorization SHA256 mismatch"
        )
    expected_fields = {
        "schema_version", "kind", "created_utc", "authorized_run_dir",
        "original_claim_path", "original_claim_sha256",
        "original_lineage_sha256", "original_release_sha256",
        "original_primary_attempt_id", "original_primary_job_id",
        "original_collector_attempt_id", "original_collector_job_id",
        "original_evidence_sha256", "terminal_scheduler_rows",
        "incident_classification", "original_global_claims_consumed",
        "authorized_infrastructure_replacements", "scientific_attempts_observed",
        "maximum_scientific_attempts", "new_lineage_created",
        "current_config_binding", "current_workflow_sha256", "current_git_commit",
        "replacement_resources", "structure_accepted", "preflight_unlocked",
        "full_execution_released", "force_execution_released",
        "production_execution_released",
    }
    incident = TRUSTED_STARTUP_INCIDENT
    if set(receipt) != expected_fields or (
        receipt.get("schema_version") != 1
        or receipt.get("kind")
        != "single_fire_pilot_infrastructure_replacement_authorization"
        or not isinstance(receipt.get("created_utc"), str)
        or receipt.get("authorized_run_dir") != str(run_dir)
        or receipt.get("original_claim_path") != str(evidence["claim_path"])
        or receipt.get("original_claim_sha256") != incident["hashes"]["global_claim"]
        or receipt.get("original_lineage_sha256") != incident["hashes"][LINEAGE]
        or receipt.get("original_release_sha256") != incident["hashes"][PILOT_RELEASE]
        or receipt.get("original_primary_attempt_id") != incident["primary_attempt_id"]
        or receipt.get("original_primary_job_id") != incident["primary_job_id"]
        or receipt.get("original_collector_attempt_id") != incident["collector_attempt_id"]
        or receipt.get("original_collector_job_id") != incident["collector_job_id"]
        or receipt.get("original_evidence_sha256") != evidence["evidence_sha256"]
        or receipt.get("terminal_scheduler_rows") != {
            str(incident["primary_job_id"]): str(incident["primary_allocation"]),
            str(incident["collector_job_id"]): str(incident["collector_allocation"]),
        }
        or receipt.get("incident_classification")
        != "pinned_git_was_unavailable_before_p3_begin_attempt_or_qe"
        or receipt.get("original_global_claims_consumed") != 1
        or receipt.get("authorized_infrastructure_replacements") != 1
        or receipt.get("scientific_attempts_observed") != 0
        or receipt.get("maximum_scientific_attempts") != 1
        or receipt.get("new_lineage_created") is not False
        or receipt.get("current_config_binding")
        != _current_config_binding(config_path, config, validation)
        or receipt.get("current_workflow_sha256") != _workflow_hashes()
        or receipt.get("current_git_commit") != _git_commit()
        or receipt.get("replacement_resources") != {
            "primary": {
                "account": "def-kleinke_cpu", "partition": "cpubase_bycore_b2",
                "nodes": 1, "ntasks": 32, "cpus_per_task": 1,
                "mem_per_cpu_mb": 2000, "walltime_minutes": 120,
            },
            "collector": {
                "dependency": "afterany", "nodes": 1, "ntasks": 1,
                "cpus_per_task": 1, "memory": "4G", "walltime_minutes": 30,
            },
        }
        or any(receipt.get(name) is not False for name in (
            "structure_accepted", "preflight_unlocked", "full_execution_released",
            "force_execution_released", "production_execution_released",
        ))
    ):
        raise core.CampaignError(
            "FIRE infrastructure replacement authorization binding drift"
        )
    if require_unused:
        original = str(TRUSTED_STARTUP_INCIDENT["primary_attempt_id"])
        submission_root = _strict_dir(run_dir, "submissions/fire-pilot")
        entries = {item.name for item in submission_root.iterdir()}
        if entries - {original, ".submission.lock"} or original not in entries:
            raise core.CampaignError(
                "FIRE infrastructure replacement submission slot is already consumed"
            )
    return {
        "stage": "fire-pilot", "replacement": True,
        "authorization_path": str(path), "authorization_sha256": digest,
        "lineage_sha256": incident["hashes"][LINEAGE],
        "release_sha256": incident["hashes"][PILOT_RELEASE],
        "config_sha256": validation["config_sha256"],
        "git_commit": receipt["current_git_commit"],
        "workflow_sha256": dict(receipt["current_workflow_sha256"]),
        "resources": dict(receipt["replacement_resources"]),
        "structure_accepted": False, "preflight_unlocked": False,
        "full_execution_released": False,
    }


def _validate_generated_input(config: Mapping[str, Any], text: str, stage: str) -> None:
    """Reparse the generated QE input and pin every reviewed pilot control."""
    parsed = parse_qe_input(text)
    settings = _policy(config)["settings"]
    spec = _policy(config)[stage]
    required_patterns = {
        "calculation": r"(?im)^\s*calculation\s*=\s*'relax'\s*,?\s*$",
        "prefix": rf"(?im)^\s*prefix\s*=\s*'Rb2Cu2SnS4_fire_{stage}'\s*,?\s*$",
        "outdir": rf"(?im)^\s*outdir\s*=\s*'\./tmp-fire-{stage}'\s*,?\s*$",
        "restart_mode": r"(?im)^\s*restart_mode\s*=\s*'from_scratch'\s*,?\s*$",
        "nstep": rf"(?im)^\s*nstep\s*=\s*{spec['nstep']}\s*,?\s*$",
        "max_seconds": rf"(?im)^\s*max_seconds\s*=\s*{spec['max_seconds']}\s*,?\s*$",
        "ecutwfc": r"(?im)^\s*ecutwfc\s*=\s*100(?:\.0*)?\s*,?\s*$",
        "ecutrho": r"(?im)^\s*ecutrho\s*=\s*800(?:\.0*)?\s*,?\s*$",
        "occupations": r"(?im)^\s*occupations\s*=\s*'fixed'\s*,?\s*$",
        "conv_thr": r"(?im)^\s*conv_thr\s*=\s*1(?:\.0*)?[EeDd]-10\s*,?\s*$",
        "electron_maxstep": r"(?im)^\s*electron_maxstep\s*=\s*300\s*,?\s*$",
        "mixing_beta": r"(?im)^\s*mixing_beta\s*=\s*(?:0?\.3|3(?:\.0*)?[EeDd]-1)\s*,?\s*$",
        "scf_must_converge": r"(?im)^\s*scf_must_converge\s*=\s*\.true\.\s*,?\s*$",
        "etot_conv_thr": r"(?im)^\s*etot_conv_thr\s*=\s*1(?:\.0*)?[EeDd]-0*8\s*,?\s*$",
        "forc_conv_thr": r"(?im)^\s*forc_conv_thr\s*=\s*1(?:\.0*)?[EeDd]-0*5\s*,?\s*$",
        "ion_dynamics": r"(?im)^\s*ion_dynamics\s*=\s*'fire'\s*,?\s*$",
        "dt": r"(?im)^\s*dt\s*=\s*10(?:\.0*)?\s*,?\s*$",
        "startingpot": r"(?im)^\s*startingpot\s*=\s*'atomic'\s*,?\s*$",
        "startingwfc": r"(?im)^\s*startingwfc\s*=\s*'atomic\+random'\s*,?\s*$",
        "fire_alpha_init": r"(?im)^\s*fire_alpha_init\s*=\s*(?:0?\.2|2(?:\.0*)?[EeDd]-1)\s*,?\s*$",
        "fire_falpha": r"(?im)^\s*fire_falpha\s*=\s*(?:0?\.99|9\.9(?:0*)?[EeDd]-1)\s*,?\s*$",
        "fire_nmin": r"(?im)^\s*fire_nmin\s*=\s*5\s*,?\s*$",
        "fire_f_inc": r"(?im)^\s*fire_f_inc\s*=\s*1\.1(?:0*)?\s*,?\s*$",
        "fire_f_dec": r"(?im)^\s*fire_f_dec\s*=\s*(?:0?\.5|5(?:\.0*)?[EeDd]-1)\s*,?\s*$",
        "fire_dtmax": r"(?im)^\s*fire_dtmax\s*=\s*2(?:\.0*)?\s*,?\s*$",
        "pot_extrapolation": r"(?im)^\s*pot_extrapolation\s*=\s*'atomic'\s*,?\s*$",
        "wfc_extrapolation": r"(?im)^\s*wfc_extrapolation\s*=\s*'none'\s*,?\s*$",
    }
    missing = [name for name, pattern in required_patterns.items() if re.search(pattern, text) is None]
    if missing:
        raise core.CampaignError("generated FIRE input control mismatch: " + ", ".join(missing))
    if parsed.nat != int(core.required(config, "material.unitcell_atoms")):
        raise core.CampaignError("generated FIRE input atom count drift")
    if tuple(parsed.k_points.grid) != tuple(int(value) for value in settings["kmesh"]):
        raise core.CampaignError("generated FIRE input k mesh drift")
    if any(re.search(rf"(?im)^\s*{name}\s*=", text) for name in _FORBIDDEN_BFGS):
        raise core.CampaignError("generated FIRE input contains forbidden BFGS controls")


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
    spec = _policy(config)[stage]
    assert isinstance(spec, Mapping)
    text = _set_namelist_values(text, "CONTROL", {"nstep": str(spec["nstep"]), "max_seconds": str(spec["max_seconds"]), "restart_mode": "'from_scratch'"})
    text = _set_namelist_values(text, "ELECTRONS", {"startingpot": "'atomic'", "startingwfc": "'atomic+random'", "scf_must_converge": ".true."})
    text = _set_namelist_values(text, "SYSTEM", {"occupations": "'fixed'"})
    if any(re.search(rf"(?im)^\s*{name}\s*=", text) for name in _FORBIDDEN_BFGS):
        raise core.CampaignError("generated FIRE input contains forbidden BFGS trust controls")
    _validate_generated_input(config, text, stage)
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


def _trusted_polish_release(
    config: Mapping[str, Any],
    old_lineage_run: Path,
    binding: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, bytes]]:
    """Replay the real polish receipt/manifest relation and return its UPFs.

    The filenames and both whole-file digests are code/config-owned trust roots.
    This deliberately does not accept a caller-selected JSON object or the
    never-created ``polish_lineage_receipt.json`` spelling.
    """
    from polish_recovery import TRUSTED_EXECUTED_WORKFLOW_SNAPSHOTS

    historical = _historical_config_view(config)
    receipt, lineage_sha256 = _load_strict_json_snapshot(
        old_lineage_run, _POLISH_LINEAGE_RECEIPT, "polish lineage receipt"
    )
    manifest, manifest_sha256 = _load_strict_json_snapshot(
        old_lineage_run, _OLD_RUN_MANIFEST, "polish run manifest"
    )
    if lineage_sha256 != binding["polish_lineage_sha256"]:
        raise core.CampaignError("trusted polish lineage receipt hash drift")
    if manifest_sha256 != binding["run_manifest_sha256"]:
        raise core.CampaignError("trusted polish run manifest hash drift")
    expected_lineage_fields = {
        "schema_version", "kind", "created_utc", "material",
        "structure_policy_sha256", "polish_policy_sha256",
        "config_canonical_sha256", "source_run_dir", "source_attempt",
        "source_manifest_sha256", "source_output_sha256", "source_files",
        "seed_unitcell_sha256", "reference_unitcell_sha256",
        "backend_sha256", "diagnostic_input_sha256",
        "pseudopotential_archive", "review", "automatic_reset",
        "maximum_polish_attempts", "reuse_qe_scratch", "acceptance",
    }
    snapshot = TRUSTED_EXECUTED_WORKFLOW_SNAPSHOTS[_TRUSTED_HISTORICAL_COMMIT]
    if set(receipt) != expected_lineage_fields:
        raise core.CampaignError("trusted polish lineage receipt schema drift")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "reviewed_single_bfgs_polish_after_terminal_one_reset"
        or receipt.get("material") != core.required(config, "material.formula")
        or receipt.get("structure_policy_sha256") != core.policy_sha256(historical, "structure")
        or receipt.get("polish_policy_sha256")
        != core.canonical_sha256(core.required(historical, "reviewed_bfgs_polish"))
        or receipt.get("config_canonical_sha256")
        != _TRUSTED_HISTORICAL_CONFIG_CANONICAL_SHA256
        or receipt.get("reference_unitcell_sha256") != binding["reference_sha256"]
        or receipt.get("backend_sha256") != snapshot["polish_recovery.py"]
        or receipt.get("automatic_reset") is not False
        or receipt.get("maximum_polish_attempts") != 1
        or receipt.get("reuse_qe_scratch") is not False
        or receipt.get("acceptance")
        != "diagnostic cannot accept structure; normal BFGS plus independent pristine SCF and ordinary final gate remain mandatory"
    ):
        raise core.CampaignError("trusted polish lineage identity/policy drift")
    if not isinstance(receipt.get("created_utc"), str):
        raise core.CampaignError("trusted polish lineage timestamp is invalid")
    for field in ("source_run_dir", "source_attempt"):
        value = receipt.get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise core.CampaignError(f"trusted polish lineage {field} is invalid")
    for field in (
        "source_manifest_sha256", "source_output_sha256",
        "seed_unitcell_sha256",
    ):
        if re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field, ""))) is None:
            raise core.CampaignError(f"trusted polish lineage {field} is invalid")
    source_files = receipt.get("source_files")
    if not isinstance(source_files, Mapping) or not source_files:
        raise core.CampaignError("trusted polish lineage source inventory is invalid")
    for name, digest in source_files.items():
        relative = Path(str(name))
        if relative.is_absolute() or ".." in relative.parts or re.fullmatch(
            r"[0-9a-f]{64}", str(digest)
        ) is None:
            raise core.CampaignError("trusted polish lineage source inventory is invalid")
    diagnostic_inputs = receipt.get("diagnostic_input_sha256")
    if not isinstance(diagnostic_inputs, Mapping) or set(diagnostic_inputs) != {
        "baseline.in", "higher_ecutrho.in"
    } or any(
        re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
        for value in diagnostic_inputs.values()
    ):
        raise core.CampaignError("trusted polish diagnostic-input schema drift")

    expected_manifest_fields = {
        "schema_version", "material", "created_utc", "config_path",
        "config_sha256", "structure_policy_sha256",
        "preflight_policy_sha256", "source_qe_input", "source_qe_sha256",
        "source_relax_output", "source_relax_sha256", "workflow_files",
        "git_commit", "relax_polish",
    }
    if set(manifest) != expected_manifest_fields:
        raise core.CampaignError("trusted polish run manifest schema drift")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("material") != core.required(config, "material.formula")
        or manifest.get("config_sha256") != _TRUSTED_HISTORICAL_CONFIG_SHA256
        or manifest.get("git_commit") != _TRUSTED_HISTORICAL_COMMIT
        or manifest.get("structure_policy_sha256") != core.policy_sha256(historical, "structure")
        or manifest.get("preflight_policy_sha256") != core.policy_sha256(historical, "preflight")
    ):
        raise core.CampaignError("trusted polish run manifest identity/config drift")
    for path_field, hash_field, source_key in (
        ("source_qe_input", "source_qe_sha256", "source.qe_scf_input"),
        ("source_relax_output", "source_relax_sha256", "source.original_relax_output"),
    ):
        if not isinstance(manifest.get(path_field), str) or not Path(str(manifest[path_field])).is_absolute():
            raise core.CampaignError(f"trusted polish manifest {path_field} is invalid")
        if manifest.get(hash_field) != core.sha256_path(core.resolve_repo_source(historical, source_key)):
            raise core.CampaignError(f"trusted polish manifest {hash_field} drift")
    workflow = manifest.get("workflow_files")
    expected_workflow_names = {
        "thermo_candidates/scripts/phono3py_campaign/campaign.py",
        "thermo_candidates/scripts/phono3py_campaign/qe_input.py",
        "thermo_candidates/scripts/phono3py_campaign/qe_output.py",
        "thermo_candidates/scripts/phono3py_campaign/polish_recovery.py",
    }
    if not isinstance(workflow, Mapping) or set(workflow) != expected_workflow_names:
        raise core.CampaignError("trusted polish manifest workflow schema drift")
    if (
        workflow["thermo_candidates/scripts/phono3py_campaign/campaign.py"] != snapshot["campaign.py"]
        or workflow["thermo_candidates/scripts/phono3py_campaign/polish_recovery.py"] != snapshot["polish_recovery.py"]
        or any(re.fullmatch(r"[0-9a-f]{64}", str(value)) is None for value in workflow.values())
    ):
        raise core.CampaignError("trusted polish manifest workflow trust-root drift")
    pointer = manifest.get("relax_polish")
    expected_pointer_fields = {
        "kind", "lineage_receipt", "lineage_sha256", "diagnostic_gate",
        "diagnostic_gate_sha256", "maximum_attempts",
        "automatic_submission_allowed",
    }
    if not isinstance(pointer, Mapping) or set(pointer) != expected_pointer_fields:
        raise core.CampaignError("trusted polish manifest pointer schema drift")
    if (
        pointer.get("kind") != "single_reviewed_bfgs_polish"
        or pointer.get("lineage_receipt") != _POLISH_LINEAGE_RECEIPT
        or pointer.get("lineage_sha256") != binding["polish_lineage_sha256"]
        or pointer.get("maximum_attempts") != 1
        or pointer.get("automatic_submission_allowed") is not False
        or pointer.get("diagnostic_gate") != "diagnostic/final/gate.json"
    ):
        raise core.CampaignError("trusted polish manifest/lineage relation drift")
    diagnostic_gate = _strict_regular(old_lineage_run, "diagnostic/final/gate.json")
    if pointer.get("diagnostic_gate_sha256") != core.sha256_path(diagnostic_gate):
        raise core.CampaignError("trusted polish manifest diagnostic-gate hash drift")

    inventory = receipt.get("pseudopotential_archive")
    configured = core.required(config, "pseudopotentials.files")
    if not isinstance(inventory, Mapping) or set(inventory) != set(configured):
        raise core.CampaignError("trusted polish lineage pseudopotential inventory is invalid")
    review = receipt.get("review")
    if not isinstance(review, Mapping) or set(review) != {
        "one_reset_job_id", "one_reset_qe_health",
        "maximum_cumulative_shift_angstrom", "pseudopotentials",
        "original_recovery",
    }:
        raise core.CampaignError("trusted polish review schema drift")
    review_pseudos = review.get("pseudopotentials")
    frozen: dict[str, dict[str, str]] = {}
    blobs: dict[str, bytes] = {}
    for species, filename_value in configured.items():
        filename = str(filename_value)
        item = inventory.get(species)
        relative = f"lineage_source/pseudopotentials/{filename}"
        if (
            not isinstance(item, Mapping)
            or set(item) != {"filename", "relative_path", "sha256"}
            or item.get("filename") != filename
            or item.get("relative_path") != relative
            or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) is None
        ):
            raise core.CampaignError(
                f"trusted polish pseudopotential identity is invalid: {species}"
            )
        source = _strict(old_lineage_run, relative)
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise core.CampaignError(
                f"trusted polish pseudopotential bytes drifted: {species}"
            )
        expected_review_item = {"filename": filename, "sha256": item["sha256"]}
        if not isinstance(review_pseudos, Mapping) or review_pseudos.get(species) != expected_review_item:
            raise core.CampaignError(
                f"trusted polish review pseudopotential drift: {species}"
            )
        frozen[str(species)] = dict(item)
        blobs[filename] = data
    if not isinstance(review_pseudos, Mapping) or set(review_pseudos) != set(configured):
        raise core.CampaignError("trusted polish review pseudopotential schema drift")
    return frozen, blobs


def _verify_frozen_pseudopotentials(
    config: Mapping[str, Any], run_dir: Path, receipt: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    configured = core.required(config, "pseudopotentials.files")
    inventory = receipt.get("pseudopotential_archive")
    if not isinstance(inventory, Mapping) or set(inventory) != set(configured):
        raise core.CampaignError("FIRE frozen pseudopotential inventory is invalid")
    pseudo_root = _strict_dir(run_dir, "lineage_source/pseudopotentials")
    if {item.name for item in pseudo_root.iterdir()} != set(configured.values()):
        raise core.CampaignError("FIRE frozen pseudopotential directory has unexpected entries")
    verified: dict[str, dict[str, str]] = {}
    for species, filename_value in configured.items():
        filename = str(filename_value)
        item = inventory.get(species)
        relative = f"lineage_source/pseudopotentials/{filename}"
        if (
            not isinstance(item, Mapping)
            or set(item) != {"filename", "relative_path", "sha256"}
            or item.get("filename") != filename
            or item.get("relative_path") != relative
            or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) is None
        ):
            raise core.CampaignError(f"FIRE frozen pseudopotential identity drift: {species}")
        archived = _strict_regular(run_dir, relative)
        if core.sha256_path(archived) != item["sha256"]:
            raise core.CampaignError(f"FIRE frozen pseudopotential hash drift: {species}")
        verified[str(species)] = dict(item)
    return verified


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
    pseudo_inventory, pseudo_blobs = _trusted_polish_release(
        config, old_lineage_run, binding
    )
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
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    _reject_existing_ancestor_symlinks(run_dir.parent, "RUN_DIR parent")
    try:
        os.mkdir(run_dir, 0o750)
    except FileExistsError as exc:
        raise core.CampaignError(
            "FIRE RUN_DIR was concurrently created; the lineage is not reusable"
        ) from exc
    for name, data in payloads.items():
        destination = run_dir / "lineage_source" / _archived_source_relative(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        core.write_immutable(destination, data.decode())
    audit_destination = run_dir / "lineage_source" / _archived_source_relative(STANDARDIZATION_AUDIT)
    audit_destination.parent.mkdir(parents=True, exist_ok=True)
    core.write_immutable(audit_destination, audit_path.read_text())
    for filename, data in pseudo_blobs.items():
        destination = run_dir / "lineage_source/pseudopotentials" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes_immutable(destination, data)
    core.write_immutable(run_dir / "fire_seed.in", seed)
    receipt = {
        "schema_version": 3, "kind": "reviewed_fire_recovery_from_audited_polish_reference_only",
        "material": config["material"]["formula"], "structure_accepted": False,
        "preflight_unlocked": False, "seed_path": "fire_seed.in",
        "seed_sha256": core.sha256_path(run_dir / "fire_seed.in"),
        "source_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        "pseudopotential_archive": pseudo_inventory,
        "original_standardization_audit_sha256": core.sha256_path(audit_destination),
        "current_config_binding": _current_config_binding(config_path, config, validation),
        "trusted_old_lineage": dict(binding),
        "trusted_failed_output": str(failed_output.relative_to(old_lineage_run)),
        "trusted_later_collection": str(later_collection.relative_to(old_lineage_run)),
        "atom_count": nat, "atom_labels": [item.label for item in parsed.atomic_positions],
        "fixed_cell": [list(row) for row in parsed.cell_parameters],
        "spacegroup_requirement": "Ibam No.72 at 1e-6 angstrom; replayed in final gate",
        "policy_sha256": core.canonical_sha256(_policy(config)),
        "execution_policy_version": EXECUTION_POLICY_VERSION,
        "git_commit": _git_commit(),
        "global_claim_path": str(_global_claim_path(old_lineage_run, binding)),
        "workflow_sha256": _workflow_hashes(),
    }
    _write_json(run_dir / LINEAGE, receipt)
    for name in ("slurm_attempts/fire-pilot", "slurm_attempts/fire-full", "slurm_attempts/fire-pristine", "submissions/fire-pilot", "submissions/fire-full"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    global_claim_path, _ = _create_global_claim(
        old_lineage_run,
        binding,
        run_dir,
        core.sha256_path(run_dir / LINEAGE),
        config,
    )
    release = {
        "schema_version": 1,
        "kind": "fire_pilot_execution_release",
        "released_stage": "fire-pilot",
        "execution_policy_version": EXECUTION_POLICY_VERSION,
        "maximum_attempts": 1,
        "config_path": str(config_path),
        "config_sha256": validation["config_sha256"],
        "config_canonical_sha256": core.canonical_sha256(config),
        "fire_policy_sha256": core.canonical_sha256(_policy(config)),
        "fire_lineage_sha256": core.sha256_path(run_dir / LINEAGE),
        "global_claim_path": str(global_claim_path),
        "global_claim_sha256": core.sha256_path(global_claim_path),
        "seed_sha256": receipt["seed_sha256"],
        "pseudopotential_archive_sha256": core.canonical_sha256(
            pseudo_inventory
        ),
        "workflow_sha256": _workflow_hashes(),
        "git_commit": receipt["git_commit"],
        "resources": {
            "account": core.required(config, "scheduler.slurm_account"),
            "partition": "cpubase_bycore_b2",
            "nodes": 1,
            "ntasks": 32,
            "cpus_per_task": 1,
            "mem_per_cpu_mb": 2000,
            "walltime_minutes": 120,
        },
        "collector_dependency": "afterany",
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
        "force_execution_released": False,
        "production_execution_released": False,
    }
    _write_json(run_dir / PILOT_RELEASE, release)
    return {
        "healthy": True,
        "run_dir": str(run_dir),
        "seed_sha256": receipt["seed_sha256"],
        "fire_lineage_sha256": core.sha256_path(run_dir / LINEAGE),
        "fire_pilot_release_sha256": core.sha256_path(run_dir / PILOT_RELEASE),
        "execution_released": ["fire-pilot"],
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
    }


def verify_fire_submission_ready(
    config_path: Path, run_dir: Path, stage: str, *, require_unused: bool = True
) -> dict[str, Any]:
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
        "pseudopotential_archive",
        "current_config_binding", "trusted_old_lineage", "trusted_failed_output",
        "trusted_later_collection", "atom_count", "atom_labels", "fixed_cell",
        "spacegroup_requirement", "policy_sha256", "execution_policy_version",
        "git_commit", "global_claim_path", "workflow_sha256",
    }
    if set(receipt) != receipt_fields or receipt.get("schema_version") != 3 or receipt.get("kind") != "reviewed_fire_recovery_from_audited_polish_reference_only":
        raise core.CampaignError("FIRE lineage receipt schema is incomplete or drifted")
    if receipt.get("structure_accepted") is not False or receipt.get("preflight_unlocked") is not False:
        raise core.CampaignError("FIRE plan receipt may not claim structure acceptance or release")
    if receipt.get("material") != config["material"]["formula"] or receipt.get("current_config_binding") != _current_config_binding(config_path, config, validation):
        raise core.CampaignError("FIRE lineage receipt current config binding drift")
    binding = _policy(config)["trusted_old_lineage"]
    if receipt.get("trusted_old_lineage") != dict(binding):
        raise core.CampaignError("FIRE lineage receipt trusted historical anchor drift")
    replayed_old, _, failed_output, later_collection = _replay_trusted_old_lineage(config, config_path, binding)
    _trusted_polish_release(config, replayed_old, binding)
    if receipt.get("trusted_failed_output") != str(failed_output.relative_to(replayed_old)) or receipt.get("trusted_later_collection") != str(later_collection.relative_to(replayed_old)):
        raise core.CampaignError("FIRE lineage receipt does not bind replayed old failed/collector evidence")
    if receipt.get("policy_sha256") != core.canonical_sha256(_policy(config)):
        raise core.CampaignError("FIRE lineage policy/config drift")
    if receipt.get("execution_policy_version") != EXECUTION_POLICY_VERSION or receipt.get("git_commit") != _git_commit():
        raise core.CampaignError("FIRE lineage execution-policy/commit drift")
    global_claim_path, _ = _verify_global_claim(run_dir, binding, receipt)
    seed_path = _strict_regular(run_dir, "fire_seed.in")
    if receipt.get("seed_path") != "fire_seed.in" or receipt.get("seed_sha256") != core.sha256_path(seed_path):
        raise core.CampaignError("FIRE frozen seed hash mismatch")
    if receipt.get("workflow_sha256") != _workflow_hashes():
        raise core.CampaignError("FIRE workflow source has drifted from the frozen lineage")
    _verify_frozen_pseudopotentials(config, run_dir, receipt)
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
    submission_entries = [path for path in submission_root.iterdir() if path.name != ".submission.lock"]
    if require_unused and (any(attempt_root.iterdir()) or submission_entries):
        raise core.CampaignError("FIRE stage has already consumed its sole attempt/submission slot")
    release = _load_release(config_path, run_dir, config, validation, receipt)
    return {
        "material": config["material"]["formula"],
        "config_sha256": validation["config_sha256"],
        "lineage_sha256": core.sha256_path(run_dir / LINEAGE),
        "release_sha256": core.sha256_path(run_dir / PILOT_RELEASE),
        "git_commit": release["git_commit"],
        "stage": stage,
    }


def _load_release(
    config_path: Path,
    run_dir: Path,
    config: Mapping[str, Any],
    validation: Mapping[str, Any],
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay the code-issued pilot release; caller JSON cannot authorize work."""
    path = _strict_regular(run_dir, PILOT_RELEASE)
    value = core.load_json(path)
    expected_keys = {
        "schema_version", "kind", "released_stage", "execution_policy_version",
        "maximum_attempts", "config_path", "config_sha256", "config_canonical_sha256",
        "fire_policy_sha256", "fire_lineage_sha256", "seed_sha256", "workflow_sha256",
        "git_commit", "global_claim_path", "global_claim_sha256", "resources", "collector_dependency",
        "pseudopotential_archive_sha256", "structure_accepted",
        "preflight_unlocked", "full_execution_released", "force_execution_released",
        "production_execution_released",
    }
    if set(value) != expected_keys or value.get("schema_version") != 1 or value.get("kind") != "fire_pilot_execution_release":
        raise core.CampaignError("FIRE pilot release receipt schema drift")
    if value.get("released_stage") != "fire-pilot" or value.get("execution_policy_version") != EXECUTION_POLICY_VERSION or value.get("maximum_attempts") != 1:
        raise core.CampaignError("FIRE pilot release scope/version drift")
    if any(value.get(key) is not False for key in ("structure_accepted", "preflight_unlocked", "full_execution_released", "force_execution_released", "production_execution_released")):
        raise core.CampaignError("FIRE pilot release illegally unlocks a downstream stage")
    expected_resources = {
        "account": core.required(config, "scheduler.slurm_account"),
        "partition": "cpubase_bycore_b2", "nodes": 1, "ntasks": 32,
        "cpus_per_task": 1, "mem_per_cpu_mb": 2000, "walltime_minutes": 120,
    }
    if value.get("resources") != expected_resources or value.get("collector_dependency") != "afterany":
        raise core.CampaignError("FIRE pilot release scheduler/collector policy drift")
    lineage_path = _strict_regular(run_dir, LINEAGE)
    lineage = core.load_json(lineage_path) if lineage is None else lineage
    binding = _policy(config)["trusted_old_lineage"]
    assert isinstance(binding, Mapping)
    global_claim_path, _ = _verify_global_claim(run_dir, binding, lineage)
    expected = {
        "config_path": str(config_path.resolve(strict=True)),
        "config_sha256": validation["config_sha256"],
        "config_canonical_sha256": core.canonical_sha256(config),
        "fire_policy_sha256": core.canonical_sha256(_policy(config)),
        "fire_lineage_sha256": core.sha256_path(lineage_path),
        "global_claim_path": str(global_claim_path),
        "global_claim_sha256": core.sha256_path(global_claim_path),
        "seed_sha256": lineage.get("seed_sha256"),
        "pseudopotential_archive_sha256": core.canonical_sha256(
            _verify_frozen_pseudopotentials(config, run_dir, lineage)
        ),
        "workflow_sha256": _workflow_hashes(),
        "git_commit": _git_commit(),
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise core.CampaignError(f"FIRE pilot release binding drift: {key}")
    return dict(value)


def verify_fire_collector_attachment(
    config_path: Path,
    run_dir: Path,
    primary_attempt_id: str,
    primary_job_id: str,
    *,
    require_release_receipt: bool = True,
    replacement_authorization_sha256: str | None = None,
    allow_primary_attempt: bool = False,
    replacement_collector_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Prove the held primary has an accepted afterany collector before QE."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", primary_attempt_id) is None or not primary_job_id.isdigit():
        raise core.CampaignError("invalid FIRE primary attachment identity")
    config_path = config_path.resolve(strict=True)
    config, validation = core.validate_config(config_path)
    if replacement_authorization_sha256 is None:
        ready = verify_fire_submission_ready(
            config_path, run_dir, "fire-pilot", require_unused=False
        )
    else:
        ready = verify_infrastructure_replacement_authorization(
            config_path,
            run_dir,
            require_unused=False,
            expected_authorization_sha256=replacement_authorization_sha256,
            replacement_attempt_id=primary_attempt_id,
            allow_primary_attempt=allow_primary_attempt,
            replacement_collector_attempt_id=replacement_collector_attempt_id,
        )
    run_dir = core.safe_run_dir(run_dir)
    submission = _strict_dir(
        run_dir, f"submissions/fire-pilot/{primary_attempt_id}"
    )
    request_path = _strict_regular(submission, "request.json")
    primary_result_path = _strict_regular(submission, "primary_result.json")
    collector_request_path = _strict_regular(submission, "collector_request.json")
    collector_result_path = _strict_regular(submission, "collector_result.json")
    attachment_path = _strict_regular(submission, "collector_attachment.json")
    release_candidate = submission / "primary_release.json"
    if os.path.lexists(release_candidate):
        release_path: Path | None = _strict_regular(submission, "primary_release.json")
    elif require_release_receipt:
        raise core.CampaignError("FIRE held-primary release receipt is missing")
    else:
        release_path = None
    request = core.load_json(request_path)
    primary_result = core.load_json(primary_result_path)
    collector_request = core.load_json(collector_request_path)
    collector_result = core.load_json(collector_result_path)
    attachment = core.load_json(attachment_path)
    release = core.load_json(release_path) if release_path is not None else None
    from submit import SLURM_DIR as SUBMIT_SLURM_DIR, StagePlan, sbatch_command
    expected_primary_exports = {
        "CAMPAIGN_CONFIG": str(config_path),
        "RUN_DIR": str(run_dir),
        "ATTEMPT_ID": primary_attempt_id,
        "P3_SLURM_DIR": str(SUBMIT_SLURM_DIR),
        "P3_EXPECTED_CONFIG_SHA256": validation["config_sha256"],
        "P3_SUBMIT_SCRIPT_SHA256": core.sha256_path(Path(__file__).resolve().with_name("submit.py")),
        "P3_STAGE_SCRIPT_SHA256": core.sha256_path(SUBMIT_SLURM_DIR / "fire_pilot.sbatch"),
        "P3_CLUSTER_ENV_SHA256": core.sha256_path(SUBMIT_SLURM_DIR / "cluster.env"),
        "P3_CAMPAIGN_CLI_SHA256": core.sha256_path(Path(__file__).resolve().with_name("campaign.py")),
        "P3_FIRE_RECOVERY_SHA256": core.sha256_path(Path(__file__).resolve()),
        "P3_FIRE_LINEAGE_SHA256": ready["lineage_sha256"],
        "P3_FIRE_RELEASE_SHA256": ready["release_sha256"],
        "P3_GIT_COMMIT": ready["git_commit"],
        "P3_FIRE_REQUESTED_WALLTIME_MINUTES": "120",
    }
    if replacement_authorization_sha256 is not None:
        expected_primary_exports["P3_FIRE_REPLACEMENT_SHA256"] = (
            replacement_authorization_sha256
        )
    expected_primary_plan = StagePlan(
        stage="fire-pilot",
        script=(SUBMIT_SLURM_DIR / "fire_pilot.sbatch").resolve(),
        account=core.required(config, "scheduler.slurm_account"),
        exports=expected_primary_exports,
        array=None, task_count=None, task_map=None, task_map_sha256=None,
        scheduler_options=(
            "--partition=cpubase_bycore_b2", "--nodes=1", "--ntasks=32",
            "--cpus-per-task=1", "--mem-per-cpu=2000M", "--time=02:00:00",
        ),
    )
    expected_primary_command = sbatch_command(expected_primary_plan)
    expected_collector_exports = dict(expected_primary_exports)
    expected_collector_exports.update(
        {
            "ATTEMPT_ID": str(collector_result.get("attempt_id", "")),
            "PRIMARY_STAGE": "fire-pilot",
            "PRIMARY_ATTEMPT_ID": primary_attempt_id,
            "PRIMARY_JOB_ID": primary_job_id,
            "PRIMARY_REQUEST_SHA256": core.sha256_path(request_path),
            "PRIMARY_RESULT_SHA256": core.sha256_path(primary_result_path),
            "PRIMARY_STAGE_SCRIPT_SHA256": expected_primary_exports["P3_STAGE_SCRIPT_SHA256"],
            "P3_STAGE_SCRIPT_SHA256": core.sha256_path(SUBMIT_SLURM_DIR / "collect.sbatch"),
        }
    )
    expected_collector_command = sbatch_command(
        StagePlan(
            stage="collect", script=(SUBMIT_SLURM_DIR / "collect.sbatch").resolve(),
            account=core.required(config, "scheduler.slurm_account"),
            exports=expected_collector_exports, array=None, task_count=None,
            task_map=None, task_map_sha256=None,
        ),
        dependency=f"afterany:{primary_job_id}",
    )
    attachment_keys = {
        "schema_version", "kind", "primary_attempt_id", "primary_job_id",
        "primary_request_sha256", "primary_result_sha256",
        "collector_attempt_id", "collector_job_id",
        "collector_request_sha256", "collector_result_sha256",
        "collector_dependency", "primary_command", "collector_command",
        "release_command", "config_sha256", "fire_lineage_sha256",
        "fire_release_sha256", "workflow_sha256",
    }
    if replacement_authorization_sha256 is not None:
        attachment_keys.add("fire_replacement_sha256")
    collector_attempt_id = str(collector_result.get("attempt_id", ""))
    collector_job_id = str(collector_result.get("job_id", ""))
    collector_stderr = collector_result.get("stderr")
    allowed_collector_stderr = (
        ("", _NIBI_4G_MEMORY_NOTE)
        if replacement_authorization_sha256 is not None
        else ("",)
    )
    release_command = ["scontrol", "release", primary_job_id]
    primary_command = request.get("command")
    collector_command = collector_request.get("command")
    if set(attachment) != attachment_keys or (
        attachment.get("schema_version") != 1
        or attachment.get("kind") != "fire_pilot_afterany_collector_attachment"
        or attachment.get("primary_attempt_id") != primary_attempt_id
        or str(attachment.get("primary_job_id")) != primary_job_id
        or attachment.get("primary_request_sha256") != core.sha256_path(request_path)
        or attachment.get("primary_result_sha256") != core.sha256_path(primary_result_path)
        or attachment.get("collector_attempt_id") != collector_attempt_id
        or str(attachment.get("collector_job_id")) != collector_job_id
        or attachment.get("collector_request_sha256") != core.sha256_path(collector_request_path)
        or attachment.get("collector_result_sha256") != core.sha256_path(collector_result_path)
        or attachment.get("collector_dependency") != f"afterany:{primary_job_id}"
        or attachment.get("primary_command") != expected_primary_command
        or attachment.get("collector_command") != expected_collector_command
        or attachment.get("release_command") != release_command
        or attachment.get("config_sha256") != validation["config_sha256"]
        or attachment.get("fire_lineage_sha256") != ready["lineage_sha256"]
        or attachment.get("fire_release_sha256") != ready["release_sha256"]
        or attachment.get("fire_replacement_sha256")
        != replacement_authorization_sha256
        or attachment.get("workflow_sha256") != request.get("workflow_sha256")
        or request.get("fire_replacement_sha256")
        != replacement_authorization_sha256
        or primary_result.get("fire_replacement_sha256")
        != replacement_authorization_sha256
        or collector_request.get("fire_replacement_sha256")
        != replacement_authorization_sha256
        or collector_result.get("fire_replacement_sha256")
        != replacement_authorization_sha256
    ):
        raise core.CampaignError("FIRE collector attachment exact binding drift")
    if (
        primary_command != expected_primary_command
        or collector_command != expected_collector_command
        or primary_result.get("command") != expected_primary_command
        or primary_result.get("returncode") != 0
        or not _sbatch_stdout_matches_job(primary_result.get("stdout"), primary_job_id)
        or primary_result.get("stderr") != ""
        or str(primary_result.get("job_id")) != primary_job_id
        or collector_request.get("dependency") != f"afterany:{primary_job_id}"
        or collector_result.get("command") != expected_collector_command
        or collector_result.get("returncode") != 0
        or not _sbatch_stdout_matches_job(collector_result.get("stdout"), collector_job_id)
        or not isinstance(collector_stderr, str)
        or collector_stderr not in allowed_collector_stderr
        or collector_result.get("primary_attempt_id") != primary_attempt_id
        or str(collector_result.get("primary_job_id")) != primary_job_id
        or not collector_job_id.isdigit()
    ):
        raise core.CampaignError("FIRE primary/collector acceptance evidence drift")
    if release is not None:
        release_keys = {
            "command", "returncode", "stdout", "stderr", "finished_utc",
            "primary_attempt_id", "primary_job_id", "collector_attachment_sha256",
        }
        if replacement_authorization_sha256 is not None:
            release_keys.add("fire_replacement_sha256")
        if set(release) != release_keys or (
            release.get("command") != release_command
            or release.get("returncode") != 0
            or release.get("primary_attempt_id") != primary_attempt_id
            or str(release.get("primary_job_id")) != primary_job_id
            or release.get("collector_attachment_sha256") != core.sha256_path(attachment_path)
            or release.get("fire_replacement_sha256")
            != replacement_authorization_sha256
        ):
            raise core.CampaignError("FIRE held-primary release evidence is missing or invalid")
    if primary_job_id == collector_job_id:
        raise core.CampaignError("FIRE primary and collector job IDs must differ")
    return {
        "primary_job_id": primary_job_id,
        "collector_job_id": collector_job_id,
        "collector_attachment_sha256": core.sha256_path(attachment_path),
        "primary_release_sha256": (
            core.sha256_path(release_path) if release_path is not None else None
        ),
    }


def _runtime_context(config_path: Path, run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    core.require_compute_node()
    run_dir = core.safe_run_dir(run_dir)
    attempt = core.attempt_dir(run_dir)
    if attempt.parent != run_dir / "slurm_attempts/fire-pilot":
        raise core.CampaignError("FIRE pilot attempt is outside the exact stage root")
    replacement_sha256 = os.environ.get("P3_FIRE_REPLACEMENT_SHA256") or None
    if replacement_sha256 is None:
        ready = verify_fire_submission_ready(
            config_path, run_dir, "fire-pilot", require_unused=False
        )
    else:
        ready = verify_infrastructure_replacement_authorization(
            config_path,
            run_dir,
            require_unused=False,
            expected_authorization_sha256=replacement_sha256,
            replacement_attempt_id=attempt.name,
            allow_primary_attempt=True,
        )
    context = _context_fields(_strict_regular(run_dir, str((attempt / "context.tsv").relative_to(run_dir))))
    expected = {
        "stage": "fire-pilot",
        "attempt_id": attempt.name,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "run_dir": str(run_dir),
        "config_sha256": ready["config_sha256"],
        "fire_lineage_sha256": ready["lineage_sha256"],
        "fire_release_sha256": ready["release_sha256"],
        "fire_backend_sha256": core.sha256_path(Path(__file__).resolve()),
        "git_commit": ready["git_commit"],
    }
    if replacement_sha256 is not None:
        expected["fire_replacement_sha256"] = replacement_sha256
    for key, value in expected.items():
        if context.get(key) != value:
            raise core.CampaignError(f"FIRE pilot wrapper context mismatch: {key}")
    if (
        context.get("slurm_job_account") != core.required(core.validate_config(config_path)[0], "scheduler.slurm_account")
        or context.get("slurm_job_partition") != "cpubase_bycore_b2"
        or context.get("slurm_job_num_nodes") != "1"
        or context.get("slurm_ntasks") != "32"
        or context.get("slurm_cpus_per_task") != "1"
        or context.get("slurm_mem_per_cpu") != "2000"
        or context.get("slurm_timelimit") not in {"", "02:00:00", "120"}
        or context.get("fire_requested_walltime_minutes") != "120"
        or context.get("stdenv_module") != "StdEnv/2023"
        or context.get("qe_module") != "quantumespresso/7.3.1"
        or context.get("qe_executable") != "pw.x"
        or context.get("qe_mpi_launcher") != "srun"
        or context.get("qe_nk") != "1"
        or context.get("omp_num_threads") != "1"
    ):
        raise core.CampaignError("FIRE pilot observed wrapper allocation drift")
    submission = _strict_dir(run_dir, f"submissions/fire-pilot/{attempt.name}")
    request = core.load_json(_strict_regular(submission, "request.json"))
    expected_workflow = _workflow_hashes()
    if (
        request.get("stage") != "fire-pilot"
        or request.get("attempt_id") != attempt.name
        or request.get("run_dir") != str(run_dir)
        or request.get("config") != str(config_path.resolve(strict=True))
        or request.get("config_sha256") != ready["config_sha256"]
        or request.get("fire_lineage_sha256") != ready["lineage_sha256"]
        or request.get("fire_release_sha256") != ready["release_sha256"]
        or request.get("fire_replacement_sha256") != replacement_sha256
        or request.get("git_commit") != ready["git_commit"]
        or request.get("scheduler_options") != ["--partition=cpubase_bycore_b2", "--nodes=1", "--ntasks=32", "--cpus-per-task=1", "--mem-per-cpu=2000M", "--time=02:00:00"]
        or request.get("workflow_sha256") != {
            "submit.py": expected_workflow["submit.py"],
            "campaign.py": expected_workflow["campaign.py"],
            "cluster.env": expected_workflow["slurm/cluster.env"],
            "fire_pilot.sbatch": expected_workflow["slurm/fire_pilot.sbatch"],
            "fire_recovery.py": expected_workflow["fire_recovery.py"],
        }
    ):
        raise core.CampaignError("FIRE pilot lacks its exact code-issued submission request")
    config, _ = core.validate_config(config_path.resolve(strict=True))
    return config, ready, attempt


def run_stage(config_path: Path, run_dir: Path, stage: str) -> dict[str, Any]:
    """Run the sole bounded pilot; full and every downstream stage stay locked."""
    if stage != "pilot":
        raise core.CampaignError("only the bounded FIRE pilot execution is released")
    config, ready, attempt = _runtime_context(config_path, run_dir)
    run_dir = core.safe_run_dir(run_dir)
    if any((attempt / name).exists() for name in ("fire.in", "fire.out", "fire.err", "fire.process.json", "execution.json")):
        raise core.CampaignError("FIRE pilot attempt already contains execution evidence")
    lineage = core.load_json(_strict_regular(run_dir, LINEAGE))
    frozen_pseudos = _verify_frozen_pseudopotentials(config, run_dir, lineage)
    pseudo_dir = _strict_dir(run_dir, "lineage_source/pseudopotentials")
    pseudo_hashes = core.pseudopotential_hashes(config, pseudo_dir)
    if any(
        pseudo_hashes[species]["sha256"] != frozen_pseudos[species]["sha256"]
        for species in frozen_pseudos
    ):
        raise core.CampaignError("FIRE runtime pseudopotential bytes differ from frozen lineage")
    seed_path = _strict_regular(core.safe_run_dir(run_dir), "fire_seed.in")
    generated = _input(config, seed_path.read_text(), pseudo_dir, "pilot")
    _validate_generated_input(config, generated, "pilot")
    scratch = attempt / "tmp-fire-pilot"
    if os.path.lexists(scratch):
        raise core.CampaignError("FIRE pilot requires fresh, absent QE scratch")
    core.write_immutable(attempt / "fire.in", generated)
    command = core.qe_command("fire.in")
    launch = {
        "schema_version": 1,
        "stage": "fire-pilot",
        "attempt_id": attempt.name,
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "config_sha256": ready["config_sha256"],
        "fire_lineage_sha256": ready["lineage_sha256"],
        "fire_release_sha256": ready["release_sha256"],
        "fire_seed_sha256": core.sha256_path(seed_path),
        "fire_input_sha256": core.sha256_path(attempt / "fire.in"),
        "pseudopotentials": pseudo_hashes,
        "command": command,
        "fresh_scratch": True,
        "nstep": 8,
        "max_seconds": 6300,
        "structure_accepted": False,
        "preflight_unlocked": False,
    }
    replacement_sha256 = os.environ.get("P3_FIRE_REPLACEMENT_SHA256") or None
    if replacement_sha256 is not None:
        launch["fire_replacement_sha256"] = replacement_sha256
    core.write_json_immutable(attempt / "launch.json", launch)
    process = core.run_process(command, attempt, attempt / "fire.out", attempt / "fire.err")
    execution = {
        **launch,
        "fire_output_sha256": core.sha256_path(attempt / "fire.out"),
        "fire_stderr_sha256": core.sha256_path(attempt / "fire.err"),
        "process_record_sha256": core.sha256_path(attempt / "fire.process.json"),
        "process": process,
        "finished_utc": core.utc_now(),
    }
    core.write_json_immutable(attempt / "execution.json", execution)
    return execution


def _fatal_output_errors(text: str) -> list[str]:
    checks = (
        (r"(?i)Error in routine", "QE Error in routine"),
        (r"%{6,}", "QE fatal banner"),
        (r"(?i)(?:out of memory|oom-kill|oom killer|cannot allocate memory)", "out-of-memory marker"),
        (r"(?i)(?:segmentation fault|sig(?:term|kill|segv)|killed by signal)", "fatal signal marker"),
        (r"(?i)(?:maximum cpu time exceeded|fire[^\n]*(?:failed|fatal|error))", "abnormal FIRE/runtime termination marker"),
        (r"(?i)(?<![A-Za-z])(?:nan|inf)(?![A-Za-z])", "non-finite numeric marker"),
    )
    return [label for pattern, label in checks if re.search(pattern, text)]


def _sbatch_stdout_matches_job(stdout: object, job_id: str) -> bool:
    return isinstance(stdout, str) and re.fullmatch(
        rf"{re.escape(job_id)}(?:;[^\s;]+)?\n", stdout
    ) is not None


def _pilot_trajectory(output_path: Path, seed_path: Path, expected_atoms: int) -> dict[str, Any]:
    text = output_path.read_text(errors="replace")
    starts = list(RUN_START.finditer(text))
    run_text = text[starts[-1].start():] if starts else text
    records = _force_records(run_text)
    errors = _fatal_output_errors(run_text)
    version_header = PWSCF_VERSION_HEADER.match(run_text) if starts else None
    pwscf_7p3p1 = version_header is not None and version_header.group(1) == "7.3.1"
    if not starts:
        errors.append("missing explicit Program PWSCF main-run header")
    elif version_header is None:
        errors.append("last Program PWSCF main-run header is malformed")
    elif version_header.group(1) != "7.3.1":
        errors.append(
            f"last Program PWSCF main run used unsupported QE version {version_header.group(1)}"
        )
    headers = list(FORCE_HEADER.finditer(run_text))
    if len(records) != 8:
        errors.append(f"expected exactly 8 complete FIRE force steps; found {len(records)}")
    if len(headers) != len(records):
        errors.append("incomplete main force block is present")
    previous_end = 0
    for index, located in enumerate(records, 1):
        if len(located.record.forces_ry_bohr) != expected_atoms:
            errors.append(f"FIRE step {index} force atom count mismatch")
        prefix = run_text[previous_end:located.header_start]
        achieved = prefix.rfind("convergence has been achieved")
        failed = prefix.rfind("convergence NOT achieved")
        if achieved < 0 or failed > achieved:
            errors.append(f"FIRE step {index} lacks a successful SCF convergence marker")
        previous_end = located.block_end
    if "convergence NOT achieved" in run_text[previous_end:]:
        errors.append("non-converged SCF follows the last complete force block")
    if "convergence has been achieved" in run_text[previous_end:]:
        errors.append("later SCF cycle has no complete force block")
    final_begins = [match.start() for match in re.finditer(r"(?m)^\s*Begin final coordinates\s*$", run_text)]
    final_ends = [match.end() for match in re.finditer(r"(?m)^\s*End final coordinates\s*$", run_text)]
    final_coordinates_after_trajectory = (
        len(final_begins) == 1
        and len(final_ends) == 1
        and bool(records)
        and records[-1].block_end < final_begins[0] < final_ends[0]
    )
    job_done = run_text.find("JOB DONE", final_ends[0] if final_ends else 0)
    if job_done >= 0 and final_ends and final_ends[0] >= job_done:
        final_coordinates_after_trajectory = False
    if not final_coordinates_after_trajectory:
        errors.append(
            "selected final coordinates are not one unique block after the eighth force step"
        )
    seed = parse_qe_input(seed_path.read_text())
    final = extract_final_coordinates(run_text, expected_atoms=expected_atoms)
    labels = [item.label for item in final.atomic_positions]
    seed_labels = [item.label for item in seed.atomic_positions]
    order_unchanged = labels == seed_labels
    if not order_unchanged:
        errors.append("final atom order/species differs from frozen seed")
    cell = final.cell_parameters or seed.cell_parameters
    cell_unchanged = all(
        math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-8)
        for left_row, right_row in zip(seed.cell_parameters, cell)
        for left, right in zip(left_row, right_row)
    )
    if not cell_unchanged:
        errors.append("fixed FIRE cell changed")
    final_for_positions = type(final)(
        final.position_unit,
        final.atomic_positions,
        None,
        None,
        None,
    )
    final_input = replace_qe_geometry(seed.text, final_for_positions, require_cell=False)
    shifts = core._position_shifts_angstrom(seed.text, final_input)
    symmetry = core.symmetry_scan(
        cell,
        [item.coordinates for item in final.atomic_positions],
        labels,
        [1e-6],
    )
    ibam = len(symmetry) == 1 and symmetry[0].get("spacegroup_number") == 72
    if not ibam:
        errors.append("final structure is not Ibam No.72 at 1e-6 angstrom")
    forces = [located.record.max_abs_ry_bohr for located in records]
    initial_force = forces[0] if forces else math.inf
    final_force = forces[-1] if forces else math.inf
    checks = {
        "last_main_run_is_pwscf_7p3p1": pwscf_7p3p1,
        "eight_complete_force_steps": len(records) == 8 and len(headers) == len(records),
        "final_coordinates_follow_eighth_force_step": final_coordinates_after_trajectory,
        "all_scf_converged": not any("SCF" in item for item in errors),
        "no_fatal_nan_or_oom": not _fatal_output_errors(run_text),
        "cell_unchanged": cell_unchanged,
        "atom_order_unchanged": order_unchanged,
        "final_max_component_below_initial": final_force < initial_force,
        "final_max_component_le_1e-4_Ry_per_bohr": final_force <= 1e-4,
        "cumulative_shift_le_0p02A": bool(shifts) and max(shifts) <= 0.02,
        "Ibam_at_1e-6A": ibam,
    }
    return {
        "checks": checks,
        "errors": errors,
        "force_step_count": len(records),
        "max_force_component_by_step_ry_bohr": forces,
        "initial_max_force_component_ry_bohr": initial_force,
        "final_max_force_component_ry_bohr": final_force,
        "per_atom_cumulative_shift_angstrom": shifts,
        "maximum_cumulative_shift_angstrom": max(shifts) if shifts else None,
        "spacegroup_scan": symmetry,
        "final_unitcell_text": final_input,
    }


def collect_pilot_evidence(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    run_dir: Path,
    current_attempt: Path,
    primary_attempt_id: str,
    primary_job_id: str,
    expected_primary_request_sha256: str,
    expected_primary_result_sha256: str,
    expected_primary_stage_script_sha256: str,
    accounting_records: Sequence[Mapping[str, str]],
    accounting_errors: Sequence[str],
    accounting_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect raw pilot evidence only; never interpret or finalize it."""
    provenance_integrity_errors = [
        error
        for error in accounting_errors
        if not error.startswith(("missing scheduler accounting:", "missing sacct exit-code record:", "sacct exited with code "))
    ]
    execution_incomplete_reasons: list[str] = [
        error for error in accounting_errors if error not in provenance_integrity_errors
    ]
    config_path = config_path.resolve(strict=True)
    lineage_path = _strict_regular(run_dir, LINEAGE)
    release_path = _strict_regular(run_dir, PILOT_RELEASE)
    submission_dir = _strict_dir(run_dir, f"submissions/fire-pilot/{primary_attempt_id}")
    request_path = _strict_regular(submission_dir, "request.json")
    result_path = _strict_regular(submission_dir, "primary_result.json")
    for label, expected, path in (
        ("primary request", expected_primary_request_sha256, request_path),
        ("primary result", expected_primary_result_sha256, result_path),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", expected or "") is None or core.sha256_path(path) != expected:
            raise core.CampaignError(f"FIRE collector {label} hash mismatch")
    request, result = core.load_json(request_path), core.load_json(result_path)
    replacement_sha256 = request.get("fire_replacement_sha256")
    if replacement_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", str(replacement_sha256)) is None:
            raise core.CampaignError(
                "FIRE collector replacement authorization hash is invalid"
            )
        verify_infrastructure_replacement_authorization(
            config_path,
            run_dir,
            require_unused=False,
            expected_authorization_sha256=str(replacement_sha256),
            replacement_attempt_id=primary_attempt_id,
            allow_primary_attempt=True,
            replacement_collector_attempt_id=current_attempt.name,
        )
    if (
        request.get("stage") != "fire-pilot"
        or request.get("attempt_id") != primary_attempt_id
        or request.get("run_dir") != str(run_dir)
        or request.get("config") != str(config_path)
        or request.get("config_sha256") != core.sha256_path(config_path)
        or request.get("fire_lineage_sha256") != core.sha256_path(lineage_path)
        or request.get("fire_release_sha256") != core.sha256_path(release_path)
        or request.get("git_commit") != _git_commit()
        or request.get("stage_script_sha256") != expected_primary_stage_script_sha256
        or request.get("slurm_account") != core.required(config, "scheduler.slurm_account")
    ):
        raise core.CampaignError("FIRE primary submission request identity/hash mismatch")
    if (
        result.get("stage") != "fire-pilot"
        or result.get("attempt_id") != primary_attempt_id
        or str(result.get("job_id")) != primary_job_id
        or result.get("config_sha256") != request.get("config_sha256")
        or result.get("returncode") != 0
    ):
        raise core.CampaignError("FIRE primary submission result identity mismatch")
    wrapper = run_dir / "slurm_attempts/fire-pilot" / primary_attempt_id
    if wrapper.is_dir() and not wrapper.is_symlink():
        wrapper = _strict_dir(run_dir, f"slurm_attempts/fire-pilot/{primary_attempt_id}")
        context = _context_fields(_strict_regular(wrapper, "context.tsv"))
    else:
        context = {}
        execution_incomplete_reasons.append(
            "FIRE wrapper attempt is missing (startup failure before p3_begin_attempt)"
        )
    workflow = request.get("workflow_sha256") if isinstance(request.get("workflow_sha256"), Mapping) else {}
    expected_context = {
        "stage": "fire-pilot", "attempt_id": primary_attempt_id,
        "slurm_job_id": primary_job_id, "run_dir": str(run_dir),
        "config_sha256": request.get("config_sha256"),
        "fire_lineage_sha256": core.sha256_path(lineage_path),
        "fire_release_sha256": core.sha256_path(release_path),
        "fire_backend_sha256": workflow.get("fire_recovery.py"),
        "git_commit": request.get("git_commit"),
        "fire_requested_walltime_minutes": "120",
    }
    if replacement_sha256 is not None:
        expected_context["fire_replacement_sha256"] = str(replacement_sha256)
    for key, expected in expected_context.items():
        if context.get(key) != str(expected):
            if wrapper.is_dir():
                raise core.CampaignError(f"FIRE wrapper context mismatch for {key}")
    if (
        context.get("slurm_job_account") != core.required(config, "scheduler.slurm_account")
        or context.get("slurm_job_partition") != "cpubase_bycore_b2"
        or context.get("slurm_job_num_nodes") != "1"
        or context.get("slurm_ntasks") != "32"
        or context.get("slurm_cpus_per_task") != "1"
        or context.get("slurm_mem_per_cpu") != "2000"
        or context.get("slurm_timelimit") not in {"", "02:00:00", "120"}
        or context.get("fire_time_limit_source") not in {"native_slurm_timelimit", "submitted_request_export"}
        or context.get("stdenv_module") != "StdEnv/2023"
        or context.get("qe_module") != "quantumespresso/7.3.1"
        or context.get("qe_executable") != "pw.x"
        or context.get("qe_mpi_launcher") != "srun"
        or context.get("qe_nk") != "1"
        or context.get("omp_num_threads") != "1"
    ):
        if wrapper.is_dir():
            raise core.CampaignError(
                "FIRE wrapper allocation context differs from exact released resources"
            )
    for context_key, workflow_key in (
        ("submit_script_sha256", "submit.py"), ("campaign_cli_sha256", "campaign.py"),
        ("cluster_env_sha256", "cluster.env"), ("stage_script_sha256", "fire_pilot.sbatch"),
    ):
        if context.get(context_key) != workflow.get(workflow_key):
            if wrapper.is_dir():
                raise core.CampaignError(
                    f"FIRE wrapper workflow mismatch for {workflow_key}"
                )
    exit_code = None
    finished_valid = False
    if wrapper.is_dir():
        exit_path = wrapper / "exit_code.txt"
        if os.path.lexists(exit_path):
            try:
                exit_code = int(_strict_regular(wrapper, "exit_code.txt").read_text().strip())
            except (OSError, ValueError, core.CampaignError) as exc:
                raise core.CampaignError(f"invalid FIRE wrapper exit-code evidence: {exc}") from exc
        else:
            execution_incomplete_reasons.append("FIRE wrapper exit code is missing")
        finished_path = wrapper / "finished_utc.txt"
        if os.path.lexists(finished_path):
            finished = _strict_regular(wrapper, "finished_utc.txt").read_text()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\n", finished) is None:
                raise core.CampaignError("malformed FIRE wrapper finished-UTC evidence")
            finished_valid = True
        else:
            execution_incomplete_reasons.append("FIRE wrapper finished-UTC receipt is missing")
    related = [
        dict(row) for row in accounting_records
        if row.get("JobIDRaw") == primary_job_id
        or str(row.get("JobIDRaw", "")).startswith(primary_job_id + ".")
    ]
    allocations = [row for row in related if row.get("JobIDRaw") == primary_job_id]
    allocation = allocations[0] if len(allocations) == 1 else None
    if len(allocations) != 1:
        execution_incomplete_reasons.append(
            f"expected one FIRE sacct allocation row for {primary_job_id}; found {len(allocations)}"
        )
    allocation_matches = False
    resources = _policy(config)["resources"]
    if allocation is not None:
        try:
            from campaign import _diagnostic_reqmem_total_mb, _normalized_slurm_state
            allocated_cpus = int(allocation["AllocCPUS"])
            nodes = int(allocation["NNodes"])
            total_mb = _diagnostic_reqmem_total_mb(
                allocation["ReqMem"], allocated_cpus=allocated_cpus, nodes=nodes
            )
            allocation_matches = (
                allocation["Account"] == core.required(config, "scheduler.slurm_account")
                and allocation["Partition"] == resources["partition"]
                and nodes == 1 and allocated_cpus == 32 and int(allocation["NCPUS"]) == 32
                and int(allocation["TimelimitRaw"]) == 120
                and 0 <= int(allocation["ElapsedRaw"]) <= 7200
                and math.isclose(total_mb, 64000, rel_tol=0, abs_tol=0.01)
            )
            scheduler_success = (
                _normalized_slurm_state(allocation.get("State", "")) == "COMPLETED"
                and allocation.get("ExitCode") == "0:0"
            )
        except (KeyError, TypeError, ValueError, core.CampaignError):
            scheduler_success = False
    else:
        scheduler_success = False
    if allocation is not None and not allocation_matches:
        raise core.CampaignError("FIRE sacct allocation differs from exact released resources")
    if allocation is not None and not scheduler_success:
        execution_incomplete_reasons.append(
            "FIRE scheduler allocation did not finish COMPLETED with ExitCode 0:0"
        )
    if exit_code not in {None, 0}:
        execution_incomplete_reasons.append(
            f"FIRE wrapper exited nonzero ({exit_code})"
        )
    evidence: dict[str, Any] = {}
    if wrapper.is_dir():
        for name in ("context.tsv", "exit_code.txt", "finished_utc.txt", "launch.json", "fire.in", "fire.out", "fire.err", "fire.process.json", "execution.json", "stdout.log", "stderr.log"):
            path = wrapper / name
            if path.is_file():
                evidence[name] = {"sha256": core.sha256_path(path), "bytes": path.stat().st_size}
    integrity = not provenance_integrity_errors
    complete = integrity and scheduler_success and exit_code == 0 and finished_valid
    collection = {
        "schema_version": 1,
        "stage": "collect",
        "collection_kind": "fire_pilot_single_attempt",
        "material": core.required(config, "material.formula"),
        "collected_utc": core.utc_now(),
        "collector_attempt": str(current_attempt),
        "submission": {"record_dir": str(submission_dir), "request_sha256": core.sha256_path(request_path), "primary_result_sha256": core.sha256_path(result_path)},
        "primary": {"stage": "fire-pilot", "attempt_id": primary_attempt_id, "job_id": primary_job_id, "wrapper_attempt": str(wrapper), "scheduler_accounting": dict(accounting_metadata)},
        "entry": {
            "context": context,
            "wrapper_exit_code": exit_code,
            "scheduler_records": related,
            "allocation": dict(allocation) if allocation else None,
            "evidence": evidence,
            "provenance_integrity_errors": provenance_integrity_errors,
            "execution_incomplete_reasons": execution_incomplete_reasons,
            "errors": provenance_integrity_errors + execution_incomplete_reasons,
        },
        "collection_integrity_complete": integrity,
        "scheduler_completed_successfully": scheduler_success,
        "wrapper_completed_successfully": exit_code == 0 and finished_valid,
        "pilot_execution_complete": complete,
        "incomplete": not complete,
        "scientific_gate_published": False,
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
    }
    if replacement_sha256 is not None:
        collection["fire_replacement_sha256"] = str(replacement_sha256)
    return collection


def _global_job_id_counts(run_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    root = _strict_dir(run_dir, "submissions")
    core.reject_symlinks_below(run_dir, root, "FIRE submission inventory")
    for path in root.rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            raise core.CampaignError("submission inventory contains a symlink or non-file")
        if path.name not in {"primary_result.json", "collector_result.json"}:
            continue
        value = core.load_json(path)
        job_id = str(value.get("job_id", ""))
        if not job_id.isdigit():
            raise core.CampaignError("submission inventory contains an invalid Slurm job ID")
        counts[job_id] = counts.get(job_id, 0) + 1
    return counts


def _validate_exact_frozen_pilot_input(
    config: Mapping[str, Any], run_dir: Path, input_text: str
) -> None:
    pseudo_dir = _strict_dir(run_dir, "lineage_source/pseudopotentials")
    seed_text = _strict_regular(run_dir, "fire_seed.in").read_text()
    expected = _input(config, seed_text, pseudo_dir, "pilot")
    if input_text != expected:
        raise core.CampaignError(
            "FIRE pilot input bytes differ from the exact frozen-seed/policy rebuild"
        )


def _validate_present_execution_provenance(
    config: Mapping[str, Any],
    run_dir: Path,
    wrapper: Path | None,
    request: Mapping[str, Any],
    primary_attempt_id: str,
    primary_job_id: str,
) -> dict[str, Any]:
    """Validate every existing execution artifact, including failed attempts.

    A job may fail before the wrapper or QE starts and still yield an honest
    negative pilot gate.  Once any launch artifact exists, however, its exact
    schema, identity and byte hashes are provenance and corruption is fatal.
    """
    if wrapper is None:
        return {"state": "startup_before_attempt", "process_returncode": None}
    names = (
        "launch.json", "fire.in", "fire.out", "fire.err",
        "fire.process.json", "execution.json",
    )
    present = {name for name in names if os.path.lexists(wrapper / name)}
    if not present:
        return {"state": "attempt_before_launch", "process_returncode": None}
    if present == {"fire.in"}:
        input_text = _strict_regular(wrapper, "fire.in").read_text()
        _validate_exact_frozen_pilot_input(config, run_dir, input_text)
        return {
            "state": "interrupted_before_launch_receipt",
            "process_returncode": None,
        }
    if not {"launch.json", "fire.in"}.issubset(present):
        raise core.CampaignError("partial FIRE launch provenance is invalid")
    launch_path = _strict_regular(wrapper, "launch.json")
    input_path = _strict_regular(wrapper, "fire.in")
    launch = core.load_json(launch_path)
    launch_keys = {
        "schema_version", "stage", "attempt_id", "slurm_job_id",
        "config_sha256", "fire_lineage_sha256", "fire_release_sha256",
        "fire_seed_sha256", "fire_input_sha256", "pseudopotentials",
        "command", "fresh_scratch", "nstep", "max_seconds",
        "structure_accepted", "preflight_unlocked",
    }
    replacement_sha256 = request.get("fire_replacement_sha256")
    if replacement_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", str(replacement_sha256)) is None:
            raise core.CampaignError("FIRE replacement authorization hash is invalid")
        launch_keys.add("fire_replacement_sha256")
    expected_command = ["srun", "pw.x", "-nk", "1", "-in", "fire.in"]
    if set(launch) != launch_keys or (
        launch.get("schema_version") != 1
        or launch.get("stage") != "fire-pilot"
        or launch.get("attempt_id") != primary_attempt_id
        or str(launch.get("slurm_job_id")) != primary_job_id
        or launch.get("config_sha256") != request.get("config_sha256")
        or launch.get("fire_lineage_sha256") != request.get("fire_lineage_sha256")
        or launch.get("fire_release_sha256") != request.get("fire_release_sha256")
        or launch.get("fire_replacement_sha256") != replacement_sha256
        or launch.get("fire_seed_sha256") != core.sha256_path(run_dir / "fire_seed.in")
        or launch.get("fire_input_sha256") != core.sha256_path(input_path)
        or launch.get("command") != expected_command
        or launch.get("fresh_scratch") is not True
        or launch.get("nstep") != 8
        or launch.get("max_seconds") != 6300
        or launch.get("structure_accepted") is not False
        or launch.get("preflight_unlocked") is not False
    ):
        raise core.CampaignError("FIRE launch exact schema/identity drift")
    pseudo = launch.get("pseudopotentials")
    expected_pseudo = core.required(config, "pseudopotentials.files")
    lineage = core.load_json(_strict_regular(run_dir, LINEAGE))
    frozen_pseudos = _verify_frozen_pseudopotentials(config, run_dir, lineage)
    if (
        not isinstance(pseudo, Mapping)
        or set(pseudo) != set(expected_pseudo)
        or any(
            not isinstance(pseudo.get(species), Mapping)
            or set(pseudo[species]) != {"file", "sha256"}
            or Path(str(pseudo[species].get("file", ""))).name != filename
            or Path(str(pseudo[species].get("file", ""))).parent
            != run_dir / "lineage_source/pseudopotentials"
            or pseudo[species].get("sha256") != frozen_pseudos[species]["sha256"]
            for species, filename in expected_pseudo.items()
        )
    ):
        raise core.CampaignError("FIRE launch pseudopotential provenance is invalid")
    input_text = input_path.read_text()
    _validate_exact_frozen_pilot_input(config, run_dir, input_text)
    process_artifacts = {"fire.out", "fire.err", "fire.process.json"}
    if {"fire.out", "fire.err"}.issubset(present) and "fire.process.json" not in present and "execution.json" not in present:
        return {"state": "interrupted_during_process", "process_returncode": None}
    if present.intersection(process_artifacts | {"execution.json"}) and not process_artifacts.issubset(present):
        raise core.CampaignError("partial FIRE process provenance is invalid")
    if not process_artifacts.issubset(present):
        return {"state": "launch_before_process", "process_returncode": None}
    output_path = _strict_regular(wrapper, "fire.out")
    stderr_path = _strict_regular(wrapper, "fire.err")
    process_path = _strict_regular(wrapper, "fire.process.json")
    process = core.load_json(process_path)
    if set(process) != {
        "command", "cwd", "started_utc", "finished_utc", "returncode",
        "stdout_sha256", "stderr_sha256",
    } or (
        process.get("command") != expected_command
        or process.get("cwd") != str(wrapper)
        or not isinstance(process.get("returncode"), int)
        or process.get("stdout_sha256") != core.sha256_path(output_path)
        or process.get("stderr_sha256") != core.sha256_path(stderr_path)
    ):
        raise core.CampaignError("FIRE process exact schema/identity drift")
    if "execution.json" not in present:
        return {
            "state": "failed_or_interrupted_before_execution_receipt",
            "process_returncode": process["returncode"],
        }
    execution_path = _strict_regular(wrapper, "execution.json")
    execution = core.load_json(execution_path)
    execution_keys = launch_keys | {
        "fire_output_sha256", "fire_stderr_sha256", "process_record_sha256",
        "process", "finished_utc",
    }
    if set(execution) != execution_keys or any(
        execution.get(key) != launch.get(key) for key in launch_keys
    ) or (
        execution.get("fire_output_sha256") != core.sha256_path(output_path)
        or execution.get("fire_stderr_sha256") != core.sha256_path(stderr_path)
        or execution.get("process_record_sha256") != core.sha256_path(process_path)
        or execution.get("process") != process
        or process.get("returncode") != 0
    ):
        raise core.CampaignError("FIRE execution exact schema/hash/identity drift")
    return {"state": "complete_receipt", "process_returncode": 0}


def replay_pilot(config_path: Path, run_dir: Path, collection_path: Path, *, expected_collection_sha256: str) -> dict[str, Any]:
    """Read-only, independent replay from raw QE and scheduler evidence."""
    config_path = config_path.resolve(strict=True)
    config, validation = core.validate_config(config_path)
    validate_fire_policy(config)
    run_dir = core.safe_run_dir(run_dir)
    lexical_collection = Path(os.path.abspath(collection_path))
    try:
        relative_collection = lexical_collection.relative_to(run_dir)
    except ValueError as exc:
        raise core.CampaignError("FIRE collection must be a strict RUN_DIR descendant") from exc
    collection_path = _strict_regular(run_dir, str(relative_collection))
    if re.fullmatch(r"[0-9a-f]{64}", expected_collection_sha256 or "") is None or core.sha256_path(collection_path) != expected_collection_sha256:
        raise core.CampaignError("FIRE collection SHA256 mismatch")
    collection = core.load_json(collection_path)
    replacement_sha256 = collection.get("fire_replacement_sha256")
    if replacement_sha256 is not None and re.fullmatch(
        r"[0-9a-f]{64}", str(replacement_sha256)
    ) is None:
        raise core.CampaignError("FIRE collection replacement hash is invalid")
    collection_keys = {
        "schema_version", "stage", "collection_kind", "material",
        "collected_utc", "collector_attempt", "submission", "primary", "entry",
        "collection_integrity_complete", "scheduler_completed_successfully",
        "wrapper_completed_successfully", "pilot_execution_complete", "incomplete",
        "scientific_gate_published", "structure_accepted", "preflight_unlocked",
        "full_execution_released",
    }
    if replacement_sha256 is not None:
        collection_keys.add("fire_replacement_sha256")
    if (
        set(collection) != collection_keys
        or collection.get("schema_version") != 1
        or collection.get("stage") != "collect"
        or collection.get("collection_kind") != "fire_pilot_single_attempt"
        or collection.get("material") != core.required(config, "material.formula")
        or collection.get("incomplete") is not (not collection.get("pilot_execution_complete"))
        or collection.get("structure_accepted") is not False
        or collection.get("preflight_unlocked") is not False
        or collection.get("full_execution_released") is not False
        or collection.get("scientific_gate_published") is not False
    ):
        raise core.CampaignError("invalid FIRE pilot collection schema/scope")
    primary = collection.get("primary")
    if not isinstance(primary, Mapping) or primary.get("stage") != "fire-pilot":
        raise core.CampaignError("FIRE collection lacks its exact primary identity")
    primary_attempt_id, primary_job_id = str(primary.get("attempt_id", "")), str(primary.get("job_id", ""))
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", primary_attempt_id) is None or not primary_job_id.isdigit():
        raise core.CampaignError("FIRE collection primary IDs are invalid")
    submission_dir = _strict_dir(run_dir, f"submissions/fire-pilot/{primary_attempt_id}")
    collector_request = core.load_json(_strict_regular(submission_dir, "collector_request.json"))
    collector_result = core.load_json(_strict_regular(submission_dir, "collector_result.json"))
    collector_request_path = _strict_regular(submission_dir, "collector_request.json")
    collector_result_path = _strict_regular(submission_dir, "collector_result.json")
    collector_request_keys = {
        "created_utc", "stage", "attempt_id", "slurm_account", "config_sha256",
        "primary_stage", "primary_attempt_id", "primary_job_id",
        "primary_request_sha256", "primary_result_sha256",
        "primary_stage_script_sha256", "collector_script_sha256",
        "submit_script_sha256", "cluster_env_sha256", "campaign_cli_sha256",
        "diagnostic_lineage_sha256", "diagnostic_resource_sha256",
        "diagnostic_requested_walltime_minutes", "fire_lineage_sha256",
        "fire_release_sha256", "fire_backend_sha256",
        "fire_requested_walltime_minutes", "git_commit", "dependency", "command",
    }
    collector_result_keys = {
        "command", "returncode", "stdout", "stderr", "finished_utc", "stage",
        "attempt_id", "job_id", "primary_stage", "primary_attempt_id",
        "primary_job_id", "config_sha256",
    }
    if replacement_sha256 is not None:
        collector_request_keys.add("fire_replacement_sha256")
        collector_result_keys.add("fire_replacement_sha256")
    if set(collector_request) != collector_request_keys or set(collector_result) != collector_result_keys:
        raise core.CampaignError("FIRE collector request/result exact schema drift")
    collector_attempt_id = str(collector_result.get("attempt_id", ""))
    collector_job_id = str(collector_result.get("job_id", ""))
    if replacement_sha256 is None:
        ready = verify_fire_submission_ready(
            config_path, run_dir, "fire-pilot", require_unused=False
        )
    else:
        ready = verify_infrastructure_replacement_authorization(
            config_path,
            run_dir,
            require_unused=False,
            expected_authorization_sha256=str(replacement_sha256),
            replacement_attempt_id=primary_attempt_id,
            allow_primary_attempt=True,
            replacement_collector_attempt_id=collector_attempt_id,
        )
    if (
        collector_request.get("stage") != "collect"
        or collector_request.get("attempt_id") != collector_attempt_id
        or collector_request.get("slurm_account") != core.required(config, "scheduler.slurm_account")
        or collector_request.get("primary_stage") != "fire-pilot"
        or collector_request.get("primary_attempt_id") != primary_attempt_id
        or str(collector_request.get("primary_job_id")) != primary_job_id
        or collector_request.get("dependency") != f"afterany:{primary_job_id}"
        or collector_request.get("config_sha256") != validation["config_sha256"]
        or collector_request.get("fire_lineage_sha256") != core.sha256_path(run_dir / LINEAGE)
        or collector_request.get("fire_release_sha256") != core.sha256_path(run_dir / PILOT_RELEASE)
        or collector_request.get("fire_replacement_sha256") != replacement_sha256
        or collector_request.get("git_commit") != _git_commit()
        or collector_request.get("fire_requested_walltime_minutes") != "120"
        or collector_request.get("primary_request_sha256") != core.sha256_path(submission_dir / "request.json")
        or collector_request.get("primary_result_sha256") != core.sha256_path(submission_dir / "primary_result.json")
        or collector_request.get("primary_stage_script_sha256") != core.sha256_path(Path(__file__).resolve().parent / "slurm/fire_pilot.sbatch")
        or collector_request.get("collector_script_sha256") != core.sha256_path(Path(__file__).resolve().parent / "slurm/collect.sbatch")
        or collector_request.get("submit_script_sha256") != core.sha256_path(Path(__file__).resolve().with_name("submit.py"))
        or collector_request.get("campaign_cli_sha256") != core.sha256_path(Path(__file__).resolve().with_name("campaign.py"))
        or collector_request.get("cluster_env_sha256") != core.sha256_path(Path(__file__).resolve().parent / "slurm/cluster.env")
        or collector_result.get("stage") != "collect"
        or collector_result.get("primary_stage") != "fire-pilot"
        or collector_result.get("primary_attempt_id") != primary_attempt_id
        or str(collector_result.get("primary_job_id")) != primary_job_id
        or collector_result.get("config_sha256") != validation["config_sha256"]
        or collector_result.get("fire_replacement_sha256") != replacement_sha256
        or collector_result.get("returncode") != 0
        or not collector_job_id.isdigit()
    ):
        raise core.CampaignError("FIRE collector request/result identity mismatch")
    primary_request_path = _strict_regular(submission_dir, "request.json")
    primary_result_path = _strict_regular(submission_dir, "primary_result.json")
    primary_request = core.load_json(primary_request_path)
    primary_result = core.load_json(primary_result_path)
    from submit import (
        SLURM_DIR as SUBMIT_SLURM_DIR,
        StagePlan,
        SubmissionContext,
        _request_record,
        sbatch_command,
    )
    expected_primary_exports = {
        "CAMPAIGN_CONFIG": str(config_path),
        "RUN_DIR": str(run_dir),
        "ATTEMPT_ID": primary_attempt_id,
        "P3_SLURM_DIR": str(SUBMIT_SLURM_DIR),
        "P3_EXPECTED_CONFIG_SHA256": validation["config_sha256"],
        "P3_SUBMIT_SCRIPT_SHA256": core.sha256_path(Path(__file__).resolve().with_name("submit.py")),
        "P3_STAGE_SCRIPT_SHA256": core.sha256_path(SUBMIT_SLURM_DIR / "fire_pilot.sbatch"),
        "P3_CLUSTER_ENV_SHA256": core.sha256_path(SUBMIT_SLURM_DIR / "cluster.env"),
        "P3_CAMPAIGN_CLI_SHA256": core.sha256_path(Path(__file__).resolve().with_name("campaign.py")),
        "P3_FIRE_RECOVERY_SHA256": core.sha256_path(Path(__file__).resolve()),
        "P3_FIRE_LINEAGE_SHA256": ready["lineage_sha256"],
        "P3_FIRE_RELEASE_SHA256": ready["release_sha256"],
        "P3_GIT_COMMIT": ready["git_commit"],
        "P3_FIRE_REQUESTED_WALLTIME_MINUTES": "120",
    }
    if replacement_sha256 is not None:
        expected_primary_exports["P3_FIRE_REPLACEMENT_SHA256"] = str(
            replacement_sha256
        )
    expected_primary_plan = StagePlan(
        stage="fire-pilot",
        script=(SUBMIT_SLURM_DIR / "fire_pilot.sbatch").resolve(),
        account=core.required(config, "scheduler.slurm_account"),
        exports=expected_primary_exports,
        array=None,
        task_count=None,
        task_map=None,
        task_map_sha256=None,
        scheduler_options=(
            "--partition=cpubase_bycore_b2", "--nodes=1", "--ntasks=32",
            "--cpus-per-task=1", "--mem-per-cpu=2000M", "--time=02:00:00",
        ),
    )
    expected_primary_command = sbatch_command(expected_primary_plan)
    expected_primary_request = _request_record(
        SubmissionContext(
            config_path=config_path,
            run_dir=run_dir,
            config=dict(config),
            manifest=dict(ready),
            config_sha256=validation["config_sha256"],
        ),
        expected_primary_plan,
        expected_primary_command,
    )
    expected_primary_request["created_utc"] = primary_request.get("created_utc")
    if replacement_sha256 is not None:
        expected_primary_request["fire_replacement_sha256"] = str(
            replacement_sha256
        )
    if primary_request != expected_primary_request:
        raise core.CampaignError("FIRE primary request exact schema/command drift")
    primary_result_keys = {
        "command", "returncode", "stdout", "stderr", "finished_utc", "stage",
        "attempt_id", "job_id", "config_sha256",
    }
    if replacement_sha256 is not None:
        primary_result_keys.add("fire_replacement_sha256")
    if set(primary_result) != primary_result_keys or (
        primary_result.get("command") != expected_primary_command
        or primary_result.get("returncode") != 0
        or not _sbatch_stdout_matches_job(primary_result.get("stdout"), primary_job_id)
        or primary_result.get("stderr") != ""
        or primary_result.get("stage") != "fire-pilot"
        or primary_result.get("attempt_id") != primary_attempt_id
        or str(primary_result.get("job_id")) != primary_job_id
        or primary_result.get("config_sha256") != validation["config_sha256"]
        or primary_result.get("fire_replacement_sha256") != replacement_sha256
    ):
        raise core.CampaignError("FIRE primary result exact schema/command drift")
    primary_command = primary_request.get("command")
    export_items = [item for item in primary_command if isinstance(item, str) and item.startswith("--export=")]
    if len(export_items) != 1:
        raise core.CampaignError("FIRE primary submission must have one exact export argument")
    primary_exports: dict[str, str] = {}
    for item in export_items[0][len("--export="):].split(","):
        if "=" not in item:
            raise core.CampaignError("FIRE primary export argument is malformed")
        name, value = item.split("=", 1)
        if not name or name in primary_exports:
            raise core.CampaignError("FIRE primary export argument has a duplicate/empty name")
        primary_exports[name] = value
    expected_exports = dict(primary_exports)
    expected_exports.update(
        {
            "ATTEMPT_ID": collector_attempt_id,
            "PRIMARY_STAGE": "fire-pilot",
            "PRIMARY_ATTEMPT_ID": primary_attempt_id,
            "PRIMARY_JOB_ID": primary_job_id,
            "PRIMARY_REQUEST_SHA256": core.sha256_path(submission_dir / "request.json"),
            "PRIMARY_RESULT_SHA256": core.sha256_path(submission_dir / "primary_result.json"),
            "PRIMARY_STAGE_SCRIPT_SHA256": str(primary_request.get("stage_script_sha256", "")),
            "P3_STAGE_SCRIPT_SHA256": core.sha256_path(Path(__file__).resolve().parent / "slurm/collect.sbatch"),
        }
    )
    expected_collector_command = sbatch_command(
        StagePlan(
            stage="collect",
            script=(Path(__file__).resolve().parent / "slurm/collect.sbatch").resolve(),
            account=core.required(config, "scheduler.slurm_account"),
            exports=expected_exports,
            array=None,
            task_count=None,
            task_map=None,
            task_map_sha256=None,
        ),
        dependency=f"afterany:{primary_job_id}",
    )
    if collector_request.get("command") != expected_collector_command or collector_result.get("command") != expected_collector_command:
        raise core.CampaignError("FIRE collector command/dependency/export reconstruction mismatch")
    collector_stderr = collector_result.get("stderr")
    allowed_collector_stderr = (
        ("", _NIBI_4G_MEMORY_NOTE)
        if replacement_sha256 is not None
        else ("",)
    )
    if (
        not _sbatch_stdout_matches_job(collector_result.get("stdout"), collector_job_id)
        or not isinstance(collector_stderr, str)
        or collector_stderr not in allowed_collector_stderr
    ):
        raise core.CampaignError("FIRE collector sbatch response bytes do not prove its exact job ID")
    attachment = verify_fire_collector_attachment(
        config_path, run_dir, primary_attempt_id, primary_job_id,
        require_release_receipt=False,
        replacement_authorization_sha256=(
            str(replacement_sha256) if replacement_sha256 is not None else None
        ),
        allow_primary_attempt=True,
        replacement_collector_attempt_id=collector_attempt_id,
    )
    submission_incomplete_reasons: list[str] = []
    if attachment["primary_release_sha256"] is None:
        submission_incomplete_reasons.append(
            "submitter stopped after scontrol release but before its result receipt"
        )
    summary_candidate = submission_dir / "submission.json"
    if os.path.lexists(summary_candidate):
        summary_path = _strict_regular(submission_dir, "submission.json")
        summary = core.load_json(summary_path)
        summary_collector = summary.get("collector")
        if (
            not isinstance(summary_collector, Mapping)
            or summary.get("fire_replacement_sha256") != replacement_sha256
            or summary_collector.get("request_sha256") != core.sha256_path(collector_request_path)
            or summary_collector.get("result_sha256") != core.sha256_path(collector_result_path)
            or summary_collector.get("command") != expected_collector_command
            or summary_collector.get("dependency") != f"afterany:{primary_job_id}"
            or str(summary_collector.get("job_id")) != collector_job_id
            or summary_collector.get("attachment_sha256")
            != attachment["collector_attachment_sha256"]
            or summary_collector.get("primary_release_sha256")
            != attachment["primary_release_sha256"]
        ):
            raise core.CampaignError("FIRE submission summary does not bind exact collector records")
    else:
        submission_incomplete_reasons.append(
            "submitter stopped after release receipt but before submission summary"
        )
    if Path(str(collection.get("collector_attempt", ""))) != run_dir / "slurm_attempts/collect" / collector_attempt_id:
        raise core.CampaignError("FIRE collection path/collector attempt mismatch")
    counts = _global_job_id_counts(run_dir)
    if primary_job_id == collector_job_id or counts.get(primary_job_id) != 1 or counts.get(collector_job_id) != 1:
        raise core.CampaignError("FIRE primary/collector Slurm job IDs are not globally unique")
    submission = collection.get("submission")
    if not isinstance(submission, Mapping):
        raise core.CampaignError("FIRE collection lacks submission hashes")
    request_path = _strict_regular(submission_dir, "request.json")
    result_path = _strict_regular(submission_dir, "primary_result.json")
    if submission.get("request_sha256") != core.sha256_path(request_path) or submission.get("primary_result_sha256") != core.sha256_path(result_path):
        raise core.CampaignError("FIRE collection submission hashes drifted")
    collector_attempt = _strict_dir(run_dir, f"slurm_attempts/collect/{collector_attempt_id}")
    collector_context = _context_fields(_strict_regular(collector_attempt, "context.tsv"))
    collector_workflow = {
        "submit_script_sha256": collector_request.get("submit_script_sha256"),
        "campaign_cli_sha256": collector_request.get("campaign_cli_sha256"),
        "cluster_env_sha256": collector_request.get("cluster_env_sha256"),
        "stage_script_sha256": collector_request.get("collector_script_sha256"),
    }
    collector_expected = {
        "stage": "collect", "attempt_id": collector_attempt_id,
        "slurm_job_id": collector_job_id, "run_dir": str(run_dir),
        "config_sha256": validation["config_sha256"],
        "primary_stage": "fire-pilot", "primary_attempt_id": primary_attempt_id,
        "primary_job_id": primary_job_id,
        "primary_request_sha256": collector_request.get("primary_request_sha256"),
        "primary_result_sha256": collector_request.get("primary_result_sha256"),
        "primary_stage_script_sha256": collector_request.get("primary_stage_script_sha256"),
        "fire_lineage_sha256": collector_request.get("fire_lineage_sha256"),
        "fire_release_sha256": collector_request.get("fire_release_sha256"),
        "fire_backend_sha256": collector_request.get("fire_backend_sha256"),
        "fire_requested_walltime_minutes": collector_request.get("fire_requested_walltime_minutes"),
        **collector_workflow,
    }
    if replacement_sha256 is not None:
        collector_expected["fire_replacement_sha256"] = str(replacement_sha256)
    for key, expected in collector_expected.items():
        if collector_context.get(key) != str(expected):
            raise core.CampaignError(f"FIRE collector wrapper context mismatch: {key}")
    if collection_path != collector_attempt / "collection.json":
        raise core.CampaignError("FIRE collection is not the exact collector attempt receipt")
    from campaign import DIAGNOSTIC_SACCT_FIELDS, _read_sacct_records
    records, accounting_errors, metadata = _read_sacct_records(
        _strict_regular(collector_attempt, "primary_sacct.psv"),
        _strict_regular(collector_attempt, "primary_sacct_exit_code.txt"),
        DIAGNOSTIC_SACCT_FIELDS,
    )
    replayed = collect_pilot_evidence(
        config=config, config_path=config_path, run_dir=run_dir, current_attempt=collector_attempt,
        primary_attempt_id=primary_attempt_id, primary_job_id=primary_job_id,
        expected_primary_request_sha256=str(collector_request.get("primary_request_sha256", "")),
        expected_primary_result_sha256=str(collector_request.get("primary_result_sha256", "")),
        expected_primary_stage_script_sha256=str(collector_request.get("primary_stage_script_sha256", "")),
        accounting_records=records, accounting_errors=accounting_errors, accounting_metadata=metadata,
    )
    replay_keys = (
        "submission", "primary", "entry", "collection_integrity_complete",
        "scheduler_completed_successfully", "wrapper_completed_successfully",
        "pilot_execution_complete", "incomplete",
    )
    if replacement_sha256 is not None:
        replay_keys += ("fire_replacement_sha256",)
    for key in replay_keys:
        if replayed.get(key) != collection.get(key):
            raise core.CampaignError(f"FIRE collector replay mismatch: {key}")
    entry = collection.get("entry")
    if not isinstance(entry, Mapping):
        raise core.CampaignError("FIRE collection entry provenance is missing")
    integrity_errors = entry.get("provenance_integrity_errors")
    incomplete_reasons = entry.get("execution_incomplete_reasons")
    if not isinstance(integrity_errors, list) or not isinstance(incomplete_reasons, list):
        raise core.CampaignError("FIRE collection does not separate provenance from execution failure")
    if integrity_errors or collection.get("collection_integrity_complete") is not True:
        raise core.CampaignError("FIRE collection contains provenance/integrity errors")
    wrapper_path = run_dir / "slurm_attempts/fire-pilot" / primary_attempt_id
    wrapper: Path | None
    if wrapper_path.is_dir() and not wrapper_path.is_symlink():
        wrapper = _strict_dir(run_dir, f"slurm_attempts/fire-pilot/{primary_attempt_id}")
        if primary.get("wrapper_attempt") != str(wrapper):
            raise core.CampaignError("FIRE collection wrapper path identity mismatch")
        recorded_evidence = entry.get("evidence")
        if not isinstance(recorded_evidence, Mapping):
            raise core.CampaignError("FIRE collection evidence inventory is invalid")
        for name, metadata in recorded_evidence.items():
            if not isinstance(name, str) or not isinstance(metadata, Mapping) or set(metadata) != {"sha256", "bytes"}:
                raise core.CampaignError("FIRE collection evidence inventory schema drift")
            evidence_path = _strict_regular(wrapper, name)
            if (
                metadata.get("sha256") != core.sha256_path(evidence_path)
                or metadata.get("bytes") != evidence_path.stat().st_size
            ):
                raise core.CampaignError(f"FIRE collected evidence bytes drifted: {name}")
    elif os.path.lexists(wrapper_path):
        raise core.CampaignError("FIRE wrapper attempt path is unsafe")
    else:
        wrapper = None
        if primary.get("wrapper_attempt") != str(wrapper_path):
            raise core.CampaignError("FIRE missing-wrapper path identity mismatch")
    execution_state = _validate_present_execution_provenance(
        config, run_dir, wrapper, primary_request, primary_attempt_id, primary_job_id
    )
    if collection.get("pilot_execution_complete") is True and execution_state.get("state") != "complete_receipt":
        raise core.CampaignError("FIRE collection claims completion without complete execution provenance")
    if collection.get("pilot_execution_complete") is not True or submission_incomplete_reasons:
        checks = {
            "collection_integrity_complete": collection.get("collection_integrity_complete") is True,
            "scheduler_completed_successfully": collection.get("scheduler_completed_successfully") is True,
            "wrapper_completed_successfully": collection.get("wrapper_completed_successfully") is True,
            "process_completed_successfully": False,
            "last_main_run_is_pwscf_7p3p1": False,
            "eight_complete_force_steps": False,
            "final_coordinates_follow_eighth_force_step": False,
            "all_scf_converged": False,
            "no_fatal_nan_or_oom": False,
            "cell_unchanged": False,
            "atom_order_unchanged": False,
            "final_max_component_below_initial": False,
            "final_max_component_le_1e-4_Ry_per_bohr": False,
            "cumulative_shift_le_0p02A": False,
            "Ibam_at_1e-6A": False,
        }
        report = {
            "schema_version": 1,
            "stage": "fire-pilot-review",
            "material": core.required(config, "material.formula"),
            "pass": False,
            "full_review_eligible": False,
            "checks": checks,
            "trajectory": None,
            "submission_incomplete_reasons": submission_incomplete_reasons,
            "config_sha256": validation["config_sha256"],
            "collection_sha256": expected_collection_sha256,
            "primary_job_id": primary_job_id,
            "collector_job_id": collector_job_id,
            "structure_accepted": False,
            "preflight_unlocked": False,
            "full_execution_released": False,
            "force_execution_released": False,
            "production_execution_released": False,
            "normal_fire_convergence_markers_required": False,
            "normal_fire_convergence_markers_scope": "future full FIRE only; the bounded pilot trend gate requires eight healthy complete force/SCF steps and terminal scheduler evidence",
        }
        if replacement_sha256 is not None:
            report["fire_replacement_sha256"] = str(replacement_sha256)
        return report
    if wrapper is None:  # pragma: no cover - guarded by completion assertion
        raise core.CampaignError("FIRE completed collection lacks wrapper attempt")
    launch = core.load_json(_strict_regular(wrapper, "launch.json"))
    execution = core.load_json(_strict_regular(wrapper, "execution.json"))
    process = core.load_json(_strict_regular(wrapper, "fire.process.json"))
    for key, filename in (
        ("fire_seed_sha256", None), ("fire_input_sha256", "fire.in"),
        ("fire_output_sha256", "fire.out"), ("fire_stderr_sha256", "fire.err"),
        ("process_record_sha256", "fire.process.json"),
    ):
        expected = core.sha256_path(run_dir / "fire_seed.in") if filename is None else core.sha256_path(wrapper / filename)
        if execution.get(key) != expected or (key in launch and launch.get(key) != expected):
            raise core.CampaignError(f"FIRE execution hash mismatch: {key}")
    if process != execution.get("process") or process.get("returncode") != 0 or process.get("command") != launch.get("command") or process.get("cwd") != str(wrapper):
        raise core.CampaignError("FIRE process/launch/execution identity mismatch")
    if process.get("stdout_sha256") != execution.get("fire_output_sha256") or process.get("stderr_sha256") != execution.get("fire_stderr_sha256"):
        raise core.CampaignError("FIRE process output hash mismatch")
    input_text = (wrapper / "fire.in").read_text()
    _validate_generated_input(config, input_text, "pilot")
    seed_parsed = parse_qe_input((run_dir / "fire_seed.in").read_text())
    input_parsed = parse_qe_input(input_text)
    if (
        input_parsed.cell_parameters != seed_parsed.cell_parameters
        or [item.label for item in input_parsed.atomic_positions] != [item.label for item in seed_parsed.atomic_positions]
        or [item.coordinates for item in input_parsed.atomic_positions] != [item.coordinates for item in seed_parsed.atomic_positions]
    ):
        raise core.CampaignError("FIRE pilot input geometry differs from the frozen seed")
    try:
        trajectory = _pilot_trajectory(wrapper / "fire.out", run_dir / "fire_seed.in", int(core.required(config, "material.unitcell_atoms")))
    except (core.CampaignError, OSError, ValueError) as exc:
        trajectory = {
            "checks": {
                "last_main_run_is_pwscf_7p3p1": False,
                "eight_complete_force_steps": False,
                "final_coordinates_follow_eighth_force_step": False,
                "all_scf_converged": False,
                "no_fatal_nan_or_oom": False,
                "cell_unchanged": False,
                "atom_order_unchanged": False,
                "final_max_component_below_initial": False,
                "final_max_component_le_1e-4_Ry_per_bohr": False,
                "cumulative_shift_le_0p02A": False,
                "Ibam_at_1e-6A": False,
            },
            "errors": [f"FIRE trajectory parse failed: {exc}"],
            "force_step_count": None,
        }
    combined_fatal = _fatal_output_errors(
        (wrapper / "fire.out").read_text(errors="replace")
        + "\n"
        + (wrapper / "fire.err").read_text(errors="replace")
    )
    if combined_fatal:
        trajectory["checks"]["no_fatal_nan_or_oom"] = False
        trajectory["errors"].extend(
            f"combined stdout/stderr: {message}" for message in combined_fatal
        )
    checks = {
        "collection_integrity_complete": collection.get("collection_integrity_complete") is True,
        "scheduler_completed_successfully": collection.get("scheduler_completed_successfully") is True,
        "wrapper_completed_successfully": collection.get("wrapper_completed_successfully") is True,
        "process_completed_successfully": process.get("returncode") == 0,
        **trajectory["checks"],
    }
    report = {
        "schema_version": 1,
        "stage": "fire-pilot-review",
        "material": core.required(config, "material.formula"),
        "pass": all(checks.values()) and not trajectory["errors"],
        "full_review_eligible": all(checks.values()) and not trajectory["errors"],
        "checks": checks,
        "trajectory": {key: value for key, value in trajectory.items() if key != "final_unitcell_text"},
        "config_sha256": validation["config_sha256"],
        "collection_sha256": expected_collection_sha256,
        "primary_job_id": primary_job_id,
        "collector_job_id": collector_job_id,
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
        "force_execution_released": False,
        "production_execution_released": False,
        "normal_fire_convergence_markers_required": False,
        "normal_fire_convergence_markers_scope": "future full FIRE only; the bounded pilot trend gate requires eight healthy complete force/SCF steps and terminal scheduler evidence",
    }
    if replacement_sha256 is not None:
        report["fire_replacement_sha256"] = str(replacement_sha256)
    return report


def finalize_stage(config_path: Path, run_dir: Path, stage: str, collection_path: Path | None = None, *, expected_collection_sha256: str = "") -> dict[str, Any]:
    if stage != "pilot":
        raise core.CampaignError("FIRE full finalization is not released")
    if collection_path is None:
        raise core.CampaignError("FIRE pilot finalization requires the exact collection receipt")
    run_dir = core.safe_run_dir(run_dir)
    report = replay_pilot(config_path, run_dir, collection_path, expected_collection_sha256=expected_collection_sha256)
    core.write_json_immutable(run_dir / PILOT_GATE, report)
    provenance = {
        "schema_version": 1,
        "gate_sha256": core.sha256_path(run_dir / PILOT_GATE),
        "collection_path": str(collection_path.resolve(strict=True)),
        "collection_sha256": expected_collection_sha256,
        "fire_lineage_sha256": core.sha256_path(run_dir / LINEAGE),
        "fire_release_sha256": core.sha256_path(run_dir / PILOT_RELEASE),
        "structure_accepted": False,
        "preflight_unlocked": False,
        "full_execution_released": False,
    }
    if report.get("fire_replacement_sha256") is not None:
        provenance["fire_replacement_sha256"] = report["fire_replacement_sha256"]
    core.write_json_immutable(
        run_dir / PILOT_PROVENANCE,
        provenance,
    )
    if report["pass"] is not True:
        raise core.CampaignError("FIRE pilot trend gate failed; immutable evidence was preserved")
    return report


def release_preflight(*_: object, **__: object) -> dict[str, Any]:
    """Reserved future boundary; arbitrary review JSON must never unlock work."""
    raise core.CampaignError("independent replay not implemented; FIRE preflight remains locked")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-lineage"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--old-lineage-run", type=Path, required=True)
    p = sub.add_parser("authorize-infrastructure-replacement"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True)
    p = sub.add_parser("verify-infrastructure-replacement"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--expect-authorization-sha"); p.add_argument("--replacement-attempt-id"); p.add_argument("--allow-primary-attempt", action="store_true")
    p = sub.add_parser("verify-release"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True)
    p = sub.add_parser("verify-collector-attachment"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--primary-attempt-id", required=True); p.add_argument("--primary-job-id", required=True); p.add_argument("--replacement-authorization-sha")
    p = sub.add_parser("run"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--stage", choices=("pilot", "full"), required=True)
    p = sub.add_parser("replay-pilot"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--collection", type=Path, required=True); p.add_argument("--expect-collection-sha", required=True)
    p = sub.add_parser("finalize-pilot"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-dir", type=Path, required=True); p.add_argument("--collection", type=Path, required=True); p.add_argument("--expect-collection-sha", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-lineage": result = prepare_lineage(args.config,args.run_dir,args.old_lineage_run)
        elif args.command == "authorize-infrastructure-replacement": result = create_infrastructure_replacement_authorization(args.config, args.run_dir)
        elif args.command == "verify-infrastructure-replacement": result = verify_infrastructure_replacement_authorization(args.config, args.run_dir, require_unused=False, expected_authorization_sha256=args.expect_authorization_sha, replacement_attempt_id=args.replacement_attempt_id, allow_primary_attempt=args.allow_primary_attempt)
        elif args.command == "verify-release": result = verify_fire_submission_ready(args.config, args.run_dir, "fire-pilot", require_unused=False)
        elif args.command == "verify-collector-attachment": result = verify_fire_collector_attachment(args.config, args.run_dir, args.primary_attempt_id, args.primary_job_id, replacement_authorization_sha256=args.replacement_authorization_sha)
        elif args.command == "run": result = run_stage(args.config, args.run_dir, args.stage)
        elif args.command == "replay-pilot": result = replay_pilot(args.config, args.run_dir, args.collection, expected_collection_sha256=args.expect_collection_sha)
        elif args.command == "finalize-pilot": result = finalize_stage(args.config, args.run_dir, "pilot", args.collection, expected_collection_sha256=args.expect_collection_sha)
    except (core.CampaignError, OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())

#!/usr/bin/env python3
"""Finalize a complete production-force dataset from immutable evidence.

This module performs no QE or phono3py calculation.  It consumes an explicit,
hash-anchored plan, replays the existing force/provenance validators, requires
complete FC3 and FC2 force coverage, and publishes a canonical force gate only
after every check passes.  It deliberately has no integration in campaign.py;
the public command can be wired only after its submission contract supplies the
trusted plan digest required here.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import campaign as core
import force_backend as fb
import submit as submit_backend
from postprocess_backend import (
    ForceArtifact,
    PostprocessError,
    file_hash,
    load_force_artifact,
)
from qe_output import parse_last_force_block


SHA256_RE = re.compile(r"[0-9a-f]{64}")
RAW_FILES = (
    "context.tsv",
    "exit_code.txt",
    "finished_utc.txt",
    "force_claim.json",
    "launch.json",
    "result.json",
    "scf.process.json",
    "scf.in",
    "scf.out",
    "scf.err",
)


class ForceFinalizeError(RuntimeError):
    """The proposed production dataset is incomplete or not provenance-safe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ForceFinalizeError(message)


def _digest(value: Any, label: str) -> str:
    _require(
        isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
        f"invalid SHA256 for {label}",
    )
    return value


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ForceFinalizeError(f"cannot read {label}: {exc}") from exc
    _require(isinstance(value, dict), f"{label} must contain a JSON object")
    return value


def _has_symlink_below_root(path: Path, root: Path) -> bool:
    """Ignore host-level aliases while rejecting every symlink below root."""

    current = path
    while True:
        if current.is_symlink():
            return True
        if current.resolve() == root:
            return False
        parent = current.parent
        if parent == current:
            return True
        current = parent


def _safe_run_dir(path: Path) -> Path:
    raw = Path(path)
    _require(raw.is_absolute(), "RUN_DIR must be absolute")
    _require("READY_TO_ATTACH" not in raw.parts, "RUN_DIR may not be inside READY_TO_ATTACH")
    _require(not raw.is_symlink(), "RUN_DIR may not be a symlink")
    resolved = raw.resolve()
    _require(resolved.is_dir(), f"RUN_DIR does not exist: {resolved}")
    return resolved


def _safe_descendant(path: Path, root: Path, label: str, *, file: bool) -> Path:
    raw = Path(path)
    _require(raw.is_absolute(), f"{label} path must be absolute")
    _require("READY_TO_ATTACH" not in raw.parts, f"{label} may not be inside READY_TO_ATTACH")
    resolved = raw.resolve()
    _require(resolved != root and resolved.is_relative_to(root), f"{label} must be a strict descendant of RUN_DIR")
    _require(not _has_symlink_below_root(raw, root), f"{label} path may not contain a symlink")
    _require(resolved.is_file() if file else resolved.is_dir(), f"missing {label}: {resolved}")
    return resolved


def _reference(value: Any, root: Path, label: str) -> tuple[Path, str]:
    _require(isinstance(value, Mapping), f"{label} reference must be an object")
    _require(set(value) == {"path", "sha256"}, f"{label} reference must contain only path and sha256")
    path = _safe_descendant(Path(str(value["path"])), root, label, file=True)
    expected = _digest(value["sha256"], label)
    _require(file_hash(path) == expected, f"{label} hash mismatch")
    return path, expected


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        import yaml  # type: ignore
    except ImportError:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ForceFinalizeError(
                "PyYAML is required for a non-JSON phono3py displacement YAML"
            ) from exc
    else:
        value = yaml.safe_load(text)
    _require(isinstance(value, dict), "phono3py displacement YAML must be an object")
    return value


def _dataset_ids(dataset: Mapping[str, Any]) -> tuple[list[int], list[int]]:
    try:
        inventory = core.analyze_displacement_yaml(dataset)
        pairs = dataset["displacement_pairs"]
        first = [item["displacement_id"] for item in pairs]
    except (KeyError, TypeError, ValueError, core.CampaignError) as exc:
        raise ForceFinalizeError(f"invalid accepted displacement YAML: {exc}") from exc
    _require(
        all(type(item) is int and item > 0 for item in first)
        and len(first) == len(set(first)),
        "FC2 first-displacement IDs are invalid or duplicated",
    )
    included = list(inventory["included_displacement_ids"])
    _require(set(first).issubset(included), "FC2 IDs are not a subset of included FC3 IDs")
    return included, first


def _allocation_for(
    entry: Mapping[str, Any], accounting_records: list[dict[str, str]],
    job_id: str, task_id: int, raw_job_id: str,
) -> Mapping[str, Any]:
    display = f"{job_id}_{task_id}"
    records, allocation, errors = core._accounting_for_force_task(
        accounting_records, job_id, task_id, raw_job_id
    )
    _require(not errors and allocation is not None, f"task {display} accounting audit failed: {errors}")
    _require(entry.get("scheduler_records") == records, f"task {display} collection/accounting rows differ")
    allocations = [row for row in records if row.get("JobID") == display]
    _require(len(allocations) == 1, f"task {display} does not have exactly one scheduler allocation")
    allocation = allocations[0]
    state = str(allocation.get("State", "")).strip().upper().split()[0].rstrip("+")
    _require(state == "COMPLETED", f"task {display} scheduler state is not COMPLETED")
    _require(allocation.get("ExitCode") == "0:0", f"task {display} scheduler exit is not 0:0")
    return allocation


def _force_values(artifact: ForceArtifact) -> list[float]:
    block = parse_last_force_block(artifact.output_path)
    values = [component for row in block.forces_ry_bohr for component in row]
    _require(bool(values) and all(math.isfinite(value) for value in values), "invalid pristine force array")
    return values


def _same_force_fingerprint(left: ForceArtifact, right: ForceArtifact) -> None:
    for key in (
        "dataset_sha256",
        "supercell_sha256",
        "settings_sha256",
        "pseudo_sha256",
        "atom_order",
    ):
        _require(left.manifest.get(key) == right.manifest.get(key), f"force artifact mismatch: {key}")


def _explicit_tolerances(plan: Mapping[str, Any]) -> tuple[float, float]:
    value = plan.get("pristine_comparison_tolerances_ry_bohr")
    _require(isinstance(value, Mapping), "explicit pristine comparison tolerances are required")
    _require(
        set(value) == {"maximum_component", "rms_component"},
        "pristine tolerances must contain maximum_component and rms_component",
    )
    result = []
    for name in ("maximum_component", "rms_component"):
        raw = value[name]
        _require(not isinstance(raw, bool), f"{name} tolerance must be numerical")
        number = float(raw)
        _require(math.isfinite(number) and number >= 0, f"{name} tolerance must be finite and non-negative")
        result.append(number)
    return result[0], result[1]


def _validate_fixed_references(
    plan: Mapping[str, Any], run_dir: Path
) -> tuple[Path, Path, Path, Path, Path, Path]:
    accepted = plan.get("accepted_structure")
    preflight = plan.get("selected_preflight")
    _require(isinstance(accepted, Mapping), "accepted_structure references are required")
    _require(isinstance(preflight, Mapping), "selected_preflight references are required")
    gate, _ = _reference(accepted.get("gate"), run_dir, "accepted structure gate")
    provenance, _ = _reference(accepted.get("provenance"), run_dir, "accepted structure provenance")
    unitcell, unitcell_sha = _reference(accepted.get("unitcell"), run_dir, "accepted unitcell")
    _require(gate == run_dir / "relax" / "final" / "gate.json", "accepted gate is not the canonical relax gate")
    _require(provenance == run_dir / "relax" / "final" / "provenance.json", "accepted provenance is not canonical")
    _require(unitcell == run_dir / "relax" / "final" / "unitcell.in", "accepted unitcell is not canonical")
    gate_value = _read_json(gate, "accepted structure gate")
    _require(gate_value.get("pass") is True, "accepted structure gate is not passing")
    _require(gate_value.get("final_unitcell_sha256") == unitcell_sha, "accepted gate does not bind unitcell")

    inventory, _ = _reference(preflight.get("inventory"), run_dir, "preflight inventory")
    result, _ = _reference(preflight.get("result"), run_dir, "preflight result")
    dataset, dataset_sha = _reference(preflight.get("dataset"), run_dir, "phono3py displacement dataset")
    _require(result.parent == dataset.parent, "preflight result and displacement dataset must be adjacent")
    result_value = _read_json(result, "preflight result")
    _require(result_value.get("yaml_sha256") == dataset_sha, "preflight result does not bind displacement YAML")
    return inventory, result, dataset, gate, provenance, unitcell


def _raw_plan_map(value: Any, root: Path) -> dict[int, tuple[Path, dict[str, str]]]:
    _require(isinstance(value, list) and value, "batch raw_artifacts must be a nonempty list")
    output: dict[int, tuple[Path, dict[str, str]]] = {}
    for item in value:
        _require(isinstance(item, Mapping), "raw artifact plan entry must be an object")
        task_id = item.get("task_id")
        _require(type(task_id) is int and task_id >= 0 and task_id not in output, "raw artifact task IDs are invalid or duplicated")
        attempt = _safe_descendant(Path(str(item.get("attempt_path", ""))), root, f"task {task_id} attempt", file=False)
        hashes = item.get("files_sha256")
        _require(
            isinstance(hashes, Mapping) and set(RAW_FILES).issubset(hashes),
            f"task {task_id} raw hash set is incomplete",
        )
        checked: dict[str, str] = {}
        for raw_name, raw_digest in hashes.items():
            name = str(raw_name)
            _require(Path(name).name == name and name != "failure.json", f"task {task_id} raw filename is unsafe")
            digest = _digest(raw_digest, f"task {task_id} {name}")
            path = _safe_descendant(attempt / name, root, f"task {task_id} {name}", file=True)
            _require(path.parent == attempt, f"task {task_id} raw evidence escaped its attempt")
            _require(file_hash(path) == digest, f"task {task_id} {name} hash mismatch")
            checked[name] = digest
        output[task_id] = (attempt, checked)
    return output


def _audit_batch(
    batch: Mapping[str, Any], *, config: Mapping[str, Any], config_path: Path,
    run_dir: Path, expected_settings: Mapping[str, Any], expected_sources: Mapping[str, str],
    expected_selection: Mapping[str, Any], reference_artifact: ForceArtifact | None,
) -> tuple[dict[str, Any], list[ForceArtifact], ForceArtifact]:
    batch_id = batch.get("batch_id")
    _require(isinstance(batch_id, str) and batch_id, "batch_id must be a nonempty string")
    collection_path, collection_sha = _reference(batch.get("collection"), run_dir, f"{batch_id} collection")
    manifest_path, manifest_sha = _reference(batch.get("force_manifest"), run_dir, f"{batch_id} force manifest")
    task_map_path, task_map_sha = _reference(batch.get("task_map"), run_dir, f"{batch_id} task map")
    budget_path, budget_sha = _reference(batch.get("budget_receipt"), run_dir, f"{batch_id} budget receipt")
    ledger_path, ledger_sha = _reference(
        batch.get("budget_ledger_reservation"), run_dir, f"{batch_id} budget ledger reservation"
    )
    request_path, request_sha = _reference(batch.get("submission_request"), run_dir, f"{batch_id} submission request")
    result_path, result_sha = _reference(batch.get("submission_result"), run_dir, f"{batch_id} submission result")
    submission_path, submission_sha = _reference(batch.get("submission_summary"), run_dir, f"{batch_id} submission summary")
    collector_request_path, collector_request_sha = _reference(
        batch.get("collector_request"), run_dir, f"{batch_id} collector submission request"
    )
    collector_result_path, collector_result_sha = _reference(
        batch.get("collector_result"), run_dir, f"{batch_id} collector submission result"
    )
    _require(
        manifest_path.parent == task_map_path.parent == budget_path.parent,
        f"{batch_id} force bundle references are not adjacent",
    )
    _require(
        len({request_path.parent, result_path.parent, submission_path.parent,
             collector_request_path.parent, collector_result_path.parent}) == 1,
        f"{batch_id} submission records are not from one immutable attempt",
    )
    accounting_path, accounting_sha = _reference(batch.get("scheduler_accounting"), run_dir, f"{batch_id} scheduler accounting")
    accounting_status_path, accounting_status_sha = _reference(
        batch.get("scheduler_accounting_status"), run_dir, f"{batch_id} scheduler accounting status"
    )
    accounting_records, accounting_errors, accounting_metadata = core._read_sacct_records(
        accounting_path, accounting_status_path
    )
    _require(not accounting_errors, f"{batch_id} scheduler accounting audit failed: {accounting_errors}")

    collection = _read_json(collection_path, f"{batch_id} collection")
    manifest = _read_json(manifest_path, f"{batch_id} force manifest")
    request = _read_json(request_path, f"{batch_id} submission request")
    submission_result = _read_json(result_path, f"{batch_id} submission result")
    submission = _read_json(submission_path, f"{batch_id} submission summary")
    collector_request = _read_json(collector_request_path, f"{batch_id} collector submission request")
    collector_result = _read_json(collector_result_path, f"{batch_id} collector submission result")
    budget = _read_json(budget_path, f"{batch_id} budget receipt")
    ledger_reservation = _read_json(ledger_path, f"{batch_id} budget ledger reservation")
    _require(
        ledger_path.parent == run_dir / ".force_budget"
        and ledger_reservation.get("receipt_path") == str(budget_path)
        and ledger_reservation.get("receipt_sha256") == budget_sha,
        f"{batch_id} budget ledger reservation does not bind the exact receipt",
    )
    try:
        replayed_ledger = fb.replay_budget_ledger(run_dir, config)
    except core.CampaignError as exc:
        raise ForceFinalizeError(f"{batch_id} budget ledger replay failed: {exc}") from exc
    matching_ledger = [
        item for item in replayed_ledger
        if item["path"] == ledger_path
        and item["record"]["receipt_path"] == str(budget_path)
        and item["record"]["receipt_sha256"] == budget_sha
    ]
    _require(len(matching_ledger) == 1, f"{batch_id} budget receipt is not uniquely anchored in the ledger")
    _require(collection.get("schema_version") == 1 and collection.get("stage") == "collect", f"{batch_id} collection schema/stage mismatch")
    _require(collection.get("collection_kind") == "force_array_batch", f"{batch_id} is not a force-array collection")
    _require(collection.get("force_mode") == "production", f"{batch_id} is not a production collection")
    _require(collection.get("material") == config["material"]["formula"], f"{batch_id} collection material mismatch")
    _require(collection.get("collection_integrity_complete") is True and collection.get("batch_execution_complete") is True and collection.get("incomplete") is False, f"{batch_id} collection is incomplete")
    _require(manifest.get("schema_version") == 1 and manifest.get("stage") == "force" and manifest.get("mode") == "production", f"{batch_id} force manifest is not production")
    _require(manifest.get("material") == config["material"]["formula"], f"{batch_id} material mismatch")
    _require(manifest.get("config_sha256") == file_hash(config_path), f"{batch_id} config hash mismatch")
    _require(manifest.get("task_map_sha256") == task_map_sha, f"{batch_id} manifest/task-map mismatch")
    _require(manifest.get("budget_receipt_sha256") == budget_sha, f"{batch_id} manifest/budget mismatch")
    _require(
        budget.get("schema_version") == 1
        and budget.get("phase") == "production"
        and type(manifest.get("task_count")) is int
        and manifest["task_count"] > 0
        and budget.get("task_count") == manifest["task_count"]
        and budget.get("task_map_sha256") == task_map_sha
        and budget.get("reserved_core_hours") == ledger_reservation.get("reserved_core_hours"),
        f"{batch_id} budget receipt semantic fields do not match production task evidence",
    )
    _require(manifest.get("settings") == expected_settings, f"{batch_id} force physics differs from selected settings")
    _require(manifest.get("selection_validation") == expected_selection, f"{batch_id} selection validation mismatch")
    _require(manifest.get("force_policy_sha256") == core.canonical_sha256({"production": config["production"], "force": config["force_and_amplitude_validation"]}), f"{batch_id} force policy mismatch")
    evidence = manifest.get("evidence_sha256")
    _require(isinstance(evidence, Mapping), f"{batch_id} force provenance is missing")
    for path, digest in expected_sources.items():
        _require(evidence.get(path) == digest, f"{batch_id} does not bind accepted upstream evidence: {path}")
    fb.verify_selection_provenance(manifest, run_dir, config_path=config_path)
    context = submit_backend.SubmissionContext(
        config_path=config_path,
        run_dir=run_dir,
        config=dict(config),
        manifest={},
        config_sha256=file_hash(config_path),
    )
    try:
        validated = submit_backend.validate_force_bundle(context, task_map_path)
    except (submit_backend.SubmissionError, core.CampaignError, OSError, ValueError) as exc:
        raise ForceFinalizeError(f"{batch_id} force bundle replay failed: {exc}") from exc
    _require(
        validated[0] == task_map_path
        and validated[2] == task_map_sha
        and validated[3] == manifest_path
        and file_hash(validated[3]) == manifest_sha
        and validated[5] == budget_path
        and file_hash(validated[5]) == budget_sha,
        f"{batch_id} force bundle replay resolved different evidence",
    )

    primary = collection.get("primary")
    _require(isinstance(primary, Mapping), f"{batch_id} collection primary metadata is missing")
    attempt_id = primary.get("attempt_id")
    job_id = primary.get("job_id")
    _require(isinstance(attempt_id, str) and attempt_id, f"{batch_id} primary attempt ID is invalid")
    _require(isinstance(job_id, str) and job_id.isdigit(), f"{batch_id} primary job ID is invalid")
    _require(primary.get("force_manifest") == str(manifest_path) and primary.get("force_manifest_sha256") == manifest_sha and primary.get("submitted_force_manifest_sha256") == manifest_sha, f"{batch_id} collection does not bind force manifest")
    _require(primary.get("task_map") == str(task_map_path) and primary.get("task_map_sha256") == task_map_sha and primary.get("submitted_task_map_sha256") == task_map_sha, f"{batch_id} collection does not bind task map")
    scheduler = primary.get("scheduler_accounting")
    _require(isinstance(scheduler, Mapping), f"{batch_id} scheduler metadata is missing")
    _require(scheduler.get("path") == str(accounting_path) and scheduler.get("sha256") == accounting_sha, f"{batch_id} collection does not bind scheduler accounting")
    _require(scheduler.get("status_path") == str(accounting_status_path) and scheduler.get("status_sha256") == accounting_status_sha and scheduler.get("sacct_exit_code") == 0, f"{batch_id} collection does not bind successful accounting status")
    for key in ("path", "sha256", "status_path", "status_sha256", "sacct_exit_code"):
        _require(scheduler.get(key) == accounting_metadata.get(key), f"{batch_id} collection/accounting metadata differs: {key}")

    _require(request.get("stage") == "force" and request.get("attempt_id") == attempt_id, f"{batch_id} submission request stage/attempt mismatch")
    _require(request.get("config") == str(config_path) and request.get("config_sha256") == file_hash(config_path), f"{batch_id} submission request config mismatch")
    _require(request.get("run_dir") == str(run_dir), f"{batch_id} submission request run mismatch")
    _require(request.get("force_mode") == "production", f"{batch_id} submission request is not production")
    _require(request.get("force_manifest") == str(manifest_path) and request.get("force_manifest_sha256") == manifest_sha, f"{batch_id} submission request manifest mismatch")
    _require(request.get("task_map") == str(task_map_path) and request.get("task_map_sha256") == task_map_sha, f"{batch_id} submission request task-map mismatch")
    _require(request.get("budget_receipt") == str(budget_path) and request.get("budget_receipt_sha256") == budget_sha, f"{batch_id} submission request budget mismatch")
    try:
        parsed_job_id = submit_backend.parse_job_id(str(submission_result.get("stdout", "")))
    except submit_backend.SubmissionError as exc:
        raise ForceFinalizeError(f"{batch_id} primary submission stdout is invalid: {exc}") from exc
    _require(
        submission_result.get("job_id") == job_id
        and submission_result.get("returncode") == 0
        and submission_result.get("command") == request.get("command")
        and parsed_job_id == job_id,
        f"{batch_id} submission result job/command mismatch",
    )
    collector_attempt_id = collector_request.get("attempt_id")
    collector_job_id = collector_result.get("job_id")
    _require(
        isinstance(collector_attempt_id, str) and collector_attempt_id
        and isinstance(collector_job_id, str) and collector_job_id.isdigit()
        and collector_result.get("returncode") == 0,
        f"{batch_id} collector submission result is invalid",
    )
    _require(
        collector_request.get("primary_stage") == "force"
        and collector_request.get("primary_attempt_id") == attempt_id
        and collector_request.get("primary_job_id") == job_id
        and collector_request.get("dependency") == f"afterany:{job_id}",
        f"{batch_id} collector request does not bind the primary submission",
    )
    expected_collector = {
        "attempt_id": collector_attempt_id,
        "job_id": collector_job_id,
        "primary_stage": "force",
        "primary_attempt_id": attempt_id,
        "primary_job_id": job_id,
        "dependency": f"afterany:{job_id}",
        "command": collector_request.get("command"),
    }
    _require(
        submission.get("healthy") is True
        and submission.get("stage") == "force"
        and submission.get("attempt_id") == attempt_id
        and submission.get("primary_job_id") == job_id
        and submission.get("config_sha256") == file_hash(config_path)
        and submission.get("run_dir") == str(run_dir)
        and submission.get("task_map_sha256") == task_map_sha
        and submission.get("force_manifest_sha256") == manifest_sha
        and submission.get("budget_receipt_sha256") == budget_sha
        and submission.get("force_mode") == "production"
        and submission.get("record_dir") == str(submission_path.parent)
        and submission.get("collector") == expected_collector,
        f"{batch_id} submission summary mismatch",
    )
    _require(
        collection.get("collector_attempt") == str(collection_path.parent)
        and collection_path.parent == run_dir / "slurm_attempts" / "collect" / collector_attempt_id,
        f"{batch_id} collection is not the submitted collector attempt",
    )

    tasks = manifest.get("tasks")
    entries = collection.get("entries")
    _require(isinstance(tasks, list) and isinstance(entries, list) and len(tasks) == len(entries) == manifest.get("task_count"), f"{batch_id} task domain mismatch")
    raw = _raw_plan_map(batch.get("raw_artifacts"), run_dir)
    _require(set(raw) == set(range(len(tasks))), f"{batch_id} raw-artifact plan does not cover every task")
    artifacts: list[ForceArtifact] = []
    pristine: ForceArtifact | None = None
    for task_id, (task, entry) in enumerate(zip(tasks, entries)):
        _require(isinstance(task, Mapping) and isinstance(entry, Mapping), f"{batch_id} malformed task/entry")
        _require(task.get("task_id") == task_id and entry.get("task_id") == task_id, f"{batch_id} non-contiguous task IDs")
        _safe_descendant(Path(str(task.get("input_path", ""))), run_dir, f"{batch_id} task {task_id} source input", file=True)
        _require(entry.get("displacement_id") == task.get("displacement_id") and entry.get("role") == task.get("role"), f"{batch_id} collection task identity mismatch")
        _require(entry.get("outcome") == "accepted_success" and entry.get("errors") == [], f"{batch_id} task {task_id} was not accepted")
        context = entry.get("context")
        _require(isinstance(context, Mapping), f"{batch_id} task {task_id} context is missing")
        raw_job_id = context.get("slurm_job_id")
        _require(isinstance(raw_job_id, str) and raw_job_id.isdigit(), f"{batch_id} task {task_id} raw job ID is invalid")
        _require(
            context.get("stage") == "force"
            and context.get("attempt_id") == attempt_id
            and context.get("slurm_array_job_id") == job_id
            and context.get("slurm_array_task_id") == str(task_id)
            and context.get("run_dir") == str(run_dir)
            and context.get("config_sha256") == file_hash(config_path),
            f"{batch_id} task {task_id} immutable context mismatch",
        )
        _require(entry.get("exit_code") == 0 and entry.get("finished") is True, f"{batch_id} task {task_id} did not finish with exit 0")
        _allocation_for(entry, accounting_records, job_id, task_id, raw_job_id)
        attempt, expected_raw = raw[task_id]
        raw_context, context_errors = core._read_context_tsv(attempt / "context.tsv")
        _require(not context_errors and dict(context) == raw_context, f"{batch_id} task {task_id} raw context audit failed: {context_errors}")
        raw_exit_code, exit_errors = core._read_exit_code(attempt)
        _require(not exit_errors and raw_exit_code == 0, f"{batch_id} task {task_id} raw exit audit failed: {exit_errors}")
        _require(entry.get("attempt_path") == str(attempt), f"{batch_id} task {task_id} attempt mismatch")
        collected_hashes = entry.get("evidence")
        _require(isinstance(collected_hashes, Mapping), f"{batch_id} task {task_id} lacks collected hashes")
        _require(set(collected_hashes) == set(expected_raw), f"{batch_id} task {task_id} raw evidence set differs from plan")
        for name, digest in expected_raw.items():
            item = collected_hashes.get(name)
            _require(isinstance(item, Mapping) and item.get("sha256") == digest, f"{batch_id} task {task_id} collection hash mismatch: {name}")
        try:
            artifact = load_force_artifact(manifest_path, attempt, task_id)
        except (PostprocessError, OSError, ValueError) as exc:
            raise ForceFinalizeError(f"{batch_id} task {task_id} raw audit failed: {exc}") from exc
        if reference_artifact is not None:
            _same_force_fingerprint(reference_artifact, artifact)
        if artifact.displacement_id == 0:
            _require(pristine is None and task.get("role") == "pristine", f"{batch_id} must contain exactly one pristine task")
            pristine = artifact
        else:
            _require(task.get("role") == "displacement", f"{batch_id} has invalid displacement role")
            artifacts.append(artifact)
    _require(pristine is not None, f"{batch_id} has no pristine task")
    for artifact in artifacts:
        _same_force_fingerprint(pristine, artifact)
    if reference_artifact is not None:
        _same_force_fingerprint(reference_artifact, pristine)
    return {
        "batch_id": batch_id,
        "collection": {"path": str(collection_path), "sha256": collection_sha},
        "force_manifest": {"path": str(manifest_path), "sha256": manifest_sha},
        "task_map": {"path": str(task_map_path), "sha256": task_map_sha},
        "budget_receipt": {"path": str(budget_path), "sha256": budget_sha},
        "budget_ledger_reservation": {"path": str(ledger_path), "sha256": ledger_sha},
        "submission_request": {"path": str(request_path), "sha256": request_sha},
        "submission_result": {"path": str(result_path), "sha256": result_sha},
        "submission_summary": {"path": str(submission_path), "sha256": submission_sha},
        "collector_request": {"path": str(collector_request_path), "sha256": collector_request_sha},
        "collector_result": {"path": str(collector_result_path), "sha256": collector_result_sha},
        "scheduler_accounting": {"path": str(accounting_path), "sha256": accounting_sha},
        "scheduler_accounting_status": {"path": str(accounting_status_path), "sha256": accounting_status_sha},
        "raw_artifacts": [
            {
                "task_id": task_id,
                "attempt_path": str(attempt),
                "files_sha256": hashes,
            }
            for task_id, (attempt, hashes) in sorted(raw.items())
        ],
    }, artifacts, pristine


def _audit(
    config_path: Path, run_dir: Path, plan_path: Path, expected_plan_sha256: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_config_path = Path(config_path)
    _require(raw_config_path.is_absolute(), "campaign config path must be absolute")
    _require(not raw_config_path.is_symlink(), "campaign config is missing or symlinked")
    _require("READY_TO_ATTACH" not in raw_config_path.parts, "campaign config may not be inside READY_TO_ATTACH")
    config_path = raw_config_path.resolve()
    _require(config_path.is_file(), "campaign config is missing or symlinked")
    expected_plan_sha256 = _digest(expected_plan_sha256, "force-finalize plan")
    plan_path = _safe_descendant(Path(plan_path), run_dir, "force-finalize plan", file=True)
    _require(file_hash(plan_path) == expected_plan_sha256, "force-finalize plan hash mismatch")
    plan = _read_json(plan_path, "force-finalize plan")
    _require(plan.get("schema_version") == 1 and plan.get("stage") == "force_finalize_plan", "unsupported force-finalize plan schema/stage")
    _require(plan.get("config_sha256") == file_hash(config_path), "plan config hash mismatch")
    try:
        config, _ = core.validate_config(config_path)
    except (core.CampaignError, OSError, ValueError) as exc:
        raise ForceFinalizeError(f"campaign config validation failed: {exc}") from exc
    formula = config["material"]["formula"]
    _require(plan.get("material") == formula, "plan material mismatch")
    production = config.get("production")
    _require(isinstance(production, Mapping) and production.get("selection_required") is False and production.get("automatic_submission_allowed") is True, "production selection has not been released")
    fc3_matrix = production.get("selected_fc3_supercell_matrix")
    fc2_matrix = production.get("selected_fc2_supercell_matrix")
    _require(fc3_matrix is not None and fc2_matrix is not None, "selected FC2/FC3 matrices must be explicit")
    _require(fc2_matrix == fc3_matrix, "independent FC2 supercells are not supported by this finalizer")

    inventory_path, result_path, dataset_path, gate_path, provenance_path, unitcell_path = _validate_fixed_references(plan, run_dir)
    dataset = _load_yaml(dataset_path)
    _require(core.required(dataset, "physical_unit.length") == "au", "QE phono3py YAML length unit must be au")
    _require(dataset.get("supercell_matrix") == fc3_matrix, "accepted YAML supercell matrix differs from production selection")
    fc3_ids, fc2_ids = _dataset_ids(dataset)
    preflight_result = _read_json(result_path, "preflight result")
    _require(preflight_result.get("selection_eligible") is True, "selected preflight is not production eligible")
    _require(preflight_result.get("supercell_id") == production.get("selected_supercell") and preflight_result.get("cutoff_id") == production.get("selected_cutoff"), "selected preflight identity differs from production config")
    _require(preflight_result.get("generated_displacement_ids") == fc3_ids, "preflight/YAML FC3 ID inventory mismatch")

    try:
        expected_settings = fb._settings(config, "production", None)
        expected_sources, _ = fb._provenance(config, config_path, run_dir, inventory_path, dataset_path.parent)
    except (fb.ForceError, core.CampaignError, OSError, ValueError, KeyError, TypeError) as exc:
        raise ForceFinalizeError(f"accepted upstream provenance failed replay: {exc}") from exc

    selection_path, selection_sha = _reference(plan.get("selection_receipt"), run_dir, "selection receipt")
    try:
        expected_selection = fb.validate_selection_evidence(
            selection_path, config_path, config, expected_settings, run_dir, dataset_path.parent
        )
    except (fb.ForceError, OSError, ValueError, KeyError, TypeError) as exc:
        raise ForceFinalizeError(f"selection receipt failed raw-evidence replay: {exc}") from exc
    _require(expected_selection.get("selection_receipt_path") == str(selection_path) and expected_selection.get("selection_receipt_sha256") == selection_sha, "selection replay does not bind the explicit receipt")

    batches = plan.get("batches")
    _require(isinstance(batches, list) and batches, "at least one production batch is required")
    batch_ids = [item.get("batch_id") if isinstance(item, Mapping) else None for item in batches]
    _require(all(isinstance(item, str) and item for item in batch_ids) and len(batch_ids) == len(set(batch_ids)), "batch IDs are invalid or duplicated")
    batch_records: list[dict[str, Any]] = []
    displaced: dict[int, ForceArtifact] = {}
    pristine_by_identity: dict[tuple[str, int], ForceArtifact] = {}
    reference: ForceArtifact | None = None
    for batch in batches:
        assert isinstance(batch, Mapping)
        record, artifacts, pristine = _audit_batch(
            batch,
            config=config,
            config_path=config_path,
            run_dir=run_dir,
            expected_settings=expected_settings,
            expected_sources=expected_sources,
            expected_selection=expected_selection,
            reference_artifact=reference,
        )
        reference = reference or pristine
        batch_records.append(record)
        manifest = _read_json(Path(record["force_manifest"]["path"]), "force manifest")
        pristine_task = next(task for task in manifest["tasks"] if task["displacement_id"] == 0)
        pristine_by_identity[(str(batch["batch_id"]), int(pristine_task["task_id"]))] = pristine
        for artifact in artifacts:
            _require(artifact.displacement_id not in displaced, f"duplicate displacement ID across batches: {artifact.displacement_id}")
            displaced[artifact.displacement_id] = artifact
    actual_ids = sorted(displaced)
    missing = sorted(set(fc3_ids) - set(actual_ids))
    extra = sorted(set(actual_ids) - set(fc3_ids))
    _require(not missing and not extra, f"production displacement coverage mismatch; missing={missing}, extra={extra}")

    canonical = plan.get("canonical_pristine")
    _require(isinstance(canonical, Mapping), "canonical_pristine identity is required")
    _require(set(canonical) == {"batch_id", "task_id", "output_sha256"}, "canonical_pristine must bind batch_id, task_id, and output_sha256")
    identity = (canonical.get("batch_id"), canonical.get("task_id"))
    _require(identity in pristine_by_identity, "canonical pristine identity is absent")
    canonical_artifact = pristine_by_identity[identity]
    canonical_output_sha = _digest(canonical.get("output_sha256"), "canonical pristine output")
    _require(canonical_artifact.manifest["output_sha256"] == canonical_output_sha, "canonical pristine output hash mismatch")
    maximum_tolerance, rms_tolerance = _explicit_tolerances(plan)
    baseline = _force_values(canonical_artifact)
    pristine_comparisons = []
    for current_identity, artifact in sorted(pristine_by_identity.items()):
        _same_force_fingerprint(canonical_artifact, artifact)
        values = _force_values(artifact)
        _require(len(values) == len(baseline), "pristine force-array size mismatch")
        differences = [abs(left - right) for left, right in zip(values, baseline)]
        maximum = max(differences, default=0.0)
        rms = math.sqrt(sum(value * value for value in differences) / len(differences))
        _require(maximum <= maximum_tolerance, f"pristine maximum-component mismatch for {current_identity}")
        _require(rms <= rms_tolerance, f"pristine RMS mismatch for {current_identity}")
        pristine_comparisons.append({
            "batch_id": current_identity[0],
            "task_id": current_identity[1],
            "maximum_component_difference_ry_bohr": maximum,
            "rms_component_difference_ry_bohr": rms,
        })

    artifact_index = []
    for displacement_id in fc3_ids:
        artifact = displaced[displacement_id]
        artifact_index.append({
            "displacement_id": displacement_id,
            "input_path": artifact.input_path,
            "input_sha256": artifact.manifest["input_sha256"],
            "output_path": artifact.output_path,
            "output_sha256": artifact.manifest["output_sha256"],
            "stderr_path": artifact.stderr_path,
            "stderr_sha256": artifact.manifest["stderr_sha256"],
            "force_manifest_sha256": artifact.manifest["force_manifest_sha256"],
            "receipt_sha256": artifact.manifest["receipt_sha256"],
        })
    audit_backends = {
        str(path): file_hash(path)
        for path in (
            Path(__file__).resolve(),
            Path(core.__file__).resolve(),
            Path(fb.__file__).resolve(),
            Path(submit_backend.__file__).resolve(),
            Path(__file__).with_name("postprocess_backend.py").resolve(),
            Path(__file__).with_name("qe_input.py").resolve(),
            Path(__file__).with_name("qe_output.py").resolve(),
        )
    }
    force_finalize_backend_sha = audit_backends[str(Path(__file__).resolve())]
    index = {
        "schema_version": 1,
        "stage": "force_dataset_index",
        "material": formula,
        "config": str(config_path),
        "config_sha256": file_hash(config_path),
        "plan": str(plan_path),
        "plan_sha256": expected_plan_sha256,
        "audit_backend_sha256": audit_backends,
        "force_finalize_backend_sha256": force_finalize_backend_sha,
        "accepted_structure": {
            "gate": {"path": str(gate_path), "sha256": file_hash(gate_path)},
            "provenance": {"path": str(provenance_path), "sha256": file_hash(provenance_path)},
            "unitcell": {"path": str(unitcell_path), "sha256": file_hash(unitcell_path)},
        },
        "preflight_inventory": {"path": str(inventory_path), "sha256": file_hash(inventory_path)},
        "preflight_result": {"path": str(result_path), "sha256": file_hash(result_path)},
        "dataset": {"path": str(dataset_path), "sha256": file_hash(dataset_path)},
        "selection_receipt": {"path": str(selection_path), "sha256": selection_sha},
        "selected_fc3_supercell_matrix": fc3_matrix,
        "selected_fc2_supercell_matrix": fc2_matrix,
        "required_fc3_displacement_ids": fc3_ids,
        "required_fc2_first_displacement_ids": fc2_ids,
        "batches": batch_records,
        "canonical_pristine": {
            "batch_id": identity[0],
            "task_id": identity[1],
            "input_path": canonical_artifact.input_path,
            "input_sha256": canonical_artifact.manifest["input_sha256"],
            "output_path": canonical_artifact.output_path,
            "output_sha256": canonical_output_sha,
            "stderr_path": canonical_artifact.stderr_path,
            "stderr_sha256": canonical_artifact.manifest["stderr_sha256"],
        },
        "pristine_comparison_tolerances_ry_bohr": {
            "maximum_component": maximum_tolerance,
            "rms_component": rms_tolerance,
        },
        "pristine_comparisons": pristine_comparisons,
        "artifacts": artifact_index,
        "force_dataset_ready_for_fc2_fc3_construction": True,
        "limitations": [
            "This gate establishes complete audited force evidence only.",
            "It is not an FC2, FC3, phonon-stability, kappa_L, convergence, or thermoelectric result.",
        ],
    }
    receipt = {
        "schema_version": 1,
        "stage": "force_finalize",
        "pass": True,
        "material": formula,
        "checked_utc": core.utc_now(),
        "plan": str(plan_path),
        "plan_sha256": expected_plan_sha256,
        "audit_backend_sha256": audit_backends,
        "force_finalize_backend_sha256": force_finalize_backend_sha,
        "fc3_displacement_count": len(fc3_ids),
        "fc2_first_displacement_count": len(fc2_ids),
        "batch_count": len(batch_records),
        "canonical_pristine": {"batch_id": identity[0], "task_id": identity[1], "output_sha256": canonical_output_sha},
        "force_dataset_ready_for_fc2_fc3_construction": True,
        "scientific_results_claimed": False,
    }
    return receipt, index


def finalize_force_dataset(
    config_path: Path,
    run_dir: Path,
    plan_path: Path,
    *,
    expected_plan_sha256: str,
    attempt_dir: Path,
) -> dict[str, Any]:
    """Audit and immutably publish one complete production-force dataset."""

    run_dir = _safe_run_dir(Path(run_dir))
    attempt_dir = _safe_descendant(Path(attempt_dir), run_dir, "force-finalize attempt", file=False)
    _require(
        attempt_dir.parent == run_dir / "slurm_attempts" / "force-finalize"
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", attempt_dir.name) is not None,
        "force-finalize attempt must be one direct, safely named child of RUN_DIR/slurm_attempts/force-finalize",
    )
    receipt_path = attempt_dir / "force_finalize_receipt.json"
    _require(not receipt_path.exists(), f"force-finalize attempt receipt already exists: {receipt_path}")
    final_dir = run_dir / "force" / "final"
    try:
        _require(not final_dir.exists(), f"canonical force final directory already exists: {final_dir}")
        receipt, index = _audit(
            Path(config_path), run_dir, Path(plan_path), expected_plan_sha256
        )
        core.write_json_immutable(receipt_path, receipt)
        index["finalize_receipt"] = {
            "path": str(receipt_path),
            "sha256": file_hash(receipt_path),
        }
        final_dir.mkdir(parents=True, exist_ok=False)
        index_path = final_dir / "index.json"
        core.write_json_immutable(index_path, index)
        gate = {
            "schema_version": 1,
            "stage": "force_dataset_gate",
            "pass": True,
            "material": receipt["material"],
            "config_sha256": index["config_sha256"],
            "plan_sha256": index["plan_sha256"],
            "audit_backend_sha256": index["audit_backend_sha256"],
            "force_finalize_backend_sha256": index["force_finalize_backend_sha256"],
            "index_sha256": file_hash(index_path),
            "finalize_receipt_sha256": file_hash(receipt_path),
            "production_dataset_complete": True,
            "eligible_for_force_constant_construction": True,
            "scientific_results_claimed": False,
            "scope": "audited production force dataset readiness only",
        }
        gate_path = final_dir / "gate.json"
        core.write_json_immutable(gate_path, gate)
        return {
            "healthy": True,
            "pass": True,
            "receipt": str(receipt_path),
            "receipt_sha256": file_hash(receipt_path),
            "index": str(index_path),
            "index_sha256": file_hash(index_path),
            "gate": str(gate_path),
            "gate_sha256": file_hash(gate_path),
        }
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "stage": "force_finalize",
            "pass": False,
            "checked_utc": core.utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "scientific_results_claimed": False,
        }
        if not receipt_path.exists():
            core.write_json_immutable(receipt_path, failure)
        if isinstance(exc, ForceFinalizeError):
            raise
        raise ForceFinalizeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expect-plan-sha", required=True)
    parser.add_argument("--attempt-dir", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = finalize_force_dataset(
            args.config,
            args.run_dir,
            args.plan,
            expected_plan_sha256=args.expect_plan_sha,
            attempt_dir=args.attempt_dir,
        )
    except ForceFinalizeError as exc:
        print(json.dumps({"healthy": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed Nibi submission frontend for phono3py campaign stages.

The CLI deliberately separates a read-only ``plan`` from ``execute``.  An
execution is accepted only when the caller repeats the exact configuration
SHA-256 printed by the plan.  Scientific work is delegated to the versioned
Slurm scripts; this module never runs QE or phono3py itself.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import math
import json
import os
import re
import secrets
import socket
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from campaign import (
    CampaignError,
    canonical_sha256,
    load_json,
    required,
    safe_run_dir,
    sha256_path,
    validate_config,
    verify_manifest,
    verify_upstream_manifest,
)


SLURM_DIR = (Path(__file__).resolve().parent / "slurm").resolve()
STAGE_SCRIPTS = {
    "relax": "relax.sbatch",
    "preflight": "preflight.sbatch",
    "force": "force_array.sbatch",
    "postprocess": "postprocess.sbatch",
}
COLLECTED_STAGES = frozenset({"relax", "force"})
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ATTEMPT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
TERMINAL_STATES = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "SPECIAL_EXIT",
        "TIMEOUT",
    }
)


class SubmissionError(RuntimeError):
    """Raised when a submission cannot be proven safe."""


class UncertainSubmissionError(SubmissionError):
    """Raised when sbatch may have accepted work but no job ID is provable."""

    def __init__(self, message: str, evidence: Mapping[str, Any]):
        super().__init__(message)
        self.evidence = dict(evidence)


class RejectedSubmissionError(SubmissionError):
    """Raised when sbatch definitely did not return an accepted submission."""

    def __init__(self, message: str, evidence: Mapping[str, Any]):
        super().__init__(message)
        self.evidence = dict(evidence)


@dataclass(frozen=True)
class SubmissionContext:
    config_path: Path
    run_dir: Path
    config: dict[str, Any]
    manifest: dict[str, Any]
    config_sha256: str


@dataclass(frozen=True)
class StagePlan:
    stage: str
    script: Path
    account: str
    exports: dict[str, str]
    array: str | None
    task_count: int | None
    task_map: Path | None
    task_map_sha256: str | None
    force_manifest: Path | None = None
    force_manifest_sha256: str | None = None
    budget_receipt: Path | None = None
    budget_receipt_sha256: str | None = None
    force_mode: str | None = None
    scheduler_options: tuple[str, ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_attempt_id(stage: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    attempt_id = f"{timestamp}-{stage}-{secrets.token_hex(4)}"
    if not ATTEMPT_RE.fullmatch(attempt_id):  # pragma: no cover - defensive
        raise SubmissionError("generated an invalid ATTEMPT_ID")
    return attempt_id


def write_json_exclusive(path: Path, value: object) -> None:
    """Create one immutable JSON record without replacing prior evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise SubmissionError(f"refusing to overwrite submission record: {path}") from exc


@contextmanager
def submission_lock(run_dir: Path, stage: str) -> Iterable[None]:
    """Serialize duplicate checking and submission for one run/stage."""

    lock_path = run_dir / "submissions" / stage / ".submission.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SubmissionError(
                f"another {stage} submission process holds the run lock: {lock_path}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve_context(config_path: Path, run_dir: Path, stage: str) -> SubmissionContext:
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise SubmissionError(f"campaign config does not exist: {config_path}")
    run_dir = safe_run_dir(run_dir)
    if not run_dir.is_dir():
        raise SubmissionError(f"prepared run directory does not exist: {run_dir}")
    config, validation = validate_config(config_path)
    policy_stage = "structure" if stage == "relax" else "preflight"
    if stage == "relax":
        manifest = verify_manifest(config, config_path, run_dir, stage=policy_stage)
    else:
        # Preflight consumes an already accepted structure.  Preserve the
        # upstream workflow hashes as provenance, but allow reviewed downstream
        # code fixes; each new submission/attempt records its current code hash.
        manifest = verify_upstream_manifest(
            config, config_path, run_dir, stage=policy_stage
        )
    config_sha = validation.get("config_sha256")
    if not isinstance(config_sha, str) or not SHA256_RE.fullmatch(config_sha):
        raise SubmissionError("config validation has no valid config_sha256")
    if config_sha != sha256_path(config_path):
        raise SubmissionError("config SHA-256 changed during submission validation")
    return SubmissionContext(config_path, run_dir, config, manifest, config_sha)


def require_passing_gate(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise SubmissionError(f"{description} is missing: {path}")
    gate = load_json(path)
    if gate.get("pass") is not True:
        raise SubmissionError(f"{description} has not passed: {path}")
    return gate


def require_relax_gate(context: SubmissionContext) -> None:
    require_passing_gate(context.run_dir / "relax" / "final" / "gate.json", "tight-relax gate")
    unitcell = context.run_dir / "relax" / "final" / "unitcell.in"
    if not unitcell.is_file():
        raise SubmissionError(f"accepted tight-relax unit cell is missing: {unitcell}")


def require_imported_acceptance(
    context: SubmissionContext,
) -> dict[str, Any] | None:
    """Replay an imported accepted structure before downstream submission."""

    if context.manifest.get("accepted_structure_import") is None:
        return None
    from accepted_structure_import import verify_imported_acceptance

    try:
        result = verify_imported_acceptance(context.config_path, context.run_dir)
    except (CampaignError, OSError, ValueError, KeyError) as exc:
        raise SubmissionError(
            f"accepted-structure import replay failed: {exc}"
        ) from exc
    if result.get("healthy") is not True:
        raise SubmissionError("accepted-structure import replay did not pass")
    return result


def require_single_polish_release(context: SubmissionContext) -> None:
    """Enforce the one-shot diagnostic gate for a reviewed polish run."""

    pointer = context.manifest.get("relax_polish")
    if pointer is None:
        return
    if context.manifest.get("relax_recovery") is not None:
        raise SubmissionError("a polish run cannot also be an automatic recovery run")
    if (
        not isinstance(pointer, Mapping)
        or pointer.get("maximum_attempts") != 1
        or pointer.get("automatic_submission_allowed") is not False
    ):
        raise SubmissionError("invalid single-polish release pointer")
    relative_gate = pointer.get("diagnostic_gate")
    if not isinstance(relative_gate, str) or not relative_gate:
        raise SubmissionError("single-polish release lacks its diagnostic gate")
    gate_path = (context.run_dir / relative_gate).resolve()
    try:
        gate_path.relative_to(context.run_dir)
    except ValueError as exc:
        raise SubmissionError("single-polish diagnostic gate escapes RUN_DIR") from exc
    if sha256_path(gate_path) != pointer.get("diagnostic_gate_sha256"):
        raise SubmissionError("single-polish diagnostic gate hash mismatch")
    gate = require_passing_gate(gate_path, "force-consistency diagnostic gate")
    if gate.get("structure_accepted") is not False or gate.get("preflight_unlocked") is not False:
        raise SubmissionError("diagnostic gate must not accept a structure or unlock preflight")
    prior_attempts = context.run_dir / "slurm_attempts" / "relax"
    if prior_attempts.is_dir() and any(path.is_dir() for path in prior_attempts.iterdir()):
        raise SubmissionError("the single reviewed polish attempt has already been consumed")
    prior_submissions = context.run_dir / "submissions" / "relax"
    if prior_submissions.is_dir() and any(path.is_dir() for path in prior_submissions.iterdir()):
        raise SubmissionError("the single reviewed polish submission has already been consumed")


def require_production_selection(config: Mapping[str, Any]) -> None:
    production = required(config, "production")
    if not isinstance(production, Mapping):
        raise SubmissionError("production config must be an object")
    if production.get("selection_required") is not False:
        raise SubmissionError("production selection is still required; force submission is blocked")
    if not production.get("selected_supercell") or not production.get("selected_cutoff"):
        raise SubmissionError("selected_supercell and selected_cutoff must both be recorded")
    if production.get("automatic_submission_allowed") is not True:
        raise SubmissionError("production.automatic_submission_allowed is not true")


def require_force_gate(context: SubmissionContext) -> None:
    """Replay the canonical finalizer gate/index/receipt and their live hashes."""

    final = context.run_dir / "force" / "final"
    gate_path = final / "gate.json"
    index_path = final / "index.json"
    if not gate_path.is_file() or not index_path.is_file():
        raise SubmissionError(
            "postprocessing requires the canonical force/final gate and index"
        )
    if any(
        path.is_symlink()
        for path in (context.run_dir / "force", final, gate_path, index_path)
    ):
        raise SubmissionError("canonical force-final evidence may not use symlinks")
    gate = load_json(gate_path)
    index = load_json(index_path)
    if (
        gate.get("schema_version") != 1
        or gate.get("stage") != "force_dataset_gate"
        or gate.get("pass") is not True
        or gate.get("production_dataset_complete") is not True
        or gate.get("eligible_for_force_constant_construction") is not True
        or gate.get("scientific_results_claimed") is not False
        or gate.get("scope") != "audited production force dataset readiness only"
    ):
        raise SubmissionError("canonical force gate schema or scope is invalid")
    if (
        index.get("schema_version") != 1
        or index.get("stage") != "force_dataset_index"
        or index.get("material") != context.config["material"]["formula"]
        or index.get("config") != str(context.config_path)
        or index.get("config_sha256") != context.config_sha256
        or index.get("force_dataset_ready_for_fc2_fc3_construction") is not True
    ):
        raise SubmissionError("canonical force index schema or campaign identity is invalid")
    if (
        gate.get("material") != index.get("material")
        or gate.get("config_sha256") != context.config_sha256
        or gate.get("index_sha256") != sha256_path(index_path)
    ):
        raise SubmissionError("canonical force gate does not bind its index/config")

    def indexed_file(raw_path: Any, digest: Any, label: str) -> Path:
        if (
            not isinstance(raw_path, str)
            or not Path(raw_path).is_absolute()
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
        ):
            raise SubmissionError(f"invalid indexed {label} path/hash")
        raw = Path(raw_path)
        resolved = raw.resolve()
        if (
            resolved == context.run_dir
            or not resolved.is_relative_to(context.run_dir)
            or "READY_TO_ATTACH" in raw.parts
            or not resolved.is_file()
        ):
            raise SubmissionError(f"indexed {label} is missing or outside RUN_DIR")
        current = raw
        while True:
            if current.is_symlink():
                raise SubmissionError(f"indexed {label} path may not contain a symlink")
            if current.resolve() == context.run_dir:
                break
            parent = current.parent
            if parent == current:
                raise SubmissionError(f"indexed {label} path does not reach RUN_DIR")
            current = parent
        if sha256_path(resolved) != digest:
            raise SubmissionError(f"indexed {label} hash mismatch")
        return resolved

    def indexed_reference(value: Any, label: str) -> Path:
        if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
            raise SubmissionError(f"invalid indexed {label} reference")
        return indexed_file(value["path"], value["sha256"], label)

    plan_path = indexed_file(
        index.get("plan"), index.get("plan_sha256"), "force-finalize plan"
    )
    if (
        gate.get("plan_sha256") != index.get("plan_sha256")
        or gate.get("plan_sha256") != sha256_path(plan_path)
    ):
        raise SubmissionError("canonical force gate/index plan hash mismatch")
    receipt_ref = index.get("finalize_receipt")
    receipt_path = indexed_reference(receipt_ref, "force-finalize receipt")
    if (
        receipt_path.parent.parent
        != context.run_dir / "slurm_attempts" / "force-finalize"
        or receipt_path.name != "force_finalize_receipt.json"
        or gate.get("finalize_receipt_sha256") != receipt_ref["sha256"]
    ):
        raise SubmissionError("force-finalize receipt is not canonical or gate-bound")
    receipt = load_json(receipt_path)

    backend_names = (
        "force_finalize.py",
        "campaign.py",
        "force_backend.py",
        "submit.py",
        "postprocess_backend.py",
        "qe_input.py",
        "qe_output.py",
    )
    expected_backends = {
        str(Path(__file__).with_name(name).resolve()): sha256_path(
            Path(__file__).with_name(name).resolve()
        )
        for name in backend_names
    }
    index_backends = index.get("audit_backend_sha256")
    if (
        index_backends != expected_backends
        or gate.get("audit_backend_sha256") != expected_backends
        or receipt.get("audit_backend_sha256") != expected_backends
    ):
        raise SubmissionError("force-finalize audit backend hashes are stale or forged")
    force_finalize_sha = sha256_path(Path(__file__).with_name("force_finalize.py"))
    if any(
        value != force_finalize_sha
        for value in (
            index.get("force_finalize_backend_sha256"),
            gate.get("force_finalize_backend_sha256"),
            receipt.get("force_finalize_backend_sha256"),
        )
    ):
        raise SubmissionError("force-finalize backend identity mismatch")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("stage") != "force_finalize"
        or receipt.get("pass") is not True
        or receipt.get("material") != index.get("material")
        or receipt.get("plan") != str(plan_path)
        or receipt.get("plan_sha256") != index.get("plan_sha256")
        or receipt.get("force_dataset_ready_for_fc2_fc3_construction") is not True
        or receipt.get("scientific_results_claimed") is not False
    ):
        raise SubmissionError("force-finalize receipt schema or identity is invalid")

    accepted = index.get("accepted_structure")
    if not isinstance(accepted, Mapping):
        raise SubmissionError("force index lacks accepted structure references")
    for name in ("gate", "provenance", "unitcell"):
        indexed_reference(accepted.get(name), f"accepted structure {name}")
    for name in (
        "preflight_inventory",
        "preflight_result",
        "dataset",
        "selection_receipt",
    ):
        indexed_reference(index.get(name), name.replace("_", " "))
    canonical = index.get("canonical_pristine")
    if not isinstance(canonical, Mapping):
        raise SubmissionError("canonical pristine force identity is missing")
    for stem in ("input", "output", "stderr"):
        indexed_file(
            canonical.get(f"{stem}_path"),
            canonical.get(f"{stem}_sha256"),
            f"canonical pristine {stem}",
        )
    artifacts = index.get("artifacts")
    required_ids = index.get("required_fc3_displacement_ids")
    if (
        not isinstance(artifacts, list)
        or not artifacts
        or any(not isinstance(item, Mapping) for item in artifacts)
        or not isinstance(required_ids, list)
        or [item.get("displacement_id") for item in artifacts] != required_ids
    ):
        raise SubmissionError("force index displacement artifact domain is invalid")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise SubmissionError("force index contains a malformed artifact")
        displacement_id = artifact.get("displacement_id")
        for stem in ("input", "output", "stderr"):
            indexed_file(
                artifact.get(f"{stem}_path"),
                artifact.get(f"{stem}_sha256"),
                f"displacement {displacement_id} {stem}",
            )
    batches = index.get("batches")
    if not isinstance(batches, list) or not batches:
        raise SubmissionError("force index has no audited production batches")
    batch_refs = (
        "collection",
        "force_manifest",
        "task_map",
        "budget_receipt",
        "budget_ledger_reservation",
        "submission_request",
        "submission_result",
        "submission_summary",
        "collector_request",
        "collector_result",
        "scheduler_accounting",
        "scheduler_accounting_status",
    )
    for batch in batches:
        if not isinstance(batch, Mapping):
            raise SubmissionError("force index contains a malformed production batch")
        for name in batch_refs:
            indexed_reference(
                batch.get(name), f"batch {batch.get('batch_id')} {name}"
            )
        raw_artifacts = batch.get("raw_artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise SubmissionError("force index batch lacks raw force artifacts")
        for raw in raw_artifacts:
            if not isinstance(raw, Mapping) or not isinstance(
                raw.get("files_sha256"), Mapping
            ):
                raise SubmissionError("force index contains malformed raw force evidence")
            attempt_path = Path(str(raw.get("attempt_path", "")))
            for name, digest in raw["files_sha256"].items():
                if not isinstance(name, str) or Path(name).name != name:
                    raise SubmissionError("force index contains an unsafe raw filename")
                indexed_file(
                    str(attempt_path / name),
                    digest,
                    f"batch raw task {raw.get('task_id')} {name}",
                )


def validate_task_map(path: Path, run_dir: Path, hard_cap: int) -> tuple[Path, int, str]:
    path = path.resolve()
    try:
        path.relative_to(run_dir)
    except ValueError as exc:
        raise SubmissionError(f"TASK_MAP must be inside RUN_DIR: {path}") from exc
    if "READY_TO_ATTACH" in path.parts:
        raise SubmissionError("TASK_MAP may not be inside READY_TO_ATTACH")
    if not path.is_file():
        raise SubmissionError(f"TASK_MAP does not exist: {path}")

    rows: list[tuple[int, str]] = []
    header_seen = False
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = raw_line.split("\t")
        first = fields[0].strip()
        if not rows and not header_seen and first.lower() in {"task_id", "task", "index"}:
            header_seen = True
            continue
        if len(fields) < 2:
            raise SubmissionError(f"TASK_MAP line {line_number} is not tab-separated data")
        if not first.isdigit():
            raise SubmissionError(f"TASK_MAP line {line_number} has a non-integer task id")
        rows.append((int(first), raw_line))

    if not rows:
        raise SubmissionError("TASK_MAP contains no tasks")
    expected = list(range(len(rows)))
    actual = [item[0] for item in rows]
    if actual != expected:
        raise SubmissionError("TASK_MAP task ids must be unique, ordered, and exactly 0..N-1")
    if len(rows) > hard_cap:
        raise SubmissionError(
            f"TASK_MAP has {len(rows)} tasks, above configured hard cap {hard_cap}"
        )
    return path, len(rows), sha256_path(path)


def format_slurm_time(hours: Any) -> str:
    """Render an exactly second-resolved positive budgeted walltime."""

    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        raise SubmissionError("budget receipt walltime_hours must be numeric")
    seconds_float = float(hours) * 3600
    if (
        not math.isfinite(seconds_float)
        or seconds_float <= 0
        or not math.isclose(seconds_float, round(seconds_float), abs_tol=1e-9)
    ):
        raise SubmissionError(
            "budget receipt walltime must be positive and exactly representable in seconds"
        )
    seconds = int(round(seconds_float))
    days, remainder = divmod(seconds, 24 * 3600)
    hours_part, remainder = divmod(remainder, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if days:
        return f"{days}-{hours_part:02d}:{minutes:02d}:{seconds_part:02d}"
    return f"{hours_part:02d}:{minutes:02d}:{seconds_part:02d}"


def validate_force_bundle(
    context: SubmissionContext, task_map: Path
) -> tuple[Path, int, str, Path, dict[str, Any], Path, dict[str, Any]]:
    """Validate the immutable force manifest and its resource receipt."""

    hard_cap_value = required(context.config, "displacements.hard_cap")
    if isinstance(hard_cap_value, bool) or not isinstance(hard_cap_value, int):
        raise SubmissionError("displacements.hard_cap must be an integer")
    resolved, task_count, task_map_sha = validate_task_map(
        task_map, context.run_dir, hard_cap_value + 2
    )
    bundle = resolved.parent
    manifest_path = bundle / "force_manifest.json"
    receipt_path = bundle / "budget_receipt.json"
    if not manifest_path.is_file() or not receipt_path.is_file():
        raise SubmissionError(
            "force task map requires adjacent force_manifest.json and budget_receipt.json"
        )
    manifest = load_json(manifest_path)
    receipt = load_json(receipt_path)
    manifest_sha = sha256_path(manifest_path)
    receipt_sha = sha256_path(receipt_path)
    if manifest.get("schema_version") != 1 or manifest.get("stage") != "force":
        raise SubmissionError("unsupported force manifest schema/stage")
    mode = manifest.get("mode")
    if mode not in {"pilot", "production"}:
        raise SubmissionError("force manifest mode must be pilot or production")
    if manifest.get("material") != context.config["material"]["formula"]:
        raise SubmissionError("force manifest belongs to another material")
    if manifest.get("config_sha256") != context.config_sha256:
        raise SubmissionError("force manifest was prepared from another configuration")
    if (
        manifest.get("task_map_sha256") != task_map_sha
        or manifest.get("task_count") != task_count
        or not isinstance(manifest.get("tasks"), list)
        or len(manifest["tasks"]) != task_count
    ):
        raise SubmissionError("force manifest does not bind the exact task map/domain")
    columns = ("task_id", "displacement_id", "role", "input_path", "input_sha256")
    try:
        with resolved.open(newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t", strict=True))
    except csv.Error as exc:
        raise SubmissionError("force TASK_MAP contains malformed TSV quoting") from exc
    if not rows or tuple(rows[0]) != columns:
        raise SubmissionError("force TASK_MAP header must be task_id/displacement_id/role/input_path/input_sha256 in that order")
    if len(rows) != task_count + 1 or any(len(row) != len(columns) for row in rows[1:]):
        raise SubmissionError("force TASK_MAP must contain exactly five fields per task and no blank/comment rows")
    pristine_count = 0
    displacement_ids: set[int] = set()
    original_input_hashes: dict[int, str] = {}
    for index, (row, task) in enumerate(zip(rows[1:], manifest["tasks"])):
        if not isinstance(task, Mapping):
            raise SubmissionError(f"force manifest task {index} is not a mapping")
        if type(task.get("task_id")) is not int or task["task_id"] != index or row[0] != str(index):
            raise SubmissionError("force task ids must be unique, ordered, and exactly 0..N-1 in map and manifest")
        if type(task.get("displacement_id")) is not int:
            raise SubmissionError("force displacement_id must be an integer")
        if any(key not in task or str(task[key]) != value for key,value in zip(columns,row)):
            raise SubmissionError(f"force TASK_MAP row {index} differs from manifest.tasks")
        role, displacement_id = task["role"], task["displacement_id"]
        if role == "pristine":
            if displacement_id != 0:
                raise SubmissionError("pristine tasks must use displacement_id 0")
            pristine_count += 1
        elif role == "displacement":
            if displacement_id <= 0 or (mode == "production" and displacement_id in displacement_ids):
                raise SubmissionError("displacement task IDs must be unique positive integers")
            if displacement_id in original_input_hashes and task["input_sha256"] != original_input_hashes[displacement_id]:
                raise SubmissionError("pilot duplicate input SHA-256 differs from its original displacement task")
            original_input_hashes.setdefault(displacement_id, task["input_sha256"])
            displacement_ids.add(displacement_id)
        else:
            raise SubmissionError("force task role must be pristine or displacement")
        if not isinstance(task["input_path"], str) or not Path(task["input_path"]).is_absolute():
            raise SubmissionError("force input_path must be an absolute path")
        input_path = Path(task["input_path"]).resolve()
        if input_path == bundle or not input_path.is_relative_to(bundle) or "READY_TO_ATTACH" in input_path.parts:
            raise SubmissionError("force input must be a strict descendant of the immutable bundle")
        digest = task["input_sha256"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) or not input_path.is_file() or sha256_path(input_path) != digest:
            raise SubmissionError(f"force input file missing or SHA-256 mismatch: {input_path}")
    if mode == "production" and pristine_count != 1:
        raise SubmissionError("production force bundle requires exactly one pristine task")
    if mode == "pilot" and pristine_count not in (1,2):
        raise SubmissionError("pilot force bundle requires one or two pristine tasks")
    if mode == "pilot":
        spec = manifest.get("pilot_spec")
        if not isinstance(spec, Mapping):
            raise SubmissionError("pilot force bundle requires explicit pilot_spec task semantics")
        original_ids, duplicate_ids = spec.get("displacement_ids"), spec.get("duplicate_displacement_ids", [])
        pristine_repetitions = spec.get("pristine_repetitions", 1)
        if (
            type(pristine_repetitions) is not int
            or pristine_repetitions not in (1,2)
            or not isinstance(original_ids, list)
            or not original_ids
            or any(type(value) is not int or value <= 0 for value in original_ids)
            or len(set(original_ids)) != len(original_ids)
            or not isinstance(duplicate_ids, list)
            or any(type(value) is not int or value not in original_ids for value in duplicate_ids)
        ):
            raise SubmissionError("pilot_spec must explicitly identify unique original IDs and valid duplicate associations")
        expected_ids = [0]*pristine_repetitions + original_ids + duplicate_ids
        if [task["displacement_id"] for task in manifest["tasks"]] != expected_ids:
            raise SubmissionError("pilot task order differs from declared pristine/original/duplicate semantics")
    backend = Path(__file__).with_name("force_backend.py")
    if manifest.get("backend_sha256") != sha256_path(backend):
        raise SubmissionError("force backend changed after bundle preparation")
    workflow = manifest.get("workflow_sha256")
    if not isinstance(workflow, Mapping) or not workflow:
        raise SubmissionError("force manifest has no workflow hash set")
    for raw_path, digest in workflow.items():
        path = Path(raw_path)
        if (
            not path.is_absolute()
            or not path.is_file()
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            or sha256_path(path) != digest
        ):
            raise SubmissionError(f"force workflow evidence changed: {path}")
    if manifest.get("budget_receipt_sha256") != receipt_sha:
        raise SubmissionError("force manifest budget-receipt hash mismatch")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("material") != manifest["material"]
        or receipt.get("task_map_sha256") != task_map_sha
        or receipt.get("task_count") != task_count
    ):
        raise SubmissionError("budget receipt does not bind the force task map")
    expected_policy = canonical_sha256(context.config["resource_budget"])
    if receipt.get("resource_policy_sha256") != expected_policy:
        raise SubmissionError("budget receipt resource policy mismatch")
    phase = receipt.get("phase")
    if phase not in {"initial", "validation", "production"}:
        raise SubmissionError("budget receipt phase is invalid")
    if (mode == "production") != (phase == "production"):
        raise SubmissionError("force mode and budget phase disagree")
    if mode == "pilot":
        from force_backend import audit_signed_pilot_dataset, validate_initial_pilot_composition
        signed = manifest.get("signed_pilot_dataset")
        if not isinstance(signed, Mapping) or not isinstance(signed.get("dataset_dir"), str):
            raise SubmissionError("pilot force bundle requires bound signed-pilot dataset evidence")
        try:
            audited = audit_signed_pilot_dataset(Path(signed["dataset_dir"]), context.run_dir,
                context.config, manifest["settings"], manifest["pilot_spec"],
                expected_manifest_sha256=signed.get("expected_manifest_sha256"))
            if audited != signed:
                raise SubmissionError("signed pilot dataset re-audit differs from force manifest")
            if phase == "initial":
                validate_initial_pilot_composition(manifest["pilot_spec"], audited["task_kinds"])
                if task_count != 6 or pristine_count != 2:
                    raise SubmissionError("initial pilot must contain exactly six SCFs including two pristine")
        except (CampaignError, KeyError, TypeError, ValueError) as exc:
            raise SubmissionError(f"signed pilot dataset gate failed: {exc}") from exc
        evidence = manifest.get("evidence_sha256", {})
        if any(evidence.get(path) != digest for path,digest in signed["files_sha256"].items()):
            raise SubmissionError("force manifest does not bind every signed pilot dataset file")
        pilot_code = Path(__file__).with_name("pilot_dataset.py")
        if workflow.get(str(pilot_code)) != sha256_path(pilot_code):
            raise SubmissionError("force workflow does not freeze pilot_dataset.py")
    if mode == "production":
        require_production_selection(context.config)
        selection = manifest.get("selection_validation")
        if not isinstance(selection, Mapping) or selection.get("pass") is not True:
            raise SubmissionError("production force manifest lacks passing pilot evidence")
    elif manifest.get("selection_validation") is not None:
        raise SubmissionError("pilot manifest may not claim production selection evidence")
    from force_backend import verify_selection_provenance
    try:
        verify_selection_provenance(manifest, context.run_dir, config_path=context.config_path)
    except (CampaignError, KeyError, TypeError, ValueError) as exc:
        raise SubmissionError(f"force selection provenance gate failed: {exc}") from exc
    ranks = receipt.get("mpi_ranks")
    concurrency = receipt.get("maximum_concurrency")
    if (
        isinstance(ranks, bool)
        or not isinstance(ranks, int)
        or ranks < 1
        or isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or not 1 <= concurrency <= 2
    ):
        raise SubmissionError("budget receipt has invalid ranks or concurrency")
    if receipt.get("maximum_technical_retries_per_task") != 1:
        raise SubmissionError("budget receipt retry policy mismatch")
    # Parse here so malformed or unrepresentable time is rejected before sbatch.
    format_slurm_time(receipt.get("walltime_hours"))
    ledger = context.run_dir / ".force_budget"
    if not ledger.is_dir():
        raise SubmissionError("material force-budget ledger is missing")
    from force_backend import replay_budget_ledger
    try:
        ledger_records = replay_budget_ledger(context.run_dir, context.config)
    except CampaignError as exc:
        raise SubmissionError(f"budget ledger replay failed: {exc}") from exc
    matching = [
        item["path"] for item in ledger_records
        if item["record"]["receipt_path"] == str(receipt_path.resolve())
        and item["record"]["receipt_sha256"] == receipt_sha
    ]
    if len(matching) != 1:
        raise SubmissionError("budget receipt is not uniquely anchored in this material ledger")
    return (
        resolved,
        task_count,
        task_map_sha,
        manifest_path,
        manifest,
        receipt_path,
        receipt,
    )


def safe_export_value(name: str, value: Path | str) -> str:
    rendered = str(value)
    if not rendered or any(character in rendered for character in (",", "\n", "\r", "\x00")):
        raise SubmissionError(f"{name} cannot be represented safely in sbatch --export")
    return rendered


def stage_plan(
    context: SubmissionContext,
    stage: str,
    *,
    attempt_id: str,
    task_map: Path | None = None,
    max_in_flight: int | None = None,
) -> StagePlan:
    if stage not in STAGE_SCRIPTS:
        raise SubmissionError(f"unsupported stage: {stage}")
    if not ATTEMPT_RE.fullmatch(attempt_id):
        raise SubmissionError(f"invalid ATTEMPT_ID: {attempt_id}")
    script = SLURM_DIR / STAGE_SCRIPTS[stage]
    if not script.is_file():
        raise SubmissionError(f"Slurm stage script is missing: {script}")
    cluster_env = SLURM_DIR / "cluster.env"
    if not cluster_env.is_file():
        raise SubmissionError(f"Slurm cluster environment is missing: {cluster_env}")
    account = required(context.config, "scheduler.slurm_account")
    if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", account):
        raise SubmissionError("scheduler.slurm_account is invalid")

    exports = {
        "CAMPAIGN_CONFIG": safe_export_value("CAMPAIGN_CONFIG", context.config_path),
        "RUN_DIR": safe_export_value("RUN_DIR", context.run_dir),
        "ATTEMPT_ID": safe_export_value("ATTEMPT_ID", attempt_id),
        "P3_SLURM_DIR": safe_export_value("P3_SLURM_DIR", SLURM_DIR),
    }
    array: str | None = None
    task_count: int | None = None
    task_map_sha: str | None = None
    resolved_task_map: Path | None = None
    force_manifest_path: Path | None = None
    force_manifest_sha: str | None = None
    budget_receipt_path: Path | None = None
    budget_receipt_sha: str | None = None
    force_mode: str | None = None
    scheduler_options: tuple[str, ...] = ()

    if stage == "relax":
        if context.manifest.get("accepted_structure_import") is not None:
            raise SubmissionError(
                "an imported accepted-structure RUN_DIR cannot submit a relax stage"
            )
        require_single_polish_release(context)
    elif stage == "preflight":
        require_imported_acceptance(context)
        require_relax_gate(context)
    elif stage == "force":
        require_imported_acceptance(context)
        require_relax_gate(context)
        if task_map is None:
            raise SubmissionError("force submission requires an explicit --task-map")
        (
            resolved_task_map,
            task_count,
            task_map_sha,
            force_manifest_path,
            force_manifest,
            budget_receipt_path,
            budget_receipt,
        ) = validate_force_bundle(context, task_map)
        force_manifest_sha = sha256_path(force_manifest_path)
        budget_receipt_sha = sha256_path(budget_receipt_path)
        force_mode = str(force_manifest["mode"])
        concurrency = int(budget_receipt["maximum_concurrency"])
        if max_in_flight is not None and (
            isinstance(max_in_flight, bool)
            or not isinstance(max_in_flight, int)
            or max_in_flight != concurrency
        ):
            raise SubmissionError(
                "--max-in-flight, when supplied, must equal the immutable budget receipt"
            )
        ranks = int(budget_receipt["mpi_ranks"])
        walltime = format_slurm_time(budget_receipt["walltime_hours"])
        scheduler_options = (f"--ntasks={ranks}", f"--time={walltime}")
        exports["FORCE_MANIFEST"] = safe_export_value(
            "FORCE_MANIFEST", force_manifest_path
        )
        exports["FORCE_BUDGET_RECEIPT"] = safe_export_value(
            "FORCE_BUDGET_RECEIPT", budget_receipt_path
        )
        exports["TASK_MAP"] = safe_export_value("TASK_MAP", resolved_task_map)
        array = f"0-{task_count - 1}%{min(concurrency, task_count)}"
    elif stage == "postprocess":
        require_imported_acceptance(context)
        require_production_selection(context.config)
        require_force_gate(context)

    return StagePlan(
        stage=stage,
        script=script,
        account=account,
        exports=exports,
        array=array,
        task_count=task_count,
        task_map=resolved_task_map,
        task_map_sha256=task_map_sha,
        force_manifest=force_manifest_path,
        force_manifest_sha256=force_manifest_sha,
        budget_receipt=budget_receipt_path,
        budget_receipt_sha256=budget_receipt_sha,
        force_mode=force_mode,
        scheduler_options=scheduler_options,
    )


def export_argument(exports: Mapping[str, str]) -> str:
    ordered = (
        "CAMPAIGN_CONFIG",
        "RUN_DIR",
        "ATTEMPT_ID",
        "P3_SLURM_DIR",
        "PRIMARY_STAGE",
        "PRIMARY_ATTEMPT_ID",
        "PRIMARY_JOB_ID",
        "PRIMARY_TASK_MAP_SHA256",
        "PRIMARY_FORCE_MANIFEST_SHA256",
        "TASK_MAP",
        "FORCE_MANIFEST",
        "FORCE_BUDGET_RECEIPT",
    )
    missing = [name for name in ordered[:4] if name not in exports]
    if missing:
        raise SubmissionError("missing mandatory Slurm exports: " + ", ".join(missing))
    pairs = [f"{name}={exports[name]}" for name in ordered if name in exports]
    extras = sorted(name for name in exports if name not in ordered)
    pairs.extend(f"{name}={exports[name]}" for name in extras)
    return "--export=ALL," + ",".join(pairs)


def sbatch_command(plan: StagePlan, *, dependency: str | None = None) -> list[str]:
    command = [
        "sbatch",
        "--parsable",
        f"--account={plan.account}",
    ]
    command.extend(plan.scheduler_options)
    command.append(export_argument(plan.exports))
    if plan.array is not None:
        command.append(f"--array={plan.array}")
    if dependency is not None:
        if not re.fullmatch(r"afterany:[0-9]+", dependency):
            raise SubmissionError(f"unsafe or unsupported dependency: {dependency}")
        command.append(f"--dependency={dependency}")
    command.append(str(plan.script))
    return command


def require_nibi_login() -> None:
    if os.environ.get("SLURM_JOB_ID"):
        raise SubmissionError("submit.py execute must run on a Nibi login node, not inside a job")
    cluster = os.environ.get("SLURM_CLUSTER_NAME", "").lower()
    hostname = socket.getfqdn().lower()
    hostname_is_nibi = bool(
        re.fullmatch(r"ic-l[0-9]+\.nibi\.sharcnet", hostname)
        or re.fullmatch(r"l[0-9]+", hostname)
        or re.match(r"^nibi(?:login)?[0-9]*(?:\.|$)", hostname)
    )
    if cluster != "nibi" and not hostname_is_nibi:
        raise SubmissionError(
            f"submit.py execute is restricted to a Nibi login node (detected {hostname!r})"
        )


def normalize_state(raw: str) -> str:
    state = raw.strip().upper().split()[0] if raw.strip() else ""
    return state.rstrip("+")


def scheduler_job_is_active(job_id: str) -> bool:
    if not job_id.isdigit():
        raise SubmissionError(f"invalid recorded Slurm job id: {job_id!r}")
    try:
        queued = subprocess.run(
            ["squeue", "--noheader", "--jobs", job_id, "--format=%T"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SubmissionError(f"cannot query squeue for prior job {job_id}: {exc}") from exc
    # Slurm may evict a just-finished job from squeue before sacct has been
    # consulted.  On Nibi that ordinary absence is reported as exit 1 plus
    # "Invalid job id specified", rather than an empty successful listing.
    # Only that exact absence case is allowed to fall through to accounting;
    # every other scheduler-query error remains fail closed.
    queue_reports_absent_job = (
        queued.returncode != 0
        and not queued.stdout.strip()
        and re.search(r"\bInvalid job id specified\b", queued.stderr, re.IGNORECASE)
        is not None
    )
    if queued.returncode != 0 and not queue_reports_absent_job:
        raise SubmissionError(
            f"squeue failed while checking prior job {job_id}: {queued.stderr.strip()}"
        )
    queue_states = [normalize_state(line) for line in queued.stdout.splitlines() if line.strip()]
    if queue_states:
        # squeue should expose only nonterminal work.  Unknown output is treated
        # as active rather than guessing that a duplicate is safe.
        return any(state not in TERMINAL_STATES for state in queue_states)

    try:
        accounting = subprocess.run(
            ["sacct", "--noheader", "--jobs", job_id, "--format=State", "--parsable2"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SubmissionError(f"cannot query sacct for prior job {job_id}: {exc}") from exc
    if accounting.returncode != 0:
        raise SubmissionError(
            f"sacct failed while checking prior job {job_id}: {accounting.stderr.strip()}"
        )
    states = [normalize_state(line.split("|", 1)[0]) for line in accounting.stdout.splitlines()]
    states = [state for state in states if state]
    if not states:
        raise SubmissionError(
            f"no scheduler state is available for recorded job {job_id}; "
            "manual reconciliation required"
        )
    return any(state not in TERMINAL_STATES for state in states)


def ensure_no_active_duplicate(run_dir: Path, stage: str) -> None:
    stage_root = run_dir / "submissions" / stage
    if not stage_root.is_dir():
        return
    for record_dir in sorted(path for path in stage_root.iterdir() if path.is_dir()):
        request = record_dir / "request.json"
        rejected = record_dir / "primary_rejected.json"
        uncertain = record_dir / "primary_uncertain.json"
        summary = record_dir / "submission.json"
        terminal = record_dir / "scheduler_terminal.json"
        if not request.is_file():
            raise SubmissionError(f"malformed submission record requires review: {record_dir}")
        if rejected.is_file() and not summary.exists():
            continue
        if uncertain.is_file():
            raise SubmissionError(
                f"uncertain prior sbatch response requires scheduler reconciliation: {record_dir}"
            )
        if terminal.is_file():
            continue
        if not summary.is_file():
            raise SubmissionError(
                f"incomplete or uncertain prior submission requires review: {record_dir}"
            )
        data = load_json(summary)
        job_ids = [data.get("primary_job_id")]
        collector = data.get("collector")
        if isinstance(collector, Mapping):
            job_ids.append(collector.get("job_id"))
        clean_ids = [str(job_id) for job_id in job_ids if job_id is not None]
        if not clean_ids:
            raise SubmissionError(f"submission record has no job id: {summary}")
        active = [job_id for job_id in clean_ids if scheduler_job_is_active(job_id)]
        if active:
            raise SubmissionError(
                f"active duplicate {stage} submission exists for this run: jobs {', '.join(active)}"
            )
        write_json_exclusive(
            terminal,
            {
                "checked_utc": utc_now(),
                "job_ids": clean_ids,
                "scheduler_states_terminal": True,
            },
        )


def parse_job_id(stdout: str) -> str:
    line = next((item.strip() for item in stdout.splitlines() if item.strip()), "")
    match = re.fullmatch(r"([0-9]+)(?:;[^\s;]+)?", line)
    if not match:
        raise SubmissionError(f"could not parse sbatch --parsable job id from {line!r}")
    return match.group(1)


def run_sbatch(command: Sequence[str]) -> tuple[str, dict[str, Any]]:
    try:
        completed = subprocess.run(
            list(command), text=True, capture_output=True, check=False
        )
    except OSError as exc:
        evidence = {
            "command": list(command),
            "invocation_error": str(exc),
            "finished_utc": utc_now(),
        }
        raise RejectedSubmissionError(f"failed to invoke sbatch: {exc}", evidence) from exc
    evidence = {
        "command": list(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "finished_utc": utc_now(),
    }
    if completed.returncode != 0:
        raise RejectedSubmissionError(
            f"sbatch failed with exit {completed.returncode}: {completed.stderr.strip()}",
            evidence,
        )
    try:
        job_id = parse_job_id(completed.stdout)
    except SubmissionError as exc:
        raise UncertainSubmissionError(
            "sbatch returned success but its job ID could not be proven; "
            "treat this submission as potentially active",
            evidence,
        ) from exc
    return job_id, evidence


def plan_report(
    context: SubmissionContext,
    stage: str,
    *,
    task_map: Path | None,
    max_in_flight: int | None,
) -> dict[str, Any]:
    preview = stage_plan(
        context,
        stage,
        attempt_id="GENERATED-ON-EXECUTE",
        task_map=task_map,
        max_in_flight=max_in_flight,
    )
    preview_command = sbatch_command(preview)
    return {
        "healthy": True,
        "mode": "plan",
        "stage": stage,
        "material": context.manifest.get("material"),
        "config": str(context.config_path),
        "config_sha256": context.config_sha256,
        "run_dir": str(context.run_dir),
        "task_map": str(preview.task_map) if preview.task_map else None,
        "task_map_sha256": preview.task_map_sha256,
        "task_count": preview.task_count,
        "array": preview.array,
        "force_mode": preview.force_mode,
        "force_manifest": str(preview.force_manifest) if preview.force_manifest else None,
        "force_manifest_sha256": preview.force_manifest_sha256,
        "budget_receipt": str(preview.budget_receipt) if preview.budget_receipt else None,
        "budget_receipt_sha256": preview.budget_receipt_sha256,
        "scheduler_options": list(preview.scheduler_options),
        "primary_command_template": preview_command,
        "collector": stage in COLLECTED_STAGES,
        "execute_requirement": (
            "Run execute with --expect-config-sha exactly equal to config_sha256; "
            "a new ATTEMPT_ID is generated for every sbatch call."
        ),
    }


def _request_record(
    context: SubmissionContext, plan: StagePlan, command: Sequence[str]
) -> dict[str, Any]:
    return {
        "created_utc": utc_now(),
        "stage": plan.stage,
        "attempt_id": plan.exports["ATTEMPT_ID"],
        "slurm_account": plan.account,
        "config": str(context.config_path),
        "config_sha256": context.config_sha256,
        "run_dir": str(context.run_dir),
        "run_manifest_sha256": sha256_path(context.run_dir / "run_manifest.json"),
        "submit_script_sha256": sha256_path(Path(__file__).resolve()),
        "stage_script_sha256": sha256_path(plan.script),
        "cluster_env_sha256": sha256_path(SLURM_DIR / "cluster.env"),
        "task_map": str(plan.task_map) if plan.task_map else None,
        "task_map_sha256": plan.task_map_sha256,
        "task_count": plan.task_count,
        "array": plan.array,
        "force_mode": plan.force_mode,
        "force_manifest": str(plan.force_manifest) if plan.force_manifest else None,
        "force_manifest_sha256": plan.force_manifest_sha256,
        "budget_receipt": str(plan.budget_receipt) if plan.budget_receipt else None,
        "budget_receipt_sha256": plan.budget_receipt_sha256,
        "scheduler_options": list(plan.scheduler_options),
        "command": list(command),
    }


def execute_submission(
    context: SubmissionContext,
    stage: str,
    *,
    expected_config_sha: str,
    task_map: Path | None,
    max_in_flight: int | None,
) -> dict[str, Any]:
    require_nibi_login()
    expected = expected_config_sha
    if not SHA256_RE.fullmatch(expected):
        raise SubmissionError(
            "--expect-config-sha must be exactly 64 lowercase hexadecimal characters"
        )
    if expected != context.config_sha256:
        raise SubmissionError(
            "configuration SHA-256 changed or was not copied from the current plan; "
            "nothing submitted"
        )
    with submission_lock(context.run_dir, stage):
        return _execute_locked(
            context,
            stage,
            task_map=task_map,
            max_in_flight=max_in_flight,
        )


def _execute_locked(
    context: SubmissionContext,
    stage: str,
    *,
    task_map: Path | None,
    max_in_flight: int | None,
) -> dict[str, Any]:
    ensure_no_active_duplicate(context.run_dir, stage)

    attempt_id = new_attempt_id(stage)
    plan = stage_plan(
        context,
        stage,
        attempt_id=attempt_id,
        task_map=task_map,
        max_in_flight=max_in_flight,
    )
    command = sbatch_command(plan)
    record_dir = context.run_dir / "submissions" / stage / attempt_id
    if record_dir.exists():
        raise SubmissionError(f"generated ATTEMPT_ID already exists: {record_dir}")
    write_json_exclusive(record_dir / "request.json", _request_record(context, plan, command))

    try:
        primary_job_id, primary_evidence = run_sbatch(command)
    except UncertainSubmissionError as exc:
        write_json_exclusive(
            record_dir / "primary_uncertain.json",
            {
                "finished_utc": utc_now(),
                "error": str(exc),
                "scheduler_acceptance_unknown": True,
                "evidence": exc.evidence,
            },
        )
        raise
    except RejectedSubmissionError as exc:
        write_json_exclusive(
            record_dir / "primary_rejected.json",
            {
                "finished_utc": utc_now(),
                "error": str(exc),
                "scheduler_acceptance_unknown": False,
                "evidence": exc.evidence,
            },
        )
        raise
    except SubmissionError as exc:
        # No unclassified post-invocation error is safe to retry blindly.
        write_json_exclusive(
            record_dir / "primary_uncertain.json",
            {
                "finished_utc": utc_now(),
                "error": str(exc),
                "scheduler_acceptance_unknown": True,
                "command": command,
            },
        )
        raise
    write_json_exclusive(
        record_dir / "primary_result.json",
        {**primary_evidence, "job_id": primary_job_id},
    )

    collector: dict[str, Any] | None = None
    if stage in COLLECTED_STAGES:
        collector_attempt = new_attempt_id("collect")
        collector_exports = dict(plan.exports)
        collector_exports["ATTEMPT_ID"] = collector_attempt
        collector_exports["PRIMARY_STAGE"] = safe_export_value(
            "PRIMARY_STAGE", stage
        )
        collector_exports["PRIMARY_ATTEMPT_ID"] = safe_export_value(
            "PRIMARY_ATTEMPT_ID", attempt_id
        )
        collector_exports["PRIMARY_JOB_ID"] = safe_export_value(
            "PRIMARY_JOB_ID", primary_job_id
        )
        if stage == "force":
            if plan.task_map_sha256 is None or plan.force_manifest_sha256 is None:
                raise SubmissionError(
                    "force collector cannot be submitted without primary plan hashes"
                )
            collector_exports["PRIMARY_TASK_MAP_SHA256"] = safe_export_value(
                "PRIMARY_TASK_MAP_SHA256", plan.task_map_sha256
            )
            collector_exports["PRIMARY_FORCE_MANIFEST_SHA256"] = safe_export_value(
                "PRIMARY_FORCE_MANIFEST_SHA256", plan.force_manifest_sha256
            )
        collector_plan = StagePlan(
            stage="collect",
            script=SLURM_DIR / "collect.sbatch",
            account=plan.account,
            exports=collector_exports,
            array=None,
            task_count=plan.task_count,
            task_map=plan.task_map,
            task_map_sha256=plan.task_map_sha256,
        )
        collector_command = sbatch_command(
            collector_plan, dependency=f"afterany:{primary_job_id}"
        )
        write_json_exclusive(
            record_dir / "collector_request.json",
            {
                "created_utc": utc_now(),
                "attempt_id": collector_attempt,
                "primary_stage": stage,
                "primary_attempt_id": attempt_id,
                "primary_job_id": primary_job_id,
                "dependency": f"afterany:{primary_job_id}",
                "command": collector_command,
            },
        )
        try:
            collector_job_id, collector_evidence = run_sbatch(collector_command)
        except SubmissionError as exc:
            write_json_exclusive(
                record_dir / "collector_error.json",
                {
                    "finished_utc": utc_now(),
                    "error": str(exc),
                    "command": collector_command,
                    "primary_job_id": primary_job_id,
                },
            )
            raise SubmissionError(
                f"primary job {primary_job_id} was submitted but its afterany collector was not; "
                "manual review is required"
            ) from exc
        write_json_exclusive(
            record_dir / "collector_result.json",
            {**collector_evidence, "job_id": collector_job_id},
        )
        collector = {
            "attempt_id": collector_attempt,
            "job_id": collector_job_id,
            "primary_stage": stage,
            "primary_attempt_id": attempt_id,
            "primary_job_id": primary_job_id,
            "dependency": f"afterany:{primary_job_id}",
            "command": collector_command,
        }

    summary = {
        "healthy": True,
        "mode": "execute",
        "submitted_utc": utc_now(),
        "stage": stage,
        "attempt_id": attempt_id,
        "primary_job_id": primary_job_id,
        "primary_command": command,
        "collector": collector,
        "config_sha256": context.config_sha256,
        "run_dir": str(context.run_dir),
        "task_map_sha256": plan.task_map_sha256,
        "task_count": plan.task_count,
        "array": plan.array,
        "force_mode": plan.force_mode,
        "force_manifest_sha256": plan.force_manifest_sha256,
        "budget_receipt_sha256": plan.budget_receipt_sha256,
        "scheduler_options": list(plan.scheduler_options),
        "record_dir": str(record_dir),
    }
    write_json_exclusive(record_dir / "submission.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("plan", "execute"):
        subparser = subparsers.add_parser(mode)
        subparser.add_argument("--stage", choices=sorted(STAGE_SCRIPTS), required=True)
        subparser.add_argument("--config", type=Path, required=True)
        subparser.add_argument("--run-dir", type=Path, required=True)
        subparser.add_argument("--task-map", type=Path)
        subparser.add_argument(
            "--max-in-flight",
            type=int,
            help=(
                "force only: optional cross-check that must equal the immutable "
                "budget receipt; the receipt always controls concurrency"
            ),
        )
        if mode == "execute":
            subparser.add_argument("--expect-config-sha", required=True)
    return parser


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        context = resolve_context(args.config, args.run_dir, args.stage)
        if args.mode == "plan":
            result = plan_report(
                context,
                args.stage,
                task_map=args.task_map,
                max_in_flight=args.max_in_flight,
            )
        else:
            result = execute_submission(
                context,
                args.stage,
                expected_config_sha=args.expect_config_sha,
                task_map=args.task_map,
                max_in_flight=args.max_in_flight,
            )
        print_json(result)
        return 0
    except (CampaignError, SubmissionError, OSError, ValueError, KeyError, TypeError) as exc:
        print_json({"healthy": False, "mode": args.mode, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

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
import stat
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
    select_preflight_candidates,
    required,
    strict_run_descendant,
    safe_run_dir,
    sha256_path,
    validate_config,
    verify_manifest,
    verify_upstream_manifest,
)


SLURM_DIR = (Path(__file__).resolve().parent / "slurm").resolve()
STAGE_SCRIPTS = {
    "diagnostic": "diagnostic.sbatch",
    "relax": "relax.sbatch",
    "preflight": "preflight.sbatch",
    "force": "force_array.sbatch",
    "postprocess": "postprocess.sbatch",
    "fire-pilot": "fire_pilot.sbatch",
    "fire-full": "fire_full.sbatch",
}
COLLECTED_STAGES = frozenset({"diagnostic", "relax", "force", "fire-pilot"})
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
    candidate_ids: tuple[str, ...] | None = None
    candidate_subset_sha256: str | None = None
    diagnostic_resource_sha256: str | None = None
    submitted_task_ids: tuple[int, ...] | None = None
    retry_collection: Path | None = None
    retry_collection_sha256: str | None = None
    hold_primary: bool = False


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

    if not path.parent.is_dir() or path.parent.is_symlink():
        raise SubmissionError(
            f"immutable submission record parent is missing or unsafe: {path.parent}"
        )
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise SubmissionError(f"refusing to overwrite submission record: {path}") from exc


def _strict_run_descendant(
    run_dir: Path,
    path: Path,
    label: str,
    *,
    require_exists: bool = False,
) -> Path:
    """Reject symlinks component-by-component and prove strict containment."""

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
                    raise SubmissionError(
                        f"{label} path contains a symlink: {ancestor}"
                    )
                if os.path.samefile(ancestor, root):
                    alias_root = ancestor
                    break
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
        if alias_root is None:
            raise SubmissionError(f"{label} must be a strict RUN_DIR descendant")
        relative = candidate_input.relative_to(alias_root)
    if not relative.parts:
        raise SubmissionError(f"{label} must be a strict RUN_DIR descendant")
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
            raise SubmissionError(f"{label} path contains a symlink: {current}")
    if require_exists and missing:
        raise SubmissionError(f"{label} does not exist: {candidate}")
    resolved = candidate.resolve(strict=require_exists)
    if resolved == root or not resolved.is_relative_to(root):
        raise SubmissionError(f"{label} resolves outside RUN_DIR")
    return candidate


def _ensure_run_directory(run_dir: Path, relative: Path, label: str) -> Path:
    """Create a RUN_DIR-relative directory chain without following symlinks."""

    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SubmissionError(f"{label} has an unsafe relative path")
    root = run_dir.resolve(strict=True)
    current = root
    for part in relative.parts:
        current = _strict_run_descendant(root, current / part, label)
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            try:
                os.mkdir(current, 0o750)
            except FileExistsError:
                pass
            mode = os.lstat(current).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SubmissionError(f"{label} is not a non-symlink directory: {current}")
        if current.resolve(strict=True) != current:
            raise SubmissionError(f"{label} directory containment changed: {current}")
    return current


def _reject_symlinks_below(run_dir: Path, root: Path, label: str) -> None:
    root = _strict_run_descendant(run_dir, root, label, require_exists=True)
    if not root.is_dir():
        raise SubmissionError(f"{label} is not a directory: {root}")
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            _strict_run_descendant(
                run_dir,
                Path(parent) / name,
                label,
                require_exists=True,
            )


@contextmanager
def submission_lock(run_dir: Path, stage: str) -> Iterable[None]:
    """Serialize duplicate checking and submission for one run/stage."""

    stage_root = _ensure_run_directory(
        run_dir, Path("submissions") / stage, f"{stage} submission root"
    )
    lock_path = _strict_run_descendant(
        run_dir, stage_root / ".submission.lock", f"{stage} submission lock"
    )
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise SubmissionError(f"cannot safely open submission lock: {lock_path}") from exc
    with os.fdopen(descriptor, "a+") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise SubmissionError(f"submission lock is not a regular file: {lock_path}")
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
    if stage == "diagnostic":
        from polish_recovery import verify_diagnostic_submission_ready

        try:
            manifest = verify_diagnostic_submission_ready(config_path, run_dir)
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            raise SubmissionError(
                f"reviewed diagnostic lineage is not submission-ready: {exc}"
            ) from exc
    elif stage in {"fire-pilot", "fire-full"}:
        from fire_recovery import verify_fire_submission_ready
        try:
            ready = verify_fire_submission_ready(config_path, run_dir, stage)
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            raise SubmissionError(f"FIRE lineage is not submission-ready: {exc}") from exc
        manifest = {"material": ready["material"], "fire_lineage_sha256": ready["lineage_sha256"]}
    elif stage == "relax":
        policy_stage = "structure"
        manifest = verify_manifest(config, config_path, run_dir, stage=policy_stage)
    else:
        policy_stage = "preflight"
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
    gate_path = _strict_run_descendant(
        context.run_dir,
        context.run_dir / relative_gate,
        "single-polish diagnostic gate",
        require_exists=True,
    )
    if not stat.S_ISREG(os.lstat(gate_path).st_mode):
        raise SubmissionError("single-polish diagnostic gate is not a regular file")
    if sha256_path(gate_path) != pointer.get("diagnostic_gate_sha256"):
        raise SubmissionError("single-polish diagnostic gate hash mismatch")
    gate = require_passing_gate(gate_path, "force-consistency diagnostic gate")
    if gate.get("structure_accepted") is not False or gate.get("preflight_unlocked") is not False:
        raise SubmissionError("diagnostic gate must not accept a structure or unlock preflight")
    prior_attempts = context.run_dir / "slurm_attempts" / "relax"
    if os.path.lexists(prior_attempts):
        prior_attempts = _strict_run_descendant(
            context.run_dir,
            prior_attempts,
            "single-polish Slurm attempts",
            require_exists=True,
        )
        _reject_symlinks_below(
            context.run_dir, prior_attempts, "single-polish Slurm attempts"
        )
        if any(prior_attempts.iterdir()):
            raise SubmissionError(
                "the single reviewed polish attempt has already been consumed"
            )
    prior_submissions = context.run_dir / "submissions" / "relax"
    if os.path.lexists(prior_submissions):
        prior_submissions = _strict_run_descendant(
            context.run_dir,
            prior_submissions,
            "single-polish submissions",
            require_exists=True,
        )
        _reject_symlinks_below(
            context.run_dir, prior_submissions, "single-polish submissions"
        )
        if any(
            path.name != ".submission.lock"
            for path in prior_submissions.iterdir()
        ):
            raise SubmissionError(
                "the single reviewed polish submission has already been consumed"
            )


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


def diagnostic_scheduler_options(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Render only the explicit, validated diagnostic allocation policy."""

    resources = required(config, "scheduler.diagnostic_resources")
    if not isinstance(resources, Mapping):
        raise SubmissionError("scheduler.diagnostic_resources must be an object")
    partition = resources.get("partition")
    if (
        not isinstance(partition, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]+", partition) is None
    ):
        raise SubmissionError("diagnostic partition is invalid")
    integers: dict[str, int] = {}
    for key in ("nodes", "ntasks", "cpus_per_task", "mem_per_cpu_mb"):
        value = resources.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SubmissionError(f"diagnostic {key} must be a positive integer")
        integers[key] = value
    walltime = format_slurm_time(resources.get("walltime_hours"))
    maximum_core_hours = resources.get("maximum_core_hours")
    expected_core_hours = (
        integers["ntasks"]
        * integers["cpus_per_task"]
        * float(resources["walltime_hours"])
    )
    if (
        isinstance(maximum_core_hours, bool)
        or not isinstance(maximum_core_hours, (int, float))
        or not math.isclose(
            float(maximum_core_hours), expected_core_hours, rel_tol=0, abs_tol=1e-12
        )
    ):
        raise SubmissionError(
            "diagnostic maximum_core_hours does not match the requested allocation"
        )
    return (
        f"--partition={partition}",
        f"--nodes={integers['nodes']}",
        f"--ntasks={integers['ntasks']}",
        f"--cpus-per-task={integers['cpus_per_task']}",
        f"--mem-per-cpu={integers['mem_per_cpu_mb']}M",
        f"--time={walltime}",
    )


def diagnostic_requested_walltime_minutes(config: Mapping[str, Any]) -> str:
    """Return the reviewed diagnostic walltime as an integer-minute export."""

    resources = required(config, "scheduler.diagnostic_resources")
    if not isinstance(resources, Mapping):
        raise SubmissionError("scheduler.diagnostic_resources must be an object")
    walltime_hours = resources.get("walltime_hours")
    if (
        isinstance(walltime_hours, bool)
        or not isinstance(walltime_hours, (int, float))
        or not math.isfinite(float(walltime_hours))
        or float(walltime_hours) <= 0
    ):
        raise SubmissionError("diagnostic walltime_hours must be positive")
    minutes = float(walltime_hours) * 60
    if not math.isclose(minutes, round(minutes), rel_tol=0, abs_tol=1e-12):
        raise SubmissionError("diagnostic walltime_hours must be whole minutes")
    return str(int(round(minutes)))


def validate_force_retry_collection(
    context: SubmissionContext,
    collection_path: Path,
    expected_sha256: str,
    *,
    force_manifest_sha256: str,
    task_map_sha256: str,
    task_count: int,
) -> tuple[Path, tuple[int, ...]]:
    """Authorize one retry array containing only proven technical failures."""

    if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(
        expected_sha256
    ):
        raise SubmissionError("retry collection SHA-256 must be 64 lowercase hex")
    collection_path = strict_run_descendant(
        context.run_dir, collection_path, "force retry collection"
    )
    if collection_path.is_symlink() or sha256_path(collection_path) != expected_sha256:
        raise SubmissionError("force retry collection hash mismatch")
    collection = load_json(collection_path)
    primary = collection.get("primary")
    entries = collection.get("entries")
    if (
        collection.get("schema_version") != 1
        or collection.get("stage") != "collect"
        or collection.get("collection_kind") != "force_array_batch"
        or collection.get("material") != context.config["material"]["formula"]
        or collection.get("force_mode") != "pilot"
        or collection.get("expected_task_count") != task_count
        or collection.get("collection_integrity_complete") is not True
        or collection.get("unfinished_or_invalid_count") != 0
        or collection.get("global_errors") != []
        or collection.get("accepted_success_count", 0)
        + collection.get("upstream_failure_count", 0) != task_count
        or not isinstance(primary, Mapping)
        or primary.get("force_manifest_sha256") != force_manifest_sha256
        or primary.get("task_map_sha256") != task_map_sha256
        or not isinstance(entries, list)
    ):
        raise SubmissionError("retry collection scope does not match this force bundle")
    records = primary.get("submission_records")
    if not isinstance(records, Mapping):
        raise SubmissionError("retry collection lacks replayable submit.py records")
    request_ref = records.get("primary_request")
    result_ref = records.get("primary_result")
    if not isinstance(request_ref, Mapping) or not isinstance(result_ref, Mapping):
        raise SubmissionError("retry collection submission record refs are malformed")
    submitted_ids = collection.get("submitted_task_ids")
    if (
        submitted_ids != list(range(task_count))
        or collection.get("submitted_task_count") != task_count
        or len(entries) != task_count
        or sorted(
            entry.get("task_id")
            for entry in entries
            if isinstance(entry, Mapping) and type(entry.get("task_id")) is int
        )
        != list(range(task_count))
    ):
        raise SubmissionError(
            "retry authorization requires the original full primary collection"
        )
    try:
        collector_attempt = strict_run_descendant(
            context.run_dir,
            Path(str(collection.get("collector_attempt", ""))),
            "retry source collector attempt",
        )
    except CampaignError as exc:
        raise SubmissionError(f"invalid retry source collector attempt: {exc}") from exc
    if (
        collector_attempt.parent
        != context.run_dir / "slurm_attempts" / "collect"
        or ATTEMPT_RE.fullmatch(collector_attempt.name) is None
        or not collector_attempt.is_dir()
    ):
        raise SubmissionError(
            "retry source collector is not at the exact slurm_attempts/collect location"
        )
    try:
        from campaign import _force_submission_binding

        request_path = strict_run_descendant(
            context.run_dir, Path(str(request_ref.get("path", ""))),
            "retry collection primary request"
        )
        request = load_json(request_path)
        if (
            request.get("retry_collection") is not None
            or request.get("retry_collection_sha256") is not None
        ):
            raise SubmissionError(
                "a retry-derived collection cannot authorize another retry"
            )
        replayed = _force_submission_binding(
            config_path=context.config_path,
            run_dir=context.run_dir,
            collector_attempt=collector_attempt,
            primary_attempt_id=str(primary.get("attempt_id", "")),
            primary_job_id=str(primary.get("job_id", "")),
            force_manifest_sha256=force_manifest_sha256,
            task_map_sha256=task_map_sha256,
            submitted_task_ids=collection.get("submitted_task_ids", []),
            expected_primary_request_sha256=str(request_ref.get("sha256", "")),
            expected_primary_result_sha256=str(result_ref.get("sha256", "")),
            expected_primary_stage_script_sha256=str(
                request.get("stage_script_sha256", "")
            ),
            require_held_primary=True,
        )
    except (CampaignError, OSError, KeyError, TypeError, ValueError) as exc:
        raise SubmissionError(f"retry collection submission replay failed: {exc}") from exc
    if replayed != records:
        raise SubmissionError("retry collection submit.py records changed")
    retryable: list[int] = []
    technical_states = {"NODE_FAIL", "BOOT_FAIL", "PREEMPTED"}
    for entry in entries:
        if not isinstance(entry, Mapping) or type(entry.get("task_id")) is not int:
            raise SubmissionError("retry collection contains a malformed task entry")
        task_id = entry["task_id"]
        states = {
            normalize_state(str(row.get("State", "")))
            for row in entry.get("scheduler_records", [])
            if isinstance(row, Mapping)
        }
        usage = entry.get("resource_usage")
        elapsed = usage.get("elapsed_seconds") if isinstance(usage, Mapping) else None
        cpus = usage.get("allocated_cpus") if isinstance(usage, Mapping) else None
        timelimit = usage.get("timelimit_minutes") if isinstance(usage, Mapping) else None
        core_hours = usage.get("core_hours") if isinstance(usage, Mapping) else None
        expected_core_hours = (
            elapsed * cpus / 3600
            if type(elapsed) is int and type(cpus) is int else None
        )
        if (
            entry.get("errors") != []
            or cpus != 32
            or timelimit != 120
            or type(elapsed) is not int
            or not 0 <= elapsed <= 7200
            or isinstance(core_hours, bool)
            or not isinstance(core_hours, (int, float))
            or not math.isfinite(float(core_hours))
            or not math.isclose(
                float(core_hours), float(expected_core_hours),
                rel_tol=0, abs_tol=1e-12,
            )
            or not 0 <= float(core_hours) <= 64
        ):
            raise SubmissionError(
                "original primary collection entry lacks exact released resource evidence"
            )
        if entry.get("outcome") == "accepted_success":
            continue
        if (
            entry.get("outcome") != "upstream_failed"
            or task_id not in range(task_count)
            or len(states & technical_states) != 1
            or states - technical_states
        ):
            raise SubmissionError(
                "retry collection includes a nontechnical or unresolved failure"
            )
        retryable.append(task_id)
    if not retryable or len(set(retryable)) != len(retryable):
        raise SubmissionError("retry collection has no unique failed-task subset")
    if set(retryable) != {
        entry["task_id"]
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("outcome") != "accepted_success"
    }:
        raise SubmissionError("retry task subset is ambiguous")
    return collection_path, tuple(sorted(retryable))


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
        if phase == "initial":
            from initial_pilot import (
                replay_initial_pilot_release,
                validate_release_use,
            )

            binding = manifest.get("initial_pilot_release")
            if not isinstance(binding, Mapping) or set(binding) != {
                "path", "sha256", "consumption_identity"
            }:
                raise SubmissionError(
                    "initial pilot force manifest requires one exact release binding"
                )
            release_digest = binding.get("sha256")
            if not isinstance(release_digest, str) or not SHA256_RE.fullmatch(
                release_digest
            ):
                raise SubmissionError("initial pilot release SHA-256 is invalid")
            try:
                release_path = strict_run_descendant(
                    context.run_dir,
                    Path(str(binding.get("path", ""))),
                    "initial pilot release",
                )
                release = replay_initial_pilot_release(
                    release_path,
                    config_path=context.config_path,
                    run_dir=context.run_dir,
                    expected_release_sha256=release_digest,
                )
                validate_release_use(
                    release,
                    force_spec=manifest["pilot_spec"],
                    resource_request={
                        "phase": phase,
                        "mpi_ranks": receipt.get("mpi_ranks"),
                        "walltime_hours": receipt.get("walltime_hours"),
                        "max_concurrency": receipt.get("maximum_concurrency"),
                    },
                )
            except (CampaignError, KeyError, TypeError, ValueError) as exc:
                raise SubmissionError(
                    f"initial pilot release replay failed: {exc}"
                ) from exc
            if (
                binding.get("consumption_identity")
                != release.get("consumption_identity")
            ):
                raise SubmissionError("initial pilot consumption identity mismatch")
            if [task["displacement_id"] for task in manifest["tasks"]] != [
                0, 0, 1, 3, 1, 3
            ]:
                raise SubmissionError(
                    "initial pilot task order must be exactly [0,0,1,3,1,3]"
                )
            resources = release.get("contract", {}).get("resources", {})
            if (
                receipt.get("maximum_technical_retries_per_task")
                != resources.get("maximum_technical_retries_per_task")
                or receipt.get("reserved_core_hours")
                != resources.get("maximum_reserved_core_hours")
                or receipt.get("approved_total_core_hours") is not None
            ):
                raise SubmissionError(
                    "initial pilot budget differs from the released exact-six ceiling"
                )
            signed_manifest_path = strict_run_descendant(
                context.run_dir,
                Path(signed["dataset_dir"]) / "pilot_dataset_manifest.json",
                "signed initial pilot manifest",
            )
            signed_manifest = load_json(signed_manifest_path)
            signed_binding = signed_manifest.get("initial_pilot_release")
            if (
                not isinstance(signed_binding, Mapping)
                or set(signed_binding) != {
                    "path",
                    "sha256",
                    "consumption_identity",
                    "consumption_path",
                    "consumption_sha256",
                }
                or any(
                    signed_binding.get(key) != binding.get(key)
                    for key in ("path", "sha256", "consumption_identity")
                )
            ):
                raise SubmissionError(
                    "signed pilot dataset and force manifest bind different releases"
                )
            consumption_digest = signed_binding.get("consumption_sha256")
            if not isinstance(consumption_digest, str) or not SHA256_RE.fullmatch(
                consumption_digest
            ):
                raise SubmissionError("initial pilot consumption SHA-256 is invalid")
            consumption_path = strict_run_descendant(
                context.run_dir,
                Path(str(signed_binding.get("consumption_path", ""))),
                "initial pilot consumption claim",
            )
            if sha256_path(consumption_path) != consumption_digest:
                raise SubmissionError("initial pilot consumption claim hash mismatch")
            consumption = load_json(consumption_path)
            valid_created = (
                isinstance(consumption, Mapping)
                and isinstance(consumption.get("created_utc"), str)
                and bool(consumption["created_utc"])
            )
            expected_consumption = {
                "schema_version": 1,
                "stage": "initial_pilot_release_consumption",
                "consumption_identity": release["consumption_identity"],
                "release_path": str(release_path),
                "release_sha256": release_digest,
                "dataset_dir": str(Path(signed["dataset_dir"]).resolve()),
                "created_utc": consumption.get("created_utc") if valid_created else None,
            }
            if not valid_created or consumption != expected_consumption:
                raise SubmissionError("initial pilot consumption claim is invalid")
            evidence = manifest.get("evidence_sha256", {})
            if (
                not isinstance(evidence, Mapping)
                or evidence.get(str(release_path)) != release_digest
                or evidence.get(str(consumption_path)) != consumption_digest
            ):
                raise SubmissionError(
                    "force manifest does not hash-bind release and consumption claim"
                )
            initial_code = Path(__file__).with_name("initial_pilot.py")
            if workflow.get(str(initial_code)) != sha256_path(initial_code):
                raise SubmissionError("force workflow does not freeze initial_pilot.py")
        elif manifest.get("initial_pilot_release") is not None:
            raise SubmissionError(
                "validation pilot may not carry an initial-pilot release"
            )
    if mode == "production":
        if manifest.get("initial_pilot_release") is not None:
            raise SubmissionError(
                "production force manifest may not carry an initial-pilot release"
            )
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
    candidate_ids: Sequence[str] | None = None,
    retry_collection: Path | None = None,
    expected_retry_collection_sha256: str | None = None,
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
        "P3_EXPECTED_CONFIG_SHA256": context.config_sha256,
        "P3_SUBMIT_SCRIPT_SHA256": sha256_path(Path(__file__).resolve()),
        "P3_STAGE_SCRIPT_SHA256": sha256_path(script),
        "P3_CLUSTER_ENV_SHA256": sha256_path(cluster_env),
        "P3_CAMPAIGN_CLI_SHA256": sha256_path(
            Path(__file__).resolve().with_name("campaign.py")
        ),
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
    selected_candidate_ids: tuple[str, ...] | None = None
    candidate_subset_sha256: str | None = None
    diagnostic_resource_sha256: str | None = None
    submitted_task_ids: tuple[int, ...] | None = None
    retry_collection_path: Path | None = None
    retry_collection_sha256: str | None = None
    hold_primary = False

    if candidate_ids is not None and stage != "preflight":
        raise SubmissionError("--candidate-id is valid only for the preflight stage")
    if (retry_collection is not None or expected_retry_collection_sha256 is not None) and stage != "force":
        raise SubmissionError("--retry-collection is valid only for the force stage")

    if stage == "diagnostic":
        from polish_recovery import verify_diagnostic_submission_ready

        try:
            ready = verify_diagnostic_submission_ready(
                context.config_path, context.run_dir
            )
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            raise SubmissionError(f"reviewed diagnostic is not ready: {exc}") from exc
        if ready.get("config_sha256") != context.config_sha256:
            raise SubmissionError("diagnostic lineage/config SHA256 mismatch")
        scheduler_options = diagnostic_scheduler_options(context.config)
        diagnostic_resource_sha256 = canonical_sha256(
            required(context.config, "scheduler.diagnostic_resources")
        )
        exports["P3_DIAGNOSTIC_RESOURCE_SHA256"] = safe_export_value(
            "P3_DIAGNOSTIC_RESOURCE_SHA256", diagnostic_resource_sha256
        )
        exports["P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES"] = safe_export_value(
            "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES",
            diagnostic_requested_walltime_minutes(context.config),
        )
        exports["P3_DIAGNOSTIC_LINEAGE_SHA256"] = safe_export_value(
            "P3_DIAGNOSTIC_LINEAGE_SHA256", ready["lineage_sha256"]
        )
        exports["P3_DIAGNOSTIC_BACKEND_SHA256"] = sha256_path(
            Path(__file__).resolve().with_name("polish_recovery.py")
        )
    elif stage in {"fire-pilot", "fire-full"}:
        from fire_recovery import verify_fire_submission_ready
        try:
            ready = verify_fire_submission_ready(context.config_path, context.run_dir, stage)
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            raise SubmissionError(f"FIRE lineage is not ready: {exc}") from exc
        resources = required(context.config, "reviewed_fire_recovery.resources")
        hours = resources["pilot_walltime_hours"] if stage == "fire-pilot" else resources["full_walltime_hours"]
        scheduler_options = ("--partition=cpubase_bycore_b2", "--nodes=1", "--ntasks=32", "--cpus-per-task=1", "--mem-per-cpu=2000M", f"--time={format_slurm_time(hours)}")
        exports["P3_FIRE_RECOVERY_SHA256"] = sha256_path(Path(__file__).resolve().with_name("fire_recovery.py"))
        exports["P3_FIRE_LINEAGE_SHA256"] = ready["lineage_sha256"]
        exports["P3_FIRE_RELEASE_SHA256"] = ready["release_sha256"]
        exports["P3_GIT_COMMIT"] = ready["git_commit"]
        exports["P3_FIRE_REQUESTED_WALLTIME_MINUTES"] = "120" if stage == "fire-pilot" else "720"
    elif stage == "relax":
        if context.manifest.get("accepted_structure_import") is not None:
            raise SubmissionError(
                "an imported accepted-structure RUN_DIR cannot submit a relax stage"
            )
        require_single_polish_release(context)
    elif stage == "preflight":
        require_imported_acceptance(context)
        require_relax_gate(context)
        if candidate_ids is not None:
            try:
                _, selection = select_preflight_candidates(
                    context.config, candidate_ids
                )
            except CampaignError as exc:
                raise SubmissionError(str(exc)) from exc
            selected_candidate_ids = tuple(selection["candidate_ids"])
            candidate_subset_sha256 = selection["candidate_subset_sha256"]
            exports["P3_PREFLIGHT_CANDIDATE_IDS"] = safe_export_value(
                "P3_PREFLIGHT_CANDIDATE_IDS", ":".join(selected_candidate_ids)
            )
            exports["P3_PREFLIGHT_CANDIDATE_SHA256"] = safe_export_value(
                "P3_PREFLIGHT_CANDIDATE_SHA256", candidate_subset_sha256
            )
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
        hold_primary = (
            force_mode == "pilot"
            and budget_receipt.get("phase") == "initial"
            and force_manifest.get("initial_pilot_release") is not None
        )
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
        if retry_collection is not None or expected_retry_collection_sha256 is not None:
            if retry_collection is None or expected_retry_collection_sha256 is None:
                raise SubmissionError(
                    "force retry requires --retry-collection and --expect-retry-collection-sha together"
                )
            retry_collection_path, submitted_task_ids = validate_force_retry_collection(
                context,
                retry_collection,
                expected_retry_collection_sha256,
                force_manifest_sha256=force_manifest_sha,
                task_map_sha256=task_map_sha,
                task_count=task_count,
            )
            retry_collection_sha256 = expected_retry_collection_sha256
            exports["P3_FORCE_RETRY_EVIDENCE"] = safe_export_value(
                "P3_FORCE_RETRY_EVIDENCE", retry_collection_path
            )
            exports["P3_FORCE_RETRY_EVIDENCE_SHA256"] = retry_collection_sha256
        else:
            submitted_task_ids = tuple(range(task_count))
        task_selector = ",".join(str(value) for value in submitted_task_ids)
        exports["P3_FORCE_TASK_IDS"] = task_selector
        array_domain = (
            f"0-{task_count - 1}"
            if submitted_task_ids == tuple(range(task_count))
            else task_selector
        )
        array = f"{array_domain}%{concurrency}"
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
        candidate_ids=selected_candidate_ids,
        candidate_subset_sha256=candidate_subset_sha256,
        diagnostic_resource_sha256=diagnostic_resource_sha256,
        submitted_task_ids=submitted_task_ids,
        retry_collection=retry_collection_path,
        retry_collection_sha256=retry_collection_sha256,
        hold_primary=hold_primary,
    )


def export_argument(exports: Mapping[str, str]) -> str:
    ordered = (
        "CAMPAIGN_CONFIG",
        "RUN_DIR",
        "ATTEMPT_ID",
        "P3_SLURM_DIR",
        "P3_EXPECTED_CONFIG_SHA256",
        "P3_SUBMIT_SCRIPT_SHA256",
        "P3_STAGE_SCRIPT_SHA256",
        "P3_CLUSTER_ENV_SHA256",
        "P3_CAMPAIGN_CLI_SHA256",
        "P3_PREFLIGHT_CANDIDATE_IDS",
        "P3_PREFLIGHT_CANDIDATE_SHA256",
        "P3_DIAGNOSTIC_RESOURCE_SHA256",
        "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES",
        "P3_DIAGNOSTIC_LINEAGE_SHA256",
        "P3_DIAGNOSTIC_BACKEND_SHA256",
        "P3_FIRE_RECOVERY_SHA256",
        "P3_FIRE_LINEAGE_SHA256",
        "P3_FIRE_RELEASE_SHA256",
        "P3_GIT_COMMIT",
        "P3_FIRE_REQUESTED_WALLTIME_MINUTES",
        "PRIMARY_STAGE",
        "PRIMARY_ATTEMPT_ID",
        "PRIMARY_JOB_ID",
        "PRIMARY_TASK_MAP_SHA256",
        "PRIMARY_FORCE_MANIFEST_SHA256",
        "PRIMARY_REQUEST_SHA256",
        "PRIMARY_RESULT_SHA256",
        "PRIMARY_STAGE_SCRIPT_SHA256",
        "P3_FORCE_TASK_IDS",
        "P3_FORCE_RETRY_EVIDENCE",
        "P3_FORCE_RETRY_EVIDENCE_SHA256",
        "TASK_MAP",
        "FORCE_MANIFEST",
        "FORCE_BUDGET_RECEIPT",
    )
    mandatory = ordered[:9]
    missing = [name for name in mandatory if name not in exports]
    if missing:
        raise SubmissionError("missing mandatory Slurm exports: " + ", ".join(missing))
    pairs = [f"{name}={exports[name]}" for name in ordered if name in exports]
    extras = sorted(name for name in exports if name not in ordered)
    if extras:
        raise SubmissionError(
            "unsupported Slurm exports outside the explicit allow-list: "
            + ", ".join(extras)
        )
    # Omitting ALL is deliberate: only these reviewed values (plus Slurm's own
    # SLURM_* variables) enter the job.  In particular BASH_ENV, runner knobs,
    # and stale candidate selectors from the login shell are never inherited.
    return "--export=" + ",".join(pairs)


def sbatch_command(plan: StagePlan, *, dependency: str | None = None) -> list[str]:
    command = [
        "sbatch",
        "--parsable",
        f"--account={plan.account}",
    ]
    if (plan.stage == "fire-pilot" or plan.hold_primary) and dependency is None:
        command.append("--hold")
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
    if not os.path.lexists(stage_root):
        return
    stage_root = _strict_run_descendant(
        run_dir, stage_root, f"{stage} submission root", require_exists=True
    )
    if not stage_root.is_dir():
        raise SubmissionError(f"submission stage root is not a directory: {stage_root}")
    record_dirs: list[Path] = []
    for entry in sorted(stage_root.iterdir()):
        if entry.name == ".submission.lock":
            if entry.is_symlink() or not entry.is_file():
                raise SubmissionError(f"submission lock is unsafe: {entry}")
            continue
        _strict_run_descendant(
            run_dir, entry, f"{stage} submission record", require_exists=True
        )
        if entry.is_symlink() or not entry.is_dir():
            raise SubmissionError(f"malformed submission record requires review: {entry}")
        _reject_symlinks_below(run_dir, entry, f"{stage} submission record")
        record_dirs.append(entry)
    for record_dir in record_dirs:
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
    candidate_ids: Sequence[str] | None = None,
    retry_collection: Path | None = None,
    expected_retry_collection_sha256: str | None = None,
) -> dict[str, Any]:
    preview = stage_plan(
        context,
        stage,
        attempt_id="GENERATED-ON-EXECUTE",
        task_map=task_map,
        max_in_flight=max_in_flight,
        candidate_ids=candidate_ids,
        retry_collection=retry_collection,
        expected_retry_collection_sha256=expected_retry_collection_sha256,
    )
    preview_command = None if stage == "fire-full" else sbatch_command(preview)
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
        "candidate_ids": list(preview.candidate_ids) if preview.candidate_ids else None,
        "candidate_subset_sha256": preview.candidate_subset_sha256,
        "diagnostic_resource_sha256": preview.diagnostic_resource_sha256,
        "submitted_task_ids": list(preview.submitted_task_ids or ()),
        "retry_collection": str(preview.retry_collection) if preview.retry_collection else None,
        "retry_collection_sha256": preview.retry_collection_sha256,
        "hold_primary": preview.hold_primary,
        "diagnostic_requested_walltime_minutes": preview.exports.get(
            "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES"
        ),
        "primary_command_template": preview_command,
        "collector": stage in COLLECTED_STAGES,
        "execution_released": stage != "fire-full",
        "execute_requirement": (
            "Unavailable: FIRE full execution remains hard-locked; a passing pilot is review evidence only."
            if stage == "fire-full" else
            "Run execute with --expect-config-sha exactly equal to config_sha256; "
            "an explicit preflight subset also requires --expect-candidate-subset-sha "
            "exactly equal to candidate_subset_sha256; a new ATTEMPT_ID is generated "
            "for every sbatch call."
        ),
    }


def _request_record(
    context: SubmissionContext, plan: StagePlan, command: Sequence[str]
) -> dict[str, Any]:
    manifest_path = context.run_dir / "run_manifest.json"
    workflow_sha256 = {
        "submit.py": plan.exports["P3_SUBMIT_SCRIPT_SHA256"],
        "campaign.py": plan.exports["P3_CAMPAIGN_CLI_SHA256"],
        "cluster.env": plan.exports["P3_CLUSTER_ENV_SHA256"],
        plan.script.name: plan.exports["P3_STAGE_SCRIPT_SHA256"],
    }
    if plan.stage == "diagnostic":
        workflow_sha256["polish_recovery.py"] = plan.exports[
            "P3_DIAGNOSTIC_BACKEND_SHA256"
        ]
    if plan.stage in {"fire-pilot", "fire-full"}:
        workflow_sha256["fire_recovery.py"] = plan.exports["P3_FIRE_RECOVERY_SHA256"]
    return {
        "created_utc": utc_now(),
        "stage": plan.stage,
        "attempt_id": plan.exports["ATTEMPT_ID"],
        "slurm_account": plan.account,
        "config": str(context.config_path),
        "config_sha256": context.config_sha256,
        "run_dir": str(context.run_dir),
        "run_manifest_sha256": (
            sha256_path(manifest_path) if manifest_path.is_file() else None
        ),
        "polish_lineage_sha256": (
            context.manifest.get("lineage_sha256")
            if plan.stage == "diagnostic"
            else None
        ),
        "fire_lineage_sha256": (
            plan.exports.get("P3_FIRE_LINEAGE_SHA256")
            if plan.stage in {"fire-pilot", "fire-full"}
            else None
        ),
        "fire_release_sha256": (
            plan.exports.get("P3_FIRE_RELEASE_SHA256")
            if plan.stage == "fire-pilot"
            else None
        ),
        "git_commit": plan.exports.get("P3_GIT_COMMIT"),
        "submit_script_sha256": sha256_path(Path(__file__).resolve()),
        "stage_script_sha256": sha256_path(plan.script),
        "cluster_env_sha256": sha256_path(SLURM_DIR / "cluster.env"),
        "workflow_sha256": workflow_sha256,
        "task_map": str(plan.task_map) if plan.task_map else None,
        "task_map_sha256": plan.task_map_sha256,
        "task_count": plan.task_count,
        "submitted_task_ids": list(plan.submitted_task_ids or ()),
        "retry_collection": str(plan.retry_collection) if plan.retry_collection else None,
        "retry_collection_sha256": plan.retry_collection_sha256,
        "hold_primary": plan.hold_primary,
        "array": plan.array,
        "force_mode": plan.force_mode,
        "force_manifest": str(plan.force_manifest) if plan.force_manifest else None,
        "force_manifest_sha256": plan.force_manifest_sha256,
        "budget_receipt": str(plan.budget_receipt) if plan.budget_receipt else None,
        "budget_receipt_sha256": plan.budget_receipt_sha256,
        "scheduler_options": list(plan.scheduler_options),
        "candidate_ids": list(plan.candidate_ids) if plan.candidate_ids else None,
        "candidate_subset_sha256": plan.candidate_subset_sha256,
        "diagnostic_resource_sha256": plan.diagnostic_resource_sha256,
        "diagnostic_requested_walltime_minutes": plan.exports.get(
            "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES"
        ),
        "diagnostic_lineage_sha256": plan.exports.get(
            "P3_DIAGNOSTIC_LINEAGE_SHA256"
        ),
        "command": list(command),
    }


def execute_submission(
    context: SubmissionContext,
    stage: str,
    *,
    expected_config_sha: str,
    task_map: Path | None,
    max_in_flight: int | None,
    candidate_ids: Sequence[str] | None = None,
    expected_candidate_subset_sha: str | None = None,
    retry_collection: Path | None = None,
    expected_retry_collection_sha256: str | None = None,
) -> dict[str, Any]:
    return _execute_locked(
        context,
        stage,
        expected_config_sha=expected_config_sha,
        task_map=task_map,
        max_in_flight=max_in_flight,
        candidate_ids=candidate_ids,
        expected_candidate_subset_sha=expected_candidate_subset_sha,
        retry_collection=retry_collection,
        expected_retry_collection_sha256=expected_retry_collection_sha256,
    )


def _guard_submission_entry(func):
    """Apply login, exact-config and file-lock gates to every callable entry.

    The only function that can call ``run_sbatch`` is captured by this closure,
    not exposed as a separately importable unguarded helper.
    """

    def guarded(
        context: SubmissionContext,
        stage: str,
        *,
        expected_config_sha: str | None = None,
        task_map: Path | None,
        max_in_flight: int | None,
        candidate_ids: Sequence[str] | None = None,
        expected_candidate_subset_sha: str | None = None,
        retry_collection: Path | None = None,
        expected_retry_collection_sha256: str | None = None,
    ) -> dict[str, Any]:
        if stage == "fire-full":
            raise SubmissionError(
                "FIRE execution is hard-locked: independent lineage replay and execution receipt verification are not implemented"
            )
        require_nibi_login()
        if not isinstance(expected_config_sha, str) or not SHA256_RE.fullmatch(
            expected_config_sha
        ):
            raise SubmissionError(
                "--expect-config-sha must be exactly 64 lowercase hexadecimal characters"
            )
        if expected_config_sha != context.config_sha256:
            raise SubmissionError(
                "configuration SHA-256 changed or was not copied from the current plan; "
                "nothing submitted"
            )
        if candidate_ids is None:
            if expected_candidate_subset_sha is not None:
                raise SubmissionError(
                    "--expect-candidate-subset-sha is forbidden without an explicit preflight subset"
                )
        else:
            if stage != "preflight":
                raise SubmissionError("--candidate-id is valid only for the preflight stage")
            if (
                not isinstance(expected_candidate_subset_sha, str)
                or SHA256_RE.fullmatch(expected_candidate_subset_sha) is None
            ):
                raise SubmissionError(
                    "explicit preflight execute requires the exact 64-character "
                    "--expect-candidate-subset-sha printed by plan"
                )
            try:
                _, reviewed_selection = select_preflight_candidates(
                    context.config, candidate_ids
                )
            except CampaignError as exc:
                raise SubmissionError(str(exc)) from exc
            if (
                reviewed_selection["candidate_subset_sha256"]
                != expected_candidate_subset_sha
            ):
                raise SubmissionError(
                    "preflight candidate subset SHA256 changed or was not copied "
                    "from the current plan; nothing submitted"
                )
        with submission_lock(context.run_dir, stage):
            return func(
                context,
                stage,
                expected_config_sha=expected_config_sha,
                task_map=task_map,
                max_in_flight=max_in_flight,
                candidate_ids=candidate_ids,
                expected_candidate_subset_sha=expected_candidate_subset_sha,
                retry_collection=retry_collection,
                expected_retry_collection_sha256=expected_retry_collection_sha256,
            )

    return guarded


@_guard_submission_entry
def _execute_locked(
    context: SubmissionContext,
    stage: str,
    *,
    expected_config_sha: str | None = None,
    task_map: Path | None,
    max_in_flight: int | None,
    candidate_ids: Sequence[str] | None = None,
    expected_candidate_subset_sha: str | None = None,
    retry_collection: Path | None = None,
    expected_retry_collection_sha256: str | None = None,
) -> dict[str, Any]:
    ensure_no_active_duplicate(context.run_dir, stage)

    attempt_id = new_attempt_id(stage)
    plan = stage_plan(
        context,
        stage,
        attempt_id=attempt_id,
        task_map=task_map,
        max_in_flight=max_in_flight,
        candidate_ids=candidate_ids,
        retry_collection=retry_collection,
        expected_retry_collection_sha256=expected_retry_collection_sha256,
    )
    if plan.candidate_subset_sha256 != expected_candidate_subset_sha:
        raise SubmissionError(
            "preflight candidate subset SHA256 changed or was not copied from the current plan; nothing submitted"
        )
    command = sbatch_command(plan)
    record_dir = _strict_run_descendant(
        context.run_dir,
        context.run_dir / "submissions" / stage / attempt_id,
        f"{stage} submission attempt",
    )
    if os.path.lexists(record_dir):
        raise SubmissionError(f"generated ATTEMPT_ID already exists: {record_dir}")
    record_dir = _ensure_run_directory(
        context.run_dir,
        Path("submissions") / stage / attempt_id,
        f"{stage} submission attempt",
    )
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
        {
            **primary_evidence,
            "stage": stage,
            "attempt_id": attempt_id,
            "job_id": primary_job_id,
            "config_sha256": context.config_sha256,
        },
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
        collector_exports["PRIMARY_REQUEST_SHA256"] = sha256_path(
            record_dir / "request.json"
        )
        collector_exports["PRIMARY_RESULT_SHA256"] = sha256_path(
            record_dir / "primary_result.json"
        )
        collector_exports["PRIMARY_STAGE_SCRIPT_SHA256"] = plan.exports[
            "P3_STAGE_SCRIPT_SHA256"
        ]
        collector_exports["P3_STAGE_SCRIPT_SHA256"] = sha256_path(
            SLURM_DIR / "collect.sbatch"
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
                "stage": "collect",
                "attempt_id": collector_attempt,
                "slurm_account": plan.account,
                "config_sha256": context.config_sha256,
                "primary_stage": stage,
                "primary_attempt_id": attempt_id,
                "primary_job_id": primary_job_id,
                "primary_request_sha256": collector_exports[
                    "PRIMARY_REQUEST_SHA256"
                ],
                "primary_result_sha256": collector_exports[
                    "PRIMARY_RESULT_SHA256"
                ],
                "primary_stage_script_sha256": collector_exports[
                    "PRIMARY_STAGE_SCRIPT_SHA256"
                ],
                "collector_script_sha256": collector_exports[
                    "P3_STAGE_SCRIPT_SHA256"
                ],
                "submit_script_sha256": collector_exports[
                    "P3_SUBMIT_SCRIPT_SHA256"
                ],
                "cluster_env_sha256": collector_exports[
                    "P3_CLUSTER_ENV_SHA256"
                ],
                "campaign_cli_sha256": collector_exports[
                    "P3_CAMPAIGN_CLI_SHA256"
                ],
                "diagnostic_lineage_sha256": collector_exports.get(
                    "P3_DIAGNOSTIC_LINEAGE_SHA256"
                ),
                "diagnostic_resource_sha256": collector_exports.get(
                    "P3_DIAGNOSTIC_RESOURCE_SHA256"
                ),
                "diagnostic_requested_walltime_minutes": collector_exports.get(
                    "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES"
                ),
                "fire_lineage_sha256": collector_exports.get(
                    "P3_FIRE_LINEAGE_SHA256"
                ),
                "fire_release_sha256": collector_exports.get(
                    "P3_FIRE_RELEASE_SHA256"
                ),
                "fire_backend_sha256": collector_exports.get(
                    "P3_FIRE_RECOVERY_SHA256"
                ),
                "fire_requested_walltime_minutes": collector_exports.get(
                    "P3_FIRE_REQUESTED_WALLTIME_MINUTES"
                ),
                "git_commit": collector_exports.get("P3_GIT_COMMIT"),
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
            {
                **collector_evidence,
                "stage": "collect",
                "attempt_id": collector_attempt,
                "job_id": collector_job_id,
                "primary_stage": stage,
                "primary_attempt_id": attempt_id,
                "primary_job_id": primary_job_id,
                "config_sha256": context.config_sha256,
            },
        )
        if stage == "fire-pilot" or plan.hold_primary:
            release_command = ["scontrol", "release", primary_job_id]
            attachment_kind = (
                "fire_pilot_afterany_collector_attachment"
                if stage == "fire-pilot"
                else "initial_pilot_afterany_collector_attachment"
            )
            attachment = {
                "schema_version": 1,
                "kind": attachment_kind,
                "primary_attempt_id": attempt_id,
                "primary_job_id": primary_job_id,
                "primary_request_sha256": sha256_path(record_dir / "request.json"),
                "primary_result_sha256": sha256_path(record_dir / "primary_result.json"),
                "collector_attempt_id": collector_attempt,
                "collector_job_id": collector_job_id,
                "collector_request_sha256": sha256_path(record_dir / "collector_request.json"),
                "collector_result_sha256": sha256_path(record_dir / "collector_result.json"),
                "collector_dependency": f"afterany:{primary_job_id}",
                "primary_command": command,
                "collector_command": collector_command,
                "release_command": release_command,
                "config_sha256": context.config_sha256,
                "fire_lineage_sha256": plan.exports.get("P3_FIRE_LINEAGE_SHA256"),
                "fire_release_sha256": plan.exports.get("P3_FIRE_RELEASE_SHA256"),
                "workflow_sha256": load_json(record_dir / "request.json")[
                    "workflow_sha256"
                ],
            }
            if plan.hold_primary:
                attachment.update(
                    force_manifest_sha256=plan.force_manifest_sha256,
                    task_map_sha256=plan.task_map_sha256,
                    submitted_task_ids=list(plan.submitted_task_ids or ()),
                    retry_collection_sha256=plan.retry_collection_sha256,
                )
            write_json_exclusive(
                record_dir / "collector_attachment.json",
                attachment,
            )
            try:
                released = subprocess.run(
                    release_command,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except OSError as exc:
                write_json_exclusive(
                    record_dir / "primary_release_uncertain.json",
                    {
                        "command": release_command,
                        "invocation_error": str(exc),
                        "finished_utc": utc_now(),
                    },
                )
                raise SubmissionError(
                    "held primary remains fail-closed without a proven scontrol release"
                ) from exc
            release_evidence = {
                "command": release_command,
                "returncode": released.returncode,
                "stdout": released.stdout,
                "stderr": released.stderr,
                "finished_utc": utc_now(),
            }
            if released.returncode != 0:
                write_json_exclusive(
                    record_dir / "primary_release_rejected.json", release_evidence
                )
                raise SubmissionError(
                    "held primary remains held because scontrol release failed"
                )
            write_json_exclusive(
                record_dir / "primary_release.json",
                {
                    **release_evidence,
                    "primary_attempt_id": attempt_id,
                    "primary_job_id": primary_job_id,
                    "collector_attachment_sha256": sha256_path(
                        record_dir / "collector_attachment.json"
                    ),
                },
            )
        collector = {
            "attempt_id": collector_attempt,
            "job_id": collector_job_id,
            "primary_stage": stage,
            "primary_attempt_id": attempt_id,
            "primary_job_id": primary_job_id,
            "dependency": f"afterany:{primary_job_id}",
            "command": collector_command,
            "request_sha256": sha256_path(record_dir / "collector_request.json"),
            "result_sha256": sha256_path(record_dir / "collector_result.json"),
        }
        if stage == "fire-pilot" or plan.hold_primary:
            collector["attachment_sha256"] = sha256_path(
                record_dir / "collector_attachment.json"
            )
            collector["primary_release_sha256"] = sha256_path(
                record_dir / "primary_release.json"
            )

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
        "slurm_account": plan.account,
        "polish_lineage_sha256": plan.exports.get(
            "P3_DIAGNOSTIC_LINEAGE_SHA256"
        ),
        "fire_lineage_sha256": plan.exports.get("P3_FIRE_LINEAGE_SHA256"),
        "fire_release_sha256": plan.exports.get("P3_FIRE_RELEASE_SHA256"),
        "git_commit": plan.exports.get("P3_GIT_COMMIT"),
        "workflow_sha256": load_json(record_dir / "request.json")[
            "workflow_sha256"
        ],
        "run_dir": str(context.run_dir),
        "task_map_sha256": plan.task_map_sha256,
        "task_count": plan.task_count,
        "array": plan.array,
        "force_mode": plan.force_mode,
        "force_manifest_sha256": plan.force_manifest_sha256,
        "budget_receipt_sha256": plan.budget_receipt_sha256,
        "scheduler_options": list(plan.scheduler_options),
        "candidate_ids": list(plan.candidate_ids) if plan.candidate_ids else None,
        "candidate_subset_sha256": plan.candidate_subset_sha256,
        "diagnostic_resource_sha256": plan.diagnostic_resource_sha256,
        "diagnostic_requested_walltime_minutes": plan.exports.get(
            "P3_DIAGNOSTIC_REQUESTED_WALLTIME_MINUTES"
        ),
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
            "--candidate-id",
            action="append",
            dest="candidate_ids",
            help="preflight only: repeat for each explicitly reviewed candidate",
        )
        subparser.add_argument(
            "--max-in-flight",
            type=int,
            help=(
                "force only: optional cross-check that must equal the immutable "
                "budget receipt; the receipt always controls concurrency"
            ),
        )
        subparser.add_argument(
            "--retry-collection",
            type=Path,
            help="force only: immutable failed primary collection for one technical retry",
        )
        subparser.add_argument("--expect-retry-collection-sha")
        if mode == "execute":
            subparser.add_argument("--expect-config-sha", required=True)
            subparser.add_argument("--expect-candidate-subset-sha")
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
                candidate_ids=args.candidate_ids,
                retry_collection=args.retry_collection,
                expected_retry_collection_sha256=args.expect_retry_collection_sha,
            )
        else:
            result = execute_submission(
                context,
                args.stage,
                expected_config_sha=args.expect_config_sha,
                task_map=args.task_map,
                max_in_flight=args.max_in_flight,
                candidate_ids=args.candidate_ids,
                expected_candidate_subset_sha=args.expect_candidate_subset_sha,
                retry_collection=args.retry_collection,
                expected_retry_collection_sha256=args.expect_retry_collection_sha,
            )
        print_json(result)
        return 0
    except (CampaignError, SubmissionError, OSError, ValueError, KeyError, TypeError) as exc:
        print_json({"healthy": False, "mode": args.mode, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

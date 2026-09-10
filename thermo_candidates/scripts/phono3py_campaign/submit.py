#!/usr/bin/env python3
"""Fail-closed Nibi submission frontend for phono3py campaign stages.

The CLI deliberately separates a read-only ``plan`` from ``execute``.  An
execution is accepted only when the caller repeats the exact configuration
SHA-256 printed by the plan.  Scientific work is delegated to the versioned
Slurm scripts; this module never runs QE or phono3py itself.
"""

from __future__ import annotations

import argparse
import fcntl
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
    load_json,
    required,
    safe_run_dir,
    sha256_path,
    validate_config,
    verify_manifest,
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
    manifest = verify_manifest(config, config_path, run_dir, stage=policy_stage)
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
    candidates = (
        context.run_dir / "force" / "final" / "gate.json",
        context.run_dir / "collection" / "final" / "gate.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            require_passing_gate(candidate, "collected-force gate")
            return
    raise SubmissionError(
        "postprocessing requires a passing collected-force gate at "
        + " or ".join(str(path) for path in candidates)
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
    max_in_flight: int = 32,
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

    if stage == "preflight":
        require_relax_gate(context)
    elif stage == "force":
        require_relax_gate(context)
        require_production_selection(context.config)
        if task_map is None:
            raise SubmissionError("force submission requires an explicit --task-map")
        if isinstance(max_in_flight, bool) or max_in_flight < 1:
            raise SubmissionError("--max-in-flight must be a positive integer")
        hard_cap_value = required(context.config, "displacements.hard_cap")
        if isinstance(hard_cap_value, bool) or not isinstance(hard_cap_value, int):
            raise SubmissionError("displacements.hard_cap must be an integer")
        resolved_task_map, task_count, task_map_sha = validate_task_map(
            task_map, context.run_dir, hard_cap_value
        )
        exports["TASK_MAP"] = safe_export_value("TASK_MAP", resolved_task_map)
        array = f"0-{task_count - 1}%{min(max_in_flight, task_count)}"
    elif stage == "postprocess":
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
    )


def export_argument(exports: Mapping[str, str]) -> str:
    ordered = ("CAMPAIGN_CONFIG", "RUN_DIR", "ATTEMPT_ID", "P3_SLURM_DIR", "TASK_MAP")
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
        export_argument(plan.exports),
    ]
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
    hostname_is_nibi = bool(re.match(r"^nibi(?:login)?[0-9]*(?:\.|$)", hostname))
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
    if queued.returncode != 0:
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
    max_in_flight: int,
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
        "command": list(command),
    }


def execute_submission(
    context: SubmissionContext,
    stage: str,
    *,
    expected_config_sha: str,
    task_map: Path | None,
    max_in_flight: int,
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
    max_in_flight: int,
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
        subparser.add_argument("--max-in-flight", type=int, default=32)
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

"""Immutable, evidence-gated QE force datasets; no automatic scientific selection.

``prepare_force`` consumes an existing audited phono3py dataset. It performs
only input preparation and validation. ``run_force_task`` is compute-only and
runs exactly one immutable map row in a fresh attempt directory. Pilot specs
are explicit sampling plans, never claims of convergence or production choices.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

import campaign as core
from postprocess_backend import load_force_artifact
from qe_input import parse_qe_input
from qe_output import inspect_output, parse_last_force_block

ForceError = core.CampaignError
FIELDS = ("task_id", "displacement_id", "role", "input_path", "input_sha256")
COST_SETTING_FIELDS = ("matrix", "atoms", "ecutwfc_Ry", "ecutrho_Ry", "conv_thr_Ry", "kmesh", "kshift")
LEDGER_RECORD_FIELDS = frozenset((
    "phase", "task_count", "reserved_core_hours", "receipt_path", "receipt_sha256",
))
SHA256_RE = re.compile(r"[0-9a-f]{64}")
LEDGER_NAME_RE = re.compile(r"reservation-(\d{6})\.json")
LEDGER_LOCK_RE = re.compile(r"\.reservation-\d{6}\.json\.lock")


def safe_budget_ledger(run_dir: Path, *, create: bool = False) -> Path:
    """Return only the canonical, non-symlink material budget ledger."""
    root = Path(run_dir).resolve()
    raw = Path(run_dir) / ".force_budget"
    expected = root / ".force_budget"
    if raw.parent.resolve() != root or raw.name != ".force_budget":
        raise ForceError("force-budget ledger must be a direct RUN_DIR child")
    if os.path.lexists(raw):
        if raw.is_symlink() or not raw.is_dir() or raw.resolve() != expected:
            raise ForceError("force-budget ledger must be a non-symlink RUN_DIR child")
    elif create:
        raw.mkdir()
        if raw.is_symlink() or not raw.is_dir() or raw.resolve() != expected:
            raise ForceError("force-budget ledger creation is unsafe")
    else:
        raise ForceError("material force-budget ledger is missing")
    for child in raw.iterdir():
        if child.name == "executions":
            if child.is_symlink() or not child.is_dir() or child.resolve().parent != expected:
                raise ForceError("force-budget executions directory is unsafe")
            for claim in child.iterdir():
                if claim.is_symlink() or not claim.is_file() or not (
                    claim.name.endswith(".json") or claim.name.endswith(".json.lock")
                ):
                    raise ForceError("force-budget execution claim is unsafe")
        elif (
            child.name == "lock"
            or LEDGER_NAME_RE.fullmatch(child.name) is not None
            or LEDGER_LOCK_RE.fullmatch(child.name) is not None
        ):
            if child.is_symlink() or not child.is_file():
                raise ForceError("force-budget ledger record or lock is unsafe")
        else:
            raise ForceError(f"budget ledger contains an invalid record name: {child.name}")
    return expected


def _ledger_lock_path(ledger: Path) -> Path:
    lock = ledger / "lock"
    if os.path.lexists(lock) and (lock.is_symlink() or not lock.is_file()):
        raise ForceError("force-budget ledger lock is unsafe")
    return lock


def _ledger_number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ForceError(f"budget ledger {label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        qualifier = "positive finite" if positive else "finite and non-negative"
        raise ForceError(f"budget ledger {label} must be {qualifier}")
    return number


def _bundle_file(path: Path, bundle: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file() or path.parent != bundle:
        raise ForceError(f"budget receipt requires adjacent non-symlink {label}")
    return path


def _has_symlink_below(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return True
        current = parent
    return root.is_symlink()


def _replay_existing_submission_anchor(
    run_dir: Path, receipt_path: Path, receipt_sha: str, manifest: Mapping[str, Any],
    task_map_path: Path,
) -> None:
    """Use already-written submission/attempt evidence as an extra local anchor.

    This does not pretend to defeat an actor who can rewrite every local file.
    It does prevent a ledger/receipt/bundle rewrite from silently replacing an
    already submitted bundle while its request, launch, or copied task input
    still records the original bytes.
    """
    requests_root = run_dir / "submissions" / "force"
    if not requests_root.is_dir():
        return
    manifest_sha = core.sha256_path(task_map_path.parent / "force_manifest.json")
    task_map_sha = core.sha256_path(task_map_path)
    for request_path in requests_root.glob("*/request.json"):
        if request_path.is_symlink() or not request_path.is_file():
            raise ForceError("force submission request is missing or symlinked")
        request = core.load_json(request_path)
        if request.get("budget_receipt") != str(receipt_path):
            continue
        if (
            request.get("budget_receipt_sha256") != receipt_sha
            or request.get("force_manifest_sha256") != manifest_sha
            or request.get("task_map_sha256") != task_map_sha
            or request.get("stage") != "force"
            or not isinstance(request.get("attempt_id"), str)
        ):
            raise ForceError("submitted force request no longer binds its budget bundle")
        attempt_root = run_dir / "slurm_attempts" / "force" / request["attempt_id"]
        if not attempt_root.exists():
            continue  # accepted submission may not have started yet
        if attempt_root.is_symlink() or not attempt_root.is_dir():
            raise ForceError("submitted force attempt root is invalid")
        for launch_path in attempt_root.rglob("launch.json"):
            if launch_path.is_symlink():
                raise ForceError("submitted force launch is symlinked")
            launch = core.load_json(launch_path)
            task = launch.get("task")
            task_id = task.get("task_id") if isinstance(task, Mapping) else None
            tasks = manifest.get("tasks")
            if (
                launch.get("force_manifest_sha256") != manifest_sha
                or type(task_id) is not int
                or not isinstance(tasks, list)
                or task_id < 0 or task_id >= len(tasks)
                or task != tasks[task_id]
            ):
                raise ForceError("submitted force launch no longer binds manifest task bytes")
            copied_input = launch_path.parent / "scf.in"
            if copied_input.is_file() and not copied_input.is_symlink() and core.sha256_path(copied_input) != task["input_sha256"]:
                raise ForceError("submitted force copied input differs from manifest task bytes")


def _replay_bundle(
    receipt_path: Path, receipt_sha: str, receipt: Mapping[str, Any], run_dir: Path,
    config: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[list[str]]]:
    """Bind a receipt to the immutable local force-bundle prefix."""
    bundle = receipt_path.parent
    if receipt_path.name != "budget_receipt.json" or receipt_path.is_symlink():
        raise ForceError("budget receipt is not the canonical non-symlink bundle receipt")
    task_map_path = _bundle_file(bundle / "task_map.tsv", bundle, "task_map.tsv")
    manifest_path = _bundle_file(bundle / "force_manifest.json", bundle, "force_manifest.json")
    try:
        with task_map_path.open(newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t", strict=True))
    except (OSError, csv.Error) as exc:
        raise ForceError(f"cannot read budget receipt task map: {exc}") from exc
    if not rows or tuple(rows[0]) != FIELDS or any(len(row) != len(FIELDS) for row in rows[1:]):
        raise ForceError("budget receipt task map schema is invalid")
    task_rows = rows[1:]
    if not task_rows or [row[0] for row in task_rows] != [str(index) for index in range(len(task_rows))]:
        raise ForceError("budget receipt task map IDs are not contiguous")
    try:
        manifest = core.load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ForceError(f"cannot read budget receipt force manifest: {exc}") from exc
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1 or manifest.get("stage") != "force":
        raise ForceError("budget receipt force manifest schema is invalid")
    mode = manifest.get("mode")
    if mode not in {"pilot", "production"} or (receipt.get("phase") == "production") != (mode == "production"):
        raise ForceError("budget receipt phase and force-manifest mode disagree")
    tasks = manifest.get("tasks")
    if (
        not isinstance(tasks, list)
        or len(tasks) != len(task_rows)
        or manifest.get("task_count") != len(task_rows)
        or receipt.get("task_count") != len(task_rows)
        or receipt.get("task_map_sha256") != core.sha256_path(task_map_path)
        or manifest.get("task_map_sha256") != core.sha256_path(task_map_path)
        or manifest.get("budget_receipt_sha256") != receipt_sha
        or manifest.get("material") != receipt.get("material")
    ):
        raise ForceError("budget receipt does not bind its exact force bundle")
    for task_id, (row, task) in enumerate(zip(task_rows, tasks)):
        if not isinstance(task, Mapping) or task.get("task_id") != task_id:
            raise ForceError("budget receipt force manifest task IDs are invalid")
        if any(str(task.get(key)) != value for key, value in zip(FIELDS, row)):
            raise ForceError("budget receipt task map differs from force manifest")
        input_path = Path(str(task.get("input_path", "")))
        if (
            not input_path.is_absolute() or _has_symlink_below(input_path, bundle) or not input_path.is_file()
            or not input_path.resolve().is_relative_to(bundle) or input_path.resolve() == bundle
            or core.sha256_path(input_path) != task.get("input_sha256")
        ):
            raise ForceError("budget receipt force task input is missing, symlinked, or altered")
    expected_production_inputs = [
        task["input_sha256"] for task in tasks if task.get("displacement_id") != 0
    ] if mode == "production" else []
    receipt_inputs = receipt.get("production_input_hashes")
    if (
        not isinstance(receipt_inputs, list)
        or any(not isinstance(value, str) or SHA256_RE.fullmatch(value) is None for value in receipt_inputs)
        or receipt_inputs != expected_production_inputs
    ):
        raise ForceError("budget receipt production_input_hashes do not bind manifest tasks")
    if config is not None:
        policy = config.get("resource_budget")
        if not isinstance(policy, Mapping) or receipt.get("material") != config.get("material", {}).get("formula"):
            raise ForceError("budget receipt policy or material differs from current configuration")
        if (
            receipt.get("resource_policy_sha256") != core.canonical_sha256(policy)
            or receipt.get("approved_total_core_hours") != policy.get("approved_total_core_hours_per_material")
        ):
            raise ForceError("budget receipt policy/approved-total differs from current configuration")
    _replay_existing_submission_anchor(run_dir, receipt_path, receipt_sha, manifest, task_map_path)
    return dict(manifest), task_rows


def replay_budget_ledger(
    run_dir: Path, config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Replay every reservation from its hash-bound receipt.

    A ledger entry is only an index.  Its budget-bearing fields must exactly
    mirror the immutable receipt and the receipt's reservation must still be
    arithmetically possible from the declared task/rank/time/retry contract.
    This is deliberately used by reservation, submission, and finalization.
    """
    ledger = safe_budget_ledger(run_dir)
    named: list[tuple[int, Path]] = []
    for path in ledger.iterdir():
        if not path.is_file() or path.name == "lock" or re.fullmatch(r"\.reservation-\d{6}\.json\.lock", path.name):
            continue
        match = LEDGER_NAME_RE.fullmatch(path.name)
        if match is None:
            raise ForceError(f"budget ledger contains an invalid record name: {path.name}")
        named.append((int(match.group(1)), path))
    named.sort()
    if [number for number, _ in named] != list(range(len(named))):
        raise ForceError("budget ledger reservation records are non-contiguous")

    replayed: list[dict[str, Any]] = []
    receipt_paths: set[str] = set()
    receipt_hashes: set[str] = set()
    reserved_before = 0.0
    production_count = 0
    phase_counts = {"initial": 0, "validation": 0}
    production_inputs: set[str] = set()
    for number, path in named:
        try:
            record = core.load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ForceError(f"cannot read budget ledger reservation {path.name}: {exc}") from exc
        if not isinstance(record, Mapping) or set(record) != LEDGER_RECORD_FIELDS:
            raise ForceError("budget ledger reservation schema is invalid")
        phase = record.get("phase")
        task_count = record.get("task_count")
        if phase not in {"initial", "validation", "production"}:
            raise ForceError("budget ledger reservation phase is invalid")
        if type(task_count) is not int or task_count <= 0:
            raise ForceError("budget ledger reservation task_count is invalid")
        reserved = _ledger_number(record.get("reserved_core_hours"), "reserved_core_hours", positive=True)
        receipt_path_text, receipt_sha = record.get("receipt_path"), record.get("receipt_sha256")
        if not isinstance(receipt_path_text, str) or not Path(receipt_path_text).is_absolute():
            raise ForceError("budget ledger reservation receipt_path is invalid")
        if not isinstance(receipt_sha, str) or SHA256_RE.fullmatch(receipt_sha) is None:
            raise ForceError("budget ledger reservation receipt_sha256 is invalid")
        receipt_path = Path(receipt_path_text)
        try:
            receipt_path = _under(receipt_path, run_dir)
        except ForceError as exc:
            raise ForceError("budget ledger reservation receipt_path escapes RUN_DIR") from exc
        if str(receipt_path) != receipt_path_text or not receipt_path.is_file() or core.sha256_path(receipt_path) != receipt_sha:
            raise ForceError("budget ledger reservation hash mismatch")
        if receipt_path_text in receipt_paths or receipt_sha in receipt_hashes:
            raise ForceError("budget ledger has repeated reservation evidence")
        receipt_paths.add(receipt_path_text)
        receipt_hashes.add(receipt_sha)
        try:
            receipt = core.load_json(receipt_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ForceError(f"cannot read budget receipt: {exc}") from exc
        if not isinstance(receipt, Mapping) or receipt.get("schema_version") != 1:
            raise ForceError("budget receipt schema is invalid")
        if (
            receipt.get("phase") != phase
            or receipt.get("task_count") != task_count
            or receipt.get("reserved_core_hours") != record.get("reserved_core_hours")
        ):
            raise ForceError("budget ledger reservation does not match its receipt semantics")
        manifest, _ = _replay_bundle(receipt_path, receipt_sha, receipt, run_dir, config)
        ranks, retries = receipt.get("mpi_ranks"), receipt.get("maximum_technical_retries_per_task")
        if type(ranks) is not int or ranks <= 0 or type(retries) is not int or retries != 1:
            raise ForceError("budget receipt has invalid rank or retry semantics")
        walltime = _ledger_number(receipt.get("walltime_hours"), "receipt walltime_hours", positive=True)
        expected_reserved = task_count * ranks * walltime * (1 + retries)
        if not math.isclose(reserved, expected_reserved, rel_tol=1e-12, abs_tol=1e-12):
            raise ForceError("budget receipt reserved_core_hours is inconsistent with its task contract")
        used = _ledger_number(receipt.get("used_core_hours"), "receipt used_core_hours")
        if not math.isclose(_ledger_number(receipt.get("reserved_core_hours_before"), "receipt reserved_core_hours_before"), reserved_before, rel_tol=1e-12, abs_tol=1e-12):
            raise ForceError("budget receipt reserved_core_hours_before breaks the ledger prefix chain")
        charged_before = max(reserved_before, used)
        if not math.isclose(_ledger_number(receipt.get("charged_core_hours_before"), "receipt charged_core_hours_before"), charged_before, rel_tol=1e-12, abs_tol=1e-12):
            raise ForceError("budget receipt charged_core_hours_before breaks the ledger prefix chain")
        if phase == "production":
            production_count += 1
            if receipt.get("production_batch_number") != production_count:
                raise ForceError("budget receipt production_batch_number breaks the ledger prefix chain")
            inputs = receipt.get("production_input_hashes")
            if not isinstance(inputs, list) or any(
                not isinstance(value, str) or SHA256_RE.fullmatch(value) is None for value in inputs
            ):
                raise ForceError("budget receipt production_input_hashes are invalid")
            if len(inputs) != len(set(inputs)) or production_inputs.intersection(inputs):
                raise ForceError("budget ledger repeats production task inputs")
            production_inputs.update(inputs)
        elif receipt.get("production_batch_number") is not None:
            raise ForceError("non-production budget receipt has a production batch number")
        phase_counts[phase] = phase_counts.get(phase, 0) + task_count
        if config is not None:
            policy = config["resource_budget"]
            initial_limit = min(6, policy["initial_timing_and_noise_batch"]["maximum_new_scf_tasks"])
            validation_limit = min(32, policy["pilot_batch_maximum_new_scf_tasks"])
            if phase_counts["initial"] > initial_limit:
                raise ForceError("budget ledger initial phase exceeds its cumulative task cap")
            if policy.get("approved_total_core_hours_per_material") is None and phase_counts["validation"] > validation_limit:
                raise ForceError("budget ledger validation phase exceeds its cumulative task cap")
            production_limit = min(
                32 if production_count == 1 else 64,
                policy["production_first_batch_maximum_tasks"] if production_count == 1
                else policy["production_later_batch_maximum_tasks"],
            )
            if phase == "production" and task_count > production_limit:
                raise ForceError("budget ledger production batch exceeds its task cap")
        reserved_before += reserved
        replayed.append({"number": number, "path": path, "record": dict(record), "receipt": dict(receipt), "manifest": manifest})
    return replayed


def _sample(reference: Mapping[str, Any], run_dir: Path) -> dict[str, Any]:
    """Read actual immutable force evidence, never a claimed passing summary."""
    manifest_path = _under(Path(reference["manifest_path"]), run_dir)
    result_path = _under(Path(reference["result_path"]), run_dir)
    _match(manifest_path, reference["manifest_sha256"])
    _match(result_path, reference["result_sha256"])
    manifest, result = core.load_json(manifest_path), core.load_json(result_path)
    task_id = result.get("task_id")
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise ForceError("selection sample result has no valid task ID")
    # This adapter revalidates task_map -> task -> claim -> launch -> result ->
    # nested process -> raw input/output/stderr and pseudopotential hashes.
    artifact = load_force_artifact(manifest_path, result_path.parent, task_id)
    task = manifest["tasks"][task_id]
    launch_path = result_path.parent / "launch.json"
    launch = core.load_json(launch_path)
    input_path, output_path = Path(artifact.input_path), Path(artifact.output_path)
    return {
        "manifest": manifest,
        "result": result,
        "launch": launch,
        "input": parse_qe_input(input_path.read_text()),
        "forces": parse_last_force_block(output_path, task["nat"]),
        "artifact": artifact,
        "hashes": {
            str(path): core.sha256_path(path)
            for path in (
                manifest_path,
                result_path,
                input_path,
                output_path,
                Path(artifact.stderr_path),
                launch_path,
                result_path.parent / "force_claim.json",
                result_path.parent / "scf.process.json",
            )
        },
    }


def validate_selection_evidence(path: Path, config_path: Path, config, settings,
                                run_dir: Path, dataset: Path) -> dict[str, Any]:
    """Validate an external pilot_analysis audit receipt and its raw evidence.

    The scientific metrics are owned by pilot_analysis.py. Configuration flags
    cannot replace this receipt. The audit must bind the current audit backend,
    exact selected settings, accepted unitcell, dataset and healthy raw samples.
    """
    path = _under(path, run_dir)
    # Lazy import avoids the intentional pilot_evidence -> force_backend audit
    # dependency. A production unlock must be reproduced from raw files; a
    # self-consistent JSON object carrying pass=true is not evidence.
    from pilot_evidence import replay_selection_receipt

    replay = replay_selection_receipt(
        config_path,
        run_dir,
        path,
        expected_receipt_sha256=core.sha256_path(path),
    )
    if replay.get("healthy") is not True or replay.get("pass") is not True:
        raise ForceError("selection receipt does not replay to a passing raw-evidence audit")
    record = core.load_json(path)
    if record.get("schema_version") != 1 or record.get("accepted_unitcell_sha256") != core.sha256_path(run_dir / "relax/final/unitcell.in"):
        raise ForceError("selection evidence has wrong schema or accepted structure")
    if record.get("selected_settings_sha256") != core.canonical_sha256(settings) or record.get("preflight_yaml_sha256") != core.sha256_path(dataset / "phono3py_disp.yaml"):
        raise ForceError("selection evidence is for different settings or dataset")
    if any(record.get(key) is not True for key in ("pass", "force_accuracy_pass", "amplitude_pass")):
        raise ForceError("selection requires independently passing force and amplitude audits")
    claimed_analysis = record.get("analysis_sha256")
    analysis_payload = dict(record)
    analysis_payload.pop("analysis_sha256", None)
    if claimed_analysis != core.canonical_sha256(analysis_payload):
        raise ForceError("selection analysis receipt hash mismatch")
    if replay.get("analysis_sha256") != claimed_analysis:
        raise ForceError("selection replay and recorded analysis hashes differ")
    backend = Path(__file__).with_name("pilot_analysis.py")
    _match(backend, record.get("audit_backend_sha256", ""))
    references = record.get("samples", {})
    if not references or not isinstance(references, dict):
        raise ForceError("selection evidence requires actual force samples")
    hashes = {str(path): core.sha256_path(path)}
    for raw_path, digest in replay.get("source_sha256", {}).items():
        candidate = Path(raw_path).resolve()
        if candidate != run_dir and candidate.is_relative_to(run_dir):
            _match(candidate, digest)
            hashes[str(candidate)] = digest
    roles, configs = set(), set()
    for reference in references.values():
        sample = _sample(reference, run_dir)
        hashes.update(sample["hashes"])
        manifested = sample["manifest"]
        if manifested.get("material") != config["material"]["formula"] or manifested["settings"]["matrix"] != settings["matrix"]:
            raise ForceError("selection sample belongs to another material or supercell")
        if not any(digest == record["accepted_unitcell_sha256"] and Path(p).name == "unitcell.in" for p,digest in manifested["evidence_sha256"].items()):
            raise ForceError("sample does not bind accepted unitcell")
        roles.add(sample["result"]["role"])
        configs.add(core.canonical_sha256(manifested["settings"]))
    if not {"pristine", "displacement"} <= roles or core.canonical_sha256(settings) not in configs:
        raise ForceError("selection samples lack matched pristine/displacement or selected settings")
    return {"pass": True, "evidence_sha256": hashes,
            "audit_backend_sha256": core.sha256_path(backend),
            "raw_audit_backend_sha256": record.get("raw_audit_backend_sha256"),
            "analysis_sha256": claimed_analysis,
            "selection_receipt_path": str(path),
            "selection_receipt_sha256": core.sha256_path(path),
            "scope": "external pilot_analysis force/amplitude audit; cutoff and full-dataset convergence remain separate"}


def _measurements(references, run_dir):
    measured, hashes = [], {}
    seen = set()
    for reference in references:
        sample = _sample(reference["sample"], run_dir)
        accounting = _under(Path(reference["accounting_path"]), run_dir)
        _match(accounting, reference["accounting_sha256"])
        rows = list(csv.DictReader(io.StringIO(accounting.read_text()), delimiter="|"))
        matches = [row for row in rows if row.get("JobIDRaw") == reference["job_id"]]
        if len(matches) != 1 or reference["job_id"] in seen:
            raise ForceError("timing evidence needs one unique scheduler job record")
        seen.add(reference["job_id"])
        if reference["job_id"].split(".")[0] != str(sample["launch"].get("job_id")):
            raise ForceError("scheduler measurement belongs to a different launched job")
        row = matches[0]
        elapsed = core.positive_number(float(row["ElapsedRaw"]), "elapsed_seconds")
        ranks = int(row["AllocCPUS"])
        rss = re.fullmatch(r"(\d+(?:\.\d+)?)[KMGT]?", row["MaxRSS"])
        if ranks <= 0 or row["State"] != "COMPLETED" or not rss or float(rss[1]) <= 0:
            raise ForceError("timing evidence must be normal completion with measured ranks and MaxRSS")
        result_file = Path(reference["sample"]["result_path"])
        raw_output = (result_file.parent / "scf.out").read_text()
        iteration_matches = re.findall(r"convergence has been achieved in\s+(\d+)\s+iterations", raw_output)
        if not iteration_matches:
            raise ForceError("timing evidence lacks measured SCF iteration count")
        force = sample["forces"]
        dataset_paths = [Path(p) for p in sample["manifest"]["evidence_sha256"] if Path(p).name == "phono3py_disp.yaml"]
        if len(dataset_paths) != 1:
            raise ForceError("timing sample lacks unambiguous phono3py dataset")
        singles = {x["displacement_id"] for x in _yaml(dataset_paths[0])["displacement_pairs"]}
        displacement_id = sample["result"]["displacement_id"]
        kind = "pristine" if displacement_id == 0 else "single" if displacement_id in singles else "double"
        measured.append({"job_id": reference["job_id"], "elapsed_seconds": elapsed,
                         "mpi_ranks": ranks, "max_rss": row["MaxRSS"], "scf_iterations": int(iteration_matches[-1]),
                         "raw_max_force": force.max_abs_ry_bohr, "total_scf_correction": force.scf_correction_ry_bohr,
                         "material": sample["manifest"]["material"], "probe_kind": kind,
                         "cost_settings_sha256": core.canonical_sha256({k: sample["manifest"]["settings"][k] for k in COST_SETTING_FIELDS}),
                         "core_hours": elapsed*ranks/3600})
        hashes.update(sample["hashes"])
        hashes[str(accounting)] = core.sha256_path(accounting)
    return measured, hashes


def _reserve_budget(config, run_dir, destination, task_count, task_map_sha256,
                    mode, request, production_input_hashes=(), settings=None):
    """Conservative append-only reservations; no implicit refunds or budget reset.

    Production needs a numeric approved_total_core_hours_per_material, timing
    and usage evidence. Receipt reserves requested walltime for both allowed
    attempts; scheduler integration must enforce its concurrency/rank/time caps.
    The ledger must be retained when resuming the material run.
    """
    if not isinstance(request, Mapping):
        raise ForceError("an explicit resource_request is required")
    policy = config.get("resource_budget")
    if not isinstance(policy, Mapping):
        raise ForceError("resource_budget policy is required")
    phase = request.get("phase")
    if phase not in ("initial", "validation", "production") or (phase == "production") != (mode == "production"):
        raise ForceError("resource phase is inconsistent with force mode")
    ranks, concurrent = request.get("mpi_ranks"), request.get("max_concurrency")
    if isinstance(ranks,bool) or not isinstance(ranks,int) or ranks < 1 or isinstance(concurrent,bool) or not isinstance(concurrent,int) or not 1 <= concurrent <= 2:
        raise ForceError("resource request requires positive ranks and concurrency at most 2")
    if concurrent > policy["initial_timing_and_noise_batch"]["maximum_concurrent_force_tasks_per_material"]:
        raise ForceError("concurrency exceeds material resource policy")
    walltime = core.positive_number(request.get("walltime_hours"), "requested walltime_hours")
    max_retries = policy.get("maximum_technical_retries_per_task")
    if isinstance(max_retries,bool) or max_retries != 1:
        raise ForceError("this backend requires a maximum of one technical retry")
    measurements, timing_hashes = _measurements(request.get("timing_evidence", []), run_dir)
    usage, usage_hashes = _measurements(request.get("usage_evidence", []), run_dir)
    approved = policy.get("approved_total_core_hours_per_material")
    if phase == "production" and (approved is None or policy.get("selection_required_before_force_submission") is not False):
        raise ForceError("production requires an explicitly approved total core-hour budget")
    if approved is not None:
        approved = core.positive_number(approved, "approved total core-hours")
    if phase in ("validation", "production") and not measurements:
        raise ForceError("validation/production require actual timing evidence")
    if phase in ("validation", "production") and not {"pristine", "single", "double"} <= {x.get("probe_kind") for x in measurements}:
        raise ForceError("timing evidence must cover pristine, single and double displacement tasks")
    if any(x.get("material") != config["material"]["formula"] for x in measurements + usage):
        raise ForceError("resource measurements belong to another material")
    if settings is not None and any(x["cost_settings_sha256"] != core.canonical_sha256({k: settings[k] for k in COST_SETTING_FIELDS}) for x in measurements):
        raise ForceError("timing evidence does not match selected supercell and force-accuracy settings")
    if phase == "production" and not usage:
        raise ForceError("production requires scheduler-backed used-credit evidence")
    if measurements:
        if any(x["mpi_ranks"] != ranks for x in measurements):
            raise ForceError("timing samples must use requested MPI rank count")
        hours = sorted(x["elapsed_seconds"]/3600 for x in measurements)
        p90 = hours[math.ceil(0.9*len(hours))-1]
        estimated = max(1.5*p90, max(hours))
        if walltime < estimated:
            raise ForceError("requested walltime is below conservative measured P90 estimate")
    else:
        p90, estimated = None, walltime
    ledger = safe_budget_ledger(run_dir, create=True)
    with _ledger_lock_path(ledger).open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous = replay_budget_ledger(run_dir, config)
        for item in previous:
            old, previous_receipt = item["record"], item["receipt"]
            if set(production_input_hashes) & set(previous_receipt.get("production_input_hashes", [])):
                raise ForceError("production force already reserved; technical retries must use its original task map")
        prior_production = sum(item["record"]["phase"] == "production" for item in previous)
        if phase == "initial":
            limit = min(6, policy["initial_timing_and_noise_batch"]["maximum_new_scf_tasks"])
            if task_count + sum(item["record"]["task_count"] for item in previous if item["record"]["phase"] == "initial") > limit:
                raise ForceError("initial timing/noise campaign exceeds cumulative six SCFs")
        elif phase == "validation":
            limit = min(32, policy["pilot_batch_maximum_new_scf_tasks"])
            if approved is None and task_count + sum(item["record"]["task_count"] for item in previous if item["record"]["phase"] == "validation") > limit:
                raise ForceError("unbudgeted validation pilot exceeds cumulative 32 SCFs")
        else:
            limit = min(64 if prior_production else 32, policy["production_later_batch_maximum_tasks"] if prior_production else policy["production_first_batch_maximum_tasks"])
        if task_count > limit:
            raise ForceError(f"requested batch exceeds {limit} SCFs including pristine")
        reserved = sum(item["record"]["reserved_core_hours"] for item in previous)
        used = sum(x["core_hours"] for x in usage)
        reservation = task_count * walltime * ranks * (1+max_retries)
        charged_before = max(reserved, used)
        if approved is not None and charged_before + reservation > approved:
            raise ForceError("core-hour reservation exceeds approved remaining budget")
        receipt = {"schema_version": 1, "material": config["material"]["formula"], "phase": phase,
                   "task_map_sha256": task_map_sha256, "task_count": task_count,
                   "mpi_ranks": ranks, "maximum_concurrency": concurrent, "walltime_hours": walltime,
                   "maximum_technical_retries_per_task": max_retries,
                   "retry_counts_at_reservation": {str(i): 0 for i in range(task_count)},
                   "production_input_hashes": list(production_input_hashes),
                   "measured_P90_walltime_hours": p90, "estimated_normal_walltime_hours": estimated,
                   "timing_measurements": measurements, "used_core_hours": used,
                   "reserved_core_hours_before": reserved, "charged_core_hours_before": charged_before,
                   "reserved_core_hours": reservation, "approved_total_core_hours": approved,
                   "production_batch_number": prior_production+1 if phase == "production" else None,
                   "evidence_sha256": {**timing_hashes, **usage_hashes},
                   "resource_policy_sha256": core.canonical_sha256(policy),
                   "created_utc": core.utc_now(), "accounting_policy": "retain all reservations; no automatic refunds; includes one retry per task"}
        receipt_path = (destination / "budget_receipt.json").resolve()
        core.write_json_immutable(receipt_path, receipt)
        ledger_record = {"phase": phase, "task_count": task_count, "reserved_core_hours": reservation,
                         "receipt_path": str(receipt_path), "receipt_sha256": core.sha256_path(receipt_path)}
        reservation_path = ledger / f"reservation-{len(previous):06d}.json"
        if os.path.lexists(reservation_path):
            raise ForceError("force-budget reservation path already exists or is unsafe")
        core.write_json_immutable(reservation_path, ledger_record)
    return receipt


def _under(path: Path, root: Path) -> Path:
    path, root = path.resolve(), root.resolve()
    if path == root or not path.is_relative_to(root):
        raise ForceError(f"path must be a strict descendant of {root}: {path}")
    if "READY_TO_ATTACH" in path.parts:
        raise ForceError("frozen attachment path is forbidden")
    return path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _match(path: Path, digest: str) -> None:
    if not path.is_file() or core.sha256_path(path) != digest:
        raise ForceError(f"missing or altered evidence: {path}")


def _yaml(path: Path) -> dict[str, Any]:
    # JSON is a YAML subset and permits dependency-free synthetic unit tests.
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ForceError("PyYAML is required to read real phono3py YAML") from exc
        value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ForceError("phono3py YAML must contain a mapping")
    return value


def _vector(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ForceError("expected a finite three-vector")
    result = [float(x) for x in value]
    if not all(math.isfinite(x) for x in result):
        raise ForceError("nonfinite geometry or displacement")
    return result


def _inverse(a: list[list[float]]) -> list[list[float]]:
    det = core.determinant(a)
    if not math.isfinite(det) or abs(det) < 1e-12:
        raise ForceError("singular supercell")
    return [[(a[(j+1)%3][(i+1)%3]*a[(j+2)%3][(i+2)%3]
              - a[(j+1)%3][(i+2)%3]*a[(j+2)%3][(i+1)%3])/det
             for j in range(3)] for i in range(3)]


def _fragment(path: Path, settings: Mapping[str, Any], pseudo_dir: Path) -> str:
    """Convert the documented QE fragment to a full, narrowly scoped SCF."""
    raw = path.read_text()
    lines = raw.splitlines()
    meta = re.fullmatch(r"\s*!\s*ibrav\s*=\s*0\s*,\s*nat\s*=\s*(\d+)\s*,\s*ntyp\s*=\s*(\d+)\s*", lines[0] if lines else "")
    if not meta:
        raise ForceError(f"unexpected phono3py QE fragment header: {path}")
    for name in ("CELL_PARAMETERS", "ATOMIC_SPECIES", "ATOMIC_POSITIONS"):
        if len(re.findall(rf"(?im)^\s*{name}\b", raw)) != 1:
            raise ForceError(f"ambiguous {name} in {path}")
    if re.search(r"(?im)^\s*(?:&|K_POINTS|CONSTRAINTS|ATOMIC_FORCES|HUBBARD)", raw):
        raise ForceError("unexpected settings/card in generated fragment")
    cell = re.search(r"(?im)^\s*CELL_PARAMETERS\s+(bohr|au)\s*\n", raw)
    if not cell:
        raise ForceError("fragment cell must use explicit bohr/au units")
    tail = raw[cell.end():].splitlines(keepends=True)
    rows = [_vector([float(x.replace('D', 'E')) for x in row.split()]) for row in tail[:3]]
    replacement = "CELL_PARAMETERS angstrom\n" + "".join(
        " ".join(f"{x * core.BOHR_TO_ANGSTROM:.16g}" for x in row) + "\n" for row in rows)
    raw = raw[:cell.start()] + replacement + "".join(tail[3:])
    if not re.search(r"(?im)^\s*ATOMIC_POSITIONS\s+crystal\s*$", raw):
        raise ForceError("fragment positions must be crystal fractional coordinates")
    pseudo_string = str(pseudo_dir)
    if any(x in pseudo_string for x in ("'", "\n", "\r")):
        raise ForceError("unsupported characters in pseudopotential directory")
    grid = " ".join(map(str, settings["kmesh"] + settings["kshift"]))
    text = ("&CONTROL\n calculation='scf', restart_mode='from_scratch',\n"
            " prefix='p3_force', outdir='./qe-tmp', disk_io='low',\n"
            f" pseudo_dir='{pseudo_string}', tprnfor=.true., tstress=.true., verbosity='high'\n/\n"
            "&SYSTEM\n ibrav=0, " + f"nat={meta[1]}, ntyp={meta[2]},\n"
            f" ecutwfc={settings['ecutwfc_Ry']:.16g}, ecutrho={settings['ecutrho_Ry']:.16g},\n"
            " occupations='fixed', nspin=1, tot_charge=0, nosym=.true., noinv=.true.\n/\n"
            "&ELECTRONS\n" + f" conv_thr={settings['conv_thr_Ry']:.16g},\n"
            " electron_maxstep=300, mixing_beta=0.3\n/\n&IONS\n/\n&CELL\n/\n"
            + raw + "\nK_POINTS automatic\n" + grid + "\n")
    parse_qe_input(text)
    return text


def _settings(config: Mapping[str, Any], mode: str, pilot: Mapping[str, Any] | None) -> dict[str, Any]:
    force = config["force_and_amplitude_validation"]
    production = config["production"]
    flags = force.get("production_symmetry_flags")
    if flags is not None and (flags.get("nosym") is not True or flags.get("noinv") is not True):
        raise ForceError("force and matched pristine require nosym and noinv")
    if mode == "production":
        if production.get("selection_required") is not False or force.get("selection_required") is not False:
            raise ForceError("explicit production and force/amplitude selections are required")
        if production.get("automatic_submission_allowed") is not True:
            raise ForceError("production automatic_submission_allowed is not explicitly true")
        result = {"supercell_id": production.get("selected_supercell"),
                  "cutoff_id": production.get("selected_cutoff"),
                  "amplitude_angstrom": force.get("selected_displacement_distance_angstrom"),
                  "amplitude_bohr": force.get("selected_displacement_distance_cli_bohr"),
                  "ecutwfc_Ry": force.get("selected_ecutwfc_Ry"),
                  "ecutrho_Ry": force.get("selected_ecutrho_Ry"),
                  "conv_thr_Ry": force.get("selected_conv_thr_Ry"),
                  "kmesh": force.get("selected_k_points"), "kshift": [0, 0, 0]}
    elif mode == "pilot":
        if not isinstance(pilot, Mapping) or not isinstance(pilot.get("rationale"), str) or not pilot["rationale"].strip():
            raise ForceError("pilot requires an explicit specification and scientific rationale")
        result = {key: pilot.get(key) for key in ("supercell_id", "cutoff_id", "amplitude_angstrom", "amplitude_bohr", "ecutwfc_Ry", "ecutrho_Ry", "conv_thr_Ry", "kmesh")}
        result["kshift"] = pilot.get("kshift", [0, 0, 0])
    else:
        raise ForceError("mode must be production or pilot")
    for key in ("amplitude_angstrom", "amplitude_bohr", "ecutwfc_Ry", "ecutrho_Ry", "conv_thr_Ry"):
        result[key] = core.positive_number(result[key], key)
    if result["ecutrho_Ry"] < result["ecutwfc_Ry"]:
        raise ForceError("ecutrho must be >= ecutwfc")
    if not math.isclose(result["amplitude_angstrom"] / core.BOHR_TO_ANGSTROM, result["amplitude_bohr"], rel_tol=core.FLOAT_REL_TOL):
        raise ForceError("selected displacement Angstrom/bohr mismatch")
    result["kmesh"] = list(core.integer_triplet(result["kmesh"], "force kmesh", positive=True))
    result["kshift"] = list(core.integer_triplet(result["kshift"], "force kshift"))
    if any(x not in (0, 1) for x in result["kshift"]):
        raise ForceError("kmesh shift must contain 0 or 1")
    model = config["electronic_model"]
    if any(model.get(k) != v for k, v in {"exchange_correlation": "PBE", "explicit_spin_orbit_coupling": False, "occupations": "fixed", "charge_state": 0, "magnetic_order": "nonmagnetic"}.items()):
        raise ForceError("force backend supports only this campaign's PBE nonmagnetic fixed-occupation model")
    matrices = {x["id"]: x for x in config["displacements"]["supercell_candidates"]}
    cutoffs = {x["id"]: x for x in config["displacements"]["cutoff_candidates"]}
    if result["supercell_id"] not in matrices or result["cutoff_id"] not in cutoffs:
        raise ForceError("explicit configured supercell and finite cutoff IDs required")
    matrix, cutoff = matrices[result["supercell_id"]], cutoffs[result["cutoff_id"]]
    if matrix.get("production_fc3_eligible_without_new_review") is False:
        raise ForceError("count-only escalation matrix requires a new scientific policy")
    if mode == "production":
        for key, expected in (("selected_fc3_supercell_matrix", matrix["matrix"]),
                              ("selected_cutoff_pair_distance_angstrom", cutoff["cutoff_pair_distance_angstrom"]),
                              ("selected_cutoff_pair_distance_cli_bohr", cutoff["cutoff_pair_distance_cli_bohr"])):
            if production.get(key) != expected:
                raise ForceError(f"production redundant selection disagrees: {key}")
    result.update({"matrix": matrix["matrix"], "atoms": matrix["atoms"], "cutoff_pair_distance_cli_bohr": cutoff["cutoff_pair_distance_cli_bohr"]})
    return result


def _imported_acceptance_provenance(
    config_path: Path,
    run_dir: Path,
    saved: Mapping[str, Any],
) -> dict[str, str]:
    """Replay and enumerate destination-owned import evidence for force bundles."""

    if saved.get("accepted_structure_import") is None:
        return {}
    from accepted_structure_import import (
        ARCHIVE,
        RECEIPT,
        verify_imported_acceptance,
    )

    verified = verify_imported_acceptance(config_path, run_dir)
    receipt_path = _under(run_dir / RECEIPT, run_dir)
    pointer = saved["accepted_structure_import"]
    _match(receipt_path, pointer.get("sha256", ""))
    receipt = core.load_json(receipt_path)
    evidence = {str(receipt_path): core.sha256_path(receipt_path)}
    archive = run_dir / ARCHIVE
    for field in ("source_files", "workflow_files"):
        inventory = receipt.get(field)
        if not isinstance(inventory, Mapping):
            raise ForceError(f"accepted-structure import lacks {field}")
        for relative, digest in inventory.items():
            path = _under(archive / str(relative), run_dir)
            _match(path, str(digest))
            evidence[str(path)] = core.sha256_path(path)
    if verified.get("receipt_sha256") != evidence[str(receipt_path)]:
        raise ForceError("accepted-structure import receipt replay mismatch")
    return evidence


def _provenance(config: Mapping[str, Any], config_path: Path, run_dir: Path,
                inventory_path: Path, dataset: Path) -> tuple[dict[str, str], dict[str, Any]]:
    saved = core.load_json(run_dir / core.RUN_MANIFEST)
    if saved.get("schema_version") != 2 or saved.get("material") != config["material"]["formula"] or saved.get("preflight_policy_sha256") != core.policy_sha256(config, "preflight"):
        raise ForceError("saved upstream manifest schema/material/preflight policy mismatch")
    for filename, key in (("source_qe_input", "source_qe_sha256"), ("source_relax_output", "source_relax_sha256")):
        _match(Path(saved[filename]), saved[key])
    # Completed upstream stages may have run a previous driver version. Their
    # recorded hashes are provenance, not a demand to run that old code forever.
    if not isinstance(saved.get("workflow_files"), dict) or not saved["workflow_files"]:
        raise ForceError("upstream workflow hash record is missing")
    final = run_dir / "relax" / "final"
    gate = core.load_json(final / "gate.json")
    if gate.get("pass") is not True:
        raise ForceError("accepted tight-relax gate is required")
    _match(final / "unitcell.in", gate.get("final_unitcell_sha256", ""))
    provenance = core.load_json(final / "provenance.json")
    accepted = _under(Path(provenance["accepted_attempt"]), run_dir)
    for filename, key in (("execution_manifest.json", "execution_manifest_sha256"), ("starting_structure_audit.json", "starting_structure_audit_sha256")):
        _match(accepted / filename, provenance.get(key, ""))
    execution = core.load_json(accepted / "execution_manifest.json")
    for filename, key in (("pristine.in", "pristine_input_sha256"), ("pristine.out", "pristine_output_sha256"), ("relax.in", "relax_input_sha256"), ("relax.out", "relax_output_sha256")):
        _match(accepted / filename, execution.get(key, ""))
    _match(accepted / "pristine.in", gate["final_unitcell_sha256"])
    inventory = core.load_json(inventory_path)
    if inventory.get("preflight_policy_sha256") != core.policy_sha256(config, "preflight"):
        raise ForceError("preflight policy mismatch")
    if inventory.get("accepted_unitcell_sha256") != gate["final_unitcell_sha256"] or inventory.get("accepted_relax_provenance_sha256") != core.sha256_path(final / "provenance.json"):
        raise ForceError("preflight inventory does not refer to accepted relax")
    result_path = dataset / "preflight_result.json"
    result = core.load_json(result_path)
    if result not in inventory.get("results", []):
        raise ForceError("dataset result absent from supplied preflight inventory")
    if result.get("within_hard_cap") is not True or result.get("count_only") or result.get("count_only_no_cutoff"):
        raise ForceError("dataset is count-only or exceeds hard cap")
    _match(dataset / "phono3py_disp.yaml", result.get("yaml_sha256", ""))
    _match(dataset / "unitcell.in", gate["final_unitcell_sha256"])
    if result.get("unitcell_sha256") != gate["final_unitcell_sha256"]:
        raise ForceError("dataset unitcell provenance mismatch")
    imported_evidence = _imported_acceptance_provenance(
        config_path, run_dir, saved
    )
    paths = [run_dir / core.RUN_MANIFEST, final / "gate.json", final / "provenance.json", final / "unitcell.in", inventory_path, result_path, dataset / "phono3py_disp.yaml", accepted / "execution_manifest.json", accepted / "starting_structure_audit.json"]
    paths.extend(accepted / name for name in ("relax.in", "relax.out", "pristine.in", "pristine.out"))
    return {
        **{str(p): core.sha256_path(p) for p in paths},
        **imported_evidence,
    }, execution


def _dataset_inputs(dataset: Path, settings: Mapping[str, Any], pseudo_dir: Path,
                    config: Mapping[str, Any]) -> tuple[dict[int, str], dict[str, Any]]:
    data = _yaml(dataset / "phono3py_disp.yaml")
    if core.required(data, "physical_unit.length") != "au":
        raise ForceError("QE phono3py YAML length must be au")
    if data.get("supercell_matrix") != settings["matrix"]:
        raise ForceError("YAML supercell matrix differs from selection")
    cutoff = core.required(data, "displacement_pair_info.cutoff_pair_distance")
    if not math.isclose(float(cutoff), settings["cutoff_pair_distance_cli_bohr"], rel_tol=1e-8):
        raise ForceError("YAML cutoff differs from selection in bohr")
    inventory = core.analyze_displacement_yaml(data)
    ids = inventory["included_displacement_ids"]
    if len(ids) > config["displacements"]["hard_cap"]:
        raise ForceError("force dataset exceeds displacement hard cap")
    actual_names = {p.name for p in dataset.glob("supercell-*.in")}
    expected_names = {f"supercell-{index:05d}.in" for index in ids}
    if actual_names != expected_names:
        raise ForceError("generated QE files differ from YAML included displacement IDs")
    nat = settings["atoms"]
    lattice = [_vector(row) for row in core.required(data, "supercell.lattice")]
    if len(lattice) != 3:
        raise ForceError("YAML supercell lattice must be 3x3")
    inv = _inverse(lattice)
    points = core.required(data, "supercell.points")
    if len(points) != nat:
        raise ForceError("YAML atom count differs from selection")
    offsets: dict[int, list[tuple[int, list[float]]]] = {0: []}
    for first in data["displacement_pairs"]:
        a, d = first["atom"], _vector(first["displacement"])
        offsets[first["displacement_id"]] = [(a, d)]
        for second in first["paired_with"]:
            if second["included"]:
                for index, vector in zip(second["displacement_ids"], second["displacements"]):
                    offsets[index] = [(a, d), (second["atom"], _vector(vector))]
    for vector in inventory["vectors"]:
        if not math.isclose(core.vector_norm(vector), settings["amplitude_bohr"], rel_tol=1e-8):
            raise ForceError("YAML displacement amplitude differs from selected bohr value")
    source = parse_qe_input((dataset / "unitcell.in").read_text())
    species = [(x.label, x.mass_amu, x.pseudopotential) for x in source.atomic_species]
    if {x[0]: x[2] for x in species} != config["pseudopotentials"]["files"]:
        raise ForceError("accepted unitcell pseudopotential names differ from policy")
    output: dict[int, str] = {}
    for index in [0] + ids:
        filename = "supercell.in" if index == 0 else f"supercell-{index:05d}.in"
        text = _fragment(dataset / filename, settings, pseudo_dir)
        parsed = parse_qe_input(text)
        if parsed.nat != nat or [(x.label, x.mass_amu, x.pseudopotential) for x in parsed.atomic_species] != species:
            raise ForceError("generated species, pseudopotential, mass or atom count mismatch")
        for row, expected in zip(parsed.cell_parameters, lattice):
            if any(abs(x / core.BOHR_TO_ANGSTROM - y) > 2e-8 for x, y in zip(row, expected)):
                raise ForceError("generated fragment cell differs from YAML")
        expected_positions = [_vector(p["coordinates"]) for p in points]
        for atom, vector in offsets[index]:
            if isinstance(atom, bool) or not isinstance(atom, int) or not 1 <= atom <= nat:
                raise ForceError("YAML displacement atom index out of bounds")
            for axis in range(3):
                expected_positions[atom-1][axis] += sum(vector[j] * inv[j][axis] for j in range(3))
        for atom, point, expected in zip(parsed.atomic_positions, points, expected_positions):
            if atom.label != point["symbol"]:
                raise ForceError("generated atom order differs from YAML")
            if any(abs((x-y)-round(x-y)) > 2e-8 for x, y in zip(atom.coordinates, expected)):
                raise ForceError(f"fragment geometry does not reproduce YAML displacement ID {index}")
        output[index] = text
    return output, inventory


def audit_signed_pilot_dataset(dataset_dir: Path, run_dir: Path, config: Mapping[str, Any],
                               settings: Mapping[str, Any], pilot_spec: Mapping[str, Any],
                               *, expected_manifest_sha256: str) -> dict[str, Any]:
    """Bind explicitly selected signed probes to their independently audited bundle."""
    if not isinstance(expected_manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256):
        raise ForceError("pilot_dataset_manifest_sha256 must be an explicit 64-hex SHA256")
    dataset = _under(Path(dataset_dir), run_dir)
    manifest_path = dataset / "pilot_dataset_manifest.json"
    _match(manifest_path, expected_manifest_sha256)
    from pilot_dataset import audit_pilot_dataset, minimum_image_bohr
    audited = audit_pilot_dataset(dataset, expected_manifest_sha256=expected_manifest_sha256)
    if audited.get("healthy") is not True or audited.get("pilot_only") is not True:
        raise ForceError("signed pilot dataset audit did not pass as pilot-only")
    manifest = core.load_json(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("stage") != "pilot_geometry_preparation" or manifest.get("pilot_only") is not True or Path(manifest["run_dir"]).resolve() != run_dir.resolve():
        raise ForceError("signed pilot manifest has wrong schema, stage, or run")
    if manifest.get("accepted_unitcell_sha256") != core.sha256_path(run_dir / "relax/final/unitcell.in"):
        raise ForceError("signed pilot manifest does not bind accepted unitcell")
    files = manifest.get("files_sha256")
    if not isinstance(files, dict) or not {"probe_spec.json", "phono3py_disp.yaml", "unitcell.in", "supercell.in", "preflight_result.json", "preflight_inventory.json", "config.snapshot.json"} <= set(files):
        raise ForceError("signed pilot manifest lacks required bundle file hashes")
    hashes = {str(manifest_path): expected_manifest_sha256}
    for name,digest in files.items():
        if Path(name).name != name:
            raise ForceError("signed pilot bundle filename escapes dataset")
        source = _under(dataset / name, dataset)
        _match(source, digest)
        hashes[str(source)] = digest
    probe = core.load_json(dataset / "probe_spec.json")
    for key in ("supercell_id", "cutoff_id"):
        if probe.get(key) != pilot_spec.get(key) or probe.get(key) != settings.get(key):
            raise ForceError("audited probe_spec differs from force pilot " + key)
    for key in ("amplitude_angstrom", "amplitude_bohr"):
        value = core.positive_number(probe.get(key), key)
        if not math.isclose(value, core.positive_number(pilot_spec.get(key), key), rel_tol=core.FLOAT_REL_TOL) or not math.isclose(value, settings[key], rel_tol=core.FLOAT_REL_TOL):
            raise ForceError("audited probe_spec differs from force pilot " + key)
    texts, inventory = _dataset_inputs(dataset, settings, dataset, config)
    roles = core.required(manifest, "geometry_plan.roles_by_displacement_id")
    if not isinstance(roles, dict) or audited.get("generated_displacement_ids") != inventory["included_displacement_ids"]:
        raise ForceError("signed pilot audit/geometry plan displacement IDs differ")
    originals, duplicates = pilot_spec.get("displacement_ids"), pilot_spec.get("duplicate_displacement_ids", [])
    if not isinstance(originals,list) or not isinstance(duplicates,list):
        raise ForceError("pilot displacement IDs must be explicit lists")
    selected = originals + duplicates
    if any(type(i) is not int or i <= 0 or str(i) not in roles or not roles[str(i)] or i not in texts for i in selected):
        raise ForceError("selected pilot ID is absent from audited geometry_plan roles")
    pristine = parse_qe_input(texts[0])
    cell_bohr = [[x/core.BOHR_TO_ANGSTROM for x in row] for row in pristine.cell_parameters]
    kinds = {"0": "pristine"}
    for index in inventory["included_displacement_ids"]:
        parsed = parse_qe_input(texts[index])
        count = sum(core.vector_norm(minimum_image_bohr([x-y for x,y in zip(a.coordinates,b.coordinates)], cell_bohr)) > 1e-8
                    for a,b in zip(parsed.atomic_positions, pristine.atomic_positions))
        kinds[str(index)] = "single" if count == 1 else "double" if count == 2 else "invalid"
        if index in selected:
            expected_kind = "single" if count == 1 else "mixed" if count == 2 else None
            if expected_kind is None or not any(isinstance(role, dict) and role.get("kind") == expected_kind for role in roles[str(index)]):
                raise ForceError("signed geometry does not match declared single/mixed role")
    return {"dataset_dir": str(dataset), "expected_manifest_sha256": expected_manifest_sha256,
            "audit_result": audited, "probe_spec_sha256": core.sha256_path(dataset / "probe_spec.json"),
            "files_sha256": hashes, "task_kinds": kinds}


def validate_initial_pilot_composition(pilot_spec: Mapping[str, Any], task_kinds: Mapping[str,str]) -> None:
    """Exactly two pristine and one independent duplicate of each probe kind."""
    originals = pilot_spec.get("displacement_ids")
    duplicates = pilot_spec.get("duplicate_displacement_ids")
    if (pilot_spec.get("pristine_repetitions", 1) != 2 or not isinstance(originals,list)
        or len(originals) != 2 or any(type(i) is not int for i in originals) or len(set(originals)) != 2
        or not isinstance(duplicates,list) or len(duplicates) != 2 or sorted(duplicates) != sorted(originals)
        or sorted(task_kinds.get(str(i), "invalid") for i in originals) != ["double", "single"]):
        raise ForceError("initial pilot requires exactly 2 pristine + 1 single and its duplicate + 1 double and its duplicate (6 SCFs)")


def prepare_force(config_path: Path, run_dir: Path, *, preflight_inventory: Path,
                  dataset_dir: Path, output_dir: Path, pseudo_dir: Path,
                  mode: str = "production", pilot_spec: Mapping[str, Any] | None = None,
                  selection_evidence: Path | None = None,
                  resource_request: Mapping[str, Any] | None = None,
                  pilot_dataset_manifest_sha256: str | None = None) -> dict[str, Any]:
    """Prepare a new immutable force bundle, including a matched pristine task.

    A pilot_spec explicitly supplies settings, rationale and displacement_ids;
    optional duplicate_displacement_ids and pristine_repetitions supply noise
    checks. selection_evidence is an external pilot_analysis audit receipt.
    resource_request supplies phase, mpi_ranks, walltime_hours, max_concurrency,
    timing_evidence and usage_evidence; production also supplies the explicit
    batch displacement_ids. All batch counts include the pristine tasks.
    """
    config_path, run_dir = Path(config_path).resolve(), core.safe_run_dir(Path(run_dir))
    config, _ = core.validate_config(config_path)
    settings = _settings(config, mode, pilot_spec)
    dataset, inventory_path = _under(Path(dataset_dir), run_dir), _under(Path(preflight_inventory), run_dir)
    destination, pseudo_dir = _under(Path(output_dir), run_dir), Path(pseudo_dir).resolve()
    if destination.exists():
        raise ForceError("force bundle already exists; use a new immutable dataset name")
    signed_pilot = None
    if mode == "pilot":
        signed_pilot = audit_signed_pilot_dataset(dataset, run_dir, config, settings, pilot_spec,
            expected_manifest_sha256=pilot_dataset_manifest_sha256)
        if isinstance(resource_request, Mapping) and resource_request.get("phase") == "initial":
            validate_initial_pilot_composition(pilot_spec, signed_pilot["task_kinds"])
    provenance, execution = _provenance(config, config_path, run_dir, inventory_path, dataset)
    if signed_pilot:
        provenance.update(signed_pilot["files_sha256"])
    preflight = core.load_json(dataset / "preflight_result.json")
    if any(preflight.get(k) != settings[v] for k, v in (("supercell_id", "supercell_id"), ("cutoff_id", "cutoff_id"), ("generated_atoms", "atoms"))):
        raise ForceError("preflight dataset differs from explicit selection")
    pseudo_hashes = core.pseudopotential_hashes(config, pseudo_dir)
    old_pseudos = execution.get("pseudopotentials", {})
    if {k: v["sha256"] for k, v in pseudo_hashes.items()} != {k: v["sha256"] for k, v in old_pseudos.items()}:
        raise ForceError("pseudopotential contents differ from accepted relax")
    texts, inventory = _dataset_inputs(dataset, settings, pseudo_dir, config)
    ids = inventory["included_displacement_ids"]
    selection = None
    if mode == "production":
        if preflight.get("selection_eligible") is not True or inventory["nonzero_included_pair_groups"] < 1:
            raise ForceError("production requires selection_eligible preflight and a nonzero included pair")
        if selection_evidence is None:
            raise ForceError("production requires actual amplitude/force-accuracy selection evidence")
        selection = validate_selection_evidence(
            Path(selection_evidence), config_path, config, settings, run_dir, dataset
        )
    if ids != preflight.get("generated_displacement_ids"):
        raise ForceError("preflight ID inventory differs from YAML")
    if mode == "pilot":
        assert pilot_spec is not None
        ids = pilot_spec.get("displacement_ids")
        duplicates = pilot_spec.get("duplicate_displacement_ids", [])
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            raise ForceError("pilot displacement_ids must be an explicit nonempty unique list")
        if not isinstance(duplicates, list):
            raise ForceError("pilot duplicate_displacement_ids must be a list")
        if any(isinstance(i, bool) or not isinstance(i, int) or i not in texts or i == 0 for i in ids + duplicates):
            raise ForceError("pilot selects an absent/excluded displacement")
        if any(i not in ids for i in duplicates):
            raise ForceError("pilot duplicates must repeat selected probe IDs")
        ids = ids + duplicates
    else:
        batch_ids = resource_request.get("displacement_ids") if isinstance(resource_request, Mapping) else None
        if not isinstance(batch_ids, list) or not batch_ids or len(set(batch_ids)) != len(batch_ids) or any(isinstance(i,bool) or not isinstance(i,int) or i not in ids for i in batch_ids):
            raise ForceError("production requires explicit unique batch displacement_ids")
        ids = batch_ids
    if len(ids) > config["displacements"]["hard_cap"]:
        raise ForceError("requested tasks including duplicates exceed hard cap")
    pristine_count = pilot_spec.get("pristine_repetitions", 1) if mode == "pilot" else 1
    if isinstance(pristine_count, bool) or not isinstance(pristine_count,int) or not 1 <= pristine_count <= 2:
        raise ForceError("pristine_repetitions must be 1 or 2")
    rows, tasks = [], []
    for task_id, displacement_id in enumerate([0]*pristine_count + ids):
        role = "pristine" if displacement_id == 0 else "displacement"
        input_path = destination / "inputs" / f"task-{task_id:05d}.in"
        text = texts[displacement_id]
        parsed = parse_qe_input(text)
        row = {"task_id": task_id, "displacement_id": displacement_id, "role": role,
               "input_path": str(input_path), "input_sha256": _hash_text(text)}
        rows.append(row)
        tasks.append({**row, "nat": parsed.nat, "atom_labels": [x.label for x in parsed.atomic_positions],
                      "species_types": [next(i+1 for i, s in enumerate(parsed.atomic_species) if s.label == atom.label) for atom in parsed.atomic_positions]})
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    receipt = _reserve_budget(config, run_dir, destination, len(tasks), _hash_text(stream.getvalue()), mode, resource_request,
                              [t["input_sha256"] for t in tasks if t["displacement_id"] != 0] if mode == "production" else [], settings)
    for task in tasks:
        core.write_immutable(Path(task["input_path"]), texts[task["displacement_id"]])
    core.write_immutable(destination / "task_map.tsv", stream.getvalue())
    provenance.update({str(p): core.sha256_path(p) for p in dataset.glob("supercell*.in")})
    manifest = {"schema_version": 1, "stage": "force", "mode": mode, "material": config["material"]["formula"],
                "config_sha256": core.sha256_path(config_path), "force_policy_sha256": core.canonical_sha256({"production": config["production"], "force": config["force_and_amplitude_validation"]}),
                "settings": settings, "pilot_spec": dict(pilot_spec) if mode == "pilot" and pilot_spec else None,
                "selection_validation": selection,
                "signed_pilot_dataset": signed_pilot,
                "budget_receipt_sha256": core.sha256_path(destination / "budget_receipt.json"),
                "pseudopotentials": pseudo_hashes, "evidence_sha256": provenance,
                "selection_evidence_sha256": dict(selection["evidence_sha256"]) if selection else {},
                "workflow_sha256": {str(Path(__file__).with_name(name)): core.sha256_path(Path(__file__).with_name(name)) for name in (("campaign.py", "qe_input.py", "qe_output.py", "pilot_analysis.py", "pilot_dataset.py", "pilot_evidence.py", "postprocess_backend.py") if selection else ("campaign.py", "qe_input.py", "qe_output.py", "pilot_dataset.py") if signed_pilot else ("campaign.py", "qe_input.py", "qe_output.py"))},
                "backend_sha256": core.sha256_path(Path(__file__)), "task_map_sha256": core.sha256_path(destination / "task_map.tsv"),
                "tasks": tasks, "task_count": len(tasks), "created_utc": core.utc_now(),
                "limitations": ["Force collection is not a convergence or thermal-conductivity result.", "Every displaced force must be paired with this bundle's pristine task."]}
    core.write_json_immutable(destination / "force_manifest.json", manifest)
    return {"healthy": True, "mode": mode, "task_count": len(tasks), "task_map": str(destination / "task_map.tsv"), "manifest": str(destination / "force_manifest.json"), "budget_receipt": str(destination / "budget_receipt.json"), "maximum_concurrency": receipt["maximum_concurrency"]}


def verify_selection_provenance(manifest, run_dir, *, config_path=None):
    """Selection studies may contain many datasets; keep them out of force identity."""
    sources = manifest.get("selection_evidence_sha256", {})
    if not isinstance(sources, dict):
        raise ForceError("selection_evidence_sha256 must be a separate path/hash mapping")
    if manifest.get("mode") == "production":
        validation = manifest.get("selection_validation")
        if not isinstance(validation, dict) or not sources or sources != validation.get("evidence_sha256"):
            raise ForceError("production selection provenance is missing or differs from its audit")
    elif sources:
        raise ForceError("pilot bundle cannot claim production selection provenance")
    for raw_path,digest in sources.items():
        if not isinstance(raw_path,str) or not Path(raw_path).is_absolute() or not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
            raise ForceError("invalid selection source path/hash")
        _match(_under(Path(raw_path), run_dir), digest)
    if manifest.get("mode") == "production":
        # The manifest itself is not an external trust anchor. Reproduce the
        # scientific audit, even when all its internal hashes are self-consistent.
        if config_path is None:
            raise ForceError("production selection replay requires the current config path")
        raw_receipt = validation.get("selection_receipt_path")
        receipt_hash = validation.get("selection_receipt_sha256")
        if not isinstance(raw_receipt, str) or not Path(raw_receipt).is_absolute() or sources.get(raw_receipt) != receipt_hash:
            raise ForceError("production selection receipt is not explicitly hash-anchored")
        receipt_path = _under(Path(raw_receipt), run_dir)
        _match(receipt_path, receipt_hash)
        config_path = Path(config_path).resolve()
        _match(config_path, manifest["config_sha256"])
        config, _ = core.validate_config(config_path)
        datasets = [Path(p) for p in manifest["evidence_sha256"] if Path(p).name == "phono3py_disp.yaml"]
        if len(datasets) != 1:
            raise ForceError("selection replay requires one current force displacement dataset")
        replay = validate_selection_evidence(receipt_path, config_path, config,
            manifest["settings"], run_dir, _under(datasets[0], run_dir).parent)
        if replay != validation:
            raise ForceError("stored production selection audit differs from raw-evidence replay")


def _claim_execution(run_dir, manifest, receipt, task_id, attempt, retry_evidence):
    ledger = safe_budget_ledger(run_dir)
    claims = ledger / "executions"
    if os.path.lexists(claims):
        if claims.is_symlink() or not claims.is_dir() or claims.resolve().parent != ledger:
            raise ForceError("force-budget executions directory is unsafe")
    else:
        claims.mkdir()
        if claims.is_symlink() or not claims.is_dir() or claims.resolve().parent != ledger:
            raise ForceError("force-budget executions directory creation is unsafe")
    key = f"{manifest['task_map_sha256']}-{task_id}"
    with _ledger_lock_path(ledger).open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous = [core.load_json(p) for p in sorted(claims.glob(key + "-*.json"))]
        if any(Path(p["attempt_path"]) == attempt for p in previous):
            raise ForceError("attempt already claimed; retry requires a new attempt ID")
        if len(previous) > receipt["maximum_technical_retries_per_task"]:
            raise ForceError("maximum one technical retry has already been used")
        if previous:
            prior = previous[-1]
            prior_result = Path(prior["attempt_path"]) / "result.json"
            if prior_result.exists() and core.load_json(prior_result).get("healthy") is True:
                raise ForceError("successful task cannot be retried")
            if retry_evidence is None:
                raise ForceError("retry needs scheduler evidence of a technical failure")
            evidence = core.load_json(_under(Path(retry_evidence), run_dir))
            accounting = _under(Path(evidence["accounting_path"]), run_dir)
            _match(accounting, evidence["accounting_sha256"])
            rows = list(csv.DictReader(io.StringIO(accounting.read_text()), delimiter="|"))
            matched = [r for r in rows if r.get("JobIDRaw") == prior["job_id"]]
            if len(matched) != 1 or matched[0].get("State") not in ("NODE_FAIL", "BOOT_FAIL", "PREEMPTED"):
                raise ForceError("retry is not a proven node/boot/preemption technical failure")
        active = 0
        for path in claims.glob("*.json"):
            record = core.load_json(path)
            folder = Path(record["attempt_path"])
            if record not in previous and not (folder / "result.json").exists() and not (folder / "failure.json").exists():
                active += 1
        if active >= receipt["maximum_concurrency"]:
            raise ForceError("material force concurrency limit reached or prior state unresolved")
        record = {"task_id": task_id, "task_map_sha256": manifest["task_map_sha256"],
                  "budget_receipt_sha256": manifest["budget_receipt_sha256"],
                  "technical_retry_count": len(previous), "attempt_path": str(attempt),
                  "retry_evidence_sha256": core.sha256_path(Path(retry_evidence)) if retry_evidence else None,
                  "job_id": os.environ.get("SLURM_JOB_ID"), "created_utc": core.utc_now()}
        claim_path = claims / f"{key}-{len(previous)}.json"
        if os.path.lexists(claim_path):
            raise ForceError("force-budget execution claim path already exists or is unsafe")
        core.write_json_immutable(claim_path, record)
    return record


def run_force_task(config_path: Path, run_dir: Path, *, task_map: Path, task_id: int,
                   attempt_path: Path, compute_guard: Callable[[], None] | None = None,
                   retry_evidence: Path | None = None) -> dict[str, Any]:
    """Run exactly one task. Retries require a new attempt_path; never resume QE.

    compute_guard is an integration/test hook; production callers omit it and
    use the shared compute-node guard. The driver never launches on its own.
    """
    (compute_guard or core.require_compute_node)()
    run_dir = core.safe_run_dir(Path(run_dir))
    task_map = _under(Path(task_map), run_dir)
    attempt = _under(Path(attempt_path), run_dir)
    config_path = Path(config_path).resolve()
    manifest_path = task_map.parent / "force_manifest.json"
    manifest = core.load_json(manifest_path)
    _match(task_map, manifest["task_map_sha256"])
    _match(Path(__file__), manifest["backend_sha256"])
    for path, digest in manifest["workflow_sha256"].items():
        _match(Path(path), digest)
    _match(config_path, manifest["config_sha256"])
    receipt_path = task_map.parent / "budget_receipt.json"
    _match(receipt_path, manifest["budget_receipt_sha256"])
    receipt = core.load_json(receipt_path)
    if receipt["task_map_sha256"] != manifest["task_map_sha256"] or receipt["task_count"] != manifest["task_count"]:
        raise ForceError("budget receipt does not bind this task map")
    for path, digest in receipt["evidence_sha256"].items():
        _match(_under(Path(path), run_dir), digest)
    if compute_guard is None and int(os.environ.get("SLURM_NTASKS", "0")) != receipt["mpi_ranks"]:
        raise ForceError("MPI allocation differs from budget receipt")
    if compute_guard is None and int(os.environ.get("SLURM_CPUS_PER_TASK", "1")) != 1:
        raise ForceError("budget receipt assumes one allocated CPU per MPI task")
    if isinstance(task_id, bool) or not isinstance(task_id, int) or not 0 <= task_id < manifest["task_count"]:
        raise ForceError("task_id is outside the immutable map")
    rows = list(csv.DictReader(io.StringIO(task_map.read_text()), delimiter="\t"))
    tasks = manifest["tasks"]
    if len(rows) != len(tasks) or [int(r["task_id"]) for r in rows] != list(range(len(tasks))):
        raise ForceError("task map must have exactly the contiguous 0..N-1 domain")
    task = tasks[task_id]
    if any(str(task[key]) != rows[task_id][key] for key in FIELDS):
        raise ForceError("task row differs from force manifest")
    for path, digest in manifest["evidence_sha256"].items():
        _match(_under(Path(path), run_dir), digest)
    verify_selection_provenance(manifest, run_dir, config_path=config_path)
    for item in manifest["pseudopotentials"].values():
        _match(Path(item["file"]), item["sha256"])
    input_path = _under(Path(task["input_path"]), task_map.parent)
    _match(input_path, task["input_sha256"])
    if attempt.is_relative_to(task_map.parent) or task_map.parent.is_relative_to(attempt):
        raise ForceError("attempt directory must be separate from immutable input bundle")
    execution_claim = _claim_execution(run_dir, manifest, receipt, task_id, attempt, retry_evidence)
    # cluster.env creates an attempt directory containing context metadata.
    attempt.mkdir(parents=True, exist_ok=True)
    claim = attempt / "force_claim.json"
    try:
        with claim.open("x") as handle:
            json.dump({"task_id": task_id, "manifest_sha256": core.sha256_path(manifest_path)}, handle)
    except FileExistsError as exc:
        raise ForceError("attempt already claimed; retry requires a new attempt ID") from exc
    for filename in ("scf.in", "scf.out", "scf.err", "launch.json", "result.json", "qe-tmp"):
        if (attempt / filename).exists():
            raise ForceError("attempt contains prior force evidence; new attempt required")
    core.write_immutable(attempt / "scf.in", input_path.read_text())
    command = core.qe_command("scf.in")
    core.write_json_immutable(attempt / "launch.json", {"task": task, "force_manifest_sha256": core.sha256_path(manifest_path), "command": command, "created_utc": core.utc_now(), "job_id": os.environ.get("SLURM_JOB_ID"), "budget_execution_claim": execution_claim})
    try:
        process = core.run_process(command, attempt, attempt / "scf.out", attempt / "scf.err")
        _match(attempt / "scf.in", task["input_sha256"])
        for item in manifest["pseudopotentials"].values():
            _match(Path(item["file"]), item["sha256"])
        health = inspect_output(attempt / "scf.out", task["nat"])
        output = (attempt / "scf.out").read_text(errors="replace")
        # QE force type indices are one-based indices into ATOMIC_SPECIES.
        blocks = re.split(r"(?m)^\s*Forces acting on atoms[^\n]*\n", output)
        force_types = []
        for line in blocks[-1].splitlines():
            match = re.fullmatch(r"\s*atom\s+\d+\s+type\s+(\d+)\s+force\s*=.*", line)
            if match:
                force_types.append(int(match[1]))
            elif force_types:
                break
        if force_types != task["species_types"]:
            raise ForceError("QE force atom-type order differs from submitted input")
        if re.search(r"MPI_ABORT|Error in routine|segmentation fault|SIGSEGV", (attempt / "scf.err").read_text(errors="replace"), re.I):
            raise ForceError("QE stderr contains a fatal error")
        result = {"healthy": health["healthy"], "task_id": task_id, "displacement_id": task["displacement_id"], "role": task["role"], "health": health, "process": process, "input_sha256": task["input_sha256"], "output_sha256": core.sha256_path(attempt / "scf.out"), "force_manifest_sha256": core.sha256_path(manifest_path)}
        core.write_json_immutable(attempt / "result.json", result)
        if not health["healthy"]:
            raise ForceError("force output failed strict health checks")
        return result
    except Exception as exc:
        core.write_json_immutable(attempt / "failure.json", {"task_id": task_id, "error": str(exc), "error_type": type(exc).__name__, "created_utc": core.utc_now()})
        raise

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
    ledger = run_dir / ".force_budget"
    ledger.mkdir(exist_ok=True)
    with (ledger / "lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous = [core.load_json(p) for p in ledger.glob("reservation-*.json")]
        for old in previous:
            _match(Path(old["receipt_path"]), old["receipt_sha256"])
            previous_receipt = core.load_json(Path(old["receipt_path"]))
            if set(production_input_hashes) & set(previous_receipt.get("production_input_hashes", [])):
                raise ForceError("production force already reserved; technical retries must use its original task map")
        prior_production = sum(x["phase"] == "production" for x in previous)
        if phase == "initial":
            limit = min(6, policy["initial_timing_and_noise_batch"]["maximum_new_scf_tasks"])
            if task_count + sum(x["task_count"] for x in previous if x["phase"] == "initial") > limit:
                raise ForceError("initial timing/noise campaign exceeds cumulative six SCFs")
        elif phase == "validation":
            limit = min(32, policy["pilot_batch_maximum_new_scf_tasks"])
            if approved is None and task_count + sum(x["task_count"] for x in previous if x["phase"] == "validation") > limit:
                raise ForceError("unbudgeted validation pilot exceeds cumulative 32 SCFs")
        else:
            limit = min(64 if prior_production else 32, policy["production_later_batch_maximum_tasks"] if prior_production else policy["production_first_batch_maximum_tasks"])
        if task_count > limit:
            raise ForceError(f"requested batch exceeds {limit} SCFs including pristine")
        reserved = sum(x["reserved_core_hours"] for x in previous)
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
        receipt_path = destination / "budget_receipt.json"
        core.write_json_immutable(receipt_path, receipt)
        ledger_record = {"phase": phase, "task_count": task_count, "reserved_core_hours": reservation,
                         "receipt_path": str(receipt_path), "receipt_sha256": core.sha256_path(receipt_path)}
        core.write_json_immutable(ledger / f"reservation-{len(previous):06d}.json", ledger_record)
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
    paths = [run_dir / core.RUN_MANIFEST, final / "gate.json", final / "provenance.json", final / "unitcell.in", inventory_path, result_path, dataset / "phono3py_disp.yaml", accepted / "execution_manifest.json", accepted / "starting_structure_audit.json"]
    paths.extend(accepted / name for name in ("relax.in", "relax.out", "pristine.in", "pristine.out"))
    return {str(p): core.sha256_path(p) for p in paths}, execution


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
    ledger = run_dir / ".force_budget"
    claims = ledger / "executions"
    claims.mkdir(exist_ok=True)
    key = f"{manifest['task_map_sha256']}-{task_id}"
    with (ledger / "lock").open("a") as lock:
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
        core.write_json_immutable(claims / f"{key}-{len(previous)}.json", record)
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

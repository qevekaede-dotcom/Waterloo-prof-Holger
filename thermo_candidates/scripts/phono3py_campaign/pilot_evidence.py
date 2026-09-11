"""Reparse immutable QE pilot evidence before evaluating numerical gates.

No executable is launched and no scientific setting is selected here. References
contain paths and hashes only; forces, geometry, site identities and settings are
derived from audited files. ``audit_pilot_samples`` is also useful for an incomplete
pilot, without claiming convergence. A complete explicit study may be evaluated
with ``analyze_pilot_evidence`` and saved with ``write_selection_receipt``.

Study schema (version 1): rationale, dataset_manifests (ID -> manifest_path and
manifest_sha256), samples (ID -> dataset_id, manifest_path, manifest_sha256,
result_path, result_sha256), preflight_dataset_id, selected_settings,
reference_settings, force_comparisons and amplitude_probes. For production-target
lineage, replace preflight_dataset_id with target_preflight = {candidate_dir,
inventory_path, inventory_sha256, yaml_sha256}. This must name a separately
enumerated eligible full dataset. The last two fields
use pilot_analysis's role-reference schema. Their role assignments are checked
against each regenerated pilot geometry plan before the numerical analysis.

The receipt embeds this study, allowing replay_selection_receipt to derive the
entire report again from original files. A self-consistent JSON hash alone does
not establish a valid selection. Signed pilot subsets remain production-
ineligible: this interface does not relabel their YAML hash as a full dataset.
An independently checked target hash is recorded separately when supplied.
Pair-shell labels currently establish species pairs and measured pair distances,
not radial-shell completeness. Real spglib is required for a real evidence audit.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from collections.abc import Mapping

import campaign as core
import force_backend as fb
import pilot_analysis as pa
import pilot_dataset as pd
import postprocess_backend as pp
from qe_input import parse_qe_input
from qe_output import parse_last_force_block

PilotEvidenceError = core.CampaignError


def _require(condition, message):
    if not condition:
        raise PilotEvidenceError(message)


def _path(value, run_dir, label):
    _require(isinstance(value, (str, Path)) and Path(value).is_absolute(),
             f"absolute {label} path required")
    path = fb._under(Path(value), run_dir)
    _require("READY_TO_ATTACH" not in path.parts, "frozen attachment evidence is forbidden")
    return path


def _match(path, digest, hashes):
    pa._sha(digest)
    fb._match(path, digest)
    _require(str(path) not in hashes or hashes[str(path)] == digest,
             "one source is referenced by inconsistent hashes")
    hashes[str(path)] = digest


def _claim_identity(run_dir, manifest, attempt, hashes):
    """Bind independent-run identity to the backend's immutable execution ledger."""
    launch = core.load_json(attempt / "launch.json")
    claim = launch.get("budget_execution_claim")
    _require(isinstance(claim, Mapping), "missing immutable budget execution claim")
    task_id = launch["task"]["task_id"]
    retry = claim["technical_retry_count"]
    _require(type(retry) is int and retry in (0, 1), "invalid technical retry index")
    _require(claim["attempt_path"] == str(attempt) and claim["task_id"] == task_id
             and claim["task_map_sha256"] == manifest["task_map_sha256"]
             and claim["budget_receipt_sha256"] == manifest["budget_receipt_sha256"]
             and claim["job_id"] == launch["job_id"] and isinstance(claim["job_id"], str)
             and claim["job_id"].isdigit(), "execution claim identity mismatch")
    path = run_dir / ".force_budget" / "executions" / f"{manifest['task_map_sha256']}-{task_id}-{retry}.json"
    _require(core.load_json(path) == claim, "execution ledger differs from launch claim")
    _match(path, core.sha256_path(path), hashes)
    return str(path)


def _target(config, config_path, run_dir, reference, selected, hashes):
    _require(isinstance(reference, Mapping) and set(reference) ==
             {"candidate_dir", "inventory_path", "inventory_sha256", "yaml_sha256"},
             "explicit full target preflight paths/hashes required")
    folder = _path(reference["candidate_dir"], run_dir, "target candidate")
    inventory_path = _path(reference["inventory_path"], run_dir, "target inventory")
    _match(inventory_path, reference["inventory_sha256"], hashes)
    _match(folder / "phono3py_disp.yaml", reference["yaml_sha256"], hashes)
    provenance, _ = fb._provenance(config, config_path, run_dir, inventory_path, folder)
    for name, digest in provenance.items():
        _match(_path(name, run_dir, "target provenance"), digest, hashes)
    inventory, result = core.load_json(inventory_path), core.load_json(folder / "preflight_result.json")
    _require(
        inventory.get("preflight_complete") is True
        and inventory.get("full_config_preflight_complete", True) is True
        and result.get("selection_eligible") is True
             and result.get("pilot_only") is not True and result.get("count_only") is not True,
             "target must be an eligible complete full preflight, not a signed/count-only subset")
    settings = fb._settings(config, "pilot", {**selected, "rationale": "audit explicit target settings"})
    _require(settings == selected, "target selected settings are incomplete or noncanonical")
    _, ids = fb._dataset_inputs(folder, settings, folder, config)
    _require(result["generated_displacement_ids"] == ids["included_displacement_ids"]
             and ids["nonzero_included_pair_groups"] > 0, "target ID inventory/nonzero-pair mismatch")
    data = fb._yaml(folder / "phono3py_disp.yaml")
    _require(result["supercell_id"] == settings["supercell_id"] and result["cutoff_id"] == settings["cutoff_id"],
             "target preflight selection IDs mismatch")
    symmetry = pd.site_inventory(data, (folder / "unitcell.in").read_text(), config)
    for path in folder.glob("supercell*.in"):
        _match(path, core.sha256_path(path), hashes)
    return {"folder": folder, "data": data, "symmetry": symmetry,
            "yaml_sha256": reference["yaml_sha256"]}


def _audit_samples(config_path, run_dir, dataset_manifests, sample_references,
                   target_preflight, selected_settings):
    config_path = Path(config_path).resolve()
    config, _ = core.validate_config(config_path)
    run_dir = core.safe_run_dir(Path(run_dir))
    _require(isinstance(dataset_manifests, Mapping) and dataset_manifests,
             "explicit signed pilot dataset manifests required")
    _require(isinstance(sample_references, Mapping) and sample_references,
             "explicit immutable force sample references required")
    hashes = {str(config_path): core.sha256_path(config_path)}
    for name in ("pilot_evidence.py", "pilot_dataset.py", "pilot_analysis.py",
                 "postprocess_backend.py", "force_backend.py", "campaign.py", "qe_input.py", "qe_output.py"):
        path = Path(__file__).with_name(name)
        hashes[str(path)] = core.sha256_path(path)
    target = (_target(config, config_path, run_dir, target_preflight, selected_settings, hashes)
              if target_preflight is not None else None)
    datasets, accepted_hash = {}, core.sha256_path(run_dir / "relax/final/unitcell.in")
    for identifier, reference in dataset_manifests.items():
        _require(isinstance(identifier, str) and identifier.strip(), "invalid dataset ID")
        _require(set(reference) == {"manifest_path", "manifest_sha256"}, "dataset references accept paths/hashes only")
        manifest_path = _path(reference["manifest_path"], run_dir, "pilot manifest")
        _require(manifest_path.name == "pilot_dataset_manifest.json", "signed pilot manifest required")
        _match(manifest_path, reference["manifest_sha256"], hashes)
        folder, manifest = manifest_path.parent, core.load_json(manifest_path)
        pd.audit_pilot_dataset(folder, expected_manifest_sha256=reference["manifest_sha256"])
        # Recheck the accepted-run origin as well as the signed bundle. Saved
        # manifests may point to original electronic inputs outside run_dir.
        fb._provenance(config, config_path, run_dir, folder / "preflight_inventory.json", folder)
        origin = core.load_json(run_dir / core.RUN_MANIFEST)
        for name, key in (("source_qe_input", "source_qe_sha256"),
                          ("source_relax_output", "source_relax_sha256")):
            source = Path(origin[name])
            _require(source.is_absolute() and "READY_TO_ATTACH" not in source.parts,
                     "original source must be an absolute non-frozen research record")
            _match(source.resolve(), origin[key], hashes)
        _require(manifest["accepted_unitcell_sha256"] == accepted_hash,
                 "pilot dataset accepted cell differs from current accepted evidence")
        snapshot = core.load_json(folder / "config.snapshot.json")
        for key in ("material", "electronic_model", "pseudopotentials", "software", "symmetry_validation", "displacements"):
            _require(snapshot[key] == config[key], f"pilot geometry policy drift: {key}")
        for name, digest in manifest["files_sha256"].items():
            _match(folder / name, digest, hashes)
        for name, digest in manifest["source_sha256"].items():
            _match(_path(name, run_dir, "pilot source"), digest, hashes)
        data = fb._yaml(folder / "phono3py_disp.yaml")
        if target is not None:
            parent = fb._yaml(Path(manifest["candidate_dir"]) / "phono3py_disp.yaml")
            for key in ("physical_unit", "unit_cell", "supercell", "supercell_matrix"):
                _require(data[key] == parent[key] == target["data"][key],
                         f"signed parent/full target geometry mismatch: {key}")
            _require(data.get("primitive_matrix") == parent.get("primitive_matrix") == target["data"].get("primitive_matrix"),
                     "signed parent/full target primitive mapping mismatch")
            cutoff = target["data"]["displacement_pair_info"]["cutoff_pair_distance"]
            _require(all(math.isclose(value["displacement_pair_info"]["cutoff_pair_distance"], cutoff, rel_tol=1e-10)
                         for value in (data, parent)), "signed parent/full target cutoff mismatch")
            _require(manifest["geometry_plan"]["symmetry"]["atom_order"] == target["symmetry"]["atom_order"]
                     and (folder / "unitcell.in").read_bytes() == (target["folder"] / "unitcell.in").read_bytes(),
                     "signed parent/full target accepted cell or atom/site order mismatch")
        datasets[identifier] = {"folder": folder, "manifest": manifest, "data": data,
                                "plan": manifest["geometry_plan"]}
    samples, identities = {}, set()
    for identifier, reference in sample_references.items():
        _require(isinstance(identifier, str) and identifier.strip(), "invalid sample ID")
        _require(set(reference) == {"dataset_id", "manifest_path", "manifest_sha256", "result_path", "result_sha256"},
                 "sample references accept dataset ID and paths/hashes only")
        dataset = datasets[reference["dataset_id"]]
        manifest_path = _path(reference["manifest_path"], run_dir, "force manifest")
        result_path = _path(reference["result_path"], run_dir, "force result")
        _require(result_path.name == "result.json", "immutable result.json required")
        _match(manifest_path, reference["manifest_sha256"], hashes)
        _match(result_path, reference["result_sha256"], hashes)
        manifest, result = core.load_json(manifest_path), core.load_json(result_path)
        _require(manifest["mode"] == "pilot" and manifest["material"] == config["material"]["formula"],
                 "sample must come from this material's pilot force bundle")
        artifact = pp.load_force_artifact(manifest_path, result_path.parent, result["task_id"])
        _match(manifest_path.parent / "budget_receipt.json", manifest["budget_receipt_sha256"], hashes)
        settings = fb._settings(config, "pilot", manifest["pilot_spec"])
        _require(settings == manifest["settings"], "manifest settings differ from explicit validated pilot spec")
        folder, data, plan = dataset["folder"], dataset["data"], dataset["plan"]
        _require(artifact.manifest["dataset_sha256"] == core.sha256_path(folder / "phono3py_disp.yaml")
                 and artifact.manifest["supercell_sha256"] == core.sha256_path(folder / "supercell.in"),
                 "force manifest anchors a different dataset/supercell")
        evidence = manifest["evidence_sha256"]
        for name in ("phono3py_disp.yaml", "supercell.in"):
            _require(evidence.get(str(folder / name)) == core.sha256_path(folder / name),
                     "force evidence does not anchor exact pilot dataset paths")
        _require(evidence.get(str(run_dir / "relax/final/unitcell.in")) == accepted_hash,
                 "force evidence does not anchor accepted unitcell")
        pseudo_parents = {Path(p["file"]).resolve().parent for p in manifest["pseudopotentials"].values()}
        _require(len(pseudo_parents) == 1, "one pseudopotential directory required by force generator")
        pseudo_dir = next(iter(pseudo_parents))
        texts, _ = fb._dataset_inputs(folder, settings, pseudo_dir, config)
        displacement_id = artifact.displacement_id
        actual_text = Path(artifact.input_path).read_text()
        _require(actual_text == texts[displacement_id],
                 "raw force input differs from independently regenerated geometry/settings")
        # Reparse Cartesian minimum-image displacements from the actual QE input.
        parsed = parse_qe_input(actual_text)
        cell = data["supercell"]["lattice"]
        displacements = []
        for atom, point in zip(parsed.atomic_positions, data["supercell"]["points"]):
            value = pd.minimum_image_bohr([a-b for a,b in zip(atom.coordinates, point["coordinates"])], cell)
            displacements.append([0.0 if abs(x) < 1e-12 else x for x in value])
        force_record = parse_last_force_block(artifact.output_path, parsed.nat)
        independent = _claim_identity(run_dir, manifest, result_path.parent, hashes)
        _require(independent not in identities, "one executed task was relabeled as multiple independent samples")
        identities.add(independent)
        roles = plan["roles_by_displacement_id"][str(displacement_id)]
        mixed = [p for p in plan["probes"] if p["kind"] == "mixed" and displacement_id in p["displacement_ids"].values()]
        shells = {p["pair_shell_id"] for p in mixed}
        _require(len(shells) <= 1, "one geometry has ambiguous pair-shell classification")
        sample = {"forces_ry_bohr": [list(row) for row in force_record.forces_ry_bohr],
            "displacements_bohr": displacements, "atom_order": copy.deepcopy(plan["symmetry"]["atom_order"]),
            "settings": settings, "accepted_unitcell_sha256": accepted_hash,
            "supercell_sha256": artifact.manifest["supercell_sha256"],
            "dataset_sha256": artifact.manifest["dataset_sha256"],
            "input_sha256": artifact.manifest["input_sha256"], "output_sha256": artifact.manifest["output_sha256"],
            "raw_audit_backend_sha256": core.sha256_path(Path(__file__)), "independent_run_id": independent,
            "geometry_roles": copy.deepcopy(roles), "dataset_id": reference["dataset_id"],
            "displacement_id": displacement_id}
        if shells:
            sample["pair_shell_id"] = next(iter(shells))
            sample["pair_distances_bohr"] = sorted({p["pair_distance_bohr"] for p in mixed})
        if target is not None:
            sample["target_preflight_yaml_sha256"] = target["yaml_sha256"]
        samples[identifier] = sample
        for path in (manifest_path.parent / "task_map.tsv", manifest_path.parent / "budget_receipt.json",
                     Path(artifact.input_path), Path(artifact.output_path), Path(artifact.stderr_path),
                     result_path.parent / "launch.json", result_path.parent / "force_claim.json",
                     result_path.parent / "scf.process.json"):
            _match(path, core.sha256_path(path), hashes)
        for name, digest in manifest["evidence_sha256"].items():
            _match(_path(name, run_dir, "force source"), digest, hashes)
        for item in manifest["pseudopotentials"].values():
            _match(Path(item["file"]).resolve(), item["sha256"], hashes)
    for name, digest in hashes.items():
        fb._match(Path(name), digest)
    return {"healthy": True, "audited_samples": samples,
            "sample_sha256": {name: pa.canonical_sha256(value) for name,value in samples.items()},
            "source_sha256": hashes, "accepted_unitcell_sha256": accepted_hash,
            "scientific_selection_evaluated": False}


def audit_pilot_samples(config_path, run_dir, *, dataset_manifests, sample_references,
                        target_preflight=None, selected_settings=None):
    """Audit original files; incomplete pilot coverage is allowed without a pass claim."""
    try:
        return _audit_samples(config_path, run_dir, dataset_manifests, sample_references,
                              target_preflight, selected_settings)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, PilotEvidenceError):
            raise
        raise PilotEvidenceError(f"invalid raw pilot evidence: {exc}") from exc


def _check_probe_roles(study, samples):
    for probe in study["amplitude_probes"]:
        _require(probe["kind"] in ("single", "mixed"), "unknown explicit probe kind")
        roles = ("plus", "minus") if probe["kind"] == "single" else ("pp", "pm", "mp", "mm")
        for group in probe["sets"]:
            matching_probes = None
            for role in roles:
                sample = samples[group[role]]
                matches = {r["probe_id"] for r in sample["geometry_roles"] if isinstance(r, Mapping)
                           and r["kind"] == probe["kind"] and r["sign"] == role}
                matching_probes = matches if matching_probes is None else matching_probes & matches
            _require(matching_probes, "analysis sign roles do not name one regenerated geometry probe")


def analyze_pilot_evidence(config_path, run_dir, study):
    """Derive a replayable numerical report from an explicit study, never choose settings."""
    try:
        pa.canonical_sha256(study)
        _require(type(study.get("schema_version")) is int and study["schema_version"] == 1
                 and isinstance(study.get("rationale"), str) and study["rationale"].strip(),
                 "explicit versioned study and rationale required")
        config, _ = core.validate_config(Path(config_path).resolve())
        audit = audit_pilot_samples(config_path, run_dir, dataset_manifests=study["dataset_manifests"],
                                    sample_references=study["samples"], target_preflight=study.get("target_preflight"),
                                    selected_settings=study["selected_settings"])
        _check_probe_roles(study, audit["audited_samples"])
        _require(("target_preflight" in study) != ("preflight_dataset_id" in study),
                 "name exactly one full target preflight or signed preflight dataset")
        if "target_preflight" in study:
            target_yaml = Path(study["target_preflight"]["candidate_dir"]) / "phono3py_disp.yaml"
        else:
            target = study["dataset_manifests"][study["preflight_dataset_id"]]
            target_yaml = Path(target["manifest_path"]).parent / "phono3py_disp.yaml"
        record = {"schema_version": 1, "accepted_unitcell_sha256": audit["accepted_unitcell_sha256"],
            "selected_settings_sha256": pa.canonical_sha256(study["selected_settings"]),
            "preflight_yaml_sha256": core.sha256_path(target_yaml),
            "audit_backend_sha256": core.sha256_path(Path(pa.__file__)),
            "samples": {name: {k:v for k,v in reference.items() if k != "dataset_id"}
                        for name,reference in study["samples"].items()},
            "force_comparisons": copy.deepcopy(study["force_comparisons"]),
            "amplitude_probes": copy.deepcopy(study["amplitude_probes"]),
            "raw_evidence_request": copy.deepcopy(study), "raw_source_sha256": audit["source_sha256"]}
        return pa.analyze_pilot(record, audit["audited_samples"], config["force_and_amplitude_validation"],
                               study["selected_settings"], study["reference_settings"],
                               expected_sample_sha256=audit["sample_sha256"])
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, PilotEvidenceError):
            raise
        raise PilotEvidenceError(f"invalid pilot study: {exc}") from exc


def write_selection_receipt(config_path, run_dir, *, study, output_path):
    """Write one immutable report after complete raw audit and numerical evaluation."""
    run_dir = core.safe_run_dir(Path(run_dir))
    path = _path(output_path, run_dir, "selection receipt")
    _require(not path.exists(), "receipt exists; use a new immutable output path")
    report = analyze_pilot_evidence(config_path, run_dir, study)
    core.write_json_immutable(path, report)
    return {"receipt_path": str(path), "receipt_sha256": core.sha256_path(path),
            "pass": report["pass"], "production_authorized": False}


def replay_selection_receipt(config_path, run_dir, receipt_path, *, expected_receipt_sha256=None):
    """Recompute every sample and metric; reject even self-rehashed fabricated reports."""
    run_dir = core.safe_run_dir(Path(run_dir))
    path = _path(receipt_path, run_dir, "selection receipt")
    if expected_receipt_sha256 is not None:
        fb._match(path, expected_receipt_sha256)
    try:
        report = core.load_json(path)
        _require(report["raw_audit_backend_sha256"] == core.sha256_path(Path(__file__)),
                 "receipt was not produced by the current original-file auditor")
        replay = analyze_pilot_evidence(config_path, run_dir, report["input_record"]["raw_evidence_request"])
        _require(report == replay, "selection receipt differs from replay of original evidence")
        return {"healthy": True, "pass": replay["pass"], "analysis_sha256": replay["analysis_sha256"],
                "receipt_sha256": core.sha256_path(path),
                "source_sha256": replay["input_record"]["raw_source_sha256"]}
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, PilotEvidenceError):
            raise
        raise PilotEvidenceError(f"non-replayable pilot receipt: {exc}") from exc

"""Read-only numerical gates for *already audited* QE pilot samples.

Public API: ``analyze_pilot(record, audited_samples, policy, selected_settings,
reference_settings, *, expected_sample_sha256)``. No files are opened or written.
The caller must first reparse healthy raw outputs, verify input/output hashes,
geometry, atom ordering, symmetry classes and pair-shell assignments. A hash of
caller-supplied numbers is NOT proof that a QE job ran. ``expected_sample_sha256``
must be produced by that independent audit, not copied from an evidence claim.

Each sample is a mapping with forces_ry_bohr and displacements_bohr (N by 3),
atom_order (N mappings with atom_id, species, site_id; indices are zero based),
settings (electronic settings only, or identical amplitude fields within a set),
accepted_unitcell_sha256, supercell_sha256, dataset_sha256, input_sha256,
output_sha256, raw_audit_backend_sha256 and independent_run_id. Mixed samples also
have pair_shell_id, assigned by the caller's geometry/shell audit. All samples
must have the same accepted cell, supercell and atom order. Different amplitudes
may originate in different hashed displacement datasets.
For a separately enumerated production target, every sample must additionally
carry target_preflight_yaml_sha256 from the independent original-file auditor.
That auditor must verify accepted cell, atom/site order, supercell and pair
cutoff against the full target and signed dataset's parent, not trust a label.
The original subset dataset_sha256 is retained. This pure numerical API cannot
establish file provenance; production consumers must replay pilot_evidence.

record contains schema_version=1, accepted_unitcell_sha256,
selected_settings_sha256, preflight_yaml_sha256, audit_backend_sha256, samples
(IDs mapped to manifest_path/sha256 and result_path/sha256), force_comparisons,
and amplitude_probes. Top-level audit_backend_sha256 binds this numerical
analysis module, and must be checked against pilot_analysis.py by the caller;
this pure function transparently preserves that externally validated binding.
The distinct raw_audit_backend_sha256 identifies the original-file auditor and
must agree across every sample; it need not equal the numerical module hash.
A comparison names candidate/reference,
candidate_pristine/reference_pristine and candidate_duplicate/reference_duplicate.
A probe has kind=single|mixed, and sets with h_angstrom, h_bohr, pristine,
duplicate (independent repeat of plus or pp), plus/minus or pp/pm/mp/mm.
Every sample role is checked against its actual displacement, never an ID name.
Mixed probes name pair_shell_id and currently require two distinct atoms.

Numerical convention: RMS is over all 3N Cartesian components, no mean-force
removal or fit. Corrected F = F_displaced - F_setting_matched_pristine. Duplicate
noise d=RMS(F_run-F_repeat) is conservatively used as a per-run noise envelope
(not divided by sqrt(2)). Propagation assumes independent, stationary numerical
errors of at most that envelope across sign runs and pristine runs at the same
setting. This is a diagnostic assumption, not a statistical confidence bound.
The shared pristine cancels exactly in D1/D2: numerator noises sqrt(2)*d and
2*d; derivative noises divide those by 2h and 4h^2, respectively. Corrected
force noise is sqrt(2)*d. A zero measured duplicate difference does not prove
zero uncertainty; a 1e-15 Ry/bohr numerical floor is always retained.

D1 has units Ry/bohr^2 and D2 Ry/bohr^3. Relative amplitude changes use the
larger adjacent amplitude as reference. Signal/noise >=10 is required; reference
norms below 10 times noise (or the numerical floor) yield below_resolution and
relative error null, never an artificial relative pass/fail. All required gates
must pass for selection eligibility. This does not establish full-dataset,
supercell, pair-cutoff, q-mesh or NAC convergence and authorizes no submission.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping

BOHR_TO_ANGSTROM = 0.529177210903
NOISE_FLOOR_RY_BOHR = 1e-15


class PilotError(ValueError):
    """Malformed, mismatched or incompletely audited evidence (fail closed)."""


def canonical_sha256(value):
    """Hash a JSON-compatible object; reject NaN/Infinity rather than encode them."""
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise PilotError("evidence must be finite JSON data") from exc
    return hashlib.sha256(data.encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise PilotError(message)


def _sha(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
             "missing or invalid SHA256")
    return value


def _number(value, positive=False):
    _require(type(value) in (int, float) and math.isfinite(value), "non-finite/non-numeric value")
    _require(not positive or value > 0, "expected positive value")
    return float(value)


def _vectors(value, count):
    _require(isinstance(value, list) and len(value) == count, "force/displacement atom count mismatch")
    _require(all(isinstance(row, list) and len(row) == 3 for row in value), "expected N by 3 vectors")
    return [_number(x) for row in value for x in row]


def _rms(values):
    values = list(values)
    _require(bool(values), "empty vector")
    result = math.hypot(*values) / math.sqrt(len(values))
    _require(math.isfinite(result), "numerical overflow")
    return result


def _difference(a, b):
    _require(len(a) == len(b), "vector size mismatch")
    result = [x-y for x, y in zip(a, b)]
    _require(all(math.isfinite(x) for x in result), "numerical overflow")
    return result


def _near(a, b):
    return len(a) == len(b) and all(math.isclose(x, y, rel_tol=1e-8, abs_tol=1e-10)
                                  for x, y in zip(a, b))


def _relative(candidate, reference, reference_noise, limit, minimum_snr=10.0):
    scale = _rms(reference)
    delta = _rms(_difference(candidate, reference))
    if scale <= NOISE_FLOOR_RY_BOHR or scale < minimum_snr * reference_noise:
        return {"status": "below_resolution", "relative_rms": None,
                "reference_rms": scale, "rms_difference": delta}
    value = delta / scale
    return {"status": "pass" if value <= limit else "fail", "relative_rms": value,
            "reference_rms": scale, "rms_difference": delta}


def analyze_pilot(record, audited_samples, policy, selected_settings,
                  reference_settings, *, expected_sample_sha256):
    """Return deterministic, provenance-bound evidence; invalid evidence raises.

    Numerical failures return pass=False with per-gate statuses. Missing fields,
    incorrect role mappings, hashes, units, settings or geometry raise PilotError.
    ``policy`` is the campaign's force_and_amplitude_validation object. Required
    symmetry classes are the complete site_id set in the audited atom order;
    required species and pair-shell IDs come from policy.amplitude_pilot.
    The caller must not reduce those classes before calling this function.
    """
    try:
        return _analyze(record, audited_samples, policy, selected_settings,
                        reference_settings, expected_sample_sha256)
    except PilotError:
        raise
    except (KeyError, TypeError, IndexError, ValueError, OverflowError) as exc:
        raise PilotError(f"incomplete or invalid pilot evidence: {exc}") from exc


def _analyze(record, samples, policy, selected, reference, expected):
    canonical_sha256(record)
    _require(record["schema_version"] == 1, "unsupported evidence schema")
    _require(isinstance(samples, Mapping) and samples, "no audited samples")
    _require(set(record["samples"]) == set(samples) == set(expected), "sample IDs differ from independent audit")
    for key in ("accepted_unitcell_sha256", "selected_settings_sha256", "preflight_yaml_sha256", "audit_backend_sha256"):
        _sha(record[key])
    _require(record["selected_settings_sha256"] == canonical_sha256(selected), "selected settings hash mismatch")
    for ref in record["samples"].values():
        for stem in ("manifest", "result"):
            _require(isinstance(ref[stem+"_path"], str) and ref[stem+"_path"], "missing raw evidence path")
            _sha(ref[stem+"_sha256"])
    first = next(iter(samples.values()))
    order = first["atom_order"]
    _require(isinstance(order, list) and order, "missing audited atom order")
    for atom in order:
        for key in ("atom_id", "species", "site_id"):
            _require(isinstance(atom[key], str) and atom[key], "missing atom identity/symmetry class")
    _require(len({a["atom_id"] for a in order}) == len(order), "duplicate atom identity")
    classes = {}
    for atom in order:
        _require(classes.setdefault(atom["site_id"], atom["species"]) == atom["species"],
                 "symmetry class mixes species")
    arrays, disps = {}, {}
    for name, sample in samples.items():
        _require(canonical_sha256(sample) == _sha(expected[name]), "audited sample hash mismatch: " + name)
        for key in ("accepted_unitcell_sha256", "supercell_sha256", "dataset_sha256",
                    "input_sha256", "output_sha256", "raw_audit_backend_sha256"):
            _sha(sample[key])
        _require(sample["accepted_unitcell_sha256"] == record["accepted_unitcell_sha256"], "unitcell mismatch")
        _require(sample["raw_audit_backend_sha256"] == first["raw_audit_backend_sha256"],
                 "raw audit backend mismatch")
        _require(sample["supercell_sha256"] == first["supercell_sha256"] and sample["atom_order"] == order,
                 "supercell or atom order mismatch")
        _require(isinstance(sample["settings"], Mapping) and sample["settings"], "missing electronic settings")
        _require(isinstance(sample["independent_run_id"], str) and sample["independent_run_id"], "missing run identity")
        arrays[name] = _vectors(sample["forces_ry_bohr"], len(order))
        disps[name] = _vectors(sample["displacements_bohr"], len(order))
    target_bindings = [s.get("target_preflight_yaml_sha256") for s in samples.values()]
    if any(value is not None for value in target_bindings):
        _require(all(_sha(value) == record["preflight_yaml_sha256"] for value in target_bindings),
                 "independently audited full-target lineage differs across samples")
    else:
        _require(record["preflight_yaml_sha256"] in {s["dataset_sha256"] for s in samples.values()},
                 "selected displacement dataset absent from audit")

    def same_settings(a, b):
        _require(samples[a]["settings"] == samples[b]["settings"], "setting-matched pristine/duplicate required")

    def corrected(name, pristine):
        same_settings(name, pristine)
        _require(all(x == 0 for x in disps[pristine]), "pristine role has nonzero displacement")
        return _difference(arrays[name], arrays[pristine])

    def duplicate_noise(name, duplicate):
        same_settings(name, duplicate)
        _require(name != duplicate and samples[name]["independent_run_id"] != samples[duplicate]["independent_run_id"],
                 "duplicate must be an independent run")
        _require(samples[name]["input_sha256"] == samples[duplicate]["input_sha256"] and
                 samples[name]["dataset_sha256"] == samples[duplicate]["dataset_sha256"] and
                 disps[name] == disps[duplicate], "duplicate geometry/input mismatch")
        return _rms(_difference(arrays[name], arrays[duplicate]))

    amp = policy["amplitude_pilot"]
    limits = policy["force_difference_acceptance"]
    acceptance = amp["acceptance"]
    _require(policy["subtract_setting_matched_pristine_force_before_comparison"] is True,
             "matched pristine subtraction must be mandatory")
    for values, keys in ((limits, ("maximum_component_difference_Ry_per_bohr", "RMS_component_difference_Ry_per_bohr",
                                  "relative_RMS_difference", "maximum_duplicate_RMS_force_difference_Ry_per_bohr")),
                         (acceptance, ("minimum_induced_force_signal_to_duplicate_noise",
                                       "minimum_mixed_difference_numerator_signal_to_propagated_duplicate_noise",
                                       "maximum_relative_change_of_central_force_slope",
                                       "maximum_relative_change_of_mixed_second_force_derivative",
                                       "maximum_duplicate_RMS_force_difference_Ry_per_bohr"))):
        for key in keys:
            _number(values[key], positive=True)
    d1_snr = max(10.0, acceptance["minimum_induced_force_signal_to_duplicate_noise"])
    d2_snr = max(10.0, acceptance["minimum_mixed_difference_numerator_signal_to_propagated_duplicate_noise"])
    pilot = policy["basis_and_scf_pilot"]
    ref_cutoffs = [v for v in pilot["ecut_candidates_Ry"] if v.get("reference") is True]
    ref_meshes = [v["mesh"] for v in pilot["k_point_candidates"] if v.get("role") == "reference"]
    _require(len(ref_cutoffs) == len(ref_meshes) == 1, "unique conservative reference required")
    for key, value in {**{k: ref_cutoffs[0][k] for k in ("ecutwfc_Ry", "ecutrho_Ry")},
                       "kmesh": ref_meshes[0], "conv_thr_Ry": min(pilot["conv_thr_candidates_Ry"])}.items():
        _require(reference[key] == value, "reference differs from declared conservative setting")
    variable_keys = {"ecutwfc_Ry", "ecutrho_Ry", "kmesh", "conv_thr_Ry"}
    _require({k: v for k, v in selected.items() if k not in variable_keys} ==
             {k: v for k, v in reference.items() if k not in variable_keys},
             "reference changes physics/geometry outside electronic convergence settings")
    _require(any(selected["ecutwfc_Ry"] == v["ecutwfc_Ry"] and selected["ecutrho_Ry"] == v["ecutrho_Ry"]
                 for v in pilot["ecut_candidates_Ry"]) and
             selected["kmesh"] in [v["mesh"] for v in pilot["k_point_candidates"]] and
             selected["conv_thr_Ry"] in pilot["conv_thr_candidates_Ry"],
             "selected electronic setting is outside configured pilot candidates")

    comparisons = record["force_comparisons"]
    _require(isinstance(comparisons, list) and comparisons, "force comparisons required")
    force_results, force_sites = [], set()
    for item in comparisons:
        c, r, cp, rp, cd, rd = [item[k] for k in ("candidate", "reference", "candidate_pristine",
                                                "reference_pristine", "candidate_duplicate", "reference_duplicate")]
        _require(samples[c]["settings"] == selected and samples[r]["settings"] == reference,
                 "force comparison setting roles mismatch")
        _require(disps[c] == disps[r] and any(x != 0 for x in disps[c]), "force comparison displacement mismatch")
        cf, rf = corrected(c, cp), corrected(r, rp)
        cn, rn = duplicate_noise(c, cd), duplicate_noise(r, rd)
        diff = _difference(cf, rf)
        result = _relative(cf, rf, math.sqrt(2)*max(rn, NOISE_FLOOR_RY_BOHR), limits["relative_RMS_difference"])
        result.update(candidate=c, reference=r, corrected_candidate_ry_bohr=cf,
                      corrected_reference_ry_bohr=rf, max_abs_difference_ry_bohr=max(map(abs, diff)),
                      rms_difference_ry_bohr=_rms(diff), candidate_duplicate_rms_ry_bohr=cn,
                      reference_duplicate_rms_ry_bohr=rn)
        result["absolute_pass"] = (result["max_abs_difference_ry_bohr"] <= limits["maximum_component_difference_Ry_per_bohr"]
                                   and result["rms_difference_ry_bohr"] <= limits["RMS_component_difference_Ry_per_bohr"])
        result["noise_pass"] = max(cn, rn) <= limits["maximum_duplicate_RMS_force_difference_Ry_per_bohr"]
        result["pass"] = result["status"] == "pass" and result["absolute_pass"] and result["noise_pass"]
        force_results.append(result)
        force_sites.update(order[i]["site_id"] for i in range(len(order)) if any(disps[c][3*i:3*i+3]))

    amplitudes = sorted(amp["displacement_distance_candidates"], key=lambda v: v["displacement_distance_angstrom"])
    _require(len(amplitudes) == 3 and all(math.isclose(v["displacement_distance_angstrom"], h, abs_tol=1e-12)
                                        for v, h in zip(amplitudes, (0.02, 0.03, 0.04))), "required 0.02/0.03/0.04 Angstrom ladder missing")
    for value in amplitudes:
        _require(math.isclose(value["displacement_distance_cli_bohr"] * BOHR_TO_ANGSTROM,
                             value["displacement_distance_angstrom"], rel_tol=1e-8), "policy amplitude unit mismatch")
    probes = record["amplitude_probes"]
    _require(isinstance(probes, list) and probes, "amplitude probes required")
    amp_results, single_sites, pair_shells = [], set(), set()
    for probe in probes:
        kind = probe["kind"]
        _require(kind in ("single", "mixed"), "unknown amplitude probe kind")
        groups = sorted(probe["sets"], key=lambda v: v["h_angstrom"])
        _require(len(groups) == 3, "every amplitude required")
        derivative_results, identity = [], None
        for group, configured in zip(groups, amplitudes):
            h = _number(group["h_bohr"], positive=True)
            _require(math.isclose(_number(group["h_angstrom"], positive=True), configured["displacement_distance_angstrom"], abs_tol=1e-12)
                     and math.isclose(h * BOHR_TO_ANGSTROM, group["h_angstrom"], rel_tol=1e-8), "amplitude unit/ladder mismatch")
            roles = ("plus", "minus") if kind == "single" else ("pp", "pm", "mp", "mm")
            names = [group[k] for k in roles]
            _require(len(set(names)) == len(names), "sign roles reuse one sample")
            for name in names:
                actual = {k: v for k, v in samples[name]["settings"].items() if k not in ("amplitude_angstrom", "amplitude_bohr")}
                wanted = {k: v for k, v in selected.items() if k not in ("amplitude_angstrom", "amplitude_bohr")}
                _require(actual == wanted, "amplitude probe changed electronic settings")
                for key, value in (("amplitude_angstrom", group["h_angstrom"]), ("amplitude_bohr", h)):
                    if key in samples[name]["settings"]:
                        _require(math.isclose(samples[name]["settings"][key], value, rel_tol=1e-8), "sample amplitude metadata mismatch")
            forces = [corrected(name, group["pristine"]) for name in names]
            d = [disps[name] for name in names]
            if kind == "single":
                components = [d[0]]
                _require(_near(d[1], [-v for v in d[0]]), "single sign geometry mismatch")
            else:
                a = [(x-y)/2 for x, y in zip(d[0], d[2])]
                b = [(x-y)/2 for x, y in zip(d[0], d[1])]
                components = [a, b]
                for actual, (s, t) in zip(d, ((1, 1), (1, -1), (-1, 1), (-1, -1))):
                    _require(_near(actual, [s*x+t*y for x, y in zip(a, b)]), "mixed four-sign geometry mismatch")
                for name in names:
                    _require(samples[name]["pair_shell_id"] == probe["pair_shell_id"], "audited pair shell mismatch")
            atoms = []
            directions = []
            for component in components:
                moved = [i for i in range(len(order)) if math.hypot(*component[3*i:3*i+3]) > 1e-10]
                _require(len(moved) == 1 and math.isclose(math.hypot(*component[3*moved[0]:3*moved[0]+3]), h, rel_tol=1e-8),
                         "probe component must move one atom by h bohr")
                atoms.extend(moved)
                directions.extend(x/h for x in component)
            _require(kind != "mixed" or atoms[0] != atoms[1], "mixed probes currently require distinct atoms")
            if identity is not None:
                _require(identity[0] == atoms and _near(identity[1], directions), "amplitude ladder changes atoms/directions")
            identity = (atoms, directions)
            noise = duplicate_noise(names[0], group["duplicate"])
            signs = (1, -1) if kind == "single" else (1, -1, -1, 1)
            numerator = [math.fsum(s*f[i] for s, f in zip(signs, forces)) for i in range(3*len(order))]
            propagated = math.sqrt(len(signs))*max(noise, NOISE_FLOOR_RY_BOHR)
            denominator = 2*h if kind == "single" else 4*h*h
            derivative = [x/denominator for x in numerator]
            minimum = d1_snr if kind == "single" else d2_snr
            signal = _rms(numerator)
            resolved = signal > NOISE_FLOOR_RY_BOHR and signal >= minimum*propagated
            derivative_results.append({"h_angstrom": group["h_angstrom"], "h_bohr": h,
                                       "role_sample_ids": dict(zip(roles, names)),
                                       "derivative": derivative, "unit": "Ry/bohr^2" if kind == "single" else "Ry/bohr^3",
                                       "numerator_rms_ry_bohr": signal, "duplicate_rms_ry_bohr": noise,
                                       "propagated_numerator_noise_ry_bohr": propagated,
                                       "derivative_noise": propagated/denominator,
                                       "signal_to_noise": signal/propagated,
                                       "signal_status": "pass" if resolved else "below_resolution",
                                       "noise_pass": noise <= acceptance["maximum_duplicate_RMS_force_difference_Ry_per_bohr"]})
        threshold = acceptance["maximum_relative_change_of_central_force_slope" if kind == "single" else
                               "maximum_relative_change_of_mixed_second_force_derivative"]
        changes = []
        for low, high in zip(derivative_results, derivative_results[1:]):
            change = _relative(low["derivative"], high["derivative"], high["derivative_noise"], threshold,
                               d1_snr if kind == "single" else d2_snr)
            if low["signal_status"] != "pass" or high["signal_status"] != "pass":
                change.update(status="below_resolution", relative_rms=None)
            changes.append(change)
        passed = all(x["signal_status"] == "pass" and x["noise_pass"] for x in derivative_results) and all(x["status"] == "pass" for x in changes)
        amp_results.append({"kind": kind, "sets": derivative_results, "adjacent_changes": changes, "pass": passed})
        if kind == "single":
            single_sites.add(order[identity[0][0]]["site_id"])
        else:
            pair_shells.add(probe["pair_shell_id"])

    required_species = set(amp["representative_species"])
    required_pairs = set(amp["representative_pair_shells"])
    _require(required_species and required_pairs, "required coverage cannot be empty")
    _require(required_species == {atom["species"] for atom in order}, "policy species differs from audited structure")
    coverage = {"required_site_ids": sorted(classes), "single_site_ids": sorted(single_sites),
                "force_comparison_site_ids": sorted(force_sites), "required_pair_shells": sorted(required_pairs),
                "covered_pair_shells": sorted(pair_shells)}
    coverage["force_accuracy_pass"] = set(classes) <= force_sites
    coverage["amplitude_pass"] = set(classes) <= single_sites and required_pairs <= pair_shells
    force_pass = all(x["pass"] for x in force_results) and coverage["force_accuracy_pass"]
    amplitude_pass = all(x["pass"] for x in amp_results) and coverage["amplitude_pass"]
    result = {k: copy.deepcopy(record[k]) for k in ("schema_version", "accepted_unitcell_sha256", "selected_settings_sha256",
                                                   "preflight_yaml_sha256", "audit_backend_sha256", "samples")}
    result.update(pass_=force_pass and amplitude_pass)
    result["pass"] = result.pop("pass_")
    result.update(force_accuracy_pass=force_pass, amplitude_pass=amplitude_pass,
                  force_comparisons=force_results, amplitude_probes=amp_results, coverage=coverage,
                  sample_sha256=dict(expected), input_record_sha256=canonical_sha256(record),
                  input_record=copy.deepcopy(record),
                  policy_sha256=canonical_sha256(policy), reference_settings_sha256=canonical_sha256(reference),
                  supercell_sha256=first["supercell_sha256"], atom_order_sha256=canonical_sha256(order),
                  raw_audit_backend_sha256=first["raw_audit_backend_sha256"],
                  source_hashes={name: {k: v for k, v in sample.items() if k.endswith("_sha256")}
                                 for name, sample in samples.items()},
                  scope="representative force/amplitude pilots only; no full-dataset, supercell, pair-cutoff, q-mesh or NAC convergence claim",
                  noise_model="duplicate RMS difference as per-run envelope; independent stationary errors assumed; common pristine cancels in derivatives")
    result["analysis_sha256"] = canonical_sha256(result)
    return result

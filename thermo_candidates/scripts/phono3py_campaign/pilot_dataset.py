"""Prepare explicit signed pilot geometries, without executing QE or phono3py.

API: prepare_pilot_dataset(config_path, run_dir, *, candidate_dir,
preflight_inventory, output_dir, probe_spec). The accepted relax evidence is
resolved through run_dir/relax/final and verified by force_backend._provenance.
audit_pilot_dataset(dataset_dir, *, expected_manifest_sha256) rechecks the bundle.

probe_spec = {schema_version: 1, rationale: str, supercell_id: str, cutoff_id:
str, amplitude_angstrom: 0.02|0.03|0.04, amplitude_bohr: float,
singles: [{id: str, atom: 1-based index, direction_cartesian: unit vector}],
mixed: [{id: str, first: {atom, direction_cartesian}, second: {...},
pair_shell_id: configured species-pair label}], coverage: {site_ids:
{site-00001: covered|not_covered, ...}, pair_shell_ids: {...}}}.

Site IDs come from strict spglib equivalent_atoms on the accepted unit cell,
then explicit periodic mapping to its supercell. "covered" records geometrical
sampling only; no force/noise, amplitude, radial-shell completeness or scientific
convergence is inferred. Singles added solely as parents of mixed displacements
do not count toward declared single-site coverage. One amplitude per bundle.

The v4.4.0 type-I YAML parser supports this signed subset: first IDs must be
1..nfirst, then paired IDs in grouped traversal order. This contract was checked
against https://github.com/phonopy/phono3py/blob/v4.4.0/phono3py/interface/phono3py_yaml.py
(_parse_fc3_dataset_type1 and _parse_fc3_dataset_type1_without_forces).
No phono3py runtime compatibility or FC3 completeness claim is made. Other
versions/type-II/phonon datasets fail closed pending a separately audited adapter.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path

import campaign as core
import force_backend as fb
from qe_input import parse_qe_input

PilotDatasetError = core.CampaignError
TOL_BOHR = 2e-8


def _require(condition, message):
    if not condition:
        raise PilotDatasetError(message)


def _cart(fractional, cell):
    return [sum(fractional[i] * cell[i][j] for i in range(3)) for j in range(3)]


def minimum_image_bohr(delta_fractional, cell_bohr):
    """Exact bounded lattice-image search, including strongly tilted cells.

    For incumbent Cartesian radius R, |fractional[j]| <= R*|inv(A)[:,j]|.
    These bounds include every improving image; rounding fractional coordinates
    alone, or a fixed 27-image search, is insufficient for arbitrary skew cells.
    Ill-conditioned cases with >2 million images fail closed (no approximation).
    """
    cell = [fb._vector(row) for row in cell_bohr]
    _require(len(cell) == 3, "cell must be 3x3")
    inverse = fb._inverse(cell)
    delta = [x-round(x) for x in fb._vector(delta_fractional)]
    best = _cart(delta, cell)
    radius = math.hypot(*best)
    bounds = [radius * math.hypot(*(inverse[i][j] for i in range(3))) + 1e-10
              for j in range(3)]
    ranges = [range(math.ceil(delta[j]-bounds[j]), math.floor(delta[j]+bounds[j])+1)
              for j in range(3)]
    _require(math.prod(map(len, ranges)) <= 2_000_000,
             "minimum-image search too large; require an audited reduced-cell adapter")
    for image in itertools.product(*ranges):
        vector = _cart([d-n for d, n in zip(delta, image)], cell)
        if math.hypot(*vector) < math.hypot(*best):
            best = vector
    return best


def _near(a, b, tolerance=TOL_BOHR):
    return len(a) == len(b) and all(abs(x-y) <= tolerance for x, y in zip(a, b))


def _type1_inventory(data):
    """Enforce the real v4.4.0 reader's ID order, not just set equality."""
    inventory = core.analyze_displacement_yaml(data)
    pairs = data["displacement_pairs"]
    second_id = len(pairs)+1
    for first_id, first in enumerate(pairs, 1):
        _require(type(first["displacement_id"]) is int and first["displacement_id"] == first_id,
                 "type-I first IDs must be integer 1..nfirst in parser order")
        for second in first["paired_with"]:
            for value in second["displacement_ids"]:
                _require(type(value) is int and value == second_id,
                         "type-I paired IDs must follow numeric grouped parser order")
                second_id += 1
    return inventory


def site_inventory(base, accepted_text, config):
    """Derive strict unit-cell symmetry classes and audit every supercell atom."""
    try:
        import spglib
    except ImportError as exc:
        raise PilotDatasetError("spglib is required; site classes cannot be guessed") from exc
    accepted = parse_qe_input(accepted_text)
    _require(base.get("physical_unit", {}).get("length") == "au", "base YAML length must be au")
    unit = base.get("unit_cell")
    _require(isinstance(unit, dict), "base YAML must contain its hashed unit_cell")
    unit_cell = [[x/core.BOHR_TO_ANGSTROM for x in row] for row in accepted.cell_parameters]
    _require(len(unit["lattice"]) == 3 and all(_near(a, b) for a, b in zip(unit["lattice"], unit_cell)),
             "base YAML unit_cell differs from accepted cell in bohr")
    unit_points = unit["points"]
    _require(len(unit_points) == accepted.nat, "YAML unit-cell atom count mismatch")
    for point, atom in zip(unit_points, accepted.atomic_positions):
        _require(point["symbol"] == atom.label and math.hypot(*minimum_image_bohr(
            [x-y for x, y in zip(point["coordinates"], atom.coordinates)], unit_cell)) <= TOL_BOHR,
            "YAML unit-cell atom order/geometry differs from accepted relax")
    policy = config["symmetry_validation"]
    tolerance = policy.get("post_standardization_strictest_required_matching_symprec_angstrom",
                           policy.get("strictest_required_matching_symprec_angstrom"))
    tolerance = core.positive_number(tolerance, "strict symmetry tolerance angstrom")
    labels = [a.label for a in accepted.atomic_positions]
    numbers = {name: i+1 for i, name in enumerate(dict.fromkeys(labels))}
    symmetry = spglib.get_symmetry_dataset((accepted.cell_parameters,
        [a.coordinates for a in accepted.atomic_positions], [numbers[x] for x in labels]), symprec=tolerance)
    _require(symmetry is not None, "strict spglib symmetry failed")
    _require(int(symmetry.number) == config["material"]["expected_spacegroup_number"],
             "strict symmetry no longer matches accepted material")
    equivalent = [int(x) for x in symmetry.equivalent_atoms]
    _require(len(equivalent) == accepted.nat and all(0 <= x < accepted.nat for x in equivalent),
             "invalid spglib equivalent_atoms")
    _require(all(equivalent[x] == x and labels[i] == labels[x] for i, x in enumerate(equivalent)),
             "inconsistent spglib site equivalence")
    matrix = core.matrix3(base["supercell_matrix"], "supercell matrix")
    cell = [fb._vector(row) for row in base["supercell"]["lattice"]]
    expected = [[sum(matrix[k][i]*unit_cell[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    _require(len(cell) == 3 and all(_near(a, b) for a, b in zip(cell, expected)),
             "supercell violates M transpose times accepted cell")
    inverse = fb._inverse(unit_cell)
    points = base["supercell"]["points"]
    multiplicity = abs(round(core.determinant(matrix)))
    _require(len(points) == multiplicity*accepted.nat, "supercell atom count/determinant mismatch")
    counts, order = [0]*accepted.nat, []
    for index, point in enumerate(points):
        position = _cart(_cart(fb._vector(point["coordinates"]), cell), inverse)
        matches = [i for i, atom in enumerate(accepted.atomic_positions) if point["symbol"] == atom.label
                   and math.hypot(*minimum_image_bohr([x-y for x, y in zip(position, atom.coordinates)], unit_cell)) <= TOL_BOHR]
        _require(len(matches) == 1, "supercell atom has ambiguous/missing accepted-unitcell mapping")
        parent = matches[0]
        counts[parent] += 1
        order.append({"atom_id": str(index), "atom_1_based": index+1, "species": point["symbol"],
                      "site_id": f"site-{equivalent[parent]+1:05d}", "unitcell_atom_1_based": parent+1})
        for previous in points[:index]:
            _require(math.hypot(*minimum_image_bohr([x-y for x,y in zip(point["coordinates"], previous["coordinates"])], cell)) > TOL_BOHR,
                     "duplicate periodic supercell atom")
    _require(counts == [multiplicity]*accepted.nat, "supercell mapping multiplicities differ")
    return {"atom_order": order, "equivalent_atoms_0_based": equivalent,
            "site_ids": sorted({x["site_id"] for x in order}), "symprec_angstrom": tolerance,
            "symprec_bohr": tolerance/core.BOHR_TO_ANGSTROM, "spglib_version": str(spglib.__version__),
            "spacegroup_number": int(symmetry.number)}


def build_pilot_geometry(base, accepted_text, config, probe_spec):
    """Pure geometry preparation; requires spglib, never starts an executable."""
    spec = copy.deepcopy(probe_spec)
    _require(type(spec.get("schema_version")) is int and spec["schema_version"] == 1 and isinstance(spec.get("rationale"), str)
             and spec["rationale"].strip(), "explicit versioned probe specification and rationale required")
    _require(config["software"]["phono3py_version"] == "4.4.0", "unreviewed phono3py schema version; require adapter review")
    _require(not any(key in base for key in ("phonon_supercell_matrix", "phonon_dataset", "phonon_displacements", "displacements", "nac_params")),
             "combined/type-II/NAC YAML unsupported; require a separate audited adapter")
    _type1_inventory(base)
    h = core.positive_number(spec.get("amplitude_bohr"), "amplitude_bohr")
    angstrom = core.positive_number(spec.get("amplitude_angstrom"), "amplitude_angstrom")
    _require(angstrom in (0.02, 0.03, 0.04) and math.isclose(h*core.BOHR_TO_ANGSTROM, angstrom, rel_tol=2e-10),
             "pilot amplitude must be 0.02/0.03/0.04 angstrom with matching bohr")
    candidates = config["force_and_amplitude_validation"]["amplitude_pilot"]
    _require(any(x["displacement_distance_angstrom"] == angstrom and math.isclose(x["displacement_distance_cli_bohr"], h, rel_tol=2e-10)
                 for x in candidates["displacement_distance_candidates"]), "amplitude absent from configured candidates")
    matrices = {x["id"]: x for x in config["displacements"]["supercell_candidates"]}
    cutoffs = {x["id"]: x for x in config["displacements"]["cutoff_candidates"]}
    _require(spec.get("supercell_id") in matrices and spec.get("cutoff_id") in cutoffs, "configured candidate IDs required")
    matrix, cutoff = matrices[spec["supercell_id"]], cutoffs[spec["cutoff_id"]]
    _require(matrix["matrix"] == base["supercell_matrix"] and not matrix.get("production_fc3_eligible_without_new_review") is False,
             "base matrix mismatch or count-only escalation")
    distance = core.positive_number(cutoff["cutoff_pair_distance_cli_bohr"], "pair cutoff bohr")
    _require(math.isclose(distance*core.BOHR_TO_ANGSTROM, cutoff["cutoff_pair_distance_angstrom"], rel_tol=2e-10), "cutoff unit mismatch")
    _require(math.isclose(base["displacement_pair_info"]["cutoff_pair_distance"], distance, rel_tol=2e-8), "base cutoff differs from selected cutoff")
    symmetry = site_inventory(base, accepted_text, config)
    points = base["supercell"]["points"]
    cell = base["supercell"]["lattice"]
    _require(len(points) == matrix["atoms"], "configured supercell atom count mismatch")
    singles, mixed = spec.get("singles"), spec.get("mixed")
    _require(isinstance(singles, list) and isinstance(mixed, list) and singles and mixed,
             "explicit nonempty single and mixed probe lists required")
    ids = [p.get("id") for p in singles+mixed]
    _require(all(isinstance(x, str) and x.strip() for x in ids) and len(set(ids)) == len(ids), "unique probe IDs required")
    firsts, geometries, roles, selected_sites, selected_shells = {}, {}, [], set(), set()

    def component(value, sign):
        atom = value["atom"]
        _require(type(atom) is int and 1 <= atom <= len(points), "probe atom must be a valid 1-based integer")
        vector = fb._vector(value["direction_cartesian"])
        _require(math.isclose(math.hypot(*vector), 1, rel_tol=1e-10), "explicit Cartesian direction must be a unit vector")
        return atom, tuple(0.0 if x == 0 else sign*h*x for x in vector)

    def register(components):
        key = tuple(sorted(components))
        geometries.setdefault(key, None)
        return key

    for probe in singles:
        keys = {role: register([component(probe, sign)]) for role, sign in (("plus", 1), ("minus", -1))}
        for key in keys.values():
            firsts.setdefault(key, [])
        selected_sites.add(symmetry["atom_order"][probe["atom"]-1]["site_id"])
        roles.append({"probe_id": probe["id"], "kind": "single", "geometry_keys": keys})
    for probe in mixed:
        a, b = probe["first"]["atom"], probe["second"]["atom"]
        component(probe["first"], 1); component(probe["second"], 1)
        _require(a != b, "mixed probes require two different atoms")
        pair_distance = math.hypot(*minimum_image_bohr([x-y for x,y in zip(points[a-1]["coordinates"], points[b-1]["coordinates"])], cell))
        _require(TOL_BOHR < pair_distance <= distance+TOL_BOHR, "pair lies outside selected cutoff or has zero distance")
        shell = probe["pair_shell_id"]
        _require(shell in candidates["representative_pair_shells"] and sorted(shell.split("-")) == sorted([points[a-1]["symbol"], points[b-1]["symbol"]]),
                 "pair shell label must match configured species pair")
        selected_shells.add(shell)
        keys = {}
        for role, s, t in (("pp",1,1), ("pm",1,-1), ("mp",-1,1), ("mm",-1,-1)):
            left, right = component(probe["first"], s), component(probe["second"], t)
            parent = register([left])
            firsts.setdefault(parent, [])
            key = register([left, right])
            # Reversed probes reuse the original geometry and its original parent.
            if not any(key == item[0] for group in firsts.values() for item in group):
                firsts[parent].append((key, right, pair_distance))
            keys[role] = key
        roles.append({"probe_id": probe["id"], "kind": "mixed", "pair_shell_id": shell,
                      "pair_distance_bohr": pair_distance, "pair_distance_angstrom": pair_distance*core.BOHR_TO_ANGSTROM,
                      "geometry_keys": keys})
    coverage = spec.get("coverage", {})
    for key, required, selected in (("site_ids", symmetry["site_ids"], selected_sites),
                                    ("pair_shell_ids", candidates["representative_pair_shells"], selected_shells)):
        actual = {x: "covered" if x in selected else "not_covered" for x in required}
        _require(coverage.get(key) == actual, f"explicit {key} coverage must enumerate all classes and match probes: {actual}")
    dataset = {key: copy.deepcopy(base[key]) for key in ("physical_unit", "unit_cell", "supercell", "supercell_matrix")}
    if "primitive_matrix" in base:
        dataset["primitive_matrix"] = copy.deepcopy(base["primitive_matrix"])
    dataset["phono3py"] = {"version": "4.4.0", "calculator": "qe"}
    dataset["displacement_pairs"] = []
    next_id = len(firsts)+1
    for index, (key, seconds) in enumerate(firsts.items(), 1):
        geometries[key] = index
        atom, vector = key[0]
        first = {"atom": atom, "displacement_id": index, "displacement": list(vector), "paired_with": []}
        for pair_key, (second_atom, second_vector), pair_distance in seconds:
            geometries[pair_key] = next_id
            first["paired_with"].append({"atom": second_atom, "pair_distance": pair_distance, "included": True,
                                        "displacement_ids": [next_id], "displacements": [list(second_vector)]})
            next_id += 1
        dataset["displacement_pairs"].append(first)
    dataset["displacement_pair_info"] = {"cutoff_pair_distance": distance,
        "number_of_singles": len(firsts), "number_of_pairs": next_id-1-len(firsts)}
    _type1_inventory(dataset)
    _require(next_id-1 <= config["displacements"]["hard_cap"], "pilot exceeds displacement hard cap")
    for role in roles:
        role["displacement_ids"] = {name: geometries[key] for name,key in role.pop("geometry_keys").items()}
    offsets = {0: []}
    for key, index in geometries.items():
        _require(type(index) is int, "unmapped pilot geometry")
        offsets[index] = [(atom, list(vector)) for atom, vector in key]
    uses = {str(index): [] for index in sorted(offsets)}
    uses["0"] = ["pristine"]
    for role in roles:
        for sign, index in role["displacement_ids"].items():
            uses[str(index)].append({"probe_id": role["probe_id"], "kind": role["kind"], "sign": sign})
    return dataset, {"probes": roles, "roles_by_displacement_id": uses,
                     "reused_geometry_ids": [int(i) for i,v in uses.items() if len(v)>1],
                     "symmetry": symmetry, "coverage": coverage, "scientific_coverage_established": False}, offsets


def _settings(config, spec, base=False):
    tight = config["tight_relax"]
    return fb._settings(config, "pilot", {**spec,
        "amplitude_angstrom": config["displacements"]["amplitude_angstrom"] if base else spec["amplitude_angstrom"],
        "amplitude_bohr": config["displacements"]["amplitude_bohr"] if base else spec["amplitude_bohr"],
        "ecutwfc_Ry": tight["ecutwfc_ry"], "ecutrho_Ry": tight["ecutrho_ry"],
        "conv_thr_Ry": tight["conv_thr_ry"], "kmesh": tight["kmesh"], "kshift": tight["kmesh_shift"]})


def _fragment_text(data, accepted_text, offsets):
    source = parse_qe_input(accepted_text)
    cell = data["supercell"]["lattice"]
    inverse = fb._inverse(cell)
    positions = [fb._vector(p["coordinates"]) for p in data["supercell"]["points"]]
    for atom, vector in offsets:
        positions[atom-1] = [x+y for x,y in zip(positions[atom-1], _cart(vector, inverse))]
    return (f"! ibrav = 0, nat = {len(positions)}, ntyp = {len(source.atomic_species)}\nCELL_PARAMETERS bohr\n"
        + "".join(" ".join(f"{x:.17g}" for x in row)+"\n" for row in cell)
        + "ATOMIC_SPECIES\n" + "".join(f"{s.label} {s.mass_amu:.17g} {s.pseudopotential}\n" for s in source.atomic_species)
        + "ATOMIC_POSITIONS crystal\n" + "".join(p["symbol"]+" "+" ".join(f"{x%1:.17g}" for x in row)+"\n"
                                               for p,row in zip(data["supercell"]["points"], positions)))


def _audit_geometry(folder, config, spec, data, offsets):
    texts, inventory = fb._dataset_inputs(folder, _settings(config, spec), folder, config)
    _require(inventory["included_displacement_ids"] == list(range(1,len(offsets))), "pilot IDs must be complete numeric 1..N")
    pristine = parse_qe_input(texts[0])
    cell = data["supercell"]["lattice"]
    for index, text in texts.items():
        parsed = parse_qe_input(text)
        expected = dict(offsets[index])
        for atom_id, (atom, origin) in enumerate(zip(parsed.atomic_positions, pristine.atomic_positions), 1):
            actual = minimum_image_bohr([x-y for x,y in zip(atom.coordinates, origin.coordinates)], cell)
            _require(atom.label == origin.label and _near(actual, expected.get(atom_id, [0,0,0])),
                     f"minimum-image displacement/sign/amplitude mismatch for ID {index}, atom {atom_id}")
    return inventory


def prepare_pilot_dataset(config_path, run_dir, *, candidate_dir, preflight_inventory, output_dir, probe_spec):
    """Write a new immutable preparation bundle. No force/resource authorization."""
    config_path = Path(config_path).resolve()
    config, _ = core.validate_config(config_path)
    run_dir = core.safe_run_dir(Path(run_dir))
    candidate = fb._under(Path(candidate_dir), run_dir)
    parent_inventory = fb._under(Path(preflight_inventory), run_dir)
    destination = fb._under(Path(output_dir), run_dir)
    _require(not destination.exists(), "pilot destination exists; use a new immutable directory")
    provenance, _ = fb._provenance(config, config_path, run_dir, parent_inventory, candidate)
    parent = core.load_json(parent_inventory)
    _require(parent.get("preflight_complete") is True, "base preflight is not complete")
    result = core.load_json(candidate / "preflight_result.json")
    _require(result["supercell_id"] == probe_spec["supercell_id"] and result["cutoff_id"] == probe_spec["cutoff_id"],
             "explicit probe candidate differs from parent preflight")
    base = fb._yaml(candidate / "phono3py_disp.yaml")
    _, base_ids = fb._dataset_inputs(candidate, _settings(config, probe_spec, base=True), candidate, config)
    _require(base_ids["included_displacement_ids"] == result["generated_displacement_ids"], "base inventory IDs mismatch")
    for path in candidate.glob("supercell*.in"):
        provenance[str(path)] = core.sha256_path(path)
    accepted_text = (candidate / "unitcell.in").read_text()
    data, plan, offsets = build_pilot_geometry(base, accepted_text, config, probe_spec)
    # All validation above is read-only; claim exactly one new directory here.
    destination.mkdir(parents=True, exist_ok=False)
    core.write_immutable(destination / "unitcell.in", accepted_text)
    core.write_json_immutable(destination / "phono3py_disp.yaml", data)  # JSON is valid YAML.
    for index, displacement in sorted(offsets.items()):
        name = "supercell.in" if index == 0 else f"supercell-{index:05d}.in"
        core.write_immutable(destination / name, _fragment_text(data, accepted_text, displacement))
    audited = _audit_geometry(destination, config, probe_spec, data, offsets)
    derived = {"supercell_id": probe_spec["supercell_id"], "cutoff_id": probe_spec["cutoff_id"],
        "generated_atoms": len(data["supercell"]["points"]), "generated_displacement_ids": audited["included_displacement_ids"],
        "generated_displacement_supercells": len(offsets)-1, "within_hard_cap": True, "count_only": False,
        "yaml_length_unit": "au", "yaml_sha256": core.sha256_path(destination / "phono3py_disp.yaml"),
        "unitcell_sha256": core.sha256_path(destination / "unitcell.in"), "selection_eligible": False,
        "pilot_only": True, "derivation": "explicit signed subset; not a new phono3py enumeration",
        "parent_inventory_sha256": core.sha256_path(parent_inventory), "parent_yaml_sha256": result["yaml_sha256"],
        "amplitude_angstrom": probe_spec["amplitude_angstrom"], "amplitude_bohr": probe_spec["amplitude_bohr"],
        "cutoff_pair_distance_cli_bohr": data["displacement_pair_info"]["cutoff_pair_distance"],
        "scientific_coverage_established": False}
    core.write_json_immutable(destination / "preflight_result.json", derived)
    inventory = {"stage": "pilot_geometry_preparation", "material": config["material"]["formula"],
        "preflight_policy_sha256": parent["preflight_policy_sha256"],
        "accepted_unitcell_sha256": parent["accepted_unitcell_sha256"],
        "accepted_relax_provenance_sha256": parent["accepted_relax_provenance_sha256"],
        "parent_inventory_sha256": core.sha256_path(parent_inventory), "preflight_complete": True,
        "production_selection_still_required": True, "results": [derived]}
    core.write_json_immutable(destination / "preflight_inventory.json", inventory)
    core.write_json_immutable(destination / "config.snapshot.json", config)
    core.write_json_immutable(destination / "probe_spec.json", probe_spec)
    for path, digest in provenance.items():
        fb._match(Path(path), digest)
    manifest = {"schema_version": 1, "stage": "pilot_geometry_preparation", "pilot_only": True,
        "run_dir": str(run_dir), "candidate_dir": str(candidate), "config_sha256": core.sha256_path(config_path),
        "accepted_unitcell_sha256": parent["accepted_unitcell_sha256"],
        "accepted_relax_provenance_sha256": parent["accepted_relax_provenance_sha256"],
        "parent_inventory_path": str(parent_inventory), "parent_inventory_sha256": core.sha256_path(parent_inventory),
        "source_sha256": provenance, "geometry_plan": plan,
        "files_sha256": {p.name: core.sha256_path(p) for p in destination.iterdir() if p.is_file() and not p.name.startswith(".")},
        "backend_sha256": core.sha256_path(Path(__file__)),
        "compatibility": "v4.4.0 type-I parser contract statically audited; no phono3py runtime execution",
        "limitations": ["Synthetic structure tests only; no QE forces or convergence result.",
                        "Minimal pilot subset cannot establish FC2/FC3 or kappa and is production-ineligible.",
                        "Pair shell IDs are explicit configured species-pair labels, not proven radial-shell completeness."]}
    core.write_json_immutable(destination / "pilot_dataset_manifest.json", manifest)
    digest = core.sha256_path(destination / "pilot_dataset_manifest.json")
    audit_pilot_dataset(destination, expected_manifest_sha256=digest)
    return {"healthy": True, "dataset_dir": str(destination), "manifest_sha256": digest,
            "preflight_inventory": str(destination / "preflight_inventory.json"), "geometry_plan": plan}


def audit_pilot_dataset(dataset_dir, *, expected_manifest_sha256):
    """Read-only re-audit. Obtain expected manifest SHA from a trusted receipt."""
    folder = Path(dataset_dir).resolve()
    fb._match(folder / "pilot_dataset_manifest.json", expected_manifest_sha256)
    manifest = core.load_json(folder / "pilot_dataset_manifest.json")
    fb._match(Path(__file__), manifest["backend_sha256"])
    for name, digest in manifest["files_sha256"].items():
        _require(Path(name).name == name, "manifest filename escapes bundle")
        fb._match(folder / name, digest)
    for path, digest in manifest["source_sha256"].items():
        fb._match(Path(path), digest)
    config = core.load_json(folder / "config.snapshot.json")
    spec = core.load_json(folder / "probe_spec.json")
    base = fb._yaml(Path(manifest["candidate_dir"]) / "phono3py_disp.yaml")
    data, plan, offsets = build_pilot_geometry(base, (folder / "unitcell.in").read_text(), config, spec)
    _require(data == fb._yaml(folder / "phono3py_disp.yaml") and plan == manifest["geometry_plan"],
             "regenerated geometry/site/role plan differs from manifested bundle")
    audited = _audit_geometry(folder, config, spec, data, offsets)
    result = core.load_json(folder / "preflight_result.json")
    inventory = core.load_json(folder / "preflight_inventory.json")
    _require(result in inventory["results"] and result["generated_displacement_ids"] == audited["included_displacement_ids"]
             and result["selection_eligible"] is False, "derived pilot preflight inventory mismatch")
    return {"healthy": True, "pilot_only": True, "scientific_coverage_established": False,
            "generated_displacement_ids": audited["included_displacement_ids"]}

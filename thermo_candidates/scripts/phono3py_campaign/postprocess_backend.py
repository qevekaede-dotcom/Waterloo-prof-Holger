"""Read-only evidence gates and command plans for QE/phono3py postprocessing.

No command is executed and no file is written here. The compute-node driver
must anchor supplied manifests in its immutable launch/receipt chain, copy
the exact dataset into an empty collection directory, execute the returned
argv there, hash the products, and extract HDF5 arrays for the validators.
HDF5 does not encode every solver option: the verified launch metadata is
therefore mandatory, never inferred from a filename.

Contracts follow phono3py 4.4 documentation:
https://phonopy.github.io/phono3py/qe.html
https://phonopy.github.io/phono3py/input-output-files.html
"""

from __future__ import annotations

import hashlib
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qe_input import _find_namelist, _scan_assignments, parse_qe_input
from qe_output import FORCE_HEADER, RUN_START, inspect_output, parse_last_force_block


class PostprocessError(ValueError):
    """Evidence is missing, inconsistent, or outside the accepted policy."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PostprocessError(message)


def _digest(value: Any, name: str) -> str:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
             f"invalid SHA256: {name}")
    return value


def _number(value: Any) -> float:
    _require(not isinstance(value, bool), "boolean is not a numerical observation")
    result = float(value)
    _require(math.isfinite(result), "non-finite numerical observation")
    return result


def _plain(value: Any) -> Any:
    """Accept lists or caller-extracted numpy arrays, without importing numpy."""
    return value.tolist() if hasattr(value, "tolist") else value


def qe_settings(text: str) -> dict[str, Any]:
    """Fingerprint all supplied namelist physics and non-position cards.

    Only runtime paths/labels/output controls are excluded. No unsupported
    namelists are accepted, and omitted settings remain distinct from explicit
    defaults. The narrow QE parser is shared with input preparation.
    """
    parsed = parse_qe_input(text)
    headers = re.findall(r"(?im)^\s*&([A-Za-z_]+)\b", text)
    _require(sorted(name.upper() for name in headers) == ["CELL", "CONTROL", "ELECTRONS", "IONS", "SYSTEM"],
             "force input must use the five campaign template namelists")
    values: dict[str, Any] = {}
    runtime_keys = {"prefix", "outdir", "pseudo_dir", "verbosity", "disk_io", "max_seconds"}
    for name in ("CONTROL", "SYSTEM", "ELECTRONS", "IONS", "CELL"):
        assignments = _scan_assignments(text, _find_namelist(text, name))
        for assignment in assignments:
            if assignment.key.lower() not in runtime_keys:
                value = assignment.value.strip().lower().replace("\"", "'")
                values[f"{name.lower()}.{assignment.key.lower()}"] = value
    for key, expected in (("control.calculation", "'scf'"),
                          ("control.tprnfor", ".true."),
                          ("system.nosym", ".true."), ("system.noinv", ".true.")):
        _require(values.get(key) == expected, f"required force setting {key}={expected}")
    values["cell_angstrom"] = [list(row) for row in parsed.cell_parameters]
    values["species"] = [[s.label, s.mass_amu, s.pseudopotential] for s in parsed.atomic_species]
    values["atom_order"] = [p.label for p in parsed.atomic_positions]
    values["kmesh"] = list(parsed.k_points.grid)
    values["kshift"] = list(parsed.k_points.shift)
    return values


@dataclass(frozen=True)
class ForceArtifact:
    """One immutable task-map entry plus its successful execution receipt.

    ``manifest`` requires input/output/stderr SHA256, dataset_sha256,
    supercell_sha256, pseudo_sha256 (species to file digest), settings_sha256,
    atom_order, and returncode. The caller must verify that these are from the
    authoritative task map/launch chain rather than a newly inferred manifest.
    """

    displacement_id: int  # 0 is reserved for matching pristine
    input_path: str
    output_path: str
    stderr_path: str
    manifest: Mapping[str, Any]


def load_force_artifact(force_manifest_path: str | Path, attempt_dir: str | Path,
                        task_id: int) -> ForceArtifact:
    """Adapt an immutable force-backend receipt without caller-supplied physics.

    The force manifest is the supplied trust anchor. Dataset and pristine
    supercell are identified only by its unique, hashed evidence entries;
    settings come from its hashed task input. Every receipt must refer back
    to that manifest and exact task. Missing/ambiguous legacy fields fail closed.
    """
    def absolute(value: Any, label: str) -> Path:
        _require(isinstance(value, (str, Path)), f"invalid {label} path")
        path = Path(value)
        _require(path.is_absolute(), f"absolute {label} path required")
        _require("READY_TO_ATTACH" not in path.parts, "frozen attachment evidence is forbidden")
        return path.resolve()

    def read(path: Path) -> dict[str, Any]:
        _require(path.is_file(), f"missing receipt: {path}")
        data = json.loads(path.read_text())
        _require(isinstance(data, dict), f"receipt must be an object: {path}")
        return data

    def match(path: Path, digest: Any, label: str) -> None:
        _require(path.is_file(), f"missing {label}: {path}")
        _require(file_hash(path) == _digest(digest, label), f"{label} hash mismatch")

    try:
        anchor = absolute(force_manifest_path, "force manifest")
        attempt = absolute(attempt_dir, "attempt")
        _require(anchor.name == "force_manifest.json", "expected force_manifest.json")
        bundle = anchor.parent
        _require(attempt.is_dir() and not attempt.is_relative_to(bundle)
                 and not bundle.is_relative_to(attempt), "attempt must be separate from force bundle")
        _require(not (attempt / "failure.json").exists(), "attempt has a failure receipt")
        manifest = read(anchor)
        anchor_hash = file_hash(anchor)
        _require(manifest["schema_version"] == 1 and manifest["stage"] == "force",
                 "unsupported force manifest schema/stage")
        _require(type(task_id) is int and type(manifest["task_count"]) is int
                 and 0 <= task_id < manifest["task_count"], "task_id outside manifest domain")
        tasks = manifest["tasks"]
        _require(isinstance(tasks, list) and len(tasks) == manifest["task_count"], "task count mismatch")
        task_map = bundle / "task_map.tsv"
        match(task_map, manifest["task_map_sha256"], "task map")
        fields = ["task_id", "displacement_id", "role", "input_path", "input_sha256"]
        with task_map.open(newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            _require(reader.fieldnames == fields, "unexpected task map schema")
            rows = list(reader)
        _require(len(rows) == len(tasks), "task map count mismatch")
        for index, (row, item) in enumerate(zip(rows, tasks)):
            _require(type(item["task_id"]) is int and item["task_id"] == index
                     and all(str(item[key]) == row[key] for key in fields), "task map/manifest row mismatch")
            identifier = item["displacement_id"]
            _require(type(identifier) is int and identifier >= 0
                     and item["role"] == ("pristine" if identifier == 0 else "displacement"),
                     "invalid task displacement ID/role")
        task = tasks[task_id]
        source = absolute(task["input_path"], "task input")
        _require(source.is_relative_to(bundle) and source != bundle, "task input outside force bundle")
        match(source, task["input_sha256"], "task input")

        evidence = manifest["evidence_sha256"]
        _require(isinstance(evidence, dict) and bool(evidence), "missing hashed force evidence")
        paths = {}
        for name, digest in evidence.items():
            path = absolute(name, "evidence")
            _require(path not in paths, "ambiguous resolved evidence paths")
            match(path, digest, "source evidence")
            paths[path] = digest
        datasets = [p for p in paths if p.name == "phono3py_disp.yaml"]
        _require(len(datasets) == 1, "force manifest must anchor exactly one displacement dataset")
        dataset = datasets[0]
        supercells = [p for p in paths if p.name == "supercell.in"]
        _require(len(supercells) == 1 and supercells[0].parent == dataset.parent,
                 "force manifest must anchor one matching pristine supercell")

        # Selection probes are independent provenance, not the current dataset
        # identity. Recheck them here too: collection must not accept receipts
        # whose production selection sources have disappeared or changed.
        selection_sources = manifest.get("selection_evidence_sha256", {})
        _require(isinstance(selection_sources, dict), "invalid selection evidence namespace")
        _require(manifest.get("mode") in {"pilot", "production"}, "invalid force mode")
        if manifest["mode"] == "production":
            selection = manifest.get("selection_validation")
            _require(bool(selection_sources) and isinstance(selection, dict)
                     and selection_sources == selection.get("evidence_sha256"),
                     "missing or inconsistent production selection evidence")
        else:
            _require(not selection_sources, "pilot cannot carry production selection evidence")
        selection_paths = set()
        for name, digest in selection_sources.items():
            path = absolute(name, "selection evidence")
            _require(path not in selection_paths, "ambiguous resolved selection evidence paths")
            match(path, digest, "selection source evidence")
            selection_paths.add(path)

        claim = read(attempt / "force_claim.json")
        launch = read(attempt / "launch.json")
        result = read(attempt / "result.json")
        _require(type(claim["task_id"]) is int and claim["task_id"] == task_id
                 and claim["manifest_sha256"] == anchor_hash, "force claim task/manifest mismatch")
        _require(launch["force_manifest_sha256"] == anchor_hash and launch["task"] == task,
                 "launch task/manifest mismatch")
        _require(result["force_manifest_sha256"] == anchor_hash
                 and type(result["task_id"]) is int and result["task_id"] == task_id
                 and type(result["displacement_id"]) is int
                 and result["displacement_id"] == task["displacement_id"]
                 and result["role"] == task["role"], "result task/manifest mismatch")
        _require(result["healthy"] is True and result["health"]["healthy"] is True,
                 "result does not report a healthy calculation")
        process = result["process"]
        _require(isinstance(process, dict) and process == read(attempt / "scf.process.json"),
                 "nested process receipt differs from scf.process.json")
        _require(type(process["returncode"]) is int and process["returncode"] == 0,
                 "nested process did not exit successfully")
        _require(absolute(process["cwd"], "process cwd") == attempt
                 and process["command"] == launch["command"], "process launch command/cwd mismatch")
        command = launch["command"]
        _require(isinstance(command, list) and len(command) >= 3
                 and command[-2:] == ["-in", "scf.in"], "launch does not target scf.in")
        _require(result["input_sha256"] == task["input_sha256"], "result input hash mismatch")
        match(attempt / "scf.in", task["input_sha256"], "attempt input")
        _require(result["output_sha256"] == process["stdout_sha256"], "result/process output hash mismatch")
        match(attempt / "scf.out", process["stdout_sha256"], "attempt output")
        match(attempt / "scf.err", process["stderr_sha256"], "attempt stderr")
        settings = qe_settings(source.read_text())
        parsed = parse_qe_input(source.read_text())
        _require(type(task["nat"]) is int and parsed.nat == task["nat"]
                 and settings["atom_order"] == task["atom_labels"], "task atom-order/count mismatch")
        types = {species.label: i + 1 for i, species in enumerate(parsed.atomic_species)}
        _require(task["species_types"] == [types[label] for label in task["atom_labels"]],
                 "task species-type mismatch")
        pseudos = manifest["pseudopotentials"]
        _require(set(pseudos) == set(types), "manifest pseudo species mismatch")
        pseudo_hashes = {}
        for species in parsed.atomic_species:
            item = pseudos[species.label]
            path = absolute(item["file"], "pseudopotential")
            _require(path.name == species.pseudopotential, "manifest pseudo filename mismatch")
            match(path, item["sha256"], "pseudopotential")
            pseudo_hashes[species.label] = item["sha256"]
        adapted = {
            "input_sha256": task["input_sha256"], "output_sha256": result["output_sha256"],
            "stderr_sha256": process["stderr_sha256"], "returncode": process["returncode"],
            "dataset_sha256": paths[dataset], "supercell_sha256": paths[supercells[0]],
            "settings_sha256": canonical_hash(settings), "pseudo_sha256": pseudo_hashes,
            "atom_order": list(task["atom_labels"]), "force_manifest_sha256": anchor_hash,
            "receipt_sha256": {name: file_hash(attempt / name) for name in
                               ("force_claim.json", "launch.json", "result.json", "scf.process.json")},
        }
        artifact = ForceArtifact(task["displacement_id"], str(attempt / "scf.in"),
                                 str(attempt / "scf.out"), str(attempt / "scf.err"), adapted)
        audit_force_artifact(artifact)
        return artifact
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, PostprocessError):
            raise
        raise PostprocessError(f"invalid force receipt chain: {exc}") from exc


def audit_force_artifact(artifact: ForceArtifact) -> dict[str, Any]:
    manifest = artifact.manifest
    for label in ("input", "output", "stderr"):
        path = Path(getattr(artifact, f"{label}_path"))
        _require(path.is_absolute() and path.is_file(), f"missing absolute {label} file")
        _require(file_hash(path) == _digest(manifest[f"{label}_sha256"], label),
                 f"{label} hash mismatch")
    _require(type(manifest["returncode"]) is int and manifest["returncode"] == 0,
             "QE process did not exit successfully")
    for key in ("dataset_sha256", "supercell_sha256", "settings_sha256"):
        _digest(manifest[key], key)
    settings = qe_settings(Path(artifact.input_path).read_text())
    order = list(manifest["atom_order"])
    _require(bool(order) and settings["atom_order"] == order, "input atom-order mismatch")
    _require(canonical_hash(settings) == manifest["settings_sha256"], "setting hash mismatch")
    pseudos = manifest["pseudo_sha256"]
    _require(set(pseudos) == {row[0] for row in settings["species"]}, "pseudo species mismatch")
    for species, digest in pseudos.items():
        _digest(digest, f"pseudo {species}")
    health = inspect_output(artifact.output_path, len(order))
    _require(health["healthy"], f"unhealthy force output: {health['errors']}")
    stderr = Path(artifact.stderr_path).read_text(errors="replace")
    _require(re.search(r"MPI_ABORT|segmentation fault|killed|fatal|error in routine|time limit",
                       stderr, re.I) is None, "failure signature in QE stderr")
    text = Path(artifact.output_path).read_text(errors="replace")
    starts = list(RUN_START.finditer(text))
    run = text[starts[-1].start():] if starts else text
    header = list(FORCE_HEADER.finditer(run))[-1]
    force_types = []
    started = False
    for line in run[header.end():].splitlines():
        match = re.match(r"\s*atom\s+(\d+)\s+type\s+(\d+)\s+force\s*=", line)
        if match:
            force_types.append(int(match.group(2)))
            started = True
        elif started or line.strip():
            break
    species_types = {row[0]: index + 1 for index, row in enumerate(settings["species"])}
    _require(force_types == [species_types[label] for label in order], "output atom-type order mismatch")
    return {"healthy": True, "displacement_id": artifact.displacement_id,
            "settings_sha256": manifest["settings_sha256"], "health": health,
            "input_sha256": manifest["input_sha256"], "output_sha256": manifest["output_sha256"]}


def plan_force_collection(*, kind: str, dataset_path: str, dataset_sha256: str,
                          expected_ids: Sequence[int], displaced: Sequence[ForceArtifact],
                          pristine: ForceArtifact, max_pristine_ry_bohr: float = 5e-5) -> dict[str, Any]:
    """Validate every input then construct an ordered phono3py-init argv.

    Call independently for FC3 and a separate FC2 dataset. ``expected_ids``
    must be the authoritative YAML *included* displacement IDs in ascending
    numerical ID order, preserving gaps; excluded cutoff pairs are filled by
    phono3py itself. An FC2-only larger supercell needs its own pristine.
    """
    _require(kind in ("fc2", "fc3"), "kind must be fc2 or fc3")
    _require(Path(dataset_path).is_absolute(), "absolute dataset path required")
    _require(file_hash(dataset_path) == _digest(dataset_sha256, "dataset"), "dataset hash mismatch")
    ids = list(expected_ids)
    _require(bool(ids) and all(type(i) is int and i > 0 for i in ids) and len(set(ids)) == len(ids),
             "invalid expected displacement IDs")
    _require(ids == sorted(ids), "expected displacement IDs must be in numerical file order")
    supplied = [a.displacement_id for a in displaced]
    _require(len(supplied) == len(set(supplied)) and set(supplied) == set(ids),
             "missing, extra or duplicate displacement IDs")
    _require(pristine.displacement_id == 0, "pristine must have reserved ID 0")
    _require(_number(max_pristine_ry_bohr) > 0, "positive pristine threshold required")
    pristine_audit = audit_force_artifact(pristine)
    _require(pristine_audit["health"]["max_abs_force_ry_bohr"] <= max_pristine_ry_bohr,
             "pristine residual exceeds acceptance limit")
    by_id = {a.displacement_id: a for a in displaced}
    audits = []
    matched = ("dataset_sha256", "supercell_sha256", "settings_sha256", "pseudo_sha256", "atom_order")
    _require(pristine.manifest["dataset_sha256"] == dataset_sha256, "pristine dataset mismatch")
    for identifier in ids:
        artifact = by_id[identifier]
        audit = audit_force_artifact(artifact)
        for key in matched:
            _require(artifact.manifest[key] == pristine.manifest[key], f"pristine mismatch: {key}")
        audits.append(audit)
    return {"accepted": True, "kind": kind, "dataset_source": dataset_path,
            "dataset_sha256": dataset_sha256, "working_dataset_name": "phono3py_disp.yaml",
            "required_execution_location": "DRAC_compute_node", "requires_empty_workdir": True,
            "argv": ["phono3py-init", "--qe", "--cf3" if kind == "fc3" else "--cf2",
                     *[by_id[i].output_path for i in ids], "--cfz", pristine.output_path],
            "expected_product": f"FORCES_{kind.upper()}", "ordered_ids": ids,
            "force_audits": audits, "pristine_audit": pristine_audit}


def audit_force_product(product_text: str, *, all_dataset_ids: Sequence[int],
                        included: Sequence[ForceArtifact], pristine: ForceArtifact,
                        absolute_tolerance_ry_bohr: float = 5e-10) -> dict[str, Any]:
    """Verify type-I FORCES text against raw minus pristine, including zeros.

    Supply *all* dataset IDs in numerical displacement-ID order, including
    excluded cutoff pairs. phono3py writes FORCES blocks in this ID order,
    not in the grouped presentation order of ``displacement_pairs`` in YAML.
    This is a post-command check paired with ``plan_force_collection``; the
    driver must preserve the already-audited immutable raw evidence. No force
    units are converted here: QE FORCES collection is in Ry/bohr.
    """
    ids = list(all_dataset_ids)
    _require(bool(ids) and all(type(i) is int and i > 0 for i in ids) and len(set(ids)) == len(ids),
             "invalid all-dataset ID sequence")
    _require(ids == list(range(1, len(ids) + 1)),
             "all-dataset IDs must be the complete numerical 1..N order")
    artifacts = {a.displacement_id: a for a in included}
    _require(len(artifacts) == len(included) and set(artifacts) <= set(ids), "invalid included dataset IDs")
    audit_force_artifact(pristine)
    residual = parse_last_force_block(pristine.output_path).forces_ry_bohr
    expected = []
    for identifier in ids:
        if identifier in artifacts:
            artifact = artifacts[identifier]
            audit_force_artifact(artifact)
            for key in ("dataset_sha256", "supercell_sha256", "settings_sha256", "pseudo_sha256", "atom_order"):
                _require(artifact.manifest[key] == pristine.manifest[key], f"pristine mismatch: {key}")
            forces = parse_last_force_block(artifact.output_path, len(residual)).forces_ry_bohr
            expected.extend([[f-p for f, p in zip(row, baseline)] for row, baseline in zip(forces, residual)])
        else:
            expected.extend([[0.0, 0.0, 0.0] for _ in residual])
    observed = []
    for line in product_text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tokens = line.split()
            _require(len(tokens) == 3, "FORCES product is not type-I three-column data")
            observed.append([_number(token.replace("D", "E").replace("d", "e")) for token in tokens])
    _require(len(observed) == len(expected), "FORCES product block/atom count mismatch")
    tolerance = _number(absolute_tolerance_ry_bohr)
    _require(tolerance > 0, "positive FORCES comparison tolerance required")
    maximum = max(abs(x-y) for row, baseline in zip(observed, expected) for x, y in zip(row, baseline))
    _require(maximum <= tolerance, "FORCES product differs from residual-corrected ordered forces")
    return {"accepted": True, "all_dataset_ids": ids, "excluded_zero_blocks": len(ids)-len(artifacts),
            "atom_count": len(residual), "max_difference_ry_bohr": maximum,
            "absolute_tolerance_ry_bohr": tolerance}


def _matrix(value: Any) -> list[list[float]]:
    value = _plain(value)
    _require(len(value) == 3 and all(len(row) == 3 for row in value), "expected 3x3 matrix")
    return [[_number(x) for x in row] for row in value]


def _transpose(a: Sequence[Sequence[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*a)]


def _multiply(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _det(a: Sequence[Sequence[float]]) -> float:
    return (a[0][0] * (a[1][1]*a[2][2]-a[1][2]*a[2][1])
            - a[0][1] * (a[1][0]*a[2][2]-a[1][2]*a[2][0])
            + a[0][2] * (a[1][0]*a[2][1]-a[1][1]*a[2][0]))


def _inverse(a: Sequence[Sequence[float]]) -> list[list[float]]:
    determinant = _det(a)
    _require(abs(determinant) > 1e-15, "singular frame")
    return [[(a[(j+1)%3][(i+1)%3]*a[(j+2)%3][(i+2)%3]
              - a[(j+1)%3][(i+2)%3]*a[(j+2)%3][(i+1)%3])/determinant
             for j in range(3)] for i in range(3)]


def conventional_frame(primitive_rows: Any, transform_rows: Any,
                       max_axis_cosine: float = 1e-3) -> dict[str, Any]:
    """Recompute R from accepted geometry: C=T*A, R=(C*C^T)^(-1/2)*C.

    Newton polar iteration is a dependency-free equivalent. Require a
    right-handed, already nearly orthogonal conventional cell; do not silently
    orthogonalize an arbitrary oblique primitive basis.
    """
    conventional = _multiply(_matrix(transform_rows), _matrix(primitive_rows))
    _require(_det(conventional) > 1e-12, "conventional frame must be right-handed")
    gram = _multiply(conventional, _transpose(conventional))
    cosine = max(abs(gram[i][j])/math.sqrt(gram[i][i]*gram[j][j])
                 for i in range(3) for j in range(i))
    _require(0 <= cosine <= max_axis_cosine, "conventional axes are not sufficiently orthogonal")
    scale = math.sqrt(sum(x*x for row in conventional for x in row)/3)
    rotation = [[x/scale for x in row] for row in conventional]
    for _ in range(40):
        inverse_transpose = _transpose(_inverse(rotation))
        new = [[(rotation[i][j]+inverse_transpose[i][j])/2 for j in range(3)] for i in range(3)]
        delta = max(abs(new[i][j]-rotation[i][j]) for i in range(3) for j in range(3))
        rotation = new
        if delta < 1e-13:
            break
    identity = _multiply(rotation, _transpose(rotation))
    _require(max(abs(identity[i][j]-(i == j)) for i in range(3) for j in range(3)) < 1e-10,
             "polar frame did not converge")
    return {"conventional_cell_angstrom": conventional, "rotation_rows": rotation,
            "max_axis_cosine": cosine, "rotation_determinant": _det(rotation)}


def tensor_from_six(values: Sequence[float]) -> list[list[float]]:
    """phono3py order is xx, yy, zz, yz, xz, xy; not engineering Voigt shear."""
    _require(len(values) == 6, "full six-component conductivity is required")
    xx, yy, zz, yz, xz, xy = map(_number, values)
    return [[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]]


def rotate_tensor(tensor: Any, rotation_rows: Any) -> list[list[float]]:
    tensor, rotation = _matrix(tensor), _matrix(rotation_rows)
    _require(max(abs(tensor[i][j]-tensor[j][i]) for i in range(3) for j in range(3)) < 1e-10,
             "conductivity tensor is not symmetric")
    identity = _multiply(rotation, _transpose(rotation))
    _require(max(abs(identity[i][j]-(i == j)) for i in range(3) for j in range(3)) < 1e-10
             and abs(_det(rotation)-1) < 1e-10, "rotation must be proper orthonormal")
    return _multiply(_multiply(rotation, tensor), _transpose(rotation))


def audit_force_constant_summary(summary: Mapping[str, Any], *, order: int,
                                 supercell_atoms: int, primitive_atoms: int,
                                 expected_sha256: str,
                                 acoustic_sum_rule_tolerance: float,
                                 permutation_tolerance: float) -> dict[str, Any]:
    """Gate a compute-node FC2/FC3 array scan without loading arrays locally.

    The outer scanner records ``shape``, ``all_finite``, ``p2s_map`` for compact
    format, ``units``, ``sha256``, ``acoustic_sum_rule_max_abs`` and
    ``permutation_max_abs``. Residuals and caller-selected tolerances must use
    the declared FC units; no arbitrary universal drift threshold is assumed.
    """
    _require(order in (2, 3), "force-constant order must be 2 or 3")
    _require(type(supercell_atoms) is int and type(primitive_atoms) is int
             and 0 < primitive_atoms <= supercell_atoms, "invalid force-constant atom counts")
    _require(_digest(summary["sha256"], "force constants") == _digest(expected_sha256, "expected FC"),
             "force-constant hash mismatch")
    expected_tail = [supercell_atoms] * (order-1) + [3] * order
    shape = list(summary["shape"])
    _require(shape in ([supercell_atoms] + expected_tail, [primitive_atoms] + expected_tail),
             "force-constant shape mismatch")
    _require(summary["all_finite"] is True, "force-constant array has non-finite values or was not scanned")
    units = "eV angstrom^-2" if order == 2 else "eV angstrom^-3"
    _require(summary["units"] == units, "force-constant unit mismatch")
    if shape[0] != supercell_atoms:
        mapping = list(summary["p2s_map"])
        _require(len(mapping) == primitive_atoms and len(set(mapping)) == primitive_atoms
                 and all(type(i) is int and 0 <= i < supercell_atoms for i in mapping),
                 "compact FC primitive-to-supercell mapping invalid")
    residuals = {}
    for name, tolerance in (("acoustic_sum_rule_max_abs", acoustic_sum_rule_tolerance),
                            ("permutation_max_abs", permutation_tolerance)):
        residual = _number(summary[name])
        threshold = _number(tolerance)
        _require(residual >= 0 and threshold >= 0, "negative force-constant drift or tolerance")
        _require(residual <= threshold, f"force-constant {name} exceeds tolerance")
        residuals[name] = residual
    return {"accepted": True, "order": order, "shape": shape, "units": units,
            "residuals": residuals, "sha256": summary["sha256"],
            "scope": "array integrity and symmetry drift only; not interaction-range convergence"}


def audit_kappa_payload(payload: Mapping[str, Any], metadata: Mapping[str, Any],
                        expected: Mapping[str, Any], config: Mapping[str, Any],
                        rotation_rows: Any = None) -> dict[str, Any]:
    """Validate arrays extracted from a hashed HDF5 on the compute node.

    Required metadata/expected keys: hdf5_sha256, fc2_sha256, fc3_sha256,
    dataset_sha256, settings_sha256, grid_matrix, ladder_index, solver, nac,
    isotope_scattering, boundary_scattering, explicit_SOC, phono3py_version.
    HDF5 frequencies/weights must cover every grid point by symmetry weight.
    A GRG grid_matrix comes from the runtime grid object, not a guessed mesh.
    """
    for key in ("hdf5_sha256", "fc2_sha256", "fc3_sha256", "dataset_sha256", "settings_sha256"):
        _require(_digest(metadata[key], key) == _digest(expected[key], key), f"{key} mismatch")
    for key in ("grid_matrix", "ladder_index", "solver", "nac", "isotope_scattering",
                "boundary_scattering", "explicit_SOC", "phono3py_version"):
        _require(metadata[key] == expected[key], f"launch metadata mismatch: {key}")
    post = config["postprocess"]
    ladder = post["q_mesh_length_ladder"] if post.get("use_grg", False) else post["q_mesh_ladder"]
    _require(type(metadata["ladder_index"]) is int and 0 <= metadata["ladder_index"] < len(ladder),
             "invalid ladder index")
    for key in ("solver", "isotope_scattering", "boundary_scattering", "explicit_SOC"):
        _require(metadata[key] == post[key], f"solver policy mismatch: {key}")
    _require(metadata["nac"] == config["nac"]["enabled_for_first_pass"], "NAC policy mismatch")
    _require(metadata["phono3py_version"] == config["software"]["phono3py_version"], "version mismatch")
    _require(metadata.get("units") == {"kappa": "W m^-1 K^-1", "frequency": "THz", "temperature": "K"},
             "explicit HDF5 unit contract required")
    temperatures = [_number(x) for x in _plain(payload["temperature"])]
    _require(temperatures == list(post["temperatures_K"]), "temperature grid/order mismatch")
    raw = [tensor_from_six(row) for row in _plain(payload["kappa"])]
    _require(len(raw) == len(temperatures), "kappa/temperature shape mismatch")
    grid = _matrix(metadata["grid_matrix"])
    _require(all(x == int(x) for row in grid for x in row), "grid matrix must be integer")
    count = abs(round(_det(grid)))
    _require(count > 0, "singular grid")
    mesh = list(_plain(payload["mesh"]))
    _require(len(mesh) == 3 and all(type(x) is int and x > 0 for x in mesh)
             and math.prod(mesh) == count, "HDF5 mesh/GRG grid-count mismatch")
    if not post.get("use_grg", False):
        _require(grid == [[mesh[0], 0, 0], [0, mesh[1], 0], [0, 0, mesh[2]]], "mesh matrix mismatch")
        _require(mesh == post["q_mesh_ladder"][metadata["ladder_index"]], "wrong ladder mesh")
    else:
        expected_length = post["q_mesh_length_ladder"][metadata["ladder_index"]]["mesh_length_cli_bohr"]
        _require(metadata.get("mesh_length_cli_bohr") == expected_length, "wrong GRG design length")
        spacing = metadata.get("reciprocal_spacing_inv_angstrom", [])
        _require(len(spacing) == 3 and all(_number(x) > 0 for x in spacing), "GRG spacing evidence missing")
    frequency = [[_number(x) for x in row] for row in _plain(payload["frequency"])]
    weights = [_number(x) for x in _plain(payload["weight"])]
    qpoints = [[_number(x) for x in row] for row in _plain(payload["qpoint"])]
    bands = 3 * config["material"]["unitcell_atoms"]
    _require(bool(frequency) and all(len(row) == bands for row in frequency), "frequency band shape mismatch")
    _require(len(weights) == len(frequency) == len(qpoints) and all(len(q) == 3 for q in qpoints),
             "q-point/weight/frequency shape mismatch")
    canonical_qpoints = {tuple(round(x % 1, 9) % 1 for x in row) for row in qpoints}
    _require(len(canonical_qpoints) == len(qpoints), "duplicate irreducible q points")
    _require(all(w > 0 and w == int(w) for w in weights) and sum(weights) == count,
             "frequency evidence does not cover full mesh")
    threshold = post["harmonic_stability_gate"]["imaginary_frequency_tolerance_THz"]
    failures = [{"q_index": i, "band_index": j, "frequency_THz": f,
                 "at_Gamma": all(abs(x-round(x)) < 1e-8 for x in qpoints[i])}
                for i, row in enumerate(frequency) for j, f in enumerate(row) if f < threshold]
    require_rotation = post["q_mesh_acceptance"].get("compare_in_rotated_conventional_frame", False)
    _require(not require_rotation or rotation_rows is not None, "conventional tensor frame required")
    tensors = [rotate_tensor(t, rotation_rows) for t in raw] if rotation_rows is not None else raw
    for tensor in tensors:
        scale = max(abs(x) for row in tensor for x in row)
        _require(scale > 0 and all(tensor[i][i] > 0 for i in range(3)), "nonpositive conductivity diagonal")
        normalized = [[x/scale for x in row] for row in tensor]
        _require(all(normalized[i][i]*normalized[j][j]-normalized[i][j]**2 >= -1e-10
                     for i in range(3) for j in range(i)) and _det(normalized) >= -1e-10,
                 "conductivity is not positive semidefinite")
    offdiag = [max(abs(t[i][j]) for i in range(3) for j in range(i))/(sum(t[i][i] for i in range(3))/3)
               for t in tensors]
    limit = post["q_mesh_acceptance"].get("investigate_if_max_off_diagonal_fraction_of_trace_over_3_exceeds")
    offdiag_pass = limit is None or max(offdiag) <= limit
    fingerprint = {key: metadata[key] for key in ("fc2_sha256", "fc3_sha256", "dataset_sha256",
                   "settings_sha256", "solver", "nac", "isotope_scattering", "boundary_scattering",
                   "explicit_SOC", "phono3py_version")}
    fingerprint["rotation_rows"] = _matrix(rotation_rows) if rotation_rows is not None else None
    return {"accepted": not failures and offdiag_pass, "temperatures_K": temperatures,
            "tensors_raw_W_mK": raw, "tensors_comparison_W_mK": tensors,
            "comparison_frame": "conventional_orthonormal" if rotation_rows is not None else "cartesian",
            "ladder_index": metadata["ladder_index"], "grid_matrix": grid, "grid_count": count,
            "physics_fingerprint": canonical_hash(fingerprint), "hdf5_sha256": metadata["hdf5_sha256"],
            "minimum_frequency_THz": min(min(row) for row in frequency),
            "imaginary_modes_beyond_tolerance": failures,
            "Gamma_exception_requires_review": any(f["at_Gamma"] for f in failures),
            "off_diagonal_fraction": offdiag, "off_diagonal_gate_passed": offdiag_pass,
            "stability_scope": "sampled mesh only; not proof of stability everywhere"}


def qmesh_convergence(reports: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    """All temperatures/diagonals, two *trailing consecutive* declared steps.

    Relative changes use the newer (denser) value as denominator. A previously
    passed pair cannot excuse failure of the newest mesh; skipped/reordered
    levels and mixing different FC/NAC/frame settings are errors.
    """
    _require(bool(reports), "no q-mesh reports")
    _require(type(policy["consecutive_passing_mesh_steps_required"]) is int
             and policy["consecutive_passing_mesh_steps_required"] >= 2,
             "at least two consecutive mesh steps are required")
    indices = [r["ladder_index"] for r in reports]
    _require(indices == list(range(len(reports))), "q-mesh ladder must be an unskipped prefix")
    _require(all(r["physics_fingerprint"] == reports[0]["physics_fingerprint"] for r in reports),
             "different force constants, solver settings or frames across mesh ladder")
    _require(all(r["temperatures_K"] == reports[0]["temperatures_K"] for r in reports),
             "temperatures differ across mesh ladder")
    steps, trailing = [], 0
    for previous, current in zip(reports, reports[1:]):
        changes = []
        for left, right in zip(previous["tensors_comparison_W_mK"], current["tensors_comparison_W_mK"]):
            left, right = _matrix(left), _matrix(right)
            _require(all(right[i][i] > 0 for i in range(3)), "nonpositive q convergence denominator")
            diagonal = [abs(right[i][i]-left[i][i])/right[i][i] for i in range(3)]
            average = abs(sum(right[i][i]-left[i][i] for i in range(3)))/sum(right[i][i] for i in range(3))
            changes.append({"trace_over_3_relative_change": average, "diagonal_relative_changes": diagonal})
        passed = bool(previous["accepted"] and current["accepted"] and changes and
                      len(changes) == len(current["temperatures_K"]) and
                      all(c["trace_over_3_relative_change"] < policy["maximum_relative_change_trace_over_3"]
                          and max(c["diagonal_relative_changes"]) < policy["maximum_relative_change_each_diagonal_component"]
                          for c in changes))
        trailing = trailing + 1 if passed else 0
        steps.append({"from_index": previous["ladder_index"], "to_index": current["ladder_index"],
                      "passed": passed, "temperature_changes": changes})
    passed = trailing >= policy["consecutive_passing_mesh_steps_required"]
    return {"qmesh_converged": passed, "trailing_passing_steps": trailing, "steps": steps,
            "label": "qmesh_converged_first_pass" if passed else "first_pass_unconverged",
            "scope": "q-grid convergence only; does not establish cutoff, supercell or NAC convergence"}


def claim_review(*, force_gate_passed: bool, hdf5_gate_passed: bool,
                 qmesh_gate_passed: bool, force_accuracy_passed: bool = False,
                 amplitude_passed: bool = False, supercell_passed: bool = False,
                 cutoff_passed: bool = False, nac_sensitivity_passed: bool = False,
                 nac_enabled: bool = False) -> dict[str, Any]:
    """Describe numerical evidence; never promote kappa_L into final zT."""
    limitations = ["calculated PBE RTA result", "no explicit SOC",
                   "no isotope or boundary scattering", "stability sampled on finite q grids",
                   "full zT requires electronic relaxation-time evidence and consistent transport data"]
    if not nac_enabled:
        limitations.append("no NAC included")
    gates = {"force_output": force_gate_passed, "hdf5_and_stability": hdf5_gate_passed,
             "force_accuracy": force_accuracy_passed, "amplitude": amplitude_passed,
             "qmesh": qmesh_gate_passed, "supercell": supercell_passed,
             "pair_cutoff": cutoff_passed, "NAC_sensitivity": nac_sensitivity_passed}
    missing = [name for name, passed in gates.items() if passed is not True]
    if not (force_gate_passed and hdf5_gate_passed and force_accuracy_passed and amplitude_passed):
        label = "workflow_or_validation_status_only"
    elif missing:
        label = "calculated_first_pass" if qmesh_gate_passed else "first_pass_unconverged"
    else:
        label = "numerically_validated_within_stated_model"
    return {"label": label, "missing_gates": missing, "limitations": limitations,
            "final_zT_claim_allowed": False, "experimental_agreement_established": False,
            "total_physical_uncertainty_established": False}

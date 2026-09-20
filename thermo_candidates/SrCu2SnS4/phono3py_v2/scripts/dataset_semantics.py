"""Fail-closed semantic validation of a QE phono3py displacement dataset."""
import math
import re
from pathlib import Path


def inspect_dataset(inputs: Path, cutoff: float = 7.5589045) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("PyYAML is required by the phono3py generation environment") from exc
    data = yaml.safe_load((inputs / "phono3py_disp.yaml").read_text())
    require(data["phono3py"]["calculator"] == "qe", "calculator is not QE")
    version = str(data["phono3py"]["version"])
    require(re.fullmatch(r"\d+(?:\.\d+)+", version) is not None, "missing semantic phono3py version")
    require(data["physical_unit"]["length"] == "au", "YAML length unit is not au")
    require(data["space_group"]["type"] == "P3_121" and int(data["space_group"]["number"]) == 152, "space group mismatch")
    require(abs(float(data["phono3py"]["symmetry_tolerance"]) - 0.001) < 1e-12, "symmetry tolerance mismatch")
    require(data["supercell_matrix"] == [[2, 0, 0], [0, 2, 0], [0, 0, 1]], "supercell matrix mismatch")
    require(len(data["unit_cell"]["points"]) == 24 and len(data["supercell"]["points"]) == 96, "unit/supercell atom count mismatch")
    included, nonzero, included_distances, excluded_distances = set(), 0, [], []
    for pair in data["displacement_pairs"]:
        entries = [(pair["displacement_id"], pair["displacement"])]
        for mate in pair.get("paired_with", []):
            require(type(mate.get("included")) is bool, "paired_with included flag is not boolean")
            distance = float(mate["pair_distance"])
            require(mate["included"] == (distance <= cutoff + 1e-8), "pair cutoff classification mismatch")
            require(len(mate["displacement_ids"]) == len(mate["displacements"]), "paired displacement lengths mismatch")
            if mate["included"]:
                included_distances.append(distance)
                if distance > 1e-8: nonzero += 1
                entries.extend(zip(mate["displacement_ids"], mate["displacements"]))
            else:
                excluded_distances.append(distance)
        for ident, vector in entries:
            require(ident not in included, "duplicate included displacement ID")
            require(abs(math.sqrt(sum(float(x) ** 2 for x in vector)) - 0.06) < 1e-8, "displacement amplitude mismatch")
            included.add(int(ident))
    fragments = {int(path.stem.split("-")[1]) for path in inputs.glob("supercell-*.in")}
    require(included == fragments and len(included) == len(fragments), "included displacement IDs do not bijectively match fragments")
    require(nonzero > 0, "no nonzero included pair")
    return {"phono3py_version": version, "calculator": "qe", "length_unit": "au", "symmetry_tolerance": 0.001,
            "supercell_matrix": [[2, 0, 0], [0, 2, 0], [0, 0, 1]], "unitcell_atoms": 24, "supercell_atoms": 96,
            "amplitude_bohr": 0.06, "cutoff_bohr": cutoff, "included_displacement_ids": sorted(included),
            "included_displacement_count": len(included), "nonzero_included_pair_count": nonzero,
            "max_included_pair_distance_bohr": max(included_distances), "min_excluded_pair_distance_bohr": min(excluded_distances)}


def require(condition, message):
    if not condition:
        raise ValueError(message)

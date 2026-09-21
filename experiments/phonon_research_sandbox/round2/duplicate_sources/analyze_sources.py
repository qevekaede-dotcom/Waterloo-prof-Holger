#!/usr/bin/env python3
"""Read saved manifest/YAML only; identify candidates, never deduplicate forces."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914"
MANIFEST = BASE / "production/force_manifest.json"
DATASET = BASE / "preflight/phono3py_disp.yaml"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    yaml_hash = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    if yaml_hash != manifest["dataset_sha256"]:
        raise ValueError("YAML differs from the manifest-bound dataset")
    dataset = yaml.safe_load(DATASET.read_text())
    if dataset["physical_unit"]["length"] != "au":
        raise ValueError("This record expects the explicitly archived au unit")
    groups = defaultdict(list)
    for task in manifest["tasks"]:
        groups[task["source_sha256"]].append(task["label"])
    repeated = sorted(((h, labels) for h, labels in groups.items() if len(labels) > 1),
                      key=lambda item: (-len(item[1]), item[0]))
    largest_hash, largest_labels = repeated[0]
    targets = {int(label.removeprefix("disp")): label for label in largest_labels}
    cancellations = []
    for first in dataset["displacement_pairs"]:
        for second in first["paired_with"]:
            if len(second["displacement_ids"]) != len(second["displacements"]):
                raise ValueError("Displacement IDs and vectors are not aligned")
            for ident, vector in zip(second["displacement_ids"], second["displacements"]):
                if ident not in targets:
                    continue
                same_atom = first["atom"] == second["atom"]
                net = [a + b for a, b in zip(first["displacement"], vector)] if same_atom else None
                cancellations.append({"label": targets[ident], "first_atom_one_based": first["atom"],
                                      "second_atom_one_based": second["atom"],
                                      "first_vector_bohr": first["displacement"],
                                      "second_vector_bohr": vector, "included": second["included"],
                                      "net_same_atom_vector_bohr": net,
                                      "nominal_net_zero": same_atom and net == [0.0, 0.0, 0.0]})
    if len(cancellations) != len(targets) or len({r["label"] for r in cancellations}) != len(targets):
        raise ValueError("Largest repeated group does not map one-to-one to YAML")
    pristine = next(t for t in manifest["tasks"] if t["label"] == "pristine")
    result = {"scope": "saved manifest hash grouping and nominal displacement arithmetic only",
              "scientific_acceptance": False, "force_noise_measured": False,
              "automatic_force_reuse_allowed": False,
              "sources": [{"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in (MANIFEST, DATASET)],
              "tasks": len(manifest["tasks"]), "unique_recorded_source_hashes": len(groups),
              "multiplicity_histogram": dict(sorted(Counter(map(len, groups.values())).items())),
              "extra_records_beyond_one_per_hash": sum(len(v) - 1 for v in groups.values()),
              "repeated_groups": [{"recorded_source_sha256": h, "labels": labels} for h, labels in repeated],
              "largest_group_recorded_source_sha256": largest_hash,
              "largest_group_nominal_cancellations": cancellations,
              "pristine_source_sha256": pristine["source_sha256"],
              "largest_group_hash_equals_pristine_hash": largest_hash == pristine["source_sha256"],
              "limitation": "Source hashes are manifest records; original generated inputs and force outputs were not reopened. Identical source hashes do not prove identical execution or valid force reuse."}
    output = Path(__file__).with_name("recorded_source_groups.json")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("tasks", "unique_recorded_source_hashes", "multiplicity_histogram", "extra_records_beyond_one_per_hash")}, indent=2))


if __name__ == "__main__":
    main()

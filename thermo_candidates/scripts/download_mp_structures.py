#!/usr/bin/env python3
"""Download the selected Materials Project structures through OPTIMADE."""

from pathlib import Path

from pymatgen.ext.optimade import OptimadeRester
from pymatgen.io.cif import CifWriter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MP_OPTIMADE_URL = "https://optimade.materialsproject.org/v1"
MATERIALS = {
    "SrCu2SnS4": "mp-16988",
    "SrZrS3": "mp-558760",
    "Rb2Cu2SnS4": "mp-18006",
}


def main() -> None:
    with OptimadeRester(MP_OPTIMADE_URL) as rester:
        for formula, mp_id in MATERIALS.items():
            results = rester.get_structures_with_filter(f'id="{mp_id}"')
            structure = results[MP_OPTIMADE_URL][mp_id]

            if structure.composition.reduced_formula != formula:
                raise ValueError(
                    f"{mp_id} returned {structure.composition.reduced_formula}, "
                    f"expected {formula}"
                )

            output = PROJECT_ROOT / formula / "structures" / f"{formula}.cif"
            output.parent.mkdir(parents=True, exist_ok=True)
            CifWriter(
                structure,
                symprec=0.01,
                refine_struct=False,
            ).write_file(output)
            print(f"Downloaded {mp_id} -> {output.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

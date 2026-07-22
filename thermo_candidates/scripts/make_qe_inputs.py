#!/usr/bin/env python
"""Generate starter Quantum ESPRESSO inputs from a CIF file.

Usage:
    python thermo_candidates/scripts/make_qe_inputs.py \
        thermo_candidates/SrCu2SnS4 structures/SrCu2SnS4.cif

The CIF path may be absolute or relative to the candidate folder.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pymatgen.core import Structure
from pymatgen.io.pwscf import PWInput


MATERIALS = {
    "SrCu2SnS4": {
        "prefix": "SrCu2SnS4",
        "pseudo": {
            "Sr": "Sr_pbe_v1.uspp.F.UPF",
            "Cu": "Cu.paw.z_11.ld1.psl.v1.0.0-low.upf",
            "Sn": "Sn_pbe_v1.uspp.F.UPF",
            "S": "s_pbe_v1.4.uspp.F.UPF",
        },
        "ecutwfc": 90,
        "ecutrho": 720,
    },
    "SrZrS3": {
        "prefix": "SrZrS3",
        "pseudo": {
            "Sr": "Sr_pbe_v1.uspp.F.UPF",
            "Zr": "Zr_pbe_v1.uspp.F.UPF",
            "S": "s_pbe_v1.4.uspp.F.UPF",
        },
        "ecutwfc": 40,
        "ecutrho": 320,
    },
    "Rb2Cu2SnS4": {
        "prefix": "Rb2Cu2SnS4",
        "pseudo": {
            "Rb": "Rb_ONCV_PBE-1.0.oncvpsp.upf",
            "Cu": "Cu.paw.z_11.ld1.psl.v1.0.0-low.upf",
            "Sn": "Sn_pbe_v1.uspp.F.UPF",
            "S": "s_pbe_v1.4.uspp.F.UPF",
        },
        "ecutwfc": 90,
        "ecutrho": 720,
    },
}


def candidate_name(candidate_dir: Path) -> str:
    name = candidate_dir.name
    if name not in MATERIALS:
        raise SystemExit(f"Unknown candidate folder: {name}")
    return name


def write_pw_input(
    structure: Structure,
    path: Path,
    prefix: str,
    pseudo: dict[str, str],
    calculation: str,
    ecutwfc: int,
    ecutrho: int,
    kpoints_grid: tuple[int, int, int],
) -> None:
    pseudo_dir = os.environ.get(
        "QE_PSEUDO_SSSP_PBE_PRECISION",
        str(Path.home() / "scientific-tools/pseudopotentials/SSSP/1.3.0/PBE/precision"),
    )
    control = {
        "calculation": calculation,
        "prefix": prefix,
        "outdir": "../tmp",
        "pseudo_dir": pseudo_dir,
        "verbosity": "high",
        "tprnfor": True,
        "tstress": True,
    }
    system = {
        "ecutwfc": ecutwfc,
        "ecutrho": ecutrho,
        "occupations": "fixed",
    }
    electrons = {
        "conv_thr": 1e-8,
        "mixing_beta": 0.3,
    }
    ions = {
        "ion_dynamics": "bfgs",
    }
    cell = {
        "cell_dynamics": "bfgs",
        "press_conv_thr": 0.5,
    }

    if calculation == "scf":
        control.pop("tprnfor", None)
        control.pop("tstress", None)
        ions = None
        cell = None
    elif calculation == "nscf":
        control.pop("tprnfor", None)
        control.pop("tstress", None)
        system["nbnd"] = "TODO_SET_AFTER_SCF"
        ions = None
        cell = None

    pw = PWInput(
        structure,
        pseudo=pseudo,
        control=control,
        system=system,
        electrons=electrons,
        ions=ions,
        cell=cell,
        kpoints_mode="automatic",
        kpoints_grid=kpoints_grid,
        kpoints_shift=(0, 0, 0),
    )
    pw.write_file(path)

    text = path.read_text()
    text = text.replace("'TODO_SET_AFTER_SCF'", "TODO_SET_AFTER_SCF")
    path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_dir", type=Path)
    parser.add_argument("cif", type=Path)
    args = parser.parse_args()

    candidate_dir = args.candidate_dir.resolve()
    name = candidate_name(candidate_dir)
    material = MATERIALS[name]

    cif = args.cif
    if not cif.is_absolute():
        cif = candidate_dir / cif
    if not cif.exists():
        raise SystemExit(f"CIF not found: {cif}")

    structure = Structure.from_file(cif)

    qe_dir = candidate_dir / "qe"
    (qe_dir / "00_relax").mkdir(parents=True, exist_ok=True)
    (qe_dir / "01_scf").mkdir(parents=True, exist_ok=True)
    (qe_dir / "02_nscf").mkdir(parents=True, exist_ok=True)

    write_pw_input(
        structure,
        qe_dir / "00_relax" / f"{name}.relax.in",
        material["prefix"],
        material["pseudo"],
        "vc-relax",
        material["ecutwfc"],
        material["ecutrho"],
        (4, 4, 4),
    )
    write_pw_input(
        structure,
        qe_dir / "01_scf" / f"{name}.scf.in",
        material["prefix"],
        material["pseudo"],
        "scf",
        material["ecutwfc"],
        material["ecutrho"],
        (6, 6, 6),
    )
    write_pw_input(
        structure,
        qe_dir / "02_nscf" / f"{name}.nscf.in",
        material["prefix"],
        material["pseudo"],
        "nscf",
        material["ecutwfc"],
        material["ecutrho"],
        (12, 12, 12),
    )

    print(f"Generated QE starter inputs for {name}")
    print(f"Source CIF: {cif}")
    print("Review k-point meshes, nbnd, magnetism, SOC, and convergence before running.")


if __name__ == "__main__":
    main()

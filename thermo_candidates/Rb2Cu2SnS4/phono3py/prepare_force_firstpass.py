#!/usr/bin/env python3
"""Prepare immutable pilot or production QE force inputs for one Rb dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_generated(path: Path) -> tuple[int, str]:
    text = path.read_text(errors="strict")
    header = re.search(r"^!\s*ibrav\s*=\s*0,\s*nat\s*=\s*(\d+),\s*ntyp\s*=\s*4\s*$", text, re.MULTILINE)
    if not header:
        raise ValueError(f"unexpected generated QE header in {path}")
    nat = int(header.group(1))
    lines = text.splitlines()
    try:
        cell_index = next(i for i, line in enumerate(lines) if line.strip() == "CELL_PARAMETERS bohr")
        species_index = next(i for i, line in enumerate(lines) if line.strip() == "ATOMIC_SPECIES")
        positions_index = next(i for i, line in enumerate(lines) if line.strip() == "ATOMIC_POSITIONS crystal")
    except StopIteration as exc:
        raise ValueError(f"incomplete generated QE structure in {path}") from exc
    cell_lines = lines[cell_index:cell_index + 4]
    species_lines = lines[species_index:species_index + 5]
    position_lines = lines[positions_index:positions_index + nat + 1]
    if len(cell_lines) != 4 or len(species_lines) != 5 or len(position_lines) != nat + 1:
        raise ValueError(f"truncated generated QE structure in {path}")
    structure = "\n".join(cell_lines + species_lines + position_lines) + "\n"
    return nat, structure


def qe_input(
    generated: Path,
    *,
    pseudo_dir: Path,
    prefix: str,
    kmesh: tuple[int, int, int],
    ecutwfc: int,
    ecutrho: int,
    tstress: bool,
) -> tuple[int, str]:
    nat, structure = parse_generated(generated)
    return nat, f"""&CONTROL
  calculation = 'scf',
  disk_io = 'none',
  outdir = './tmp',
  prefix = '{prefix}',
  pseudo_dir = '{pseudo_dir.resolve(strict=True)}',
  restart_mode = 'from_scratch',
  verbosity = 'high',
  tprnfor = .true.,
  tstress = {'.true.' if tstress else '.false.'},
/
&SYSTEM
  ecutrho = {ecutrho},
  ecutwfc = {ecutwfc},
  occupations = 'fixed',
  ibrav = 0,
  nat = {nat},
  ntyp = 4,
  nosym = .true.,
  noinv = .true.,
/
&ELECTRONS
  conv_thr = 1.000000000000d-10,
  diagonalization = 'david',
  electron_maxstep = 300,
  mixing_beta = 0.3,
  startingpot = 'atomic',
  startingwfc = 'atomic+random',
  scf_must_converge = .true.,
/
{structure}K_POINTS automatic
  {kmesh[0]} {kmesh[1]} {kmesh[2]} 0 0 0
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pseudo-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("pilot", "production"), required=True)
    parser.add_argument("--kmesh", nargs=3, type=int, default=(2, 2, 2))
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to reuse {args.output_dir}")
    args.output_dir.mkdir(parents=True)

    pristine = args.dataset_dir / "supercell.in"
    displaced = sorted(args.dataset_dir.glob("supercell-[0-9][0-9][0-9][0-9][0-9].in"))
    if not pristine.is_file() or not displaced:
        raise FileNotFoundError("selected dataset lacks pristine or displaced supercells")
    if args.mode == "pilot":
        specifications = [
            ("pristine_k222_hi", pristine, (2, 2, 2), 100, 800),
            ("disp00001_k222_hi", displaced[0], (2, 2, 2), 100, 800),
            ("disp00001_k222_hi_dup", displaced[0], (2, 2, 2), 100, 800),
            ("pristine_k333_hi", pristine, (3, 3, 3), 100, 800),
            ("disp00001_k333_hi", displaced[0], (3, 3, 3), 100, 800),
            ("pristine_k222_lo", pristine, (2, 2, 2), 80, 640),
            ("disp00001_k222_lo", displaced[0], (2, 2, 2), 80, 640),
        ]
    else:
        selected_kmesh = tuple(args.kmesh)
        if len(selected_kmesh) != 3 or any(value <= 0 for value in selected_kmesh):
            raise ValueError("production k mesh must contain three positive integers")
        specifications = [("pristine", pristine, selected_kmesh, 100, 800)]
        specifications.extend(
            (source.stem.replace("supercell-", "disp"), source, selected_kmesh, 100, 800)
            for source in displaced
        )

    records: list[dict[str, object]] = []
    rows = ["task_index\tlabel\tinput_path\tinput_sha256\texpected_atoms"]
    for task_index, (label, source, kmesh, ecutwfc, ecutrho) in enumerate(specifications):
        task_dir = args.output_dir / f"task-{task_index:05d}-{label}"
        task_dir.mkdir()
        input_path = task_dir / "scf.in"
        nat, content = qe_input(
            source,
            pseudo_dir=args.pseudo_dir,
            prefix=f"rb_{args.mode}_{task_index:05d}",
            kmesh=kmesh,
            ecutwfc=ecutwfc,
            ecutrho=ecutrho,
            tstress=args.mode == "pilot",
        )
        input_path.write_text(content)
        input_hash = sha256(input_path)
        rows.append(f"{task_index}\t{label}\t{input_path.resolve()}\t{input_hash}\t{nat}")
        records.append({
            "task_index": task_index,
            "label": label,
            "source": str(source.resolve()),
            "source_sha256": sha256(source),
            "input": str(input_path.resolve()),
            "input_sha256": input_hash,
            "expected_atoms": nat,
            "kmesh": list(kmesh),
            "ecutwfc_Ry": ecutwfc,
            "ecutrho_Ry": ecutrho,
            "conv_thr_Ry": 1e-10,
            "nosym": True,
            "noinv": True,
            "tstress": args.mode == "pilot",
        })
    (args.output_dir / "task_map.tsv").write_text("\n".join(rows) + "\n")
    manifest = {
        "document_type": f"rb_firstpass_{args.mode}_force_manifest",
        "dataset": str((args.dataset_dir / "phono3py_disp.yaml").resolve()),
        "dataset_sha256": sha256(args.dataset_dir / "phono3py_disp.yaml"),
        "pseudopotential_sha256": {
            path.name: sha256(path) for path in sorted(args.pseudo_dir.glob("*.upf"))
        },
        "task_count": len(records),
        "tasks": records,
    }
    (args.output_dir / "force_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

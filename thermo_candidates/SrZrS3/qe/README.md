# Quantum ESPRESSO: SrZrS3

Use this folder for QE relax, SCF, dense NSCF, and convergence tests.

The templates in `00_relax`, `01_scf`, and `02_nscf` are not production inputs
because they intentionally do not contain fake lattice vectors or atomic
coordinates. After adding `structures/SrZrS3.cif`, generate real starter inputs
with:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python thermo_candidates/scripts/make_qe_inputs.py thermo_candidates/SrZrS3 structures/SrZrS3.cif
```

Starting SSSP cutoffs:

```text
ecutwfc = 40 Ry
ecutrho = 320 Ry
```

These are starting values only. Run convergence tests before using production
results.


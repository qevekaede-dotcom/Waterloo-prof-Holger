# Quantum ESPRESSO: Rb2Cu2SnS4

Use this folder for QE relax, SCF, dense NSCF, and convergence tests.

The templates in `00_relax`, `01_scf`, and `02_nscf` are not production inputs
because they intentionally do not contain fake lattice vectors or atomic
coordinates. After adding `structures/Rb2Cu2SnS4.cif`, generate real starter
inputs with:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python thermo_candidates/scripts/make_qe_inputs.py thermo_candidates/Rb2Cu2SnS4 structures/Rb2Cu2SnS4.cif
```

Starting SSSP cutoffs:

```text
ecutwfc = 90 Ry
ecutrho = 720 Ry
```

These are starting values only. Run convergence tests before using production
results.


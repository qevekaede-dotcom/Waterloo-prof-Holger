# Quantum ESPRESSO: Rb2Cu2SnS4

Use this folder for QE relax, SCF, dense NSCF, and convergence tests.

The `.in` files in `00_relax`, `01_scf`, and `02_nscf` are the archived inputs
for the completed first pass. The old `.in.template` placeholders were removed;
they contained no usable lattice or atomic coordinates. Preserve the actual
inputs and the evidence in `convergence/` and `../logs/`.

For a fresh calculation workspace, `thermo_candidates/scripts/make_qe_inputs.py`
can generate starter inputs from a CIF. Run it only in a fresh workspace: it
writes `.in` files directly and would overwrite this completed calculation's
inputs. Starter settings still require this material's own convergence tests.

## Selected Parameters

This material's completed convergence tests selected the cutoffs and SCF
meshes below. The dense NSCF settings are recorded in the archived NSCF input:

```text
ecutwfc = 90 Ry
ecutrho = 720 Ry
vc-relax k mesh = 2 x 4 x 4
final SCF k mesh = 3 x 5 x 5
dense NSCF k mesh = 8 x 14 x 14
dense NSCF bands = 105
```

These settings belong to Rb2Cu2SnS4. Dense-mesh transport-property convergence
remains to be checked; the completed first pass is scalar-relativistic PBE
without explicit SOC.

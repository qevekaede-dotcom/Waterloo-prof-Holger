# Quantum ESPRESSO: SrZrS3

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
ecutwfc = 50 Ry
ecutrho = 400 Ry
vc-relax k mesh = 6 x 3 x 2
final SCF k mesh = 8 x 4 x 2
dense NSCF k mesh = 20 x 10 x 6
dense NSCF bands = 108
```

These settings belong to the experimentally observed mp-558760 polymorph of
SrZrS3. Dense-mesh transport-property convergence remains to be checked; the
completed first pass is scalar-relativistic PBE without explicit SOC.

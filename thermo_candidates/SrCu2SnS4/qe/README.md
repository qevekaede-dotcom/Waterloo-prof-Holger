# Quantum ESPRESSO: SrCu2SnS4

Use this folder for QE relax, SCF, dense NSCF, and convergence tests.

The `.in` files in `00_relax`, `01_scf`, and `02_nscf` are the archived inputs
for the completed first pass. The old `.in.template` placeholders were removed;
they contained no usable lattice or atomic coordinates. Preserve the actual
inputs and the evidence in `convergence/` and `../logs/`.

For a fresh calculation workspace, `thermo_candidates/scripts/make_qe_inputs.py`
can generate starter inputs from a CIF. Run it only in a fresh workspace: it
writes `.in` files directly and would overwrite this completed calculation's
inputs. Starter settings still require this material's own convergence tests.
The commands below document the completed workflow and should be rerun only
in a separate calculation workspace.

## Selected Parameters

The completed tests in `convergence/` selected:

```text
ecutwfc = 90 Ry
ecutrho = 720 Ry
vc-relax k mesh = 4 x 4 x 2
final SCF k mesh = 5 x 5 x 3
```

Prepare and run the variable-cell relaxation with:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python prepare_relax.py
bash run_relax.sh
python extract_relaxed_structure.py
```

After relaxation, prepare and run the final SCF on the relaxed structure:

```bash
python prepare_final_scf.py
bash run_final_scf.sh
```

The final SCF has 210 electrons and 105 occupied bands. Prepare the dense NSCF
with 140 total bands and a `12x12x6` mesh:

```bash
python prepare_nscf.py
bash run_nscf.sh
```

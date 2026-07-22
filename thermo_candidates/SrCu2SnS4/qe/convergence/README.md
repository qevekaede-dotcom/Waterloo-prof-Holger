# SrCu2SnS4 Convergence Tests

Convergence tests vary one numerical parameter while keeping the structure and
all other settings fixed. The cutoff test uses a small `2 2 2` k-point mesh so
that the plane-wave basis can be screened economically.

## Cutoff Test

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python prepare_cutoff_inputs.py
bash run_cutoff_convergence.sh
python summarize_cutoff.py
```

The tested `ecutwfc` values are 50, 60, 70, 80, 90, and 100 Ry. `ecutrho` is
kept at eight times `ecutwfc`, consistent with the SSSP Precision values used
for this mixed PAW/ultrasoft pseudopotential set.

Use the smallest cutoff whose energy differs from the largest test by less than
about 1 meV/atom, while respecting the SSSP recommended cutoff of the hardest
element. For this material Cu sets that recommendation to `90/720 Ry`.

Result: all six calculations completed. At `90 Ry`, the energy differs from the
`100 Ry` reference by `0.1044 meV/atom`. Production calculations therefore use
`ecutwfc = 90 Ry` and `ecutrho = 720 Ry`.

## K-Point Test

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python prepare_kpoint_inputs.py
bash run_kpoint_convergence.sh
python summarize_kpoints.py
```

The meshes account for the long `c` axis of the trigonal cell: `2x2x1`,
`3x3x2`, `4x4x2`, and `5x5x3`. The cutoff remains fixed at `90/720 Ry`.

Result: all four calculations completed. `4x4x2` differs from the `5x5x3`
reference by `0.2532 meV/atom`, so `4x4x2` is used for structural relaxation.
The denser `5x5x3` mesh is retained for the final SCF calculation.

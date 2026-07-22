# SrZrS3 convergence tests

This material's own tests; nothing is reused from SrCu2SnS4 as final settings.

## Cutoff test (stage 1)

- Structure: `structures/SrZrS3.cif` (mp-558760 needle phase, Pnma, 20 atoms).
- Cutoffs: 30, 35, 40, 45, 50, 60 Ry with `ecutrho = 8 x ecutwfc`
  (all three pseudos are ultrasoft; SSSP suggests 40/320 Ry).
- Fixed 4x2x1 mesh, fixed occupations, conv_thr 1e-8, stress printed.
- The 60 Ry run is the reference; acceptance mirrors the SrCu2SnS4 protocol
  (energy within ~0.1-0.3 meV/atom of the reference, pressure stable).

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python prepare_cutoff_inputs.py
bash run_cutoff_convergence.sh      # QE_NP to override MPI ranks (default 4)
python extract_cutoff_results.py    # -> cutoff_results.csv
```

## Cutoff result (stage 1, complete)

`cutoff_results.csv`: 50/400 Ry sits 0.160 meV/atom from the 60 Ry reference
and on the 3.4-3.55 kbar pressure plateau. **Selected: 50/400 Ry** (45 Ry at
0.262 meV/atom would be defensible, but 50 Ry costs the same 84 s per SCF).

## k-point test (stage 2, complete)

At the selected 50/400 Ry, fixed structure, meshes scaled to the
3.84 x 8.59 x 14.00 A cell (short axis gets the most k-points):
`4x2x1`, `6x3x2`, `8x4x2`, `10x5x3` (densest = reference).

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python prepare_kpoint_inputs.py
bash run_kpoint_convergence.sh      # QE_NP to override MPI ranks (default 4)
python extract_kpoint_results.py    # -> kpoint_results.csv
```

Result (`kpoint_results.csv`): 4x2x1 -> 2.885, 6x3x2 -> 0.286,
8x4x2 -> 0.036 meV/atom vs 10x5x3. **Selected: 6x3x2 for vc-relax**
(same ~0.25 meV/atom acceptance band as SrCu2SnS4's relax mesh) and
**8x4x2 for the final SCF**.

## Selected parameters (both stages)

```text
ecutwfc = 50 Ry
ecutrho = 400 Ry
vc-relax k mesh = 6 x 3 x 2
final SCF k mesh = 8 x 4 x 2
```

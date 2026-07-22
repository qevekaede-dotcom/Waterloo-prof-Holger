# Rb2Cu2SnS4 convergence tests

This material's own tests; nothing is reused from other materials as final
settings.

## Cutoff test (stage 1)

- Structure: `structures/Rb2Cu2SnS4.cif` (mp-18006, Ibam, 18-atom primitive
  cell Rb4 Cu4 Sn2 S8).
- Pseudos are mixed: Rb norm-conserving (ONCV), Cu PAW, Sn/S ultrasoft;
  `ecutrho = 8 x ecutwfc` (driven by the PAW/ultrasoft members).
- Cutoffs: 50, 60, 70, 80, 90, 100 Ry (SSSP suggests 90/720, Cu-driven);
  the 100 Ry run is the reference, mirroring the SrCu2SnS4 protocol.
- Fixed 2x4x4 mesh (k-spacing 0.35/0.31/0.32 A^-1 from the reciprocal
  lattice lengths 0.70/1.23/1.26 A^-1), fixed occupations, conv_thr 1e-8,
  stress printed.

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python prepare_cutoff_inputs.py
bash run_cutoff_convergence.sh      # QE_NP to override MPI ranks (default 4)
python extract_cutoff_results.py    # -> cutoff_results.csv
```

## k-point test (stage 2, after the cutoff is chosen)

Prepared only after stage 1 selects the cutoff; the mesh list will be scaled
to the reciprocal-lattice shape (first axis needs about half the k-points of
the other two).

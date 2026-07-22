# SrCu2SnS4: QE DOS vs BoltzTraP2 DOS

This addresses Roy's request to run a DOS with QE and compare it to the
BoltzTraP2 DOS. All values are calculated (QE-PBE, scalar-relativistic).

## Method

- Both DOS use the **same** dense NSCF eigenvalues (`12x12x6`, 100 irreducible
  k-points, 140 bands) already stored in `qe/tmp/final/`. The NSCF was not
  re-run.
- **QE DOS**: `dos.x` on those eigenvalues with Gaussian smearing
  `ngauss=0, degauss=0.005 Ry (0.068 eV)`.
  Raw output: `qe/dos/SrCu2SnS4.dos` (+ `.in`, `.out`).
- **BoltzTraP2 DOS**: computed from the existing `boltztrap2/SrCu2SnS4.bt2`
  (interpolation multiplier 5) via `bandlib.BTPDOS`.
- Both are referenced to the QE Fermi level `E_F = 7.1887 eV`, which equals the
  valence-band maximum for this fixed-occupation insulator.
- For an equal-footing comparison the BoltzTraP2 DOS is also Gaussian-broadened
  to the same 0.068 eV width.

Reproduce with:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python boltztrap2/dos_compare.py
```

## Result

- `E_F` (= VBM): **7.1887 eV**; QE-PBE indirect gap: **0.3445 eV**. Both DOS show
  a clean near-zero DOS across the gap `[0, 0.3445] eV` above `E_F`.
- Electrons integrated below `E_F`: **QE dos.x = 210.0** (all 105 occupied
  bands); **BoltzTraP2 = 124.0** (its loader keeps 62 occupied bands and drops
  the deep semicore states).
- After matching the broadening, agreement within `|E - E_F| < 5 eV`:
  **relative L2 difference = 0.066 (6.6%)**, **Pearson r = 0.9943**.

## Interpretation

Near the Fermi level the two DOS agree closely in both shape and magnitude, and
both reproduce the same ~0.34 eV gap. The differences are methodological, not
physical:

- BoltzTraP2's native DOS is spikier because it evaluates a 5x denser
  interpolated k-mesh; once broadened to the dos.x width it overlays the QE DOS.
- BoltzTraP2 only spans about `E_F +/- 5.6 eV` and omits the deep semicore
  bands, so the two curves diverge at the window edges (this is why the electron
  counts differ). The comparison is meaningful in the near-gap region that
  matters for transport.

## Limitations

- PBE gaps are typically underestimated; `0.3445 eV` is the QE-PBE value, not an
  experimental gap.
- Scalar-relativistic; **no explicit SOC**.
- The QE DOS uses Gaussian smearing on the `12x12x6` grid, not the tetrahedron
  method. A tetrahedron DOS would need a fresh NSCF with `occupations='tetrahedra'`;
  it is not required for this comparison but would sharpen the band edges.

## Files

- `results/dos_qe_vs_boltztrap2.png` — overlay plot (full window + gap zoom).
- `results/dos_qe_vs_boltztrap2.csv` — `E - E_F (eV)`, QE DOS, BoltzTraP2 DOS,
  and broadened BoltzTraP2 DOS, all in states eV^-1 cell^-1.
- `qe/dos/` — raw QE `dos.x` input, output, and DOS file.
- `boltztrap2/dos_compare.py` — analysis script.

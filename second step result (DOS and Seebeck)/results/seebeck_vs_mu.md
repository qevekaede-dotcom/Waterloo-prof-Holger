# SrCu2SnS4: Seebeck coefficient centered on the Fermi energy

This addresses the second request in Roy's email: a graph of the Seebeck
coefficient centered on the Fermi energy. All values are calculated
(QE-PBE + BoltzTraP2, scalar-relativistic).

## Method

- Source data: the existing `boltztrap2/SrCu2SnS4.trace` (`btp2 integrate`
  chemical-potential scan, 300-900 K) from the completed first pass. No new
  QE or BoltzTraP2 runs were needed.
- x-axis: `mu - E_F` with `E_F = 7.1887 eV` (the VBM); the QE-PBE gap
  `[0, 0.3445] eV` is shaded.
- The plotted scalar `S` is the orientational average `(S_xx + S_yy + S_zz)/3`;
  verified against the full tensors in `SrCu2SnS4.condtens`
  (max relative difference 1.2e-5).
- Within the constant-relaxation-time approximation, tau cancels in
  `S = sigma^-1 (integral)`, so unlike `sigma/tau` and `PF/tau` the Seebeck
  coefficient is an absolute calculated quantity here.

Reproduce with:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python boltztrap2/plot_seebeck.py
```

## Result

- Classic bipolar shape: `S > 0` on the p-type side, `S < 0` on the n-type
  side, one sign change inside the gap.
- 300 K extrema on the sampled mu grid within `|mu - E_F| <= 1 eV`:
  `+644 uV/K` at `mu - E_F = +0.151 eV` and `-548 uV/K` at `+0.241 eV`
  (both chemical potentials lie inside the gap, where the material is
  intrinsic; practically doped samples sit closer to the band edges).
- Peak magnitudes shrink with temperature (300 -> 900 K) because minority
  carriers activate across the 0.34 eV PBE gap (bipolar compensation).
- Consistency check with the doped run sent earlier: at 300 K and p-type
  `1e20 cm^-3`, the mu-scan gives `157.4 uV/K` vs `157.2 uV/K` in
  `SrCu2SnS4.dope.trace` - the same value Roy already has in the Excel table.
- Charge neutrality confirmed: the relative carrier count crosses ~0 at
  `mu = E_F` (`+0.018 e/uc` residual, grid interpolation).

## Limitations

- PBE underestimates the gap, so the in-gap peak positions/heights and the
  onset of bipolar decay are tied to the 0.3445 eV PBE value, not the
  experimental gap.
- Scalar-relativistic; no explicit SOC.
- Rigid-band mu scan; real doping may distort the bands.
- Orientational (polycrystalline) average; single-crystal S_xx vs S_zz differ.

## Files

- `results/seebeck_vs_mu.png` - S(mu) at 300-900 K, centered on E_F.
- `results/seebeck_vs_mu.csv` - `mu - E_F (eV)` and S at each temperature
  (uV/K), `|mu - E_F| <= 1.5 eV`.
- `boltztrap2/plot_seebeck.py` - script with the three cross-checks.

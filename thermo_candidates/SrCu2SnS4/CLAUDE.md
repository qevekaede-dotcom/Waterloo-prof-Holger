# SrCu2SnS4 instructions for Claude

Status: the first scalar-relativistic PBE QE + BoltzTraP2 pass is complete.

Key verified facts:

- relaxed symmetry: `P3_121` (No. 152);
- volume: 543.884 to 546.507 A^3 (+0.48%);
- dense NSCF: 12x12x6, 140 bands, 105 occupied bands;
- sampled indirect PBE gap: 0.3445 eV;
- transport grid: 300-900 K and 1e19-1e21 cm^-3 for both carrier signs;
- sampled p-type best `PF/tau` exceeds the n-type best at each temperature;
- first-pass kappa_L [calculated] (phono3py RTA, 2x2x1 supercell,
  cutoff-pair 4.0 A, q-mesh 13x13x6, measured pristine residual forces
  5.5e-4 Ry/bohr subtracted via --cfz, PBE, no SOC, no NAC):
  0.36 W m^-1 K^-1 at 300 K (xx = yy 0.40, zz 0.30), ~1/T down to 0.12
  at 900 K; no imaginary modes; q-mesh ladder met the 3% criterion only
  marginally (2.9%; ladder spread ~0.33-0.38) — always carry the ~5%
  uncertainty with the number.

Preserve `logs/`, `qe/convergence/`, `qe/tmp/final/`, and `boltztrap2/` as the
evidence behind the processed results. Do not call the current transport result
fully converged until transport-property convergence with respect to the dense
k mesh has been checked. Explicit SOC is not included.

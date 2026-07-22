# SrCu2SnS4 instructions for Claude

Status: the first scalar-relativistic PBE QE + BoltzTraP2 pass is complete.

Key verified facts:

- relaxed symmetry: `P3_121` (No. 152);
- volume: 543.884 to 546.507 A^3 (+0.48%);
- dense NSCF: 12x12x6, 140 bands, 105 occupied bands;
- sampled indirect PBE gap: 0.3445 eV;
- transport grid: 300-900 K and 1e19-1e21 cm^-3 for both carrier signs;
- sampled p-type best `PF/tau` exceeds the n-type best at each temperature.

Preserve `logs/`, `qe/convergence/`, `qe/tmp/final/`, and `boltztrap2/` as the
evidence behind the processed results. Do not call the current transport result
fully converged until transport-property convergence with respect to the dense
k mesh has been checked. Explicit SOC is not included.

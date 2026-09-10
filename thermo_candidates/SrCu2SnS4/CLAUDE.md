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
  historical cutoff-pair 4.0 bohr = 2.1167 A (onsite pair groups only),
  q-mesh 13x13x6, measured pristine residual forces 5.5e-4 Ry/bohr
  subtracted via --cfz, PBE, no SOC, no NAC):
  0.36 W m^-1 K^-1 at 300 K (xx = yy 0.40, zz 0.30), ~1/T down to 0.12
  at 900 K; no significant imaginary modes on the sampled mesh. The q-mesh
  ladder met its average-only 3% criterion marginally (last change -2.9559%),
  while zz changed -12.2745%. The earlier ~5% estimate is not a demonstrated
  tensor or total physical uncertainty; supercell/pair-cutoff convergence
  remains unestablished. Preserve frozen sent records, but use this qualified
  interpretation in new writing.
- The archived pristine force block was emitted after SCF convergence and is
  the block actually used by `--cfz`, but the QE run then hit `seqopn(90)` and
  MPI abort. No separate healthy rerun output is preserved. Treat the force
  block as traceable evidence with an unhealthy terminal state, not as a fully
  healthy pristine calculation.

Preserve `logs/`, `qe/convergence/`, `qe/tmp/final/`, and `boltztrap2/` as the
evidence behind the processed results. Do not call the current transport result
fully converged until transport-property convergence with respect to the dense
k mesh has been checked. Explicit SOC is not included.

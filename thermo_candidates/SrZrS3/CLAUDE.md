# SrZrS3 instructions for Claude

Status: the first scalar-relativistic PBE QE + BoltzTraP2 pass is complete.

Key verified facts:

- structure: experimentally observed `mp-558760`; never substitute the
  `mp-5193` polymorph;
- relaxed symmetry kept: `Pnma` (No. 62);
- volume: 461.535 -> 464.463 A^3 (+0.63%);
- converged parameters (this material's own tests): `50/400 Ry`, relax mesh
  `6x3x2`, final SCF mesh `8x4x2`;
- dense NSCF: `20x10x6` (264 irreducible points), 108 bands, 80 occupied;
- sampled PBE gap: `0.6096 eV`;
- transport grid: 300-900 K and 1e19-1e21 cm^-3 for both carrier signs;
- on the sampled grid the n-type best `zT_e` exceeds the p-type best at every
  temperature, while the p-type best `PF/tau` is larger at 500 K and above
  (the 1e21 cm^-3 point). Quote both metrics, never just one.

Preserve `logs/`, `qe/convergence/`, `qe/tmp/final/`, and `boltztrap2/` as the
evidence behind the processed results. Do not call the transport result fully
converged until transport-property convergence with respect to the dense k
mesh has been checked. Explicit SOC is not included. History in `WORKLOG.md`.

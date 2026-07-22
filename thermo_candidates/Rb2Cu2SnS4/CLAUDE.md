# Rb2Cu2SnS4 instructions for Claude

Status: the first scalar-relativistic PBE QE + BoltzTraP2 pass is complete.

Key verified facts:

- structure: experimentally observed `mp-18006` (Ibam primitive cell);
- relaxed symmetry kept: `Ibam` (No. 72);
- volume: 446.410 -> 450.561 A^3 (+0.93%);
- converged parameters (this material's own tests): `90/720 Ry`, relax mesh
  `2x4x4`, final SCF mesh `3x5x5`;
- dense NSCF: `8x14x14` (788 irreducible points), 105 bands, 78 occupied,
  156 electrons;
- sampled PBE gap: `0.7811 eV` (the largest of the three candidates);
- transport grid: 300-900 K and 1e19-1e21 cm^-3 for both carrier signs;
- on the sampled grid, p-type is favored by BOTH `PF/tau` and `zT_e` at every
  temperature (peak sampled `zT_e` 6.419 at 900 K, p-type, 1e21 cm^-3 - an
  electronic-only upper bound, not a real zT).

The BoltzTraP2 template shipped with the same three bugs as SrZrS3's
(qe_source path, bare `btp2` under NumPy 2, half-open/through-zero ranges);
they are fixed in `boltztrap2/run_bt2.sh`.

Preserve `logs/`, `qe/convergence/`, `qe/tmp/final/`, and `boltztrap2/` as the
evidence behind the processed results. Do not call the transport result fully
converged until transport-property convergence with respect to the dense k
mesh has been checked. Explicit SOC is not included. History in `WORKLOG.md`.

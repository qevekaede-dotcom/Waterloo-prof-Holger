# Three-material first-pass comparison

Scalar-relativistic PBE (Quantum ESPRESSO) + BoltzTraP2, one identical pipeline
per material, each with its **own** convergence tests. Values are tagged
[calculated] (this work), [database] (the Materials Project-based renewed list),
or [experimental] (none yet). Every material ran the same transport grid:
300-900 K and +/-1e19 to 1e21 cm^-3 for both carrier signs.

## DFT setup and structure

| Quantity | SrCu2SnS4 | SrZrS3 | Rb2Cu2SnS4 |
|---|---|---|---|
| MP structure id [database] | mp-16988 | mp-558760 | mp-18006 |
| Space group after relaxation [calculated] | P3_121 (No. 152), kept | Pnma (No. 62), kept | Ibam (No. 72), kept |
| Own converged cutoffs (Ry) [calculated] | 90/720 | 50/400 | 90/720 |
| Relax / final-SCF k mesh [calculated] | 4x4x2 / 5x5x3 | 6x3x2 / 8x4x2 | 2x4x4 / 3x5x5 |
| Dense NSCF mesh (irreducible k) [calculated] | 12x12x6 (100) | 20x10x6 (264) | 8x14x14 (788) |
| Bands total / occupied [calculated] | 140 / 105 | 108 / 80 | 105 / 78 |
| Relaxation volume drift [calculated] | +0.48% | +0.63% | +0.93% |

The cutoffs were **not** shared: SrCu2SnS4 and Rb2Cu2SnS4 contain Cu (a hard
pseudopotential -> 90/720 Ry), while SrZrS3 has none and its own test converged
at 50/400 Ry. Each material kept its database symmetry through relaxation with a
small, healthy PBE volume expansion.

## Electronic structure and transport

| Quantity | SrCu2SnS4 | SrZrS3 | Rb2Cu2SnS4 |
|---|---|---|---|
| QE-PBE gap (eV) [calculated] | 0.3445 (indirect) | 0.6096 | 0.7811 |
| Listed gap (eV) [database] | 0.4032 | 0.5512 | 0.8641 |
| Predicted zT [database] | 1.895 | 1.894 | 1.896 |
| Favored carrier by PF/tau [calculated] | p at every T | n at 300-400 K, p at >=500 K | p at every T |
| Favored carrier by zT_e [calculated] | p (n edges ahead at 400-500 K) | n at every T | p at every T |
| Largest sampled PF/tau (W m^-1 K^-2 s^-1) [calculated] | 2.144e11 (900 K, p, 1e21) | 2.981e11 (900 K, p, 1e21) | 1.981e11 (700 K, p, 1e21) |
| Highest sampled zT_e, at its own (T, carrier, density) [calculated] | 1.898 (800 K, p, 5e20) | 1.625 (700 K, n, 1e20) | 6.419 (900 K, p, 1e21) |
| S at 300 K best-PF/tau point (uV/K) [calculated] | +157.2 (p, 1e20) | -134.4 (n, 5e19) | +199.7 (p, 5e20) |

## How to read this, and what it does NOT say

- **The gap ordering is the clearest result**: Rb2Cu2SnS4 (0.7811) > SrZrS3
  (0.6096) > SrCu2SnS4 (0.3445 eV) [calculated], and it tracks the database
  ordering. SrCu2SnS4 and Rb2Cu2SnS4 sit below their listed [database] gaps
  while SrZrS3 sits slightly above (0.6096 vs 0.5512 eV); the listed gaps are
  themselves DFT-derived database values, so only the ordering - not the
  offsets - should be read. None is an experimental gap, and PBE is still
  expected to underestimate the true experimental gaps.
- **Same recipe, different physics**: with the identical transport grid, the
  three prefer different carriers - SrCu2SnS4 and Rb2Cu2SnS4 favor p-type,
  SrZrS3 favors n-type by zT_e (its PF/tau and zT_e even disagree on carrier
  sign, because electronic thermal conductivity grows with the heavy doping
  that maximizes PF/tau). The shared grid is what makes these statements
  comparable.
- **`PF/tau` is not an absolute power factor** - it is scaled by the unknown
  relaxation time tau, so it may be compared *between* these materials only
  under the assumption that tau is similar for them; it is not a device number.
- **`zT_e` is an electronic-only upper bound, not the final zT** - tau cancels
  in it, but it omits the lattice thermal conductivity kappa_L, which will
  lower every value (Rb2Cu2SnS4's larger gap suppresses bipolar conduction,
  which is why its electronic-only zT_e runs high; this is not a real-zT claim
  and the three should not be ranked by zT_e).
- All runs are **scalar-relativistic with no explicit SOC**, rigid-band doped,
  and reported as polycrystalline (orientationally averaged) values. A "best"
  point is the best on the sampled grid, not a continuous optimum.

## What is still needed before any real ranking

A relaxation time tau (for absolute sigma and PF), the lattice thermal
conductivity kappa_L (for the full zT denominator), and ideally a beyond-PBE
gap and SOC check. Until then these are first-pass electronic screens, not
performance predictions.

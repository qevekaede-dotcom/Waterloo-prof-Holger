# Rb2Cu2SnS4 Workflow Summary

## DFT

- Materials Project structure: `mp-18006` (experimentally observed Ibam
  primitive cell)
- QE-relaxed space group: `Ibam` (No. 72)
- Cutoffs: `90/720 Ry` (this material's own convergence test)
- Relaxation k mesh: `2x4x4`
- Final SCF k mesh: `3x5x5`
- Dense NSCF k mesh: `8x14x14` (788 irreducible points)
- Bands: 105 total, 78 occupied
- QE-PBE gap from the sampled grid: `0.7811 eV`

## Best Sampled Power Factor

| T (K) | Type | Density (cm^-3) | S (uV/K) | PF/tau | zT_e |
|---:|:---:|---:|---:|---:|---:|
| 300 | n | 9.99e+18 | -160.6 | 2.067e+10 | 1.324 |
| 300 | p | 5.00e+20 | 199.7 | 1.644e+11 | 3.260 |
| 400 | n | 2.00e+19 | -145.4 | 3.072e+10 | 1.086 |
| 400 | p | 9.99e+20 | 167.8 | 1.819e+11 | 2.754 |
| 500 | n | 2.00e+19 | -171.7 | 4.033e+10 | 1.552 |
| 500 | p | 1.00e+21 | 184.6 | 1.919e+11 | 3.718 |
| 600 | n | 5.00e+19 | -135.6 | 5.176e+10 | 0.922 |
| 600 | p | 1.00e+21 | 199.0 | 1.965e+11 | 4.576 |
| 700 | n | 5.00e+19 | -157.5 | 6.339e+10 | 1.279 |
| 700 | p | 9.99e+20 | 211.7 | 1.981e+11 | 5.318 |
| 800 | n | 1.00e+20 | -137.4 | 7.439e+10 | 0.981 |
| 800 | p | 1.00e+21 | 222.9 | 1.980e+11 | 5.932 |
| 900 | n | 1.00e+20 | -155.6 | 8.555e+10 | 1.340 |
| 900 | p | 1.00e+21 | 232.9 | 1.966e+11 | 6.419 |

`PF/tau` is reported in `W m^-1 K^-2 s^-1`. `zT_e` uses only
electronic thermal conductivity, so it is an upper bound rather than
the full thermoelectric zT. A relaxation time and lattice thermal
conductivity are still required for absolute conductivity and full zT.
No explicit SOC is included. A best point is the best point on the
sampled carrier-density grid, not a continuous optimum.

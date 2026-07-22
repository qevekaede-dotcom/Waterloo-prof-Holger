# SrZrS3 Workflow Summary

## DFT

- Materials Project structure: `mp-558760` (do not confuse with the
  `mp-5193` polymorph)
- QE-relaxed space group: `Pnma` (No. 62)
- Cutoffs: `50/400 Ry` (this material's own convergence test)
- Relaxation k mesh: `6x3x2`
- Final SCF k mesh: `8x4x2`
- Dense NSCF k mesh: `20x10x6` (264 irreducible points)
- Bands: 108 total, 80 occupied
- QE-PBE gap from the sampled grid: `0.6096 eV`

## Best Sampled Power Factor

| T (K) | Type | Density (cm^-3) | S (uV/K) | PF/tau | zT_e |
|---:|:---:|---:|---:|---:|---:|
| 300 | n | 5.00e+19 | -134.4 | 4.080e+10 | 0.894 |
| 300 | p | 5.00e+19 | 133.2 | 3.675e+10 | 0.846 |
| 400 | n | 5.00e+19 | -164.2 | 5.944e+10 | 1.376 |
| 400 | p | 1.00e+20 | 121.7 | 5.444e+10 | 0.695 |
| 500 | n | 1.00e+20 | -138.7 | 7.997e+10 | 0.962 |
| 500 | p | 1.00e+21 | 67.1 | 1.005e+11 | 0.195 |
| 600 | n | 1.00e+20 | -157.5 | 1.004e+11 | 1.286 |
| 600 | p | 1.00e+21 | 83.7 | 1.538e+11 | 0.312 |
| 700 | n | 1.00e+20 | -173.8 | 1.185e+11 | 1.625 |
| 700 | p | 1.00e+21 | 97.7 | 2.061e+11 | 0.442 |
| 800 | n | 2.00e+20 | -136.3 | 1.343e+11 | 1.016 |
| 800 | p | 1.00e+21 | 109.7 | 2.544e+11 | 0.581 |
| 900 | n | 2.00e+20 | -146.8 | 1.515e+11 | 1.226 |
| 900 | p | 1.00e+21 | 120.2 | 2.981e+11 | 0.727 |

`PF/tau` is reported in `W m^-1 K^-2 s^-1`. `zT_e` uses only
electronic thermal conductivity, so it is an upper bound rather than
the full thermoelectric zT. A relaxation time and lattice thermal
conductivity are still required for absolute conductivity and full zT.
No explicit SOC is included. A best point is the best point on the
sampled carrier-density grid, not a continuous optimum.

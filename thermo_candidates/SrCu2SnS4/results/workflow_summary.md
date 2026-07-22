# SrCu2SnS4 Workflow Summary

## DFT

- Materials Project structure: `mp-16988`
- QE-relaxed space group: `P3_121` (No. 152)
- Cutoffs: `90/720 Ry`
- Relaxation k mesh: `4x4x2`
- Final SCF k mesh: `5x5x3`
- Dense NSCF k mesh: `12x12x6` (100 irreducible points)
- Bands: 140 total, 105 occupied
- QE-PBE indirect gap: `0.3445 eV`

## Best Sampled Power Factor

| T (K) | Type | Density (cm^-3) | S (uV/K) | PF/tau | zT_e |
|---:|:---:|---:|---:|---:|---:|
| 300 | n | 5.00e+20 | -27.5 | 1.330e+10 | 0.029 |
| 300 | p | 1.00e+20 | 157.2 | 5.562e+10 | 1.325 |
| 400 | n | 1.00e+19 | -104.1 | 1.777e+10 | 0.514 |
| 400 | p | 5.00e+20 | 103.7 | 8.899e+10 | 0.498 |
| 500 | n | 1.00e+19 | -126.8 | 2.525e+10 | 0.771 |
| 500 | p | 5.00e+20 | 124.5 | 1.220e+11 | 0.769 |
| 600 | n | 2.00e+19 | -112.0 | 3.341e+10 | 0.589 |
| 600 | p | 5.00e+20 | 143.5 | 1.523e+11 | 1.098 |
| 700 | n | 2.00e+19 | -128.2 | 4.213e+10 | 0.785 |
| 700 | p | 5.00e+20 | 161.0 | 1.783e+11 | 1.481 |
| 800 | n | 2.00e+19 | -142.8 | 5.013e+10 | 0.957 |
| 800 | p | 5.00e+20 | 176.7 | 1.991e+11 | 1.898 |
| 900 | n | 5.00e+19 | -112.1 | 5.794e+10 | 0.613 |
| 900 | p | 1.00e+21 | 144.0 | 2.144e+11 | 1.356 |

`PF/tau` is reported in `W m^-1 K^-2 s^-1`. `zT_e` uses only
electronic thermal conductivity, so it is an upper bound rather than
the full thermoelectric zT. A relaxation time and lattice thermal
conductivity are still required for absolute conductivity and full zT.
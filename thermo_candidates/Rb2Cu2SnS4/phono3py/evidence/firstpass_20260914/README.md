# Rb2Cu2SnS4 cost-bounded phonon first pass

Status recorded 2026-09-15 (Asia/Shanghai): force production is running. This
directory contains only curated, lightweight, machine-readable evidence. Raw
QE logs, force sets, force-constant HDF5 files, and kappa HDF5 files remain in
the remote run directory:

`/scratch/yuhansun/phono3py-runs/20260914-rb-fire-full-firstpass/Rb2Cu2SnS4`

## Completed gates

- Full FIRE `21888372`: `COMPLETED/0:0`, normal FIRE convergence in 26 steps,
  terminal maximum force `9.21e-6 Ry/bohr`, total force `3.4e-5 Ry/bohr`,
  18 atoms/order and fixed cell retained, maximum seed displacement
  `0.00185893 A`, Ibam No. 72 at `1e-6 A`.
- Independent pristine `21924016`: `COMPLETED/0:0`, exact FIRE terminal
  geometry, maximum force `8.78e-6 Ry/bohr`, RMS force
  `4.4178e-6 Ry/bohr`, total force `3.2e-5 Ry/bohr`, Ibam retained.
- Count-only preflight `21926309`: `COMPLETED/0:0`; M72/3.70 A generated 679
  displacement supercells and was the only declared candidate below 1000.
- Force pilot `21926602`: all seven tasks `COMPLETED/0:0`. Duplicate RMS was
  `3.26315e-9 Ry/bohr`; k-mesh induced-force RMS/max/relative differences were
  `3.97069e-7 Ry/bohr`, `1.20e-6 Ry/bohr`, and 0.2477%; cutoff differences
  were `5.27542e-7 Ry/bohr`, `1.74e-6 Ry/bohr`, and 0.3290%.

## Running chain

- Production array `21934047`: tasks `0-679%32`, 100/800 Ry, 2x2x2,
  `conv_thr=1e-10 Ry`, fixed occupations, `nosym/noinv`, one pristine plus 679
  displaced 72-atom supercells. Element 361 failed `135:0` on node `c189`
  after all ranks received SIGBUS; its incomplete output is archived under
  `production/failure-21934047_361/` and is not accepted as a force result.
- Recovery `21963653`: only array element 361, with `afterany:21934047`.
- Replacement postprocess `21963654`: `afterok:21963653`; captures authoritative
  accounting, runs the strict QE-output audit, builds FC2/FC3, then executes
  explicit `--nonac` RTA conductivity at 300, 600, and 900 K over the
  material-specific generalized-grid ladder. Original postprocess `21934081`
  remains fail-closed behind `afterok:21934047` and is not reused.

## Key SHA-256 provenance

- FIRE input: `ef034dd76e6ec108fca7668c4315ca48139885114f1d743aada35c6433b12f11`
- FIRE output: `63e501635c67a11d5f43bb0f275f06e7d08cf4f26994ca12a81436fc7bf3e5d5`
- FIRE audit: `ba4dc11d63d6d759a6ad15244f7ee8fc61f250a62418ac49f8c85a5e4d314383`
- pristine input/output/audit: `13741fdee760df7c191132b2465d63692f0c6cc441ef7c17d26f8880c443c0de`,
  `1da3bb00c956a909587687cad54e0402d3359f6afdb764cb752eb6819a2900f3`,
  `b3c307f5d8be9102f06f6a67dcbe0a9516ce03b7e11c861631cf57e29cd08c05`
- selected phono3py YAML: `bb69732c8161dfe57d508777fa85209e6103a07c11df120cb0ac3cc01c02beda`
- pilot audit: `45cd8562df3ace41ab6ce049a5577c4e4aaadb1894b0f29e1090ab4881dbd272`
- production task map: `6e115d64d38a4e7c4e13ad2bafe8e9ae4803cb3eed82c566ee7a559c4afa1797`
- production manifest: `9efff593656ab829485b1e5c805a7885536d70f9406adbbbc83b24d41ece9661`
- failed-attempt SHA manifest:
  `da6db84b5fa574c9029e5567c65c9ab39c594e13e6aaf22629fe4396a3a03f27`
- recovery/replacement-postprocess job ID files:
  `7014c5a917d542c0e2b992bae6b80bd114f0847e8d2c8ddd4943286457a8102a`,
  `21b9492735cead94a7e4155ad1ad8953bc6381faa5008013b05a2ba3da655c8b`

## Scientific scope

Any numerical conductivity produced by this chain is
**first_pass_unconverged**, not a converged intrinsic material property. The
model uses PBE and RTA without SOC, NAC, isotope, or boundary scattering. Only
one 72-atom supercell, one 3.70-A FC3 cutoff, one 0.03-A displacement
amplitude, and a limited force-mesh pilot were run; supercell, cutoff,
amplitude, and 4x4x4 force convergence are absent. Q-grid convergence is
tested separately and cannot repair those upstream limits.

# Rb2Cu2SnS4

Third-priority thermoelectric candidate.

From `background info/Materials renew.csv`:

- renew rank: 1
- predicted zT: 1.896
- band gap: 0.8641 eV

Why this is included:

- top zT candidate in the renewed list
- band gap below 1.0 eV
- avoids Hg, Tl, U, Pb, As, Cd, and Be

Reason it is not first: Rb chemistry may be slightly less convenient than the
Sr-based systems for an initial experimental/computational pass.

Workflow status: complete for the scalar-relativistic PBE first pass.

- structure: experimentally observed `mp-18006`
- relaxed structure: `structures/Rb2Cu2SnS4.relaxed.cif` (symmetry kept `Ibam`)
- converged settings (own tests): 90/720 Ry; relax 2x4x4; final SCF 3x5x5;
  dense NSCF 8x14x14 (788 irreducible points)
- QE-PBE sampled gap: 0.7811 eV (the renewed list gives 0.8641 eV) - the
  largest gap of the three candidates
- raw QE logs: `logs/`; BoltzTraP2 files: `boltztrap2/`; summaries: `results/`

On the sampled grid, p-type doping is favored by both `PF/tau` and `zT_e` at
every temperature. Full zT is not available: the electronic calculation
carries no relaxation time and no lattice thermal conductivity.

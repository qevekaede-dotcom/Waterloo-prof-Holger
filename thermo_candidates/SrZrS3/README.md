# SrZrS3

Second-priority thermoelectric candidate.

From `background info/Materials renew.csv`:

- renew rank: 16
- predicted zT: 1.894
- band gap: 0.5512 eV

Why this is strong:

- simple ternary sulfide chemistry
- band gap below 1.0 eV
- avoids Hg, Tl, U, Pb, As, Cd, and Be
- no rare-earth element

Workflow status: complete for the scalar-relativistic PBE first pass.

- structure: experimentally observed `mp-558760`
- relaxed structure: `structures/SrZrS3.relaxed.cif` (symmetry kept `Pnma`)
- converged settings (own tests): 50/400 Ry; relax 6x3x2; final SCF 8x4x2;
  dense NSCF 20x10x6
- QE-PBE sampled gap: 0.6096 eV (the renewed list gives 0.5512 eV)
- raw QE logs: `logs/`; BoltzTraP2 files: `boltztrap2/`; summaries: `results/`

On the sampled grid the n-type best electronic `zT_e` exceeds the p-type best
at every temperature, while the p-type best `PF/tau` is larger at 500 K and
above. Full zT is not available: the electronic calculation carries no
relaxation time and no lattice thermal conductivity.

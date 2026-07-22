# SrCu2SnS4

First-priority thermoelectric candidate.

From `background info/Materials renew.csv`:

- renew rank: 10/11
- predicted zT: 1.895
- band gap: 0.4032 eV

Why this is first:

- high predicted zT
- band gap below 1.0 eV
- avoids Hg, Tl, U, Pb, As, Cd, and Be
- avoids rare-earth f-electron complications

Workflow status: complete for the scalar-relativistic PBE first pass.

- structure: experimentally observed `mp-16988`
- relaxed structure: `structures/SrCu2SnS4.relaxed.cif`
- QE-PBE indirect gap: 0.3445 eV
- raw QE logs: `logs/`
- BoltzTraP2 files: `boltztrap2/`
- readable summary and CSV tables: `results/`

The sampled transport results favor p-type doping by power factor. Full zT is
not yet available because relaxation time and lattice thermal conductivity are
not part of this electronic BoltzTraP2 calculation.

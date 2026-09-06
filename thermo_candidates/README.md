# Thermoelectric Candidate Workspace

This workspace contains the three first-priority candidates selected from
`background info/Materials renew.csv` after applying Roy's current screening
rules.

## Current Selection

| Priority | Candidate | renew rank | predicted zT | Band gap (eV) | Reason |
| ---: | --- | ---: | ---: | ---: | --- |
| 1 | SrCu2SnS4 | 10/11 | 1.895 | 0.4032 | Cleanest practical first target |
| 2 | SrZrS3 | 16 | 1.894 | 0.5512 | Simple chemistry and no flagged elements |
| 3 | Rb2Cu2SnS4 | 1 | 1.896 | 0.8641 | Highest zT in the renewed list |

All three satisfy:

- band gap below 1.0 eV
- high predicted zT in the renewed Materials Project-filtered list
- no Hg, Tl, U, Pb, As, Cd, or Be

## Directory Rule

Each candidate folder follows the same layout:

```text
Candidate/
  candidate.yml          # data copied from Materials renew.csv
  README.md              # what this material is and what to do next
  structures/            # put CIF or Materials Project structure files here
  qe/                    # archived Quantum ESPRESSO inputs and run helpers
  boltztrap2/            # BoltzTraP2 command notes and run helper
  notes/                 # selection notes and provenance
  results/               # processed plots/tables/summaries
  logs/                  # run logs
```

## Current Structures

Trusted Materials Project CIF files are already present at:

```text
SrCu2SnS4/structures/SrCu2SnS4.cif
SrZrS3/structures/SrZrS3.cif
Rb2Cu2SnS4/structures/Rb2Cu2SnS4.cif
```

All three first-pass workflows are complete; each of SrZrS3 and Rb2Cu2SnS4 ran
its own convergence tests rather than copying SrCu2SnS4's parameters (own
cutoffs 50/400 and 90/720 Ry; sampled PBE gaps 0.6096 and 0.7811 eV). The
shared input generator `scripts/make_qe_inputs.py` is for a separate, fresh
workspace only. Do not run it over these completed material folders: the
actual `.in` files are archived research records, not disposable templates.

## Project Status

Completed:

- reviewed the renewed candidate list
- selected a few crystals worth looking into
- kept the band gap target below 1.0 eV
- avoided the most problematic elements for the first pass
- prepared clean QE and BoltzTraP2 workspaces for the top three
- completed independent first-pass QE + BoltzTraP2 workflows for all three
- sent the original SrCu2SnS4, DOS/Seebeck, and three-material packages
- completed the SrCu2SnS4 first-pass phono3py campaign on DRAC/Nibi
- sent its interim kappa_L CSV and figure; kept those attachments frozen

Next research work (not yet performed):

- SrZrS3, then Rb2Cu2SnS4 phonon campaigns with independent force convergence
- complete the three-material phonon writeup/package
- establish stronger kappa_L and transport-property convergence before
  treating first-pass values as converged predictions
- choose an explicit electronic relaxation-time model before computing full zT

Current status and open issues: [HANDOFF.md](../HANDOFF.md).

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
  qe/                    # Quantum ESPRESSO templates and run helper
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
shared input generator can be used when a fresh set of inputs is needed:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python thermo_candidates/scripts/make_qe_inputs.py thermo_candidates/SrCu2SnS4 structures/SrCu2SnS4.cif
```

Replace the material path and CIF filename as needed.

## Project Status

Completed:

- reviewed the renewed candidate list
- selected a few crystals worth looking into
- kept the band gap target below 1.0 eV
- avoided the most problematic elements for the first pass
- prepared clean QE and BoltzTraP2 workspaces for the top three
- completed the first-pass QE + BoltzTraP2 workflow for SrCu2SnS4
- sent the SrCu2SnS4 progress package to Roy

Still required for SrZrS3 and Rb2Cu2SnS4:

- run material-specific cutoff and k-point convergence tests
- run QE vc-relax, final SCF, and dense NSCF
- run BoltzTraP2 from each dense NSCF output
- verify transport-property convergence and document all limitations

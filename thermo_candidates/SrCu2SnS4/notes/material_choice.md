# Material Choice: SrCu2SnS4

SrCu2SnS4 is the recommended first material to calculate.

From `Materials renew.csv`:

- predicted zT: 1.895
- band gap: 0.4032 eV
- renewed list rank: 10/11 because the same entry appears twice

Screening logic:

- satisfies band gap < 1.0 eV
- avoids Hg, Tl, U, Pb, As, Cd, and Be
- avoids rare-earth f-electron complications
- uses a relatively understandable Sr-Cu-Sn-S chemistry

Immediate next action:

1. Confirm `Experimentally Observed = Yes` on Materials Project.
2. Save the CIF as `structures/SrCu2SnS4.cif`.
3. Generate QE files:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python thermo_candidates/scripts/make_qe_inputs.py thermo_candidates/SrCu2SnS4 structures/SrCu2SnS4.cif
```


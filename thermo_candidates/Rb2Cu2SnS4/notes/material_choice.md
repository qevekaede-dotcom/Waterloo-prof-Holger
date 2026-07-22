# Material Choice: Rb2Cu2SnS4

Rb2Cu2SnS4 is the recommended third material to calculate.

From `Materials renew.csv`:

- predicted zT: 1.896
- band gap: 0.8641 eV
- renewed list rank: 1

Screening logic:

- highest predicted zT in the renewed list
- satisfies band gap < 1.0 eV
- avoids Hg, Tl, U, Pb, As, Cd, and Be
- chemically similar to SrCu2SnS4 through the Cu-Sn-S framework

Practical note:

Rb chemistry may be less convenient than Sr chemistry, so this is kept behind
SrCu2SnS4 and SrZrS3 despite the slightly higher predicted zT.

Immediate next action:

1. Confirm `Experimentally Observed = Yes` on Materials Project.
2. Save the CIF as `structures/Rb2Cu2SnS4.cif`.
3. Generate QE files:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python thermo_candidates/scripts/make_qe_inputs.py thermo_candidates/Rb2Cu2SnS4 structures/Rb2Cu2SnS4.cif
```


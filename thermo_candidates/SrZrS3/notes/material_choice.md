# Material Choice: SrZrS3

SrZrS3 is the recommended second material to calculate.

From `Materials renew.csv`:

- predicted zT: 1.894
- band gap: 0.5512 eV
- renewed list rank: 16

Screening logic:

- satisfies band gap < 1.0 eV
- avoids Hg, Tl, U, Pb, As, Cd, and Be
- simple ternary sulfide
- no rare-earth element

Immediate next action:

1. Confirm `Experimentally Observed = Yes` on Materials Project.
2. Save the CIF as `structures/SrZrS3.cif`.
3. Generate QE files:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
python thermo_candidates/scripts/make_qe_inputs.py thermo_candidates/SrZrS3 structures/SrZrS3.cif
```


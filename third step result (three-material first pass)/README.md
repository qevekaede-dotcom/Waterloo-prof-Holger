# Third step: three-material first-pass report

Curated submission package reporting the completed first scalar-relativistic PBE
pass for all three candidates, after Roy's "good to proceed to the other
crystals' convergence" note. Mirrors the layout of
`first step result (submission_to_roy)/` and
`second step result (DOS and Seebeck)/`.

## Status

- All three first-pass workflows complete: SrCu2SnS4, SrZrS3, Rb2Cu2SnS4.
- This package: comparison table + figures + relaxed structures + combined
  transport table.
- Send plan: **one combined email, two attachment folders** - Folder 1 = the
  DOS+Seebeck package's `READY_TO_ATTACH/`, Folder 2 = this package's
  `READY_TO_ATTACH/`. The combined draft lives here in `EMAIL_DRAFT.md` (the
  second-step draft is marked superseded). The experimental-vs-computational
  answer is filled in from the user's own words. **Sent; Roy replied
  approving the work and the computational focus. Both READY_TO_ATTACH
  folders are frozen.**

## Contents

```text
README.md            - this file
EMAIL_DRAFT.md       - staged reply to Roy (first person; not yet sent)
ATTACHMENTS.md       - the eleven Folder-2 files + the two-folder send plan
CLAUDE.md            - rules for this package
WORKLOG.md           - how this package was assembled
READY_TO_ATTACH/     - the staged attachments ("Folder 2" of the email)
  three_material_comparison.md
  three_material_comparison.csv
  three_material_transport_comparison.png   (PF/tau + zT_e vs T, 2 panels)
  three_material_transport_best_power_factor.csv
  SrZrS3_Seebeck_vs_mu.png / .csv           (same format as the SrCu2SnS4 one)
  Rb2Cu2SnS4_Seebeck_vs_mu.png / .csv
  SrCu2SnS4.relaxed.cif
  SrZrS3.relaxed.cif
  Rb2Cu2SnS4.relaxed.cif
reproducibility/     - how to regenerate the comparison
results/             - working copies: comparison table + transport figure
```

## Authoritative records

Curated copy for presentation. The authoritative per-material records (QE
inputs/outputs, convergence CSVs, BoltzTraP2 traces, transport summaries) stay
under `thermo_candidates/<material>/` and were not modified.

## Headline

QE-PBE gaps [calculated]: SrCu2SnS4 0.3445 eV < SrZrS3 0.6096 eV <
Rb2Cu2SnS4 0.7811 eV - the same ordering as the listed [database] gaps
(SrCu2SnS4 and Rb2Cu2SnS4 below theirs, SrZrS3 slightly above; read the
ordering, not the offsets - the listed gaps are DFT-derived, not experimental).
On the shared sampled grid SrCu2SnS4 and Rb2Cu2SnS4 favor p-type; SrZrS3
favors n-type by electronic zT. PF/tau is not an absolute power factor and
zT_e is an electronic-only upper bound - full zT still needs a relaxation time
and lattice thermal conductivity, and no run includes SOC. See
`READY_TO_ATTACH/three_material_comparison.md` for the full table and caveats.

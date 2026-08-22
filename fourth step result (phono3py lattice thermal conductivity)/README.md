# Fourth step: phono3py lattice thermal conductivity (SrCu2SnS4)

Curated submission package for the phonon task Roy assigned after approving
the three-material report: get phono3py working (he could not), compute the
lattice thermal conductivity kappa_L, and write up how it was done. Mirrors
the layout of the earlier step-result packages.

## Status

- The SrCu2SnS4 campaign is COMPLETE: 168 force calculations on Nibi
  (DRAC), force constants, q-mesh ladder, kappa_L(300-900 K). All raw
  records are archived in `thermo_candidates/SrCu2SnS4/phono3py/`.
- This package: kappa_L table + figure + settings summary + the
  "how we got it working" write-up, staged in `READY_TO_ATTACH/`.
- The pristine residual-force check is CLOSED: max residual 5.5e-4
  Ry/bohr (above the 1e-4 guideline), measured and then SUBTRACTED from
  all displaced-cell forces via phono3py `--cfz`; the correction moved
  kappa_L by < 0.1% at fixed mesh.
- **NOT yet sent.** Only remaining step: the user reviews
  `EMAIL_DRAFT.md` and sends. Freeze `READY_TO_ATTACH/` on send.

## Contents

```text
README.md            - this file
EMAIL_DRAFT.md       - staged reply to Roy (first person; not yet sent)
ATTACHMENTS.md       - the four attachment files + send plan
CLAUDE.md            - rules for this package
WORKLOG.md           - the full campaign lab notebook (five sessions,
                       including every failed attempt)
READY_TO_ATTACH/     - the staged attachments
  HOW_WE_GOT_PHONO3PY_WORKING.md      (the write-up Roy asked for)
  SrCu2SnS4_kappa_L_first_pass.csv    (kappa_L tensor vs T, W m^-1 K^-1)
  SrCu2SnS4_kappa_L_vs_T.png          (figure)
  SrCu2SnS4_kappa_L_summary.md        (settings + checks, from stage 2)
reproducibility/     - exact campaign scripts (SLURM port included) +
                       plot_kappa.py to regenerate the figure
results/             - working copies of the table and figure
```

## Authoritative records

Curated copies for presentation. The authoritative records stay in
`thermo_candidates/SrCu2SnS4/` (raw scf outputs, slurm logs, evidence
snapshots, phono3py HDF5, `results/kappa_L_*`) and were not modified.
The campaign history, with every failure, is `WORKLOG.md` here.

## Headline

SrCu2SnS4 kappa_L [calculated, first pass]: **0.36 W m^-1 K^-1 at 300 K**
(in-plane 0.40, c-axis 0.30), falling ~1/T to 0.12 W m^-1 K^-1 at 900 K.
Very low — encouraging for a thermoelectric. Method: phono3py RTA, 2x2x1
supercell, cutoff-pair 4.0 A, q-mesh 13x13x6, measured residual forces
subtracted (--cfz), PBE, no SOC, no NAC. No imaginary phonon frequencies.
Honest caveats: the q-mesh ladder met the 3% criterion only marginally
(2.9%; ladder spread ~0.33-0.38, so ~5% is quoted as the uncertainty),
and kappa_L alone does not give a full zT (the electronic side still has
an unknown relaxation time tau).

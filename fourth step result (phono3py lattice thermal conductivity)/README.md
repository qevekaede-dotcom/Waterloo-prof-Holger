# Fourth step: phono3py lattice thermal conductivity (SrCu2SnS4)

Curated submission package for the phonon task Roy assigned after approving
the three-material report: get phono3py working (he could not), compute the
lattice thermal conductivity kappa_L, and write up how it was done. Mirrors
the layout of the earlier step-result packages.

## Status

- The SrCu2SnS4 run is preserved as a **historical first pass**, not a
  current-contract completed result. Its 4.0 cutoff was 4.0 bohr (2.1167 A),
  not 4 A, and all included pair groups were onsite. Fourteen of 168 force
  outputs fail the current terminal-health gate, and the settings are mixed.
- SrZrS3 completed 788 force tasks and FC2/FC3 integrity checks, but its
  explicit non-NAC 12x5x3 frequency gate found a -1.0716 THz minimum and
  rejected the finite conductivity tensor. It has no valid kappa_L.
- Rb2Cu2SnS4 passed FIRE, pristine, preflight, and pilot gates. One remaining
  failed production element is in narrow recovery; no FC2/FC3 or kappa_L has
  yet passed.
- The historical pristine residual-force block (max 5.5e-4 Ry/bohr) was
  actually subtracted via `--cfz`, but its QE run later hit `seqopn(90)` and
  MPI abort. Its provenance is traceable; its terminal state is unhealthy.
- **An INTERIM progress email WAS SENT to Roy** (kappa_L numbers + a
  short trap list; `EMAIL_DRAFT.md` is the sent text and
  `READY_TO_ATTACH/` is FROZEN with exactly the two sent attachments).
- **The package as a whole is IN PROGRESS**: the full "how we got it
  working" write-up (staged draft at the package root) and the
  reproducibility bundle ship with the COMPLETE package once the SrZrS3
  and Rb2Cu2SnS4 phonon campaigns are done.

## Contents

```text
README.md            - this file
EMAIL_DRAFT.md       - the interim email SENT to Roy (frozen record)
EMAIL_DRAFT_full_package_unsent.md - superseded fuller draft (reference)
HOW_WE_GOT_PHONO3PY_WORKING.md - STAGED DRAFT of the full write-up
                       (ships with the final three-material package)
ATTACHMENTS.md       - the two sent attachments (frozen record)
CLAUDE.md            - rules for this package
WORKLOG.md           - the full campaign lab notebook (all sessions from
                       both parallel tracks + reconciliation note)
READY_TO_ATTACH/     - FROZEN: exactly the two files that were sent
  SrCu2SnS4_kappa_L_first_pass.csv    (kappa_L tensor vs T, W m^-1 K^-1)
  SrCu2SnS4_kappa_L_first_pass.png    (figure that was sent)
reproducibility/     - exact campaign scripts (SLURM port included) +
                       plot_kappa.py (alternative figure)
results/             - working copies: table, figures, stage-2 summary
```

## Authoritative records

Curated copies for presentation. The authoritative records stay in
`thermo_candidates/SrCu2SnS4/` (raw scf outputs, slurm logs, evidence
snapshots, phono3py HDF5, `results/kappa_L_*`) and were not modified.
The campaign history, with every failure, is `WORKLOG.md` here.

## Headline

SrCu2SnS4 historical kappa_L record [calculated, unconverged first pass]:
**0.36 W m^-1 K^-1 at 300 K**
(in-plane 0.40, c-axis 0.30), falling ~1/T to 0.12 W m^-1 K^-1 at 900 K.
Very low — encouraging for a thermoelectric. Method: phono3py RTA, 2x2x1
supercell, historical cutoff-pair 4.0 bohr (2.1167 A; onsite pair groups
only), q-mesh 13x13x6, measured residual forces
subtracted (--cfz), PBE, no SOC, no NAC. No significant imaginary phonon
frequencies occur on the sampled mesh; this is not a global stability proof.
The corrected 11x11x5 -> 13x13x6 step changes the average by -2.9559%,
just meeting the average-only 3% stopping criterion, while kappa_zz changes
by -12.2745%. The historical ~5% estimate is not a demonstrated tensor or
total physical uncertainty. Further q-mesh, supercell, and pair-cutoff
convergence checks remain. kappa_L alone does not give a full zT: the
electronic side still has an unknown relaxation time tau.

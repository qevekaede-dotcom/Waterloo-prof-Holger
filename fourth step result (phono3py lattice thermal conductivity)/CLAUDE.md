# Rules for this result package

Curated fourth-step deliverable: SrCu2SnS4 lattice thermal conductivity +
the phono3py "how we got it working" write-up for Roy.

- `READY_TO_ATTACH/` is NOT yet frozen: the email has not been sent. The
  only remaining step before sending is user approval of
  `EMAIL_DRAFT.md` (the pristine check is closed: residual measured at
  5.5e-4 Ry/bohr and subtracted via --cfz). Freeze on send, as in the
  earlier packages.
- The authoritative raw/derived records live in
  `thermo_candidates/SrCu2SnS4/` (phono3py/ and results/); copies here are
  read-only snapshots. If a number changes upstream, regenerate here
  (`reproducibility/plot_kappa.py` for the figure) rather than editing the
  copy.
- `WORKLOG.md` is append-only history. Add dated entries; never rewrite.
- Do not add large raw files (FORCES_FC3, HDF5, full scf outputs).
- No dates in any file that might be sent to Roy; dates belong in the log.
- Keep units in every data-column header.
- Scientific rules apply unchanged: kappa_L is a first-pass RTA value with
  its q-mesh caveat; it must never be combined with PF/tau into an
  "absolute zT" while tau is unknown; no SOC, no NAC — say so.

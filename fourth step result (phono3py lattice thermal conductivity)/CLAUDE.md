# Rules for this result package

Fourth-step deliverable: phono3py lattice thermal conductivity (Roy's task:
get phono3py running + "how we got it working" writeup). Built from the
authoritative records in `thermo_candidates/SrCu2SnS4/phono3py/` and
`thermo_candidates/SrCu2SnS4/results/`.

- Package status: IN PROGRESS. Only SrCu2SnS4 is done (first pass); SrZrS3
  and Rb2Cu2SnS4 phonon campaigns have not started; the full writeup and
  reproducibility bundle are still to be assembled here.
- `EMAIL_DRAFT.md` is the INTERIM progress email (SrCu2SnS4 kappa_L +
  short trap list). `READY_TO_ATTACH/` is NOT yet frozen — freeze it the
  moment the email is sent, matching the earlier packages.
- Sending happens from the uwaterloo mailbox (where the Roy thread lives),
  not the personal Gmail.
- The authoritative raw/derived records live in the material workspace;
  treat copies here as read-only snapshots. If a number changes upstream,
  regenerate here rather than editing the copy.
- `WORKLOG.md` is append-only history. Add dated entries; do not rewrite
  past ones.
- Do not add large raw files (FORCES_FC3, `.hdf5`, slurm logs, wavefunctions).
- No dates in any file that might be sent to Roy; dates belong only in the log.
- Keep units in every data-column header.

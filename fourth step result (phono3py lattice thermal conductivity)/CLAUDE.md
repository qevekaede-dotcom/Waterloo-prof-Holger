# Rules for this result package

Fourth-step deliverable: phono3py lattice thermal conductivity (Roy's task:
get phono3py running + "how we got it working" writeup). Built from the
authoritative records in `thermo_candidates/SrCu2SnS4/phono3py/` and
`thermo_candidates/SrCu2SnS4/results/`.

- Package status: IN PROGRESS. Only SrCu2SnS4 is done (first pass); SrZrS3
  and Rb2Cu2SnS4 phonon campaigns have not started; the full writeup and
  reproducibility bundle are still to be assembled here.
- `EMAIL_DRAFT.md` is the INTERIM progress email (SrCu2SnS4 kappa_L +
  short trap list). **The interim email WAS SENT (from the uwaterloo
  mailbox); `READY_TO_ATTACH/` is now frozen** — it records exactly the two
  attachments that were sent; do not edit it. The draft body was sent with
  a personal P.S. added at send time that is deliberately not recorded
  here. Any future attachments go in new files or the final full package.
- The authoritative raw/derived records live in the material workspace;
  treat copies here as read-only snapshots. If a number changes upstream,
  regenerate here rather than editing the copy.
- `WORKLOG.md` is append-only history. Add dated entries; do not rewrite
  past ones.
- Do not add large raw files (FORCES_FC3, `.hdf5`, slurm logs, wavefunctions).
- No dates in any file that might be sent to Roy; dates belong only in the log.
- Keep units in every data-column header.

Post-reconciliation additions (2026-08-27, two parallel sessions merged —
see WORKLOG reconciliation note):

- `HOW_WE_GOT_PHONO3PY_WORKING.md` (package root) is the STAGED DRAFT of
  the full writeup for the final three-material package; keep it current
  as the next campaigns add material. `EMAIL_DRAFT_full_package_unsent.md`
  is the superseded fuller email draft, kept for reference only.
- Scientific rules apply unchanged: kappa_L is a first-pass RTA value with
  its q-mesh caveat; never combine it with PF/tau into an "absolute zT"
  while tau is unknown; no SOC, no NAC — say so.

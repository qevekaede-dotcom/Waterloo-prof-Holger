# Independent review of the Claude transfer package

Date: 2026-09-22. Disposition: **SHIP for the documentation handoff only**.

No actionable finding remains in the reviewed handoff. A newcomer can identify
the authoritative state, distinguish completed work from proposals and
synthetic tools, reproduce bounded local checks, and see which actions still
need new evidence or authorization. This disposition supports the authorized
documentation/history publication; it is not scientific acceptance of a
material result and does not assert that the main push has already succeeded.

## Scope

This was a fresh review of the transfer documents layered on scientific
checkpoint `712602c9fb1b6d8414b9e5cc34256a3978d6f275`. The reviewer did not
implement the handoff. The review did not re-audit the 58 historical commits,
rerun broad software suites, query DRAC/Nibi, reopen remote HDF5 files, run QE
or phono3py, inspect sent email, commit, or push.

## Evidence inspected

- Root `AGENTS.md`, `CLAUDE.md`, `HANDOFF.md`, the full `CLAUDE_HANDOFF/`
  package, the three material-scoped `CLAUDE.md` files, and the updated
  navigation and append-only log entries.
- `CURRENT_STATE.md`, both saved validation reports, both original independent
  Sol reviews, the round-two entry, and the relevant Rb reuse,
  duplicate-source, q-commensurability, execution-receipt, and presentation
  documentation.
- The saved SrZr audit JSON directly confirms `first_pass_unconverged`, the
  failed preferred pristine-force gate, minimum `-1.0716026422440281 THz` at
  `q=(0,0.4,0)`, 12 sampled modes below `-0.1 THz`, and
  `accepted_kappa_l_result=false`. The saved Rb audit directly confirms all
  four q-mesh transitions failed and `qmesh_converged=false`.
- All 55 selected manifest entries exist and match their recorded byte counts
  and SHA-256 values. Package-relative links resolve after this review file is
  present. The PPTX contains 11 slide XML parts and 11 note XML parts; a direct
  Han-character scan of both found none, consistent with the saved rendered
  review and the separate bilingual script.
- The fetched comparison remains `origin/main...HEAD = 0 58`, with
  `origin/main` an ancestor of the research checkpoint. The handoff correctly
  treats publication as the next operation and provides post-push verification
  commands instead of claiming a completed push.

## Scientific and authorization reconciliation

- All three materials remain without an accepted lattice thermal conductivity
  or final zT. Electronic first passes, saved-file integrity, scheduler state,
  numerical gates, and scientific acceptance remain separate.
- SrCu2SnS4 v2 remains preparation-only. The new receipt tool is a standalone
  SYNTHETIC prototype and the real workflow still records
  `execution_provenance_verified=false`.
- SrZrS3 q/reference-basis, atom/eigenvector mapping, polymorph identity, and
  proposed public-data comparison remain unresolved and unperformed. The
  handoff does not convert shared `Pnma` labels into a polymorph conclusion.
- The Rb HDF5 statement is explicitly a historical limited audit, not a current
  remote-file check. The 11-task repeated-source group is only a saved-hash and
  nominal-displacement lead; force equivalence, noise, reuse, deletion, and
  savings remain unproved.
- The one-time authorization covers publishing this reviewed handoff and
  research history to main. It does not authorize future main changes, SSH,
  jobs, heavy calculations, email, or edits to frozen records.

## Findings

None. The documentation handoff is ready to ship within the scope above.

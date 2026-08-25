# WORKLOG — CHEM 494A supervision inquiry

Lab-notebook rules: dated, append-only entries.

## 2026-08-25 — Draft written

- Task from the user: ask Professor Kleinke directly (not via Roy) whether
  he can supervise the CHEM 494A research project in the upcoming Winter
  term; if yes, ask what direction he suggests and what to learn in
  advance; open with a brief summary of the term's work with Roy.
- Decisions taken:
  - Send from the university account. Checked the personal Gmail first: it
    contains no threads with Roy or the professor — all group
    correspondence (and the CCDB registration) lives on the university
    address — so no Gmail draft was created there, and the recipient
    address must be taken from prior correspondence or the department
    directory. It is deliberately not stored in this public repo.
  - The summary cites only traceable numbers: PBE gaps
    0.3445 / 0.6096 / 0.7811 eV (each material's
    `results/workflow_summary.md`), kappa_L 0.36 -> 0.12 W m^-1 K^-1 over
    300-900 K (`SrCu2SnS4/results/kappa_L_first_pass.csv`, rounded from
    0.3639 / 0.1213), 168 displaced supercells (`phono3py_disp.yaml`).
  - House rules kept: transport values described as electronic-only upper
    bounds, per relaxation time, no SOC; kappa_L labeled first-pass with
    its approximations named (2x2x1 supercell, 4.0 A pair cutoff, RTA);
    no absolute zT and no ranking claimed.
  - The phono3py history is phrased as "I got phono3py running end to
    end" — no mention of anyone else's failed attempts.
- Rigor self-review: every number in the draft traced to its source file;
  units present; no scientific rule violated.
- Status: draft only, NOT sent. Append the outcome here after sending.

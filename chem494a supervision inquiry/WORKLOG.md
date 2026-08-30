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

## 2026-08-25 — Revision: shortened per the user

- User's direction: drop the GitHub link and all numbers; the work summary
  should be a brief mention only. The user sends the email themselves from
  the university account (no address lookup needed).
- The three-bullet summary was compressed to one sentence (candidate
  selection, first-pass transport for all three, phono3py working with a
  first-pass kappa_L for the first candidate). Compound names, gaps,
  kappa_L values, and the repository link were removed. The three
  questions and the DRAC thank-you are unchanged.
- One sentence of summary was kept (rather than none) so the professor can
  place who is writing.
- Rigor self-review: with the numbers removed, no quantitative claims
  remain; "first-pass" qualifiers kept; no rule violated.
- Status: draft only, NOT sent. Append the outcome here after sending.

## 2026-08-25 — Revision 2: restore a concrete summary; single sincere ask

- User's direction: do show the work after all (summary "slightly more
  concrete" than the one-liner), but remove the "what should I learn
  before January" question and the offer to meet in person or online
  (the user is travelling and does not want an interview; the email
  simply omits any meeting mention). The ask becomes one sincere
  question: would he supervise, and is there a project to work on.
- Summary restored to three short bullets: candidate selection under his
  constraints; first-pass QE + BoltzTraP2 for all three with per-material
  convergence tests, PBE gaps ~0.34/0.61/0.78 eV (rounded from
  0.3445/0.6096/0.7811, each material's `results/workflow_summary.md`),
  carrier preferences on the sampled grids, Roy's review; phono3py
  working with first-pass kappa_L for SrCu2SnS4 ~0.36 W m^-1 K^-1 at
  300 K (rounded from 0.3639, `results/kappa_L_first_pass.csv`), labeled
  first-pass under documented approximations. GitHub link stays out.
- Rigor self-review: numbers traced and rounded transparently ("about");
  gaps labeled PBE; carrier preferences tied to the sampled grids;
  kappa_L labeled first-pass; no zT or PF claim; no rule violated.
- Status: draft only, NOT sent. Append the outcome here after sending.

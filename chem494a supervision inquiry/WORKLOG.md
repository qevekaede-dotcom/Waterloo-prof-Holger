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

## 2026-09-06 — Draft follow-up to Roy: research direction and CHEM 494A/B

- New request from the user: after four research stages, ask Roy for the next
  concrete research direction; ask whether he has discussed the user's CHEM
  494A/B project with Professor Kleinke, what direction was discussed, what
  the user should discuss directly with the professor, and whether Quest or
  other forms/approvals are required. Clarify that wet-lab or combined work is
  also welcome.
- Repository check: the old CHEM 494A branch is already fully contained in
  `main`. The prior `EMAIL_DRAFT.md` is addressed to Professor Kleinke and has
  no sent outcome. No record says Roy discussed CHEM 494A/B with the professor,
  and no reply to the final SrCu2SnS4 phono3py direction question is recorded.
- Created `EMAIL_DRAFT_TO_ROY.md` rather than overwriting the professor draft.
  It follows up on the two research options already put to Roy (continue the
  other candidates' phonons versus tighten SrCu2SnS4 first) and leaves room for
  a different direction. It also asks whether the four completed stages become
  the CHEM 494 starting point and what new A/B work would be expected.
- The wet-lab sentence preserves the user's previously stated computational
  interest while making clear that experimental or mixed work is welcome; it
  does not imply that either kind of project has already been assigned. The
  draft asks about training/access if laboratory work is selected.
- Current official Chemistry pages say CHEM 494A/B is a consecutive two-term
  research sequence, normally at least six hours per week; the supervisor
  proposes the project, coordinator permission is required, and the supervisor
  arrangement is formally recorded. They do not identify a clear, universal
  Quest form on the public page. The draft therefore asks whether the next
  action belongs in Quest, LEARN, with the CHEM 494 coordinator, or with the
  Chemistry Undergraduate Office, and asks whether a Winter start is workable.
  The official Fall 2026 add deadline is September 22, so the draft asks if
  action is needed now without assuming Fall enrolment is correct. Sources:
  `https://uwaterloo.ca/chemistry/undergraduate-studies/course/chem-494`,
  `https://uwaterloo.ca/chemistry/undergraduate-studies/chem-494-research-project/chem-494-general-information`,
  and `https://uwaterloo.ca/important-dates/undergraduate/2026-2027/add-period-ends`.
- No technical numbers were repeated beyond the project-stage descriptions;
  no attachment is needed. Status: DRAFT ONLY, NOT SENT.

## 2026-09-06 — User correction: preliminary supervision was already agreed

- The user supplied the missing communication history: they first emailed
  Professor Kleinke about CHEM 494; he replied that the arrangement was fine
  if Roy was willing to continue working with the user. The user then spoke to
  Roy in person; Roy agreed. The user left Canada for a holiday shortly after.
- This is a user-provided outcome summary. The exact sent email, Professor
  Kleinke's reply, and the in-person conversation are not stored in the public
  repository, so `EMAIL_DRAFT.md` is labeled as a historical draft rather than
  a verbatim sent record.
- Updated the active README and HANDOFF. The current uncertainty is no longer
  whether either person is willing; it is whether Roy and Professor Kleinke
  have since discussed the project scope, what work should come next, what the
  user should confirm directly with the professor, and how to formalize course
  registration.
- Revised `EMAIL_DRAFT_TO_ROY.md` to thank Roy for agreeing in person and ask
  the remaining scope/direction/administrative questions. Its wet-lab openness
  and Winter-timing questions are unchanged. Status: DRAFT ONLY, NOT SENT.

## 2026-09-06 — Sent records confirmed; Professor Kleinke was already informed

- This evidence supersedes the provisional `no sent outcome` and `NOT SENT`
  statements in earlier entries above. Those entries remain unchanged under
  the append-only lab-notebook rule.
- The user reports that the follow-up preserved in `EMAIL_DRAFT_TO_ROY.md`
  was sent to Roy on 2026-09-06. Roy's reply is pending. The prepared version
  called for no attachments, but the exact sent message has not been exported
  from the mailbox. Treat the file as a frozen source copy rather than an
  editable draft or a guaranteed verbatim sent record.
- The user supplied a screenshot of their sent reply to Professor Kleinke in
  the CHEM 494A Winter-term thread, dated 2026-08-28. It confirms that the user
  explicitly told Professor Kleinke that Roy was happy to continue working
  with them and had already provided the next-work direction.
- The same sent message said the user would continue the remaining two
  candidates' phonon campaigns remotely over the break, continue reporting to
  Roy, ask the Undergraduate Office which CHEM 494A enrolment form was needed,
  and send it to Professor Kleinke. It separately said the user would resume
  in-person group meetings on return and looked forward to joining the group
  in Fall; this does not change the stated Winter target for CHEM 494A.
- Consequence for follow-up: Professor Kleinke does not need another email
  merely confirming Roy's agreement. The next useful message to him should
  contain either the Undergraduate Office/coordinator's concrete procedure or
  form, or a project scope agreed with Roy.
- Privacy/data handling: only project-relevant facts from the screenshot are
  recorded. The screenshot itself, email addresses, and personal medical or
  travel details were not added to this public repository. The full initial
  inquiry and Professor Kleinke's full reply remain unavailable as text.
- The CHEM 494 statement in `docs/archive/HANDOFF_2026-08-30.md` is now known
  to be stale, but that file remains unchanged as a verbatim historical
  snapshot. This entry and the active `HANDOFF.md` supersede it.
- Rigor self-review: this update changes administrative/communication state
  only. No scientific result, numerical claim, raw record, or
  `READY_TO_ATTACH/` content was changed.

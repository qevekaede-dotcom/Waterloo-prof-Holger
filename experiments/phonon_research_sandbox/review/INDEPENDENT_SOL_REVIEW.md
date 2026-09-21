# Independent scientific and software review

Decision: **fix-first**

Review basis: branch `codex/phonon-research-sandbox` at root-doc milestone
`246037c`, with the current uncommitted review set. This was a bounded,
read-only review of the repository evidence, plans, source changes, dashboard
data, rendered slides, final PPTX, and companion script. No cluster state,
remote HDF5 bytes, new QE/phono3py result, or sent email was verified.

## Actionable findings

1. **[P1] Make the SrZrS3 frozen-mode experiment commensurate with the
   reported wave vector.** The saved minimum is at reduced reciprocal
   coordinate `q = (0, 0.4, 0) = (0, 2/5, 0)`
   (`force_audit_summary.json:76-79`). A real-space frozen-mode distortion must
   use a supercell matrix `S` satisfying `S^T q` integer; for a diagonal matrix,
   the second-axis multiplier must therefore be a multiple of five. The plan
   proposes `3x2x1`, `5x2x1`, and `4x2x2` harmonic comparisons
   (`plans/SrZrS3.md:33`) and later says only to relax along the eigenvector
   (`:35`, `:50`) without specifying a commensurate mode supercell. Those
   candidate FC2 cells are useful size tests, but none is commensurate with
   this q point in the second direction. Before shipping, state that the mode
   must first be replayed and tracked at a common q, then construct a
   q-commensurate supercell (for example, a reviewed cell with second-axis
   multiplicity five, subject to the general matrix condition), generate a
   real displacement from the complex eigenvector/star, and compare symmetric
   amplitudes and relaxed endpoints. Otherwise the proposed structural branch
   is not executable for the observed mode.

2. **[P1] Do not call the v2 health record bound to the exact pristine input
   until the execution evidence is linked to that input.** The audit correctly
   checks the current `scf.in` against the manifest (`audit_pristine_v2.py:49-62`),
   but it then accepts arbitrary command-line stdout, stderr, and exit-code
   files (`:84-106`) and joins their hashes with the input hash only when it
   writes one JSON object (`:117-131`). The parser checks run health and atom
   count, not the QE settings or the identity of the input that produced the
   output. Preflight later replays those same independent hashes
   (`preflight_v2.py:138-160`), so a healthy 96-atom output from another input
   can still be labelled healthy for this exact input. Add a fail-closed launch
   receipt produced at execution time that records the reviewed input hash,
   command, working directory, stdout/stderr destinations, and exit status,
   and require the audit to validate that receipt. Until then, weaken the plan,
   README, and error message from “healthy for this exact input” to an input
   integrity check plus separately supplied process evidence.

3. **[P2] Align the proposed two-transition physical convergence rule with the
   actual control matrices.** SrCu proposes only baseline versus one larger FC3
   supercell (`plans/SrCu2SnS4.md:47`) while its proposed criterion requires two
   adjacent physical steps to pass (`:63`). Rb likewise proposes only M72
   versus M108 (`plans/Rb2Cu2SnS4.md:50`) while requiring at least two adjacent
   physical steps (`:83`); its cutoff stage also currently specifies just one
   larger shell-crossing comparison (`:49`). These plans cannot satisfy their
   own stop rule. Either add a third ordered cutoff/supercell level, with the
   same force model and fixed q mesh for both transitions, or explicitly adopt
   a one-transition pilot decision that remains provisional and cannot be
   called convergence. Keep the inherited strict `<3%` trace and `<5%`
   diagonal thresholds labelled as proposed for cutoff/supercell studies, as
   the current text correctly does.

## Verified strengths and remaining limits

- The main claims remain appropriately bounded: no accepted `kappa_L` for any
  material, no promotion of electronic-only `zT_e`, no claim that the old
  SrCu value was a 4-angstrom or tensor-converged result, and no claim that the
  SrZr imaginary mode already proves real-material instability.
- The Rb 90-to-105 diagnostic changes in the dashboard/deck reproduce the
  archived current-value-denominator audit: trace/3 changes are about 4.266%,
  4.083%, and 4.047%, and the largest diagonal changes are about 10.192%,
  9.692%, and 9.594% at 300, 600, and 900 K. The 300 K PF/tau chart values also
  match the three source CSV files. These remain rejected diagnostics.
- The final 11-slide PPTX rendered without visible clipping in the inspected
  PNGs. Its slide text and embedded notes are English; Chinese appears in the
  separate `SPEAKER_SCRIPT_EN_ZH.md`. The package/layout/chart-workbook checks
  passed, but native PowerPoint execution was not tested.
- The dashboard now correctly calls the saved HDF5 `mesh` vector SNF diagonal
  values rather than an actual grid matrix and states that the archived JSON
  cannot reconstruct the grid geometry. The dashboard rebuild was not rerun
  in this review because doing so would rewrite review artifacts.
- The new stdout scan closes the demonstrated post-`JOB DONE` `MPI_ABORT`
  hole. Common abbreviated fatal signals such as `SIGSEGV`, `SIGBUS`,
  `SIGTERM`, and `SIGKILL` are not explicit patterns in `qe_output.py`; the
  strict stderr contract and retained exit code cover the v2 audit path, but
  direct `inspect_output()` callers remain dependent on the exact wording in
  stdout. Expanding the signature set is a remaining hardening task, not a
  basis for a scientific claim.

## Bounded disposition follow-up

Decision: **fix-first** for one remaining provenance-wording contradiction.
The material is otherwise ready to ship for the **local plan and preparation
scope only**. This follow-up inspected only the edits addressing the three
findings; it did not rerun broad tests or review unrelated files.

1. **SrZrS3 mode commensurability: resolved.** The plan now distinguishes FC2
   interpolation-range supercells from a frozen-mode supercell, requires the
   saved q/reference-cell basis and atom mapping to be verified, states the
   general `q·T in Z` condition, treats a second-axis multiple of five as
   conditional on that basis, constructs a real displacement from the
   conjugate `+q/-q` pair, and requires count-only budgeting before any
   execution (`plans/SrZrS3.md:33-35,49-59`). The 1x5x1 example is explicitly
   neither an approved geometry nor a cost estimate.

2. **v2 input-to-execution provenance: one wording fix remains.** The health
   and preflight JSON now correctly set `execution_provenance_verified` to
   false and scope `healthy` to terminal parsing of caller-supplied logs
   (`audit_pristine_v2.py:117-140`, `preflight_v2.py:171-178`). The plan,
   current-state page, and learning guide explicitly require a future external
   execution receipt and do not release or accept real results without it.
   However, `preflight_v2.py:140` still raises `pristine is not healthy for
   this exact input`, which asserts the association the new scope disclaims.
   Replace it with wording that keeps the two checks separate, for example:
   `supplied pristine logs are not terminally healthy, or the current pristine
   input differs from the audited input hash`. No receipt implementation is
   required for this local-only deliverable.

3. **Physical convergence ladders: resolved.** SrCu and Rb now define
   `C0,C1,C2` and `S0,S1,S2`, choose later levels conditionally from measured
   evidence, keep a single transition explicitly provisional, and require two
   consecutive passing transitions before convergence (`plans/SrCu2SnS4.md:47-48,64,69-73`;
   `plans/Rb2Cu2SnS4.md:49-50,83,90`). The inherited strict trace/diagonal
   thresholds remain clearly labelled as proposed outside the implemented Rb
   q-mesh gate.

After the one error-message correction above, the disposition is **ship for
local plan/preparation scope only**. It does not authorize or validate SSH,
QE, phono3py postprocessing, Slurm submission, or scientific acceptance.


## Coordinator closure of the final conditional item

2026-09-21: Changed the exact remaining message at `preflight_v2.py:140` to
`supplied pristine logs are not terminally healthy, or current pristine input differs from the audited input hash`.
The condition and code behavior are unchanged; the wording now separates the
two checks. A literal search confirms the old message is absent. This fulfills
the reviewer’s stated condition for **ship for local plan/preparation scope only**.
No further general review or physics calculation was performed.
Execution provenance remains explicitly false and is a prerequisite for future
real-run acceptance, not a solved capability.

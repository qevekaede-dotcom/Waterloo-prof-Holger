# Repository-wide work log

Append-only maintenance history. Calculation/package histories remain in
their existing scoped WORKLOG files.

## 2026-09-06 — Reconcile GitHub research state and tidy repository

**Request:** learn the existing research, organize it, remove unnecessary
files, and use the complete GitHub history as authority across computers.

1. The originally supplied workspace path was unavailable; resolved the
   current saved project path before accessing the existing repository.
   Confirmed a clean checkout and its Git remote; did not create another clone.
2. Fetched GitHub, fast-forwarded local main from c138cdc to 9bfe607, then
   compared remote branch ancestry. Main was not the latest research state.
   Branch 0024114 contained 13 additional commits and both other research
   branches, so created codex/research-repository-cleanup from that basis.
3. Read standing/scoped project instructions, active handoff, summaries,
   research logs and source records. Independent read-only audits checked
   cleanup candidates, electronic transport, and phonon evidence.
4. Initial HDF5 read through the base Python environment lacked h5py; used
   the already-installed scientific environment for read-only verification.
   No environment installation or computational campaign was needed.
5. Preserved the old handoff byte-for-byte under docs/archive; wrote current
   state and continuity instructions, repaired stale status/launch guidance,
   and corrected the unsent writeup's threshold percentage. A first combined
   patch was rejected for multiple operations on one file; applied valid
   update patches instead. No scientific records were affected.
6. Removed only nine obsolete input templates (5,817 bytes). Kept actual
   inputs, all logs/results, failure evidence, all sent attachments,
   presentation/reproducibility copies, ignored scratch and private material.
7. Read-only scientific review matched 168 force logs, seven HDF5/CSV rows,
   and three sets of 98 transport / 14 selected rows. Found the average-only
   mesh convergence limitation and a residual-force awk reporting problem;
   documented both without altering scripts or sent material.
8. Preservation audit compared source blobs and confirmed all 20 frozen
   attachments and all retained non-document research files unchanged.
   Historical HANDOFF hash matches its source exactly. Checked patch
   whitespace and absence of executable references to the deleted templates.
9. Checked 30 relative Markdown links in the changed active documents; none
   were broken. Refetched GitHub before publication: main remained 13 commits
   behind the research basis. The connector's PR-list request failed with a
   transport error; the GitHub CLI read-only fallback confirmed no open PRs.

**Scientific review outcome:** stored numerical tables match their raw
sources, but first-pass caveats remain. In particular, the last q-mesh
average change (~3%) does not establish a 5% tensor uncertainty (zz changes
~12%). Full zT still needs a relaxation-time model. No SOC/NAC claim was
added; no new simulation or full convergence claim was made.

**Publication scope:** save the cleanup on its new GitHub branch and propose
a draft PR into main; do not merge, force-push, delete research branches,
or send research communications. The PR includes the 13 existing research
commits inherited from the complete GitHub basis.

## 2026-09-06 — Merge approved cleanup into main and remove temporary branch

**New authorization:** the user requested publishing the cleanup to main and
deleting this task's draft branch, preferring a tidy repository. This
supersedes the previous task's no-merge publication scope for PR #1 only.

1. Confirmed a clean local checkout, fetched GitHub, and checked PR #1:
   head `9234a5e`, base main, mergeable, no reported status checks.
2. Marked the draft ready and merged through GitHub using the expected head
   SHA. Merge commit `88c2da2` preserves the existing research commits.
3. Fast-forwarded local main to the remote merge. Verified `9234a5e` is an
   ancestor and the merge tree is identical to the reviewed cleanup tree.
4. Deleted only `codex/research-repository-cleanup`, remotely and with
   safe local `git branch -d`. Its history remains in main; other research
   branches and local ignored files were not touched.
5. Updated README, HANDOFF, and the repository audit to point to main and
   record the completed integration. Kept historical log entries unchanged.

**Scientific review:** this publication adds no calculations or scientific
claims. The merged tree preserves the previously audited records, scripts,
frozen attachments, numerical results, and documented limitations. The
follow-up edits change only publication status and this log.

## 2026-09-14 — remaining-phonons continuity update

1. Recorded the completed SrZrS3 2x1x1 count-only boundary check without
   upgrading it to a production selection: Nibi job `21850149` completed
   `0:0`; raw YAML gives 787 inputs (25 singles + 762 seconds), 147 included
   groups/122 nonzero, at `3.5541348625 A` (`6.71634150010947 bohr`).  The
   40-atom supercell's inscribed radius is `3.8384532612 A`; clearance is
   `0.284318 A` (92.5929%).  Archive validation passed.  The strict
   dependency-free validator (current policy, raw YAML, checksums, no symlinks)
   passed 333 tests with one skip; a fresh review passed.  This remains
   count-only evidence: pilot and production are blocked.
2. Recorded the completed local Rb2Cu2SnS4 replay-validator repair.  It pins
   the approved `cf0b1d1` historical workflow snapshot by full hash set,
   evaluates it under current config/policy at one checkout root, checks nested
   collector schema and global Slurm-ID uniqueness, and permits relocation
   across checkouts.  Local tests and reviews passed.
3. Kept the material's scientific gate unchanged.  The only BFGS polish,
   `21848175`, failed `2:0`; collector `21848176` completed but records an
   incomplete lineage.  The repair has not been read-only replayed against the
   real Nibi lineage using its final commit.  That replay is the next evidence
   action; it neither accepts a structure nor authorizes a rerun, pilot, or
   production campaign.

**Scientific review:** all recorded numerical values are status/evidence
metadata supplied by the archived validator and scheduler records; no QE,
phono3py, force, FC2/FC3, or transport result was generated or altered.  Units
are explicitly retained where applicable.  Count-only evidence and software
tests do not establish an fc3 cutoff, convergence, a structure, kappa_L, or
full thermoelectric zT.

## 2026-09-14 — final Rb replay repair verified read-only on Nibi

Exact commit `824cbcf0c91bd8b4f9abcd8c53266dcecd2f3cc7` was checked out
cleanly under `/scratch/yuhansun/codex-verify-824cbcf`.  The Nibi phono3py
environment passed all 333 campaign tests.  The repaired validator then
replayed the real Rb2Cu2SnS4 diagnostic lineage under
`/scratch/yuhansun/phono3py-runs/20260911-continuation-cf0b1d1/` and returned
`PASS`, with `structure_accepted=false` and `preflight_unlocked=false`.

The old run contained 963 files both before and after replay.  SHA-256 values
for `diagnostic/final/gate.json`, its provenance, `polish_lineage.json`, and
`run_manifest.json` were identical before and after.  No Slurm job was
submitted and no old evidence was changed.  This closes the replay software
defect only; the failed BFGS polish remains scientifically blocked.

## 2026-09-14 — Rb FIRE recovery preparation is reviewed plan-only

1. Added a separate fail-closed FIRE preparation policy for a future new
   Rb2Cu2SnS4 lineage.  It uses only the frozen pre-BFGS reference seed and
   does not accept or extend failed BFGS job `21848175`.
2. Two fix/review cycles closed evidence-replay gaps: historical raw and
   canonical configuration identities are pinned; failed-relax and later-
   collector outputs and full contexts are bound to exact paths and hashes;
   the replay validator is part of the workflow fingerprint; and new paths
   reject symlink ancestors before resolution.
3. The final local suite passed 353 tests with one optional-spglib skip.
   Python compilation, shell syntax, both Rb/Sr configuration validations,
   and `git diff --check` passed.  A fresh independent review returned `SHIP`
   only for the plan-only implementation.
4. Nibi remained reachable and a read-only check found no queued jobs.  No new
   RUN_DIR, Slurm submission, QE calculation, or scientific result was made at
   this milestone.  All FIRE execution, collection, final acceptance, and
   independent preflight release paths remain hard-locked.

**Scientific review:** this milestone establishes software provenance and a
bounded future hypothesis only.  Rb2Cu2SnS4 still has no accepted structure,
pristine gate, preflight, force/FC2/FC3, or kappa_L result.  SrZrS3's 787-input
record remains count-only and does not select a cutoff or release pilot or
production work.  Both production budgets/selections remain null or blocked.

## 2026-09-14 — plan-only Rb FIRE lineage prepared on Nibi

1. Committed and pushed the reviewed implementation as exact commit
   `aab9290a66cc63058584c04ad39a091ff5d13284`, then created clean Nibi
   checkout `/scratch/yuhansun/codex-verify-aab9290`.  Its worktree was clean
   and all 353 tests passed in the Nibi phono3py environment; both Rb and Sr
   configurations validated healthy while retaining their production blocks.
2. The first evidence command used the nonexistent name
   `diagnostic/final/gate.provenance.json` instead of the verified
   `diagnostic/final/provenance.json`.  `set -e` stopped before lineage
   preparation.  A follow-up check confirmed the new RUN_DIR was absent and
   the queue empty; the failed command caused no campaign or scheduler
   mutation.
3. Reran with the inspected filename.  Exact replay prepared
   `/scratch/yuhansun/phono3py-runs/20260914-rb-fire-plan-aab9290/Rb2Cu2SnS4`
   with receipt SHA-256
   `f1f4baabe1c4dee3da804eb60e14ba4cc8c23d7a33cf4914a2bcfe9a9b449e74`
   and seed SHA-256
   `b2f919f7af04a0fd93400e2e5cd021bb489947e245e3d834694167bf2ded714f`.
   The directory has eight files, zero symlinks, and zero files in its
   attempt/submission trees.
4. The read-only pilot plan returned `execution_released=false`,
   `primary_command_template=null`, and `collector=false`.  The old Rb
   lineage remained at 963 files, all eight rechecked old evidence hashes
   were unchanged, the clean checkout stayed clean, and Nibi `squeue` had
   zero rows before and after.  No `sbatch` or QE command was run.

**Scientific review:** lineage preparation validates provenance and freezes a
seed; it is not a relaxation result.  Rb2Cu2SnS4 still has no accepted
structure, pristine gate, preflight, forces, FC2/FC3, or kappa_L.  FIRE pilot,
collector, finalizer, and all downstream release paths remain deliberately
unimplemented or hard-locked.  SrZrS3 is unchanged and remains at the
count-only gate.

## 2026-09-20 — remaining-material evidence checkpoint and SrCu2SnS4 correction audit

Pushed checkpoint `30bc4ad` on `codex/complete-three-material-phonons`, adding
the curated SrZrS3 rejected-first-pass evidence and Rb2Cu2SnS4 active
first-pass evidence. The campaign suite passed 420 tests with one optional
spglib skip; Python compilation, Slurm shell syntax and whitespace checks
passed. A separate top-level fifth-step index now records what was done for
the two remaining materials without duplicating heavy QE/HDF5 artifacts or
creating another attachment directory.

On Nibi, the missing Rb task 462 infrastructure failure and the failed old
postprocess were archived with verified SHA-256 manifests. Only task 462 was
resubmitted as job `22312416`, with strict dependent postprocess `22312417`.
The submission snapshot showed priority/dependency pending states; neither is
recorded as complete or scientifically accepted. A quiet hourly same-thread
monitor replaces repeated manual polling.

The SrCu2SnS4 historical lattice pass was also re-audited. Its intended 4-A
cutoff had been supplied as 4.0 in QE atomic units, so the actual cutoff was
4.0 bohr (2.11670884 A); all 24 included pair groups were onsite, while the
shortest excluded nonzero pair was 4.33833022 bohr. The pristine force block
is traceable and was used by `--cfz`, but the QE run later hit `seqopn(90)`
and MPI abort. Fourteen of 168 displaced outputs fail the current terminal
health gate, the force settings are not uniform, and the corrected q-mesh
ladder fails the current tensor criterion. Documentation and fail-closed local
validators are corrected in this milestone; the raw record and every frozen
attachment remain unchanged. A scientifically corrected 4-A value requires a
new uniform Nibi force campaign and q-mesh ladder.

Final local validation after both review-fix cycles passed all 434 tests with
one optional-spglib skip, Python compilation, shell syntax, JSON parsing,
Markdown link checks, frozen-attachment checks, and `git diff --check`. The
fresh independent Sol review returned `SHIP` with no remaining findings.

## 2026-09-20 — Rb terminal first-pass audit and SrCu2SnS4 v2 preparation

The narrow Rb recovery job `22312416` completed `0:0`; dependent postprocess
`22312417` reached FC2/FC3 plus all five q-mesh stages and then failed `1:0`
because the old scanner looked for `force_constants` in `fc3.hdf5` instead of
the documented `fc3` dataset. One bounded read-only Nibi evidence session
verified the recovered force audit and saved HDF5 artifacts without remote
writes or recomputation. FC2/FC3 shapes, finite values, maps, version, and atom
binding pass limited integrity checks; harmonic and off-diagonal gates pass.
Every q-mesh transition fails, however, so the 105-A tensor is retained only as
a rejected diagnostic and no accepted kappa_L exists.

The local Rb finalizer now validates existing artifacts without rerunning
calculations, uses distinct FC2/FC3 schemas, binds command/hash evidence, and
returns a nonzero gate bitmask unless q-mesh, harmonic, and off-diagonal gates
all pass. Failed gates can write only an explicitly named rejected-diagnostic
CSV with a status column. This repair was not run remotely.

A separate `thermo_candidates/SrCu2SnS4/phono3py_v2/` preparation-only package
now encodes the intended 4.0-A cutoff as 7.5589045 bohr, requires uniform
90/720-Ry inputs, validates displacement YAML semantics, binds pseudopotentials
and pristine evidence to externally retained manifest/health SHA-256 anchors,
and rejects symlink or evidence-path escapes. It contains no Slurm template and
does not release QE, force, or postprocess execution. No real v2 displacement
dataset or calculation was produced.

Final local checks passed 434 shared campaign tests (one optional skip), 11 Rb
postprocess tests, 17 SrCu v2 tests, Python compilation, JSON parsing, Markdown
relative-link checks, and `git diff --check`. A fresh independent Sol review
first found and then reproduced manifest/health rebinding attacks; after the
fail-closed fixes it returned `SHIP` with no actionable findings. No
`READY_TO_ATTACH/` file was changed.

## 2026-09-21 — Isolated phonon research sandbox and current-status reconciliation

Created `codex/phonon-research-sandbox` from fetched remote research tip `cf21cce`
in an isolated worktree. Original and other existing tracked worktree states
were inspected and left unchanged. Archived the prior HANDOFF verbatim to
`docs/archive/HANDOFF_before_phonon_sandbox_2026-09-21.md`; replaced the active
handoff with a concise evidence-based entry. Reconciled stale phonon completion,
pending-run, and main-baseline statements in root guidance and Roy task status.
Current state explicitly distinguishes electronic first pass, saved artifact
integrity, scientific rejection, plan-only v2, and user-confirmed email sending.
No original research record, historical log entry, sent body or attachment was
modified. No Nibi login, job operation or heavy calculation occurred.
Further deliverables and append-only validation are recorded in
`experiments/phonon_research_sandbox/WORKLOG.md`.

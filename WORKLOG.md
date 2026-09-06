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

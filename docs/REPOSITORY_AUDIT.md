# Repository reconciliation and preservation audit

Audit date: 2026-09-06. Scope: reconcile the complete GitHub research state,
improve navigation/session continuity, and remove demonstrably obsolete
placeholders. No simulations, package installations, SSH connections,
emails, or changes to scientific source data were performed.

## GitHub authority and branch basis

The user works across computers and designated GitHub as the complete shared
record. The initially clean local checkout was at `c138cdc`; fetched
`main` was `9bfe60786c0226a9180fad22db3325d1c86a715f`.
Inspection of all fetched research branches found the complete basis:

| Remote branch at audit | Commit | Relationship to cleanup basis |
| --- | --- | --- |
| main | 9bfe607 | Ancestor; 13 commits behind |
| claude/chem494a-thesis-inquiry-gzaybw | 724a51d | Ancestor |
| claude/holger-repo-access-a8ikbc | c03b650 | Ancestor |
| claude/canada-computing-center-task-d165w2 | 0024114 | Complete research basis |

The local main was fast-forwarded, then
`codex/research-repository-cleanup` was created from the complete basis.
No remote research branch was deleted or force-pushed. Review consolidation
into main separately; a cleanup PR also contains the 13 previously unmerged
research commits, not just this maintenance change.

The existing checkout was reused. Ignored local scratch and private
background files were not deleted, inspected for content, or published.
GitHub is authoritative for shared research records, not a backup of
intentionally excluded local material.

## Changes and preservation

- Added `AGENTS.md` to make existing scientific rules and current-state
  reading order explicit for Codex; retained `CLAUDE.md`.
- Reconciled active documentation with completed electronic workflows,
  completed SrCu2SnS4 first-pass kappa_L, and the sent interim email.
- Replaced the conflicting active handoff with a concise state/evidence index.
  Preserved the previous handoff verbatim in
  [the historical snapshot](archive/HANDOFF_2026-08-30.md).
- Marked local-compute setup as historical; active heavy compute and phonon
  postprocessing belong on DRAC.
- Corrected an unsent writeup's force-threshold arithmetic: 5.2e-6 is
  10.4%, not about 1%, of the 5e-5 Ry/bohr threshold.
- Deleted **9 obsolete `.in.template` files, 5,817 bytes**: relax/SCF/NSCF
  placeholders under each of SrCu2SnS4, SrZrS3, and Rb2Cu2SnS4.
  They contained unresolved structure placeholders and were superseded by
  actual archived `.in` files. No executable script references them; the
  input generator writes `.in` directly. They remain recoverable from
  source commit `0024114` and earlier Git history.
- Added standard Python cache/environment exclusions without excluding
  scientific `.out`, `.hdf5`, CSV, or other research artifacts.

Intentional copies were retained: frozen submissions, presentation plots,
reproducibility script snapshots, pristine/displacement inputs, failure logs,
and the old uncorrected 15x15x7 HDF5. These have distinct provenance roles.

## Evidence verification

Read-only checks against the research basis:

- All 168 displacement logs include completed SCF and force records.
- All seven rows of `kappa_L_first_pass.csv` match the final corrected
  `kappa-m13136.hdf5` to the table's four decimals. The calculated mean is
  0.36394470 W m^-1 K^-1 at 300 K; minimum sampled frequency is
  -2.149e-6 THz, numerically near zero.
- For each material, all 98 transport rows reproduce PF/tau and zT_e from
  its raw BoltzTraP2 trace; all 14 selected rows match sampled PF maxima.
  zT_e is compared at those points, not independently maximized.
- SrZrS3's stored gap is 0.6096 eV at loader precision; 0.6097 from rounded
  printed QE edges is a previously documented rounding distinction.
- All source-basis scientific artifacts and scripts remain byte-identical.
  Only Markdown, `.gitignore`, and the nine placeholders were changed.
- All **20 files across four `READY_TO_ATTACH/` folders** have unchanged
  inventories and Git blob hashes (3 / 4 / 11 / 2 files respectively).
- Historical handoff blob equals `0024114:HANDOFF.md`:
  `55330fa10e7fb2a42adbfcd78a43ff67af61a6f7`.

No expensive pipeline was rerun; this checks retained evidence, not
independent physical reproducibility or current cluster availability.

## Scientific qualifications and unresolved issue

The corrected last q-mesh step (11x11x5 to 13x13x6) changes average kappa_L
by **-2.9559%**, but zz by **-12.2745%**. The stopping code checks only
the average. A historical approximate 5% estimate is not a demonstrated
tensor or overall physical uncertainty. Frozen sent files and raw results
were preserved; active documentation now states this limitation.
Larger-supercell/pair-cutoff convergence and NAC sensitivity are not
established. No significant imaginary mode on this sampled mesh is not a
global stability proof.

The force k-mesh check rejects 2x2x2 relative to 3x3x3 (1.621e-4 Ry/bohr).
The lower-cutoff check passes 60/480 against 90/720 Ry (5.2e-6 Ry/bohr,
threshold 5e-5). The mixed retained benchmark is documented, not hidden:
167 displacements at 60/480 Ry and disp-00001 at 90/720 Ry.

The pristine log contains a maximum force component of 5.4513e-4 Ry/bohr.
The residual-force `awk` expression in
`thermo_candidates/SrCu2SnS4/phono3py/scripts/run_campaign.sh`
printed zero on this Mac against that log; explicit numeric initialization
and coercion reproduced the correct value in a diagnostic check.
**Diagnose/test before the next campaign.** This cleanup does not change
scripts. Existing residual subtraction is supported by raw force data,
`log_cf3.txt`, and `slurm_logs/stage2_20311271.out`.

All reported values remain first pass, PBE/no explicit SOC, sampled-grid
results. PF/tau is not absolute PF; zT_e is not full zT. A relaxation-time
model remains required, and the other two materials lack kappa_L campaigns.

## Resuming work

Read [current handoff](../HANDOFF.md), [rules](../AGENTS.md), and the relevant
material/package instructions. The next research campaign is SrZrS3, then
Rb2Cu2SnS4, when requested. This audit does not launch that work.
See [README](../README.md) for cross-computer Git synchronization.

# Research handoff — current state

Last repository/evidence audit: 2026-09-20. Current continuation is in branch
`codex/complete-three-material-phonons`; use the pushed remote branch tip rather
than an older embedded checkpoint hash. The two remaining-material records are indexed in
`fifth step result (remaining-material phono3py first passes)/`. Historical
repository reconciliation and the merge through
[PR #1](https://github.com/qevekaede-dotcom/Waterloo-prof-Holger/pull/1)
remain documented in [the repository audit](docs/REPOSITORY_AUDIT.md), but
`main` is not the current research tip.

Read [CLAUDE.md](CLAUDE.md) for standing rules and [AGENTS.md](AGENTS.md)
for continuity. This file records state, not authorization to launch work.

## Verified completed work

| Material | Electronic first pass | Sampled PBE gap [calculated] | Lattice thermal conductivity |
| --- | --- | --- | --- |
| SrCu2SnS4 | QE + BoltzTraP2 complete | 0.3445 eV | Historical first pass only; current-contract unconverged/rejected |
| SrZrS3 | QE + BoltzTraP2 complete | 0.6096 eV | 788 forces and FC2/FC3 complete; imaginary-mode gate rejected kappa |
| Rb2Cu2SnS4 | QE + BoltzTraP2 complete | 0.7811 eV | FC2/FC3 and q-mesh artifacts pass a limited read-only HDF5 integrity audit, but every q-mesh ladder step fails; no accepted kappa_L |

Each electronic pass includes independent convergence tests, vc-relax,
final SCF, dense NSCF, and 300–900 K transport tables. Evidence:
`thermo_candidates/<material>/results/workflow_summary.md`, adjacent CSVs,
QE logs, and BoltzTraP2 trace/tensor files.
[Three-material comparison](learning/05_comparing_materials.md) explains
carrier preference; reported zT_e comparisons use PF-selected grid points,
not independently optimized zT_e.

SrCu2SnS4 lattice evidence: `thermo_candidates/SrCu2SnS4/phono3py/` and
`thermo_candidates/SrCu2SnS4/results/`. All 168 displacement outputs contain
parseable force records, but only 154 satisfy the current terminal-output
health gate; the force inputs also mix three setting families. Historical
residual-corrected `kappa-m13136.hdf5` matches
`results/kappa_L_first_pass.csv`: average **0.3639 at 300 K** and
**0.1213 at 900 K**, in W m^-1 K^-1 [calculated].

Conditions: PBE, no explicit SOC, RTA, no NAC, 2x2x1 supercell (96 atoms),
historical phono3py `cutoff_pair_distance=4.0` in QE units, i.e. **4.0 bohr
(about 2.1167 A), not 4.0 A**, 3x3x3 force k mesh, and final phonon q mesh
13x13x6.
167 displacements used 60/480 Ry; benchmark disp-00001 retained 90/720 Ry
after a force-difference test (5.2e-6 Ry/bohr versus a 5e-5 threshold).
Pristine residual maximum component 5.4513e-4 Ry/bohr was measured and
subtracted using `--cfz`.

SrZrS3 force accounting is complete for one pristine plus 787 displacements,
and the FC2/FC3 arrays passed shape and finite-value checks. The explicit
non-NAC 12x5x3 calculation has a minimum sampled frequency of
`-1.0716026422440281 THz`, with 12 modes below `-0.1 THz`. The finite tensor
is retained only as a rejected diagnostic; there is no valid kappa_L for zT.

Rb2Cu2SnS4 passed the FIRE, independent pristine, count-only preflight, and
seven-task force-pilot gates. Original production task 361 was recovered, but
task 462 failed before QE module start-up and made strict postprocess
`21963654` fail. The original failures are now separately archived. Narrow
recovery `22312416` completed `0:0`; dependent strict postprocess `22312417`
failed `1:0` at its final scan because its wrapper expected `force_constants`
in `fc3.hdf5`, whereas the HDF5 key is `fc3`. A saved-artifact, read-only HDF5
audit directly passes the FC2/FC3 integrity, shape, finite-value, map, version,
and atom-binding checks, as well as the harmonic and off-diagonal gates. It
also finds every 45->60, 60->75, 75->90, and 90->105 A q-mesh ladder step fails.
For 90->105 A, trace/3 changes are 4.2663%, 4.0831%, and 4.04694%, while the
largest diagonal changes are about 10.192%, 9.692%, and 9.594%, at 300, 600,
and 900 K. The 105-A tensor is therefore a rejected diagnostic only: no
accepted kappa_L exists. This does not establish force-constant scientific
validity or full phonon stability. Local finalizer code was repaired, but no
remote summary was written and no recomputation or submission occurred. Do not
touch the historical blocked job `21934081`.

## Scientific limits and open technical issue

- PF/tau is not absolute PF; electronic-only zT_e is not full zT.
  Full zT still needs a relaxation-time model; the other two materials
  also lack kappa_L. All electronic workflows omit explicit SOC.
- The final q-mesh step changes average kappa_L by -2.9559%, but zz by
  -12.2745%. The earlier "~5%" estimate is not a demonstrated tensor or
  total physical uncertainty. Supercell and pair-cutoff convergence remain
  unestablished. No significant imaginary frequency on the sampled mesh
  does not prove stability everywhere.
- `kappa-m15157.hdf5` is a preserved **pre-residual-correction** result,
  not the next point of the corrected mesh ladder.
- The residual-force `awk` in
  `thermo_candidates/SrCu2SnS4/phono3py/scripts/run_campaign.sh` printed zero on
  this Mac for the nonzero pristine log during this audit. Diagnose/test
  numeric handling before a future campaign. Scripts are unchanged; no
  campaign or postprocessing was rerun. Read-only force-comparison checks
  were run. Raw forces and archived `--cfz` evidence support existing results.
- Dense electronic k-mesh/transport-property convergence is not established
  merely by having completed the first-pass pipeline.
- A 2026-09-10 audit of the authoritative `phono3py_disp.yaml` found that all
  included two-displacement pairs at the 4-bohr cutoff have zero pair distance;
  the shortest nonzero pair is about 4.33833 bohr and was excluded.  Therefore
  the preserved SrCu2SnS4 kappa values are a computational record from a very
  short-range/onsite-pair fc3 dataset, not evidence of a 4-A cutoff or
  pair-cutoff convergence.  Frozen sent attachments remain unchanged.
- The residual-force `--cfz` source was also re-audited.  Stage 2 did use the
  archived `checks/pristine/scf.out`: its SCF and complete 96-atom force block
  precede a `seqopn(90)` restart-file error, MPI abort is present in stderr,
  and there is no archived evidence of a separate clean rerun.  The final
  `FORCES_FC3` numerically matches subtraction of that force block, so the
  provenance of the correction is known, but the pristine QE job itself must
  not be described as a healthy completion.  This is an additional limitation
  on the historical first pass, not proof that the written force block is
  numerically wrong.

## Communications and immutable records

- First SrCu2SnS4 submission: sent.
- Second (DOS/Seebeck) and third (three-material first pass) packages:
  sent together and approved by Roy; computational focus approved.
- Fourth package: **in progress**. SrCu2SnS4 interim email sent on
  2026-08-26; `READY_TO_ATTACH/` contains exactly its two frozen
  attachments (CSV + figure). `HOW_WE_GOT_PHONO3PY_WORKING.md` is the
  staged, unsent full writeup; `EMAIL_DRAFT_full_package_unsent.md` is
  superseded reference text.
- CHEM 494A is **Fall 2026**. On 2026-09-10, the user clarified that Winter
  was an earlier email error, corrected with Professor Kleinke before he
  gave conditional approval if Roy continued mentoring. Roy agreed in person;
  the user's 2026-08-28 sent-email screenshot confirms that this agreement was
  reported back to the professor. The old Winter wording is historical error,
  not an active plan. The correction email itself has not been archived.
- The user reports sending the Roy follow-up on 2026-09-06 and still awaiting
  a reply on 2026-09-10. Its source copy, `EMAIL_DRAFT_TO_ROY.md`, contains
  stale Winter wording; preserve the body, do not presume the sent email was
  identical. The new `EMAIL_DRAFT_CONFIRMATION_TO_HOLGER.md` is **not sent**.
  Both files are in `chem494a supervision inquiry/`.
- Current CHEM 494 action: reconfirm the Fall project scope, expected new
  work, any experimental component, temporary remote arrangement and reporting
  frequency with Professor Kleinke, then formally register the supervisor
  with the coordinator (typically via LEARN). No specific supervisor-supplied
  form has been established. See the package README and latest WORKLOG entry
  for evidence and pending questions; official registration is not yet verified.
- Never edit any of the four packages' `READY_TO_ATTACH/` folders.
  Presentation/reproducibility copies are intentional, not cleanup waste.

## Active two-material phonon campaign

### 2026-09-14 00:12 UTC first-pass production snapshot

This snapshot supersedes the older state below. The user redirected the
campaign from extended tooling work to time-bounded first-pass delivery, using
the completed SrCu2SnS4 workflow as the practical model while retaining
explicit scientific limitations.

- **Rb2Cu2SnS4:** full FIRE continuation job `21888372` is running on Nibi
  (32 ranks, 12-hour ceiling). It starts from the terminal coordinates of the
  completed eight-step pilot, uses the same 100/800-Ry, 4x7x7, fixed-cell FIRE
  settings, and has `nstep=100`. Normal FIRE convergence and an independent
  pristine SCF remain required before accepting the structure.
- **SrZrS3:** first-pass force array `21888373` is running on Nibi with tasks
  `0-787%32`, 32 ranks per task and a two-hour task ceiling. Task 0 is pristine
  and the 787 displaced inputs reproduce the archived 2x1x1,
  3.5541348625-A YAML exactly. Inputs use 80/640 Ry, `conv_thr=1e-10`, 3x3x3,
  and `nosym/noinv`. The preceding six-SCF pilot passed duplicate-noise and
  incremental-signal checks.
- Initial submissions `21887921` (Rb) and `21888045` (Sr) failed in about
  three seconds before QE because the first-pass runners used
  `SLURM_SUBMIT_DIR` instead of the explicit run directory. The remaining Sr
  array was cancelled immediately. The corrected runners use a hash-bound
  `P3_RUN_DIR`; both replacement jobs entered real QE 7.3.1 execution on 32
  MPI ranks with one thread each.

These are first-pass production choices, not demonstrated cutoff, supercell,
amplitude, q-mesh, NAC/SOC, or total-uncertainty convergence. No kappa result
exists yet for either remaining material. After terminal jobs: verify exits
and force blocks, rerun only failed Sr indices, construct FC2/FC3, run a
q-mesh ladder, and assemble the report package. No hourly automation exists;
status is checked only when the user resumes this task.

### 2026-09-14 current superseding snapshot

This subsection is the authoritative campaign state. The dated subsections
below are retained as historical snapshots; status words such as `RUNNING`,
pending, or awaiting apply only at their recorded timestamps and are not live
instructions. The authoritative next actions are in `Next research work,
when requested` below.

No phonon or lattice-thermal-conductivity result yet exists for either
remaining material, and no production force job is running.  The queue is
manually monitored; there is no hourly automation.

Rb2Cu2SnS4's fixed-geometry diagnostic completed and passed only its narrow
repeatability/ecutrho-robustness gate.  Primary job `21732222` and collector
`21732223` both completed `0:0`; duplicate RMS force difference was
`1.9245008973e-09 Ry/bohr`, and the 800-to-1000-Ry ecutrho comparison was
`3.5007935608e-07 Ry/bohr` RMS with `1.01e-06 Ry/bohr` maximum-component
difference.  A fresh independent review allowed the single configured BFGS
polish but did not accept a structure.

That unique polish is now terminally blocked.  Primary job `21848175` ended
`FAILED/2:0`; collector `21848176` completed `0:0`.  QE printed `JOB DONE` but
also explicitly reported BFGS nonconvergence after four SCF cycles and three
BFGS steps.  Its final maximum force component, `1.37e-05 Ry/bohr`, remains
above the `1e-05 Ry/bohr` BFGS threshold.  The collector correctly records an
incomplete lineage (collection SHA-256
`d5b4e87c8c69dddb5f1ba484d0a6d2f2dc618be6ec55f8d3e7b8d4611f4d2c83`);
there is no pristine calculation, relax gate, accepted unitcell, preflight, or
force release.  Independent scientific review confirmed that low force and a
zero `pw.x` exit code cannot override failed BFGS convergence.  Do not resubmit
or accept this RUN_DIR.  A genuinely different optimization method would need
a new lineage and its own prior review.

The diagnostic replay-validator software repair is complete: it binds the
approved historical workflow snapshot `cf0b1d1` by its full hash set; treats
the current config/policy as authoritative; requires one historical checkout
root; validates nested collectors against their exact schema; enforces global
Slurm-ID uniqueness; and handles cross-checkout relocation.  Local tests and
fresh reviews passed.  Exact commit `824cbcf` then passed all 333 tests in a
clean Nibi checkout and passed a read-only replay of the real lineage.  The
replay returned `structure_accepted=false` and `preflight_unlocked=false`;
the old run remained at 963 files and its four checked gate/provenance/lineage/
manifest hashes were unchanged.  This validates evidence replay only and does
not authorize another relaxation.

A distinct Rb2Cu2SnS4 FIRE hypothesis now has a locally verified,
**plan-only** preparation boundary.  It can prepare a new lineage only from
the frozen pre-BFGS `polish_reference.in` after replaying the exact historical
configuration, diagnostic chain, failed-relax output, later collector, and
their fixed paths and full context hashes.  It does not use the failed BFGS
terminal geometry.  Public and internal submission paths, both Slurm wrappers,
full planning, finalization, and preflight release remain hard-locked; the
pilot plan exposes no runnable `sbatch` command.  The full local suite passed
353 tests with one optional-spglib skip, both material configurations remained
production-blocked, and a fresh independent review returned `SHIP` for this
plan-only scope.

Exact commit `aab9290a66cc63058584c04ad39a091ff5d13284` then passed all
353 tests in the Nibi phono3py environment from clean checkout
`/scratch/yuhansun/codex-verify-aab9290`.  A replay that treated the real old
lineage as read-only prepared the new plan record under
`/scratch/yuhansun/phono3py-runs/20260914-rb-fire-plan-aab9290/Rb2Cu2SnS4`.
Its receipt SHA-256 is
`f1f4baabe1c4dee3da804eb60e14ba4cc8c23d7a33cf4914a2bcfe9a9b449e74`;
the frozen seed retained SHA-256
`b2f919f7af04a0fd93400e2e5cd021bb489947e245e3d834694167bf2ded714f`.
The generated pilot plan says `execution_released=false` and
`primary_command_template=null`.  The new directory has eight files, no
symlinks, and no attempt/submission files; the old lineage remains at 963
files with the checked hashes unchanged.  Nibi's queue was empty before and
after.  No Slurm job or QE calculation ran, and no structure or scientific
result was accepted.

After that preserved plan-only record, the bounded FIRE pilot chain was
implemented locally on 2026-09-14 and is pending independent review. Current
code can release exactly one eight-step, 32-rank/two-hour pilot only from a
new lineage plus a code-issued receipt binding the exact commit, config,
policy, workflow hashes, seed, resources, and `afterany` collector. The old
`aab9290` RUN_DIR is intentionally unusable after workflow/schema drift.
Collection is evidence-only; independent raw replay/finalization can mark only
`full_review_eligible`. Structure acceptance, preflight, full FIRE, force, and
production remain false and hard-locked. No new lineage has been prepared with
this implementation and no Slurm or QE job has run.

Fresh review subsequently hardened that local-only FIRE implementation before
execution: a code-owned atomic claim globally limits the trusted old lineage to
one new RUN_DIR; exact old-lineage UPF bytes are copied and rehashed; the
primary is held until an exact `afterany` collector attachment is recorded and
then released with its own receipt; and replay distinguishes honest scheduler/
startup failure from malformed provenance while binding QE 7.3.1, the eighth
force step, and the final-coordinate ordering. Rb-focused FIRE/submission/
collector tests pass locally. Full FIRE and every acceptance/downstream gate
remain locked, and no job was submitted.

For SrZrS3, the prior 3.70-A count-only result remains 1003 supercells for
both reviewed supercells and is over the hard cap of 800.  The narrower
2x1x1 count-only job `21850149` completed `0:0`: its raw YAML gives exactly
787 inputs (25 singles + 762 seconds), 147 included groups (122 nonzero), and
the archive validator passed.  The cutoff is `3.5541348625 A`
(`6.71634150010947 bohr`) for a 2x1x1 40-atom supercell; its inscribed radius
is `3.8384532612 A`, giving `0.284318 A` clearance (92.5929%).  The validator
is now a strict, dependency-free system-Python parser of current policy, raw
YAML, checksums, and symlink absence; 333 tests passed and one was skipped, and
a fresh review passed.  This is still **count-only** evidence: the cutoff is
not selected or convergence-qualified, and pilot and production remain blocked.

Both materials still have null approved production core-hour budgets.  Count
evidence cannot unlock force production, and a final submission package cannot
be claimed until each material has an accepted structure, reviewed production
selection, complete force/FC2/FC3 evidence, and convergence-qualified results
or is explicitly reported as scientifically blocked.

### Historical snapshot — 2026-09-11 13:32 UTC

SrZrS3 remains blocked at selection: count-only job `21730034` found exactly
1003 generated displacement supercells for each of the two newly reviewed
3.70-A candidates, so both exceed the hard cap of 800. No Sr force, FC2/FC3,
q-mesh, or kappa job has been released.

Two later Rb2Cu2SnS4 startup attempts also stopped before a scientific SCF and
are preserved as failed evidence. Job `21731206` from `f557d02` failed because
Nibi did not export `SLURM_TIMELIMIT`; collector `21731207` completed and
recorded authoritative `FAILED/2:0`, 6-second accounting. Commit `2a58b59`
added a signed requested-walltime fallback while retaining terminal `sacct`
verification. Job `21731419` then reached `srun` but failed in 9 seconds because
the step inherited the restricted `sbatch --export` policy and therefore could
not resolve `pw.x`; collector `21731420` completed and published only an
incomplete/no-gate record.

Commit `cf0b1d1` now forces nested Slurm steps to inherit the already sanitized,
module-loaded job environment while preserving the submission-side allow-list.
The full local suite passed 298 tests with one optional-spglib skip, a fresh
independent Sol review returned `SHIP`, and all 298 tests passed in a clean
detached Nibi clone. Non-scientific smoke job `21732191` completed `0:0` and
verified that an `srun` step resolves the fixed QE 7.3.1 `pw.x` and all linked
libraries. Earlier smoke job `21732162` failed only an over-strict assertion
that required a literal `LD_LIBRARY_PATH`; its `srun /usr/bin/env` step itself
completed and the record is retained.

A fourth, wholly fresh Rb lineage is under
`/scratch/yuhansun/phono3py-runs/20260911-continuation-cf0b1d1/Rb2Cu2SnS4`.
Diagnostic job `21732222` is `RUNNING` with 32 tasks and a two-hour ceiling;
afterany collector `21732223` is dependency-pending. At the snapshot,
`baseline-a/scf.out` had grown to about 41 KB, showed QE memory setup and the
start of the electronic calculation, and `scf.err` was empty. This confirms
real QE execution, not scientific completion. Do not run `finalize-diagnostic`,
release a BFGS polish, accept a structure, or start preflight/production from
this snapshot. A terminal collector plus a separate evidence review is still
required.

No hourly automation exists; future checks are manual and user-directed.

### Historical snapshot — 2026-09-11 13:06 UTC

The user explicitly authorized Nibi submission. The reviewed code was pushed
on `codex/remaining-two-phonons`, deployed in clean exact-commit clones, and
used only for the two agreed gate calculations. No production force array,
FC2/FC3 construction, q-mesh calculation, or kappa postprocessing was
submitted.

- SrZrS3 count-only preflight job `21730034` completed successfully from
  commit `4e9b64c`. The signed subset contained only
  `sr_fc3_2x1x1__sr_cutoff_3p70A` and
  `sr_fc3_3x1x1__sr_cutoff_3p70A`. Both generated **1003** displacement
  supercells and therefore exceed the 800-displacement cap. The immutable
  inventory records `requested_scope_complete=true`, but
  `preflight_complete=false`, `full_config_preflight_complete=false`, and
  zero selection-eligible candidates. This is cost/geometry evidence, not a
  force, phonon, or thermal-conductivity result.
- The first Rb2Cu2SnS4 diagnostic dispatch, job `21730035` from commit
  `4e9b64c`, failed after 3 seconds before any SCF because the Alliance module
  profile read optional `SKIP_CC_CVMFS` while the stage had shell nounset
  enabled. Its collector `21730036` completed but correctly published no
  scientific gate; it also exposed that the cleaned PATH omitted Nibi's
  `sacct`. The failed run directory and its incomplete accounting receipt are
  preserved unchanged.
- Minimal runtime fix `f557d02` temporarily disables nounset only while
  sourcing the external Alliance profile, restores the caller's shell
  options, and invokes the fixed trusted
  `/opt/software/slurm/bin/sacct`. Local validation passed 293 tests with one
  optional-spglib skip; the Nibi phono3py environment passed all 293 tests.
  A fresh independent Sol review returned `SHIP`.
- A separate fresh Rb2Cu2SnS4 lineage was prepared from the reverified source
  hashes under
  `/scratch/yuhansun/phono3py-runs/20260911-continuation-f557d02/`.
  Diagnostic job `21731206` was `RUNNING` and its afterany collector
  `21731207` was dependency-pending at the 13:06 UTC snapshot. This fixed-
  geometry three-SCF diagnostic cannot accept a structure or release
  preflight by itself. Do not run `finalize-diagnostic` until the collector
  has terminal, complete `COMPLETED/0:0` accounting and the full immutable
  evidence replay passes. Do not release or submit the BFGS polish without a
  separate reviewed decision.

The former hourly automation remains absent. Future status checks are manual
and user-directed.

### Historical milestone — 2026-09-11 local continuation

The user's completed SrCu2SnS4 calculation was audited as the experience
baseline, not as a numerical template. Its retained result is only a historical
first pass under the stricter current contract: the 4.0 cutoff was in bohr,
force settings were mixed, the pristine job was not a healthy completion, and
the corrected q-mesh ladder does not meet the current every-diagonal,
every-temperature, two-step convergence rule. No cutoff, force, residual, or
mesh threshold was copied automatically to the other materials.

Local commit `e524d6e` prepares the next evidence-gated steps without running
QE or phono3py:

- SrZrS3 can import the already accepted recovery structure into a fresh,
  self-contained run directory after replaying and archiving its complete
  structure evidence. The new 2x1x1/3.70-A and 3x1x1/3.70-A combinations are
  count-only hypotheses and cannot become production settings from count
  evidence alone.
- Rb2Cu2SnS4 retains both BFGS failures. A separate three-SCF diagnostic uses
  two identical 100/800-Ry inputs and one 100/1000-Ry input at the terminal
  one-reset geometry. A pass may release at most one fresh, small-trust-radius
  BFGS polish; it still cannot replace normal BFGS convergence, an independent
  pristine SCF, or the ordinary structure gate.
- Production-force finalization now requires complete task/submission/
  accounting/raw-evidence replay and a path-safe, prefix-checked resource
  ledger before it can publish a force-dataset gate. That gate claims only
  readiness to construct FC2/FC3, not a phonon or kappa result.

Independent review ended at `ship`. The full local suite passed 259 tests with
one optional-spglib skip; both material configs validate healthy, Python
compilation, Slurm shell syntax, and Git whitespace checks pass. Both
production selections remain null, automatic submission is false, approved
core-hour budgets remain null, and public `postprocess`/final `audit` are still
unreleased. No remote import, diagnostic, preflight, force, FC2/FC3, or kappa
calculation was run. Live Nibi state is still unverified because interactive
MFA is required. The former hourly automation has been removed; future checks
are manual/user-directed.

The historical fail-closed recovery workflow is on GitHub branch
`codex/two-material-phonons`.
The original failed chains used commit `92d973a` in the frozen clean clone
`/scratch/yuhansun/Waterloo-prof-Holger-phonons-20260910` and run directories
under `/scratch/yuhansun/phono3py-runs/20260910/`. The reviewed one-reset
recovery started from commit `20e079f` in a separate clean clone
`/scratch/yuhansun/Waterloo-prof-Holger-phonons-recovery-20e079f` and separate
run directories under
`/scratch/yuhansun/phono3py-runs/20260910-recovery-20e079f/`. After the
structure evidence was frozen, that checkout was fast-forwarded to `0586c6b`
for two reviewed preflight/submission fixes; each attempt records its exact
campaign-code hash and Git commit.

The following recovery-state block is historical. At 2026-09-10 15:11 UTC,
the user's queue was empty:

A fresh read-only SSH query was attempted on 2026-09-11 at 04:18 UTC, but the
eight-hour ControlMaster socket no longer existed and Nibi required interactive
MFA.  That failed authentication produced no newer scheduler, log, or artifact
evidence. At that time, the 2026-09-10 15:11 UTC block below remained the latest
verified remote state. The 2026-09-13 current snapshot above supersedes it.

- Rb2Cu2SnS4 recovery tight-relax `21656285`: FAILED with exit `2:0` after
  4 SCF cycles / 3 BFGS steps; collector `21656286`: COMPLETED. QE wrote
  `history already reset at previous step: exiting` followed by explicit
  BFGS nonconvergence. The last total force was `6.7e-5 Ry/bohr` and the
  strict-parser maximum component was `1.768e-5 Ry/bohr`; pw.x itself returned
  zero, `JOB DONE` is present, and stderr is empty. Those low forces do not
  replace normal BFGS convergence. No pristine SCF or accepted gate exists.
- SrZrS3 recovery tight-relax `21656287`: COMPLETED; collector `21656288`:
  COMPLETED. The immutable gate passed after normal BFGS convergence and a
  healthy independent pristine SCF. Relax/pristine maximum components were
  `9.87e-6` and `1.046e-5 Ry/bohr`; the maximum cumulative position shift was
  `0.0018848 A`, and Pnma remained present from `1e-6` through `1e-3 A`
  symmetry tolerances.
- SrZrS3 count/geometry/unit preflight `21657046` FAILED before selection
  because a too-tight lattice comparison rejected the harmless difference
  between the configured and phono3py Bohr constants. No force task ran.
  The corrected immutable attempt `21657673` COMPLETED in 1m50s. All five
  routine candidates exceeded the configured 800-displacement hard cap:
  3x2x1/4 A = 1379, 3x2x1/5 A = 2047, 4x2x1/4 A = 1379,
  4x2x1/5 A = 2047, and 4x2x1/6 A = 3747. The uncut counts are 11625 and
  15225. The inventory therefore has zero selection-eligible candidates and
  still requires explicit scientific/resource review.

Both recovery inputs recorded `restart_mode='from_scratch'`, atomic starting
potentials/wavefunctions, unchanged material-specific cutoffs and k meshes,
and no reuse of the old QE scratch. Only SrZrS3 reached an accepted structure.
No force array, FC2/FC3 construction, q-mesh calculation, or kappa
postprocessing has been submitted for either pending material.

Original chains and failure evidence:

- Rb2Cu2SnS4 tight-relax job `21638193`: FAILED the strict scientific gate
  after QE stopped with `bfgs failed ... convergence not achieved`; its
  afterany evidence collector `21638194` COMPLETED and archived the attempt.
- SrZrS3 tight-relax job `21638199`: FAILED the strict scientific gate after
  QE stopped with `bfgs failed ... convergence not achieved`; its afterany
  collector `21638200` COMPLETED and archived the failed attempt.

Rb2Cu2SnS4 stopped after 13 SCF / 12 BFGS steps. Its total force decreased
from `8.92e-4` to `8.2e-5 Ry/bohr` and its last largest force component was
`2.331e-5 Ry/bohr`. The QE output has final coordinates and `JOB DONE`, empty
stderr, and no separate QE, MPI, OOM, or time-limit fatal marker, but the small
force does not override the explicit BFGS nonconvergence. SrZrS3 likewise had
normally completed individual SCFs and pw.x, but no BFGS convergence marker
after 20 SCF / 19 ionic steps; its last total force was `3.6e-5 Ry/bohr` and
largest component about `1.097e-5 Ry/bohr`. Neither material produced a
pristine calculation, execution manifest, or accepted structure gate.
Preserve both failures and use separately audited new runs for any
continuation; never relabel either failed relaxation as successful.

The recovery primary jobs request account `def-kleinke_cpu`, 32 tasks,
62.5 GiB, and
12 hours. They run fixed-cell BFGS followed by an independent setting-matched
pristine SCF and publish no structure unless the strict force, completion,
position, atom-order, cell, and symmetry gate passes. Only a no-force
phono3py count/geometry/unit preflight is released after that gate. Force
arrays, FC2/FC3 construction, kappa postprocessing, and final claims remain
blocked pending real pilot evidence and an explicit production selection.
No scheduled heartbeat remains. Any manual status check must query current
scheduler/evidence state and must not treat these recorded job IDs as live.
Both original job chains are now terminal. Keep their submission-time clone
and scripts frozen for provenance; deploy reviewed recovery/downstream code in
a separate clean checkout that consumes the original hashed evidence.

## Next research work, when requested

1. Rb2Cu2SnS4 is terminal for the present first-pass ladder: force recovery and
   limited artifact audit pass, but q-mesh convergence fails. Do not rerun the
   completed force array or promote the 105-A tensor. Any denser-mesh or broader
   convergence study needs a separately reviewed scientific plan and explicit
   execution authorization.
2. SrZrS3 remains rejected by the sampled imaginary-mode gate. Decide
   scientifically whether to investigate the instability or stop this lane;
   do not promote its finite diagnostic tensor.
3. SrCu2SnS4 has a separate `phono3py_v2/` preparation-only package with the
   intended 4-A cutoff converted to 7.5589045 bohr and uniform force settings.
   It has not generated a real displacement set, run pristine QE, or submitted
   Slurm work. Those steps require separate review and authorization.
4. For any continued material, establish amplitude, basis/cutoff, force-k-mesh,
   supercell, q-mesh, and NAC-sensitivity decisions independently; do not infer
   convergence from cost, file existence, scheduler success, or one sampled
   stability gate.
5. Assemble the full three-material phonon writeup/package only when the
   scientific status supports it; keep every existing attachment frozen.

Use [DRAC_SETUP.md](DRAC_SETUP.md) and the campaign
[README](thermo_candidates/SrCu2SnS4/phono3py/README.md).
Heavy calculations **and phonon postprocessing run on DRAC**, not local
machines. Do not infer live cluster status from the snapshot above or from
archived jobs; query Slurm and immutable attempt evidence.

Detailed failed attempts, job IDs, and communications remain in the
fourth-step `WORKLOG.md`. The previous full handoff is preserved verbatim
in [the historical snapshot](docs/archive/HANDOFF_2026-08-30.md); its old
launch commands, "current chain", and package instructions are superseded.

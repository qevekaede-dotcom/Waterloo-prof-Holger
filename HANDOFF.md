# Research handoff — current state

Last repository/evidence audit: 2026-09-10. Research state reconciled from
GitHub commit `0024114291043468c69f1d3a382cee51b64428d3` (2026-08-30),
on `claude/canada-computing-center-task-d165w2`. That branch includes
the other two Claude branches and was 13 commits ahead of `main`.
The research and cleanup were merged into **`main`** through
[PR #1](https://github.com/qevekaede-dotcom/Waterloo-prof-Holger/pull/1)
on 2026-09-06 (merge commit `88c2da2`). Resume from `main`.
The temporary `codex/research-repository-cleanup` branch was deleted locally
and on GitHub; all its commits are retained in `main`. Other research
branches were left unchanged. See [audit](docs/REPOSITORY_AUDIT.md).

Read [CLAUDE.md](CLAUDE.md) for standing rules and [AGENTS.md](AGENTS.md)
for continuity. This file records state, not authorization to launch work.

## Verified completed work

| Material | Electronic first pass | Sampled PBE gap [calculated] | Lattice thermal conductivity |
| --- | --- | --- | --- |
| SrCu2SnS4 | QE + BoltzTraP2 complete | 0.3445 eV | First pass complete |
| SrZrS3 | QE + BoltzTraP2 complete | 0.6096 eV | Structure gate passed; preflight over cap; no kappa result |
| Rb2Cu2SnS4 | QE + BoltzTraP2 complete | 0.7811 eV | One-reset recovery failed BFGS; no kappa result |

Each electronic pass includes independent convergence tests, vc-relax,
final SCF, dense NSCF, and 300–900 K transport tables. Evidence:
`thermo_candidates/<material>/results/workflow_summary.md`, adjacent CSVs,
QE logs, and BoltzTraP2 trace/tensor files.
[Three-material comparison](learning/05_comparing_materials.md) explains
carrier preference; reported zT_e comparisons use PF-selected grid points,
not independently optimized zT_e.

SrCu2SnS4 lattice evidence: `thermo_candidates/SrCu2SnS4/phono3py/` and
`thermo_candidates/SrCu2SnS4/results/`. All 168 displacement outputs have
completed SCF/force records. Residual-corrected `kappa-m13136.hdf5` matches
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

The fail-closed workflow is on GitHub branch `codex/two-material-phonons`.
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

Live scheduler/evidence state last checked 2026-09-10 15:11 UTC; the user's
queue was empty:

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
The active hourly Codex heartbeat reports live scheduler/evidence changes and
must not treat these recorded job IDs as future live state without querying.
Both original job chains are now terminal. Keep their submission-time clone
and scripts frozen for provenance; deploy reviewed recovery/downstream code in
a separate clean checkout that consumes the original hashed evidence.

## Next research work, when requested

1. Rb2Cu2SnS4 requires scientific review before another ionic continuation.
   The allowed one-reset path is exhausted, and a second automatic reset is
   deliberately rejected. Do not infer acceptance from the small final force.
2. SrZrS3 requires an explicit new cutoff/supercell/resource selection because
   every declared routine preflight candidate exceeds the 800-task cap. Do not
   raise the cap or launch a pilot merely to bypass this gate; first review a
   scientifically defensible smaller cutoff or alternative strategy and cost.
3. For each material independently, run amplitude, basis/cutoff, force-k-mesh,
   supercell, q-mesh, and NAC-sensitivity decisions. Do not copy SrCu2SnS4
   numerical settings or infer a production choice from cost alone.
4. Re-preflight SrCu2SnS4 using explicitly converted Angstrom-to-bohr cutoffs
   before estimating cost; the historical "5.0 A / 600 supercells" proposal
   was based on the same unit misunderstanding and is not a valid 5-A budget.
   Pair-cutoff, supercell, and tensor q-mesh convergence remain unperformed.
5. Assemble the full three-material phonon writeup/package when supported
   by results; keep interim attachments frozen.

Use [DRAC_SETUP.md](DRAC_SETUP.md) and the campaign
[README](thermo_candidates/SrCu2SnS4/phono3py/README.md).
Heavy calculations **and phonon postprocessing run on DRAC**, not local
machines. Do not infer live cluster status from the snapshot above or from
archived jobs; query Slurm and immutable attempt evidence.

Detailed failed attempts, job IDs, and communications remain in the
fourth-step `WORKLOG.md`. The previous full handoff is preserved verbatim
in [the historical snapshot](docs/archive/HANDOFF_2026-08-30.md); its old
launch commands, "current chain", and package instructions are superseded.

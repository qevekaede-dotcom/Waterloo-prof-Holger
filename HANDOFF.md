# Research handoff — current state

Last repository/evidence audit: 2026-09-06. Research state reconciled from
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
| SrZrS3 | QE + BoltzTraP2 complete | 0.6096 eV | No campaign records yet |
| Rb2Cu2SnS4 | QE + BoltzTraP2 complete | 0.7811 eV | No campaign records yet |

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
4.0 A pair cutoff, 3x3x3 force k mesh, final phonon q mesh 13x13x6.
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

## Communications and immutable records

- First SrCu2SnS4 submission: sent.
- Second (DOS/Seebeck) and third (three-material first pass) packages:
  sent together and approved by Roy; computational focus approved.
- Fourth package: **in progress**. SrCu2SnS4 interim email sent on
  2026-08-26; `READY_TO_ATTACH/` contains exactly its two frozen
  attachments (CSV + figure). `HOW_WE_GOT_PHONO3PY_WORKING.md` is the
  staged, unsent full writeup; `EMAIL_DRAFT_full_package_unsent.md` is
  superseded reference text.
- CHEM 494A supervision inquiry: drafted, no sent outcome recorded.
  See `chem494a supervision inquiry/`.
- Never edit any of the four packages' `READY_TO_ATTACH/` folders.
  Presentation/reproducibility copies are intentional, not cleanup waste.

## Next research work, when requested

1. Resolve the residual-force reporting issue and review cluster traps.
2. SrZrS3 phonons with independent convergence decisions and pristine-force
   checks; then Rb2Cu2SnS4. Do not copy SrCu2SnS4 numerical settings.
3. Optionally tighten SrCu2SnS4 pair cutoff (5.0 A / 600 supercells was
   proposed) and supercell/q-mesh convergence; not yet performed.
4. Assemble the full three-material phonon writeup/package when supported
   by results; keep interim attachments frozen.

Use [DRAC_SETUP.md](DRAC_SETUP.md) and the campaign
[README](thermo_candidates/SrCu2SnS4/phono3py/README.md).
Heavy calculations **and phonon postprocessing run on DRAC**, not local
machines. Do not infer live cluster status from archived jobs.
No cluster connection or calculation was made during this cleanup.

Detailed failed attempts, job IDs, and communications remain in the
fourth-step `WORKLOG.md`. The previous full handoff is preserved verbatim
in [the historical snapshot](docs/archive/HANDOFF_2026-08-30.md); its old
launch commands, "current chain", and package instructions are superseded.

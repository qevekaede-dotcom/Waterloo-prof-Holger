# Research background

Written in my own words as the standing context for this repository. The
group's internal materials (the ML screening dataset, group slides, and
correspondence) are deliberately **not** in this public repo; they stay on
the local machine and move between my machines by direct copy only.

## The project

I am an undergraduate working with the Kleinke group (University of
Waterloo) under the mentorship of a graduate student, Roy. The group studies
**thermoelectric materials** — materials that convert heat differences into
electricity. The performance number everyone optimizes is the dimensionless
figure of merit

```text
zT = S^2 * sigma * T / (kappa_e + kappa_L)
```

- S — Seebeck coefficient (voltage per unit temperature difference)
- sigma — electrical conductivity
- kappa_e — electronic thermal conductivity
- kappa_L — lattice (phonon) thermal conductivity
- T — absolute temperature

A good thermoelectric conducts electricity well but heat poorly.

## Where the candidates come from

A machine-learning model built by another group member predicts zT for a
large set of compounds. From that ranking, with the professor's constraints
(candidates must be experimentally observed in Materials Project, band gap
below 1.0 eV, several high-zT picks), three sulfides were selected for
first-principles follow-up (selection reasoning:
`thermo_candidates/Roy_task_status.md`):

1. **SrCu2SnS4** (mp-16988) — high-ranked, moderate gap, no problematic
   elements; the workhorse first calculation.
2. **SrZrS3** — chemically simple; predicted zT within noise of
   higher-ranked entries.
3. **Rb2Cu2SnS4** — rank 1 in the screening; Rb chemistry slightly less
   convenient experimentally.

## What has been computed so far [calculated, PBE, no SOC]

For each material: its own convergence tests, variable-cell relaxation,
final SCF, dense NSCF (Quantum ESPRESSO), then BoltzTraP2 transport tables
300-900 K. Sampled PBE gaps: 0.3445 / 0.6096 / 0.7811 eV. On the sampled
carrier grids, p-type is favored for SrCu2SnS4 and Rb2Cu2SnS4; n-type for
SrZrS3 (by electronic-only zT_e). Full comparison:
`learning/05_comparing_materials.md`.

House rules for reading any number in this repo: `PF/tau` is never an
absolute power factor; electronic-only `zT_e` is never the final zT; "best"
means best point on the sampled grid; every workflow has its own convergence
parameters (`CLAUDE.md` has the full list).

## Current phase: lattice thermal conductivity

Every zT_e above omits **kappa_L from the denominator** and is not full zT.
The current task (professor's recommendation, via Roy) is to
compute it with **phono3py**: third-order force constants from displaced
supercells -> phonon-phonon scattering -> kappa_L(T). Status and the
step-by-step story (including failed attempts): the WORKLOG in
`fourth step result (phono3py lattice thermal conductivity)/` and
`thermo_candidates/SrCu2SnS4/phono3py/README.md`. The 168-displacement force
campaign for SrCu2SnS4 is complete on DRAC/Nibi. Residual-corrected first-pass
average kappa_L [calculated] is 0.3639 W m^-1 K^-1 at 300 K and 0.1213 at
900 K (RTA, no SOC, no NAC, 2x2x1 supercell, 4.0 A pair cutoff).
The q-mesh average met the recorded 3% stopping criterion, but the final
zz change was about 12%; this is not a demonstrated 5% tensor uncertainty.
Full supercell/pair-cutoff convergence and an electronic relaxation-time
model remain outstanding.

The SrCu2SnS4 interim email was sent; the full three-material phonon
writeup is still staged. Next research work is SrZrS3 phonons, then
Rb2Cu2SnS4, each with independent convergence decisions. Heavy calculations
and phonon postprocessing run on DRAC; local machines handle preparation,
transfer, Git, writeup, and lightweight read-only checks. See `HANDOFF.md`
for current state and `DRAC_SETUP.md` for the recorded cluster workflow.

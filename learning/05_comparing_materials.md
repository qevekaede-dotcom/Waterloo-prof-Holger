# Comparing materials and judging a candidate

This document teaches you how to place two (soon three) materials side by side
and decide, honestly, which one still looks promising after the first
computational pass. It assumes you have read the pipeline playbook
(`04_per_material_playbook.md`) or at least sections 1-4 of
`../WORKFLOW_EXPLAINED.md`, which define every term used here (DFT, PBE,
k-mesh, SCF/NSCF, BoltzTraP2, tau, and so on). Where a concept needs theory,
this document points at the numbered section of `../WORKFLOW_EXPLAINED.md`
instead of repeating it. Paths below are relative to this `learning/` folder,
and every path in this workspace contains spaces, so always quote paths in
shell commands.

**House rules that govern every sentence here** (decoded in
`../WORKFLOW_EXPLAINED.md` section 8.3): `PF/tau` is a power factor *divided
by an unknown relaxation time* and is never an absolute power factor; the
electronic `zT_e` is never the final `zT` (tau cancels inside it, but the
lattice thermal conductivity `kappa_L` is missing); every run is
scalar-relativistic PBE with **no explicit spin-orbit coupling (SOC)**; a
"best" value is the best point on the sampled temperature/doping grid, not a
continuous optimum; and convergence parameters belong to one material only --
they are never reused across materials.

Values are tagged [calculated] (our own QE / BoltzTraP2 output), [database]
(copied from the Materials Project-filtered candidate list), or
[experimental] (measured in a lab -- none appear in this document, because we
have no lab data yet).

**Status note.** All three materials have now finished their first
scalar-relativistic PBE pass, including Rb2Cu2SnS4
(`../thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md`). Every cell in
the comparison table below is now a real [calculated] value.

---

## 1. What this project screens FOR

Before comparing anything, know what the comparison is *for*. Roy's screening
rules (recorded in `../thermo_candidates/Roy_task_status.md` and
`../thermo_candidates/README.md`) define the target:

- **Already filtered through the Materials Project**: candidates come from a
  renewed list that was pre-screened in that database, so their structures and
  listed properties are [database] values, not ours.
- **Experimentally observed**: the crystal must actually exist in a lab
  somewhere, not just in a computer. (Whether a structure "has been observed"
  is itself [database] information -- it says the compound has been made, not
  that anyone measured its thermoelectric properties.) This matters because a
  collaborator will eventually have to synthesize the winner.
- **Band gap below 1.0 eV**: good thermoelectrics are narrow-gap
  semiconductors (see section 3 below for why).
- **High predicted zT**: the renewed list carries a model-predicted
  thermoelectric figure of merit for each entry. These are *someone else's
  model numbers*, used only for ranking what to try first.
- **Element constraints**: no Hg, Tl, U, Pb, As, Cd, or Be
  (`../thermo_candidates/README.md`), and rare-earth f-electron complications
  are avoided (`../thermo_candidates/SrCu2SnS4/notes/material_choice.md`) --
  the backup candidate BaPr(SnS3)2 was set aside precisely because it
  contains Pr (`../thermo_candidates/Roy_task_status.md`). The reasons are
  toxicity, radioactivity, cost, synthesis headaches, and (for rare earths)
  DFT itself becoming much harder to trust.

The three survivors, with their screening-list numbers (all [database], from
`../thermo_candidates/README.md`):

| Priority (-) | Candidate | Renewed-list rank (-) | Predicted zT (dimensionless) | Listed band gap (eV) |
|---:|---|---:|---:|---:|
| 1 | SrCu2SnS4 | 10/11 | 1.895 | 0.4032 |
| 2 | SrZrS3 | 16 | 1.894 | 0.5512 |
| 3 | Rb2Cu2SnS4 | 1 | 1.896 | 0.8641 |

Notice the predicted zT values differ only in the third decimal. The
screening list *cannot* rank these three against each other -- which is
exactly why we run our own first-principles pass on each: to check whether
the database's optimism survives contact with an explicit band structure.

---

## 2. Why every material gets the same temperature/doping grid

A comparison is only fair if both materials are asked the same question. Every
BoltzTraP2 transport run in this project therefore uses the identical grid:

- **Temperatures**: 300 to 900 K in 100 K steps (7 temperatures).
- **Carrier densities**: 14 signed levels -- 1e19, 2e19, 5e19, 1e20, 2e20,
  5e20, and 1e21 cm^-3, once for n-type (electron) and once for p-type (hole)
  doping. "Signed" means the sign encodes the carrier type. The exact list is
  hard-coded as `doping_levels` in
  `../thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh`.

You can verify this yourself: `../thermo_candidates/SrZrS3/results/transport_full.csv`
has exactly 98 rows = 14 densities x 7 temperatures [calculated], and the
SrZrS3 work log records that the run script was fixed to use "the explicit
14-level list used for SrCu2SnS4" for comparability -- including repairing a
half-open `300:900:100` temperature range that would have stopped at 800 K
(`../thermo_candidates/SrZrS3/WORKLOG.md`). (If you open the CSV you will see
densities like 9.994e18 instead of exactly 1e19 -- BoltzTraP2 solves for the
chemical potential that gives the *requested* density and reports the achieved
one; the tiny mismatch is numerical, not physical.)

Why this matters: if material A were sampled at 350 K and 3e19 cm^-3 and
material B at 700 K and 1e21 cm^-3, any difference between their numbers would
mix "different material" with "different question". With a shared grid, a row
in one material's table has an exact counterpart in the other's. Two cautions
travel with this convenience:

- **Best-on-grid, always.** The true optimum density could sit between grid
  points (say at 3e20 cm^-3, which we never sampled). Every "best" below is
  the best of the 14 sampled densities at that temperature -- nothing more.
- **The shared grid is a *question*, not a convergence parameter.** The
  convergence parameters (cutoffs, k-meshes) are **not** shared: those must
  be re-tested per material so that each material is *equally well
  converged*, which is a different requirement from being *identically
  sampled*. See `../WORKFLOW_EXPLAINED.md` section 6.1 for the full argument.

One more deliberate cross-material standard: the dense-NSCF meshes are chosen
to a common *k-spacing* target of roughly 0.08 A^-1, which produces different
mesh integers per cell -- 12x12x6 for SrCu2SnS4 (spacing
0.082/0.082/0.067 A^-1), 20x10x6 for SrZrS3 (0.082/0.073/0.075 A^-1), and
8x14x14 chosen for Rb2Cu2SnS4 (0.088/0.088/0.090 A^-1, a stated ~10%
deviation to keep the cost sane) -- so the band structures feeding BoltzTraP2
are comparably resolved (`../thermo_candidates/SrZrS3/WORKLOG.md`,
`../thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`).

---

## 3. The metric hierarchy: what each number may and may not be used for

The transport tables contain several columns. They are **not equally
trustworthy**, and they answer different questions. Learn this hierarchy
before quoting anything.

### 3.1 Band gap [calculated, PBE, systematically underestimated]

The band gap is the energy window with no electronic states (theory:
`../WORKFLOW_EXPLAINED.md` section 3.6). Our gaps are PBE gaps, and PBE
(the exchange-correlation approximation we use) is *known* to underestimate
real gaps -- so treat our values as lower bounds on reality, useful for
*relative* reasoning between materials computed the same way.

**The gap window logic.** A thermoelectric gap can fail in two directions:

- **Too small**: at high temperature, heat excites electrons across the gap
  even in a doped sample, so electrons and holes conduct *simultaneously*
  ("bipolar conduction"). Their Seebeck contributions have opposite signs and
  partially cancel, so the useful voltage shrinks exactly where a generator
  operates.
- **Too large**: hard to dope to useful carrier densities, and the screening
  rule (gap < 1.0 eV) already excludes these.

**Worked contrast.** SrCu2SnS4 has a QE-PBE indirect gap of 0.3445 eV
[calculated, `../thermo_candidates/SrCu2SnS4/results/workflow_summary.md`],
while SrZrS3 has a sampled PBE gap of 0.6096 eV [calculated,
`../thermo_candidates/SrZrS3/results/workflow_summary.md`] -- about 1.8x
larger. Both are inside the screening window, but the smaller SrCu2SnS4 gap
makes bipolar losses bite earlier. You can *see* this in the
Seebeck-vs-chemical-potential scan
(`../thermo_candidates/SrCu2SnS4/results/seebeck_vs_mu.md` and the
accompanying `seebeck_vs_mu.csv`, all [calculated]): at 300 K the Seebeck
peaks reach +644 uV/K (p-side, at mu - E_F = +0.151 eV) and -548 uV/K
(n-side, at +0.241 eV), but by 900 K they have shrunk to +298 and -191 uV/K,
because minority carriers activate across the 0.3445 eV PBE gap and
compensate the majority signal. That factor-of-two-plus shrinkage *is*
bipolar conduction in action. (Those peak chemical potentials lie *inside*
the gap, where a real sample would be intrinsic; practically doped samples
sit closer to the band edges with smaller |S|.) SrZrS3, with the larger gap,
holds its best-point n-type Seebeck between -136 and -174 uV/K across
400-900 K (`../thermo_candidates/SrZrS3/results/workflow_summary.md`).
Caveat both ways: since PBE underestimates gaps, the real bipolar onset is
probably at higher temperature than our curves suggest -- the durable
statement is the *relative* one ("SrZrS3's gap is larger"), not the exact
onset. See `../WORKFLOW_EXPLAINED.md` section 5.2 for how to read the
Seebeck figure itself.

### 3.2 Seebeck coefficient S [calculated, absolute under CRTA]

S (in uV/K) is the voltage a temperature difference produces; its sign tells
the carrier type -- positive for holes (p-type), negative for electrons
(n-type) (theory: `../WORKFLOW_EXPLAINED.md` section 3.8). Within the
constant-relaxation-time approximation (CRTA -- assume every electron
scatters after the same unknown time tau), tau cancels in the formula for S
(`../thermo_candidates/SrCu2SnS4/results/seebeck_vs_mu.md` states and checks
this: the mu-scan gives 157.4 uV/K where the doped table has 157.2 uV/K). So
**S is an absolute calculated number** within the stated approximations
(rigid band, polycrystalline average, PBE gap, no SOC), and you *may* compare
S directly across materials: +157.2 uV/K for SrCu2SnS4 (p-type, 1e20 cm^-3,
300 K) against -134.4 uV/K for SrZrS3 (n-type, 5e19 cm^-3, 300 K) is a
legitimate apples-to-apples statement [both calculated, from the two
`results/workflow_summary.md` files].

### 3.3 PF/tau [calculated, relative -- NEVER an absolute power factor]

The power factor PF = S^2 * sigma measures useful electrical output. But our
sigma comes out of BoltzTraP2 only as sigma/tau -- conductivity *divided by
the unknown scattering time tau*. So the tables report **PF/tau** in
W m^-1 K^-2 s^-1 (note the extra s^-1 -- that unit is the giveaway that a tau
is missing). Say this loudly and repeat it:

> **PF/tau is not a power factor. It may be compared between materials ONLY
> under the explicit, unverified assumption that the two materials have
> similar tau.**

Different crystals scatter electrons differently -- tau depends on phonons,
defects, and doping in each specific material -- so this assumption can be
badly wrong; an electron-phonon calculation or experimental mobility data
would replace it. Within one material, PF/tau comparisons across doping and
temperature are safer (same material, same rough scattering physics), which
is how the "best sampled PF/tau" rows are meant to be used.

### 3.4 zT_e [calculated, upper bound -- NEVER the final zT]

zT_e is the figure of merit computed with **only the electronic** thermal
conductivity kappa_e in the denominator. Conveniently, tau cancels between
numerator and denominator under CRTA -- but the lattice thermal conductivity
kappa_L (heat carried by atomic vibrations) is **missing entirely**, and
kappa_L always adds to the denominator, so real zT is always lower. zT_e is
an *upper bound and a screening signal*, never the ranking number and never
the final zT. The full argument is `../WORKFLOW_EXPLAINED.md` sections 1.2
and 8 (and the FAQ in section 10 dismantles "so we predicted zT = 1.9?").

### 3.5 Carrier-type preference: always quote BOTH orderings

Which doping sign is better? PF/tau and zT_e can *disagree*, so quote both.
SrZrS3 is our cautionary example [calculated, both metrics from
`../thermo_candidates/SrZrS3/results/workflow_summary.md`, narrated in
`../thermo_candidates/SrZrS3/WORKLOG.md`]. Best sampled points per
temperature:

| T (K) | n best PF/tau (W m^-1 K^-2 s^-1) | p best PF/tau (W m^-1 K^-2 s^-1) | PF/tau winner (-) | n zT_e at best-PF point (-) | p zT_e at best-PF point (-) | zT_e winner (-) |
|---:|---:|---:|:---:|---:|---:|:---:|
| 300 | 4.080e10 | 3.675e10 | n | 0.894 | 0.846 | n |
| 400 | 5.944e10 | 5.444e10 | n | 1.376 | 0.695 | n |
| 500 | 7.997e10 | 1.005e11 | p | 0.962 | 0.195 | n |
| 600 | 1.004e11 | 1.538e11 | p | 1.286 | 0.312 | n |
| 700 | 1.185e11 | 2.061e11 | p | 1.625 | 0.442 | n |
| 800 | 1.343e11 | 2.544e11 | p | 1.016 | 0.581 | n |
| 900 | 1.515e11 | 2.981e11 | p | 1.226 | 0.727 | n |

- By **zT_e** at the best-PF/tau operating point, the n-type value exceeds
  the p-type value at *every* sampled temperature.
- By **PF/tau**, the p-type best overtakes the n-type best at 500 K and
  above -- and every one of those p-type wins is the heavily doped
  1e21 cm^-3 grid point.

Both statements are true simultaneously because kappa_e grows with doping:
the 1e21 cm^-3 p-type point buys a big S^2*sigma/tau but pays for it with so
much electronic heat conduction that its zT_e collapses (0.442 vs 1.625 at
700 K). A single-metric summary would flip the recommended dopant depending
on which column you happened to read. SrCu2SnS4 has a milder version of the
same lesson: p-type wins by PF/tau at every sampled temperature, but by zT_e
the n-type best actually edges ahead at 400 K (0.514 vs 0.498) and 500 K
(0.771 vs 0.769) before p-type takes over again [calculated,
`../thermo_candidates/SrCu2SnS4/results/workflow_summary.md`]. Rule: report
the pair, name the metric, name the grid point.

---

## 4. The worked comparison: all three candidates

Sources: the three `../thermo_candidates/<material>/results/workflow_summary.md`
files, the `WORKLOG.md` files, and the SrCu2SnS4 volume line in
`../thermo_candidates/SrCu2SnS4/CLAUDE.md`. All transport rows are
best-on-sampled-grid values under CRTA, scalar-relativistic, no SOC.
Units sit in each row label.

| Quantity (unit) | SrCu2SnS4 | SrZrS3 | Rb2Cu2SnS4 |
|---|---|---|---|
| MP structure id (-) [database] | mp-16988 | mp-558760 (not the mp-5193 polymorph) | mp-18006 |
| Space group after relaxation (-) [calculated] | P3_121 (No. 152), kept | Pnma (No. 62), kept | Ibam (No. 72), kept |
| Own converged cutoffs (Ry) [calculated] | 90/720 | 50/400 | 90/720 |
| Relax / final-SCF k mesh (-) [calculated] | 4x4x2 / 5x5x3 | 6x3x2 / 8x4x2 | 2x4x4 / 3x5x5 |
| Dense NSCF mesh (irreducible points) [calculated] | 12x12x6 (100) | 20x10x6 (264) | 8x14x14 (788) |
| Bands total / occupied (-) [calculated] | 140 / 105 | 108 / 80 | 105 / 78 |
| PBE gap (eV) [calculated] | 0.3445 (indirect) | 0.6096 (sampled) | 0.7811 (sampled) |
| Listed gap (eV) [database] | 0.4032 | 0.5512 | 0.8641 |
| Predicted zT (dimensionless) [database] | 1.895 | 1.894 | 1.896 |
| Relaxation volume drift (A^3, %) [calculated] | 543.884 -> 546.507, +0.48% | 461.535 -> 464.463, +0.63% | 446.410 -> 450.561, +0.93% |
| Favored carrier by PF/tau (-) [calculated] | p-type at every sampled T | n-type at 300-400 K; p-type at >= 500 K (the 1e21 cm^-3 points) | p-type at every sampled T |
| Favored carrier by zT_e (-) [calculated] | p-type, except n-type edges ahead at 400 K and 500 K | n-type at every sampled T | p-type at every sampled T |
| Peak zT_e among the best-PF/tau points (dimensionless) [calculated] | 1.898 at 800 K, p-type, 5.00e20 cm^-3 | 1.625 at 700 K, n-type, 1.00e20 cm^-3 | 6.419 at 900 K, p-type, 1.00e21 cm^-3 |
| Largest sampled PF/tau (W m^-1 K^-2 s^-1) [calculated] | 2.144e11 at 900 K, p-type, 1.00e21 cm^-3 | 2.981e11 at 900 K, p-type, 1.00e21 cm^-3 | 1.981e11 at 700 K, p-type, 9.99e20 cm^-3 |
| S at 300 K best-PF/tau point (uV/K) [calculated] | +157.2 (p, 1.00e20 cm^-3) | -134.4 (n, 5.00e19 cm^-3) | +199.7 (p, 5.00e20 cm^-3) |
| S at 700 K best-PF/tau point (uV/K) [calculated] | +161.0 (p, 5.00e20 cm^-3) | +97.7 (p, 1.00e21 cm^-3); the n-type zT_e-best has -173.8 (1.00e20 cm^-3) | +211.7 (p, 9.99e20 cm^-3) |

How to read this table:

- **Same recipe, different physics.** All three ran the identical pipeline and
  the identical transport grid, yet behave differently: SrCu2SnS4 favors p-type
  by PF/tau, SrZrS3 favors n-type by zT_e, and Rb2Cu2SnS4 favors p-type by
  *both* metrics unambiguously. That is exactly the kind of statement the
  shared grid makes trustworthy.
- **Gap widens down the list.** 0.3445 -> 0.6096 -> 0.7811 eV [calculated,
  all PBE and so probably underestimates]. A wider gap suppresses the
  high-temperature bipolar bleed that eats the Seebeck coefficient of
  small-gap materials (section 3.1), which is part of why Rb2Cu2SnS4's S keeps
  climbing with temperature (+199.7 -> +232.9 uV/K) instead of rolling over.
- **The zT_e values are upper bounds -- and Rb2Cu2SnS4's are alarmingly high
  for a reason.** 1.898, 1.625, and 6.419 are electronic-only numbers with tau
  cancelled but kappa_L absent. The 6.419 is NOT a prediction that Rb2Cu2SnS4
  reaches zT = 6; it is what you get when the denominator has only the
  (small, wide-gap-suppressed) electronic heat term and no lattice heat at all.
  Adding kappa_L will pull it down hard, and by an unknown amount. Do not rank
  the materials by these numbers.
  (These three are the peaks *among the best-PF/tau operating points*. The
  unfiltered grid in `transport_full.csv` holds even larger zT_e values at
  near-intrinsic densities where both sigma/tau and kappae/tau go to zero and
  their ratio blows up -- those are numerical artifacts, not operating points,
  which is exactly why the summaries select by PF/tau instead.)
- **PF/tau rows compare materials only under the assumed-similar-tau caveat**
  (section 3.3). SrZrS3's larger best PF/tau does *not* mean SrZrS3 conducts
  better; it means its bands would win *if* both materials scattered
  electrons identically, which nobody has checked.
- **Every cutoff/mesh row is per-material.** 90/720 Ry appears for both
  SrCu2SnS4 and Rb2Cu2SnS4, but each was chosen by that material's own
  convergence test (Rb2Cu2SnS4: 0.0896 meV/atom at 90 Ry vs its 100 Ry
  reference, `../thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv`
  [calculated]) -- the coincidence is physically reasonable because the same
  hard Cu pseudopotential dominates both
  (`../thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`), but it was verified, not
  assumed. SrZrS3, with no Cu, converged at 50/400 Ry
  (`../thermo_candidates/SrZrS3/WORKLOG.md`).

---

## 5. The judgment checklist: is this material still promising after the first pass?

Run every candidate through these six questions before saying anything
hopeful about it. For each, one paragraph on what it means and why it earns
its place.

**1. Did it stay semiconducting with fixed occupations?** Our SCF runs use
`occupations = 'fixed'`, which asserts integer band filling -- a
semiconductor assumption (see `../WORKFLOW_EXPLAINED.md` section 3.6). If the
material were actually metallic at the PBE level, fixed occupations would
fail to converge or produce nonsense, and a metal has essentially zero
Seebeck coefficient, ending its thermoelectric story immediately. Both
finished materials converged cleanly with fixed occupations and show real
gaps, and Rb2Cu2SnS4's relaxation and final SCF also converged cleanly under
the same assumption (`../thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`), so all
three pass. This is the cheapest, earliest kill criterion.

**2. Is the gap in the useful window?** From section 3.1: too small means
bipolar losses eat the high-temperature Seebeck (SrCu2SnS4's 0.3445 eV
[calculated] is on the small side -- watch its 900 K rows, where the best
p-type point retreats to the heaviest sampled density, 1e21 cm^-3); too
large means doping is hard, and the screening rule caps it at 1.0 eV
[database criterion] anyway. Remember the PBE bias: our calculated gaps are
underestimates, so a "slightly too small" PBE gap may be fine in reality,
while a PBE gap near 1 eV would suggest the real gap exceeds the window.
SrCu2SnS4 (0.3445 eV) and SrZrS3 (0.6096 eV) both pass; Rb2Cu2SnS4's gap is
in progress.

**3. Was the relaxation healthy?** A trustworthy first pass needs the
variable-cell relaxation (`vc-relax`, `../WORKFLOW_EXPLAINED.md` section 4.3)
to converge on all criteria, *keep the database space group*, and change the
volume by only a few percent (PBE typically inflates volumes slightly). All
three materials pass: symmetry kept (P3_121, Pnma, Ibam) and drifts of
+0.48%, +0.63%, +0.93% respectively (table above, all [calculated]). A
broken symmetry or a wild volume change would mean we are no longer computing
the experimentally observed phase -- every downstream number would describe
some other crystal.

**4. Are Seebeck magnitudes ~100+ uV/K at achievable densities?** Good
thermoelectrics typically need |S| of roughly 100 uV/K or more at carrier
densities a chemist can realistically dope (the 1e19-1e21 cm^-3 grid spans
the plausible range, but the top of it is aggressive). Both finished
materials clear this bar at moderate densities: +157.2 uV/K at 1e20 cm^-3
(SrCu2SnS4, 300 K) and -173.8 uV/K at 1e20 cm^-3 (SrZrS3, 700 K)
[calculated]. S is tau-independent (section 3.2), so this is the most
trustworthy transport check on the list -- but "achievable" is still an
assumption: nobody has shown these compounds *can* be doped to these
densities (see dopability in section 6).

**5. Do PF/tau and zT_e rise or peak inside the operating window?** A
generator material should improve, or at least hold, toward its operating
temperature. SrCu2SnS4's p-type best PF/tau climbs monotonically from
5.562e10 (300 K) to 2.144e11 W m^-1 K^-2 s^-1 (900 K), and its p-type zT_e
peaks at 1.898 at 800 K before dipping [calculated,
`../thermo_candidates/SrCu2SnS4/results/workflow_summary.md`]; SrZrS3's
n-type zT_e peaks at 1.625 at 700 K [calculated] -- healthy shapes. A
material whose best values *decay* with temperature from 300 K onward would
be a low-temperature-only story at best. Check both metrics, per section 3.5,
and remember both are grid samples, not fitted optima.

**6. Any red flags?** Metallic behavior, symmetry breaking during
relaxation, anomalous volume change, non-monotonic convergence curves, or a
QE run without the final `JOB DONE.` stamp. Also *operational* red flags that
mimic physics: the Rb2Cu2SnS4 work log documents runs with huge wall time but
small CPU time -- a suspended laptop, not a struggling SCF; iteration counts
were uniform and the energy-vs-cutoff curve smooth, so the physics was clean
(`../thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`). The habit to build: when a
number looks weird, first ask whether the *computer* or the *setup* did
something weird, and trace the value back to the raw log before blaming or
crediting the material (`06_data_handling.md` shows the commands).

Scorecard today: SrCu2SnS4 and SrZrS3 pass all six (with the dopability
asterisk on item 4); Rb2Cu2SnS4 passes items 1, 3, and 6 so far, with items
2, 4, and 5 in progress. A material that passes all six is "still promising
after the first pass" -- nothing more. It has earned a second pass, not a
recommendation letter.

---

## 6. What is still missing before any real ranking

This mirrors `../WORKFLOW_EXPLAINED.md` section 8, focused on the comparison
decision. None of the following exist yet for any candidate, and each one
could reorder the materials:

| Missing ingredient | Why it blocks a ranking | What would provide it |
|---|---|---|
| Relaxation time tau (s) | PF/tau becomes a real power factor only with tau; two materials can have different tau by large factors, flipping any PF/tau-based ordering | electron-phonon calculation (expensive) or fit to measured mobility |
| Lattice thermal conductivity kappa_L (W m^-1 K^-1) | zT_e -> real zT requires kappa_L in the denominator; a material with soft, anharmonic phonons (low kappa_L) can beat one with a higher zT_e | phonon / lattice-dynamics calculation |
| Spin-orbit coupling (SOC) | all runs are scalar-relativistic; SOC can shift band edges and gaps, and differently per material | rerun with fully relativistic treatment |
| Beyond-PBE gap (eV) | PBE underestimates gaps, so the bipolar-loss onset temperatures are systematically pessimistic, and differently so per material | hybrid functional or GW (much more expensive) |
| Dopability / defect chemistry | the grid *assumes* every density up to 1e21 cm^-3 is reachable with rigid bands; real dopants may saturate earlier or distort the bands | defect-formation-energy study |
| Stability under operating conditions | "experimentally observed" [database] says the phase can exist, not that a phase-pure doped sample survives 700-900 K in service | phase-diagram analysis + the experimental collaborators |
| Transport-mesh convergence check | the BoltzTraP2 numbers have not been re-run on a denser NSCF mesh to confirm they are stable; a standing caveat recorded for all materials (`../thermo_candidates/SrZrS3/WORKLOG.md`) | repeat NSCF + BoltzTraP2 on a denser mesh and compare |

**What could be said to Roy today** (each with its tag and caveat):

- Both finished candidates are PBE semiconductors with gaps inside the
  screening window: 0.3445 eV (SrCu2SnS4, indirect) and 0.6096 eV (SrZrS3)
  [calculated]; real gaps are likely somewhat larger (PBE bias).
- Both relaxed cleanly, keeping their database space groups with small
  volume drifts [calculated] -- no structural red flags.
- On the shared sampled grid, under CRTA and without SOC, the two materials
  prefer opposite carriers: SrCu2SnS4 looks p-type (by PF/tau at every
  sampled temperature), SrZrS3 looks n-type (by zT_e at every sampled
  temperature, with the PF/tau-vs-zT_e disagreement of section 3.5 stated
  alongside) [calculated].
- Seebeck magnitudes at moderate sampled densities are in the healthy
  100+ uV/K range for both [calculated], and S is absolute under the stated
  approximations.
- Both stay on the candidate list; nothing observed so far disqualifies
  either. Rb2Cu2SnS4 has passed its own convergence tests (90/720 Ry; relax
  2x4x4; final SCF 3x5x5) and relaxation (Ibam kept, +0.93% volume), and its
  final SCF gives 78 occupied bands [calculated]; its dense NSCF and
  transport are in progress.

**What must NOT be said to Roy today:**

- Any absolute power factor or absolute conductivity (tau is unknown).
- Any final zT, including "zT = 1.9" -- 1.898 is a zT_e upper bound on a
  sampled grid, missing kappa_L; the database's 1.895 [database] is an
  external model prediction, and their numerical closeness is a coincidence
  of two different quantities.
- A ranking of SrCu2SnS4 vs SrZrS3 vs Rb2Cu2SnS4 -- the table in section 4
  shows the electronic-structure *evidence*, but every ingredient in the
  table above could reorder them.
- A real-world gap value -- our numbers are PBE underestimates, and the
  listed [database] gaps (0.4032 / 0.5512 / 0.8641 eV) are database entries,
  not measurements we can vouch for.
- Anything at all about Rb2Cu2SnS4's gap or transport -- those numbers do
  not exist yet.

The honest one-sentence summary a beginner can reuse: *"the electronic
structures of both finished candidates look favorable -- SrCu2SnS4 for p-type
and SrZrS3 for n-type doping on the sampled grid -- but absolute performance
and any final ranking still require tau, kappa_L, and the remaining checks."*

---

## Sources behind every number in this document

- `../thermo_candidates/Roy_task_status.md` -- screening rules, the three picks, backups
- `../thermo_candidates/README.md` -- ranks, predicted zT, listed gaps, element list [database]
- `../thermo_candidates/SrCu2SnS4/notes/material_choice.md` -- rare-earth avoidance
- `../thermo_candidates/SrCu2SnS4/results/workflow_summary.md` -- SrCu2SnS4 DFT facts + transport table
- `../thermo_candidates/SrCu2SnS4/results/seebeck_vs_mu.md` and `seebeck_vs_mu.csv` -- bipolar Seebeck story, tau cancellation, E_F
- `../thermo_candidates/SrCu2SnS4/results/transport_full.csv` -- 98-row grid check
- `../thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh` -- the explicit 14-level doping list
- `../thermo_candidates/SrCu2SnS4/CLAUDE.md` -- volume drift line
- `../thermo_candidates/SrZrS3/results/workflow_summary.md` -- SrZrS3 DFT facts + transport table
- `../thermo_candidates/SrZrS3/results/transport_full.csv` -- 98-row and achieved-density checks
- `../thermo_candidates/SrZrS3/WORKLOG.md` -- convergence, relaxation, grid fixes, carrier-preference finding
- `../thermo_candidates/Rb2Cu2SnS4/WORKLOG.md` and
  `../thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md` -- complete first pass
- `../thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv` and `kpoint_results.csv` -- its convergence numbers
- `../WORKFLOW_EXPLAINED.md` -- referenced sections 1.2, 3.6, 3.8, 4.3, 5.2, 6.1, 8, 10

*Next in the curriculum: `06_data_handling.md` (working with the CSVs behind
every number quoted here). Map: `README.md` in this folder.*

# Roy Task Status

Roy's original screening instruction was to select a few crystals from the renewed list,
with the professor's constraints in mind:

- use candidates already filtered through Materials Project
- focus on materials that have already been observed
- aim for band gaps below 1.0 eV
- choose several high-zT candidates for DFT and BoltzTraP2 follow-up

## Selected First-Pass Candidates

1. SrCu2SnS4
2. SrZrS3
3. Rb2Cu2SnS4

## Why These Three

`SrCu2SnS4` is the best practical first calculation because it is high in the
renewed ranking, has a moderate band gap, and avoids rare-earth and flagged
toxic/radioactive elements.

`SrZrS3` is chemically simple and clean. Its predicted zT is only 0.001 lower
than several higher-ranked entries, which is not a meaningful penalty at this
screening stage.

`Rb2Cu2SnS4` is rank 1 in the renewed file and should not be ignored, although
Rb chemistry may be slightly less convenient experimentally than Sr-based
systems.

## Backups

Reasonable backups from the same region of the renewed list:

- BaPr(SnS3)2: high zT, but contains Pr
- EuHfS3: high zT, but Eu/Hf may make the first pass more complicated

## Computational Status

The complete first-pass workflow for `SrCu2SnS4` is finished. It includes QE
convergence tests, variable-cell relaxation, final SCF, a `12x12x6` dense NSCF,
and BoltzTraP2 transport tables from 300 to 900 K.

Key first-pass result: the QE-PBE indirect gap is 0.3445 eV, and the sampled
PF/tau values favor p-type doping. First-pass lattice thermal conductivity
is now available (below), but full zT still requires a relaxation-time model.

The `SrZrS3` first pass is also finished, with its own convergence tests
(50/400 Ry; relax 6x3x2; final SCF 8x4x2), a Pnma-preserving relaxation, a
20x10x6 dense NSCF, and the same BoltzTraP2 grid. Sampled PBE gap: 0.6096 eV.
On the sampled grid, zT_e at the n-type PF-selected point exceeds that at
the p-type PF-selected point at every temperature; these are not independent
zT_e optima. The same
full-zT caveats apply.

The `Rb2Cu2SnS4` first pass is now also finished, with its own convergence
tests (90/720 Ry; relax 2x4x4; final SCF 3x5x5), an Ibam-preserving
relaxation, an 8x14x14 dense NSCF (788 irreducible points), and the same
BoltzTraP2 grid. Sampled PBE gap: 0.7811 eV - the largest of the three. On the
sampled grid, p-type is favored by both PF/tau and zT_e at every temperature.
The same full-zT caveats apply.

All three first-pass workflows are complete. The three-material comparison is
in `../learning/05_comparing_materials.md`.

## Roy's Reply to the Combined Report

Roy approved the combined DOS/Seebeck + three-material report ("This is all
great work!") and confirmed a computational focus is fine — no wet-lab
obligation.

**Next task from Roy: phonons via phono3py.** The professor recommended
phono3py; Roy himself never got it to work and asked us to give it a go and
report if/how it works. Scientific target: third-order force constants ->
phonon-phonon scattering -> lattice thermal conductivity kappa_L, the
missing denominator of every zT_e upper bound reported so far.

**Status: SrCu2SnS4 DONE; interim progress email SENT to Roy (from the
uwaterloo mailbox).** phono3py runs end to end (168 force calculations on
Nibi/DRAC). First-pass kappa_L [calculated, residual-corrected]: 0.36
W m^-1 K^-1 at 300 K (in-plane 0.40, c-axis 0.30), falling ~1/T to 0.12 at
900 K — very low, encouraging. RTA, 2x2x1 supercell, historical cutoff-pair
4.0 bohr = 2.1167 A, q-mesh 13x13x6, PBE, no SOC, no NAC. The cutoff
included only onsite pair groups, so pair-range convergence is not
established; no significant imaginary modes on the
sampled mesh; pristine residual
forces (5.5e-4 Ry/bohr) measured and subtracted via --cfz; the email quotes
"roughly 0.35-0.40 W/(m K)" with the documented caveats. The interim email
and its two frozen attachments live in
`../fourth step result (phono3py lattice thermal conductivity)/`
(EMAIL_DRAFT.md + READY_TO_ATTACH/, frozen). The full "how we got it
working" writeup is deliberately NOT sent yet — it ships with the complete
package once SrZrS3 and Rb2Cu2SnS4 are done (staged draft:
HOW_WE_GOT_PHONO3PY_WORKING.md in that package). Next: the SrZrS3 phonon
campaign, with its own convergence decisions.

Audit qualification: the corrected last q-mesh step changes average kappa_L
by -2.9559%, but zz by -12.2745%. The earlier approximate 5% estimate is not
a demonstrated tensor or total physical uncertainty. Supercell and pair-cutoff
convergence remain unestablished. See `../HANDOFF.md` for the open
residual-force reporting issue before any new campaign.

## Cluster access history

The 2026-07-15 request to apply for a sponsored CCDB account is complete:
account/role activation was recorded on 2026-08-03, and the SrCu2SnS4 campaign
subsequently completed on Nibi. The old "application not yet submitted"
state is superseded. The fourth-step `WORKLOG.md` retains the setup and
failed-submission history; `../DRAC_SETUP.md` records the working recipe.
This is historical account/job evidence, not a live access or queue check.

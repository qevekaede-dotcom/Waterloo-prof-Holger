# Roy Task Status

Roy's latest instruction was to select a few crystals from the renewed list,
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
power factors favor p-type doping. Full zT still requires a relaxation time and
lattice thermal conductivity.

The `SrZrS3` first pass is also finished, with its own convergence tests
(50/400 Ry; relax 6x3x2; final SCF 8x4x2), a Pnma-preserving relaxation, a
20x10x6 dense NSCF, and the same BoltzTraP2 grid. Sampled PBE gap: 0.6096 eV.
On the sampled grid the n-type best electronic zT_e exceeds the p-type best at
every temperature - the opposite carrier preference to SrCu2SnS4. The same
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

**Status: SrCu2SnS4 DONE; package staged, not yet sent.** phono3py runs
end to end (168 force calculations on Nibi/DRAC). First-pass kappa_L
[calculated, residual-corrected]: 0.36 W m^-1 K^-1 at 300 K (in-plane
0.40, c-axis 0.30), falling ~1/T to 0.12 at 900 K — very low,
encouraging. RTA, 2x2x1 supercell, cutoff-pair 4.0 A, q-mesh 13x13x6,
PBE, no SOC, no NAC; no imaginary modes. Pristine-supercell residual
forces measured at 5.5e-4 Ry/bohr (above the 1e-4 guideline) and
subtracted via phono3py --cfz (< 0.1% effect on kappa_L at fixed mesh —
robustness confirmed). q-mesh ladder met the 3% criterion marginally
(2.9%); ~5% quoted as the uncertainty. The "how we got it working"
write-up Roy asked for is staged in
`fourth step result (phono3py lattice thermal conductivity)/`. Only
remaining step: user reviews and sends the email. Then: same campaign for
SrZrS3 and Rb2Cu2SnS4, each with its own convergence decisions.

## Cluster Access (2026-07-15)

Roy emailed (after talking to the professor): apply for a Digital Research
Alliance of Canada (CCDB) account with Professor Kleinke as PI/sponsor, via
https://docs.alliancecan.ca/wiki/Apply_for_a_CCDB_account. Registration is as
a sponsored Group Member and requires the PI's CCRI (role identifier), which
Roy's email did not include — must ask Roy/the professor for it. Register with
the institutional (@uwaterloo.ca) email; after email confirmation the PI must
approve the sponsorship in CCDB. Status: application not yet submitted.

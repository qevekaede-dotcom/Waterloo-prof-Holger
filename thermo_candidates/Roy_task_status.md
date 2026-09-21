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
PF/tau values favor p-type doping. The historical lattice-conductivity record
is rejected under the current contract. Full zT requires accepted kappa_L and
a relaxation-time model.

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

## Current phonon and communication status — 2026-09-21

No material has an accepted kappa_L. Electronic first-pass completion does
not imply phonon/transport convergence.

- **SrCu2SnS4:** historical 168-displacement dataset preserved, with 4-bohr
  rather than 4-A cutoff, mixed settings, unhealthy outputs and tensor q-mesh
  nonconvergence. v2 corrects preparation logic but has no real generated
  displacement set or completed pristine/pilot calculation in repository evidence.
- **SrZrS3:** forces and FC2/FC3 generated. Sampled minimum -1.0716 THz
  rejects the finite diagnostic kappa tensor. The origin is unresolved.
- **Rb2Cu2SnS4:** narrow force recovery completed in saved evidence. Limited
  FC2/FC3/HDF5 audit passes, but all tested q-mesh steps fail. This is not
  scientific convergence of the force constants or a valid final kappa_L.

The SrCu2SnS4 interim email and its two attachments remain frozen sent records
in the fourth-step package. Its full writeup remains a staged, unsent draft.
On 2026-09-21 the user confirmed sending the revised status update indexed by
`../fifth step result (remaining-material phono3py first passes)/EMAIL_TO_ROY_REVIEWED.md`.
The exact sent message has not been independently retrieved. Roy's next-priority
choice is pending; this repository does not record a reply.

Use [current evidence and interpretation limits](../experiments/phonon_research_sandbox/CURRENT_STATE.md)
and [the sandbox deliverables](../experiments/phonon_research_sandbox/README.md).
Old “DONE”, “next Sr campaign” and “encouraging low kappa” interpretations are
superseded for new writing. Original reports and all sent files stay unchanged.

## Cluster access history

The 2026-07-15 request to apply for a sponsored CCDB account is complete:
account/role activation was recorded on 2026-08-03, and the SrCu2SnS4 campaign
subsequently completed on Nibi. The old "application not yet submitted"
state is superseded. The fourth-step `WORKLOG.md` retains the setup and
failed-submission history; `../DRAC_SETUP.md` records the working recipe.
This is historical account/job evidence, not a live access or queue check.

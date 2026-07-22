# Subject

Re: DOS comparison, Seebeck graphs, and first-pass results for all three candidates

# Note

This is the single combined reply covering both attachment folders:
Folder 1 = "DOS and Seebeck (SrCu2SnS4)" (from the second-step package),
Folder 2 = "Three-material first pass" (this package). The draft in
`second step result (DOS and Seebeck)/EMAIL_DRAFT.md` is superseded by this one.

# Body

Hi Roy,

Thank you for looking through my results! I finished the two things you asked
about, and since you said I was good to proceed, I also completed the first
pass for the other two crystals. I organized the attachments into two folders.

**Folder 1 - the DOS comparison and the Seebeck graph (SrCu2SnS4).**
For the DOS, I ran dos.x on the same dense 12x12x6 NSCF eigenvalues that
BoltzTraP2 uses, with 0.005 Ry Gaussian smearing, and computed the DOS from the
BoltzTraP2 interpolation for comparison. Near the Fermi level the two agree very
well: after I broaden the BoltzTraP2 DOS to the same 0.068 eV width, the curves
essentially overlay (Pearson r = 0.994 within +/-5 eV of E_F), and both show the
same 0.3445 eV indirect PBE gap. The BoltzTraP2 DOS only spans about +/-5.6 eV
around E_F and leaves out the deep semicore states, so the curves separate at
the edges of that window; as far as I can tell that is a windowing effect rather
than a physical difference. The folder also has the Seebeck coefficient versus
chemical potential centered on the Fermi energy at 300-900 K. S is positive on
the p-type side and negative on the n-type side, and the in-gap peaks shrink
with temperature as minority carriers activate across the gap. One thing I found
reassuring is that tau cancels in S under the constant-relaxation-time
approximation, so unlike sigma/tau these values are absolute; the curve also
reproduces the doped-grid numbers I sent before (157 uV/K at 1e20 cm^-3 p-type,
300 K).

**Folder 2 - the first pass for all three candidates.**
I did not reuse SrCu2SnS4's settings: each material got its own cutoff and
k-point convergence tests (SrCu2SnS4 and Rb2Cu2SnS4 ended up at 90/720 Ry,
which I think is due to the Cu pseudopotential, while SrZrS3 converged at
50/400 Ry), then relaxation, final SCF, dense NSCF, and BoltzTraP2 on the same
300-900 K and 1e19-1e21 cm^-3 grid, so the three are directly comparable. Each
material kept its database symmetry after relaxation (P3_121, Pnma, Ibam) with
a small volume change (+0.5% to +0.9%). The QE-PBE gaps come out as 0.3445,
0.6096, and 0.7811 eV for SrCu2SnS4, SrZrS3, and Rb2Cu2SnS4 - the same ordering
as the listed gaps (0.4032, 0.5512, 0.8641 eV). Two come out below the listed
values while SrZrS3 comes out slightly above (0.6096 vs 0.5512 eV); since the
listed gaps are database values from another DFT-based workflow rather than
experimental ones, I would only read the ordering, not the offsets. I still
expect PBE to underestimate the true experimental gaps.

The folder has a comparison table, a two-panel figure of the best sampled
PF/tau and the electronic zT at those points versus temperature,
Seebeck-versus-mu graphs for SrZrS3 and Rb2Cu2SnS4 in the same format as the
SrCu2SnS4 one, the combined best-point transport table, and the three relaxed
CIF files. On the sampled grid, SrCu2SnS4 and Rb2Cu2SnS4 favor p-type while
SrZrS3 comes out n-type by the electronic zT; interestingly, for SrZrS3 the
PF/tau and the electronic zT disagree on the preferred carrier at 500 K and
above (both pick n-type at 300-400 K), which I think is because the electronic
thermal conductivity grows with the heavy doping that maximizes PF/tau. I have been careful not to over-read these
numbers: the PF/tau values are still per relaxation time, so I only compare
them between materials assuming tau is similar, and the electronic zT values
leave out the lattice thermal conductivity, so I treat them as upper bounds
rather than real zT. None of the runs include SOC yet.

On your question about experimental versus computational work: I would most
like to focus on the computational side. I am still early in this area - so far
I have gotten through these calculations by following the workflow I set up
earlier, reading about the methods, and asking for help, and there are still
parts whose meaning I do not fully grasp or could not yet set up on my own.
That is exactly why I would like to keep going in this direction and build a
solid foundation; I have a lot of time between now and my final year and am
happy to put in the effort to learn it properly. At the same time, I do not
think a calculation is really complete until it can be checked against
experiment, so I would also be glad to take part in the wet-lab work - ideally
a mix of the two would suit me best. If experimental work means I need to sort
out courses and forms, I would appreciate setting up that meeting with the
professor whenever is convenient for you both.

If this all looks reasonable, I would be glad to hear which direction you would
like me to take next - for example adding a relaxation-time estimate and
lattice thermal conductivity to turn these into fuller zT values, or looking at
one of the materials in more depth.

Best regards,
Yuhan

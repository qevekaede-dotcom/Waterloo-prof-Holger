# Subject

Re: Update on my first SrCu2SnS4 calculation

# Note

SUPERSEDED, never sent: the send plan changed to one combined email with two
attachment folders. The authoritative draft is
`../third step result (three-material first pass)/EMAIL_DRAFT.md`; this
package's `READY_TO_ATTACH/` is that email's Folder 1. Kept for the record.

# Body

Hi Roy,

Thank you for looking through my results! I finished the two things you asked
about.

For the DOS, I ran dos.x on the same dense 12x12x6 NSCF eigenvalues that
BoltzTraP2 uses, with 0.005 Ry Gaussian smearing, and computed the DOS from the
BoltzTraP2 interpolation for comparison. Near the Fermi level the two agree very
well: after I broaden the BoltzTraP2 DOS to the same 0.068 eV width, the curves
essentially overlay (Pearson r = 0.994 within +/-5 eV of E_F), and both show the
same 0.3445 eV indirect PBE gap. The BoltzTraP2 DOS only spans about +/-5.6 eV
around E_F and leaves out the deep semicore states, so the two curves separate
at the edges of that window; as far as I can tell this is a windowing effect
rather than a physical difference. The overlay plot and the data are attached.

I also attached the Seebeck coefficient as a function of chemical potential,
centered on the Fermi energy, at 300-900 K from the same BoltzTraP2 run
(rigid-band scan). S is positive on the p-type side and negative on the n-type
side, with the sign change inside the gap, and the in-gap peaks shrink with
temperature as minority carriers activate across the gap. One thing I found
reassuring is that within the constant-relaxation-time approximation tau cancels
in S, so unlike sigma/tau these values are absolute; the curve also reproduces
the doped-grid numbers I sent before (for example 157 uV/K at 1e20 cm^-3 p-type
at 300 K). The values are still PBE without SOC, and the plotted S is the
average of the tensor diagonal, so I would read them as first-pass estimates.

On your question about experimental versus computational work: I would most like
to focus on the computational side. I am still early in this area - so far I have
gotten through these calculations by following the workflow I set up earlier,
reading about the methods, and asking for help, and there are still parts whose
meaning I do not fully grasp or could not yet set up on my own. That is exactly
why I would like to keep going in this direction and build a solid foundation; I
have a lot of time between now and my final year and am happy to put in the
effort to learn it properly. At the same time, I do not think a calculation is
really complete until it can be checked against experiment, so I would also be
glad to take part in the wet-lab work - ideally a mix of the two would suit me
best. If experimental work means I need to sort out courses and forms, I would
appreciate setting up that meeting with the professor whenever is convenient for
you both.

Next I will move on to SrZrS3 and Rb2Cu2SnS4 and repeat the convergence tests
for each material separately, starting with the SrZrS3 cutoff series.

Please let me know if anything looks off or if a different format would be more
useful.

Best regards,
Yuhan

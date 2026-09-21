# To

Roy (reply in the existing University of Waterloo email thread; the address is
not stored in this repository).

# Subject

Brief update on the phono3py calculations and next step

# Status

Draft only — not sent. No attachments are proposed with this short update.

# Body

Hi Roy,

I wanted to send you a brief update on the phonon calculations. The first-pass
SrZrS3 and Rb2Cu2SnS4 campaigns have now reached force-constant construction
and initial phono3py post-processing, but neither gives a lattice thermal
conductivity that I think should be accepted yet.

- For SrZrS3, the force calculations and FC2/FC3 construction were completed,
  but the sampled spectrum contains imaginary modes (minimum about -1.07 THz),
  so its finite conductivity output is only a rejected diagnostic.
- For Rb2Cu2SnS4, the force calculations and FC2/FC3 construction were
  completed, but every transition in the q-mesh sequence failed the convergence
  criterion, so I have not accepted its final conductivity tensor.

I also found an important issue while auditing the earlier SrCu2SnS4 work. The
pair cutoff that I had described as 4 angstrom was interpreted by the QE
phono3py interface as 4 bohr (about 2.12 angstrom). The previously reported
value is therefore an unconverged historical first pass, not a validated
lattice thermal conductivity. I have prepared a corrected workflow using the
intended 4-angstrom cutoff and uniform force settings, but have not launched
another large calculation.

The workflow itself is now working and documented, but before using more of
the group's computing allocation, could you please let me know which direction
would be most useful: rerun SrCu2SnS4 with the corrected cutoff, investigate
the SrZrS3 instability, extend the Rb2Cu2SnS4 convergence study, or stop here
and prepare a concise report of the workflow and these first-pass outcomes?

Best regards,
Yuhan

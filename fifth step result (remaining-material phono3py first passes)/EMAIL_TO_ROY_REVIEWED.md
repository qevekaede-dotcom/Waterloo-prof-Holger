# Status and provenance

The user confirmed sending the update after the revised text below was supplied
in the conversation. This is the reviewed source text, not an independently
retrieved copy from the Sent mailbox; exact sent wording and attachments have
not been independently verified. Roy's reply has not been recorded.
The earlier `EMAIL_DRAFT_TO_ROY.md` is preserved as a superseded draft.

# Subject

Phono3py progress update and next steps

# Body

Hi Roy,

Following the electronic-transport comparison, I have extended the phonon calculations to SrZrS3 and Rb2Cu2SnS4. Both now have calculated second- and third-order force constants and initial thermal-conductivity outputs, although neither has passed the checks needed for me to report a reliable kappa_L.

SrZrS3 shows imaginary frequencies in the sampled phonon calculation, whose origin still needs investigation. For Rb2Cu2SnS4, the conductivity has not met the convergence criterion across the q-meshes tested. Its post-processing script also failed during a final file check; a separate audit verified the saved force-constant files' basic integrity, but did not establish scientific convergence.

I also need to correct my earlier SrCu2SnS4 report: I mistook the pair-cutoff units, so the calculation used 4 bohr rather than the intended 4 Å. The audit also identified inconsistent force settings and runs that did not terminate cleanly. I therefore cannot treat the previously reported conductivity as validated. I have prepared revised input-generation and checking scripts, but have not rerun the corrected calculation.

Could you please advise what I should prioritize next—correcting and checking SrCu2SnS4, investigating the imaginary modes in SrZrS3, or extending the Rb2Cu2SnS4 convergence tests? Alternatively, would a report documenting the workflow and current limitations be the most useful next step?

Best regards,
Yuhan

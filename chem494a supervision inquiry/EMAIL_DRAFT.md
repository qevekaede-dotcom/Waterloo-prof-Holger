# To

Professor Holger Kleinke (address from prior correspondence or the
Department of Chemistry directory; deliberately not stored in this public
repo). Send from the university account.

# Subject

CHEM 494A supervision inquiry for the Winter term

# Body

Dear Professor Kleinke,

I am Yuhan Sun, the undergraduate who has been working with Roy on the computational screening of thermoelectric sulfides in your group. Thank you again for sponsoring my Digital Research Alliance account — the recent phonon calculations ran on Nibi under the group's allocation.

A brief summary of what I have done with Roy so far:

- Following the constraints you set (experimentally observed structures in the Materials Project, band gaps below 1.0 eV), I selected three candidates from the screening list: SrCu2SnS4, SrZrS3, and Rb2Cu2SnS4.
- I completed the first-pass Quantum ESPRESSO + BoltzTraP2 workflow for all three, with separate cutoff and k-point convergence tests for each material. The PBE gaps came out at 0.3445, 0.6096, and 0.7811 eV, and on the sampled doping grids SrCu2SnS4 and Rb2Cu2SnS4 favor p-type while SrZrS3 favors n-type. I also validated the BoltzTraP2 interpolation against QE's own DOS. I have treated all transport values as electronic-only upper bounds, since they are still per relaxation time and were missing the lattice thermal conductivity, and SOC is not yet included. Roy has reviewed these results.
- Most recently, following your phono3py recommendation, I got phono3py running end to end and computed a first-pass lattice thermal conductivity for SrCu2SnS4 (168 displaced supercells, run on Nibi): about 0.36 W m^-1 K^-1 at 300 K, decreasing to about 0.12 W m^-1 K^-1 at 900 K, under documented first-pass approximations (2x2x1 supercell, 4.0 A pair cutoff, RTA). All inputs, scripts, and logs are kept in a public repository: https://github.com/qevekaede-dotcom/Waterloo-prof-Holger

I am writing because I plan to take CHEM 494A in the upcoming Winter term, and I would very much like to do my research project under your supervision, ideally continuing this computational work. May I ask:

1. Would you be willing to supervise my CHEM 494A project?
2. If so, what direction would you suggest? A natural continuation seems to be completing the lattice thermal conductivity for the other two candidates and working toward a fuller zT assessment, but I am happy to take whatever direction you think is most useful for the group.
3. Is there anything I should learn or prepare between now and January so I can start the term productively? I would be glad to keep working on the current calculations in the meantime.

I would be happy to meet in person or online if that is more convenient. Thank you very much for your time.

Best regards,
Yuhan Sun

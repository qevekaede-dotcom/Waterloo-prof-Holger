# Notes from my first SrCu2SnS4 calculation

I chose the experimentally observed `mp-16988` structure and used it to learn
the QE to BoltzTraP2 workflow.

I first compared wavefunction cutoffs from 50 to 100 Ry. The 90 Ry result was
within 0.1044 meV/atom of the 100 Ry result, so I used 90/720 Ry for the rest of
the calculation. I also compared four k-point meshes. The 4x4x2 result was
within 0.2532 meV/atom of 5x5x3, so I used 4x4x2 for the relaxation and kept
5x5x3 for the final SCF.

The relaxed structure kept the `P3_121` space group. Its volume changed from
543.884 to 546.507 A^3. My dense NSCF calculation used a 12x12x6 mesh and 140
bands. From those eigenvalues, I obtained an indirect PBE gap of 0.3445 eV.

For BoltzTraP2, I sampled temperatures from 300 to 900 K and both carrier signs
from 1e19 to 1e21 cm^-3. Under the constant-relaxation-time assumption, the
p-type PF/tau values were generally larger than the n-type values in this grid.

I have not treated the electronic-only zT column as a final zT. I still need a
relaxation time for absolute conductivity and lattice thermal conductivity for
the full denominator.

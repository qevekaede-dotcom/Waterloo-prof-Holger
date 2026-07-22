# Subject

Update on my first SrCu2SnS4 calculation

# Body

Hi Roy,

I wanted to send you a quick update. I went back through the renewed list using the requirements you and the professor mentioned, and I narrowed my first group down to three experimentally observed materials with reported band gaps below 1.0 eV:

- SrCu2SnS4
- SrZrS3
- Rb2Cu2SnS4

Since this is my first time working through the full calculation process, I started with SrCu2SnS4 (Materials Project ID: mp-16988) and tried to keep track of each step. I first tested the plane-wave cutoff and k-point mesh instead of only using the initial values. I then relaxed the structure, ran the SCF and dense NSCF calculations, and used the resulting band energies in BoltzTraP2.

For the final run, I used 90/720 Ry, a 4x4x2 k-point mesh for the relaxation, a 5x5x3 mesh for the final SCF, and a 12x12x6 mesh with 140 bands for the NSCF calculation. I looked at both n-type and p-type carrier concentrations from 10^19 to 10^21 cm^-3 between 300 and 900 K.

Symmetry analysis of the relaxed structure still gave the P3_121 space group. From the dense k-point grid, I estimated an indirect PBE band gap of 0.3445 eV, compared with 0.4032 eV in the renewed list. Under the constant-relaxation-time assumption, the p-type cases generally had larger PF/tau values than the n-type cases in the grid I sampled. For example, at 300 K, the best p-type point in my sampled grid was around 1.0 x 10^20 cm^-3, with a Seebeck coefficient of 157.2 uV/K.

I attached the relaxed CIF, an Excel workbook with my calculation notes, convergence data and transport results, and a small ZIP file containing the QE inputs. I have not treated the electronic-only zT values as the final zT because the conductivity results are still per relaxation time and I do not yet have the lattice thermal conductivity. I also have not included SOC in this first calculation.

Could you please take a look and let me know whether I set up the calculation and interpreted the BoltzTraP2 results correctly? If this looks reasonable, I can move on to SrZrS3 and Rb2Cu2SnS4 and repeat the convergence tests for each material.

Best regards,
Yuhan

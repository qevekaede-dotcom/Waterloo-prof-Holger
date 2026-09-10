# SrCu2SnS4 lattice thermal conductivity — first pass [calculated]

phono3py RTA (--br), 2x2x1 supercell, historical cutoff-pair 4.0 bohr (2.1167 A; onsite pair groups only), q-mesh (13, 13, 6), PBE, no SOC, no NAC. Pair-cutoff convergence is not established.

- solver for fc3: traditional
- minimum phonon frequency on mesh: -0.0000 THz (OK)
- table: `kappa_L_first_pass.csv`

kappa_L here is a first-pass value under the documented cutoffs; it is NOT yet combined with any electronic zT_e. Full zT still needs a relaxation-time model for the electronic side.

# 08 — Phonons and lattice thermal conductivity (the phono3py step)

Status: the SrCu2SnS4 force-calculation campaign is **running**; the numbers
sections below say "[pending]" until it finishes. Everything else here is
stable and you can read it while the machine works.

## 1. Why we are doing this

Every zT we have reported so far is `zT_e` — an *electronic-only* upper
bound. The real figure of merit is

```text
zT = S^2 sigma T / (kappa_e + kappa_L)
```

We have the numerator (from BoltzTraP2, still per relaxation time tau) and
`kappa_e`, but the denominator's second term — **kappa_L, the lattice
thermal conductivity** — has been missing every time. Heat in a
semiconductor is carried mostly by lattice vibrations, so leaving kappa_L
out makes every zT_e an overestimate of unknown size. A good thermoelectric
needs kappa_L to be *small*, so this number can change the ranking of our
three candidates.

## 2. Phonons in one paragraph

Atoms in a crystal sit near equilibrium positions and vibrate. Because atoms
are coupled (move one, its neighbors feel it), the vibrations organize into
collective waves called **phonons** — each with a wavevector q, a branch
index, and a frequency. With N atoms in the primitive cell there are 3N
branches (SrCu2SnS4: 24 atoms -> 72 branches). Phonons are to lattice
vibrations what electrons' Bloch states are to charge: quantized carriers,
here of *heat*.

## 3. Harmonic vs anharmonic: fc2 and fc3

Expand the crystal energy in atomic displacements u:

```text
E = E0 + (1/2) sum fc2 * u * u + (1/6) sum fc3 * u * u * u + ...
```

- **fc2** (second-order force constants, "harmonic"): gives phonon
  frequencies and dispersions. In a purely harmonic crystal phonons never
  scatter and kappa_L would be *infinite*.
- **fc3** (third-order, "anharmonic"): lets phonons scatter off each other
  (three-phonon processes). This is what makes kappa_L finite. Computing
  fc3 is the expensive part and is exactly what phono3py automates.

phono3py gets both by **finite differences**: displace one atom (-> forces
give fc2) or two atoms (-> force *differences* give fc3) in a supercell, ask
Quantum ESPRESSO for the forces each time, and fit the constants. Then it
solves the phonon Boltzmann transport equation (we use the relaxation-time
approximation, "RTA") to get kappa_L(T).

## 4. Why so many QE runs, and how we cut them down

Two displaced atoms x three directions x every symmetry-distinct pair =
thousands of supercell calculations. Our campaign was tamed in three steps
(full story with failures: the fourth step WORKLOG):

1. **Symmetry.** With the correct space group P3_121 recognized
   (`--tolerance 1e-3`; the default misread our 6-decimal coordinates as P1),
   13,848 displacements collapse to symmetry-distinct ones.
2. **Pair-distance cutoff.** fc3 between atoms farther apart than 4.0 A is
   set to zero (`--cutoff-pair 4.0`). Cu-S and Sn-S bonds are ~2.3-2.4 A,
   so the cutoff keeps the bonding shells that dominate anharmonicity.
   Result: **168 supercell force calculations** — a laptop-sized campaign.
3. **Force-convergence checks.** Before the campaign, one displaced cell is
   recomputed with a coarser k-mesh and lower cutoffs; a candidate setting
   is accepted only if every force component matches the converged
   reference within 5e-5 Ry/bohr. Forces converge faster than total
   energies, so this often buys a 2-5x speedup *with evidence*, not by
   copying parameters.

## 5. What is actually running (and how to watch it)

Work directory: `thermo_candidates/SrCu2SnS4/phono3py/`.

- `fc_calcs/disp-XXXXX/` — one pw.x force run per displaced supercell
  (96 atoms = 2x2x1 copies of the 24-atom cell).
- `campaign_log.csv` — one line per finished run: wall seconds, settings,
  status. `tail` it to see progress.
- `campaign.out` — the driver's narrative log.
- `checks/` — the k-mesh/cutoff decisions and the undisplaced-supercell
  sanity run (its forces should be ~zero; if not, the relaxation was too
  loose and the phonons could not be trusted).
- When all 168 finish, the driver collects forces (`FORCES_FC3`), builds
  fc2/fc3, converges the q-mesh at 300 K, and writes:
  - `../results/kappa_L_first_pass.csv` — kappa_L tensor vs T [calculated]
  - `../results/kappa_L_summary.md` — settings, checks, caveats

## 6. How to read the result when it lands [pending]

- kappa_L comes out as a tensor; in this trigonal crystal kxx = kyy != kzz.
  Anisotropy tells you which crystal direction conducts heat worse (better
  for zT).
- Typical good thermoelectrics sit near or below ~1 W m^-1 K^-1 at 300 K;
  ordinary semiconductors are tens of W m^-1 K^-1.
- kappa_L falls roughly as 1/T in this regime (more phonons to scatter
  off), so high-T zT benefits twice.
- Sanity checks to look for in the summary: no imaginary frequencies away
  from Gamma (a dynamically stable structure), q-mesh converged to < 3%.

## 7. What this still is NOT

- Still RTA + PBE + no SOC, fc3 truncated at 4.0 A pairs, 2x2x1 supercell,
  no non-analytic (Born-charge) correction yet — each is documented and
  each can be tightened later.
- Combining kappa_L with our PF/tau still does not give an absolute zT:
  the electronic side keeps its unknown relaxation time tau. What kappa_L
  buys is (a) one honest, material-specific piece of the denominator, and
  (b) a fair *relative* comparison of candidates once all three have it.

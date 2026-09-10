# 08 — Phonons and lattice thermal conductivity (the phono3py step)

Status: the SrCu2SnS4 campaign is **finished** and kappa_L is in
`thermo_candidates/SrCu2SnS4/results/`. Section 6 now reads the real
numbers; sections 1-4 are unchanged background. The blow-by-blow of how
the campaign actually went (five sessions, every failure included) is the
fourth step result's `WORKLOG.md`.

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
2. **Historical pair-distance cutoff.** The QE interface interpreted
   `--cutoff-pair 4.0` as 4.0 bohr = 2.1167 A, not 4.0 A. The resulting
   included pair groups were onsite; the shortest nonzero pair was excluded.
   Result: **168 supercell force calculations**, but not a demonstrated
   physically adequate interaction range. Future designs must convert explicit
   Angstrom values to bohr and test pair-cutoff convergence.
3. **Force-convergence checks.** Before the campaign, one displaced cell is
   recomputed with a coarser k-mesh and lower cutoffs; a candidate setting
   is accepted only if every force component matches the converged
   reference within 5e-5 Ry/bohr. Forces converge faster than total
   energies, so this often buys a 2-5x speedup *with evidence*, not by
   copying parameters.

## 5. What actually ran (and where the records live)

The campaign did NOT run on a laptop in the end: one force calculation
took >= 2 h locally, so the whole thing moved to the Nibi cluster (DRAC)
as three chained SLURM jobs — stage 0 redid the force-convergence checks
on the cluster itself, stage 1 ran the 168 force SCFs as a job array
(~44 min each on 32 cores), stage 2 built the force constants and
kappa_L. Work directory: `thermo_candidates/SrCu2SnS4/phono3py/`.

- `fc_calcs/disp-XXXXX/` — one pw.x force run per displaced supercell
  (96 atoms = 2x2x1 copies of the 24-atom cell).
- `campaign_log_slurm.csv` — one line per run: wall seconds, status.
- `slurm_logs/` — per-stage logs plus timestamped `evidence_*/` snapshots
  of every failure (taken before reruns could overwrite them).
- `checks/` — the on-cluster decisions: the cheaper 2x2x2 k-mesh FAILED
  the 5e-5 Ry/bohr force criterion (3x3x3 kept), the cheaper 60/480 Ry
  cutoffs PASSED. The undisplaced-supercell sanity run measured a max
  residual force of 5.5e-4 Ry/bohr — above the 1e-4 guideline — so the
  measured residual field was subtracted from every displaced-cell force
  before fitting (phono3py `--cfz`); the correction moved kappa_L by
  < 0.1% at fixed mesh, i.e. the result was robust against it.
- Outputs: `../results/kappa_L_first_pass.csv` (tensor vs T
  [calculated]) and `../results/kappa_L_summary.md` (settings + checks).

## 6. How to read the result (now with the real numbers)

- kappa_L is a tensor; trigonal symmetry forces kxx = kyy != kzz, and the
  computed tensor obeys it within numerical precision — a useful check. Numbers at
  300 K [calculated, residual-corrected]: in-plane 0.40, c-axis 0.30,
  average **0.36 W m^-1 K^-1**. The anisotropy is modest (~25%); heat
  flows worse along c.
- Typical good thermoelectrics sit near or below ~1 W m^-1 K^-1 at 300 K;
  ordinary semiconductors are tens. 0.36 is very low — encouraging.
- kappa_L falls roughly as 1/T in this regime (more phonons to scatter
  off): our 900 K average is 0.1213, and 0.3639 x (300/900) = 0.1213 —
  the trend holds to the last digit. High-T zT benefits twice.
- Sanity checks from the summary: minimum phonon frequency -2e-6 THz,
  numerically near zero. No significant imaginary modes occur on the
  sampled mesh; this does not prove dynamical stability everywhere.
  The corrected 11x11x5 -> 13x13x6 step changes the average by -2.9559%,
  just meeting the average-only 3% stopping criterion, while kzz changes
  by -12.2745%. The historical ~5% estimate is not a demonstrated tensor
  or total physical uncertainty. Further q-mesh checks remain necessary.
- A worked lesson in robustness: the residual-force correction (--cfz)
  changed the average at fixed mesh by < 0.1% (0.364 -> 0.3639).
  The archived 15x15x7 result predates residual correction, so comparing
  it with the final corrected 13x13x6 result changes both mesh and force
  treatment. It is a historical record, not the next corrected mesh point
  or a basis for assigning a total error bar.

## 7. What this still is NOT

- Still RTA + PBE + no SOC, fc3 truncated at 4.0 A pairs, 2x2x1 supercell,
  no non-analytic (Born-charge) correction yet — each is documented and
  each can be tightened later.
- The q-mesh stopping test covered the tensor average only (section 6);
  tensor, supercell, and pair-cutoff convergence remain unestablished.
  These are first-pass results, without a demonstrated total uncertainty.
  Pristine residual forces were measured at 5.5e-4 Ry/bohr and subtracted
  via `--cfz`, with a < 0.1% effect on average kappa_L at fixed mesh.
- Combining kappa_L with our PF/tau still does not give an absolute zT:
  the electronic side keeps its unknown relaxation time tau. What kappa_L
  buys is (a) one honest, material-specific piece of the denominator, and
  (b) a fair *relative* comparison of candidates once all three have it.

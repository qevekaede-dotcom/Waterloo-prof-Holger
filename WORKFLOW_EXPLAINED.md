# The Complete Beginner's Guide to This Workspace

This document explains, assuming **zero prior knowledge**, what this project
computes, why, how every step works, what every parameter means, how the
parameters were chosen, and how to read every result file. Real numbers from
this workspace are used throughout, and every number can be traced back to a
file that exists here.

Convention used everywhere below:

- **[calculated]** = a number this workspace computed (Quantum ESPRESSO or
  BoltzTraP2 output);
- **[database]** = a number taken from a screening list / Materials Project,
  produced by someone else's model;
- **[experimental]** = a measured number. (Almost nothing in this workspace is
  experimental yet - that is the point of the project.)

---

## Table of contents

1. Why this project exists
2. What "a calculation" actually is
3. The vocabulary: every concept and parameter, in plain language
4. The full workflow on SrCu2SnS4, step by step, with real numbers
5. Round two: validating the DOS and plotting the Seebeck coefficient
6. The second material, SrZrS3 (work in progress)
7. How to read every file in this workspace
8. What the results tell us - and what they do NOT
9. Glossary (quick reference)
10. FAQ

---

## 1. Why this project exists

### 1.1 Thermoelectric materials in one paragraph

A thermoelectric (TE) material converts a temperature difference directly into
electricity (and, run in reverse, electricity into cooling). Put one side of
the material against something hot (an engine exhaust, an industrial furnace)
and one side against something cold, and a voltage appears across it. No
moving parts, no working fluid. The catch: most materials do this so weakly
that it is useless. The research question is always the same - **find a
material where the effect is strong enough to matter**.

### 1.2 The figure of merit zT

How "good" a TE material is gets compressed into one dimensionless number:

```
        S^2 * sigma * T
zT  =  -----------------
        kappa_e + kappa_L
```

| Symbol  | Name | Plain meaning | Want |
|---|---|---|---|
| S | Seebeck coefficient | Volts generated per degree of temperature difference (measured in microvolts per kelvin, uV/K) | large |
| sigma | electrical conductivity | how easily current flows | large |
| T | absolute temperature | operating temperature (kelvin) | - |
| kappa_e | electronic thermal conductivity | heat carried by the electrons themselves | small |
| kappa_L | lattice thermal conductivity | heat carried by atomic vibrations (phonons) | small |

You want a material that generates a lot of voltage (large S), lets charge
through easily (large sigma), but blocks heat (small kappa) so the hot side
stays hot. These requirements fight each other - metals have huge sigma but
tiny S; glasses have tiny kappa but tiny sigma - which is why good TE
materials are rare. `zT ~ 1` is useful; `zT > 2` is exceptional.

### 1.3 Why compute instead of just measuring

Synthesizing and measuring one material takes weeks to months in a lab.
A quantum-mechanical calculation of the same material's *electronic*
properties takes hours on a laptop. So the strategy is:

1. someone screens thousands of database entries with fast approximate models
   (that already happened - the results are in
   `background info/Materials renew.csv`),
2. **we** re-examine the most promising few with proper first-principles
   calculations (this workspace),
3. only the survivors go to the lab (the professor's experimental group).

The calculation cannot replace the experiment - it predicts *electronic*
behavior under stated approximations - but it filters out losers cheaply.

### 1.4 The specific assignment

Roy (the PhD mentor) asked for: candidates already filtered through the
Materials Project, **experimentally observed** structures only (no hypothetical
crystals), band gaps below 1.0 eV, several high-predicted-zT picks. Three were
selected (reasons in `thermo_candidates/Roy_task_status.md`):

| Material | Rank in renewed list [database] | Predicted zT [database] | Band gap [database] | Status |
|---|---|---|---|---|
| SrCu2SnS4 | 10/11 | 1.895 | 0.4032 eV | complete first pass |
| SrZrS3 | 16 | 1.894 | 0.5512 eV | complete first pass |
| Rb2Cu2SnS4 | 1 | 1.896 | 0.8641 eV | complete first pass |

**Important:** "predicted zT 1.895" is a *database model prediction*, not our
result and not a measurement. Treat it as a reason to look, nothing more.

---

## 2. What "a calculation" actually is

### 2.1 The physics problem underneath

A crystal is nuclei plus electrons. Everything we care about - whether it
conducts, how much voltage it generates per kelvin - is decided by how the
**electrons** arrange themselves, and electrons obey quantum mechanics: the
Schrodinger equation. Solving that equation exactly for the ~10^23 interacting
electrons in a real solid is impossible. All of computational materials
science is the art of approximating it well enough.

### 2.2 DFT in plain language

**Density Functional Theory (DFT)** is the workhorse approximation. Its two
ideas:

1. You do not need to track every electron individually. The ground-state
   **electron density** n(r) - "how much electron-ness is at each point in
   space" - determines everything (a proven theorem).
2. Replace the interacting electrons by fictitious *non-interacting* ones
   moving in an effective potential chosen so they reproduce the true density
   (the Kohn-Sham trick). The messy part of the interaction is bundled into
   one term, the **exchange-correlation functional**, which must be
   approximated.

Our chosen approximation for that term is **PBE** (Perdew-Burke-Ernzerhof,
1996), the standard "GGA" functional. What PBE is known for:

- geometries and energy *differences*: good (typically ~1% on lattice
  constants);
- **band gaps: systematically underestimated**, often by 30-50%. Keep this in
  mind whenever a gap appears below.
- our runs are **scalar-relativistic without spin-orbit coupling (SOC)**:
  relativistic effects are partially included, but the spin-orbit interaction
  (which splits bands, increasingly for heavy elements) is not. Fine for a
  first pass; a known limitation.

### 2.3 The two programs

- **Quantum ESPRESSO (QE)** - an open-source DFT package. The main engine is
  `pw.x` (plane-wave self-consistent field). We also use `dos.x`
  (post-processing: density of states). Build used here: QE 7.5 development
  build (`~/scientific-tools/apps/qe/build-cmake/bin`).
- **BoltzTraP2** (v26.3.1) - a Python package that takes the band energies QE
  produced and computes **transport coefficients** (S, sigma, kappa_e) from
  the Boltzmann transport equation. It cannot run without QE's output; QE
  alone never produces S or sigma. The two-stage pipeline QE -> BoltzTraP2 is
  the core of this whole workspace.

### 2.4 What the computer literally does when we "run" something

A `pw.x` SCF run is a loop:

```
guess an electron density
repeat:
    build the effective potential from the density
    solve the Kohn-Sham equations at every k-point   <- the expensive part
    compute a new density from the solutions
    mix a fraction of new into old        (mixing_beta = 0.3 here)
until the total energy stops changing     (conv_thr = 1e-8 Ry here)
print "convergence has been achieved" and finally "JOB DONE."
```

"Self-consistent" (SCF) means exactly this: the density that comes out is the
density that went in. Every QE log in `logs/` and
`qe/convergence/*/outputs/` shows this loop happening; the line starting with
`!` is the converged total energy.

---

## 3. The vocabulary: every concept and parameter

Each entry: what it is -> the analogy -> our actual value and where it lives.

### 3.1 Crystal structure and CIF files

A crystal = one small box of atoms (the **unit cell**) repeated infinitely in
3D. A **CIF file** (`structures/*.cif`) is a text file holding the box shape
(lattice vectors) and the atom positions inside it, plus the **space group**
(the symmetry label).

Our completed example, SrCu2SnS4 (`structures/SrCu2SnS4.cif`, Materials
Project entry `mp-16988`, experimentally observed, ICSD-356):

- space group `P3_121` (No. 152, trigonal) [calculated relaxation kept the
  same symmetry as the database entry]
- relaxed cell: a = b = 6.357 A, c = 15.614 A [calculated]
- 24 atoms per cell = Sr3 Cu6 Sn3 S12 = three formula units of SrCu2SnS4.

### 3.2 Plane waves and the cutoffs `ecutwfc` / `ecutrho`

QE writes the electron wavefunctions as sums of 3D waves (**plane waves**) of
increasing spatial frequency, like building an image out of coarse-to-fine
ripples. `ecutwfc` (in **Ry**, Rydberg; 1 Ry = 13.6057 eV) is the maximum
"frequency" kept - think **image resolution**. Too low = blurry, wrong
physics; higher = better but slower (cost grows steeply).

`ecutrho` is the same cutoff for the electron *density* grid. With the
"ultrasoft" pseudopotentials we use, the density has sharper features than the
wavefunctions, so the rule `ecutrho = 8 x ecutwfc` is applied throughout this
workspace.

Values actually used, and *how they were chosen* (see section 4.1):
- SrCu2SnS4: `ecutwfc/ecutrho = 90/720 Ry` [convergence-tested]
- SrZrS3: `50/400 Ry` [convergence-tested, its own test]

Why so different? The hardest pseudopotential in the cell sets the cutoff.
SrCu2SnS4 contains Cu (a hard PAW pseudopotential -> 90 Ry); SrZrS3 has no Cu
(all soft ultrasofts -> 50 Ry). This is exactly why the house rule says
**never copy one material's cutoffs to another**.

### 3.3 Pseudopotentials (the `.UPF` files)

Core electrons (e.g. the inner 18 of copper) barely notice chemistry. A
**pseudopotential** freezes them and replaces "nucleus + core" with one
smooth effective potential, so QE only computes the valence electrons.
We take pseudopotentials from **SSSP 1.3.0 (PBE, precision tier)** - a
curated "best available per element" library. They are listed in every input
file under `ATOMIC_SPECIES`, e.g. for SrCu2SnS4:

| Element | File | Valence electrons treated |
|---|---|---|
| Sr | `Sr_pbe_v1.uspp.F.UPF` (ultrasoft) | 10 |
| Cu | `Cu.paw.z_11.ld1.psl.v1.0.0-low.upf` (PAW) | 11 |
| Sn | `Sn_pbe_v1.uspp.F.UPF` (ultrasoft) | 14 |
| S | `s_pbe_v1.4.uspp.F.UPF` (ultrasoft) | 6 |

Sanity check you can do yourself: 3 Sr x 10 + 6 Cu x 11 + 3 Sn x 14 +
12 S x 6 = 30 + 66 + 42 + 72 = **210 valence electrons** - QE reports exactly
this, and 210/2 = **105 occupied bands** (each band holds 2 electrons,
spin-up + spin-down). Both numbers appear in `qe/README.md` and the logs.

### 3.4 k-points (sampling the crystal's periodicity)

Because the crystal repeats forever, the solutions are labeled by a vector
**k** living in a finite box called the **Brillouin zone** (the unit cell of
"reciprocal space"). Energies must be *integrated* over that box; numerically
we sample it on a regular **Monkhorst-Pack mesh** like `4x4x2`.

- Denser mesh = more accurate integral = proportionally slower.
- Symmetry removes duplicates: our `12x12x6` mesh = 864 raw points but only
  **100 irreducible** ones actually computed [from `logs/SrCu2SnS4.nscf.out`].
- Rule of thumb: the number of k-points along an axis should be *inversely*
  proportional to the cell length along that axis (long axis in real space =
  short axis in reciprocal space). That is why flat/elongated cells get
  unequal meshes: SrCu2SnS4 (6.36, 6.36, 15.61 A) -> `5x5x3`;
  SrZrS3 (3.84, 8.59, 14.00 A) -> meshes like `8x4x2`.

### 3.5 SCF vs NSCF

- **SCF** (`calculation = 'scf'`): the self-consistent loop of section 2.4.
  Produces the converged density + total energy. This is "the" DFT
  calculation.
- **NSCF** (`calculation = 'nscf'`): re-uses the SCF density (frozen, read
  from disk - `startingpot = 'file'`) and just solves for the band energies
  on a **denser** k-mesh, without iterating the density. Much cheaper per
  point than redoing SCF, and it is exactly what BoltzTraP2 needs as input.

`conv_thr = 1e-8` Ry is the SCF stop criterion ("stop when the energy changes
by less than a hundred-millionth of a Rydberg") - tight, because transport
quantities are sensitive to small band-energy errors. `mixing_beta = 0.3`
means each iteration only accepts 30% of the new density - conservative and
stable. `occupations = 'fixed'` declares "this is a semiconductor/insulator:
exactly fill the lowest 105 bands" (metals would need smearing instead; if
the material had turned out metallic, QE would have complained).

### 3.6 Bands, band gap, Fermi energy

At each k-point the electrons may only sit on a ladder of allowed energies -
the **bands**. Bands filled with electrons = valence bands; empty ones =
conduction bands. In a semiconductor there is an energy window with no bands
at all - the **band gap**:

- **VBM** = valence band maximum = top of the filled states,
- **CBM** = conduction band minimum = bottom of the empty states,
- gap = CBM - VBM. If VBM and CBM occur at *different* k-points, the gap is
  **indirect**.
- The **Fermi energy (E_F)** is the filling level. For our fixed-occupation
  semiconductor QE places it at the VBM.

Our numbers [calculated, `logs/SrCu2SnS4.nscf.out`]:

```
highest occupied  (VBM):  7.1887 eV
lowest unoccupied (CBM):  7.5332 eV
indirect PBE gap:         0.3445 eV
```

(The absolute "7.1887 eV" means nothing by itself - QE's energy zero is
arbitrary. Only differences matter, which is why every plot uses `E - E_F`.)

Compare: the database gap was 0.4032 eV [database]. Both are DFT-family
numbers; the *experimental* gap is probably larger than either (PBE
underestimates - section 2.2).

### 3.7 Density of states (DOS)

The **DOS** answers "how many electron states exist at each energy?" - a
histogram over energy, in states/eV/cell. Zero DOS across the gap; the
integral of DOS up to E_F must equal the electron count (we verified: 210.0
exactly [calculated, `qe/dos/SrCu2SnS4.dos`]). The DOS shape near the band
edges controls thermoelectric behavior: sharp, heavy edges tend to give large
Seebeck coefficients.

### 3.8 Transport quantities and the relaxation time tau

BoltzTraP2 computes, for any temperature T and doping level:

| Quantity | Meaning | tau problem? |
|---|---|---|
| S (Seebeck) | uV per K of voltage | **NO - tau cancels; S is absolute** |
| sigma/tau | conductivity *per unknown scattering time* | yes |
| kappa_e/tau | electronic heat conductivity per tau | yes |
| PF/tau = S^2*(sigma/tau) | power factor per tau | yes |
| zT_e | S^2*(sigma/tau)*T / (kappa_e/tau) - tau cancels again | **but kappa_L is missing** |

**tau (relaxation time)** = the average time an electron travels before
scattering (off vibrations, defects...). This level of theory cannot compute
it; BoltzTraP2 assumes it is one unknown constant (the **CRTA** - constant
relaxation time approximation) and reports everything "per tau". Consequences,
which are also house rules of this workspace:

- `PF/tau` is **not** an absolute power factor. Never quote it as one.
- `zT_e` (tau cancels, but the denominator lacks the lattice term kappa_L) is
  only an **upper bound**, not the real zT.
- S and the shape of trends across T and doping **are** meaningful now.

---

## 4. The full workflow on SrCu2SnS4, step by step

Everything below lives in `thermo_candidates/SrCu2SnS4/`. The same recipe is
being repeated for the other two materials. Order matters:

```
CIF from database
  -> (1) cutoff convergence test      "is the resolution high enough?"
  -> (2) k-point convergence test     "is the sampling dense enough?"
  -> (3) vc-relax                     "let the structure find equilibrium"
  -> (4) final SCF                    "the definitive ground state"
  -> (5) dense NSCF                   "band energies on a fine grid"
  -> (6) BoltzTraP2                   "turn bands into S, sigma/tau, ..."
  -> (7) summarize                    "human-readable tables in results/"
```

### 4.1 Step 1 - cutoff convergence test

**Question answered:** what `ecutwfc` is enough?
**Method:** same structure, same k-mesh (a coarse fixed `2x2x2` - errors
cancel in differences), only the cutoff varies. Watch the total energy
approach a plateau. Results
[calculated, `first step result (submission_to_roy)/reproducibility/cutoff_results.csv`]:

| ecutwfc (Ry) | ecutrho (Ry) | energy distance from best (meV/atom) | pressure (kbar) |
|---:|---:|---:|---:|
| 50 | 400 | 6.845 | -0.08 |
| 60 | 480 | 2.590 | 2.37 |
| 70 | 560 | 2.023 | 1.94 |
| 80 | 640 | 0.572 | 2.05 |
| 90 | 720 | **0.104** | 2.36 |
| 100 | 800 | 0 (reference) | 2.32 |

Read it like this: "if I use 90 Ry instead of the expensive 100 Ry, I make an
error of 0.104 meV per atom" - about a **ten-thousandth of a percent** of the
total energy (~2269 Ry for this cell). That is far below anything we care
about, so **90/720 Ry was selected**. The meV/atom unit is used because
errors grow with cell size; per-atom numbers are comparable across materials.

### 4.2 Step 2 - k-point convergence test

**Question answered:** which mesh is dense enough?
**Method:** cutoff fixed at 90/720, mesh varies
[calculated, same folder, `kpoint_results.csv`]:

| mesh | raw k-points | irreducible | distance from best (meV/atom) |
|---|---:|---:|---:|
| 2x2x1 | 4 | 2 | 3.406 |
| 3x3x2 | 18 | 6 | 1.085 |
| 4x4x2 | 32 | 8 | **0.253** |
| 5x5x3 | 75 | 12 | 0 (reference) |

Decision: `4x4x2` (0.25 meV/atom) is good enough for the structural
optimization where hundreds of SCF cycles run; the finer `5x5x3` is kept for
the single definitive SCF afterwards. Cheap where it can be, accurate where
it must be.

### 4.3 Step 3 - variable-cell relaxation (`vc-relax`)

The database geometry was measured/settled under someone else's conditions;
our PBE functional has its own idea of the ideal bond lengths. **vc-relax**
lets both the atom positions *and* the box shape adjust downhill (the BFGS
algorithm follows computed forces on atoms and stress on the cell) until:
forces < 1e-3 Ry/bohr, energy steps < 1e-5 Ry, pressure < 0.5 kbar
(`etot_conv_thr`, `forc_conv_thr`, `press_conv_thr` in
`qe/prepare_relax.py`).

Results [calculated, `logs/SrCu2SnS4.relax.out`, relaxed CIF in
`structures/SrCu2SnS4.relaxed.cif`]:

- symmetry **kept** `P3_121` - the structure is genuinely stable there, it
  did not want to distort into something else;
- volume 543.884 -> 546.507 A^3, i.e. **+0.48%** - a typical, healthy PBE
  drift. A wild volume change would have been a red flag.

### 4.4 Step 4 - final SCF (annotated real input)

This is `qe/01_scf/SrCu2SnS4.scf.in`, abridged and annotated - every QE input
in this workspace has the same shape:

```
&CONTROL
  calculation = 'scf',        <- which job type
  outdir = './tmp/final',     <- where the density/wavefunctions get stored
  prefix = 'SrCu2SnS4',       <- filename stem for outputs
  pseudo_dir = '.../SSSP/1.3.0/PBE/precision',   <- pseudopotential folder
/
&SYSTEM
  ecutrho = 720,              <- density cutoff (Ry)     [from step 1]
  ecutwfc = 90,               <- wavefunction cutoff (Ry)[from step 1]
  occupations = 'fixed',      <- "this is a semiconductor"
  ibrav = 0, nat = 24, ntyp = 4,   <- cell given explicitly; 24 atoms; 4 species
/
&ELECTRONS
  conv_thr = 1d-08,           <- SCF stop criterion (Ry)
  mixing_beta = 0.3,          <- density mixing fraction (stability)
/
ATOMIC_SPECIES               <- element, mass, pseudopotential file
  Cu  63.5460 Cu.paw.z_11.ld1.psl.v1.0.0-low.upf
  ...
ATOMIC_POSITIONS crystal     <- 24 atom coordinates (fractions of the cell)
  Sr 0.000000 0.562301 0.166667
  ...
K_POINTS automatic
  5 5 3 0 0 0                <- the mesh chosen in step 2
CELL_PARAMETERS angstrom     <- the relaxed cell from step 3
  6.357343 0.000000 0.000000
  ...
```

Output: the converged ground-state density in
`qe/tmp/final/SrCu2SnS4.save/` (`charge-density.dat`,
`data-file-schema.xml`) - the foundation every later step reads.

### 4.5 Step 5 - dense NSCF

Transport integrals sample band energies **finely** around E_F, so the bands
are recomputed (density frozen from step 4) on a much denser mesh:

- mesh `12x12x6` -> **100 irreducible k-points** [log];
- `nbnd = 140` bands = 105 occupied + 35 empty. The empty ones matter:
  n-type transport and finite-temperature effects need conduction states,
  and the interpolation (step 6) needs headroom above the gap;
- `diago_full_acc = .TRUE.` = solve empty bands to full accuracy too;
- this was the expensive step: **1h 29m wall** on 8 MPI ranks
  [log: `PWSCF : 1h15m CPU 1h29m WALL`].

Its physics deliverables [calculated]: VBM 7.1887 eV / CBM 7.5332 eV /
indirect gap 0.3445 eV (section 3.6).

### 4.6 Step 6 - BoltzTraP2

Driven by `boltztrap2/run_bt2.sh`, three sub-steps:

1. **interpolate** (`-m 5`): fit smooth analytic curves through the 100
   computed k-points so bands can be evaluated *between* them (~5x denser
   effective sampling; 546 symmetry-adapted basis functions). Result:
   `SrCu2SnS4.bt2` (a serialized fit - re-usable, this is why later analysis
   needed **no** new QE runs). BoltzTraP2 keeps only bands within a window
   around E_F (here 94 bands holding 124 electrons; the deep "semicore"
   states are dropped - they cannot affect transport).
2. **integrate**: scan the chemical potential mu across the window at
   T = 300..900 K in 100 K steps -> `SrCu2SnS4.trace` (the mu-scan table,
   763 mu points x 7 temperatures) and `SrCu2SnS4.condtens` (full 3x3
   tensors).
3. **dope**: same, but at **fixed carrier densities** instead of fixed mu:
   +/-1e19, 2e19, 5e19, 1e20, 2e20, 5e20, 1e21 cm^-3 (negative = n-type =
   electrons added; positive = p-type = electrons removed) ->
   `SrCu2SnS4.dope.trace`. 14 doping levels x 7 temperatures = 98 sampled
   conditions.

Doping here is **rigid-band**: shift the filling level, keep the bands
frozen. Real dopant atoms would distort bands somewhat - a stated
approximation.

### 4.7 Step 7 - summaries in `results/`

`boltztrap2/summarize_transport.py` converts the raw traces into:

- `results/transport_full.csv` - all 98 conditions, one row each, units in
  every header;
- `results/transport_best_power_factor.csv` + `results/workflow_summary.md` -
  for each temperature and carrier sign, the row with the **largest PF/tau on
  the sampled grid**. Excerpt [calculated]:

| T (K) | Type | Density (cm^-3) | S (uV/K) | PF/tau (W m^-1 K^-2 s^-1) | zT_e |
|---:|:---:|---:|---:|---:|---:|
| 300 | n | 5.00e+20 | -27.5 | 1.330e+10 | 0.029 |
| 300 | p | 1.00e+20 | 157.2 | 5.562e+10 | 1.325 |
| 700 | p | 5.00e+20 | 161.0 | 1.783e+11 | 1.481 |
| 800 | p | 5.00e+20 | 176.7 | 1.991e+11 | **1.898** |
| 900 | p | 1.00e+21 | 144.0 | 2.144e+11 | 1.356 |

How to read one row in words: *"at 300 K, if holes at 1e20 per cm^3 could be
achieved, the calculation gives S = +157 uV/K (positive sign = p-type), and
the tau-scaled power factor / electronic-only zT shown."*

The one-sentence physics conclusion of the first pass: **p-type beats n-type
at every sampled temperature** for this material.

Two warnings that cannot be repeated often enough:

- the zT_e = 1.898 at 800 K is an **electronic-only upper bound** (no lattice
  heat conduction in the denominator, section 3.8). It is *coincidentally*
  close to the database prediction 1.895 - **different quantities, unrelated**.
- "best" = best **on the sampled 14 x 7 grid**, not a continuous optimum.

---

## 5. Round two: validating the DOS and the Seebeck figure

After reviewing the first package, Roy asked for two more things
(both delivered in `second step result (DOS and Seebeck)/`).

### 5.1 The DOS comparison - *why*

All transport numbers rest on BoltzTraP2's **interpolated** bands (step 6.1).
If the interpolation were bad, everything downstream would be junk. The check:
compute the DOS twice from the same underlying eigenvalues -

- once with QE's own `dos.x` directly on the raw NSCF eigenvalues
  (Gaussian smearing 0.005 Ry = 0.068 eV), and
- once from the BoltzTraP2 interpolation -

and overlay them. Result [calculated,
`results/dos_qe_vs_boltztrap2.png/.csv`, method in `dos_comparison.md`]:

- agreement within |E - E_F| < 5 eV after matching the smearing width:
  **Pearson r = 0.9943**, relative difference 6.6%;
- both show the **same gap**, ~0 DOS across [0, 0.3445] eV;
- integral checks: QE 210.0 electrons at E_F (all bands); BoltzTraP2 124
  (60-ish deep semicore states intentionally dropped - the expected
  difference, visible only at the window edges +/-5.6 eV).

Verdict: the interpolation is trustworthy where transport happens. This is
what "validating a calculation" looks like: never trust one pipeline's output
until an independent route reproduces it.

### 5.2 The Seebeck figure - *how to read it*

`results/seebeck_vs_mu.png`: S versus chemical potential mu at seven
temperatures, x-axis centered on E_F (the request from Roy).

- **x-axis** `mu - E_F`: where the filling level sits. Moving left of 0 =
  removing electrons = p-doping; moving right past the gap = adding
  electrons = n-doping. The shaded band [0, 0.3445 eV] is the gap.
- **Sign of S** tells the carrier type directly: positive on the p-side,
  negative on the n-side, one sign flip inside the gap.
- **The huge peaks inside the gap** (+644 / -548 uV/K at 300 K [calculated])
  belong to the undoped "intrinsic" regime - impressive-looking but nearly
  useless (no carriers, no conductivity). Real devices sit just outside the
  band edges, e.g. the +157 uV/K point from the table above.
- **Peaks shrink as T rises** (300 -> 900 K): heat excites electrons across
  the small PBE gap, and electrons + holes conducting together partially
  cancel each other's voltage ("bipolar conduction"). A small-gap material
  always suffers this at high T; remember the true gap is probably somewhat
  larger than PBE's 0.3445 eV.
- Cross-checks behind the figure (all in `boltztrap2/plot_seebeck.py`
  output): the scalar S equals the average of the tensor diagonal (to
  1.2e-5); charge neutrality holds at E_F (+0.018 e/cell residual); the scan
  reproduces the doped-grid value (157.4 vs 157.2 uV/K).
- Why S is trustworthy while sigma is not: **tau cancels in S** under CRTA
  (section 3.8). S is the one transport number this workflow pins down
  absolutely (within PBE / no-SOC / rigid-band / polycrystalline-average
  caveats).

---

## 6. The second material: SrZrS3 (work in progress)

### 6.1 Why everything must be re-tested

SrZrS3 has different elements (different pseudopotential hardness -> its own
cutoff) and a different cell shape (3.84 x 8.59 x 14.00 A orthorhombic,
Pnma, 20 atoms -> its own k-mesh). House rule: **convergence parameters are
per-material, never copied.** Also structure-specific: the workspace uses
the experimentally observed `mp-558760` phase - *not* the `mp-5193`
perovskite polymorph of the same formula (different crystal = different
physics; an explicit warning lives in `thermo_candidates/SrZrS3/CLAUDE.md`).

### 6.2 Its cutoff test [calculated today, `qe/convergence/cutoff_results.csv`]

All-ultrasoft pseudos; SSSP suggests 40 Ry; tested 30-60 Ry (dual 8) on a
fixed 4x2x1 mesh; 6 SCF runs, 32-114 s each:

| ecutwfc (Ry) | distance from 60 Ry (meV/atom) | pressure (kbar) |
|---:|---:|---:|
| 30 | 2.374 | 2.92 |
| 35 | 1.138 | 3.35 |
| 40 | 0.539 | 3.42 |
| 45 | 0.262 | 3.51 |
| **50** | **0.160** | 3.55 |
| 60 | 0 (reference) | 3.50 |

**Selected 50/400 Ry** - inside the acceptance band used for SrCu2SnS4, on
the pressure plateau, and (a pleasant accident) the 50 Ry SCF costs the same
84 s as the 45 Ry one.

### 6.3 Its k-point test [calculated, `qe/convergence/kpoint_results.csv`]

At the selected 50/400 Ry:

| mesh | raw k-points | irreducible | distance from best (meV/atom) |
|---|---:|---:|---:|
| 4x2x1 | 8 | 6 | 2.885 |
| **6x3x2** | 36 | 16 | **0.286** |
| **8x4x2** | 64 | 30 | **0.036** |
| 10x5x3 | 150 | 36 | 0 (reference) |

Chosen exactly like SrCu2SnS4 (section 4.2): **6x3x2 for the relaxation**
(0.286 meV/atom - same acceptance band as SrCu2SnS4's 0.253) and **8x4x2 for
the final SCF**. Note the pattern transferred, but the *numbers* did not -
each material earned its own.

### 6.4 Relaxation, final SCF, dense NSCF [calculated]

- **vc-relax** (50/400 Ry, 6x3x2): BFGS converged in 13 steps; symmetry
  **kept Pnma**; volume 461.535 -> 464.463 A^3 (**+0.63%**) - the same
  healthy scale of PBE drift as SrCu2SnS4's +0.48%.
- **final SCF** (8x4x2): 160.00 electrons -> 80 occupied bands, matching the
  pseudopotential arithmetic (4x10 Sr + 4x12 Zr + 12x6 S).
- **dense NSCF**: 20x10x6 -> 264 irreducible points, 108 bands (80 + 28
  empty). The mesh was chosen to match the *k-spacing* of SrCu2SnS4's
  12x12x6, not its shape: the smaller SrZrS3 cell has a larger Brillouin
  zone, so equal quality genuinely needs more k-points.
- **sampled PBE gap**: VBM 7.8437 eV, CBM 8.4534 eV -> **0.6096 eV**
  (database listed 0.5512 eV [database]; both PBE-family values, both
  probably below the experimental gap).

### 6.5 Transport result, and the two-material comparison [calculated]

From `thermo_candidates/SrZrS3/results/workflow_summary.md` (same 300-900 K,
14-density grid as SrCu2SnS4):

| | SrCu2SnS4 | SrZrS3 |
|---|---|---|
| structure | P3_121 (mp-16988) | Pnma (mp-558760) |
| cutoffs (each its own test) | 90/720 Ry | 50/400 Ry |
| meshes (relax / SCF / NSCF) | 4x4x2 / 5x5x3 / 12x12x6 | 6x3x2 / 8x4x2 / 20x10x6 |
| electrons / occupied bands | 210 / 105 | 160 / 80 |
| relaxation volume drift | +0.48% | +0.63% |
| sampled PBE gap | 0.3445 eV | 0.6096 eV |
| favored carrier | p-type (both metrics) | **n-type by zT_e at every T**; p-type by PF/tau at >= 500 K |
| best sampled zT_e point | p, 800 K, 5e20 cm^-3: 1.898 | n, 700 K, 1e20 cm^-3: 1.625 |

Three lessons for a beginner in this table:

1. The *recipe* transferred, but every *number* was re-earned by that
   material's own convergence tests.
2. The physics conclusions genuinely differ: SrZrS3 leans **n-type** where
   SrCu2SnS4 leaned p-type, and its ~2x larger gap should delay the
   high-temperature bipolar collapse of S (section 5.2).
3. Never read one column alone: SrZrS3's p-branch has the *larger PF/tau*
   at >= 500 K (driven by the heavily doped 1e21 cm^-3 point) yet a much
   *lower zT_e*, because the electronic heat conductivity kappa_e grows with
   doping and sits in zT_e's denominator. Both metrics are quoted together
   everywhere in this workspace.

The usual caveats stand unchanged: best-on-sampled-grid, CRTA (no absolute
sigma or PF), no kappa_L (zT_e is an upper bound), no SOC, PBE gaps.

### 6.6 The third material, Rb2Cu2SnS4 [calculated]

Rb2Cu2SnS4 completed the identical pipeline (its own tests throughout):

- 18-atom primitive cell of the Ibam mp-18006 structure; it contains Cu again,
  so its own cutoff test landed back at 90/720 Ry (0.0896 meV/atom at 90 Ry vs
  its 100 Ry reference) - the same convergence point as SrCu2SnS4, because the
  hard Cu pseudopotential dominates both.
- relax mesh 2x4x4, final SCF 3x5x5, dense NSCF 8x14x14 (788 irreducible
  points - the most of the three, because this primitive-cell orientation
  reduces little by symmetry).
- vc-relax kept Ibam; volume 446.410 -> 450.561 A^3 (+0.93%). Final SCF: 156
  electrons -> 78 occupied bands.
- **sampled PBE gap 0.7811 eV** - the largest of the three (database listed
  0.8641 eV).
- transport: on the sampled grid, p-type is favored by BOTH PF/tau and zT_e at
  every temperature; its Seebeck coefficient keeps rising with temperature
  (+199.7 uV/K at 300 K to +232.9 uV/K at 900 K) rather than rolling over,
  consistent with the wider gap suppressing bipolar conduction. The peak
  sampled electronic zT_e is very large (6.419 at 900 K) - this is an
  electronic-only upper bound with kappa_L absent, NOT a real zT of 6.

All three first-pass workflows are now complete. The side-by-side comparison
lives in `learning/05_comparing_materials.md`; the usual caveats stand
unchanged (best-on-sampled-grid, CRTA, no kappa_L, no SOC, PBE gaps).

---

## 7. How to read every file in this workspace

### 7.1 The directory map

```
Waterloo Holger thermoelectric materials/
|- README_START_HERE.md            entry point
|- WORKFLOW_EXPLAINED.md           this guide
|- CLAUDE.md                       standing rules for the AI assistant
|- background info/                the screening list, professor's slides
|- first step result (submission_to_roy)/   frozen: what was sent to Roy
|- second step result (DOS and Seebeck)/    staged: the reply package
|- thermo_candidates/
   |- Roy_task_status.md           why these three materials
   |- scripts/                     shared input generators
   |- SrCu2SnS4/   <- completed example; layout below
   |- SrZrS3/      <- in progress (same layout)
   |- Rb2Cu2SnS4/  <- complete first pass (same layout)

SrCu2SnS4/ (the per-material layout, identical for every material)
|- structures/     source CIF + relaxed CIF        <- crystal geometry
|- qe/             inputs, convergence tests, scripts, tmp/ restart data
|- logs/           raw QE output logs              <- the evidence
|- boltztrap2/     .bt2 fit, traces, analysis scripts
|- results/        derived CSVs, plots, summaries  <- read these first
|- notes/          why this material was chosen
|- candidate.yml   screening metadata [database]
```

Rule of thumb: **read `results/`, trust but verify against `logs/`, never
edit either.**

### 7.2 Inspecting QE logs (copy-paste commands)

```bash
grep '!'                logs/SrCu2SnS4.scf.out    # converged total energy
grep 'highest occupied' logs/SrCu2SnS4.nscf.out   # VBM / CBM -> the gap
grep 'JOB DONE'         logs/*.out                # did it finish cleanly?
grep 'P='               logs/SrCu2SnS4.relax.out  # pressure during relaxation
```

If `JOB DONE.` is missing, the run died - nothing downstream of it can be
trusted.

### 7.3 BoltzTraP2 file columns

`SrCu2SnS4.trace` / `SrCu2SnS4.dope.trace` (one row per condition; header
row names them):

| Column | Unit | Meaning |
|---|---|---|
| Ef | Ry | chemical potential mu (absolute, QE zero) |
| T | K | temperature |
| N | e/cell | carriers *relative to neutral*: + = p (holes), - = n |
| DOS(ef) | 1/(Ha*cell) | DOS at mu |
| S | V/K | Seebeck (multiply by 1e6 -> uV/K) |
| sigma/tau0 | 1/(ohm m s) | conductivity per tau |
| RH | m^3/C | Hall coefficient |
| kappae/tau0 | W/(m K s) | electronic thermal conductivity per tau |
| cv, chi | - | heat capacity, susceptibility (not used here) |

`condtens` holds the same as full 3x3 tensors (9 numbers each) - used to
verify the scalar files are the tensor average.

### 7.4 The `results/` CSVs

Every column header carries its unit (workspace rule). Key ones in
`transport_full.csv`: `carrier_density_cm-3`, `seebeck_uV_K`,
`power_factor_over_tau_W_m-1_K-2_s-1`, `electronic_zT_no_lattice` - that last
name is deliberately verbose so nobody mistakes it for real zT.

### 7.5 Reproducing anything

Each step-result package has `reproducibility/README.txt` with the exact
commands, and the material folders keep the scripts that were actually run
(`qe/convergence/*.py`, `boltztrap2/*.py`). Environment setup is always:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
```

---

## 8. What the results tell us - and what they do NOT

### 8.1 Defensible statements today

1. SrCu2SnS4 (PBE, relaxed) is a small-gap **indirect semiconductor**,
   gap 0.3445 eV [calculated]; the true gap is likely larger (PBE bias).
2. The BoltzTraP2 interpolation is validated against QE's own DOS
   (r = 0.9943 near E_F) [calculated].
3. On the sampled grid, **p-type doping outperforms n-type at every
   temperature** by PF/tau; e.g. S = +157.2 uV/K at 1e20 cm^-3, 300 K
   [calculated]. Seebeck values are tau-independent and absolute within the
   stated approximations.
4. SrZrS3 (PBE, relaxed, Pnma kept) is a semiconductor with a sampled gap of
   0.6096 eV [calculated]; on its sampled grid the n-type best zT_e beats
   p-type at every temperature - the opposite carrier preference to
   SrCu2SnS4.
5. Rb2Cu2SnS4 (PBE, relaxed, Ibam kept) is a semiconductor with a sampled gap
   of 0.7811 eV [calculated] - the largest of the three; on its sampled grid
   p-type is favored by both PF/tau and zT_e at every temperature.

### 8.2 What we cannot say (yet), and what would fix it

| Cannot say | Missing ingredient | How it would be obtained |
|---|---|---|
| "sigma = X", "PF = Y" absolutely | tau | electron-phonon calculation (expensive) or fit to experiment |
| "zT = 1.9" | kappa_L | phonon/lattice-dynamics calculation |
| "the gap is 0.34 eV" (as a real-world claim) | beyond-PBE electronic structure | hybrid functional / GW (much more expensive) |
| heavy-element fine structure | SOC | rerun with spin-orbit coupling |
| "1e21 cm^-3 doping is achievable" | defect chemistry | dopability study |
| single-crystal directional values | - | the tensors exist in `condtens`; the summaries use the polycrystalline average |

### 8.3 The house rules, decoded

The rules in `CLAUDE.md` are exactly the list above enforced in practice:
never present PF/tau as absolute, never present zT_e as zT, always state
no-SOC, "best" means best-on-grid, convergence parameters are per-material,
raw outputs are immutable evidence and derived numbers go to `results/`.

---

## 9. Glossary (quick reference)

| Term | One-line meaning |
|---|---|
| DFT | quantum-mechanics approximation: solve for electron *density*, not every electron |
| PBE / GGA | the specific exchange-correlation approximation used; underestimates gaps |
| SOC | spin-orbit coupling; relativistic band effect, NOT included here |
| plane wave | the "ripple" basis functions QE builds wavefunctions from |
| ecutwfc / ecutrho | resolution knobs (Ry) for wavefunctions / density; higher = finer + slower |
| Ry (Rydberg) | energy unit, 13.6057 eV; QE's native unit (1 Ha = 2 Ry) |
| pseudopotential | frozen-core replacement of nucleus+core electrons; `.UPF` files |
| SSSP | curated pseudopotential library (v1.3.0 PBE precision here) |
| k-point / mesh | sampling point of the periodic problem / the grid of them (`4x4x2`) |
| irreducible k-points | the symmetry-distinct subset actually computed |
| Brillouin zone | the finite box the k-points live in |
| SCF | self-consistent loop -> density + total energy |
| NSCF | band energies on a dense mesh, density frozen |
| conv_thr | SCF stop criterion (1e-8 Ry here) |
| mixing_beta | fraction of new density accepted per iteration (0.3) |
| occupations='fixed' | semiconductor assumption: integer band filling |
| vc-relax | optimize atomic positions and cell shape (BFGS on forces/stress) |
| band / VBM / CBM | allowed energy ladder / top filled / bottom empty |
| band gap | energy window with no states; indirect if VBM, CBM at different k |
| E_F (Fermi energy) | filling level; = VBM here; energy zero of every plot |
| DOS | number of states per energy interval (states/eV/cell) |
| BoltzTraP2 | band-energies -> transport coefficients (Boltzmann equation) |
| interpolation multiplier | -m 5: effective k-density increase in the band fit |
| rigid band | doping approximation: shift filling, freeze band shapes |
| CRTA / tau | constant-relaxation-time approx.; tau = unknown scattering time |
| S (Seebeck) | uV/K of voltage; sign = carrier type; tau-independent |
| sigma/tau, kappa_e/tau | conductivities *per unknown tau* - relative only |
| PF/tau | S^2 sigma/tau; NOT an absolute power factor |
| zT_e | electronic-only zT (no kappa_L); an upper bound only |
| kappa_L | lattice (phonon) heat conductivity; not computed yet |
| p-type / n-type | doped with holes (+S) / electrons (-S) |
| chemical potential mu | tunable filling level in the mu-scan plots |
| bipolar conduction | electrons + holes both active (small gap, high T); shrinks S |
| meV/atom | convergence-error currency; per-atom so sizes compare |
| JOB DONE. | QE's "run finished cleanly" stamp - always check it |

---

## 10. FAQ

**Q: So did we predict zT = 1.9 for SrCu2SnS4?**
No. The 1.898 at 800 K is `zT_e` - electronic-only, missing the lattice heat
conduction that always lowers real zT. And the database's 1.895 is someone
else's model prediction. The honest statement: *"the electronic structure
looks favorable for p-type thermoelectric performance; absolute zT needs tau
and kappa_L."*

**Q: Two gaps are floating around - 0.3445 and 0.4032 eV. Which is right?**
Ours (0.3445 [calculated]) and the database's (0.4032 [database]) are both
DFT-family results with different codes/settings; both are probably *below*
the experimental gap, because PBE-type functionals underestimate gaps. For
this project's purpose (screening + trends) the discrepancy is unimportant.

**Q: Why did SrZrS3 get 50 Ry when SrCu2SnS4 needed 90?**
(Cutoffs, section 3.2 / 6.2.) Copper's pseudopotential is hard; SrZrS3 has no
copper and its own test proved 50 Ry sufficient. This is why per-material
convergence testing is a hard rule.

**Q: What does "converged to 0.16 meV/atom" actually buy us?**
It means the numerical settings contribute errors far smaller than the
physics we compare (band gaps ~ hundreds of meV, energy orderings ~ tens of
meV/atom). Numerical noise is out of the conversation.

**Q: The Seebeck peaks are ±600 uV/K - is that the headline?**
No - those sit inside the gap where there are almost no carriers (nearly
zero conductivity). Devices operate near the band edges; the meaningful
sampled numbers are ~100-180 uV/K at 1e19-1e21 cm^-3.

**Q: How expensive is all this?**
On this laptop [logs]: convergence SCFs 32-411 s each; the dense NSCF is the
big one (SrCu2SnS4: 1h29m; SrZrS3: 1h15m); BoltzTraP2 analysis is seconds to
minutes. SrZrS3's complete first pass, measured end to end: cutoff + k-point
tests ~25 min, vc-relax 36 min, final SCF 3.5 min, dense NSCF 1h15m,
BoltzTraP2 + summaries a few minutes - roughly 2.5 hours of compute.

**Q: Where do I look first when a new material finishes?**
`results/workflow_summary.md` (headline numbers + best-PF table), then
`results/*.png`, then this guide's section 8 to keep claims honest.

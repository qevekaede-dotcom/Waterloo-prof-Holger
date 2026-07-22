# Exercises (with answer key)

Twelve hands-on exercises, ordered from easy to hard. Every one of them can be
answered purely from files inside this repository — no external references and
no memorized physics. Try each exercise first, then check the
[Answer key](#answer-key) at the bottom.

How to work:

- Open a terminal and `cd` into the workspace. **Every path here contains
  spaces, so always quote them** in shell commands (for example
  `grep gap "logs/SrZrS3.nscf.out"`).
- The concept background lives in `../WORKFLOW_EXPLAINED.md`; each exercise
  points to the numbered section that explains the idea being exercised, so
  this document does not repeat the theory.
- Practical, deeper skills are in the sibling learning documents:
  `01_tools_quantum_espresso.md` (running Quantum ESPRESSO and reading its
  logs), `02_tools_boltztrap2.md` (the BoltzTraP2 stages and file formats),
  `03_code_walkthrough.md` (every script), `04_per_material_playbook.md` (the
  7-step pipeline with real numbers), `05_comparing_materials.md` (judging a
  candidate), and `06_data_handling.md` (CSV columns, unit conversions,
  sanity checks). The curriculum map is `README.md` in this folder.

Vocabulary you need for these exercises, in one place (fuller definitions in
`../WORKFLOW_EXPLAINED.md`):

- **DFT** = density functional theory, the physics method used to compute the
  electrons. **PBE** is the specific approximation (a "functional") used here.
- **QE** = Quantum ESPRESSO, the DFT program. **SCF** = self-consistent field,
  the ground-state calculation. **NSCF** = non-self-consistent field, a second
  run on a denser k-point grid that reuses the SCF electron density.
- **k-points** sample the crystal's repeating (periodic) directions; a mesh
  like `12x12x6` means that many divisions along the three axes.
- **Cutoffs** `ecutwfc`/`ecutrho` (written like `90/720 Ry`) set how many plane
  waves describe the wavefunction and the charge density; `Ry` = Rydberg, an
  energy unit.
- **BoltzTraP2** turns the band structure into transport numbers (Seebeck
  coefficient, conductivity, etc.).

House rules that apply to every answer (from `../CLAUDE.md`):

- `PF/tau` is a power factor **divided by an unknown relaxation time tau**
  (`tau`, the average time between electron scattering events). It is **never**
  an absolute power factor.
- The electronic `zT_e` is **never** the final thermoelectric `zT`. The unknown
  `tau` cancels inside `zT_e`, but the **lattice** thermal conductivity
  `kappa_L` is missing, so `zT_e` is only an electronic upper-bound-style
  indicator, not the real figure of merit.
- Every run in this workspace is **scalar-relativistic with no explicit
  spin-orbit coupling (SOC)**.
- A **"best" point is the best on the sampled grid** (the finite list of
  temperatures and carrier densities that were actually computed), not a
  continuous optimum.
- **Convergence parameters are per-material.** Cutoffs, k-meshes, and band
  counts found for one compound are never reused for another; each material
  gets its own convergence tests.

Status note: **Rb2Cu2SnS4's first pass is now complete.** Its sampled QE-PBE
gap is `0.7811 eV` **[calculated]** and its BoltzTraP2 transport is done
(p-type favored by both `PF/tau` and `zT_e`); see
`"thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md"`. Exercises 10 and
11 still deliberately use only its convergence and k-point records, so they can
be answered without those transport numbers.

Values are tagged **[calculated]** (produced by QE or BoltzTraP2 in this
workspace), **[database]** (taken from a materials database such as Materials
Project), or **[experimental]** (measured in a lab).

---

## The exercises

### Exercise 1 — SrZrS3 relaxed volume change (easy)

During "variable-cell relaxation" (`vc-relax`), QE lets the crystal cell change
shape and size until the forces and stress are tiny. The cell volume shifts a
little from the starting database structure. **By what percentage did the
SrZrS3 cell volume change during relaxation, and did it grow or shrink?**

*Hint:* read the relaxation entry in
`"thermo_candidates/SrZrS3/WORKLOG.md"`, or the relax log
`"thermo_candidates/SrZrS3/logs/SrZrS3.relax.out"`. Look for the two volume
numbers in A^3. Background: `../WORKFLOW_EXPLAINED.md` section 4.3.

---

### Exercise 2 — verify SrCu2SnS4 has 210 electrons (easy)

Each pseudopotential contributes a fixed number of valence electrons per atom
(its "Z valence"). The SrCu2SnS4 cell contains 3 Sr, 6 Cu, 3 Sn, and 12 S
atoms. **Using the valences that QE printed, add them up and confirm the cell
has exactly 210 electrons.**

*Hint:* the valence table is in the SCF log
`"thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.scf.out"`. Grep for
`atomic species` and read the "valence" column. Background:
`../WORKFLOW_EXPLAINED.md` section 3.3.

---

### Exercise 3 — read the SrZrS3 PBE band gap (easy)

The band gap is the energy jump between the highest filled electron level (the
valence band maximum, VBM) and the lowest empty one (the conduction band
minimum, CBM). QE prints both on one line of the NSCF log. **Read the two
levels and compute the sampled PBE gap of SrZrS3 in eV.**

*Hint:*
`grep "highest occupied" "thermo_candidates/SrZrS3/logs/SrZrS3.nscf.out"`.
The two numbers are the VBM and CBM in eV; subtract. Background:
`../WORKFLOW_EXPLAINED.md` section 3.6. Careful wording: this is a
**scalar-relativistic PBE gap on the sampled k-mesh**, not an experimental gap.

---

### Exercise 4 — convert 5e20 cm^-3 to electrons per SrCu2SnS4 cell (easy)

Carrier density is quoted per cubic centimeter (`cm^-3`), but it helps to know
how many extra/removed electrons that is **per unit cell**. **How many carriers
per cell does 5e20 cm^-3 correspond to for SrCu2SnS4?**

*Hint:* you need the cell volume. It is in the SCF log
`"thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.scf.out"` as
`unit-cell volume` in atomic units ((a.u.)^3 = bohr^3); 1 bohr = 0.529177 A, and
1 A = 1e-8 cm. Multiply density (in cm^-3) by the cell volume (in cm^3).
Background: `../WORKFLOW_EXPLAINED.md` section 3.8 and `06_data_handling.md`.

---

### Exercise 5 — Seebeck at 700 K, p-type, 5e20, and the best-PF table (medium)

The Seebeck coefficient `S` (units `uV/K`, microvolts per kelvin) measures the
voltage a temperature difference produces. **Find `S` for the row at 700 K,
p-type, carrier density ~5e20 cm^-3 in
`"thermo_candidates/SrCu2SnS4/results/transport_full.csv"`, then find the
p-type row at 700 K in
`"thermo_candidates/SrCu2SnS4/results/transport_best_power_factor.csv"` and
say whether they match.**

*Hint:* the column is `seebeck_uV_K`. Filter the full CSV to
`temperature_K == 700`, `carrier_type == p`, density near 5e20. Then read the
700 K p-row of the best-PF table. Ask yourself *why* they would be the same
row. Background: `../WORKFLOW_EXPLAINED.md` sections 3.8 and 4.7;
`06_data_handling.md` for the columns.

---

### Exercise 6 — why does `btp2 integrate` use `300:1000:100`? (medium)

The BoltzTraP2 driver script runs its temperature scan over `300:1000:100`, yet
the intended physics range is 300–900 K. **Explain why the script writes
`300:1000:100` and not `300:900:100`, and how many temperatures the scan
actually produces.**

*Hint:* look at the actual command in
`"thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh"` and the reasoning in
`"thermo_candidates/SrZrS3/WORKLOG.md"` (the "BoltzTraP2 template had three
bugs" entry). The `start:stop:step` triple is treated like a half-open Python
range. Check how many distinct `temperature_K` values ended up in
`"thermo_candidates/SrCu2SnS4/results/transport_full.csv"`. Background:
`../WORKFLOW_EXPLAINED.md` section 4.6; `02_tools_boltztrap2.md`.

---

### Exercise 7 — choose the SrZrS3 relaxation mesh (medium)

The workflow rule is: pick the relaxation k-mesh as the coarsest mesh whose
energy is converged to roughly the ~0.25 meV/atom band, then use one tier
denser for the final SCF. **From SrZrS3's k-point convergence numbers, which
mesh should be the relaxation mesh, and which the final-SCF mesh? Justify with
the convergence deltas.**

*Hint:* read `"thermo_candidates/SrZrS3/qe/convergence/kpoint_results.csv"`.
The `delta_meV_per_atom_vs_max` column is each mesh's energy error versus the
densest reference. Background: `../WORKFLOW_EXPLAINED.md` section 4.2;
`04_per_material_playbook.md`. Remember: this choice is SrZrS3's own — it is
not copied from any other material.

---

### Exercise 8 — spot the house-rule violations (medium)

Read this sentence:

> "SrCu2SnS4 has zT = 1.9 and a power factor of 2e11 W/m/K^2."

**Every part of it breaks a rule or misstates a number. List what is wrong.**

*Hint:* compare against `../CLAUDE.md`'s house rules and against the actual
columns in `"thermo_candidates/SrCu2SnS4/results/transport_full.csv"`. Think
about: is there a final `zT` anywhere in this workspace? What is the real name
and unit of the column near 2e11? Background: `../WORKFLOW_EXPLAINED.md`
section 8 ("what the results do NOT tell us").

---

### Exercise 9 — verify PF/tau = S^2 * sigma/tau for one row (hard)

The power factor divided by relaxation time is defined as
`PF/tau = S^2 * (sigma/tau)`, where `S` is the Seebeck coefficient and
`sigma/tau` is the conductivity divided by tau. **Take one concrete row of
`"thermo_candidates/SrCu2SnS4/results/transport_full.csv"` and check that its
`power_factor_over_tau_W_m-1_K-2_s-1` column equals `S^2 * sigma/tau` computed
from the other two columns.**

*Hint:* use the 700 K, p-type, ~5e20 cm^-3 row. Watch units: `seebeck_uV_K` is
in `uV/K`, so convert to volts per kelvin (multiply by 1e-6) before squaring.
`sigma/tau` is the `sigma_over_tau_ohm-1_m-1_s-1` column. Background:
`../WORKFLOW_EXPLAINED.md` section 3.8; `06_data_handling.md`. Do not call the
result an absolute power factor.

---

### Exercise 10 — which pseudopotential forces the 90 Ry cutoff? (hard)

SrCu2SnS4 and Rb2Cu2SnS4 both converged to a hard `90/720 Ry` plane-wave
cutoff, while SrZrS3 needed only `50/400 Ry`. **Identify which single element's
pseudopotential drives the high cutoff, and describe how you would check this
by comparing the three materials' cutoff records.**

*Hint:* the pseudopotential filenames are printed near the top of each SCF log
(grep for `read from file`). Compare which elements the two hard materials
share that SrZrS3 lacks. Then compare
`"thermo_candidates/SrCu2SnS4/qe/convergence/cutoff/cutoff_results.csv"`,
`"thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv"`, and
`"thermo_candidates/SrZrS3/qe/convergence/cutoff_results.csv"` — look at the
`delta_meV_per_atom_vs_max` column and see where each material's error drops
below the acceptance band. Background: `../WORKFLOW_EXPLAINED.md` sections 3.2
and 3.3; `05_comparing_materials.md`.

---

### Exercise 11 — Rb2Cu2SnS4 dense-NSCF k-points vs SrCu2SnS4's 100 (hard)

SrCu2SnS4's dense NSCF used a 12x12x6 mesh that reduced by symmetry to 100
irreducible k-points. **How many irreducible k-points does the Rb2Cu2SnS4 dense
NSCF use, and why is it so much larger?**

*Hint:* the Rb NSCF log is
`"thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.nscf.out"`
(`grep "number of k points"`), and the dense-NSCF sizing reasoning is in the
newest entry of `"thermo_candidates/Rb2Cu2SnS4/WORKLOG.md"`. Think about the
cell shape (primitive vs conventional) and how much symmetry can fold the mesh.
For SrCu2SnS4 the count is in
`"thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out"`. Background:
`../WORKFLOW_EXPLAINED.md` sections 3.4 and 4.5. Note: this exercise only reads
the k-point count the log prints — you do not need Rb2Cu2SnS4's gap or transport
numbers here, even though its first pass is now complete.

---

### Exercise 12 — compute zT_e for one row and match the CSV (hard)

The electronic figure of merit is
`zT_e = S^2 * (sigma/tau) * T / (kappa_e/tau)`. The unknown `tau` cancels
(it divides out top and bottom), but note the lattice term `kappa_L` is **not**
in this expression, so `zT_e` is not the final `zT`. **Compute `zT_e` for one
row of `"thermo_candidates/SrCu2SnS4/results/transport_full.csv"` from its own
columns and check it matches the `electronic_zT_no_lattice` column.**

*Hint:* use the same 700 K, p-type, ~5e20 cm^-3 row. The columns are
`seebeck_uV_K` (convert `uV/K` to `V/K` with 1e-6),
`sigma_over_tau_ohm-1_m-1_s-1`, `kappa_e_over_tau_W_m-1_K-1_s-1`, and
`temperature_K`. Background: `../WORKFLOW_EXPLAINED.md` sections 3.8 and 1.2;
`05_comparing_materials.md` explains why `electronic_zT_no_lattice` is an
electronic-only quantity, never the reported `zT`.

---

## Answer key

Every answer below was checked directly against the cited file. Numbers from
QE or BoltzTraP2 in this workspace are tagged **[calculated]**; structural
inputs from a database are **[database]**.

### Answer 1 — SrZrS3 relaxed volume change

**+0.63 % (the cell grew).** The relaxation drove the volume from 461.535 A^3
to 464.463 A^3, a `+0.63%` change. Source:
`"thermo_candidates/SrZrS3/WORKLOG.md"` (vc-relax entry:
"volume 461.535 -> 464.463 A^3 (**+0.63%**)"). **[calculated]** (the starting
461.535 A^3 comes from the `mp-558760` database structure **[database]**; the
relaxed 464.463 A^3 and the percentage are computed here). This is normal PBE
expansion — the same log notes it is "the same scale as SrCu2SnS4's +0.48%".
The relaxed symmetry stayed `Pnma` (space group No. 62).

### Answer 2 — SrCu2SnS4 has 210 electrons

The valences QE printed **[calculated, from the pseudopotentials]** are, from
`"thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.scf.out"`:

| Element | Atoms in cell | Valence (electrons/atom) [calculated] | Subtotal (electrons) |
|---------|---------------|----------------------------------------|----------------------|
| Sr      | 3             | 10.00                                  | 30                   |
| Cu      | 6             | 11.00                                  | 66                   |
| Sn      | 3             | 14.00                                  | 42                   |
| S       | 12            | 6.00                                   | 72                   |
| **Total** |             |                                        | **210**              |

30 + 66 + 42 + 72 = **210 electrons**, which matches
`number of electrons = 210.00` in the same log. **[calculated].** (The cell is
Sr3 Cu6 Sn3 S12, i.e. three formula units of SrCu2SnS4, read from the
`ATOMIC_POSITIONS`/`site n.` block of that log.)

### Answer 3 — SrZrS3 PBE band gap

**0.6097 eV.** The NSCF log line is:

```
highest occupied, lowest unoccupied level (ev):     7.8437    8.4534
```

so gap = 8.4534 - 7.8437 = **0.6097 eV**. Source:
`"thermo_candidates/SrZrS3/logs/SrZrS3.nscf.out"`. **[calculated].** This is a
**scalar-relativistic PBE gap on the sampled 20x10x6 mesh** (no SOC), which the
`WORKLOG.md` and `CLAUDE.md` for SrZrS3 record as 0.6097/0.6096 eV (the 0.6096
is the BoltzTraP2 loader's rounding of the same value). It is not an
experimental gap; standard PBE typically underestimates real gaps.

### Answer 4 — 5e20 cm^-3 in electrons per SrCu2SnS4 cell

**About 0.27 carriers per cell.** The cell volume is
`unit-cell volume = 3688.0115 (a.u.)^3` (bohr^3) in
`"thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.scf.out"`. Converting:

- 3688.0115 bohr^3 x (0.529177 A/bohr)^3 = 546.507 A^3 **[calculated]**
  (this matches the relaxed volume 546.507 A^3 in SrCu2SnS4's `CLAUDE.md`);
- 546.507 A^3 x (1e-8 cm/A)^3 = 5.4651e-22 cm^3;
- 5e20 cm^-3 x 5.4651e-22 cm^3 = **0.273 carriers per cell**.

So 5e20 cm^-3 is a little over a quarter of one carrier per unit cell — dilute
doping, consistent with the rigid-band picture in
`../WORKFLOW_EXPLAINED.md` section 4.6. **[calculated].**

### Answer 5 — Seebeck at 700 K, p-type, 5e20, vs the best-PF table

**S = 160.988 uV/K, and yes, it is the identical row.** From
`"thermo_candidates/SrCu2SnS4/results/transport_full.csv"`, the 700 K p-type
row at density 4.9975e20 cm^-3 (the grid's 5e20 point) has
`seebeck_uV_K = 160.988`. The 700 K p-type row in
`"thermo_candidates/SrCu2SnS4/results/transport_best_power_factor.csv"` is the
same density and the same `seebeck_uV_K = 160.988`, with
`power_factor_over_tau_W_m-1_K-2_s-1 = 1.78278e11`. **[calculated].**

Why they match: the best-PF table is just the subset of `transport_full.csv`
that has the largest `PF/tau` at each temperature and carrier sign. At 700 K
p-type that maximum lands on the 5e20 cm^-3 grid point, so the two files show
the same numbers. Note this "best" is the best **on the sampled density grid**
(14 discrete densities), not a continuous optimum, and `PF/tau` here is the
power factor divided by the unknown tau, not an absolute power factor.

### Answer 6 — why `300:1000:100`

The `start:stop:step` triple is treated as a **half-open range** (like Python's
`range`/`numpy.arange`): the `stop` value is excluded. So `300:1000:100`
produces `300, 400, 500, 600, 700, 800, 900` — **7 temperatures**, ending at
900 K as intended. Writing `300:900:100` would exclude 900 and stop at 800 K,
dropping the top temperature. Sources: the command
`btp2 ... integrate ... 300:1000:100` in
`"thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh"`, and the explicit note in
`"thermo_candidates/SrZrS3/WORKLOG.md"` that "`300:900:100` is a half-open
range that stops at 800 K ... replaced with `300:1000:100`". Confirmed by the
data: `"thermo_candidates/SrCu2SnS4/results/transport_full.csv"` contains
exactly 7 distinct `temperature_K` values (300 through 900, 14 rows each = 98
rows). **[calculated].**

### Answer 7 — SrZrS3 relaxation mesh

**Relaxation mesh: 6x3x2. Final-SCF mesh: 8x4x2.** From
`"thermo_candidates/SrZrS3/qe/convergence/kpoint_results.csv"`, the energy
error versus the 10x5x3 reference is:

| Mesh (SrZrS3) | Irreducible k-points [calculated] | delta vs reference (meV/atom) [calculated] |
|---------------|-----------------------------------|--------------------------------------------|
| 4x2x1         | 6                                 | 2.885                                      |
| 6x3x2         | 16                                | 0.286                                      |
| 8x4x2         | 30                                | 0.036                                      |
| 10x5x3        | 36                                | 0.000 (reference)                          |

6x3x2 is the coarsest mesh inside the ~0.25 meV/atom target band (0.286 is at
the edge of it; the `WORKLOG.md` calls this "the ~0.25 meV/atom band"), so it
is the relaxation mesh; 8x4x2 (0.036 meV/atom) is one tier denser, so it is the
final-SCF mesh. This matches the choice recorded in
`"thermo_candidates/SrZrS3/WORKLOG.md"` and `SrZrS3/CLAUDE.md`. **[calculated].**
This is SrZrS3's own convergence result — it is not inherited from SrCu2SnS4
(whose relax mesh sat at 0.253 meV/atom) or Rb2Cu2SnS4.

### Answer 8 — house-rule violations in the sentence

The sentence "SrCu2SnS4 has zT = 1.9 and a power factor of 2e11 W/m/K^2" is
wrong on every count:

1. **"zT = 1.9" invents a final figure of merit that does not exist here.** No
   final `zT` has been computed for SrCu2SnS4: doing so requires a relaxation
   time `tau` and the lattice thermal conductivity `kappa_L`, neither of which
   this workspace has. The only zT-like number in the data is
   `electronic_zT_no_lattice`, which is electronic-only and must never be called
   the final `zT` (`../CLAUDE.md` house rules; `../WORKFLOW_EXPLAINED.md`
   section 8). The value 1.9 also does not appear as any zT_e in the data.
2. **"power factor of 2e11 W/m/K^2" mislabels PF/tau as an absolute power
   factor.** The column near 2e11 is
   `power_factor_over_tau_W_m-1_K-2_s-1` — a power factor **divided by the
   unknown tau** — and its unit is `W/(m K^2 s)`, not `W/(m K^2)`. Calling it a
   power factor drops the "/tau" and drops the extra `per second` in the unit.
   (For reference the largest such value at 700 K p-type is 1.78278e11
   `W m^-1 K^-2 s^-1` **[calculated]**, from
   `"thermo_candidates/SrCu2SnS4/results/transport_full.csv"` — a `PF/tau`, not
   a power factor.)
3. **No temperature or carrier density is stated.** Both quantities vary across
   the sampled grid (7 temperatures x 14 densities), so a bare single number
   with no `T` and no doping level is meaningless, and any "best" value would be
   the best **on the sampled grid**, not a continuous optimum.

A corrected phrasing: "At 700 K and 5e20 cm^-3 p-type on the sampled grid,
SrCu2SnS4's `PF/tau` is 1.78e11 W m^-1 K^-2 s^-1 [calculated]; its electronic
`zT_e` (no lattice, no SOC) at that point is 1.48 — not a final `zT`."

### Answer 9 — verify PF/tau = S^2 * sigma/tau

**It matches exactly.** Using the 700 K, p-type, 5e20 cm^-3 row of
`"thermo_candidates/SrCu2SnS4/results/transport_full.csv"`:

- `seebeck_uV_K` = 160.988 uV/K -> S = 160.988e-6 V/K;
- `sigma_over_tau_ohm-1_m-1_s-1` = 6.87877e18 ohm^-1 m^-1 s^-1;
- S^2 * (sigma/tau) = (160.988e-6)^2 x 6.87877e18 = **1.78278e11**
  W m^-1 K^-2 s^-1;
- the CSV column `power_factor_over_tau_W_m-1_K-2_s-1` = **1.78278018593e11**.

The computed value equals the stored value to full printed precision (ratio
1.000). **[calculated].** This confirms the definition `PF/tau = S^2 * sigma/tau`,
and note it is a power factor divided by the unknown tau — not an absolute
power factor. (The unit carries an extra `s^-1` exactly because it is divided
by a time.)

### Answer 10 — which pseudopotential forces the 90 Ry cutoff

**Copper (Cu).** The SCF logs list the pseudopotential files near the top
(grep `read from file`):

- SrCu2SnS4 and Rb2Cu2SnS4 both use
  `Cu.paw.z_11.ld1.psl.v1.0.0-low.upf` — a hard **PAW** Cu pseudopotential with
  11 valence electrons.
- SrZrS3 has no Cu (its species are Sr, Zr, S, all ultrasoft) and needs a much
  lower cutoff.

So the shared hard element is Cu, and it is the reason both Cu-containing
materials converge only at `90/720 Ry`. How to check by comparing the cutoff
records — read the `delta_meV_per_atom_vs_max` column in each:

| ecutwfc (Ry) | SrCu2SnS4 delta (meV/atom) [calculated] | Rb2Cu2SnS4 delta (meV/atom) [calculated] | SrZrS3 delta (meV/atom) [calculated] |
|--------------|------------------------------------------|-------------------------------------------|---------------------------------------|
| 30           | —                                        | —                                         | 2.374                                 |
| 40           | —                                        | —                                         | 0.539                                 |
| 50           | 6.845                                    | 6.022                                     | 0.160                                 |
| 60           | 2.590                                    | 2.274                                     | 0.000 (ref)                           |
| 80           | 0.572                                    | 0.509                                     | —                                     |
| 90           | 0.104                                    | 0.090                                     | —                                     |
| 100          | 0.000 (ref)                              | 0.000 (ref)                               | —                                     |

Sources:
`"thermo_candidates/SrCu2SnS4/qe/convergence/cutoff/cutoff_results.csv"`,
`"thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv"`,
`"thermo_candidates/SrZrS3/qe/convergence/cutoff_results.csv"`. The two
Cu-materials still show ~0.5 meV/atom error even at 80 Ry and only settle by
90 Ry, while SrZrS3 is already at 0.16 meV/atom by 50 Ry — the two curves that
look alike are exactly the two that share the Cu PAW pseudopotential.
Rb2Cu2SnS4's `WORKLOG.md` states this outright: "the same hard Cu PAW
pseudopotential dominates both materials." **[calculated].** (Note each cutoff
is still selected per-material from its own test; the shared value is a physical
coincidence of sharing Cu, not a reused parameter.)

### Answer 11 — Rb2Cu2SnS4 dense-NSCF k-points

**788 irreducible k-points, versus 100 for SrCu2SnS4.** From the running log
`"thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.nscf.out"`,
`number of k points = 788` (mesh 8x14x14). SrCu2SnS4's dense NSCF has
`number of k points = 100` (mesh 12x12x6) in
`"thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out"`.

Why so much larger: Rb2Cu2SnS4 is run as the **primitive** `Ibam` cell
(`mp-18006`), and in that orientation QE's automatic mesh folds by only ~2x
under symmetry, so a full 8x14x14 = 1568-point grid reduces to 788 irreducible
points. SrCu2SnS4's cell has higher effective symmetry folding, so its 12x12x6
grid collapses all the way to 100. The
`"thermo_candidates/Rb2Cu2SnS4/WORKLOG.md"` dense-NSCF entry explains the mesh
was deliberately kept at 8x14x14 (~0.088 A^-1 spacing) rather than matching the
0.08 standard exactly (which "would about double the cost for a marginal gain"),
precisely because the weak symmetry folding makes each extra division
expensive. **[calculated].** (This answer reports only the k-point count, which
the NSCF log prints. Rb2Cu2SnS4's first pass is now complete — its sampled
QE-PBE gap is `0.7811 eV` **[calculated]**, from
`"thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md"` — but that number
is not needed here.)

### Answer 12 — zT_e for one row, matched to the CSV

**zT_e = 1.4811, matching `electronic_zT_no_lattice` exactly.** Using the same
700 K, p-type, 5e20 cm^-3 row of
`"thermo_candidates/SrCu2SnS4/results/transport_full.csv"`:

- S = 160.988e-6 V/K; `sigma/tau` = 6.87877e18 ohm^-1 m^-1 s^-1;
  `kappa_e/tau` = 8.42554e13 W m^-1 K^-1 s^-1; T = 700 K.
- zT_e = S^2 * (sigma/tau) * T / (kappa_e/tau)
       = (160.988e-6)^2 x 6.87877e18 x 700 / 8.42554e13
       = **1.48115**.
- the CSV column `electronic_zT_no_lattice` = **1.48114676347**.

The computed value equals the stored value to full printed precision.
**[calculated].** Notice the unknown `tau` cancels — it multiplies `sigma` in
the numerator and `kappa_e` in the denominator, so it divides out — which is
why `zT_e` can be reported without knowing `tau`. But the **lattice** thermal
conductivity `kappa_L` is entirely absent from this expression, so
`electronic_zT_no_lattice` is an **electronic-only** indicator, **not** the
final thermoelectric `zT`. Adding the (currently unknown) `kappa_L` to the
denominator would only lower it. Every number here is scalar-relativistic PBE
with no SOC, at one point on the sampled grid.

---

*Every value in this document was traced to the QE or BoltzTraP2 file cited
next to it and recomputed where a calculation was involved. `PF/tau` is a power
factor divided by the unknown relaxation time tau (never an absolute power
factor); `electronic_zT_no_lattice`/`zT_e` is an electronic-only quantity that
omits the lattice thermal conductivity kappa_L (never the final zT); all runs
are scalar-relativistic with no explicit SOC; every "best" is the best on the
sampled temperature/density grid, not a continuous optimum; and each material's
cutoffs and meshes come from its own convergence tests.*

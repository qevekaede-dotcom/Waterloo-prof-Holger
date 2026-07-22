# The per-material playbook: tasks, purpose, data, checks

This document turns the 7-step pipeline into a repeatable playbook. For each
step it answers six questions: (a) what is the task, (b) why does it exist,
(c) what do you type, (d) what files appear, (e) what numbers do you check and
when do you accept them, and (f) what those numbers actually came out to be
for our three materials. The theory behind each step lives in
`../WORKFLOW_EXPLAINED.md` (sections 4.1-4.7 walk the same steps on
SrCu2SnS4); this file is the *doing* companion. For tool mechanics see
`01_tools_quantum_espresso.md` and `02_tools_boltztrap2.md`; for the scripts
themselves see `03_code_walkthrough.md`; for judging the results see
`05_comparing_materials.md`; for the CSV columns see `06_data_handling.md`.
The curriculum map is `README.md` in this folder.

All repo paths below are relative to the workspace root, and the root path
contains spaces — **always quote paths in shell commands**.

**The three materials:**

| Material | Materials Project id [database] | Space group | Atoms per cell | Status |
|---|---|---|---|---|
| SrCu2SnS4 | mp-16988 | P3_121 (No. 152) | 24 | first pass complete |
| SrZrS3 | mp-558760 | Pnma (No. 62) | 20 | first pass complete |
| Rb2Cu2SnS4 | mp-18006 | Ibam (No. 72) | 18 (primitive cell) | first pass complete |

Sources: `thermo_candidates/SrCu2SnS4/README.md` and
`thermo_candidates/SrCu2SnS4/CLAUDE.md` (id, symmetry; 24 atoms from
`number of atoms/cell` in `thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.scf.out`),
`thermo_candidates/SrZrS3/CLAUDE.md` and `thermo_candidates/SrZrS3/WORKLOG.md`,
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md` (18 atoms also printed in
`thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.scf.out`).

**House rules that apply to every sentence here** (decoded in
`../WORKFLOW_EXPLAINED.md` section 8.3): `PF/tau` is a power factor *divided
by an unknown relaxation time tau*, never an absolute power factor; the
electronic `zT_e` is never the final `zT` — tau cancels inside `zT_e`, but the
lattice thermal conductivity `kappa_L` is missing from its denominator; all
runs are scalar-relativistic PBE with **no explicit spin-orbit coupling
(SOC)**; a "best" value is the best point on the sampled temperature/doping
grid, not a continuous optimum; and convergence parameters belong to one
material only — steps 1 and 2 are rerun from scratch for every new compound.

**Status note.** Rb2Cu2SnS4's first pass is now complete: its dense NSCF log
`thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.nscf.out` reports `JOB DONE`
(788 irreducible k-points, 5h27m wall), and BoltzTraP2 has been run and
summarized into `results/`. Its sampled PBE gap and every transport number
below are therefore real. As with the other two materials, all of them are
scalar-relativistic PBE with no explicit SOC, its `PF/tau` values are per-tau
(never an absolute power factor), its `zT_e` is electronic-only (an
upper-bound indicator, not the final `zT`), and every "best" is the best
point on the sampled temperature/doping grid.

---

## The pipeline at a glance

| Step | Task | Key artifact |
|---|---|---|
| 0 | Get the experimentally observed structure | `structures/<name>.cif` |
| 1 | Cutoff convergence test | `qe/convergence/cutoff_results.csv` |
| 2 | k-point convergence test | `qe/convergence/kpoint_results.csv` |
| 3 | Variable-cell relaxation (vc-relax) | `structures/<name>.relaxed.cif` |
| 4 | Final SCF on the relaxed structure | ground-state density in `qe/tmp/final/` |
| 5 | Dense NSCF (bands on a fine mesh) | eigenvalues + the sampled PBE gap |
| 6 | BoltzTraP2 interpolate / integrate / dope | `boltztrap2/*.trace`, `*.condtens` |
| 7 | Processed summaries | CSVs + `workflow_summary.md` in `results/` |

Every material directory (`thermo_candidates/<name>/`) has the same layout —
`structures/`, `qe/`, `boltztrap2/`, `logs/`, `results/`, `notes/`, plus a
`WORKLOG.md` lab notebook (layout defined in `thermo_candidates/CLAUDE.md`).
Raw outputs stay raw; only processed tables go in `results/`.

---

## Step 0 — structure acquisition

**(a) Task.** Download the crystal structure of the *experimentally observed*
polymorph from the Materials Project database as a CIF file, then generate
starter QE inputs from it.

**(b) Why it exists.** Everything downstream — energies, band gap, transport —
is computed *for whatever structure you feed in*. Databases list several
polymorphs (same formula, different atomic arrangement), some purely
hypothetical. The workspace rule is to use only experimentally observed
entries. The cautionary case is SrZrS3: `thermo_candidates/SrZrS3/CLAUDE.md`
states the structure is the experimentally observed **mp-558760** (the Pnma
"needle" phase) and orders "never substitute the **mp-5193** polymorph" — the
perovskite phase is a different crystal whose electronic structure would
answer a different question. What a CIF contains is explained in
`../WORKFLOW_EXPLAINED.md` section 3.1.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials"
python thermo_candidates/scripts/download_mp_structures.py
python thermo_candidates/scripts/make_qe_inputs.py \
    thermo_candidates/SrZrS3 structures/SrZrS3.cif
```

`download_mp_structures.py` fetches the selected Materials Project entries
through the OPTIMADE API (its docstring and the mp-id table are in the script
itself); the `make_qe_inputs.py` usage pattern above matches its docstring
(which uses SrCu2SnS4 as its example). Both live in `thermo_candidates/scripts/`.

**(d) Artifacts.** `structures/<name>.cif` (a research record — never edit or
delete), starter input templates under `qe/`, provenance notes in `notes/`.

**(e) Checks and acceptance.** The MP id is the intended *experimentally
observed* entry; formula and atom count in the CIF match the database entry;
every element's pseudopotential file exists locally (the SrZrS3 WORKLOG
records verifying all three SSSP pseudos before starting; the pseudo library
is SSSP 1.3.0 PBE precision, per the `pseudo_dir` line of
`thermo_candidates/Rb2Cu2SnS4/qe/02_nscf/Rb2Cu2SnS4.nscf.in`).

> **Health check — step 0**
> - [ ] MP id is the experimentally observed polymorph (SrZrS3: mp-558760, NOT mp-5193)
> - [ ] Atom count and formula in the CIF match the database entry
> - [ ] All pseudopotentials present locally

**(f) The real numbers.** The screening-side data come from
`background info/Materials renew.csv`, quoted in each material's `README.md`:

| Material | MP id [database] | Database band gap (eV) [database] | Predicted zT (screening model) [database] | Cell from CIF [database] |
|---|---|---|---|---|
| SrCu2SnS4 | mp-16988 | 0.4032 | 1.895 | 24 atoms, P3_121, V = 543.884 A^3 |
| SrZrS3 | mp-558760 | 0.5512 | 1.894 | 20 atoms, Pnma; a=3.84, b=8.59, c=14.00 A; V = 461.535 A^3 |
| Rb2Cu2SnS4 | mp-18006 | 0.8641 | 1.896 | 18-atom primitive cell, Ibam; a=b=c=9.49 A, non-orthogonal angles; V = 446.410 A^3 |

Sources: the three `README.md` files under `thermo_candidates/<name>/`;
volumes and cell details from `thermo_candidates/SrCu2SnS4/CLAUDE.md`,
`thermo_candidates/SrZrS3/WORKLOG.md`, and
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`. The "predicted zT" is a
database-listed screening number, not something we calculated — and the
database gaps are what our step-5 gaps get compared against.

---

## Step 1 — cutoff convergence

**(a) Task.** Run the same fixed-structure SCF at a series of plane-wave
cutoffs (`ecutwfc`, with `ecutrho = 8 x ecutwfc` because the pseudopotential
sets include ultrasoft/PAW members) and pick the cheapest cutoff whose total
energy sits within a small tolerance of the highest-cutoff reference.

**(b) Why it exists.** The cutoff controls how finely the electron
wavefunctions are described (`../WORKFLOW_EXPLAINED.md` section 3.2). Too low
and every energy, force, and band is wrong; too high and every later run
wastes hours. The required cutoff is a property of the *pseudopotentials in
the cell* (section 3.3), so it must be retested per material — this is
exactly why the three materials do NOT share a cutoff.

**(c) Commands** (inside the material folder; quote paths):

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
python qe/convergence/prepare_cutoff_inputs.py
bash   qe/convergence/run_cutoff_convergence.sh      # loops mpirun pw.x over the ecut_*.in series
python qe/convergence/extract_cutoff_results.py      # -> qe/convergence/cutoff_results.csv
```

Test design (from the two WORKLOGs): fixed coarse k-mesh (SrZrS3: 4x2x1;
Rb2Cu2SnS4: 2x4x4 — the k-error cancels in the energy *differences*), fixed
occupations, `conv_thr` 1e-8, stress printed.

**(d) Artifacts.** `qe/convergence/cutoff/outputs/ecut_*.out` (raw logs,
keep) and `qe/convergence/cutoff_results.csv` with columns
`ecutwfc_Ry, ecutrho_Ry, total_energy_Ry, delta_meV_per_atom_vs_max, pressure_kbar`.

**(e) Checks and acceptance.** Every run ends in `JOB DONE`; the energy
approaches the reference monotonically; the printed pressure reaches a
plateau (pressure converges more slowly than energy, so a flat pressure is
the stricter signal); the chosen cutoff sits in the ~0.1-0.25 meV/atom band
below the reference. The workspace precedent is SrCu2SnS4's 0.1044 meV/atom
acceptance; the SrZrS3 WORKLOG calls its own choice "comfortably inside the
acceptance band used for SrCu2SnS4".

> **Health check — step 1**
> - [ ] All series runs end in `JOB DONE`
> - [ ] Energy-vs-cutoff curve smooth and monotonic toward the reference
> - [ ] Pressure plateau reached at or below the chosen cutoff
> - [ ] Chosen delta <= ~0.25 meV/atom (ideally ~0.1) vs the reference

**(f) The real numbers** [all calculated]:

| Material | Range tested (Ry) | Chosen ecutwfc/ecutrho (Ry) | Delta at choice (meV/atom) | Neighboring deltas (meV/atom) | Pressure plateau (kbar) |
|---|---|---|---|---|---|
| SrCu2SnS4 | 50-100, ref 100 | 90/720 | 0.1044 | 80 -> 0.5719 | ~1.9-2.4 from 60 Ry |
| SrZrS3 | 30-60, ref 60 | 50/400 | 0.1596 | 45 -> 0.2617, 40 -> 0.5394 | 3.4-3.55 from 40 Ry |
| Rb2Cu2SnS4 | 50-100, ref 100 | 90/720 | 0.0896 | 80 -> 0.5088 | ~2.5-2.7 from 60 Ry |

Sources: `first step result (submission_to_roy)/reproducibility/cutoff_results.csv`,
`thermo_candidates/SrZrS3/qe/convergence/cutoff_results.csv`,
`thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv`; the plateau
descriptions match the CSV pressure columns and the two WORKLOGs.

**Why 90 Ry twice but 50 Ry once?** The required cutoff is set by the
"hardest" pseudopotential in the cell. SrCu2SnS4 and Rb2Cu2SnS4 both contain
copper, described by the same hard Cu PAW file
(`Cu.paw.z_11.ld1.psl.v1.0.0-low.upf` — the identical filename appears in
`first step result (submission_to_roy)/reproducibility/SrCu2SnS4.scf.in` and
`thermo_candidates/Rb2Cu2SnS4/qe/02_nscf/Rb2Cu2SnS4.nscf.in`). The
Rb2Cu2SnS4 WORKLOG notes SSSP suggests 90/720 for it, "Cu-driven, same
situation as SrCu2SnS4", and that landing at essentially the same convergence
point "is physically expected since the same hard Cu PAW pseudopotential
dominates both materials". SrZrS3 has no copper — its Sr/Zr/S set is all
ultrasoft, SSSP suggests only 40 Ry, and its own test settled on 50/400 Ry
(per its WORKLOG, the same per-SCF cost as 45 Ry). Same protocol,
material-specific answer: the per-material rule working as intended, not a
coincidence to reuse.

---

## Step 2 — k-point convergence

**(a) Task.** At the chosen cutoff, repeat the fixed-structure SCF over a
ladder of k-point meshes (how densely we sample the crystal's repeating
pattern — `../WORKFLOW_EXPLAINED.md` section 3.4) and pick two meshes: a
cheaper one for the relaxation and a denser one for the final SCF.

**(b) Why it exists.** Total energies, forces, and the cell stress all depend
on the k-mesh; an unconverged mesh silently distorts the relaxed structure.
Mesh shape must also match the *cell shape*: a long real-space axis needs few
k-points along it, a short axis needs many. That is why the three chosen
meshes look completely different (4x4x2 vs 6x3x2 vs 2x4x4) — each mirrors its
own reciprocal lattice. The Rb2Cu2SnS4 WORKLOG records reciprocal-lattice
lengths of 0.70/1.23/1.26 A^-1, so its mesh ladder was scaled to the ratios
~1:1.76:1.81.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
python qe/convergence/prepare_kpoint_inputs.py
bash   qe/convergence/run_kpoint_convergence.sh
python qe/convergence/extract_kpoint_results.py      # -> qe/convergence/kpoint_results.csv
```

**(d) Artifacts.** `qe/convergence/kpoints/outputs/k_*.out` and
`qe/convergence/kpoint_results.csv` with columns
`mesh, full_kpoints, irreducible_kpoints, total_energy_Ry, delta_meV_per_atom_vs_max`.

**(e) Checks and acceptance.** All `JOB DONE`; deltas fall rapidly as the
mesh densifies. Selection protocol, identical wording in both WORKLOGs: the
**relax mesh** sits inside the ~0.25 meV/atom band and the **final-SCF mesh**
is one tier denser.

> **Health check — step 2**
> - [ ] All series runs end in `JOB DONE`
> - [ ] Delta falls monotonically as the mesh densifies
> - [ ] Relax mesh within ~0.25 meV/atom of the reference; final-SCF mesh one tier denser
> - [ ] Mesh shape follows the reciprocal-lattice shape

**(f) The real numbers** [all calculated]:

| Material | Ladder tested | Reference mesh (irr. k) | Relax mesh (delta, meV/atom; irr. k) | Final-SCF mesh (delta, meV/atom; irr. k) |
|---|---|---|---|---|
| SrCu2SnS4 | 2x2x1, 3x3x2, 4x4x2, 5x5x3 | 5x5x3 (12) | 4x4x2 (0.2532; 8) | 5x5x3 (0.0 — it is the reference; 12) |
| SrZrS3 | 4x2x1, 6x3x2, 8x4x2, 10x5x3 | 10x5x3 (36) | 6x3x2 (0.2863; 16) | 8x4x2 (0.0363; 30) |
| Rb2Cu2SnS4 | 2x4x4, 3x5x5, 4x7x7, 5x9x9 | 5x9x9 (203) | 2x4x4 (0.1749; 20) | 3x5x5 (0.0161; 38) |

Sources: `first step result (submission_to_roy)/reproducibility/kpoint_results.csv`,
`thermo_candidates/SrZrS3/qe/convergence/kpoint_results.csv`,
`thermo_candidates/Rb2Cu2SnS4/qe/convergence/kpoint_results.csv`.
Rb2Cu2SnS4 converges unusually fast with k-points — its 4x7x7 rung was
already at 0.0015 meV/atom — which its WORKLOG flags explicitly.

---

## Step 3 — variable-cell relaxation (vc-relax)

**(a) Task.** Let QE move both the atoms and the cell shape/size downhill in
energy (BFGS algorithm, `cell_dofree = all`) until energy change, forces, and
cell pressure are all below thresholds, then extract the relaxed structure as
a new CIF.

**(b) Why it exists.** The database structure was determined experimentally
or relaxed with someone else's settings; our PBE functional has its own
slightly different preferred geometry. Computing bands and transport on an
un-relaxed structure mixes two inconsistent descriptions: residual forces and
stress contaminate everything derived afterwards. See
`../WORKFLOW_EXPLAINED.md` section 4.3.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
python qe/prepare_relax.py                # writes qe/00_relax/<name>.relax.in with this material's settings
bash   qe/run_relax.sh                    # mpirun -np $QE_NP pw.x -nk $QE_NK ... -> logs/<name>.relax.out
python qe/extract_relaxed_structure.py    # -> structures/<name>.relaxed.cif (+ formula sanity check)
```

The run script reads `QE_NP` (MPI ranks) and `QE_NK` (k-point pools) from the
environment (`thermo_candidates/Rb2Cu2SnS4/qe/run_relax.sh`, defaults 8/2).
On the throttling-prone laptop the production runs are wrapped as
`QE_NP=12 QE_NK=2 caffeinate -i bash qe/run_relax.sh` — see the timeline
section at the end. Thresholds, from both WORKLOGs: energy 1e-5 Ry, force
1e-3 Ry/bohr, pressure 0.5 kbar, fixed occupations.

**(d) Artifacts.** `logs/<name>.relax.out` (raw log, keep),
`structures/<name>.relaxed.cif`, restart data under `qe/tmp/`.

**(e) Checks and acceptance.** The log says `bfgs converged` with all three
criteria met; the space group is *unchanged* (a symmetry drop means something
went wrong or the structure is unstable); the volume drift vs the database
cell is small — for PBE on these sulfides, roughly +0.5 to +1% expansion is
the healthy range observed.

> **Health check — step 3**
> - [ ] `JOB DONE` and `bfgs converged` with all three criteria met
> - [ ] Final pressure near zero (well inside 0.5 kbar)
> - [ ] Space group kept (P3_121 / Pnma / Ibam)
> - [ ] Volume drift ~< 1% vs the database cell, expansion direction

**(f) The real numbers** [all calculated]:

| Material | Relax mesh | BFGS steps / SCF cycles | Final pressure (kbar) | Symmetry kept | Volume (A^3): database -> relaxed | Drift (%) |
|---|---|---|---|---|---|---|
| SrCu2SnS4 | 4x4x2 | 4 / 5 | -0.20 | P3_121 (No. 152) | 543.884 -> 546.507 | +0.48 |
| SrZrS3 | 6x3x2 | 13 / 14 | -0.03 | Pnma (No. 62) | 461.535 -> 464.463 | +0.63 |
| Rb2Cu2SnS4 | 2x4x4 | 8 / 9 | 0.07 | Ibam (No. 72) | 446.410 -> 450.561 | +0.93 |

Sources: `thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.relax.out` ("bfgs
converged in 5 scf cycles and 4 bfgs steps", final stress line P= -0.20, new
unit-cell volume 546.50692 A^3) with the database volume from
`thermo_candidates/SrCu2SnS4/CLAUDE.md`; `thermo_candidates/SrZrS3/WORKLOG.md`
(also per-axis: a -0.04%, b +0.63%, c +0.05%);
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md` and
`thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.relax.out`. All three drifts
are expansions — the expected direction for PBE — and the WORKLOGs call each
"healthy" / "normal for PBE", with Rb2Cu2SnS4's +0.93% explicitly noted as
"slightly larger ... but still normal".

---

## Step 4 — final SCF

**(a) Task.** One self-consistent field (SCF) calculation on the *relaxed*
structure at the denser final-SCF mesh, producing the converged ground-state
electron density that every later step reads.

**(b) Why it exists.** The NSCF and BoltzTraP2 stages never recompute the
density; they inherit it. If it was computed on the wrong structure or an
unconverged mesh, every band energy and transport number downstream is
quietly wrong. This step also pins down the electron count, which fixes how
many occupied bands exist and therefore how many bands the NSCF must carry.
See `../WORKFLOW_EXPLAINED.md` sections 3.5 and 4.4.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
python qe/prepare_final_scf.py     # writes qe/01_scf/<name>.scf.in on the relaxed structure
bash   qe/run_final_scf.sh         # -> logs/<name>.scf.out ; density -> qe/tmp/final/<name>.save/
```

**(d) Artifacts.** `logs/<name>.scf.out` and the ground-state density in
`qe/tmp/final/<name>.save/` — a preserved research record (the SrCu2SnS4 and
SrZrS3 CLAUDE.md files list `qe/tmp/final/` among the evidence directories).

**(e) Checks and acceptance.** `JOB DONE`; and the **electron arithmetic**
must close exactly. Each pseudopotential contributes a fixed number of
valence electrons per atom — Sr 10, Zr 12 (SrZrS3 WORKLOG arithmetic), Rb 9,
Cu 11, Sn 14, S 6 (Rb2Cu2SnS4 WORKLOG arithmetic; Cu's 11 is even in the
pseudo filename `z_11`) — and QE's `number of electrons` must equal the sum,
with occupied bands = electrons/2 (fixed occupations, non-magnetic). If it
does not close, a pseudopotential or the structure is wrong.

> **Health check — step 4**
> - [ ] `JOB DONE`
> - [ ] Electron count matches the pseudo-valence sum exactly
> - [ ] Occupied bands = electrons / 2
> - [ ] `highest occupied level` printed and physically sensible

**(f) The real numbers** [all calculated]:

| Material | Cutoffs (Ry) | Mesh | Irr. k-points | Electrons | Occupied bands | Valence arithmetic (electrons) | Highest occupied level (eV) |
|---|---|---|---|---|---|---|---|
| SrCu2SnS4 | 90/720 | 5x5x3 | 12 | 210.00 | 105 | 3x10 (Sr) + 6x11 (Cu) + 3x14 (Sn) + 12x6 (S) = 210 | 7.1805 |
| SrZrS3 | 50/400 | 8x4x2 | 30 | 160.00 | 80 | 4x10 (Sr) + 4x12 (Zr) + 12x6 (S) = 160 | 7.8437 |
| Rb2Cu2SnS4 | 90/720 | 3x5x5 | 38 | 156.00 | 78 | 4x9 (Rb) + 4x11 (Cu) + 2x14 (Sn) + 8x6 (S) = 156 | 6.2203 |

Sources: `thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.scf.out` (210.00
electrons, 105 Kohn-Sham states, 12 k-points, 7.1805 eV);
`thermo_candidates/SrZrS3/logs/SrZrS3.scf.out` and its WORKLOG (160.00, 80,
30, 7.8437 eV); `thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.scf.out` and
its WORKLOG (156.00, 78, 38, 6.2203 eV). The per-element valences are quoted
from the two WORKLOG arithmetic lines. Note: the highest occupied level alone
is not a gap — with fixed occupations the SCF only computes occupied states,
so the gap must wait for step 5 (the SrZrS3 WORKLOG makes this point
explicitly).

---

## Step 5 — dense NSCF

**(a) Task.** A non-self-consistent (NSCF) calculation that reuses the step-4
density to evaluate band energies on a much denser k-mesh, including empty
(conduction) bands — this is the data BoltzTraP2 interpolates, and it is
where the calculated band gap comes from.

**(b) Why it exists.** Transport integrals sample the band structure finely
around the band edges; the coarse SCF mesh is nowhere near enough. BoltzTraP2
also needs empty bands to describe electron (n-type) transport — without
headroom above the gap the interpolation has nothing to work with. See
`../WORKFLOW_EXPLAINED.md` sections 3.5, 3.6, and 4.5.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
python qe/prepare_nscf.py     # sizes nbnd (~35% empty-band headroom) and the dense mesh
bash   qe/run_nscf.sh         # disk_io='nowf', diago_full_acc -> logs/<name>.nscf.out
```

(The `disk_io = 'nowf'` and `diago_full_acc = .TRUE.` settings are visible in
`thermo_candidates/Rb2Cu2SnS4/qe/02_nscf/Rb2Cu2SnS4.nscf.in`.)

**(d) Artifacts.** `logs/<name>.nscf.out` and the eigenvalue XML inside
`qe/tmp/final/<name>.save/` (the input for step 6).

**(e) Checks and acceptance.** `JOB DONE`; the irreducible k-point count
matches the requested mesh; the VBM (valence band maximum) is consistent with
the step-4 highest occupied level — equal on the same sampling (SrZrS3:
7.8437 eV in both logs) or a few meV higher when the denser mesh finds a
point closer to the true band edge (SrCu2SnS4: 7.1805 -> 7.1887 eV); the CBM
(conduction band minimum) appears and the gap is positive. **Mesh sizing
rule:** match the *k-spacing* of the SrCu2SnS4 standard (~0.08 A^-1), not its
mesh numbers. SrCu2SnS4's 12x12x6 corresponds to spacings of
0.082/0.082/0.067 A^-1; SrZrS3's smaller cell has a larger Brillouin zone, so
equal spacing genuinely needs more k-points (20x10x6 -> 0.082/0.073/0.075
A^-1). Rb2Cu2SnS4's 8x14x14 gives 0.088/0.088/0.090 A^-1 — **documented as
~10% coarser** than the 0.08 standard, because in its primitive-cell
orientation QE's automatic grids reduce only ~2x by symmetry, and matching
0.08 exactly (9x16x16, ~1150 irreducible points) would about double the cost
for marginal gain. That deviation is stated in the Rb2Cu2SnS4 WORKLOG and is
covered by the standing transport-mesh-convergence caveat shared by all three
materials.

> **Health check — step 5**
> - [ ] `JOB DONE`
> - [ ] Irreducible k-point count matches the requested mesh
> - [ ] VBM consistent with the step-4 highest occupied level
> - [ ] nbnd has ~1/3 empty-band headroom above the occupied count
> - [ ] k-spacing matches (or has a *documented* deviation from) the ~0.08 A^-1 standard

**(f) The real numbers** [calculated except where marked]:

| Material | Dense mesh | k-spacing (A^-1) | Irr. k-points | nbnd (occupied + empty) | VBM (eV) | CBM (eV) | Sampled PBE gap (eV) |
|---|---|---|---|---|---|---|---|
| SrCu2SnS4 | 12x12x6 | 0.082/0.082/0.067 | 100 | 140 (105 + 35) | 7.1887 | 7.5332 | 0.3445 (indirect) |
| SrZrS3 | 20x10x6 | 0.082/0.073/0.075 | 264 | 108 (80 + 28) | 7.8437 | 8.4534 | 0.6097 (recorded as 0.6096, see step 6) |
| Rb2Cu2SnS4 | 8x14x14 | 0.088/0.088/0.090 | 788 | 105 (78 + 27) | 6.2402 | 7.0213 | 0.7811 |

Sources: `thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out` (100 k-points,
140 states, "highest occupied, lowest unoccupied level (ev): 7.1887 7.5332")
and `thermo_candidates/SrCu2SnS4/CLAUDE.md` ("sampled indirect PBE gap:
0.3445 eV"); `thermo_candidates/SrZrS3/logs/SrZrS3.nscf.out` (264 k-points,
108 states, 7.8437/8.4534) and `thermo_candidates/SrZrS3/WORKLOG.md`
(spacings, headroom); `thermo_candidates/Rb2Cu2SnS4/qe/02_nscf/Rb2Cu2SnS4.nscf.in`
(mesh 8x14x14, nbnd 105) and `thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`
(spacings, sizing reasoning); the 788 irreducible points, VBM 6.2402 eV, CBM
7.0213 eV, and 0.7811 eV gap are from the completed
`thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.nscf.out` and its WORKLOG.

Gap context (do not over-read): the calculated PBE gaps of 0.3445 eV
[calculated], 0.6096 eV [calculated], and 0.7811 eV [calculated] sit near
(and, as usual for PBE, below) the database-listed 0.4032 eV, 0.5512 eV, and
0.8641 eV [database]. PBE typically underestimates gaps, these runs contain
no explicit SOC, and "sampled" means the gap seen on this k-mesh — the true
band extrema could lie between mesh points. Rb2Cu2SnS4's 0.7811 eV is our
calculated sampled gap; do not conflate it with its database 0.8641 eV
[database].

---

## Step 6 — BoltzTraP2

**(a) Task.** Interpolate the NSCF bands onto a finer effective mesh
(`interpolate -m 5`), integrate them into temperature-dependent transport
tensors (`integrate`), and evaluate those tensors at fixed carrier densities
(`dope`) — all under the constant relaxation time approximation (CRTA), which
is why every conductivity-like output carries a `/tau`.

**(b) Why it exists.** DFT gives band energies; the Seebeck coefficient
(uV/K), `sigma/tau`, `kappa_e/tau`, and `PF/tau` require Boltzmann transport
integrals over those bands. What breaks without care: the SrZrS3 WORKLOG
records **three bugs found in the pre-made template** and fixed in
`thermo_candidates/SrZrS3/boltztrap2/run_bt2.sh` before running — (i)
`qe_source` pointed at `qe/tmp/<name>.save` instead of
`qe/tmp/final/<name>.save`; (ii) the bare `btp2` CLI crashes under NumPy 2,
so runs go through the `boltztrap2/btp2_compat.py` shim; (iii) the range
`300:900:100` is half-open (stops at 800 K) and a naive `-1e21:1e21:1e20`
doping sweep would pass through zero — replaced by `300:1000:100` and an
explicit 14-level doping list. The Rb2Cu2SnS4 WORKLOG expects "the same three
bugs" in its template. Mechanics in `02_tools_boltztrap2.md`; theory in
`../WORKFLOW_EXPLAINED.md` sections 3.8 and 4.6.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
bash boltztrap2/run_bt2.sh
# which runs, via the NumPy-2 shim:
#   python boltztrap2/btp2_compat.py -n 4 -v interpolate -m 5 -o boltztrap2/SrZrS3.bt2 qe/tmp/final/SrZrS3.save
#   python boltztrap2/btp2_compat.py -v integrate boltztrap2/SrZrS3.bt2 300:1000:100
#   python boltztrap2/btp2_compat.py -v dope boltztrap2/SrZrS3.bt2 300:1000:100 \
#       -1e21,-5e20,-2e20,-1e20,-5e19,-2e19,-1e19,1e19,2e19,5e19,1e20,2e20,5e20,1e21
```

(Command lines and the doping list are verbatim from
`thermo_candidates/SrZrS3/boltztrap2/run_bt2.sh`; the SrCu2SnS4 script uses
the identical `-m 5`, `300:1000:100`, and 14-level list, per
`thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh`.)

**(d) Artifacts.** `boltztrap2/<name>.bt2` (interpolation coefficients),
`<name>.trace` / `<name>.condtens` / `<name>.halltens` (chemical-potential
scan), `<name>.dope.trace` / `<name>.dope.condtens` / `<name>.dope.halltens`
(fixed-density), and the three logs
`logs/<name>.bt2.{interpolate,integrate,dope}.log`. All research records.

**(e) Checks and acceptance.** The loader (which re-reads the QE output) must
report a gap consistent with the NSCF log — for SrZrS3 the loader gave
0.6096 eV against 0.6097 eV from the NSCF eigenvalues, a rounding-level match
(this 0.6096 eV is the recorded headline gap in its CLAUDE.md and README). At
zero doping the chemical potential must sit inside the gap (charge neutrality
at E_F); the doped output must contain exactly temperatures x densities rows.

> **Health check — step 6**
> - [ ] Loader gap matches the NSCF gap (rounding-level)
> - [ ] Neutrality: undoped chemical potential falls inside the gap
> - [ ] All 7 temperatures x 14 doping levels present in the dope output
> - [ ] Every `sigma`, `kappa_e`, `PF` output understood as per-tau (CRTA)

**(f) The real numbers:**

| Material | Interp. multiplier | T grid (K) | Doping grid (cm^-3) | Gap used (eV) | Headline on the sampled grid (CRTA, no SOC) |
|---|---|---|---|---|---|
| SrCu2SnS4 | -m 5 | 300-900, step 100 | 14 levels, 1e19-1e21, both signs | 0.3445 [calculated] | p-type best `PF/tau` exceeds the n-type best at each sampled temperature |
| SrZrS3 | -m 5 | 300-900, step 100 | same 14-level list | 0.6096 [calculated] | at each sampled T the n-type best-power-factor point also has the higher `zT_e` than the p-type best-PF point (top such point: `zT_e` 1.625 at 700 K, n-type 1e20 cm^-3, S = -173.8 uV/K); note `zT_e` itself climbs higher (~6.5) at lighter ~1e19 doping, which is not the best-PF point; p-type best `PF/tau` is larger at >= 500 K (the 1e21 cm^-3 point) — quote both metrics, never one |
| Rb2Cu2SnS4 | -m 5 | 300-900, step 100 | same 14-level list | 0.7811 [calculated] | p-type is favored by BOTH `PF/tau` and `zT_e` at every sampled T — the clean case. Largest sampled `PF/tau` 1.981e11 W m^-1 K^-2 s^-1 at 700 K, p-type 9.99e20 cm^-3 (S = +211.7 uV/K); peak sampled `zT_e` 6.419 at 900 K, p-type 1.00e21 cm^-3 (electronic-only upper bound, NOT a real zT of 6); at 300 K the best-PF point is p-type 5.00e20 cm^-3, S = +199.7 uV/K — quote both metrics, never one |

Sources: `thermo_candidates/SrCu2SnS4/CLAUDE.md` and
`first step result (submission_to_roy)/reproducibility/calculation_notes.md`;
`thermo_candidates/SrZrS3/WORKLOG.md`, `thermo_candidates/SrZrS3/CLAUDE.md`,
and `thermo_candidates/SrZrS3/results/workflow_summary.md` (the 700 K n-type
row); `thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md` and
`thermo_candidates/Rb2Cu2SnS4/results/transport_best_power_factor.csv` (the
best-PF rows and gap), with the fixed run recorded in
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md` and the artifacts
(`Rb2Cu2SnS4.bt2`, `.trace`, `.dope.trace`, `.condtens`) now in
`thermo_candidates/Rb2Cu2SnS4/boltztrap2/`.
Reminder: `zT_e` is the electronic-only figure of merit — tau cancels inside
it, but `kappa_L` is absent from its denominator, so it is an upper-bound
style indicator, never the final `zT`. And every "best" above is the best
*sampled grid point*, not a continuous optimum. Note the two finished
materials prefer opposite carrier signs — the SrZrS3 WORKLOG calls it "same
recipe, different physics" — which is exactly why headline claims must name
the metric and the grid point.

---

## Step 7 — summaries in `results/`

**(a) Task.** Reduce the raw BoltzTraP2 dope output into small, readable CSVs
and a prose summary, leaving the raw outputs untouched.

**(b) Why it exists.** The raw `.dope.trace` is a wide text file in
atomic-ish units; nobody should quote numbers straight from it. The summary
script converts to labeled units, tags what is per-tau, and writes the tables
that emails and comparisons are built from. Workspace rule
(`thermo_candidates/CLAUDE.md`): raw files never move into `results/`;
`results/` holds only derived tables. See `../WORKFLOW_EXPLAINED.md` section
4.7 and, for every column meaning, `06_data_handling.md`.

**(c) Commands.**

```bash
cd "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrZrS3"
python boltztrap2/summarize_transport.py    # -> results/*.csv + results/workflow_summary.md
```

**(d) Artifacts.** `results/transport_full.csv` (every grid point),
`results/transport_best_power_factor.csv` (per-temperature best *sampled*
`PF/tau` points for each carrier sign), `results/workflow_summary.md`.
SrCu2SnS4 additionally has second-pass validation files
(`results/dos_qe_vs_boltztrap2.csv`, `results/seebeck_vs_mu.csv`, and their
write-ups) from the DOS/Seebeck round — see `../WORKFLOW_EXPLAINED.md`
section 5.

**(e) Checks and acceptance.** Row count equals the grid size (14 densities x
7 temperatures = 98 data rows); every column header carries its unit; per-tau
columns are named as such; the electronic zT column is explicitly named so it
cannot be mistaken for a final zT. The actual header of both finished files:

```text
temperature_K,carrier_type,carrier_density_cm-3,signed_density_cm-3,
chemical_potential_Ry,seebeck_uV_K,sigma_over_tau_ohm-1_m-1_s-1,
kappa_e_over_tau_W_m-1_K-1_s-1,power_factor_over_tau_W_m-1_K-2_s-1,
electronic_zT_no_lattice,hall_m3_C,smoothed_DOS_Ha-1_uc-1,
cv_J_mol-1_K-1,chi_m3_mol-1
```

(one line in the file; wrapped here for readability).

> **Health check — step 7**
> - [ ] `transport_full.csv` has 98 data rows (14 densities x 7 temperatures)
> - [ ] Per-tau columns named `_over_tau_` with units; zT column named `electronic_zT_no_lattice`
> - [ ] Numbers trace back to the `.dope.trace` file; raw outputs unmoved

**(f) The real numbers:**

| Material | transport_full.csv data rows | Grid | Status |
|---|---|---|---|
| SrCu2SnS4 | 98 | 14 densities x 7 temperatures | complete [calculated] |
| SrZrS3 | 98 | 14 densities x 7 temperatures | complete [calculated] |
| Rb2Cu2SnS4 | 98 | 14 densities x 7 temperatures | complete [calculated] |

Sources: `wc -l` (99 lines including header) and headers of
`thermo_candidates/SrCu2SnS4/results/transport_full.csv`,
`thermo_candidates/SrZrS3/results/transport_full.csv`, and
`thermo_candidates/Rb2Cu2SnS4/results/transport_full.csv` (also 99 lines),
whose `results/` now holds `transport_full.csv`,
`transport_best_power_factor.csv`, and `workflow_summary.md`. A worked example of reading one best
row, from `thermo_candidates/SrZrS3/results/workflow_summary.md` [calculated]:
at 300 K the best sampled n-type point is 5.00e19 cm^-3 with S = -134.4 uV/K,
`PF/tau` = 4.080e10 W m^-1 K^-2 s^-1, and `zT_e` = 0.894 — a per-tau power
factor and an electronic-only zT on a sampled grid, nothing more.

---

## The whole pipeline on a timeline

Measured wall/CPU times from the retained logs and WORKLOGs (machine, per the
Rb2Cu2SnS4 WORKLOG: Apple M5 Pro, 18-core CPU, 24 GB unified memory; QE runs
used 4-12 MPI ranks depending on the stage):

| Step | SrCu2SnS4 | SrZrS3 | Rb2Cu2SnS4 |
|---|---|---|---|
| 1. Cutoff runs (each) | not re-timed in the retained records | 32-114 s (4 ranks) | ecut_90: 17m26s CPU but 1h37m wall; ecut_80: 8m27s CPU but 1h56m wall (both suspended overnight, see below) |
| 2. k-point runs (each) | not re-timed in the retained records | 86-411 s (4 ranks) | 2088 s (4x7x7) and 4817 s (5x9x9) at 12 ranks; 3.3 h and 6.0 h wall when throttled overnight at 4 ranks |
| 3. vc-relax | 25m23s wall | 35m47s wall | 49m48s wall |
| 4. Final SCF | 7m08s wall | 3m28s wall | 13m14s wall |
| 5. Dense NSCF | 1h15m CPU / 1h29m wall | 28m30s CPU / 1h15m wall | 5h27m wall (12 ranks / 2 pools; 788 irreducible k-points) |
| 6-7. BoltzTraP2 + summaries | not separately timed in the retained logs | same-day tail of the first pass (all five WORKLOG entries carry the same date) | minutes, same-day tail after the dense NSCF |

Sources: `thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.relax.out`,
`.../SrCu2SnS4.scf.out`, `.../SrCu2SnS4.nscf.out` (the `PWSCF ... WALL`
lines); `thermo_candidates/SrZrS3/WORKLOG.md` and
`thermo_candidates/SrZrS3/logs/SrZrS3.{scf,nscf}.out`;
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md` and
`.../logs/Rb2Cu2SnS4.{relax,scf,nscf}.out` (the completed NSCF's 5h27m wall).

The shape to remember: convergence tests cost seconds to minutes each, the
relaxation costs tens of minutes (25-50 min here), and the dense NSCF
dominates — from ~1.5 h wall upward as the irreducible k-point count grows
(100 -> 264 -> 788 across the three materials).

**The machine-throttling lesson** (from
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`). Overnight, the laptop suspended
and background-scheduled the QE jobs: `k_2x4x4` took 3.3 h and `k_3x5x5`
6.0 h of wall time versus ~17 min of CPU for the same-size daytime run, and
one cutoff run showed 1h56m wall against only 8m27s CPU. The diagnostic was
the **wall/CPU gap with uniform SCF iteration counts (17-18 in all six
cutoff runs)** — a machine effect, not a physics problem, so no input needed
changing. The fix, applied to every long run since: wrap it in
`caffeinate -i` (blocks idle sleep for the job's duration) and run with
`QE_NP=12 QE_NK=2` — 12 MPI ranks as 2 k-point pools x 6-way plane-wave
parallelization. Pools were capped at 2 because each pool replicates memory:
the 4-rank single-pool run used ~6.8 GB, so 4 pools would have exceeded the
24 GB machine, while 2 pools sit around 10-14 GB. The expected ~2.5-3x
speedup was confirmed at 12 ranks (the 2088 s and 4817 s runs above). The
20-core GPU stays idle: QE's GPU acceleration is CUDA/NVIDIA-only. Practical
rule: **always compare wall time against CPU time before blaming the
physics.**

---

## Self-review (scientific rigor)

Every number above was traced to a file read while writing: the three
convergence CSV pairs, the three material README/CLAUDE/WORKLOG files, the QE
logs (`SrCu2SnS4.{relax,scf,nscf}.out`, `SrZrS3.{scf,nscf}.out`, and
`Rb2Cu2SnS4.{relax,scf,nscf}.out`), the frozen SrCu2SnS4 inputs and
`calculation_notes.md` in `first step result (submission_to_roy)/reproducibility/`,
the three `run_bt2.sh` scripts, `Rb2Cu2SnS4.nscf.in`, the `results/` CSV
headers and row counts, and the `SrZrS3` and `Rb2Cu2SnS4`
`results/workflow_summary.md` files (plus
`Rb2Cu2SnS4/results/transport_best_power_factor.csv`). Values are
tagged [calculated] or [database]; no experimental values appear in this
document. Limitations restated: all transport is CRTA per-tau (no absolute
power factor anywhere), `zT_e` is electronic-only (no kappa_L, so no final
zT), no explicit SOC in any run, gaps are sampled on finite meshes,
transport-mesh convergence is an unchecked standing caveat for all three
materials, and Rb2Cu2SnS4's gap and transport entries are now filled in from
its completed first pass (its `zT_e` of 6.419 is an electronic-only
upper-bound point, not a real zT).

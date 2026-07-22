# Quantum ESPRESSO in practice

Document 1 of the learning curriculum (map: `learning/README.md`). The
concept companion is `../WORKFLOW_EXPLAINED.md`: it explains *what* DFT is
and *why* each parameter exists. This document shows the *practice*: the
real input files, run scripts, and log files in this repository, so you can
run Quantum ESPRESSO yourself and read what it prints back.

Conventions: every value is tagged **[calculated]** (produced by a run in
this repo), **[database]** (taken from an external source such as the
Materials Project or the SSSP pseudopotential library), or
**[experimental]** (measured in a lab). Every table column carries its
unit. All runs here are scalar-relativistic PBE with **no explicit
spin-orbit coupling (SOC)**, and convergence parameters (cutoffs, k-meshes,
band counts) are chosen **per material**, never copied from one compound to
another.

Sibling documents: `02_tools_boltztrap2.md` (the transport step that
consumes QE output), `03_code_walkthrough.md` (the helper scripts that
generate these inputs), `04_per_material_playbook.md` (the 7-step
pipeline), `06_data_handling.md` (units and CSV skills), `07_exercises.md`
(practice tasks against these same files).

---

## 1. What Quantum ESPRESSO is and which executables this repo uses

**Quantum ESPRESSO (QE)** is an open-source suite of programs for
density-functional theory (DFT) calculations on crystals. If "DFT" means
nothing to you yet, read `../WORKFLOW_EXPLAINED.md` sections 2.1-2.4 first;
in one sentence, DFT solves an approximate quantum-mechanics problem for
the electron density of a crystal and returns total energies, forces, and
electron energy levels (bands).

"Suite" is literal. The local build directory

```text
~/scientific-tools/apps/qe/build-cmake/bin
```

contains 56 separate executables (counted with `ls | wc -l`), each doing
one job. On this machine the bare command `pw.x` resolves to that
directory (checked with `command -v pw.x`). This project uses exactly two
of the 56:

| Executable | Job in this repo |
|---|---|
| `pw.x` | the main DFT engine: structure relaxation, SCF, NSCF (section 3) |
| `dos.x` | post-processing: reads a finished `pw.x` run and writes a density-of-states table (section 6) |

The version is frozen in the reproducibility notes that were sent with the
first result package, `first step result
(submission_to_roy)/reproducibility/README.txt`:

> Quantum ESPRESSO pw.x 7.5 development build

The logs confirm it. Line 2 of
`thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out` reads
`Program PWSCF v.7.5 starts on 30Jun2026 at  5:47:52`, and the `dos.x` log
`thermo_candidates/SrCu2SnS4/qe/dos/SrCu2SnS4.dos.out` even records the
exact source state: `Git branch: develop`, last commit
`ea9b1b3d7915154c244e4a71786faaa0fdafa55c`. A "development build" means it
was compiled from the develop branch of the QE source rather than a tagged
release — worth recording, because reproducing a number years later
requires knowing exactly which code produced it.

---

## 2. Anatomy of a pw.x input file

A `pw.x` input file has two kinds of blocks:

- **Namelists**: Fortran-style blocks starting with `&NAME` and ending
  with `/`, holding `keyword = value` pairs. Keyword order inside a
  namelist does not matter.
- **Cards**: blocks starting with an ALL-CAPS keyword followed by data
  lines. Here line order *does* matter (atom 3 is the third line).

The walk-through below uses the real final-SCF input
`thermo_candidates/SrCu2SnS4/qe/01_scf/SrCu2SnS4.scf.in` (every parameter
quoted from that file). `../WORKFLOW_EXPLAINED.md` section 4.4 annotates
the same file from the physics side; here we go keyword by keyword.

### 2.1 `&CONTROL` — what kind of run, and where files go

```fortran
&CONTROL
  calculation = 'scf',
  disk_io = 'medium',
  outdir = './tmp/final',
  prefix = 'SrCu2SnS4',
  pseudo_dir = '/Users/kaede/scientific-tools/pseudopotentials/SSSP/1.3.0/PBE/precision',
  restart_mode = 'from_scratch',
  verbosity = 'high',
/
```

| Keyword | Value here | Plain-language meaning |
|---|---|---|
| `calculation` | `'scf'` | which job to run. `scf` = self-consistent field: iterate until the electron density stops changing (see `../WORKFLOW_EXPLAINED.md` 3.5). Other values used in this repo: `'nscf'`, `'vc-relax'` (section 3). |
| `disk_io` | `'medium'` | how much intermediate data to write to disk. `'medium'` keeps what a follow-up calculation needs; the NSCF later uses `'nowf'` = "do not keep wavefunctions" to save gigabytes. |
| `outdir` | `'./tmp/final'` | scratch/output directory. QE creates `<outdir>/<prefix>.save/` inside it (section 7.2). Relative to where `pw.x` is launched. |
| `prefix` | `'SrCu2SnS4'` | name stem for all output files of this run. A later run with the same `prefix` + `outdir` can find this run's data — that is exactly how NSCF finds the SCF density. |
| `pseudo_dir` | SSSP 1.3.0 PBE precision path | folder holding the pseudopotential `.UPF` files named in `ATOMIC_SPECIES`. SSSP is a curated pseudopotential library [database]; see `../WORKFLOW_EXPLAINED.md` 3.3. |
| `restart_mode` | `'from_scratch'` | start fresh rather than continuing an interrupted run. |
| `verbosity` | `'high'` | print more detail into the log (e.g. eigenvalues at every k-point) — helpful because the logs are our permanent record. |

### 2.2 `&SYSTEM` — what the crystal is and how finely to describe it

```fortran
&SYSTEM
  ecutrho = 720,
  ecutwfc = 90,
  occupations = 'fixed',
  ibrav = 0,
  nat = 24,
  ntyp = 4,
/
```

| Keyword | Value here | Plain-language meaning |
|---|---|---|
| `ecutwfc` | `90` (Ry) | plane-wave cutoff for wavefunctions — the resolution knob. Higher = finer description, slower run. 90 Ry was selected by SrCu2SnS4's own cutoff convergence test [calculated]; theory in `../WORKFLOW_EXPLAINED.md` 3.2. |
| `ecutrho` | `720` (Ry) | cutoff for the electron *density*. Here 8x `ecutwfc`, required because ultrasoft/PAW pseudopotentials (the Cu, Sn, Sr, S files below) need a denser density grid. Written "90/720 Ry" in our notes. |
| `occupations` | `'fixed'` | fill bands with whole electrons (2 per band), the correct choice for a semiconductor with a gap. Metals need smearing instead. |
| `ibrav` | `0` | Bravais-lattice index. `0` = "I will give you the three cell vectors explicitly in a `CELL_PARAMETERS` card" instead of picking a numbered lattice type. |
| `nat` | `24` | number of atoms in the cell (3 Sr + 6 Cu + 3 Sn + 12 S — count the lines in `ATOMIC_POSITIONS`). |
| `ntyp` | `4` | number of distinct chemical species (Sr, Cu, Sn, S). |

**House rule reminder:** 90/720 Ry is SrCu2SnS4's convergence result, not a
default. Rb2Cu2SnS4 repeated the whole 50-100 Ry test for itself
(`thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv`) and only
then selected its own 90/720 Ry — at 90 Ry its energy error vs the 100 Ry
reference is 0.0896 meV/atom [calculated]. Same landing point, but it had
to be earned independently.

### 2.3 `&ELECTRONS` — how the SCF loop behaves

```fortran
&ELECTRONS
  conv_thr = 1d-08,
  diagonalization = 'david',
  electron_maxstep = 200,
  mixing_beta = 0.3,
/
```

| Keyword | Value here | Plain-language meaning |
|---|---|---|
| `conv_thr` | `1d-08` (Ry) | stop the SCF loop when the estimated energy error drops below this. 1e-8 Ry is tight, deliberately: transport quantities are sensitive to band details. |
| `diagonalization` | `'david'` | the numerical algorithm (Davidson) used to solve for the band energies at each iteration. The standard, robust choice. |
| `electron_maxstep` | `200` | give up after 200 SCF iterations (a failed run prints `convergence NOT achieved`, see section 8). |
| `mixing_beta` | `0.3` | fraction of the newly computed density mixed into the running density each iteration. Smaller = more cautious = more stable but slower. |

### 2.4 `&IONS` and `&CELL` — empty here

The file contains `&IONS / ` and `&CELL /` with nothing inside: an SCF run
does not move atoms or change the cell, so there is nothing to configure.
They are filled in for the relaxation run (section 3.3).

### 2.5 The cards

```text
ATOMIC_SPECIES
  Cu  63.5460 Cu.paw.z_11.ld1.psl.v1.0.0-low.upf
  S  32.0650 s_pbe_v1.4.uspp.F.UPF
  Sn  118.7100 Sn_pbe_v1.uspp.F.UPF
  Sr  87.6200 Sr_pbe_v1.uspp.F.UPF
```

One line per species: name, atomic mass (amu) [database, standard atomic
weights], and the pseudopotential file to load from `pseudo_dir`. The file
names encode the type: `paw` = projector augmented wave (Cu), `uspp` =
ultrasoft (S, Sn, Sr). Mass does not affect the electronic results in these
runs; it matters only for dynamics we do not do here.

```text
ATOMIC_POSITIONS crystal
  Sr 0.000000 0.562301 0.166667
  Sr 0.437699 0.437699 0.500000
  ...            (24 lines total)
  S 0.882398 0.236202 0.004683
```

One line per atom: species and three coordinates. The word `crystal` means
the coordinates are **fractions of the cell vectors** (0.5 = halfway along
that vector), not Angstroms. These particular positions are the *relaxed*
geometry [calculated] produced by the earlier `vc-relax` step — the SCF
input was regenerated from the relaxation output.

```text
K_POINTS automatic
  5 5 3 0 0 0
```

`automatic` = build a regular (Monkhorst-Pack) grid of k-points. The six
numbers are the mesh divisions along the three reciprocal directions
(5x5x3) and the shift flags (0 0 0 = unshifted, Gamma-centered). What
k-points are: `../WORKFLOW_EXPLAINED.md` 3.4. The 5x5x3 final-SCF mesh is,
again, SrCu2SnS4's own k-point convergence result [calculated].

```text
CELL_PARAMETERS angstrom
  6.357343 0.000000 0.000000
  -3.178672 5.505619 0.000000
  0.000000 0.000000 15.613989
```

The three cell vectors, one per line, in Angstroms (because `ibrav = 0`).
The second vector at 120 degrees to the first is the signature of the
trigonal/hexagonal cell of relaxed SrCu2SnS4 (space group P3_121, No. 152
[calculated], `thermo_candidates/SrCu2SnS4/CLAUDE.md`). These are the
relaxed vectors [calculated]; the relaxation grew the cell volume from
543.884 to 546.507 A^3, +0.48% [calculated] (same source).

---

## 3. The three calculation types and how their inputs differ

The pipeline runs `pw.x` three times per material, changing `calculation`
and a handful of keywords each time. Physics reasoning:
`../WORKFLOW_EXPLAINED.md` 4.3 (relax), 4.4 (SCF), 4.5 (NSCF).

| Aspect | `vc-relax` (`qe/00_relax/SrCu2SnS4.relax.in`) | `scf` (`qe/01_scf/SrCu2SnS4.scf.in`) | `nscf` (`qe/02_nscf/SrCu2SnS4.nscf.in`) |
|---|---|---|---|
| Purpose | find the geometry PBE prefers | compute the converged density on that geometry | band energies on a dense k-mesh, density frozen |
| k-mesh (divisions) | 4x4x2 | 5x5x3 | 12x12x6 |
| Geometry in file | starting structure (from mp-16988 [database]) | relaxed [calculated] | relaxed [calculated] |
| `outdir` / `prefix` | `./tmp/relax` / `SrCu2SnS4_relax` | `./tmp/final` / `SrCu2SnS4` | `./tmp/final` / `SrCu2SnS4` (must match the SCF!) |
| `disk_io` | `'medium'` | `'medium'` | `'nowf'` |
| Extra keywords | see 3.3 | — | `nbnd`, `startingpot`, `diago_full_acc` |

All three share 90/720 Ry, `occupations = 'fixed'`, `conv_thr = 1d-08`,
`diagonalization = 'david'` (quoted from the three files above).

### 3.1 `scf` — the reference

Section 2 covered it. It ends with a converged electron density stored in
`./tmp/final/SrCu2SnS4.save/`.

### 3.2 `nscf` — same physics, frozen density, many more k-points

`thermo_candidates/SrCu2SnS4/qe/02_nscf/SrCu2SnS4.nscf.in` differs from the
SCF input in exactly these keywords:

- `calculation = 'nscf'` — non-self-consistent: do **not** iterate the
  density; take the SCF density as given and just solve for band energies
  at each requested k-point.
- `startingpot = 'file'` — "read the potential/density from file", i.e.
  from the `.save` directory the SCF left behind. This is why `outdir` and
  `prefix` must match the SCF run.
- `nbnd = 140` — compute 140 bands per k-point. The SCF only needs the
  occupied ones; transport interpolation (see `02_tools_boltztrap2.md`)
  also needs empty conduction bands. SrCu2SnS4 has 105 occupied bands
  [calculated], so 140 gives 35 empty ones as headroom.
- `diago_full_acc = .TRUE.` — converge *every* band, including the empty
  ones, to full accuracy. By default QE is sloppier on empty bands; here
  they are the product, not a by-product.
- `disk_io = 'nowf'` — do not write wavefunctions to disk. On a 12x12x6
  mesh with 140 bands they would be huge, and BoltzTraP2 only needs the
  eigenvalues (band energies), which land in the `.save` XML file.
- `K_POINTS automatic 12 12 6 0 0 0` — the dense mesh, 12x12x6.
- Gone: `restart_mode`, `mixing_beta`, `electron_maxstep` — there is no
  SCF loop to configure.

### 3.3 `vc-relax` — let the atoms and the cell move

`thermo_candidates/SrCu2SnS4/qe/00_relax/SrCu2SnS4.relax.in` adds
geometry-optimization machinery ("vc" = variable cell):

In `&CONTROL`:

- `calculation = 'vc-relax'`
- `nstep = 100` — at most 100 geometry steps.
- `etot_conv_thr = 1d-05` (Ry) — geometry is converged when the energy
  change per step is below this...
- `forc_conv_thr = 0.001` (Ry/bohr) — ...and every force is below this...
- (in `&CELL`) `press_conv_thr = 0.5` (kbar) — ...and the residual
  pressure on the cell is below this. All three must hold.
- `tprnfor = .TRUE.`, `tstress = .TRUE.` — print forces and the stress
  tensor each step (that is where the `P=` lines in section 5 come from).

In `&IONS` and `&CELL` (empty for SCF, now filled):

- `ion_dynamics = 'bfgs'` and `cell_dynamics = 'bfgs'` — BFGS is a
  standard quasi-Newton minimization algorithm: use the computed forces
  and stress to propose the next geometry, downhill in energy.
- `cell_dofree = 'all'` — all cell degrees of freedom may change (lengths
  and angles), constrained only by symmetry.

Its `CELL_PARAMETERS` block holds the *starting* cell (first vector
6.346583 A, third 15.591788 A — the pre-relaxation values), unlike the SCF
file which holds the relaxed cell. Its k-mesh is the cheaper 4x4x2
[calculated choice from SrCu2SnS4's k-point test]: each relaxation step
re-runs a full SCF, so the mesh is chosen one tier coarser than the final
SCF.

**Per-material contrast** (`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`,
`.../qe/convergence/kpoint_results.csv`): for Rb2Cu2SnS4 the same protocol
selected different numbers — relax mesh 2x4x4 (0.175 meV/atom vs the 5x9x9
reference), final SCF 3x5x5 (0.016 meV/atom), dense NSCF 8x14x14 with
`nbnd = 105` [all calculated]. Different crystal shape, different meshes.
Never copy these across materials.

---

## 4. Running QE: environment, mpirun, and the runner scripts

### 4.1 The environment script

Every session starts with:

```bash
source "$HOME/scientific-tools/env/thermo-bt2.sh"
```

Reading that script: it activates the `thermo-bt2` conda environment (the
Python side: BoltzTraP2 and analysis scripts) and exports the
pseudopotential paths (`SSSP_PBE_PRECISION`, `QE_PSEUDO_SSSP_PBE_PRECISION`).
It does not need to add QE to `PATH` — on this machine `pw.x` already
resolves to `~/scientific-tools/apps/qe/build-cmake/bin/pw.x` (checked with
`command -v pw.x`). The `results/dos_comparison.md` "Reproduce with" block
shows the same `source` line as step one.

### 4.2 MPI ranks vs k-point pools

`pw.x` is parallelized with **MPI** (Message Passing Interface): `mpirun
-np 8 pw.x ...` starts 8 copies ("ranks") of the program that share the
work. QE splits that work on two levels:

- **k-point pools** (`-nk N`): the k-points are divided among N pools.
  Different k-points are independent problems, so this scales very well.
- **plane-wave parallelization** (the default within a pool): ranks inside
  one pool share the heavy linear algebra of each single k-point.

With `mpirun -np 8 pw.x -nk 4`, you get 4 pools x 2 ranks each. The log
confirms the layout — from
`thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out`:

```text
     Parallel version (MPI), running on     8 processors
     K-points division:     npool     =       4
```

The trade-off: pools are fast but **each pool holds a full copy of the
density in memory**. A real sizing decision is recorded in
`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`: on the 18-core/24 GB machine the
k-point series was relaunched with `QE_NP=12 QE_NK=2` because a 4-rank
single-pool run used ~6.8 GB, so 4 pools would have exceeded 24 GB while 2
pools sit around 10-14 GB — and the 12-rank layout finished the 4x7x7 mesh
in 2088 s [calculated]. (Same log entry: QE's GPU acceleration is
CUDA/NVIDIA-only, so the Mac GPU is unused.)

### 4.3 A runner script, line by line

`thermo_candidates/SrCu2SnS4/qe/run_nscf.sh`, in full:

```bash
#!/usr/bin/env bash                  # run with bash
set -euo pipefail                    # stop on any error, undefined var, or broken pipe

np="${QE_NP:-8}"                     # MPI ranks: env var QE_NP, default 8
nk="${QE_NK:-4}"                     # k-point pools: env var QE_NK, default 4
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"          # one thread per rank:
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}" # stop the math libraries
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}" # from oversubscribing cores

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"    # absolute path of the qe/ folder
input="$here/02_nscf/SrCu2SnS4.nscf.in"                 # which input to run
output="$here/../logs/SrCu2SnS4.nscf.out"               # log goes to logs/, kept forever
scf_xml="$here/tmp/final/SrCu2SnS4.save/data-file-schema.xml"  # proof the SCF ran

if [ ! -f "$scf_xml" ]; then         # guard: NSCF is meaningless without
  printf 'Missing final SCF data: %s\n' "$scf_xml" >&2  # the SCF density on disk
  exit 1
fi
if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then  # idempotency: if this NSCF
  printf 'Skipping completed NSCF: %s\n' "$output"         # already finished, do not
  exit 0                                                   # burn hours redoing it
fi

printf 'Running dense NSCF with %s MPI ranks, %s k-point pools, %s thread ...\n' \
  "$np" "$nk" "$OMP_NUM_THREADS"
cd "$here"                           # relative outdir './tmp/final' resolves from qe/
mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"   # the actual run

if ! grep -q 'JOB DONE' "$output"; then                 # QE prints JOB DONE only on
  printf 'QE did not finish cleanly: %s\n' "$output" >&2 # clean exit; fail loudly
  exit 1                                                # if it is missing
fi
printf 'Finished dense NSCF: %s\n' "$output"
```

So a custom-size run is just:

```bash
QE_NP=12 QE_NK=2 "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrCu2SnS4/qe/run_nscf.sh"
```

(note the quotes — every path in this repo contains spaces).

`run_relax.sh` (same folder) is the same skeleton with three differences:
its default is `QE_NK=2` instead of 4 (fewer pools for the coarser 4x4x2
relaxation mesh), it runs `mkdir -p "$here/tmp/relax" "$here/../logs"`
because it is the first step and the folders may not exist yet, and it has
no `scf_xml` guard because a relaxation starts from scratch.

---

## 5. Reading a QE log

The log is the primary research record — every result in `results/` must
trace back to one. The markers below were pulled with `grep -n` from two
real logs. You can reproduce every excerpt, e.g.:

```bash
grep -n "number of electrons" "/Users/kaede/research/Waterloo Holger thermoelectric materials/thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out"
```

### 5.1 The header block (any run)

From `thermo_candidates/SrCu2SnS4/logs/SrCu2SnS4.nscf.out` (line numbers
from `grep -n`):

```text
2:      Program PWSCF v.7.5 starts on 30Jun2026 at  5:47:52
17:     Parallel version (MPI), running on     8 processors
41:     K-points division:     npool     =       4
63:     number of electrons       =       210.00
64:     number of Kohn-Sham states=          140
278:    number of k points=   100
```

- **`number of electrons = 210.00`** — the valence electrons the
  pseudopotentials provide. First sanity check of any run: with fixed
  occupations, 210 electrons fill 210/2 = 105 bands, matching the "105
  occupied bands" recorded in `thermo_candidates/SrCu2SnS4/CLAUDE.md`
  [calculated].
- **`number of Kohn-Sham states = 140`** — bands computed per k-point;
  equals the `nbnd = 140` we asked for. "Kohn-Sham states" is DFT jargon
  for the one-electron energy levels (bands).
- **`number of k points = 100`** — the 12x12x6 mesh nominally has 864
  points, but symmetry reduces the distinct ("irreducible") ones to 100.
  QE computes only those.

### 5.2 The end of a healthy NSCF

Same file:

```text
618:     End of band structure calculation
4720:    highest occupied, lowest unoccupied level (ev):     7.1887    7.5332
4775:    PWSCF        :      1h15m CPU      1h29m WALL
4781:  JOB DONE.
```

- **`highest occupied, lowest unoccupied level (ev)`** — the top of the
  filled bands (VBM, 7.1887 eV) and bottom of the empty bands (CBM, 7.5332
  eV) *among the sampled k-points*. Their difference, 0.3445 eV, is the
  sampled indirect PBE gap [calculated] — "sampled" because the true band
  extrema may sit between grid points, "PBE" because this functional
  systematically underestimates gaps, and remember: no SOC. This is the
  number reported in `results/dos_comparison.md`.
- **`PWSCF : 1h15m CPU 1h29m WALL`** — CPU time (summed compute) vs
  wall-clock time. A wall time far above CPU time means the machine was
  busy or asleep, not that the physics struggled (a real diagnosed case is
  in section 8).
- **`JOB DONE.`** — QE's clean-exit stamp. The run scripts grep for
  exactly this.

Two markers are *absent* from an NSCF log, by design: there is no
`!    total energy` line and no `convergence has been achieved`, because
those belong to an SCF loop and an NSCF has none. If you need those, look
in an `scf` or relaxation log — like the next one.

### 5.3 A relaxation log

From `thermo_candidates/SrZrS3/logs/SrZrS3.relax.out` (a finished
`vc-relax` of the second material):

```text
1045:  !    total energy              =    -969.03969634 Ry
1054:       convergence has been achieved in  16 iterations
1214:            total   stress  (Ry/bohr**3)                   (kbar)     P=        3.19
...
12367: !    total energy              =    -969.04024282 Ry
12536:           total   stress  (Ry/bohr**3)                   (kbar)     P=       -0.03
12601:      bfgs converged in  14 scf cycles and  13 bfgs steps
12602:      (criteria: energy <  1.0E-05 Ry, force <  1.0E-03 Ry/Bohr, cell <  5.0E-01 kbar)
12609: Begin final coordinates
13719: !    total energy              =    -969.04024663 Ry
14016:      PWSCF        :  22m21.23s CPU  35m46.97s WALL
14022:    JOB DONE.
```

- **`!    total energy`** — the `!` marks a *converged* SCF total energy
  (unconverged iterations print the energy without `!`). In a relaxation
  you get one per geometry step; the sequence should settle:
  -969.03969634 Ry at the first geometry down to -969.04024663 Ry at the
  final one [calculated].
- **`convergence has been achieved in 16 iterations`** — one line per SCF
  cycle; the electron density converged in 16 mixing iterations. This log
  contains 15 such lines (`grep -c`): 14 SCF cycles during BFGS plus one
  final fresh SCF at the relaxed geometry.
- **`P= 3.19` -> `P= -0.03`** — the pressure (kbar) from the stress
  tensor, printed each step because `tstress = .TRUE.`. It starts at 3.19
  kbar on the database geometry and ends at -0.03 kbar, comfortably inside
  the 0.5 kbar threshold [calculated].
- **`bfgs converged in 14 scf cycles and 13 bfgs steps`** + the
  `(criteria: ...)` line — the success stamp, restating exactly the three
  thresholds from the input (`etot_conv_thr`, `forc_conv_thr`,
  `press_conv_thr`; compare section 3.3).
- **`Begin final coordinates`** — after this line QE prints the relaxed
  cell and positions; that block is what
  `extract_relaxed_structure.py`-style scripts parse (see
  `03_code_walkthrough.md`).

---

## 6. dos.x: from a finished run to a density-of-states table

**DOS** (density of states) = how many electronic states exist per unit of
energy; concept in `../WORKFLOW_EXPLAINED.md` 3.7, and the QE-vs-BoltzTraP2
comparison that motivated this run in its section 5.1.

### 6.1 The input, line by line

`thermo_candidates/SrCu2SnS4/qe/dos/SrCu2SnS4.dos.in`, complete:

```fortran
&DOS
  prefix = 'SrCu2SnS4'      ! same prefix as the SCF/NSCF ...
  outdir = './tmp/final'    ! ... and same outdir: that is how dos.x finds the run
  fildos = './dos/SrCu2SnS4.dos'  ! where to write the DOS table
  ngauss = 0                ! broadening shape: 0 = plain Gaussian
  degauss = 0.005           ! broadening width in Ry (= 0.068 eV, per results/dos_comparison.md)
  Emin = -30.0              ! energy window bottom, eV
  Emax = 15.0               ! energy window top, eV
  DeltaE = 0.02             ! energy step of the table, eV
/
```

`dos.x` does no new physics: it reads the eigenvalues the NSCF stored in
`./tmp/final/SrCu2SnS4.save/` (its log
`qe/dos/SrCu2SnS4.dos.out` says `Reading xml data from directory:
./tmp/final/SrCu2SnS4.save/`), replaces each discrete level by a small
Gaussian bump of width `degauss`, and sums. It ran on 1 processor in
seconds: `DOS : 5.35s CPU 5.79s WALL`.

### 6.2 The output columns

`thermo_candidates/SrCu2SnS4/qe/dos/SrCu2SnS4.dos` — header plus the first
data line:

```text
#  E (eV)   dos(E)     Int dos(E) EFermi =    7.189 eV
 -30.000  0.3214E-83  0.6427E-85
```

| Column | Unit | Meaning |
|---|---|---|
| `E` | eV | energy (absolute QE scale, *not* shifted to E_F = 0) |
| `dos(E)` | states/eV (per cell) | the DOS itself |
| `Int dos(E)` | electrons | running integral of the DOS from `Emin` up to `E` |

The header also stamps `EFermi = 7.189 eV` — the same 7.1887 eV VBM from
the NSCF log, rounded. The file has 2252 lines: 1 header + 2251 energy
points ((15 - (-30))/0.02 + 1).

### 6.3 The 210-electron integral check

The third column is the built-in sanity check. Just below the Fermi level
(line 1861 of the `.dos` file):

```text
    7.180  0.7140E+00  0.2100E+03
```

`Int dos = 0.2100E+03` = **210.0 electrons** integrated up to 7.180 eV —
exactly the `number of electrons = 210.00` from the NSCF log, i.e. all 105
occupied bands x 2 [calculated]. If broadening, the energy window, or the
run directory were wrong, this integral would miss the electron count.
`results/dos_comparison.md` records the same check, and also why the
BoltzTraP2 DOS integrates to only 124.0 there: its loader keeps 62 occupied
bands and drops the deep semicore states — a bookkeeping difference, not a
physics disagreement (details in `02_tools_boltztrap2.md`).

---

## 7. Units in QE, and the files a run leaves behind

### 7.1 Units

QE mixes units, and the logs/columns always say which — keep the habit of
reading the unit off the line itself:

| Quantity | QE unit | Where you saw it | Conversion |
|---|---|---|---|
| total energy, `conv_thr`, `etot_conv_thr` | Ry (Rydberg) | `!    total energy = -969.04024663 Ry` | 1 Ry = 13.6057 eV (`../WORKFLOW_EXPLAINED.md` glossary), so 90 Ry cutoff = about 1224.5 eV |
| band energies, gap, DOS grid | eV | `highest occupied, lowest unoccupied level (ev)` | — |
| forces, `forc_conv_thr` | Ry/bohr | `(criteria: ... force < 1.0E-03 Ry/Bohr ...)` | bohr = atomic length unit, see next row |
| lengths (internal) | bohr = a.u. | `lattice parameter (alat) = 12.0136 a.u.` (NSCF log line 59) | that same length is the first cell vector, 6.357343 A in `SrCu2SnS4.scf.in` — ratio 0.529 A/bohr |
| volume | (a.u.)^3 | `unit-cell volume = 3688.0115 (a.u.)^3` (NSCF log line 60) | x (0.529178)^3 -> 546.51 A^3, matching the relaxed volume 546.507 A^3 in `thermo_candidates/SrCu2SnS4/CLAUDE.md` [calculated] |
| stress/pressure, `press_conv_thr` | kbar (QE prints Ry/bohr^3 and kbar side by side) | `total stress (Ry/bohr**3) (kbar) P= -0.03` | 10 kbar = 1 GPa |

Note the pattern in the table: our *inputs* to QE use Angstrom
(`CELL_PARAMETERS angstrom`) and Ry (cutoffs, thresholds); QE's *internal
reports* use bohr and Ry; the *human-facing* band numbers come out in eV.
More unit-handling practice: `06_data_handling.md`.

### 7.2 What a run leaves behind

After the SCF + NSCF, the scratch directory
`thermo_candidates/SrCu2SnS4/qe/tmp/final/SrCu2SnS4.save/` contains (from
`ls`):

| File | What it is |
|---|---|
| `charge-density.dat` | the converged electron density — the SCF's real product, what the NSCF reads via `startingpot = 'file'` |
| `data-file-schema.xml` | the run's structured record: cell, symmetry, k-points, eigenvalues. This is what `dos.x` and BoltzTraP2 read, and what `run_nscf.sh` checks for before starting |
| `Cu.paw.z_11...upf`, `s_pbe_v1.4...UPF`, `Sn_pbe_v1...UPF`, `Sr_pbe_v1...UPF` | verbatim copies of the four pseudopotentials used — self-documenting provenance |
| `paw.txt` | bookkeeping for the PAW (Cu) pseudopotential |

No wavefunction files are kept — the last run to touch this directory was
the NSCF with `disk_io = 'nowf'`. That is deliberate: wavefunctions are
huge, and the reproducibility notes for the Roy package state they were
left out of the email for exactly that reason.

The permanent, human-readable record lives in `logs/`:
`SrCu2SnS4.relax.out`, `SrCu2SnS4.scf.out`, `SrCu2SnS4.nscf.out` plus the
three BoltzTraP2 logs. House rule: raw logs and `.save` data are research
records — never edit, never delete; derived tables go in `results/`.

### 7.3 Status of the third material

For Rb2Cu2SnS4 the first pass is now complete, and every step is quotable:
cutoff and k-point CSVs (`qe/convergence/`), relaxation (Ibam symmetry
kept, volume +0.93% [calculated]), final SCF (156.00 electrons, 78 occupied
bands, highest occupied level 6.2203 eV [calculated]) — all in its
`WORKLOG.md` and `logs/`. Its **dense NSCF (8x14x14, nbnd = 105) finished**
with `JOB DONE` (`thermo_candidates/Rb2Cu2SnS4/logs/Rb2Cu2SnS4.nscf.out`):
788 irreducible k-points, 156.00 electrons, VBM 6.2402 eV and CBM 7.0213 eV
among the sampled points for a sampled PBE gap of 0.7811 eV, in 5h27m WALL
[all calculated] — remember the same caveats as SrCu2SnS4 (sampled, PBE
underestimates, no SOC). BoltzTraP2 then ran on that NSCF; the transport
tables (`results/transport_full.csv`,
`results/transport_best_power_factor.csv`,
`results/workflow_summary.md`) hold `PF/tau` and electronic-only `zT_e`
values, which are not an absolute power factor or the final zT (see
`02_tools_boltztrap2.md`).

---

## 8. Failure checklist: when something looks wrong

Work through these in order; each is grounded in a real check or a real
incident from this repo.

1. **`JOB DONE.` missing from the log.** First decide: crashed, or still
   running? `tail` the log. A healthy in-flight run shows steady progress
   lines — a dense NSCF, mid-run, ends on an in-flight
   `Computing kpt #: N of 394 on this pool` progress line (that 394 is the
   per-pool k-point count for Rb2Cu2SnS4's 8x14x14 mesh split across 2
   pools; it has since finished with `JOB DONE`). A crashed run ends
   abruptly or with an error block. The runner scripts automate the check
   (`grep -q 'JOB DONE'`) and refuse to report success without it; they
   also *skip* a job whose log already has `JOB DONE`, so delete or move
   the stale log if you genuinely want a rerun.

2. **SCF does not converge.** A healthy cycle prints
   `convergence has been achieved in N iterations` (16 on SrZrS3's first
   geometry); a failing one hits `electron_maxstep` (200 here) and prints
   `convergence NOT achieved`. The knobs already present in these inputs
   are the ones to reach for: a smaller `mixing_beta` (0.3 here — smaller
   is more stable, slower), a larger `electron_maxstep`, and only then
   question the structure or pseudopotential choice. Also confirm
   `occupations = 'fixed'` is even legitimate: it presumes a gapped
   system.

3. **Wrong electron count.** Check `number of electrons` against the
   pseudopotential valence arithmetic *before* trusting anything else.
   Real examples: SrCu2SnS4 210.00 electrons -> 105 occupied bands;
   Rb2Cu2SnS4 156.00 electrons = 4x9 (Rb) + 4x11 (Cu) + 2x14 (Sn) + 8x6
   (S) -> 78 occupied bands (`WORKLOG.md`). A mismatch means a wrong or
   swapped `.UPF` file in `ATOMIC_SPECIES` — every downstream number
   (gap, DOS integral, doping levels) would be wrong.

4. **BFGS oscillates or will not converge.** Watch the two series from
   section 5.3: `!    total energy` should settle (SrZrS3:
   -969.03969634 -> -969.04024663 Ry over 13 steps) and `P=` should head
   toward zero (3.19 -> -0.03 kbar). If energy bounces up and down at the
   1e-5 Ry scale, the geometry step is fighting SCF noise — the SCF
   `conv_thr` must stay much tighter than `etot_conv_thr` (here 1e-8 vs
   1e-5 Ry, a factor of 1000). Also confirm the run did not just hit
   `nstep = 100` without meeting the criteria — success is only the
   explicit `bfgs converged` + `(criteria: ...)` stamp.

5. **Run is mysteriously slow.** Compare CPU and WALL in the `PWSCF :`
   closing line. Real incident (`Rb2Cu2SnS4/WORKLOG.md`): a cutoff run
   showed 1h56m wall but only 8m27s CPU with a perfectly uniform 17-18
   SCF iterations — the laptop had been suspended/throttled; the physics
   was fine. Fix the machine (that log entry's answer: `caffeinate -i`
   and sane `QE_NP`/`QE_NK`), not the input.

6. **Numbers exist but look odd.** Re-read the guardrails before
   panicking: the gap is the *sampled* PBE gap on that material's grid
   (PBE underestimates; no SOC anywhere in this workspace); the meshes
   and cutoffs are only proven for the material whose convergence test
   produced them; and if a number cannot be traced to a line in a log or
   a derived table, it does not exist — say so rather than inventing one.
   "Not yet computed" is a complete answer.

---

*Next in the curriculum:* `02_tools_boltztrap2.md` — what happens to
`data-file-schema.xml` after QE is done.

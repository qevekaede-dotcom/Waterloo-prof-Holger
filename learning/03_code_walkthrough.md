# Code walkthrough: every script in this repo

This is document 3 of the learning curriculum (map: `learning/README.md`).
It walks through every script in the workspace: what each one is for, what
goes in and what comes out, and a guided read of the lines that actually
matter. The concepts behind the scripts (what DFT is, what a k-point mesh
is, why we converge cutoffs) live in `../WORKFLOW_EXPLAINED.md` — its
section 2 explains what "a calculation" is, section 3 defines every
parameter, and section 4 traces the full SrCu2SnS4 workflow. Read those
first if any term below is new. For running the tools themselves, see
`01_tools_quantum_espresso.md` (input anatomy in its section 2, a runner
line-by-line in its section 4.3) and `02_tools_boltztrap2.md`; for the data
the scripts produce, see `06_data_handling.md`.

All paths below are relative to the repository root, and all quoted code is
copied verbatim from the files cited. Two standing caveats apply to every
number in this document: all runs are scalar-relativistic PBE with **no
explicit spin-orbit coupling (SOC)**, and every "best" value is the best
point **on the sampled grid**, not a continuous optimum.

Quick jargon for this page:

- **QE** = Quantum ESPRESSO, the density-functional-theory (DFT) code; its
  main program is `pw.x`.
- **SCF** = self-consistent field, the basic DFT calculation that finds the
  electron density; **NSCF** = non-self-consistent, which reuses that
  density to compute band energies on a denser k mesh
  (`../WORKFLOW_EXPLAINED.md` section 3.5).
- **Cutoff** = the plane-wave energy limit (`ecutwfc`, in Rydberg, Ry) that
  controls basis-set quality; `ecutrho` is the companion charge-density
  cutoff (section 3.2 there).
- **k mesh** = the grid of sampling points in reciprocal space, written
  like `12x12x6` (section 3.4 there).
- **CIF** = crystallographic information file, a standard text format for
  crystal structures.
- **pymatgen / ASE** = Python libraries for manipulating structures and
  reading/writing DFT files.
- **tau** = the electronic relaxation time, the unknown scattering
  timescale that BoltzTraP2 cannot compute; it is why transport results are
  reported "per tau" (`02_tools_boltztrap2.md` section 7).

The scripts fall into four roles, and the same four roles repeat for every
material:

| Role | Where | What it does |
|---|---|---|
| Shared generators | `thermo_candidates/scripts/` | download structures, write starter QE inputs, sanity-check the environment |
| Convergence testing | `<material>/qe/convergence/` | choose the cutoff and k mesh **for that material** |
| Production steps | `<material>/qe/` | relax the cell, final SCF, dense NSCF |
| Transport + analysis | `<material>/boltztrap2/` | BoltzTraP2 stages and derived tables/plots |

---

## 1. Shared generators (`thermo_candidates/scripts/`)

These three scripts are deliberately material-agnostic: they hold the
per-material *starting points*, never the converged values.

### 1.1 `make_qe_inputs.py` — starter QE inputs from a CIF

**Purpose:** given a candidate folder and a CIF, write three template QE
inputs: `qe/00_relax/*.relax.in`, `qe/01_scf/*.scf.in`,
`qe/02_nscf/*.nscf.in`.

**Inputs -> outputs:** a CIF file -> three `pw.x` input files under
`<material>/qe/`.

The heart of the script is the `MATERIALS` dictionary
(`thermo_candidates/scripts/make_qe_inputs.py`), which records, per
material, the pseudopotential filenames and the SSSP-suggested cutoffs:

```python
MATERIALS = {
    "SrCu2SnS4": {
        "prefix": "SrCu2SnS4",
        "pseudo": {
            "Sr": "Sr_pbe_v1.uspp.F.UPF",
            "Cu": "Cu.paw.z_11.ld1.psl.v1.0.0-low.upf",
            "Sn": "Sn_pbe_v1.uspp.F.UPF",
            "S": "s_pbe_v1.4.uspp.F.UPF",
        },
        "ecutwfc": 90,
        "ecutrho": 720,
    },
    ...
```

A **pseudopotential** is a file that replaces the chemically inert core
electrons of an atom with an effective potential, so QE only has to solve
for the valence electrons. The filenames here come from the SSSP 1.3.0 PBE
"precision" library, so the cutoffs in this dict are **database-listed
starting suggestions [database]**, not converged values. The SrZrS3 entry
is the clearest proof: the dict lists `40/320 Ry` [database], but SrZrS3's
own cutoff test later selected `50/400 Ry` [calculated]
(`thermo_candidates/SrZrS3/qe/convergence/prepare_kpoint_inputs.py`,
docstring: "Runs at the cutoff selected by the cutoff test (50/400 Ry ...)").
This is the house rule in action: **convergence parameters are chosen per
material and never reused across materials.**

The actual file writing goes through pymatgen's `PWInput` class, which
takes a `Structure` plus dictionaries for each QE input namelist
(`control`, `system`, `electrons`, ...):

```python
    pw = PWInput(
        structure,
        pseudo=pseudo,
        control=control,
        system=system,
        electrons=electrons,
        ions=ions,
        cell=cell,
        kpoints_mode="automatic",
        kpoints_grid=kpoints_grid,
        kpoints_shift=(0, 0, 0),
    )
    pw.write_file(path)
```

The starter meshes hard-coded in `main()` (`4x4x4` relax, `6x6x6` SCF,
`12x12x12` NSCF) are placeholders — the script itself prints:

```python
    print("Review k-point meshes, nbnd, magnetism, SOC, and convergence before running.")
```

**Why `nbnd` is left as a TODO.** `nbnd` is the number of electronic bands
QE computes. For the NSCF step it must be set to "all occupied bands plus
generous empty headroom", but the number of occupied bands is only known
*after* the SCF run reports the electron count. So the generator writes a
sentinel:

```python
    elif calculation == "nscf":
        ...
        system["nbnd"] = "TODO_SET_AFTER_SCF"
```

and then patches the file, because `PWInput` would otherwise quote the
string and produce `nbnd = 'TODO_SET_AFTER_SCF'`, which looks like a valid
(but nonsense) Fortran value:

```python
    text = text.replace("'TODO_SET_AFTER_SCF'", "TODO_SET_AFTER_SCF")
```

Left unquoted, `pw.x` fails loudly if someone forgets to replace it — a
small trick that turns a silent mistake into a crash.

### 1.2 `download_mp_structures.py` — fetch the three structures

**Purpose:** download the selected Materials Project structures through the
OPTIMADE API and write CIFs into each `structures/` folder.

**Inputs -> outputs:** network access -> `<material>/structures/<formula>.cif`.

The material list is another small dict
(`thermo_candidates/scripts/download_mp_structures.py`):

```python
MATERIALS = {
    "SrCu2SnS4": "mp-16988",
    "SrZrS3": "mp-558760",
    "Rb2Cu2SnS4": "mp-18006",
}
```

These `mp-*` identifiers are **database entries [database]**. Two details
worth copying: the script verifies the downloaded composition
(`if structure.composition.reduced_formula != formula: raise ValueError`),
so a wrong ID cannot silently write the wrong compound; and it writes CIFs
with `CifWriter(structure, symprec=0.01, refine_struct=False)` — a symmetry
tolerance of 0.01 Angstrom for detecting the space group, without altering
the atomic coordinates.

### 1.3 `check_workspace.sh` — environment sanity check

**Purpose:** print where the required tools live and whether every
pseudopotential file and candidate folder exists. Run it before any long
job.

**Inputs -> outputs:** environment -> a human-readable report on stdout.

It loops over the tools (`python pw.x mpirun btp2`), checks the
`QE_PSEUDO_SSSP_PBE_PRECISION` environment variable, and tests each of the
six pseudopotential filenames used across the three materials
(`thermo_candidates/scripts/check_workspace.sh`):

```bash
    if [ -f "$QE_PSEUDO_SSSP_PBE_PRECISION/$pp" ]; then
      printf 'found   %s\n' "$pp"
    else
      printf 'missing %s\n' "$pp"
    fi
```

Note it uses `set -u` (fail on undefined variables) but not `set -e`,
because a missing tool should be *reported*, not abort the report.

---

## 2. The convergence-testing set (SrZrS3 versions as the cleanest example)

Every material gets four small scripts in `qe/convergence/`: two Python
"prepare" scripts that write batches of SCF inputs, one bash runner, and
one Python "extract" script that parses the outputs into a CSV. The SrZrS3
copies are the cleanest, so we read those. Rb2Cu2SnS4 has identical copies
with its own constants; SrCu2SnS4, the oldest workspace, does the same job
with its extractors under the older names `summarize_cutoff.py` /
`summarize_kpoints.py` (cutoff list 50-100 Ry on a fixed 2x2x2 mesh, k
meshes 2x2x1 to 5x5x3 at 90/720 Ry —
`thermo_candidates/SrCu2SnS4/qe/convergence/prepare_cutoff_inputs.py` and
`prepare_kpoint_inputs.py`). The concepts are
`../WORKFLOW_EXPLAINED.md` sections 4.1 and 4.2.

### 2.1 `SrZrS3/qe/convergence/prepare_cutoff_inputs.py`

**Purpose:** write one SCF input per trial cutoff, all with the same fixed
structure and the same fixed k mesh, so the *only* thing that varies is the
basis-set quality.

**Inputs -> outputs:** `structures/SrZrS3.cif` -> `cutoff/inputs/ecut_<N>.in`
for each cutoff.

The design constants sit at the top
(`thermo_candidates/SrZrS3/qe/convergence/prepare_cutoff_inputs.py`):

```python
CUTOFFS_RY = (30, 35, 40, 45, 50, 60)
KMESH = (4, 2, 1)
```

Three deliberate choices, all explained in the file's own docstring:

- the cutoff list brackets the SSSP suggestion of 40/320 Ry [database]
  with headroom above, and the highest run (60 Ry) becomes the reference;
- the k mesh is fixed and deliberately coarse (`4x2x1`), because the
  k-sampling error largely *cancels* when you take energy differences
  between cutoffs;
- `"ecutrho": cutoff * 8` — the charge-density cutoff is held at 8x the
  wavefunction cutoff ("dual 8") because all three SrZrS3 pseudopotentials
  are ultrasoft, and ultrasoft/PAW pseudos need a dual of ~8 (pure
  norm-conserving sets can use 4).

Each input also sets `"tstress": True` so QE prints the pressure — the
second convergence indicator besides the energy.

### 2.2 `SrZrS3/qe/convergence/run_cutoff_convergence.sh`

**Purpose:** run every prepared input through `pw.x`, skipping anything
already finished.

**Inputs -> outputs:** `cutoff/inputs/*.in` -> `cutoff/outputs/*.out`
(raw QE logs).

This 31-line script is the template for every runner in the repo, so read
it slowly (`thermo_candidates/SrZrS3/qe/convergence/run_cutoff_convergence.sh`):

```bash
set -euo pipefail

np="${QE_NP:-4}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
```

- `set -euo pipefail` is bash's fail-fast mode: `-e` aborts on any command
  error, `-u` on any undefined variable, and `pipefail` makes a pipeline
  fail if *any* stage fails. A half-finished convergence series should
  stop, not limp on.
- `np="${QE_NP:-4}"` is an **environment knob**: the number of MPI ranks
  (parallel processes) defaults to 4 but can be overridden per run as
  `QE_NP=12 ./run_cutoff_convergence.sh` without editing the script.
- The `OMP_NUM_THREADS=1` exports pin each MPI rank to a single thread so
  the linear-algebra libraries don't oversubscribe the CPU.

Then the idempotent loop — "idempotent" means running the script twice is
safe, because completed work is detected and skipped:

```bash
  if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
    printf 'Skipping completed %s\n' "$name"
    continue
  fi
```

`JOB DONE` is the literal string `pw.x` prints at the end of a clean run,
so its presence in the log is the completion marker. After each run the
same string is checked again as a health test:

```bash
  mpirun -np "$np" pw.x -in "$input" > "$output"
  if ! grep -q 'JOB DONE' "$output"; then
    printf 'QE did not finish cleanly: %s\n' "$output" >&2
    exit 1
  fi
```

This mattered in practice: the Rb2Cu2SnS4 k-point series was killed and
relaunched with more ranks, and "Completed meshes were skipped by the run
script" (`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`) — the skip guard is
what made that restart free. The k-point runner
(`run_kpoint_convergence.sh`) is the same file with `cutoff` -> `kpoints`
and `ecut_*` -> `k_*`.

### 2.3 `SrZrS3/qe/convergence/extract_cutoff_results.py`

**Purpose:** parse every finished output into one machine-readable CSV.

**Inputs -> outputs:** `cutoff/outputs/ecut_*.out` -> `cutoff_results.csv`.

Parsing is done with regular expressions (regex): text patterns matched
against the raw QE log
(`thermo_candidates/SrZrS3/qe/convergence/extract_cutoff_results.py`):

```python
RY_TO_MEV = 13605.693122994
...
    energy = float(re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)[-1])
    pressures = re.findall(r"P=\s*([-\d.]+)", text)
```

Line by line:

- QE prefixes the total energy of a **converged** SCF cycle with `!` — the
  regex keys on that so intermediate unconverged energies are ignored, and
  `[-1]` takes the last match in case the log contains several.
- The pressure is scraped from QE's `P=` line (in kbar); `nan` if absent.
- `RY_TO_MEV` converts Rydberg to millielectronvolt, 1 Ry =
  13605.693122994 meV [database, CODATA-derived constant].

The convergence measure is the energy difference to the best available run:

```python
    e_ref = rows[-1][1]  # highest cutoff = reference
    ...
            delta = abs(energy - e_ref) * RY_TO_MEV / NAT
```

with `NAT = 20` (atoms in the SrZrS3 cell) so the delta is **meV/atom vs
the maximum-cutoff reference** — comparable across materials with different
cell sizes. The CSV column contract is fixed and shared by all materials:

```
ecutwfc_Ry,ecutrho_Ry,total_energy_Ry,delta_meV_per_atom_vs_max,pressure_kbar
```

And the real output for SrZrS3, complete
(`thermo_candidates/SrZrS3/qe/convergence/cutoff_results.csv`, all values
[calculated]):

| ecutwfc (Ry) | ecutrho (Ry) | delta vs 60 Ry (meV/atom) | pressure (kbar) |
|---:|---:|---:|---:|
| 30 | 240 | 2.374 | 2.92 |
| 35 | 280 | 1.138 | 3.35 |
| 40 | 320 | 0.539 | 3.42 |
| 45 | 360 | 0.262 | 3.51 |
| 50 | 400 | 0.160 | 3.55 |
| 60 | 480 | 0.000 (reference) | 3.50 |

Reading it the way the workflow did: at 50/400 Ry the energy is within
0.160 meV/atom of the reference and the pressure has flattened onto the
3.4-3.55 kbar plateau, so 50/400 Ry was selected — for SrZrS3 only.

### 2.4 The k-point pair: `prepare_kpoint_inputs.py` and `extract_kpoint_results.py`

Same pattern, second knob. `prepare_kpoint_inputs.py` fixes the cutoff at
the value the cutoff test chose and varies only the mesh
(`thermo_candidates/SrZrS3/qe/convergence/prepare_kpoint_inputs.py`):

```python
ECUTWFC = 50
ECUTRHO = 400
MESHES = ((4, 2, 1), (6, 3, 2), (8, 4, 2), (10, 5, 3))
```

The meshes are not arbitrary: the docstring shows they are scaled to the
Pnma cell's reciprocal-axis ratios so the k-spacing stays roughly equal in
all three directions (e.g. `6x3x2` gives ~0.27/0.24/0.22 A^-1). A cubic
`6x6x6` mesh would waste points along the long axes of an elongated cell.

`extract_kpoint_results.py` adds one new parsing job — the **irreducible
k-point count**. Crystal symmetry makes many k-points equivalent, and QE
only computes one representative per equivalence class (that is what
"irreducible" means); the count is what actually determines cost:

```python
    irr = int(re.search(r"number of k points=\s*(\d+)", text).group(1))
    mesh = re.search(r"k_(\d+)x(\d+)x(\d+)", path.stem).groups()
```

The mesh itself is recovered from the *filename*, and the full point count
is just the product — so the CSV can report all three:

```
mesh,full_kpoints,irreducible_kpoints,total_energy_Ry,delta_meV_per_atom_vs_max
```

Real SrZrS3 numbers
(`thermo_candidates/SrZrS3/qe/convergence/kpoint_results.csv`, [calculated]):

| mesh | full k-points (count) | irreducible k-points (count) | delta vs 10x5x3 (meV/atom) |
|---|---:|---:|---:|
| 4x2x1 | 8 | 6 | 2.885 |
| 6x3x2 | 36 | 16 | 0.286 |
| 8x4x2 | 64 | 30 | 0.036 |
| 10x5x3 | 150 | 36 | 0.000 (reference) |

Note how symmetry compresses 150 points to 36. The Rb2Cu2SnS4 copies of
these four scripts follow the identical pattern with their own constants
(`NAT = 18`; cutoffs 50-100 Ry against a 100 Ry reference on a fixed 2x4x4
mesh; k meshes 2x4x4 to 5x9x9 at 90/720 Ry). Their results exist:
90/720 Ry sits 0.0896 meV/atom from the 100 Ry reference
(`thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv`
[calculated]) and the 3x5x5 mesh 0.016 meV/atom from the 5x9x9 reference
(`.../kpoint_results.csv` [calculated]).

---

## 3. Production steps for one material (SrCu2SnS4 files)

After convergence testing, each material runs three production stages
(`../WORKFLOW_EXPLAINED.md` sections 4.3-4.5): variable-cell relaxation
(find the PBE equilibrium geometry), final SCF (the converged density on
the relaxed cell), and dense NSCF (band energies on a fine mesh for
transport). Each stage is one "prepare" Python script plus one bash
runner. SrCu2SnS4's copies are the completed originals.

### 3.1 `SrCu2SnS4/qe/prepare_relax.py`

**Inputs -> outputs:** `structures/SrCu2SnS4.cif` ->
`qe/00_relax/SrCu2SnS4.relax.in`.

This writes a `vc-relax` (variable-cell relaxation) input at the
material's own converged parameters — `ecutwfc 90 / ecutrho 720 Ry`,
`4x4x2` mesh (`thermo_candidates/SrCu2SnS4/qe/prepare_relax.py`). The lines
worth understanding are the stopping thresholds and the cell freedom:

```python
            "etot_conv_thr": 1e-5,
            "forc_conv_thr": 1e-3,
            ...
        cell={
            "cell_dynamics": "bfgs",
            "press_conv_thr": 0.5,
            "cell_dofree": "all",
        },
```

- The relaxation stops when between-step energy changes fall below
  1e-5 Ry, forces below 1e-3 Ry/bohr, and the residual pressure below
  0.5 kbar — three independent "we are at the minimum" tests.
- **BFGS** is the quasi-Newton optimizer QE uses to move atoms and cell.
- `cell_dofree = "all"` lets *all* cell degrees of freedom relax (lengths
  and angles). The symmetry is not constrained by the input — which is
  exactly why the extraction script below asserts afterwards that the
  space group survived.

### 3.2 `SrCu2SnS4/qe/extract_relaxed_structure.py`

**Inputs -> outputs:** `logs/SrCu2SnS4.relax.out` (raw QE log) ->
`structures/SrCu2SnS4.relaxed.cif`.

Only ~30 lines, but three libraries cooperate
(`thermo_candidates/SrCu2SnS4/qe/extract_relaxed_structure.py`):

```python
    frames = read(OUTPUT, index=":", format="espresso-out")
    ...
    structure = AseAtomsAdaptor.get_structure(frames[-1])
    if structure.composition.reduced_formula != "SrCu2SnS4":
        raise ValueError(f"Unexpected formula: {structure.composition.reduced_formula}")
    CifWriter(structure, symprec=0.01, refine_struct=False).write_file(
        RELAXED_CIF
    )
```

- ASE's `read(..., index=":", format="espresso-out")` parses the QE
  relaxation log as a *trajectory*: one frame per BFGS step. `frames[-1]`
  is the final, converged geometry.
- The **formula assertion guard** is cheap insurance: if the parser
  misreads the log (wrong species order, truncated file), the composition
  changes and the script crashes instead of writing a wrong CIF that would
  poison every downstream step.
- `symprec=0.01` re-detects the space group with a 0.01 Angstrom tolerance,
  and `refine_struct=False` keeps the raw relaxed coordinates — the CIF
  *records* the symmetry, it does not snap atoms onto it.

### 3.3 `prepare_final_scf.py` and `prepare_nscf.py`

`prepare_final_scf.py` is `prepare_relax.py` minus the relaxation blocks:
it reads the **relaxed** CIF (`structures/SrCu2SnS4.relaxed.cif`), writes a
plain `scf` input at 90/720 Ry on a `5x5x3` mesh (one tier denser than the
relax mesh), and directs the output density into `./tmp/final`
(`thermo_candidates/SrCu2SnS4/qe/prepare_final_scf.py`).

`prepare_nscf.py` is where the transport requirements show up
(`thermo_candidates/SrCu2SnS4/qe/prepare_nscf.py`):

```python
        system={
            "ecutwfc": 90,
            "ecutrho": 720,
            "occupations": "fixed",
            "nbnd": 140,
        },
        electrons={
            "conv_thr": 1e-8,
            "diagonalization": "david",
            "diago_full_acc": True,
            "startingpot": "file",
        },
        kpoints_mode="automatic",
        kpoints_grid=(12, 12, 6),
```

- **`nbnd` sizing:** here the TODO from the generator is finally resolved.
  The final SCF showed 105 occupied bands for this cell, so `nbnd = 140`
  gives 35 empty bands of headroom (140 total, 105 occupied — recorded in
  the summary written by `summarize_transport.py`, section 4.2 below).
  BoltzTraP2 needs empty bands well above the gap because doped, hot
  carriers sample them. The same sizing logic for Rb2Cu2SnS4 chose
  `nbnd = 105` for 78 occupied bands, "~35% headroom, same ratio as the
  other two materials" (`thermo_candidates/Rb2Cu2SnS4/qe/prepare_nscf.py`
  docstring) — the number is per-material arithmetic, never copied.
- `startingpot = "file"` makes the NSCF *reuse* the SCF density from
  `outdir` instead of recomputing it — that is what "non-self-consistent"
  means operationally.
- `diago_full_acc = True` forces full accuracy for the empty bands, which
  a ground-state-only run would otherwise treat sloppily.
- `12x12x6` is the dense transport mesh — dense because transport
  integrals sample fine features of the bands, and 12x12x6 keeps roughly
  even k-spacing on this trigonal cell (compare the shapes: SrZrS3 used
  20x10x6, Rb2Cu2SnS4 8x14x14 — each matched to its own cell).

### 3.4 The runners: `run_relax.sh`, `run_final_scf.sh`, `run_nscf.sh`

All three follow the convergence-runner pattern from section 2.2, with two
additions (`thermo_candidates/SrCu2SnS4/qe/run_relax.sh`):

```bash
np="${QE_NP:-8}"
nk="${QE_NK:-2}"
...
mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"
```

- **`QE_NK` — k-point pools.** `pw.x -nk 2` splits the MPI ranks into 2
  groups ("pools") that each handle a subset of k-points, which
  parallelizes better than plane-wave distribution alone but replicates
  memory per pool. The NSCF runner defaults to `QE_NK=4` (many k-points to
  spread), relax and SCF to 2. The Rb2Cu2SnS4 worklog documents the
  real-world trade-off: pools were capped at 2 on a 24 GB machine because
  "pools replicate memory" (`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`).
- **Tee-free redirect.** The QE output goes `> "$output"` straight to the
  log file, with nothing on the terminal. QE logs are huge and the raw log
  *is* the research record (kept under `logs/`); progress is checked with
  `tail -f` on the file. Contrast section 4.1, where the BoltzTraP2 runner
  does use `tee` because its output is short and useful live.
- **Health check.** Same as before — after the run, `grep -q 'JOB DONE'`
  or `exit 1`. `run_nscf.sh` adds a *precondition* check too: it refuses to
  start unless the final-SCF result file
  `tmp/final/SrCu2SnS4.save/data-file-schema.xml` exists, since NSCF is
  meaningless without the SCF density.

(`run_qe_sequence.sh` in the same folder is an older convenience wrapper
that chains all three stages without the skip guards or the `QE_NK` knob;
the individual runners superseded it.)

For Rb2Cu2SnS4 the same trio has been run through relax and final SCF
([calculated], from `thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`: relax
converged in 8 BFGS steps, symmetry kept Ibam, volume 446.410 -> 450.561
A^3, +0.93%; final SCF gave 156.00 electrons -> 78 occupied bands). Its
dense NSCF (8x14x14, 788 irreducible points) and all BoltzTraP2 transport
have since finished a first pass: a sampled PBE gap of 0.7811 eV and a
full transport table now exist for it ([calculated],
`thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md`).

---

## 4. Transport + analysis (`SrCu2SnS4/boltztrap2/`)

Concepts: `../WORKFLOW_EXPLAINED.md` sections 4.6-4.7 (BoltzTraP2 and the
summaries) and 5.1-5.2 (the DOS comparison and the Seebeck figure).

### 4.1 `run_bt2.sh` — the three BoltzTraP2 stages, chained

**Purpose:** run interpolate -> integrate -> dope in one go, with logs.
(What each stage means is `02_tools_boltztrap2.md` section 2.)

**Inputs -> outputs:** `qe/tmp/final/SrCu2SnS4.save/` (QE result folder) ->
`boltztrap2/SrCu2SnS4.bt2` (interpolation file), `SrCu2SnS4.trace`,
`SrCu2SnS4.condtens`, `SrCu2SnS4.dope.trace`, plus three logs in `logs/`.

Key lines (`thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh`):

```bash
doping_levels="-1e21,-5e20,-2e20,-1e20,-5e19,-2e19,-1e19,1e19,2e19,5e19,1e20,2e20,5e20,1e21"
btp2_cmd=(python boltztrap2/btp2_compat.py)
...
if [ ! -f "$bt2_file" ]; then
  "${btp2_cmd[@]}" -n "$workers" -v interpolate -m 5 -o "$bt2_file" "$qe_source" \
    2>&1 | tee "$log_dir/SrCu2SnS4.bt2.interpolate.log"
fi

"${btp2_cmd[@]}" -v integrate "$bt2_file" 300:1000:100 \
  2>&1 | tee "$log_dir/SrCu2SnS4.bt2.integrate.log"
"${btp2_cmd[@]}" -v dope "$bt2_file" 300:1000:100 "$doping_levels" \
  2>&1 | tee "$log_dir/SrCu2SnS4.bt2.dope.log"
```

- The command is not `btp2` directly but the local shim
  `btp2_compat.py`, which patches two NumPy-2 incompatibilities in the
  installed BoltzTraP2 before calling its normal CLI (read line by line in
  `02_tools_boltztrap2.md` section 4).
- The expensive `interpolate` stage (`-m 5` = interpolate onto a mesh with
  ~5x more points per direction) is guarded by `[ ! -f "$bt2_file" ]` — the
  same idempotency idea as the QE runners, keyed on the output file rather
  than a JOB DONE string.
- `300:1000:100` is a start:stop:step temperature range with an exclusive
  stop, i.e. 300-900 K in 100 K steps.
- The doping list spans 1e19-1e21 cm^-3 for **both** carrier signs
  (negative = electron/n-doping, positive = hole/p-doping in this
  convention).
- Each stage is `tee`'d, so the log is preserved *and* visible live.

A caution for the next user: this polished form exists for SrCu2SnS4 and
SrZrS3 only. The pre-made SrZrS3 template had three bugs that were fixed
before running — `qe_source` missing the `final/` path component, a bare
`btp2` call that crashes under NumPy 2, and a `300:900:100` range that
stops at 800 K plus a `-1e21:1e21:1e20` doping sweep that passes through
zero (`thermo_candidates/SrZrS3/WORKLOG.md`; full story in
`02_tools_boltztrap2.md` section 3). The Rb2Cu2SnS4 copy
(`thermo_candidates/Rb2Cu2SnS4/boltztrap2/run_bt2.sh`) is **still the
unfixed starter template** with all three issues, and per its worklog it
will get the same fixes before its transport stage runs.

### 4.2 `summarize_transport.py` — from raw trace to tables

**Purpose:** convert the raw `dope.trace` into the CSVs and the summary
under `results/`, without touching the raw file. (Column meanings of the
trace: `02_tools_boltztrap2.md` section 5.)

**Inputs -> outputs:** `SrCu2SnS4.dope.trace`, the relaxed CIF, and the QE
`.save` folder -> `results/transport_full.csv`,
`results/transport_best_power_factor.csv`, `results/workflow_summary.md`.

Guided read (`thermo_candidates/SrCu2SnS4/boltztrap2/summarize_transport.py`):

**(a) Load and convert densities.** The trace stores carriers *per unit
cell*; dividing by the cell volume (from the relaxed CIF, converted A^3 ->
cm^3 by the 1e-24 factor) gives a signed density in cm^-3, whose sign
encodes the carrier type:

```python
    raw = np.loadtxt(TRACE, comments="#")
    structure = Structure.from_file(RELAXED_CIF)
    volume_cm3 = structure.volume * 1e-24
    ...
        signed_density = carriers_uc / volume_cm3
```

**(b) The two derived quantities.**

```python
        power_factor_tau = seebeck**2 * sigma_tau
        electronic_zt = power_factor_tau * temperature / kappa_tau
```

Read these with the units attached. `sigma_tau` is sigma/tau (electrical
conductivity per relaxation time), so `power_factor_tau` is
**PF/tau = S^2 * sigma/tau** in W m^-1 K^-2 s^-1 — a power factor *per
relaxation time*, never an absolute power factor, because tau is unknown.
The second line divides PF/tau * T by kappa_e/tau (electronic thermal
conductivity per relaxation time): the **tau cancels**, so `electronic_zt`
(zT_e) is a genuinely tau-independent number — but it is still **not the
final thermoelectric zT**, because the denominator is missing the lattice
thermal conductivity kappa_L entirely. The CSV column names encode both
caveats: `power_factor_over_tau_W_m-1_K-2_s-1` and
`electronic_zT_no_lattice`.

**(c) Best-on-grid selection.** For each (temperature, carrier-type) pair
the script keeps the row with the largest PF/tau:

```python
            best.append(
                max(
                    subset,
                    key=lambda row: row[
                        "power_factor_over_tau_W_m-1_K-2_s-1"
                    ],
                )
            )
```

This is a plain `max()` over the 7 sampled densities per sign — a **best
point on the sampled grid**, and nothing more. If the true optimum lies
between 2e20 and 5e20 cm^-3, this table will not see it.

**(d) The gap from the QE data itself.** Rather than trusting a
hand-copied number, the script reloads the QE eigenvalues through
BoltzTraP2's `ESPRESSOLoader` and computes the gap:

```python
    data = ESPRESSOLoader(str(QE_SOURCE))
    occupied = int(round(data.nelect / data.dosweight))
    vbm = float(np.max(data.ebands[occupied - 1]))
    cbm = float(np.min(data.ebands[occupied]))
    gap_ev = (cbm - vbm) * HARTREE_TO_EV
```

`nelect / dosweight` is the occupied-band count (dosweight = 2 for a
spin-degenerate, scalar-relativistic calculation); the valence-band maximum
(VBM) is the highest energy of the last occupied band across all sampled
k-points, the conduction-band minimum (CBM) the lowest energy of the first
empty one, and `HARTREE_TO_EV = 27.211386245988` [database] converts
Hartree to eV. Because VBM and CBM are extrema over the *sampled*
k-points, this is a sampled gap. For SrCu2SnS4 it evaluates to 0.3445 eV
[calculated] (the value recorded as `GAP_EV = 0.3445` in
`dos_compare.py` and `plot_seebeck.py`, and printed into
`results/workflow_summary.md` by this script).

**(e) Summary generation.** The script ends by writing
`results/workflow_summary.md` with the run's parameters (90/720 Ry, meshes
4x4x2 / 5x5x3 / 12x12x6, 140 bands / 105 occupied) and a best-PF/tau table
— followed by a hard-coded disclaimer block repeating that PF/tau is per
relaxation time and zT_e "is an upper bound rather than the full
thermoelectric zT". The caveats travel with the data.

The SrZrS3 copy (`thermo_candidates/SrZrS3/boltztrap2/summarize_transport.py`)
is the same script with its own paths and summary constants. Rb2Cu2SnS4
now has its own copy too
(`thermo_candidates/Rb2Cu2SnS4/boltztrap2/summarize_transport.py`, adapted
from the SrZrS3 version — the header identifiers and meshes swapped, the
transport math identical), and this stage has run for it: `Rb2Cu2SnS4.bt2`,
`.trace`, and `.dope.trace` exist in its `boltztrap2/`, and the script
wrote `results/workflow_summary.md` with a sampled gap of 0.7811 eV and a
best-PF/tau table for the material.

### 4.3 `dos_compare.py` — cross-validating two DOS calculations

**Purpose:** check that BoltzTraP2's interpolated density of states (DOS —
how many electronic states exist per energy interval) agrees with QE's own
`dos.x` result. If interpolation had mangled the bands, transport built on
it would be worthless. (Why this check exists: `../WORKFLOW_EXPLAINED.md`
section 5.1.)

**Inputs -> outputs (read-only on the raw records):**
`qe/dos/SrCu2SnS4.dos` and `boltztrap2/SrCu2SnS4.bt2` ->
`results/dos_qe_vs_boltztrap2.csv` and `.png`.

The subtlety is that `dos.x` output is Gaussian-smeared (width 0.005 Ry =
0.068 eV) while the BoltzTraP2 DOS is nearly raw, so a fair comparison
requires **matched broadening**
(`thermo_candidates/SrCu2SnS4/boltztrap2/dos_compare.py`):

```python
    sigma, dx = QE_DEGAUSS_EV, grid[1] - grid[0]
    kx = np.arange(-int(round(4 * sigma / dx)), int(round(4 * sigma / dx)) + 1) * dx
    kernel = np.exp(-0.5 * (kx / sigma) ** 2)
    kernel /= kernel.sum()
    bt_broad = np.convolve(bt_i, kernel, mode="same")
```

That is a normalized Gaussian kernel of the *same* 0.068 eV width,
convolved over the BoltzTraP2 DOS after both curves are interpolated onto
a common energy grid (-6 to +6 eV around E_F, 0.02 eV steps). Agreement is
then quantified two ways on the |E - E_F| < 5 eV window:

```python
    rel_l2 = np.linalg.norm(qe_i[w] - bt_broad[w]) / np.linalg.norm(qe_i[w])
    corr = np.corrcoef(qe_i[w], bt_broad[w])[0, 1]
```

— a relative L2 difference (overall size of the mismatch) and a Pearson
correlation coefficient (shape similarity). Both are printed, and the CSV
keeps units in every header
(`E_minus_EF_eV,QE_dosx_DOS_states_eV-1_cell-1,...`).

### 4.4 `plot_seebeck.py` — the Seebeck figure plus three cross-checks

**Purpose:** plot the Seebeck coefficient S (thermoelectric voltage per
unit temperature difference, in uV/K) against chemical potential, and run
three independent consistency checks on the BoltzTraP2 outputs before
trusting the picture (how to read the figure:
`../WORKFLOW_EXPLAINED.md` section 5.2). Note from the file's own
docstring: under the constant-relaxation-time approximation (CRTA) S is
independent of tau, so unlike sigma/tau and PF/tau the Seebeck values are
absolute (within scalar-relativistic QE-PBE, no SOC).

**Inputs -> outputs (read-only):** `SrCu2SnS4.trace`,
`SrCu2SnS4.condtens`, `SrCu2SnS4.dope.trace`, `SrCu2SnS4.bt2`, relaxed CIF
-> `results/seebeck_vs_mu.png`, `results/seebeck_vs_mu.csv`.

The three checks (`thermo_candidates/SrCu2SnS4/boltztrap2/plot_seebeck.py`):

**Check 1 — scalar vs tensor.** The scalar S column in the trace should be
the orientational average of the tensor diagonal stored in `condtens`:

```python
    s_diag_avg = cond[:, [12, 16, 20]].mean(axis=1) * 1e6
    sel = np.abs(s_uv) > 5.0             # avoid 0/0 near the sign change
    rel = np.max(np.abs(s_diag_avg[sel] - s_uv[sel]) / np.abs(s_uv[sel]))
```

Columns 12/16/20 are S_xx, S_yy, S_zz; rows where |S| < 5 uV/K are excluded
because a relative error is meaningless when the value itself passes
through zero. This confirms the two output files describe the same physics.

**Check 2 — charge neutrality at E_F.** The trace's carrier column must
cross ~0 exactly at the Fermi level:

```python
    n_at_ef = np.interp(fermi_ry, row300[:, 0], row300[:, 2])
```

If it did not, the Fermi level, the electron count, or the unit conventions
would be wrong somewhere.

**Check 3 — dope vs mu-scan consistency.** The `dope` run (fixed carrier
density) and the `integrate` run (scan over chemical potential mu) are two
routes to the same physics. The script takes the 300 K p-type 1e20 cm^-3
dope row, finds its chemical potential, and interpolates the mu-scan S at
that potential — the two S values must agree:

```python
    s_dope = row[4] * 1e6
    s_scan = np.interp(row[0], row300[:, 0], row300[:, 4]) * 1e6
```

Only after these three checks does the script draw the figure (gap region
shaded using the 0.3445 eV [calculated] sampled QE-PBE gap, p-type and
n-type sides labeled) and write a pivoted CSV with one S column per
temperature (`mu_minus_EF_eV,S_300K_uV_K-1,...`).

---

## 5. The bash runner pattern, distilled

Every runner in this repo — the per-stage QE runners of the completed
materials plus `run_bt2.sh` — is the same five ideas. When you write the
next one, copy this skeleton, not a memory of it:

```bash
#!/usr/bin/env bash
set -euo pipefail                       # 1. fail fast: any error stops the run

np="${QE_NP:-8}"                        # 2. env knobs with safe defaults
nk="${QE_NK:-2}"                        #    (override per run, never edit)
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

# 3. idempotency: completed work is detected and skipped,
#    keyed on QE's literal completion marker
if [ -f "$output" ] && grep -q 'JOB DONE' "$output"; then
  printf 'Skipping completed ...\n'; exit 0
fi

# 4. raw log goes to a file under logs/ (or outputs/), terminal stays quiet;
#    the raw log is a research record and is never rewritten
mpirun -np "$np" pw.x -nk "$nk" -in "$input" > "$output"

# 5. post-run health check: absence of the marker is a hard failure
if ! grep -q 'JOB DONE' "$output"; then
  printf 'QE did not finish cleanly: %s\n' "$output" >&2; exit 1
fi
```

Why each piece earns its place:

1. **Fail fast** (`set -euo pipefail`): a convergence series with one
   silently failed point produces a misleading CSV; better to stop.
2. **Env knobs** (`QE_NP`, `QE_NK`, `BT2_NP` in `run_bt2.sh`): parallelism
   is a property of the machine and the day, not of the script. The
   Rb2Cu2SnS4 k-point series went from 4 to 12 ranks by changing an
   environment variable, not a file (`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`).
3. **Idempotency**: reruns after crashes, suspends, or deliberate kills
   cost nothing. Precondition guards (like `run_nscf.sh` checking for the
   SCF's `data-file-schema.xml`) are the same idea pointed backwards.
4. **Logging convention**: raw QE logs live under `<material>/logs/`
   (production) or `convergence/*/outputs/` (tests) and are treated as
   research records — parsed by the extract scripts, never edited.
   BoltzTraP2 stages `tee` because their output is short; QE stages do not
   because theirs is not.
5. **Health checks**: trust the completion marker, not the exit path.

---

## 6. Adapting the set to a fourth material: what changes where

Suppose a fourth candidate `XYZ` enters the queue. The pattern is: **paths
and prefixes change everywhere; physics constants change only after that
material's own tests.** Never copy SrCu2SnS4's (or anyone's) cutoffs,
meshes, or band counts — that is the per-material convergence rule.

| File (relative to its usual location) | What must change for material 4 | Where the new value comes from |
|---|---|---|
| `scripts/make_qe_inputs.py` | add a `MATERIALS["XYZ"]` entry: prefix, pseudo filenames, SSSP-suggested cutoffs (Ry) | SSSP 1.3.0 PBE precision tables [database] — starting point only |
| `scripts/download_mp_structures.py` | add `"XYZ": "mp-NNNNN"` | Materials Project ID [database]; formula guard catches typos |
| `scripts/check_workspace.sh` | add any new pseudo filenames and the `XYZ` folder to the two loops | same pseudo list as the MATERIALS entry |
| `qe/convergence/prepare_cutoff_inputs.py` | `CIF` path; `CUTOFFS_RY` band bracketing the SSSP suggestion; `KMESH` scaled to the new cell's reciprocal shape; `PSEUDOS`; dual (x8 if any ultrasoft/PAW pseudo, x4 if all norm-conserving) | cell geometry + pseudo types |
| `qe/convergence/run_cutoff_convergence.sh`, `run_kpoint_convergence.sh` | nothing but paths (pattern is material-agnostic) | — |
| `qe/convergence/extract_cutoff_results.py` | `NAT` (atoms per cell; 24 / 20 / 18 for the three current materials) | the CIF |
| `qe/convergence/prepare_kpoint_inputs.py` | `ECUTWFC`/`ECUTRHO` from XYZ's own cutoff test [calculated]; `MESHES` scaled to the reciprocal axes; `PSEUDOS` | XYZ's `cutoff_results.csv` |
| `qe/convergence/extract_kpoint_results.py` | `NAT` | the CIF |
| `qe/prepare_relax.py` | `CIF`, prefix, `PSEUDOS`, cutoffs, `kpoints_grid` (relax tier from XYZ's k test; 4x4x2 / 6x3x2 / 2x4x4 for the current three) | XYZ's `kpoint_results.csv` |
| `qe/extract_relaxed_structure.py` | log filename; the expected formula string in the assertion guard | the material itself |
| `qe/prepare_final_scf.py` | relaxed-CIF path, prefix, cutoffs, mesh (one tier denser than relax: 5x5x3 / 8x4x2 / 3x5x5 currently) | XYZ's k test |
| `qe/prepare_nscf.py` | relaxed-CIF path, prefix, cutoffs; `nbnd` = occupied bands from XYZ's final SCF + ~30-35% headroom (140/105 SrCu2SnS4, 108/80 SrZrS3, 105/78 Rb2Cu2SnS4); dense mesh targeting ~0.08 A^-1 spacing on XYZ's cell (12x12x6 / 20x10x6 / 8x14x14) | XYZ's final-SCF log |
| `qe/run_relax.sh`, `run_final_scf.sh`, `run_nscf.sh` | input/output filenames; possibly `QE_NK` default for the machine | — |
| `boltztrap2/run_bt2.sh` | `qe_source`, `bt2_file`, log-name prefixes; temperature/doping grids only if the study design changes — and start from the *fixed* SrCu2SnS4/SrZrS3 form, not the buggy starter template (section 4.1) | — |
| `boltztrap2/summarize_transport.py` | `TRACE`, `QE_SOURCE`, `RELAXED_CIF` paths; every constant in the summary text (structure ID, space group, cutoffs, meshes, band counts) | XYZ's own runs [calculated] |
| `boltztrap2/dos_compare.py` | paths; `GAP_EV` (XYZ's own sampled gap); `QE_DEGAUSS_EV` if a different dos.x smearing is used | XYZ's NSCF via the loader |
| `boltztrap2/plot_seebeck.py` | paths; `GAP_EV`; the check-3 target density if the grid changes | XYZ's own runs [calculated] |

Rb2Cu2SnS4 is the live demonstration of this table: every stage is now
complete with its own numbers (90/720 Ry at 0.0896 meV/atom from the 100 Ry
reference, relax mesh 2x4x4, final SCF 3x5x5, dense NSCF 8x14x14, 78
occupied bands — all [calculated], traceable to
`thermo_candidates/Rb2Cu2SnS4/qe/convergence/cutoff_results.csv`,
`kpoint_results.csv`, and `WORKLOG.md`), through a first BoltzTraP2 pass
that produced a sampled PBE gap of 0.7811 eV and its own transport tables
(`results/transport_full.csv`, `transport_best_power_factor.csv`,
`workflow_summary.md`; p-type is favored by both PF/tau and zT_e). Those
numbers are that material's own [calculated] outputs, not carried over from
SrCu2SnS4; PF/tau there is still per relaxation time (not an absolute power
factor) and zT_e is still an electronic-only upper bound (not the full zT),
from a scalar-relativistic PBE run without explicit SOC, with grid "best"
points being maxima on the sampled carrier-density grid.

Next in the curriculum: `04_per_material_playbook.md` runs the whole
pipeline again as a task-by-task playbook with each material's real
numbers, and `07_exercises.md` has you trace these scripts' outputs by
hand.

---

*Self-review note: every number above was traced to the cited repo file at
writing time; conversion factors (Ry -> meV, Ha -> eV) are CODATA-derived
constants tagged [database]. Quantities from BoltzTraP2 are per relaxation
time where tau does not cancel; zT_e omits lattice thermal conductivity
and is never presented as the final zT; all electronic-structure runs are
scalar-relativistic PBE without explicit SOC; grid "best" values are grid
maxima; no convergence parameter is presented as transferable between
materials. Rb2Cu2SnS4's first-pass transport values (sampled gap 0.7811 eV
and its PF/tau and zT_e tables) now exist and are its own [calculated]
outputs, carrying the same PF/tau, zT_e, SOC, and best-on-grid caveats.*

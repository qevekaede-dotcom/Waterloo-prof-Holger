# BoltzTraP2 in practice

Document 2 of the learning curriculum (map: `learning/README.md`).
Companion documents: `01_tools_quantum_espresso.md` (the QE side that feeds
BoltzTraP2), `03_code_walkthrough.md` (the repo's scripts in depth),
`04_per_material_playbook.md` (the full pipeline per material), and
`06_data_handling.md` (working with the output CSVs).

The theory behind everything here is in `../WORKFLOW_EXPLAINED.md` —
especially **section 3.8** (transport quantities and the relaxation time tau)
and **section 4.6** (where BoltzTraP2 sits in the SrCu2SnS4 workflow). This
document does not repeat that theory; it teaches the *tool*: the commands, the
files, the code, and the traps.

Everything below is scalar-relativistic PBE with **no explicit SOC**
(spin-orbit coupling — a relativistic correction that splits bands; our QE
runs do not include it, and BoltzTraP2 inherits whatever QE gives it).
All numbers are tagged [calculated] / [database] / [experimental].

---

## 1. What BoltzTraP2 does in one page

BoltzTraP2 does two jobs, in sequence:

**Job 1 — band interpolation.** Quantum ESPRESSO gives band energies only at
a finite grid of k-points (for SrCu2SnS4: the dense NSCF on a `12x12x6` mesh,
100 irreducible k-points, 140 bands [calculated,
`thermo_candidates/SrCu2SnS4/results/dos_comparison.md`]). Transport
integrals need band energies and band *slopes* (velocities) essentially
everywhere in the Brillouin zone. BoltzTraP2 fits smooth,
symmetry-respecting analytic functions through the computed points, so the
bands can be evaluated at any k-point in between. See
`../WORKFLOW_EXPLAINED.md` section 4.6 for how this played out on SrCu2SnS4.

**Job 2 — Boltzmann transport in the CRTA.** From the interpolated bands it
evaluates the semiclassical Boltzmann transport equation. "Semiclassical"
means electrons occupy quantum band states but move and scatter like
classical particles. The **CRTA** (constant relaxation time approximation)
assumes every electron travels the same unknown average time `tau` between
scattering events. Because `tau` is a single unknown constant, it factors out
of every transport integral — which fixes exactly what you can and cannot
get:

What BoltzTraP2 **gives** you (per temperature and per doping level):

- `S` — the Seebeck coefficient. `tau` cancels; this is an absolute number
  at this level of theory (PBE bands, rigid doping, no SOC).
- `sigma/tau` — electrical conductivity *divided by the unknown tau*.
- `kappa_e/tau` — the electronic part of the thermal conductivity, per tau.
- Derived: `PF/tau = S^2 * (sigma/tau)` and the electronic-only `zT_e`.

What BoltzTraP2 **cannot** give you:

- **An absolute `sigma` or an absolute power factor.** `PF/tau` is a power
  factor *per unknown relaxation time* — never call it an absolute power
  factor. Getting absolute values requires a real scattering model for `tau`,
  which is outside this level of theory.
- **Anything about `kappa_L`**, the lattice (phonon) thermal conductivity.
  BoltzTraP2 only knows about electrons. In `zT_e` the `tau` conveniently
  cancels (it is a ratio), but the denominator still lacks `kappa_L`, so
  `zT_e` is **never** the final thermoelectric `zT` — it is an
  electronic-only quantity. The full argument is the table in
  `../WORKFLOW_EXPLAINED.md` section 3.8.
- **Real dopant chemistry.** Doping is "rigid band": the filling level is
  shifted while the bands stay frozen. Real dopant atoms would distort the
  bands somewhat — a stated approximation
  (`../WORKFLOW_EXPLAINED.md` section 4.6).

---

## 2. The three CLI stages, with our real commands

The driver is `thermo_candidates/SrCu2SnS4/boltztrap2/run_bt2.sh`. Its three
working commands (paths shortened; `"${btp2_cmd[@]}"` expands to
`python boltztrap2/btp2_compat.py` — see section 4 for why not the bare
`btp2` command):

```bash
# stage 1: interpolate  (skipped automatically if the .bt2 already exists)
python boltztrap2/btp2_compat.py -n 4 -v interpolate -m 5 \
    -o boltztrap2/SrCu2SnS4.bt2 qe/tmp/final/SrCu2SnS4.save

# stage 2: integrate  (chemical-potential scan)
python boltztrap2/btp2_compat.py -v integrate boltztrap2/SrCu2SnS4.bt2 300:1000:100

# stage 3: dope  (fixed carrier densities)
python boltztrap2/btp2_compat.py -v dope boltztrap2/SrCu2SnS4.bt2 300:1000:100 \
    "-1e21,-5e20,-2e20,-1e20,-5e19,-2e19,-1e19,1e19,2e19,5e19,1e20,2e20,5e20,1e21"
```

All three lines, the worker count (`-n`, default 4 via the `BT2_NP`
environment variable), and the 14-level doping list are verbatim from
`run_bt2.sh` [calculated setup].

### Stage 1: `interpolate`

- **Input**: the QE `.save` directory from the *dense NSCF* — the script
  refuses to run unless `qe/tmp/final/SrCu2SnS4.save/data-file-schema.xml`
  exists (that XML is QE's machine-readable output; see
  `01_tools_quantum_espresso.md`).
- **`-m 5`**: the interpolation multiplier. Roughly: use about 5x as many
  fitting functions as there are ab initio k-points, giving ~5x denser
  effective band sampling (546 symmetry-adapted basis functions for
  SrCu2SnS4's 100 k-points [calculated, `../WORKFLOW_EXPLAINED.md`
  section 4.6]).
- **`-o SrCu2SnS4.bt2`**: the output. A `.bt2` file is a serialized
  (saved-to-disk) bundle of the fitted band coefficients plus the structure
  and electron-count metadata — on disk it is an XZ-compressed archive (its
  first bytes are the `7zXZ` magic [calculated, byte inspection of
  `boltztrap2/SrCu2SnS4.bt2`]). It is *reusable*: every later analysis in
  this repo (`dos_compare.py`, `plot_seebeck.py`) loads this one file and
  never reruns QE. `run_bt2.sh` therefore skips this stage when the `.bt2`
  already exists — a convenience that becomes a trap (see the checklist,
  section 8).
- BoltzTraP2 keeps only bands inside an energy window around the Fermi level;
  for SrCu2SnS4 that window holds 124 of the 210 valence electrons — the deep
  "semicore" states are dropped [calculated,
  `thermo_candidates/SrCu2SnS4/results/dos_comparison.md`]. Details in
  section 8.

### Stage 2: `integrate` — the mu scan

Scans the chemical potential `mu` (the filling level of the electron states)
across the band window at each temperature, writing `SrCu2SnS4.trace`,
`.condtens`, and `.halltens`. For SrCu2SnS4 that is 763 mu points x 7
temperatures = 5341 rows [calculated: `SrCu2SnS4.trace` has 5342 lines
= 1 header + 5341 rows, with 763 unique mu values and exactly the
temperatures 300, 400, 500, 600, 700, 800, 900 K, counted with
`wc -l`/`awk`; same breakdown in `../WORKFLOW_EXPLAINED.md` section 4.6].

**The temperature syntax `300:1000:100` is a half-open range**, exactly like
Python's `range()`: the start is included, the stop is **excluded**. So
`300:1000:100` produces 300, 400, 500, 600, 700, 800, 900 K — seven
temperatures ending at 900 K. It is written with `1000` *on purpose*: the
naive-looking `300:900:100` would stop at **800 K** and silently drop the
900 K row. This exact mistake was in the SrZrS3 template
(`thermo_candidates/SrZrS3/WORKLOG.md`; section 3 below).

### Stage 3: `dope` — fixed carrier densities

Instead of scanning `mu`, `dope` solves for the `mu` that produces each
*requested carrier density*, at each temperature. Sign convention: **negative
density = n-type (electrons added), positive = p-type (electrons removed)**
(`../WORKFLOW_EXPLAINED.md` section 4.6). Our grid: +/-1e19, 2e19, 5e19,
1e20, 2e20, 5e20, 1e21 cm^-3 — 14 levels x 7 temperatures = 98 rows
[calculated: `SrCu2SnS4.dope.trace` has 99 lines = 1 header + 98 rows,
`wc -l`].

**Why an explicit comma list and not a colon range?** A range like
`-1e21:1e21:1e20` is wrong for two reasons:

1. **It sweeps through zero.** Stepping linearly from -1e21 the grid lands
   exactly on 0 cm^-3 — an undoped point that is useless in a doping study
   and was flagged as a template bug in
   `thermo_candidates/SrZrS3/WORKLOG.md`.
2. **Linear steps cannot cover two decades.** With a 1e20 step the smallest
   nonzero magnitude is 1e20 cm^-3; the entire 1e19-1e20 decade (where
   thermoelectrics are often optimized) is skipped. Doping grids need
   log-like spacing, which only an explicit list gives.

One consequence for how results are worded: any "best" doping point found
later is the best **on this sampled 14 x 7 grid**, not a continuous optimum —
the true optimum can sit between grid points.

---

## 3. A real bug story: the SrZrS3 template

When SrZrS3 (material 2) reached the transport step, its pre-made
`boltztrap2/run_bt2.sh` template — written before any SrZrS3 output existed —
contained **three bugs**, all caught by reading the script before running it
(`thermo_candidates/SrZrS3/WORKLOG.md`, entry "dense NSCF + BoltzTraP2
complete; first pass done"):

1. **Wrong `qe_source` path**: it pointed at `qe/tmp/SrZrS3.save` instead of
   `qe/tmp/final/SrZrS3.save`. The final SCF stores its density under
   `qe/tmp/final/`; the template guessed the layout and guessed wrong. The
   `data-file-schema.xml` existence check in the script is what turns this
   from a silent wrong-data disaster into a clean error message.
2. **It called the bare `btp2` CLI**, which crashes under NumPy 2. Fix:
   route every call through the `btp2_compat.py` shim (section 4), copied
   from SrCu2SnS4.
3. **Half-open-range mistakes**: `300:900:100` (stops at 800 K, losing the
   900 K row) and the `-1e21:1e21:1e20` doping syntax (sweeps through zero).
   Replaced with `300:1000:100` and the explicit 14-level list used for
   SrCu2SnS4.

The lessons generalize: a template is a hypothesis about your directory
layout and your software environment, not a fact. Read every line before
running; check the input path against what the previous step actually wrote;
and expect the *same* bugs in every sibling template — the Rb2Cu2SnS4 work
log already anticipates "the same three bugs expected as SrZrS3's"
(`thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`).

---

## 4. `btp2_compat.py`, line by line

The whole shim is 27 lines
(`thermo_candidates/SrCu2SnS4/boltztrap2/btp2_compat.py`; shebang and module
docstring elided here):

```python
import numpy as np

if not hasattr(np, "trapz"):
    np.trapz = np.trapezoid

from BoltzTraP2 import bandlib  # noqa: E402
from BoltzTraP2.interface import btp2_main  # noqa: E402

_smoothen_dos = bandlib.smoothen_DOS_direct

def _smoothen_positive_dos(*args, **kwargs):
    # BoltzTraP2 26.3.1 divides by the negative FD-derivative normalization.
    return -_smoothen_dos(*args, **kwargs)

bandlib.smoothen_DOS_direct = _smoothen_positive_dos

if __name__ == "__main__":
    btp2_main()
```

- **`np.trapz = np.trapezoid`**: NumPy 2 removed the old `np.trapz`
  (trapezoidal integration) after renaming it `np.trapezoid`. BoltzTraP2
  26.3.1 still calls `np.trapz`, so under NumPy 2 the bare `btp2` command
  dies — bug 2 of section 3. The shim restores the old name *before*
  BoltzTraP2 is imported (the `# noqa: E402` comments tell the style checker
  that these deliberately-late imports are intentional). The `hasattr` guard
  makes the shim harmless on older NumPy, where `np.trapz` still exists.
- **The `smoothen_DOS_direct` sign fix**: per the comment in the file,
  BoltzTraP2 26.3.1 normalizes its smoothed DOS (density of states —
  states per unit energy) by the *negative* of the Fermi-Dirac-derivative
  kernel, so the smoothed DOS comes out with a flipped sign. The wrapper
  keeps a reference to the original function, negates its result, and
  installs the wrapper back into `bandlib`. Replacing a library function at
  runtime like this is called **monkey-patching**.
- **Why a shim file instead of editing the installed library?** The fix
  lives in the repo, under version control, visible to anyone reproducing
  the run — and it survives reinstalls of BoltzTraP2. Editing files inside
  the installed package would be invisible and fragile.
- **`if __name__ == "__main__": btp2_main()`**: the "spawn guard" — required
  because BoltzTraP2 runs parallel workers (`-n 4` in `run_bt2.sh`). Why it
  matters is explained with the Python API in section 6.

---

## 5. The output files and their columns

Directory listing after a full SrCu2SnS4 run
(`thermo_candidates/SrCu2SnS4/boltztrap2/`): `SrCu2SnS4.bt2` (the fit) and
`SrCu2SnS4.btj` (an XZ-compressed JSON dump of the loaded DFT data — it
decompresses to `[{"BoltzTraP2_type": "DFTData", "ebands": ...}]` [calculated,
`xz -dc` inspection]), then per stage: `.trace`, `.condtens`, `.halltens`
from `integrate`, and `.dope.trace`, `.dope.condtens`, `.dope.halltens` from
`dope`.

### 5.1 The trace files: 10 columns of scalars

`SrCu2SnS4.trace` (mu scan) and `SrCu2SnS4.dope.trace` (fixed densities)
share one header, quoted from the files themselves:

```
#   Ef[Ry]  T[K]  N[e/uc]  DOS(ef)[1/(Ha*uc)]  S[V/K]  sigma/tau0[1/(ohm*m*s)]  RH[m**3/C]  kappae/tau0[W/(m*K*s)]  cv[J/(mol*K)]  chi[m**3/mol]
```

| # | Column (unit) | NumPy index | Meaning |
|---|---|---|---|
| 1 | `Ef` (Ry) | `[:,0]` | The chemical potential `mu` of this row, in Rydberg (1 Ry = 13.6057 eV [database]). The header says "Ef", but only the row where `N ~ 0` is the actual Fermi level; every other row is a shifted `mu`. |
| 2 | `T` (K) | `[:,1]` | Temperature. |
| 3 | `N` (electrons/unit cell) | `[:,2]` | Electron count **relative to the neutral cell**: positive = electrons removed (p-type), negative = electrons added (n-type); it crosses ~0 exactly at `mu = E_F` (sign convention documented in `boltztrap2/plot_seebeck.py`, check 2). |
| 4 | `DOS(ef)` (states/(Ha * unit cell)) | `[:,3]` | Density of states at `mu`, per Hartree (1 Ha = 2 Ry = 27.2114 eV [database, constant used in `plot_seebeck.py`]). |
| 5 | `S` (V/K) | `[:,4]` | Seebeck coefficient. Multiply by 1e6 for uV/K. tau-independent (section 7). |
| 6 | `sigma/tau0` (1/(ohm * m * s)) | `[:,5]` | Electrical conductivity divided by the unknown `tau`. |
| 7 | `RH` (m^3/C) | `[:,6]` | Hall coefficient (what a Hall-effect measurement would give; its sign tracks the dominant carrier type). |
| 8 | `kappae/tau0` (W/(m * K * s)) | `[:,7]` | Electronic thermal conductivity per `tau`. |
| 9 | `cv` (J/(mol * K)) | `[:,8]` | Electronic heat capacity. |
| 10 | `chi` (m^3/mol) | `[:,9]` | Magnetic susceptibility of the electrons. |

A concrete example of the column-3 sign convention, from the first data row
of `SrCu2SnS4.dope.trace` at 300 K: `N = -0.546719` e/uc [calculated]. That
is the -1e21 cm^-3 (n-type) request converted to the cell: the relaxed
volume is 546.507 A^3 [calculated,
`thermo_candidates/SrCu2SnS4/CLAUDE.md`] = 546.507e-24 cm^3, and
1e21 cm^-3 x 546.507e-24 cm^3 = 0.5465 electrons per cell — matching the
file's 0.546719 to 0.04% (the residual is rounding in the quoted volume) and
negative because electrons were *added*.

### 5.2 The condtens files: 30 columns of tensors

Crystals conduct differently along different axes (SrCu2SnS4 is trigonal,
space group P3_121 [calculated, `thermo_candidates/SrCu2SnS4/CLAUDE.md`]), so
the full results are 3x3 **tensors**. `SrCu2SnS4.condtens` has 30 columns
[calculated, `awk` field count]:

| Columns (1-based) | NumPy indices | Content (unit) |
|---|---|---|
| 1-3 | `[:,0:3]` | `Ef` (Ry), `T` (K), `N` (e/uc) — same as the trace file |
| 4-12 | `[:,3:12]` | `sigma/tau0` 3x3 tensor, 9 components (1/(ohm * m * s)) |
| 13-21 | `[:,12:21]` | `S` 3x3 tensor, 9 components (V/K) |
| 22-30 | `[:,21:30]` | `kappae/tau0` 3x3 tensor, 9 components (W/(m * K * s)) |

Within each 9-component block the **diagonal** (xx, yy, zz) sits at block
positions 1, 5, 9 — that is NumPy columns 12, 16, 20 for the S block, exactly
the indices `plot_seebeck.py` uses for its cross-check. In the row inspected
below every off-diagonal is at numerical-noise level (the S off-diagonals
are ~1e-21 V/K against ~1e-5 V/K diagonals [calculated]), so the
off-diagonal ordering convention never matters in practice for this
material.

**The scalar in the trace file is the average of the tensor diagonal.**
Verified on the first data row of `SrCu2SnS4.condtens` (mu = 0.169152 Ry,
300 K) [calculated]:

- `S` diagonal: (1.00283e-05 + 1.00283e-05 + 3.03888e-05)/3 = 1.68151e-05
  V/K — the trace file's `S` for the same row is 1.68152e-05 V/K.
- `sigma/tau0` diagonal: (2.93986e+19 + 2.93985e+19 + 1.15265e+19)/3 =
  2.34412e+19 1/(ohm * m * s) — the trace value is 2.34412e+19.

Note how anisotropic this row is: `sigma_zz/tau` is ~2.5x smaller than
`sigma_xx/tau` [calculated, same row]. The trace scalar hides that — check
the tensors before claiming a material is a good conductor "overall". (More
column-by-column reading practice: `../WORKFLOW_EXPLAINED.md` section 7.3 and
`06_data_handling.md`.)

The `.halltens` files hold the analogous Hall tensor; they are not used by
the current analysis scripts.

---

## 6. The Python API, as used in this repo

Beyond the CLI, the repo's analysis scripts import BoltzTraP2 as a library.
The two worked examples are
`thermo_candidates/SrCu2SnS4/boltztrap2/dos_compare.py` and
`plot_seebeck.py`. The pattern:

```python
from BoltzTraP2 import serialization, fite, bandlib

# 1. load the saved interpolation (no QE needed)
data, equivalences, coeffs, metadata = serialization.load_calculation("SrCu2SnS4.bt2")

# 2. rebuild bands + band velocities on the dense interpolated grid
eband, vvband = fite.getBTPbands(equivalences, coeffs, data.get_lattvec())[:2]

# 3. density of states from the interpolated bands
epsilon, dos, vvdos, cdos = bandlib.BTPDOS(eband, vvband, npts=4000)
```

Key objects and unit traps (all visible in the two scripts):

- `data.fermi` — the Fermi level in **Hartree**. BoltzTraP2 works internally
  in Hartree atomic units; `plot_seebeck.py` converts with
  `fermi_ry = data.fermi * 2.0` (Ha -> Ry, to match trace-file column 1)
  and `dos_compare.py` with `HA_TO_EV = 27.211386245988` [database constant].
- `data.nelect` — the electron count *inside BoltzTraP2's band window*: 124
  for SrCu2SnS4, not the full 210 (section 8).
- `data.dosweight` — the spin degeneracy factor; `dos_compare.py` multiplies
  the raw DOS by it (and divides by `HA_TO_EV`) to get states/eV/cell.

What the two scripts do with this:

- **`dos_compare.py`** builds the interpolated DOS, broadens it by the same
  0.068 eV Gaussian width as QE's `dos.x`, and overlays the two. Result:
  relative L2 difference 0.066 and Pearson r = 0.9943 within |E - E_F| < 5 eV
  [calculated, `thermo_candidates/SrCu2SnS4/results/dos_comparison.md`] — the
  interpolation is faithful where transport happens.
- **`plot_seebeck.py`** runs three consistency checks before plotting:
  (1) trace scalar S = condtens diagonal average (section 5.2); (2) the `N`
  column crosses ~0 at `mu = E_F` (charge neutrality); (3) a `dope` row
  agrees with interpolating the mu scan at the same `mu`. Copy this habit:
  never plot a file you have not cross-checked against its siblings.

**The macOS spawn guard.** All three Python files in `boltztrap2/` end with

```python
if __name__ == "__main__":
    main()          # or btp2_main() in btp2_compat.py
```

BoltzTraP2 parallelizes with Python's `multiprocessing` (the `-n 4` workers
in `run_bt2.sh`). On macOS, each worker process is started by *re-importing
the main script* (the "spawn" start method). Without the guard, the
top-level code would re-execute in every worker — each worker spawning
workers of its own, recursing until the machine chokes. The guard makes the
import side-effect-free: only the original process, where the file is run
directly (`__name__ == "__main__"`), actually starts the work. Any script
you write that touches BoltzTraP2 needs this guard on macOS.

---

## 7. tau-independent vs tau-scaled quantities

The one table to memorize (theory: `../WORKFLOW_EXPLAINED.md` section 3.8):

| Quantity | Unit as printed | tau status | May you quote it as absolute? |
|---|---|---|---|
| `S` | V/K (uV/K in summaries) | tau cancels in the CRTA | Yes — absolute at this level of theory (PBE, rigid band, no SOC) |
| `sigma/tau` | 1/(ohm * m * s) | scaled by unknown tau | No — only ratios/trends |
| `kappa_e/tau` | W/(m * K * s) | scaled by unknown tau | No — only ratios/trends |
| `PF/tau = S^2 * sigma/tau` | W/(m * K^2 * s) | scaled by unknown tau | **No — never call PF/tau an absolute power factor** |
| `zT_e` | dimensionless | tau cancels (it is a ratio) | No — it still **lacks `kappa_L`**, so it is electronic-only, never the final `zT` |

Note the subtlety in the last row: `tau` cancelling is *not* enough to make
`zT_e` final. The real `zT` denominator is `kappa_e + kappa_L`, and
BoltzTraP2 knows nothing about `kappa_L` (phonons). A final `zT` needs both a
relaxation-time model and a lattice thermal conductivity calculation —
neither exists yet for any material in this repo.

---

## 8. Gotchas checklist

Work through this before and after every BoltzTraP2 run:

- [ ] **Quote your paths.** Every path in this repo contains spaces
  (`.../Waterloo Holger thermoelectric materials/...`); an unquoted path in a
  shell command splits into pieces and fails confusingly.
- [ ] **Point at the right `.save`.** The input is the *dense NSCF / final*
  directory, `qe/tmp/final/<material>.save`, and it must contain
  `data-file-schema.xml` (checked by `run_bt2.sh`). The SrZrS3 template got
  this wrong (`thermo_candidates/SrZrS3/WORKLOG.md`).
- [ ] **Never call bare `btp2` under NumPy 2.** Always go through
  `btp2_compat.py` (section 4).
- [ ] **Half-open ranges.** `300:1000:100` gives 300-900 K; `300:900:100`
  silently stops at 800 K. Never use a colon range for doping — it sweeps
  through zero and misses the low decades; use the explicit list (section 2).
- [ ] **Stale `.bt2` cache.** `run_bt2.sh` skips `interpolate` when the
  `.bt2` file already exists. If you reran the NSCF, delete or rename the old
  `.bt2` first, or `integrate`/`dope` will happily process the *old* fit.
- [ ] **The band window drops semicore states — on purpose.** BoltzTraP2
  keeps only bands within roughly E_F +/- 5.6 eV; for SrCu2SnS4 that is 94
  bands holding 124 of the 210 valence electrons [calculated,
  `thermo_candidates/SrCu2SnS4/results/dos_comparison.md` and
  `../WORKFLOW_EXPLAINED.md` section 4.6]. So `data.nelect = 124`
  disagreeing with QE's 210 is expected, not a bug — but it also means the
  `.bt2` is useless for anything about deep states, and DOS comparisons
  against QE only make sense inside the window.
- [ ] **A "best" point is best on the sampled grid** (14 densities x 7
  temperatures), not a continuous optimum.
- [ ] **Convergence parameters are per-material.** SrCu2SnS4's `12x12x6`
  dense mesh and band count are not defaults for the next compound; SrZrS3
  ran its own tests and landed on 50/400 Ry with a `20x10x6` dense NSCF, and
  Rb2Cu2SnS4's own cutoff test selected 90/720 Ry [calculated,
  `thermo_candidates/SrZrS3/WORKLOG.md` and
  `thermo_candidates/Rb2Cu2SnS4/WORKLOG.md`]. Rerun the whole convergence
  ladder for every material (`thermo_candidates/CLAUDE.md`).
- [ ] **Standing physics caveats** (state them whenever you report numbers):
  scalar-relativistic, no explicit SOC; rigid-band doping; CRTA; and
  transport-property convergence with respect to the dense k-mesh has not
  been checked for any material yet
  (`thermo_candidates/SrCu2SnS4/CLAUDE.md`).
- [ ] **Rb2Cu2SnS4 status: complete.** Its convergence tests, vc-relax,
  final SCF, dense NSCF, and BoltzTraP2 transport are all done (156 electrons
  -> 78 occupied bands; dense NSCF `8x14x14` with 105 bands; sampled QE-PBE
  gap `0.7811 eV`; p-type favored by both `PF/tau` and `zT_e` [calculated,
  `thermo_candidates/Rb2Cu2SnS4/WORKLOG.md` and
  `thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md`]). Its
  `run_bt2.sh` carried the same three bugs as SrZrS3's (qe_source missing
  `/final`; bare `btp2` crashing under NumPy 2; half-open `300:900:100` range
  and through-zero `-1e21:1e21:1e20` doping) — all three were fixed before the
  run, giving `Rb2Cu2SnS4.bt2`, `.trace`, `.dope.trace`, `.condtens` and
  `results/{transport_full.csv,transport_best_power_factor.csv,workflow_summary.md}`.
  This is the second material to confirm the shipped template carries those
  three bugs.

Self-review note for this document: every number above was traced to the
cited repo file at writing time (file headers and row values via direct
inspection; line/column counts via `wc -l` and `awk`); the interpolation
internals (multiplier behavior, band-window mechanics) are described only as
far as `../WORKFLOW_EXPLAINED.md` section 4.6 and
`results/dos_comparison.md` document them for our runs.

Next in the curriculum: `03_code_walkthrough.md`.

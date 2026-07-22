# Data handling: reading, converting, checking

This is the practical data-skills document of the curriculum (map:
`README.md`). It teaches you to find, read, convert, and cross-check every
data file this project produces. Theory lives in `../WORKFLOW_EXPLAINED.md`:
see its section 3.7 (density of states), 3.8 (transport quantities and the
relaxation time tau), and 4.7 (how the `results/` summaries are built).
Siblings: `01_tools_quantum_espresso.md` (reading QE logs line by line),
`02_tools_boltztrap2.md` (the BoltzTraP2 file formats in depth),
`03_code_walkthrough.md` (the scripts that generate these files), and
`07_exercises.md` (practice on exactly these files).

Conventions used here:

- Unless stated otherwise, paths are relative to
  `thermo_candidates/SrCu2SnS4/`, the one material with a completed first
  pass. In shell snippets `$M` stands for that folder.
- **Every repo path contains spaces** (the repo root is
  `Waterloo Holger thermoelectric materials`), so **always quote paths** in
  shell commands: `"$M/results/transport_full.csv"`, never
  `$M/results/transport_full.csv`.
- Values are tagged [calculated] (produced by our QE/BoltzTraP2 runs),
  [database] (looked up, e.g. physical constants), or [experimental]
  (measured; none appear in this document).
- All calculations here are scalar-relativistic PBE, **no explicit SOC**
  (spin-orbit coupling, a relativistic correction that splits bands).

Status note: for `Rb2Cu2SnS4` the first pass is **complete** — the dense NSCF
and the BoltzTraP2 transport have both finished. Its convergence, relaxation,
final-SCF, band-gap, and transport numbers all exist and are used below; its
sampled QE-PBE gap is `0.7811 eV` [calculated]
(`$R/results/workflow_summary.md`). As always, PF/tau is not an absolute power
factor and `electronic_zT_no_lattice` is an electronic-only upper bound, not
the final zT.

Set up the shell variables used throughout (run from the repo root):

```bash
M="thermo_candidates/SrCu2SnS4"
R="thermo_candidates/Rb2Cu2SnS4"
```

---

## 1. Where data lives: raw vs derived

Two kinds of files exist, and the distinction drives the most important
house rule of the workspace.

**Raw research records** — direct output of Quantum ESPRESSO (QE) or
BoltzTraP2. They are the evidence; every number in a summary must trace back
to one of them.

| Location (under `$M/`) | What it is | Format |
|---|---|---|
| `logs/SrCu2SnS4.relax.out`, `logs/SrCu2SnS4.scf.out`, `logs/SrCu2SnS4.nscf.out` | full QE text logs of the relaxation, final SCF, dense NSCF | plain text |
| `logs/SrCu2SnS4.bt2.interpolate.log`, `.integrate.log`, `.dope.log` | BoltzTraP2 stage logs | plain text |
| `qe/tmp/final/` | QE binary scratch: wavefunctions, charge density, eigenvalue XML that BoltzTraP2 reads | binary/XML |
| `qe/dos/SrCu2SnS4.dos` (+ `.dos.in`, `.dos.out`) | `dos.x` density-of-states table | whitespace text |
| `qe/convergence/cutoff/outputs/`, `qe/convergence/kpoints/outputs/` | the convergence-test QE logs | plain text |
| `boltztrap2/SrCu2SnS4.trace`, `.dope.trace` | BoltzTraP2 scalar transport tables (mu scan / fixed doping) | whitespace text, `#` header |
| `boltztrap2/SrCu2SnS4.condtens`, `.halltens`, `.dope.condtens`, `.dope.halltens` | full 3x3 transport tensors | whitespace text |
| `boltztrap2/SrCu2SnS4.bt2`, `.btj` | the saved band interpolation | binary/JSON |

**Derived summaries** — tables and figures computed *from* the raw files,
kept in `results/`: `transport_full.csv`, `transport_best_power_factor.csv`,
`dos_qe_vs_boltztrap2.csv`, `seebeck_vs_mu.csv`, the `.png` figures, and the
`.md` write-ups.

The rule (from the project `CLAUDE.md`): **never edit, "clean up", or delete
raw files.** They are research records, like lab-notebook pages. If a derived
number looks wrong, fix the script that produced it and regenerate the file
in `results/`; before changing any result, trace it back to the raw QE or
BoltzTraP2 output it came from. The convergence CSVs under `qe/convergence/`
sit in between (a script extracted them from raw logs) — treat them as
records too and regenerate rather than hand-edit.

For `Rb2Cu2SnS4` right now: `$R/logs/` holds `Rb2Cu2SnS4.relax.out`,
`Rb2Cu2SnS4.scf.out`, and the finished `Rb2Cu2SnS4.nscf.out`;
`$R/qe/convergence/` holds its two finished convergence CSVs;
`$R/boltztrap2/` now holds the full interpolation and transport set
(`Rb2Cu2SnS4.bt2`, `.btj`, `.trace`, `.dope.trace`, `.condtens`,
`.dope.condtens`, `.halltens`, `.dope.halltens`) alongside the runner script
and README; and `$R/results/` holds `transport_full.csv` (98 rows),
`transport_best_power_factor.csv` (14 rows), and `workflow_summary.md`
alongside its README — the first-pass transport outputs are **complete**.

---

## 2. Column glossaries: every CSV in the repo

All values in these files are [calculated] (QE-PBE + BoltzTraP2,
scalar-relativistic, no SOC) unless noted. Column names carry their units
after the last underscore — `seebeck_uV_K` means "Seebeck coefficient in
uV/K". `uc` means "unit cell".

### 2.1 `results/transport_full.csv` — the full doped-transport grid

98 data rows = 7 temperatures (300–900 K in 100 K steps) x 2 carrier types
x 7 target carrier densities (1e19, 2e19, 5e19, 1e20, 2e20, 5e20,
1e21 cm^-3). Source: `boltztrap2/SrCu2SnS4.dope.trace`, reshaped by
`boltztrap2/summarize_transport.py`. Header read from the file itself:

| # | Column | Unit | Meaning |
|---|---|---|---|
| 1 | `temperature_K` | K | temperature of the transport integral |
| 2 | `carrier_type` | - | `n` (extra electrons) or `p` (extra holes) |
| 3 | `carrier_density_cm-3` | cm^-3 | achieved carrier density (magnitude). BoltzTraP2 hits the target only approximately, so you see e.g. `1.0000001459217128e+20` instead of exactly 1e20, and the achieved value drifts slightly with temperature |
| 4 | `signed_density_cm-3` | cm^-3 | same, negative for n-type, positive for p-type |
| 5 | `chemical_potential_Ry` | Ry | chemical potential mu (the "Fermi level of the doped system") on QE's absolute energy scale |
| 6 | `seebeck_uV_K` | uV/K | Seebeck coefficient S, orientational average. Within the constant relaxation-time approximation tau cancels here, so S is an absolute calculated quantity |
| 7 | `sigma_over_tau_ohm-1_m-1_s-1` | ohm^-1 m^-1 s^-1 | electrical conductivity **divided by the unknown relaxation time tau**. Not an absolute conductivity |
| 8 | `kappa_e_over_tau_W_m-1_K-1_s-1` | W m^-1 K^-1 s^-1 | electronic part of the thermal conductivity, also per tau |
| 9 | `power_factor_over_tau_W_m-1_K-2_s-1` | W m^-1 K^-2 s^-1 | PF/tau = S^2 * (sigma/tau). **Never call this an absolute power factor** — it still carries the unknown 1/tau |
| 10 | `electronic_zT_no_lattice` | - | S^2 sigma T / kappa_e. tau cancels in this ratio, but the lattice thermal conductivity kappa_L is **missing** from the denominator. The verbose name is deliberate: this is an electronic-only upper bound, **never the final thermoelectric zT** |
| 11 | `hall_m3_C` | m^3/C | Hall coefficient R_H (sign encodes carrier type) |
| 12 | `smoothed_DOS_Ha-1_uc-1` | Ha^-1 uc^-1 | interpolated density of states at mu, per Hartree per unit cell |
| 13 | `cv_J_mol-1_K-1` | J mol^-1 K^-1 | electronic heat capacity |
| 14 | `chi_m3_mol-1` | m^3/mol | magnetic susceptibility (Pauli-like, from the DOS) |

### 2.2 `results/transport_best_power_factor.csv` — best rows only

Identical 14 columns. 14 rows: for each (temperature, carrier type) pair,
the row of `transport_full.csv` with the **largest PF/tau** (selection code:
`max(subset, key=... "power_factor_over_tau_W_m-1_K-2_s-1")` in
`boltztrap2/summarize_transport.py`). "Best" always means *best on the
7-point sampled density grid*, not a continuous optimum — the true maximum
may sit between grid points. Example row read from the file: 300 K, p-type,
`1.0000001459217128e+20 cm^-3`, S = `157.165 uV/K`,
PF/tau = `5.5623e+10 W m^-1 K^-2 s^-1`,
`electronic_zT_no_lattice` = `1.325` [calculated] — an electronic-only value;
the full zT needs tau and kappa_L, which we have not computed.

### 2.3 `results/dos_qe_vs_boltztrap2.csv` — two DOS on one grid

Source: `boltztrap2/dos_compare.py`; write-up `results/dos_comparison.md`.
Both DOS come from the same dense NSCF eigenvalues (12x12x6 mesh, 100
irreducible k-points, 140 bands — `logs/SrCu2SnS4.nscf.out`).

| Column | Unit | Meaning |
|---|---|---|
| `E_minus_EF_eV` | eV | energy relative to the Fermi level E_F = 7.1887 eV (the valence-band maximum) [calculated] |
| `QE_dosx_DOS_states_eV-1_cell-1` | states eV^-1 cell^-1 | QE `dos.x` DOS (Gaussian smearing, degauss 0.005 Ry = 0.068 eV) |
| `BoltzTraP2_DOS_states_eV-1_cell-1` | states eV^-1 cell^-1 | BoltzTraP2 native interpolated DOS |
| `BoltzTraP2_DOS_broadened_states_eV-1_cell-1` | states eV^-1 cell^-1 | the same, Gaussian-broadened to 0.068 eV for an equal-footing comparison |

### 2.4 `results/seebeck_vs_mu.csv` — Seebeck vs chemical potential

Source: `boltztrap2/plot_seebeck.py` from `boltztrap2/SrCu2SnS4.trace`
(the undoped mu scan); write-up `results/seebeck_vs_mu.md`. Covers
`|mu - E_F| <= 1.5 eV`.

| Column | Unit | Meaning |
|---|---|---|
| `mu_minus_EF_eV` | eV | chemical potential relative to E_F = 7.1887 eV |
| `S_300K_uV_K-1` … `S_900K_uV_K-1` (7 columns) | uV/K | orientationally averaged Seebeck coefficient at 300, 400, …, 900 K |

### 2.5 Convergence CSVs (per material — never reused across materials)

SrCu2SnS4 keeps them one level deeper than Rb2Cu2SnS4; note the paths.

`$M/qe/convergence/cutoff/cutoff_results.csv`:

| Column | Unit | Meaning |
|---|---|---|
| `ecutwfc_Ry` | Ry | plane-wave kinetic-energy cutoff for wavefunctions |
| `ecutrho_Ry` | Ry | cutoff for the charge density (here always 8 x ecutwfc) |
| `total_energy_Ry` | Ry | final SCF total energy at this cutoff |
| `delta_meV_per_atom_vs_max` | meV/atom | energy difference vs the highest-cutoff reference (the 100/800 Ry row is 0 by construction) |
| `pressure_kbar` | kbar | stress-derived pressure, a second convergence indicator |

Example row [calculated]: at 90/720 Ry the error is `0.1044 meV/atom` — the
production choice for this material (`logs/SrCu2SnS4.scf.out` confirms
`kinetic-energy cutoff = 90.0000 Ry`, `charge density cutoff = 720.0000 Ry`).

`$M/qe/convergence/kpoints/kpoint_results.csv`:

| Column | Unit | Meaning |
|---|---|---|
| `mesh` | - | Monkhorst-Pack grid, e.g. `4x4x2` |
| `full_kpoints` | count | points before symmetry reduction |
| `irreducible_kpoints` | count | points actually computed |
| `total_energy_Ry` | Ry | SCF energy on this mesh |
| `delta_meV_per_atom_vs_max` | meV/atom | error vs the densest tested mesh (5x5x3 here) |

Rb2Cu2SnS4 has its **own** files with the same columns at
`$R/qe/convergence/cutoff_results.csv` (90/720 Ry -> `0.0896 meV/atom`) and
`$R/qe/convergence/kpoint_results.csv` (meshes 2x4x4 … 5x9x9; 3x5x5 ->
`0.016 meV/atom`) [calculated]. The near-identical cutoff outcome is
*checked, not assumed*: convergence parameters are re-tested per material,
never carried over.

---

## 3. Unit conversions used everywhere

Conversion factors are physical constants [database]: 1 Ry = 13.6057 eV,
1 Ha = 2 Ry = 27.2114 eV, 1 bohr = 0.529177 A. Everything else in the
"worked example" column is [calculated] from repo files.

| Conversion | Factor | Worked example from this repo |
|---|---|---|
| Ry -> eV | multiply by 13.6057 | `chemical_potential_Ry = 0.606061` (`results/transport_full.csv`, 300 K n-type ~1e21 row) -> 0.606061 x 13.6057 = 8.2459 eV; minus E_F = 7.1887 eV gives mu - E_F = +1.057 eV |
| eV -> Ry | divide by 13.6057 | the QE-PBE gap 0.3445 eV (`logs/SrCu2SnS4.nscf.out`: levels 7.1887 and 7.5332 eV) = 0.02532 Ry |
| Ha -> eV | multiply by 27.2114 | `smoothed_DOS_Ha-1_uc-1 = 84.3677` (same row) -> 84.3677 / 27.2114 = 3.1005 states eV^-1 uc^-1 (dividing, because the unit is *per* energy) |
| Ha <-> Ry | 1 Ha = 2 Ry | degauss 0.005 Ry = 0.0025 Ha = 0.068 eV (`results/dos_comparison.md`) |
| V/K -> uV/K | multiply by 1e6 | `boltztrap2/SrCu2SnS4.dope.trace` stores `S[V/K] = -2.05224e-05`; `results/transport_full.csv` stores the same number as `seebeck_uV_K = -20.5224` |
| bohr^3 -> A^3 | multiply by 0.529177^3 = 0.148185 | `logs/SrCu2SnS4.scf.out`: `unit-cell volume = 3688.0115 (a.u.)^3` -> 546.506 A^3, matching `_cell_volume 546.50692043` in `structures/SrCu2SnS4.relaxed.cif` to within the log's print rounding |
| e/uc <-> cm^-3 | divide by the cell volume in cm^3 | see below |

**Electrons per unit cell to a volume density.** BoltzTraP2's trace files
count carriers per unit cell (`N[e/uc]`); experimentalists quote cm^-3. The
bridge is the relaxed cell volume [calculated]:

```text
V = 546.507 A^3 = 546.507 x 10^-24 cm^3 = 5.46507e-22 cm^3
n(cm^-3) = N(e/uc) / V(cm^3)
```

Real check against the raw and derived files:
`boltztrap2/SrCu2SnS4.dope.trace` has a 300 K row with `Ef = 0.52534 Ry`,
`N = 0.0546507 e/uc`; 0.0546507 / 5.46507e-22 = 1.0000e+20 cm^-3 — exactly
the `carrier_density_cm-3 = 1.0000001459217128e+20` p-type row of
`results/transport_full.csv`. Likewise `N = -0.546719 e/uc` ->
1.00039e+21 cm^-3, the n-type "1e21" row. Rule of thumb for this cell:
**0.0547 e/uc is about 1e20 cm^-3** — roughly one carrier per 18 unit cells.

---

## 4. Recipes

Each recipe has a Python (pandas/numpy) version and a quick shell version.
Run them from the repo root after setting `M` and `R`; for the plots,
activate the project environment
(`source "$HOME/scientific-tools/env/thermo-bt2.sh"`, the same activation
`results/seebeck_vs_mu.md` documents). Paths are quoted because of the
spaces.

### 4a. Load `transport_full.csv` and plot S vs T at fixed density

The achieved density differs slightly per temperature (section 2.1), so
filter with a tolerance instead of `== 1e20`.

```python
import pandas as pd
import matplotlib.pyplot as plt

M = "thermo_candidates/SrCu2SnS4"
df = pd.read_csv(f"{M}/results/transport_full.csv")

target = 1e20                       # nominal density, cm^-3
sel = df[(df["carrier_type"] == "p")
         & ((df["carrier_density_cm-3"] - target).abs() / target < 0.05)]
sel = sel.sort_values("temperature_K")

plt.plot(sel["temperature_K"], sel["seebeck_uV_K"], "o-")
plt.xlabel("T (K)")
plt.ylabel("S (uV/K)")
plt.title("SrCu2SnS4, p-type, ~1e20 cm^-3 (nominal target)")
plt.savefig("S_vs_T_p1e20.png", dpi=150)
```

Shell version (columns: 1 = T, 2 = type, 3 = density, 6 = S):

```bash
awk -F, 'NR>1 && $2=="p" && $3>0.95e20 && $3<1.05e20 {print $1, $6}' \
    "$M/results/transport_full.csv"
```

Expected first lines: `300 157.165`, then `400 195.116` (uV/K) [calculated].

### 4b. Best row per temperature and carrier type

The stored `results/transport_best_power_factor.csv` keeps, for each
(T, carrier type), the row with the **largest PF/tau** — that is the
selection `boltztrap2/summarize_transport.py` performs. Reproduce it:

```python
key = "power_factor_over_tau_W_m-1_K-2_s-1"
idx = df.groupby(["temperature_K", "carrier_type"])[key].idxmax()
best = df.loc[idx].sort_values(["temperature_K", "carrier_type"])

ref = pd.read_csv(f"{M}/results/transport_best_power_factor.csv") \
        .sort_values(["temperature_K", "carrier_type"])
assert (best.reset_index(drop=True) == ref.reset_index(drop=True)).all().all()
print("reproduced", len(best), "rows")   # 14
```

To rank by the electronic-only figure instead, swap the key to
`"electronic_zT_no_lattice"`. Be aware the two criteria pick **different
densities** in most groups — e.g. at 300 K p-type, the best PF/tau sits at
the ~1e20 cm^-3 grid point but the best `electronic_zT_no_lattice` at the
~1e19 cm^-3 point [calculated] — and remember both are best *on the sampled
grid* only, and `electronic_zT_no_lattice` is an electronic-only quantity
(no kappa_L), never the final zT.

Shell one-liner for one group (largest column 9 among 300 K p rows):

```bash
awk -F, 'NR>1 && $1==300 && $2=="p" && $9>m {m=$9; row=$0} END {print row}' \
    "$M/results/transport_full.csv"
```

### 4c. Recompute PF/tau and verify the stored column

PF/tau = S^2 x (sigma/tau). S must go back to V/K first:

```python
pf = (df["seebeck_uV_K"] * 1e-6) ** 2 * df["sigma_over_tau_ohm-1_m-1_s-1"]
rel = ((pf - df["power_factor_over_tau_W_m-1_K-2_s-1"]).abs()
       / df["power_factor_over_tau_W_m-1_K-2_s-1"])
print(rel.max())        # 5.8e-16 over all 98 rows: floating-point identical
```

Hand check on one row (300 K, n-type, ~1e21 cm^-3): (20.5224e-6 V/K)^2 x
2.30932e+19 ohm^-1 m^-1 s^-1 = 9.7261e+9 W m^-1 K^-2 s^-1, matching the
stored `9726137682.12` [calculated]. This is a *consistency* check between
columns; it does not make PF/tau an absolute power factor — the unknown tau
is still in there.

### 4d. Verify the 210-electron DOS integral

`qe/dos/SrCu2SnS4.dos` has three columns —
`E (eV)`, `dos(E)` in states/eV, `Int dos(E)` in states — and a header line
ending `EFermi =    7.189 eV`. The cumulative integral of the DOS up to E_F
must equal the number of electrons QE put in the cell.

```bash
# last cumulative-integral value at or below E_F = 7.189 eV
awk 'NR>1 && $1 <= 7.189 {n = $3} END {print n}' "$M/qe/dos/SrCu2SnS4.dos"
#  -> 0.2100E+03  (= 210.0 electrons)

grep "number of electrons" "$M/logs/SrCu2SnS4.scf.out"
#  -> number of electrons       =       210.00
```

Both give 210 [calculated] — the DOS integrates to exactly the electron
count. (`results/dos_comparison.md` records the same check: QE `dos.x`
integrates to 210.0 over all 105 occupied bands; the BoltzTraP2 loader keeps
only 62 occupied bands, so its window integrates to 124.0 — a windowing
artifact, not missing physics.)

### 4e. grep recipes for QE logs

QE logs are long (thousands of lines); these four lines answer most
questions. Real outputs shown as comments [calculated].

```bash
# 1. Final converged total energy: the line starting with "!"
grep '^!' "$M/logs/SrCu2SnS4.scf.out"
#   !    total energy              =   -2269.30123715 Ry

# 2. Band edges / gap (fixed occupations; from the dense NSCF)
grep 'highest occupied' "$M/logs/SrCu2SnS4.nscf.out"
#   highest occupied, lowest unoccupied level (ev):  7.1887  7.5332
#   -> QE-PBE gap = 0.3445 eV

# 3. Pressure at every relaxation step (should decay toward ~0)
grep 'P=' "$M/logs/SrCu2SnS4.relax.out"
#   P= 3.35, 1.94, 0.69, -0.15, -0.22 kbar over the BFGS steps,
#   then -0.20 in the final re-SCF

# 4. Timing: how long did the run take
grep 'PWSCF.*WALL' "$M/logs/SrCu2SnS4.scf.out"
#   PWSCF        :   7m 3.07s CPU   7m 7.82s WALL
```

The same recipes already work on `$R/logs/Rb2Cu2SnS4.scf.out` (recipe 1
gives `-1568.23828522 Ry`, and `number of electrons = 156.00` [calculated]);
recipe 2 on `$R/logs/Rb2Cu2SnS4.nscf.out` now runs on its finished NSCF and
gives a sampled QE-PBE gap of `0.7811 eV` [calculated]
(`$R/results/workflow_summary.md`) — larger than SrCu2SnS4's, and still a
PBE gap that underestimates the true value.

### 4f. Read a `.trace` file with numpy and plot S(mu)

The raw mu-scan trace `boltztrap2/SrCu2SnS4.trace` is whitespace-separated
with a `#` header naming the columns:
`Ef[Ry]  T[K]  N[e/uc]  DOS(ef)[1/(Ha*uc)]  S[V/K]  sigma/tau0[1/(ohm*m*s)]
RH[m**3/C]  kappae/tau0[W/(m*K*s)]  cv[J/(mol*K)]  chi[m**3/mol]`.

```python
import numpy as np
import matplotlib.pyplot as plt

M = "thermo_candidates/SrCu2SnS4"
d = np.loadtxt(f"{M}/boltztrap2/SrCu2SnS4.trace", comments="#")

RY_EV = 13.6057          # [database] conversion constant
EF_EV = 7.1887           # [calculated] QE NSCF VBM, logs/SrCu2SnS4.nscf.out

mu = d[:, 0] * RY_EV - EF_EV      # Ef[Ry] -> mu - E_F in eV
T,  S = d[:, 1], d[:, 4] * 1e6    # S[V/K] -> uV/K

for temp in (300, 600, 900):
    m = T == temp
    plt.plot(mu[m], S[m], label=f"{temp} K")
plt.axvspan(0, 0.3445, color="0.9")          # shade the QE-PBE gap
plt.xlim(-1.5, 1.5); plt.xlabel("mu - E_F (eV)"); plt.ylabel("S (uV/K)")
plt.legend(); plt.savefig("S_vs_mu_quick.png", dpi=150)
```

This is a minimal version of `boltztrap2/plot_seebeck.py`, which produced
`results/seebeck_vs_mu.png`/`.csv`.

---

## 5. Sanity-check habits

Every derived file in this repo was cross-checked before being reported.
Copy these habits; each one below is a real check already recorded in the
repo, with its actual outcome.

1. **Tensor average vs the scalar trace.** BoltzTraP2 writes scalar
   orientational averages (`.trace`) *and* full 3x3 tensors (`.condtens`).
   Recompute the scalar as (S_xx + S_yy + S_zz)/3 from the tensor file and
   compare. Recorded outcome: maximum relative difference `1.2e-5`
   [calculated] — `results/seebeck_vs_mu.md`, implemented in
   `boltztrap2/plot_seebeck.py`. If this ever disagrees, you are reading the
   wrong columns.

2. **Charge neutrality at E_F.** In the undoped mu scan, the relative
   carrier count must cross zero at mu = E_F (no added carriers there).
   Recorded outcome: residual `+0.018 e/uc` at 300 K, attributed to grid
   interpolation [calculated] — `results/seebeck_vs_mu.md`. A large residual
   would mean E_F or the electron count is wrong.

3. **Two independent runs, one number.** The doped run (`.dope.trace`) and
   the mu scan (`.trace`) are separate BoltzTraP2 integrations; where they
   describe the same state they must agree. Recorded outcome: at 300 K,
   p-type 1e20 cm^-3, the mu scan gives `157.4 uV/K` vs `157.2 uV/K` in the
   doped run [calculated] — `results/seebeck_vs_mu.md` (the stored
   full-precision value in `results/transport_full.csv` is `157.165`).
   Agreement to ~0.1% across independent code paths is the goal.

4. **The DOS must integrate to the electron count.** Recipe 4d: the
   cumulative integral of `qe/dos/SrCu2SnS4.dos` at E_F is 210.0, equal to
   `number of electrons = 210.00` in `logs/SrCu2SnS4.scf.out` [calculated].
   Any mismatch means a wrong Fermi level, wrong smearing, or missing bands.

5. **Pseudo-valence arithmetic must predict the electron count.** Each
   pseudopotential contributes a fixed valence charge, printed in the SCF
   log (`logs/SrCu2SnS4.scf.out`: Sr 10, Cu 11, Sn 14, S 6 electrons). The
   cell holds 24 atoms = 3 formula units of SrCu2SnS4, so
   3x10 + 6x11 + 3x14 + 12x6 = 210 — exactly QE's 210.00. The same habit was
   applied to Rb2Cu2SnS4 before trusting its SCF: its log lists Rb 9, Cu 11,
   Sn 14, S 6, and the 2-formula-unit cell gives 4x9 + 4x11 + 2x14 + 8x6 =
   156; the log shows `156.00 electrons -> 78 occupied bands` [calculated] —
   `$R/logs/Rb2Cu2SnS4.scf.out`, recorded in `$R/WORKLOG.md`. Do this
   *before* the expensive runs: a wrong pseudopotential shows up here
   immediately.

A sixth habit is the whole of section 2.5: **convergence evidence is
per-material**. SrCu2SnS4's 90/720 Ry and 5x5x3 SCF mesh were re-derived for
Rb2Cu2SnS4 from its own `cutoff_results.csv` / `kpoint_results.csv`, not
assumed.

---

## 6. Plotting conventions used here

Look at `results/dos_qe_vs_boltztrap2.png` and `results/seebeck_vs_mu.png`
(sources: `boltztrap2/dos_compare.py`, `boltztrap2/plot_seebeck.py`) and
copy their conventions:

- **Energy axes are relative to E_F.** The x-axis is `E - E_F (eV)` or
  `mu - E_F (eV)` with E_F = 7.1887 eV [calculated], which for this
  fixed-occupation insulator equals the valence-band maximum. Absolute QE
  energies (like 7.1887 eV itself) are arbitrary-zero numbers; differences
  are the physics.
- **The gap is shaded.** Both scripts shade `[0, 0.3445] eV` with a light
  gray `axvspan` — the QE-PBE gap [calculated]. Readers instantly see which
  features live inside the gap (e.g. the 300 K S(mu) extrema of
  `+644 / -548 uV/K` at `mu - E_F = +0.151 / +0.241 eV` sit inside it, where
  a real sample is intrinsic — `results/seebeck_vs_mu.md`). Remember PBE
  underestimates gaps, so the shading marks the *calculated* gap, not an
  experimental one.
- **Units live in the axis labels**, always: `S (uV/K)`,
  `DOS (states eV^-1 cell^-1)`, `T (K)`. A plot whose numbers cannot be
  traced to a unit is not a result.
- **State what the scalar is.** Plotted S is the orientational average of
  the tensor (check 1 in section 5); single-crystal S_xx vs S_zz differ, and
  the figure write-up says so (`results/seebeck_vs_mu.md`, Limitations).
- **Temperatures get a labeled legend** (300–900 K), one curve per
  temperature, consistent across figures.
- **Figures pair with a write-up and a CSV.** Every PNG in `results/` has a
  same-name `.csv` (the plotted numbers, machine-readable) and an `.md`
  (method, checks, limitations). Keep that triple intact when you add plots.

---

## Scientific-rigor review of this document

- Every number above was read from the cited repo file in this session
  (CSV headers and rows, grepped log lines, trace rows) or recomputed from
  them and re-verified (the volume/density conversions, the PF/tau check,
  the DOS integral, the best-row reproduction, the valence arithmetic). The
  conversion factors 13.6057 / 27.2114 / 0.529177 are standard constants
  [database]; nothing is quoted from memory.
- House rules respected: PF/tau is described only as a tau-carrying ratio,
  never an absolute power factor; `electronic_zT_no_lattice` is flagged as
  electronic-only (tau cancels in it, but kappa_L is missing), never the
  final zT; all runs are scalar-relativistic with no explicit SOC; "best"
  always means best on the sampled grid; convergence parameters are shown as
  re-derived per material.
- Rb2Cu2SnS4: its first pass is complete, so its convergence, relaxation,
  final-SCF, gap, and transport numbers are all quoted from its own files
  (convergence CSVs, `logs/Rb2Cu2SnS4.scf.out`/`.nscf.out`,
  `results/workflow_summary.md`, and `results/transport_full.csv` /
  `transport_best_power_factor.csv`); its sampled QE-PBE gap `0.7811 eV` and
  its transport numbers (e.g. peak sampled `electronic_zT_no_lattice` 6.419 at
  900 K, p-type, ~1e21 cm^-3) are electronic-only, best-on-the-sampled-grid,
  no-SOC values — never an absolute power factor or the final zT.
- Limitations: the shell recipes assume the current file layouts (SrCu2SnS4
  and Rb2Cu2SnS4 store their convergence CSVs at different depths, as
  stated); the bohr^3 -> A^3 example matches the CIF volume only to the
  print precision of the QE log; recipe outputs were verified against
  SrCu2SnS4 files only.

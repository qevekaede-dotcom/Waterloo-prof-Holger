# Work log: Rb2Cu2SnS4 first-pass workflow

Lab-notebook record for this material. Newest entry at the bottom.

---

## 2026-07-02 — starter inputs and cutoff convergence launched

**Context.** Third candidate in the queue (rank 1 in the renewed list);
started after the SrZrS3 first pass completed so the machine runs one heavy
job at a time.

**1. Structure.** `structures/Rb2Cu2SnS4.cif` = mp-18006, Ibam, given as the
18-atom primitive cell (Rb4 Cu4 Sn2 S8; a=b=c=9.49 A with non-orthogonal
angles). Reciprocal-lattice lengths 0.70/1.23/1.26 A^-1, so balanced k-meshes
need roughly half as many points along the first axis.

**2. Starter inputs** were generated earlier with the sanctioned
`scripts/make_qe_inputs.py`. Pseudos are mixed: Rb norm-conserving ONCV,
Cu PAW, Sn/S ultrasoft - dual 8 (ecutrho = 8 x ecutwfc) is required by the
PAW/ultrasoft members.

**3. Cutoff test design** (own test): 50-100 Ry against the 100 Ry
reference (SSSP suggests 90/720, Cu-driven, same situation as SrCu2SnS4);
fixed 2x4x4 mesh (spacing 0.35/0.31/0.32 A^-1), fixed occupations,
conv_thr 1e-8, stress printed. Series launched in the background.

**Next.** Extract `cutoff_results.csv`, select the cutoff, then the k-point
test (mesh list scaled to the reciprocal shape), vc-relax, final SCF, dense
NSCF, and BoltzTraP2 on the same 300-900 K / 1e19-1e21 cm^-3 grid.

---

## 2026-07-02 — cutoff result; k-point test launched

**1. Cutoff result.** All six runs JOB DONE. Deltas vs the 100 Ry reference:
80 -> 0.509, **90 -> 0.0896**, meV/atom; pressure plateau 2.5-2.7 kbar from
60 Ry. **Selected 90/720 Ry** - essentially the same convergence point as
SrCu2SnS4 (0.104 meV/atom at 90 Ry), which is physically expected since the
same hard Cu PAW pseudopotential dominates both materials. Record:
`qe/convergence/cutoff_results.csv`.

**2. Runtime anomaly investigated, physics clean.** ecut_80 showed 1h56m
wall but only 8m27s CPU (ecut_90: 1h37m wall, 17m26s CPU) while all six runs
took a uniform 17-18 SCF iterations. The wall/CPU gap means the laptop was
suspended or heavily loaded during those runs, not that the SCF struggled -
the energy-vs-cutoff curve is smooth and fixed occupations converged
normally everywhere.

**3. k-point test launched** at 90/720 Ry: meshes 2x4x4, 3x5x5, 4x7x7,
5x9x9 (reference), scaled to the reciprocal ratios ~1:1.76:1.81 so the
spacing stays balanced. Extraction mirrors the standard CSV format.

**Next.** Choose relax + final-SCF meshes, then vc-relax onward.

---

## 2026-07-02 — k-point series re-parallelized (4 -> 12 ranks)

The overnight runs were heavily throttled (laptop sleep + background
scheduling): k_2x4x4 took 3.3 h and k_3x5x5 6.0 h wall, versus ~17 min CPU
for the same-size run in the daytime cutoff test. SCF iteration counts were
uniform (17-18) - a machine effect, not a physics problem.

With the user's go-ahead (M5 Pro, 18-core CPU, 24 GB unified memory), the
running k_4x7x7 was stopped and the series relaunched with
`QE_NP=12 QE_NK=2` (2 k-point pools x 6-way plane-wave parallel) wrapped in
`caffeinate -i` to block idle sleep for the duration of the job. Pool count
was capped at 2 because pools replicate memory: the 4-rank single-pool run
used ~6.8 GB total, so 4 pools would have exceeded 24 GB, while 2 pools sit
around 10-14 GB. Completed meshes were skipped by the run script; k_4x7x7
restarted from scratch. `run_kpoint_convergence.sh` gained the same QE_NK
support the production scripts already had. Expected ~2.5-3x speedup.
(The 20-core GPU is unused: QE GPU acceleration is CUDA/NVIDIA-only.)

At 12 ranks the speedup was confirmed: k_4x7x7 finished in 2088 s and
k_5x9x9 in 4817 s.

---

## 2026-07-03 — k-point result; meshes chosen; vc-relax launched

**1. k-point result** (`qe/convergence/kpoint_results.csv`). Deltas vs the
5x9x9 (203 irreducible k) reference: 2x4x4 -> 0.175, 3x5x5 -> 0.016,
4x7x7 -> 0.0015 meV/atom. This material converges unusually fast with
k-points.

**2. Meshes chosen**, same protocol as the other two materials (relax mesh
inside the ~0.25 meV/atom band, final SCF one tier denser):
  - vc-relax: **2x4x4** (0.175 meV/atom; cf. SrCu2SnS4 0.253, SrZrS3 0.286)
  - final SCF: **3x5x5** (0.016 meV/atom)

**3. vc-relax launched** at 90/720 Ry + 2x4x4 from the mp-18006 primitive
cell (`prepare_relax.py` / `run_relax.sh`, thresholds as before:
etot 1e-5 Ry, force 1e-3 Ry/bohr, pressure 0.5 kbar, BFGS, cell_dofree all,
fixed occupations), 12 ranks / 2 pools under `caffeinate -i`;
log -> `logs/Rb2Cu2SnS4.relax.out`.

**Next.** Health checks (criteria met, symmetry still Ibam, sane volume
drift), extract relaxed CIF, final SCF at 3x5x5 (expect 156 electrons ->
78 occupied bands by pseudo arithmetic), dense NSCF, BoltzTraP2.

---

## 2026-07-03 — vc-relax complete; final SCF launched

**1. vc-relax result** (`logs/Rb2Cu2SnS4.relax.out`, 49m48s wall, 12 ranks):
BFGS converged in 8 steps / 9 SCF cycles; all three criteria met; final
pressure 0.07 kbar; final enthalpy -1568.2380702 Ry.

**2. Structure check** (extract_relaxed_structure.py, 10 frames): symmetry
**kept Ibam (#72)**; volume 446.410 -> 450.561 A^3 (**+0.93%**) - slightly
larger drift than SrCu2SnS4 (+0.48%) / SrZrS3 (+0.63%) but still normal for
PBE. Relaxed CIF -> `structures/Rb2Cu2SnS4.relaxed.cif`.

**3. Final SCF launched** at 90/720 Ry, 3x5x5, on the relaxed structure
(12 ranks / 2 pools, caffeinate). Density -> `qe/tmp/final/`.

**Next.** Verify 156 electrons / 78 occupied bands, size the dense NSCF
(nbnd ~105 with ~35% headroom; mesh matched to the ~0.08 A^-1 spacing
standard of the other two materials), then BoltzTraP2.

---

## 2026-07-03 — final SCF complete; dense NSCF launched

**1. Final SCF** (`logs/Rb2Cu2SnS4.scf.out`, 13m14s wall, 12 ranks): JOB
DONE; **156.00 electrons -> 78 occupied bands** (matches the pseudo valence
arithmetic 4x9 Rb + 4x11 Cu + 2x14 Sn + 8x6 S); 38 irreducible k-points at
3x5x5; highest occupied level 6.2203 eV; total energy -1568.23828522 Ry.

**2. Dense NSCF sizing** (reasoning in `qe/prepare_nscf.py`):
  - nbnd = **105** (78 occupied + 27 empty, ~35% headroom);
  - mesh = **8x14x14** -> spacing 0.088/0.088/0.090 A^-1, ~10% coarser than
    the 0.08 standard: in this primitive-cell orientation QE's automatic
    grids reduce only ~2x by symmetry, so matching 0.08 exactly (9x16x16,
    ~1150 irreducible points) would about double the cost for a marginal
    gain. Deviation stated here and covered by the standing
    transport-mesh-convergence caveat shared by all three materials.

**3. NSCF launched** (12 ranks / 2 pools, caffeinate, disk_io=nowf,
diago_full_acc). Expect ~780 irreducible points; the gap number comes from
this run.

**Next.** Read VBM/CBM/gap, fix-and-run the BoltzTraP2 template (same three
bugs expected as SrZrS3's), summarize, then the three-material comparison.

---

## 2026-07-03 — dense NSCF complete; BoltzTraP2 launched

**1. Dense NSCF** (`logs/Rb2Cu2SnS4.nscf.out`, 5h27m wall, 12 ranks / 2 pools):
JOB DONE; 788 irreducible k-points (8x14x14); 105 bands / 156 electrons;
VBM 6.2402 eV, CBM 7.0213 eV -> sampled PBE gap **0.7811 eV** - the largest
of the three candidates (SrCu2SnS4 0.3445, SrZrS3 0.6096).

**2. BoltzTraP2 template had the same three bugs as SrZrS3's** - fixed in
`boltztrap2/run_bt2.sh` before running: qe_source path missing `/final`; bare
`btp2` CLI (NumPy 2 crash) -> `btp2_compat.py` shim (copied); half-open
`300:900:100` range and through-zero `-1e21:1e21:1e20` doping -> `300:1000:100`
and the explicit 14-level list. The pre-made template ships with these bugs
for every material; this is now the second confirmation.

**3. BoltzTraP2 launched** (`BT2_NP=8`, caffeinate): interpolate -m 5 ->
integrate -> dope; `summarize_transport.py` adapted from the SrZrS3 version
(header identifiers/meshes swapped, transport math identical).

**Next.** Summarize -> `results/`; then update the three-material comparison
in `learning/05_comparing_materials.md`, `WORKFLOW_EXPLAINED.md` section 6,
`Roy_task_status.md`, and this material's README/CLAUDE.

---

## 2026-07-03 — Seebeck(mu) figure for the Roy report

`boltztrap2/plot_seebeck.py` cloned from the verified SrCu2SnS4 version
(gap shading 0.7811 eV, window +/-1.4 eV) -> `results/seebeck_vs_mu.png/.csv`.
Cross-checks: trace-vs-condtens diag average 1.72e-5; dope-vs-scan S at 300 K
p 1e20 cm^-3: 331.5 vs 331.6 uV/K. Honest flag: the charge-neutrality
interpolation residual at E_F is +0.211 e/uc (vs +0.005/+0.018 for the other
two) because the valence DOS is high and steep at the VBM (flat bands), so
N(mu) rises sharply within one mu-grid step; the dope-based check confirms the
S curves are unaffected. Curated copy in
`third step result (three-material first pass)/READY_TO_ATTACH/`.

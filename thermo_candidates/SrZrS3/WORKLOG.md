# Work log: SrZrS3 first-pass workflow

Lab-notebook record for this material. Newest entry at the bottom.
The step-result package for Roy comes later, once there is something to send.

---

## 2026-07-02 — starter inputs and cutoff convergence

**Context.** Roy's go-ahead: "you're good to proceed to the other crystals'
convergence." SrZrS3 is second in the queue after SrCu2SnS4.

**1. Starter inputs.** Ran the sanctioned generator
(`scripts/make_qe_inputs.py`) on `structures/SrZrS3.cif` (mp-558760 needle
phase, Pnma, 20 atoms, a=3.84 b=8.59 c=14.00 A - NOT the mp-5193 perovskite
polymorph). Verified all three SSSP pseudos exist locally (Sr/Zr/S, all
ultrasoft). Rb2Cu2SnS4 starter inputs were generated at the same time; its
convergence waits until this material's runs finish so the machine is not
oversubscribed.

**2. Cutoff test design.** Own test, nothing reused from SrCu2SnS4:
30-60 Ry (SSSP suggests 40), dual 8 throughout (all-USPP), fixed 4x2x1 mesh
(k-spacing 0.37-0.45 A^-1 scaled to this cell; the k error cancels in the
differences), fixed occupations, conv_thr 1e-8, stress printed.

**3. Cutoff result.** All six runs JOB DONE (32-114 s each, 4 MPI ranks).
Energies decay monotonically toward the 60 Ry reference; pressure plateaus at
3.4-3.55 kbar from 40 Ry. Deltas vs 60 Ry: 40 -> 0.539, 45 -> 0.262,
50 -> 0.160 meV/atom. **Selected 50/400 Ry** - same per-SCF cost as 45 Ry and
comfortably inside the acceptance band used for SrCu2SnS4.
Record: `qe/convergence/cutoff_results.csv` (same columns as the SrCu2SnS4
record in the first-step package).

**4. k-point test launched.** At 50/400 Ry: meshes 4x2x1, 6x3x2, 8x4x2,
10x5x3 (reference), same SCF settings. Extraction script mirrors the
SrCu2SnS4 CSV format. Running in the background at the time of this entry.

**Next.** Choose relaxation + final-SCF meshes from `kpoint_results.csv`,
then vc-relax, final SCF, dense NSCF (band count set after the SCF), and
BoltzTraP2 with the same 300-900 K / 1e19-1e21 cm^-3 grid for comparability.

---

## 2026-07-02 — k-point result; meshes chosen; vc-relax launched

**1. k-point result.** All four runs JOB DONE (86-411 s, 4 MPI ranks).
Deltas vs the 10x5x3 reference: 4x2x1 -> 2.885, 6x3x2 -> 0.286,
8x4x2 -> 0.036 meV/atom. Record: `qe/convergence/kpoint_results.csv`.

**2. Meshes chosen**, mirroring the SrCu2SnS4 protocol (relax mesh in the
~0.25 meV/atom band, final SCF one tier denser):
  - vc-relax: **6x3x2** (0.286 meV/atom; SrCu2SnS4's relax mesh sat at 0.253)
  - final SCF: **8x4x2** (0.036 meV/atom)

**3. vc-relax launched.** `qe/prepare_relax.py` written with this material's
converged 50/400 Ry + 6x3x2 and the same thresholds as SrCu2SnS4
(etot 1e-5 Ry, force 1e-3 Ry/bohr, pressure 0.5 kbar, BFGS, cell_dofree all,
fixed occupations). Started from the mp-558760 database structure via
`qe/run_relax.sh` (8 ranks, 2 k-pools); log -> `logs/SrZrS3.relax.out`.

**Next.** After relaxation: extract relaxed CIF, final SCF at 8x4x2, count
electrons/bands for the dense NSCF, then BoltzTraP2 (300-900 K,
+/-1e19-1e21 cm^-3).

---

## 2026-07-02 — vc-relax complete; final SCF launched

**1. vc-relax result** (`logs/SrZrS3.relax.out`, 35m47s wall on 8 ranks):
BFGS converged in 13 steps / 14 SCF cycles; all three criteria met
(energy < 1e-5 Ry, force < 1e-3 Ry/bohr, cell < 0.5 kbar); final
pressure -0.03 kbar; final enthalpy -969.0402428 Ry.

**2. Structure check** (extract_relaxed_structure.py, 15 frames):
symmetry **kept Pnma (#62)**; a: 3.8402 -> 3.8385 A (-0.04%),
b: 8.5868 -> 8.6412 A (+0.63%), c: 13.9965 -> 14.0030 A (+0.05%);
volume 461.535 -> 464.463 A^3 (**+0.63%**) - healthy PBE drift, same scale
as SrCu2SnS4's +0.48%. Relaxed CIF -> `structures/SrZrS3.relaxed.cif`.

**3. Final SCF launched** at 50/400 Ry, 8x4x2, on the relaxed structure
(`qe/prepare_final_scf.py` + `run_final_scf.sh`, density -> `qe/tmp/final/`).

**Next.** Read electron/band counts from the SCF log, size the dense NSCF
(nbnd with ~1/3 empty-band headroom, mesh ~2x the SCF mesh per axis), run
NSCF, then BoltzTraP2.

---

## 2026-07-02 — final SCF complete; dense NSCF launched

**1. Final SCF** (`logs/SrZrS3.scf.out`, 3m28s wall, 8 ranks): JOB DONE;
**160.00 electrons -> 80 occupied bands** (matches the pseudo valence
arithmetic 4x10 Sr + 4x12 Zr + 12x6 S); 30 irreducible k-points at 8x4x2;
highest occupied level 7.8437 eV; total energy -969.04063942 Ry. Ground-state
density stored in `qe/tmp/final/SrZrS3.save/`.

**2. Dense NSCF sizing** (documented in `qe/prepare_nscf.py`):
  - nbnd = **108** (80 occupied + 28 empty, ~35% headroom - same ratio as
    SrCu2SnS4's 105 -> 140);
  - mesh = **20x10x6** -> k-spacing 0.082/0.073/0.075 A^-1 on the relaxed
    cell, deliberately matching the SrCu2SnS4 dense-NSCF spacing standard
    (12x12x6 -> 0.082/0.082/0.067 A^-1). The smaller SrZrS3 cell has a larger
    Brillouin zone, so equal spacing genuinely needs more k-points.

**3. NSCF launched** (`run_nscf.sh`, 8 ranks, 4 k-pools, disk_io=nowf,
diago_full_acc). The gap number comes from this run (the SCF only computed
the 80 occupied states, so no lowest-unoccupied level was printed there).

**Next.** After NSCF: read VBM/CBM/gap, then BoltzTraP2 interpolate ->
integrate -> dope (300-900 K, +/-1e19-1e21 cm^-3, multiplier 5) and the
transport summaries, mirroring the SrCu2SnS4 scripts.

---

## 2026-07-02 — dense NSCF + BoltzTraP2 complete; first pass done

**1. Dense NSCF** (`logs/SrZrS3.nscf.out`, 1h15m wall, 8 ranks / 4 pools):
JOB DONE; 264 irreducible k-points (20x10x6); 108 bands / 160 electrons;
VBM 7.8437 eV (matches the SCF value), CBM 8.4534 eV -> sampled PBE gap
**0.6097 eV**.

**2. The pre-made BoltzTraP2 template had three bugs**, fixed in
`boltztrap2/run_bt2.sh` before running:
  - `qe_source` pointed at `qe/tmp/SrZrS3.save` instead of
    `qe/tmp/final/SrZrS3.save`;
  - it called the bare `btp2` CLI, which crashes under NumPy 2 - switched to
    the `btp2_compat.py` shim (copied from SrCu2SnS4);
  - `300:900:100` is a half-open range that stops at 800 K, and the
    `-1e21:1e21:1e20` doping syntax would sweep through zero - replaced with
    `300:1000:100` and the explicit 14-level list used for SrCu2SnS4.

**3. BoltzTraP2 run**: interpolate `-m 5` -> `SrZrS3.bt2`; integrate + dope ->
trace/condtens files; logs in `logs/SrZrS3.bt2.*.log`.

**4. Summaries** (`boltztrap2/summarize_transport.py`, adapted from
SrCu2SnS4): `results/transport_full.csv` (98 rows = 14 densities x 7 T),
`results/transport_best_power_factor.csv`, `results/workflow_summary.md`.
Loader gap 0.6096 eV, consistent with the NSCF log value (rounding).

**5. Key findings** (sampled grid, CRTA, no SOC):
  - by electronic zT_e the **n-type best exceeds the p-type best at every
    sampled temperature** (top point: zT_e 1.625 at 700 K, n-type
    1e20 cm^-3, S = -173.8 uV/K);
  - by PF/tau alone, p-type overtakes at >= 500 K, driven by the 1e21 cm^-3
    point, but with much lower zT_e (kappa_e grows with doping) - quote both
    metrics, never one;
  - carrier preference is **opposite to SrCu2SnS4** (p-favored): same
    recipe, different physics.

**First pass complete.** Standing caveats: transport-mesh convergence not
checked (same as SrCu2SnS4), no SOC, no tau / kappa_L.

---

## 2026-07-03 — Seebeck(mu) figure for the Roy report

`boltztrap2/plot_seebeck.py` cloned from the verified SrCu2SnS4 version
(gap shading 0.6096 eV, window +/-1.2 eV) -> `results/seebeck_vs_mu.png/.csv`.
Cross-checks: trace-vs-condtens diag average 1.65e-5; N(E_F) residual
+0.005 e/uc; dope-vs-scan S at 300 K n 1e20 cm^-3: -91.1 vs -91.2 uV/K.
Curated copy in `third step result (three-material first pass)/READY_TO_ATTACH/`.

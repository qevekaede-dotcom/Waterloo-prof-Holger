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

---

## 2026-09-13 — frozen 3.70-A count evidence and reviewed 3.554-A prediction

The completed remote count-only preflight at 3.70 A produced 1003 displacement
supercells for both 2x1x1 and 3x1x1, above the configured hard cap of 800. Five
raw source files were copied without byte changes into
`phono3py/evidence/3p70A_count_only/`; `SHA256SUMS` and `manifest.json` bind
their names, sizes, hashes, staging source, and original remote provenance.
This is preserved count/geometry evidence, not FC3, phonon, or kappa evidence.

Read-only thresholding of the frozen 2x1x1 3.70-A YAML identified the open
shell gap from 3.526178139 to 3.582091586 A. The midpoint candidate
3.5541348625 A (6.71634150010947 bohr) predicts 787 files: 25 singles and 762
second-displacement IDs in 147 included pair groups, 122 of them nonzero,
across exactly 12 positive included shells. The config now records the full
included-shell group/ID multiplicities and the complete three-shell set newly
excluded between the candidate and the 3.70-A source cutoff. Runtime checks use
a 5e-8-A absolute clustering tolerance and fail closed on extra, missing, or
redistributed shells.

Strict limitation: 787 is a prediction from frozen source evidence, not a new
phono3py result. The candidate is enumerated only for 2x1x1 count-only and is
blocked from both pilot and production force settings. A fresh count-only run
must reproduce the signed contract and then receive separate scientific review;
even exact count/shell agreement would not establish FC3 cutoff or supercell
convergence and would not authorize production.

After an initial independent `FIX`, the runtime contract was tightened to
require the complete newly excluded shell set in `(3.5541348625, 3.70] A`, not
merely the presence of three expected shells.  A new 3.65-A shell now fails;
an irrelevant 3.75-A shell remains outside that source-cutoff interval.  The
final fresh review returned `SHIP`: 309 tests passed with one optional-spglib
skip, both material configs validated healthy, all five raw hashes and byte
comparisons passed, and no `READY_TO_ATTACH/` file changed.

---

## 2026-09-13 — targeted 3.5541348625-A count reproduced and archived

The reviewed commit `5733f0cc486fa806ca2f6a1a653cd21541f70403` was deployed
as an exact clean Nibi clone.  A fresh run imported the already accepted
SrZrS3 structure with unchanged unit-cell SHA-256
`fdae2066bdf829fbeeca6685880f25e6354ce94fa03e82e5de53bb05ab6f0db8`.
Its signed preflight submitted only
`sr_fc3_2x1x1__sr_cutoff_3p5541348625A` under attempt
`20260913T144259Z-preflight-2f0ab287` and job `21850149`.  Slurm reports
`COMPLETED/0:0` in 10 seconds; the wrapper and `phono3py-init` process both
returned zero.

The actual YAML and filesystem contain exactly 787 generated inputs: 25
singles and 762 second-displacement IDs, with 147 included pair groups and 122
nonzero groups.  The runtime comparison reproduced all 12 included positive
shells, their multiplicities, and the complete newly excluded three-shell set
without mismatch.  The 787 actual filenames equal the YAML included-ID set;
their canonical ID-list SHA-256 is
`95f8de9fb1df32992b09d2f723890fbca2bcbb20f5623d9287b7b93237720f0b`.

The byte-preserved run/submission/result records, Slurm receipt, and a
per-input checksum list are under
`phono3py/evidence/3p5541348625A_count_only/`.  All 787 reproducible QE input
files are deliberately not duplicated in Git.  Fresh scientific review
returned `SHIP` only for the count gate.  The targeted scope is complete, but
the full configured preflight is not; `selection_eligible`, force-pilot
authorization, and production eligibility all remain false.  The cutoff uses
about 92.6% of the 2x1x1 inscribed radius, so explicit excluded-shell and
larger-supercell tests remain mandatory before any production decision.

---

## 2026-09-14 — exact-six initial force pilot prepared, not submitted

An independently reviewed release was prepared to test only timing,
repeatability, and whether a small incremental force response is resolvable.
It fixes the six task identities to `[0, 0, 1, 3, 1, 3]`: two pristine SCFs,
one single-displacement SCF and its independent duplicate, and one
double-displacement SCF and its duplicate.  The settings are 80/640 Ry,
`conv_thr=1e-10`, 3x3x3, `nosym/noinv`, 32 MPI ranks, two hours, and at most
two concurrent tasks.  The 768-core-hour reservation includes the one allowed
technical retry for each task; it is a ceiling, not measured usage.

The first clean-checkout preparation at `25a5869` exposed a real adapter bug
before any one-time release consumption or force-budget reservation.  The
accepted QE input lists `ATOMIC_SPECIES` as `S,Sr,Zr`, whereas phono3py's
equivalent fragments list `Sr,Zr,S`.  QE binds species by label, so card-row
order is not physical identity.  Existing code nevertheless compared an
ordered list and failed with `generated species, pseudopotential, mass or atom
count mismatch`.  The unconsumed release
`initial-six-25a5869/release.json` is preserved with SHA-256
`c0891eae24f32474e2a98de438eeb2d426e3d9d7b0eaa87dcfbfb3920446bc70`;
that base has no dataset, consumption claim, or budget reservation.

Commit `964eafc06a6f08507ae559c8fde78a0d9fe290db` corrected only this
validation rule: `ATOMIC_SPECIES` row order may differ, while the unique label
set and every label's exact mass and pseudopotential filename must still
match.  Duplicate, missing/extra, mass-drifted, and pseudopotential-drifted
species remain fail-closed.  The full local suite passed 415 tests with one
pre-existing optional-spglib skip, and a fresh independent review returned
`SHIP`.

The corrected exact clean Nibi checkout then replayed all 787 archived
count-only inputs successfully and prepared the one-time six-geometry bundle:

- checkout: `/scratch/yuhansun/codex-run-sr-initial-964eafc`;
- run: `/scratch/yuhansun/phono3py-runs/20260913-sr-count-5733f0c/SrZrS3`;
- release SHA-256: `841a8e70cf72b6b3723b42a9ad53a2fb7deb85dd6984657d39ceca1db4c620a8`;
- consumption identity: `3ce030de419a1a9f3e9921df9eac1da7ed21621bc2226c2e3edb444395866b04`;
- consumption receipt SHA-256: `db2d857061c2c007d3c3685478290b901286df8e4995c6b85d07171d87153c89`;
- pilot-dataset manifest SHA-256: `f4d2cf5ca0d220bfc30ea10a2bedb930351ce457f4c13df22fb839f38d1cf5d8`;
- force manifest SHA-256: `fc4bff74ec59b19652ae3e44ac841ea8b15699879d708049376299ad17dc0cda`;
- task-map SHA-256: `10315e26ea3f2f07a91d198efcaa710bb96ca90cdbb98163ae98153f54efc4dd`;
- budget-receipt SHA-256: `7ca7f6726e5b078a7c35c3dea10ddd5483eece4f5882eb5e3b5280dc02c66389`.

The read-only submission plan passed every reviewed gate: six task IDs
`0..5`, array `0-5%2`, 32 ranks, two hours, concurrency two, held primary,
and an `afterany` collector.  **No Sr Slurm job has been submitted or
released at this snapshot.**  Execution remains ordered after the terminal Rb
FIRE collector and requires a fresh Nibi MFA session.  Even a successful
six-SCF result cannot establish D2, FC3, displacement-amplitude or pair-cutoff
selection, supercell convergence, phonons, or kappa.

---

## 2026-09-14 — initial pilot accepted for first-pass use; production array running

All six Nibi pilot allocations under primary array `21882066` completed
`0:0` with no retry. The original collector `21882067` failed only because a
comma-delimited Slurm export truncated the logical task-ID list; offline
read-only reconstruction recovered all six raw outputs and accounting rows
without relabelling that collector as successful.

Direct evaluation of the final complete QE force blocks passed the intended
timing/noise/signal screen. Duplicate RMS values were `9.1287093e-10`
(pristine), `7.9582243e-09` (single), and `3.1622777e-09 Ry/bohr` (double).
Incremental RMS signals were `8.9725771e-04` for single minus pristine and
`9.0362425e-04 Ry/bohr` for double minus single; propagated noises were
`8.0104099e-09` and `8.5634884e-09 Ry/bohr`. This supports first-pass force
execution only, not FC2/FC3, cutoff, supercell, phonon, or kappa validation.

The archived generation command reproduced the 787-file YAML byte for byte.
A simple immutable task map prepared one pristine plus 787 displaced SCFs at
80/640 Ry, `conv_thr=1e-10`, 3x3x3, and `nosym/noinv`. Task-map SHA-256 is
`7c5651e5adeb7ba6743e037abcee95605a681ae99421547ad06f06ba2e4c95fa`.
The first array `21888045` failed before QE because it changed to the login
submission directory; remaining tasks were cancelled. Corrected array
`21888373` uses the explicit run directory and is running as `0-787%32` from
`/scratch/yuhansun/phono3py-runs/20260914-sr-firstpass-production/SrZrS3`.
This remains an unconverged first-pass pair cutoff and supercell choice.

---

## 2026-09-15 — first-pass FC2/FC3 built; kappa rejected on imaginary modes

Fresh Nibi accounting confirmed all 788 rows of production force array
`21888373` as `COMPLETED|0:0`. A material-scoped audit verified the exact
pristine-plus-787 task mapping against all 4,025 YAML displacement IDs, all
input/output/stderr hashes, exit-code and identity receipts, strict last
complete QE force blocks, `JOB DONE`, the 8-Sr/8-Zr/24-S atom order, and
cell/position identity after the required bohr-to-angstrom conversion.

The pristine maximum component was `9.342e-5 Ry/bohr`, so the configured
`5e-5 Ry/bohr` preferred gate remains failed. Under an explicit time-bounded
exception below `1e-4 Ry/bohr`, postprocessing used strict per-atom pristine
subtraction and permanently required `first_pass_unconverged`. The archived
six-task pilot independently showed incremental RMS signals of
`8.9725771e-4` and `9.0362425e-4 Ry/bohr`, roughly five orders of magnitude
above propagated duplicate noise.

Failed postprocess jobs `21924767`, `21924822`, `21924947`, and `21925015`
exposed respectively a wrapper-version query, YAML presentation-order, total-
versus-included-ID, and bohr/angstrom checker assumption before FC fitting.
Job `21925300` preserved the pristine scientific gate failure. With the
authorized exception, job `21925488` exposed phono3py's per-output drift
removal plus 10-decimal serialization; the independently reproduced model
then passed within `2e-10 Ry/bohr`. Job `21925660` built FCs and the first
mesh but stopped on the documented FC2 HDF5 dataset name `force_constants`.
These attempts remain immutable and are not represented as successful jobs.

Final job `21925850` passed the force, mapping, serialization, and HDF5
shape/finite audits. Full FC2 `(40,40,3,3)` and FC3
`(40,40,40,3,3,3)` were constructed. Its explicit `--nonac` 12x5x3 RTA
command returned zero, but the independent frequency gate found a minimum of
`-1.0716026422440281 THz` at `[0.0,0.4,0.0]`, with 12 sampled modes below
`-0.1 THz`. The job therefore exited fail-closed as `FAILED|2:0`; no denser
q mesh was submitted.

The finite 12x5x3 tensor is archived only as a rejected diagnostic. Its
trace/3 values are `1.2710574279`, `0.6274234731`, and `0.4172933640
W m^-1 K^-1` at 300, 600, and 900 K. They are not a valid kappa_L result and
must not be combined with electronic transport into zT. The compact evidence,
remote SHA-256 manifest, commands, assumptions, and limitations are under
`phono3py/evidence/first_pass_unconverged/`; large force logs and HDF5 files
remain only in the immutable Nibi attempt.

# WORKLOG — phono3py lattice thermal conductivity (fourth step)

Lab-notebook rules: dated, append-only entries; record failed attempts, not
just what worked. Raw compute lives in
`thermo_candidates/SrCu2SnS4/phono3py/`; this package holds curated copies.

## 2026-07-13 — Session 1: install, displacement generation, campaign design

**Goal.** Roy's task: get phono3py running (he could not), compute lattice
thermal conductivity kappa_L for SrCu2SnS4, and write up how we got it
working. kappa_L is the missing denominator of every zT_e reported so far.

**Step 1 — Install (worked first try).**
`pip install phonopy phono3py` inside the `thermo-bt2` conda env installed
phonopy 4.3.1 + phono3py 4.3.3 from prebuilt macOS arm64 wheels — no compiler
needed. If Roy tried a source build or conda mixing, that is likely where he
got stuck; on this machine the pip route just worked.

**Step 2 — CLI surprises (failed attempts, recorded deliberately).**
- `phono3py --version` → error; the flag does not exist in 4.x.
- The documented-in-older-tutorials call `phono3py --qe -c cell.in -d --dim ...`
  no longer exists: phono3py 4.x split the interface. Setup operations
  (displacement generation, force collection `--cf3/--cf2`) moved to a new
  command **`phono3py-init`**; the `phono3py` command now always runs in
  "load mode" and expects a `phono3py_disp.yaml`/`phono3py.yaml`.
- A config file `phono3py disp.conf` with `CELL_FILENAME`/`CALCULATOR` tags
  also fails in load mode ("phono3py_disp.yaml could not be found").
- Working call: `phono3py-init --qe -c unitcell.in -d --dim 2 2 1 [...]`.

**Step 3 — Symmetry trap (the big one).**
First displacement generation reported **spacegroup P1** and **83,088
displacements** — intractable and wrong. Cause: `unitcell.in` (copied from
the relaxed final SCF input `qe/01_scf/SrCu2SnS4.scf.in`) stores crystal
coordinates rounded to 6 decimals; phono3py's default symmetry tolerance
(1e-5) is too tight for that rounding, so it saw no symmetry at all.
Fix: `--tolerance 1e-3` → spacegroup **P3_121 (No. 152)**, matching the
QE-relaxed space group in `results/workflow_summary.md`, and the count drops
to 13,848. Side effect cleaned up: the failed P1 run had written 83,089
`supercell-*.in` files; all were deleted before regenerating so no stale
P1-numbered supercell could be mixed into the real campaign.

**Step 4 — Making the campaign fit the laptop.**
13,848 supercell force calculations (96-atom 2x2x1 supercells) is months of
compute on the M5 Pro. Counted the systematic-displacement sets under a
pair-distance cutoff (`--cutoff-pair`):
- 3.0 A → 168 supercells
- 4.0 A → 168 supercells (identical set; no new pair shells between 3-4 A)
- 5.0 A → 600 supercells
Decision: **--cutoff-pair 4.0 A, 2x2x1 supercell (96 atoms), 168 force
calculations**. Bond lengths here (Cu-S ~2.3 A, Sn-S ~2.4 A, Sr-S ~3.0 A)
mean 4.0 A covers displacement pairs through the nearest-neighbor bonding
shells. fc3 elements beyond the cutoff are set to zero — an explicit,
documented approximation of this first pass, to be tightened later (600-cell
5.0 A set) if kappa_L looks load-bearing for conclusions.
Displacement amplitude: phono3py's QE default 0.06 au (~0.032 A).

**Step 5 — Automated campaign design (scripts written while the benchmark
runs).** Everything lives in `thermo_candidates/SrCu2SnS4/phono3py/scripts/`
and is resumable (safe to rerun after any interruption):
- `prepare_inputs.py`: wraps each phono3py structure fragment with the QE
  header — converged 90/720 Ry basis, fixed occupations, `tprnfor=.true.`,
  `conv_thr=1e-9` (tighter than the 1e-8 used for energies: fc3 needs force
  differences, so force noise must stay well below ~1e-4 Ry/bohr),
  `disk_io='none'`, per-run `tmp/` deleted after each run.
- `run_campaign.sh` stage 0: two one-factor force-convergence checks on
  disp-00001 against the 90/720 Ry, 3x3x3 benchmark — (a) k-mesh 2x2x2,
  (b) cutoffs 60/480 Ry — accepted only if max |dF| <= 5e-5 Ry/bohr
  (about 1% of the ~6e-3 Ry/bohr force scale a 0.032 A displacement
  induces). This is a documented per-material convergence test, not a
  parameter reuse; decisions land in `checks/DECISIONS.txt`.
- stage 0.5: residual forces on the undisplaced supercell (non-gating
  sanity check; warns if > 1e-4 Ry/bohr, which would mean the relaxation
  is too loose for phonons).
- stage 1: all 168 force SCFs sequentially with health checks (JOB DONE +
  SCF converged + forces present), one retry at nk=1 per failure, timings
  in `campaign_log.csv`, failures in `FAILED.list` (block stage 2).
- stage 2 (`postprocess.py`): FORCES_FC3 via `phono3py-init --cf3`;
  q-mesh ladder 7x7x3 -> 15x15x7 at 300 K until kappa_avg changes < 3%;
  final RTA (--br) run 300-900 K; derived tables to `../results/`;
  imaginary-mode check from the frequency dataset. fc3 solver: traditional
  first, `--fc-calc symfc` fallback if the cutoff-pair dataset is rejected.

**Benchmark observation (RAM).** QE estimated > 5.19 GB/process (62 GB
total) for the 96-atom supercell — the actual resident set is ~5-6 GB total
across 12 ranks, so the estimate is pessimistic and 24 GB is enough with
`disk_io='none'`. A memory guard watches the run; fallback if it ever
climbs: `disk_io='low'`.

**Step 6 — Local campaign ABANDONED; waiting on cluster resources.**
The disp-00001 benchmark (90/720 Ry, 3x3x3 k, 12 MPI ranks) had not finished
its first SCF iteration after ~42 minutes when the session ended, i.e. a
single force calculation costs plausibly >= 2 h and the 168-cell campaign
1-2 weeks of uninterrupted laptop time — times three materials. Decision
(user's call): do NOT run the campaign locally. An email asking Roy about
group computing resources (workstation / Digital Research Alliance
allocation) is drafted in Gmail; the campaign stays paused until access is
sorted out. Everything needed to launch elsewhere is on disk and portable:
displacement dataset (`phono3py_disp.yaml` + 168 fragments), input
generator, resumable driver, postprocessing. Adapting the driver to a
SLURM cluster (job arrays instead of the sequential loop) is a known,
small task once we know the machine. No calculations are running.

**Step 7 — Repo published; pipeline made portable for a Windows
workstation.** The workspace is now a git repo (public GitHub:
`qevekaede-dotcom/Waterloo-prof-Holger`; private/third-party background
material excluded and kept local-only). To try the campaign on a Windows
workstation: hardcoded macOS paths replaced (`SSSP_PBE_PRECISION` env var
for pseudos; `QE_ENV_SCRIPT` optional env hook in the driver), stage 0 now
runs the disp-00001 reference benchmark itself on a fresh machine instead
of erroring, and `WINDOWS_SETUP.md` documents the WSL2 route end to end
(conda-forge QE, SSSP download, power settings, feasibility check after
the benchmark). `RESEARCH_BACKGROUND.md` carries the public-safe project
context.

**Approximations / limitations declared up front.**
- fc3 pair cutoff 4.0 A (above); fc2 limited to the 2x2x1 supercell range.
- No non-analytic correction yet (no Born charges / dielectric tensor);
  planned as a follow-up via `ph.x` if dispersions look suspicious near
  Gamma.
- Scalar-relativistic PBE, no SOC — same level as all transport so far.
- 2x2x1 supercell (12.7 x 12.7 x 15.6 A): in-plane fc range is limited by
  the 2x supercell; a supercell-size check is a known follow-up, not part
  of the first pass.

## 2026-07-21 — Session 2: Windows workstation env + DRAC SLURM port

**Context.** The professor authorized a Digital Research Alliance (DRAC)
account under the group's allocation, so the plan changed from "try the
campaign on the Windows workstation" to: workstation does preparation and
postprocessing, DRAC runs the 168 force calculations. The local environment
was still set up in full so stage-2 postprocessing (and prep for the next
materials) can run here.

**Windows workstation environment (WSL2 Ubuntu 24.04) — done.**
- Hardware: AMD Ryzen 7 9800X3D (8c/16t), 32 GB RAM; WSL exposes 12 logical
  CPUs / 19 GB.
- conda env `thermo`: conda-forge QE 7.5 (pw.x + bundled OpenMPI 5.0.10),
  pip phonopy 4.4.0 + phono3py 4.4.0 + h5py. Both 4.4.0 — one minor version
  newer than the Mac's 4.3.x; the `phono3py-init` split interface is
  unchanged.
- SSSP 1.3.0 PBE precision downloaded from the Materials Cloud archive
  record (60 MB tarball; direct URL now in DRAC_SETUP.md). All 4 files from
  `qe/pseudo/manifest.md` verified present; `SSSP_PBE_PRECISION` exported in
  `~/.bashrc`.
- Repo cloned to the WSL home (`~/Waterloo-prof-Holger`), per
  WINDOWS_SETUP.md.
- Failed attempt, recorded: `mpirun -np 8` was refused — the conda OpenMPI
  counts *physical* cores and WSL exposes only 6 of them. Local QE runs here
  use `QE_NP=6` (or add `--use-hwthread-cpus`).
- Smoke tests (plumbing checks, deliberately not physics): (1)
  `prepare_inputs.py --only 00002` in a scratch copy picked the pseudo dir
  from the env var; (2) the 24-atom unitcell at intentionally low 40/320 Ry,
  Gamma-only, conv_thr 1e-4 ran healthy on 6 ranks in 31 s wall (QE 7.5);
  (3) `phono3py.load(symprec=1e-3)` on the repo dataset: 2x2x1 matrix, 24
  first_atoms + 144 included pairs = 168 force calculations, spacegroup
  P3_121 (152) — matches the Mac-generated dataset exactly.

**DRAC SLURM port — new `scripts/slurm/` (untested on a real cluster until
account details arrive; flagged as such).**
- `run_campaign.sh` gained a `STOP_AFTER=stage0` hook — the only edit, no
  behavior change when the variable is unset.
- `stage0_checks.sbatch`: reuses run_campaign.sh unchanged for the reference
  benchmark, k-mesh/cutoff force checks, pristine check, and input
  generation (1 node / 32 ranks / 10 h cap).
- `stage1_array.sbatch`: 168-task job array (throttle %32), `srun pw.x`,
  same three health-check strings and the nk=1 retry as the laptop driver,
  per-run `timing.csv`.
- `stage2_post.sbatch`: gates on all 168 healthy (the FAILED.list rule,
  re-expressed), assembles `campaign_log_slurm.csv`, runs postprocess.py in
  a venv (16 threads / 64 GB / 12 h caps).
- `submit_all.sh` chains the three with afterok dependencies;
  `cluster.env` holds ACCOUNT / module version / paths.
- `DRAC_SETUP.md` (repo root): CCDB key upload -> login -> one-time cluster
  setup -> submit -> monitor -> failure recovery -> rsync results home.

**Pending (user actions, not compute).** Confirm CCDB account + Duo MFA;
paste the WSL public key (`~/.ssh/id_ed25519_drac.pub`) into CCDB; get the
allocation string (def-<professor>) and cluster choice from Roy/the
professor; fill User/HostName in the WSL `~/.ssh/config`. First login is
interactive (password + Duo), then keys take over and the campaign is
`bash scripts/slurm/submit_all.sh` away.

## 2026-08-03 — Session 3: cluster access debugged, campaign SUBMITTED on Nibi

**The login mystery solved (this was Roy-writeup-grade confusion).** CCDB
account was fine (username yuhansun, allocation def-kleinke, RAP asw-382-aa,
sponsor-approved). A fresh SSH key made on the Mac was accepted within
minutes of pasting into CCDB. Yet Nibi closed the connection right after
"Success. Logging you in...", and Narval looped Duo three times then denied
— the same failure the user had hit before and read as "the key didn't
take". The real cause was in Narval's login banner: **since 2025-09-05
each cluster must be individually activated at
ccdb.alliancecan.ca/me/access_systems** (select the cluster, answer four
agreement questions). Neither key nor Duo was ever the problem. After
activating Nibi + Narval there, Nibi login worked immediately.

**Cluster deployment (all via one authenticated SSH channel; ControlMaster
multiplexing so the user taps Duo once per 8 h, not per command).**
- Repo cloned to `~/scratch/Waterloo-prof-Holger` on Nibi; all 168
  supercell fragments + phono3py_disp.yaml verified in the clone.
- SSSP 1.3.0 PBE precision fetched from the Materials Cloud archive; all
  4 manifest files verified.
- **Wheelhouse trap [recorded for the writeup]**: pip on Nibi installs from
  the Alliance wheelhouse -> phono3py 3.25.0 / phonopy 2.48.0, NOT the 4.x
  used to generate the dataset (3.x lacks `phono3py-init` entirely).
  Decision: the cluster runs only stages 0-1 (pure QE force runs, no
  phonopy dependency); stage 2 (FORCES_FC3 + kappa_L) runs at home on
  phono3py 4.x so ONE version handles the dataset end to end. stage2 was
  therefore NOT submitted on the cluster.
- **Nibi SLURM specifics** (both cost a failed submission to learn):
  no default partition (CPU <=12 h -> `cpubase_bycore_b2`), and accounts
  are split by resource (`def-kleinke_cpu`, not `def-kleinke`).
  `cluster.env` updated accordingly (SBATCH_PARTITION + ACCOUNT).
- QE module: quantumespresso/7.3.1 (StdEnv/2023) confirmed available.

**Submitted (2026-08-03): stage0 = job 19030260, stage1 array (168 tasks,
%32 throttle) = job 19030261, afterok-chained.** Stage 0 reruns the
reference benchmark and both force-convergence checks ON NIBI before any
campaign input is generated — per-machine convergence rule, unchanged.
Postprocessing plan when the array finishes: rsync the 168 scf.out home,
run scripts/postprocess.py locally (phono3py 4.3.3).

## 2026-08-21 — Session 4: stage0 timeout diagnosed (OpenMP oversubscription); resubmitted; stage2 moved onto Nibi

**Discovery — 18 days of silence, zero compute.** First status check since
submission (workstation WSL over `ssh drac`): stage0 19030260 = TIMEOUT at
its 10 h cap (the `.extern` step's COMPLETED is SLURM bookkeeping, not
success); stage1 19030261 = PENDING 00:00:00 with reason
DependencyNeverSatisfied — afterok on a timed-out job can never fire.
`campaign_log.csv` on the cluster: header only. Nothing had run.

**Root cause [writeup-grade].** The stage0 log shows all 10 h were spent
inside the first reference benchmark (disp-00001, 90/720 Ry, 3x3x3). Its
`scf.out` banner reads "Parallel version (MPI & OpenMP), running on 352
processor cores" against `--ntasks=32`: the Alliance quantumespresso/7.3.1
module is an MPI+OpenMP hybrid build and nothing capped the thread count,
so 32 ranks x ~11 threads thrashed the 32-core allocation. After 10 h the
run was still on SCF iteration 7 at 0.013 Ry estimated accuracy (target
conv_thr 1e-9; normally ~30-40 iterations at minutes each). Roughly a 10x
slowdown — the time cap was never the real problem.

**Fix + resubmission (2026-08-21).** `export OMP_NUM_THREADS=1` added to
`scripts/slurm/cluster.env` (sourced by every sbatch script; stage2
overrides it back to $SLURM_CPUS_PER_TASK for phono3py's own OpenMP), and
stage0/stage1 time caps raised to the 12 h partition max as headroom — no
clean per-SCF timing exists yet. Edits were applied directly in the Nibi
clone by the user and mirrored in this commit; the Nibi copy is therefore
locally modified — rsync results home with `--exclude 'scripts/'`, and
`git checkout -- .../phono3py/scripts/` there before any future pull. Old
stage1 scancel'ed. **New jobs: stage0 = 20213855, stage1 array = 20213856
(afterok).** Verification once stage0 runs: the pw.x banner must say 32
processor cores and the iteration count must climb minutes-fast.

**Plan change: stage2 runs on Nibi after all.** The workstation's compute
is committed elsewhere, so the "collect forces + kappa_L at home" plan is
dead. The Session-3 blocker (wheelhouse pins phono3py 3.25, no
phono3py-init) is bypassed by installing the pinned dataset version from
PyPI into the stage-2 venv: `PIP_CONFIG_FILE=/dev/null pip install
'phono3py==4.3.3' h5py`, with the venv recreated from scratch in case a
3.25 attempt left one behind (DRAC_SETUP.md section 3 updated). One
phono3py version — 4.3.3, the version that generated the dataset — again
handles it end to end, just on the cluster instead of at home.
`stage2_post.sbatch` is chained with afterok on the array, so the whole
pipeline runs unattended and kappa_L(300-900 K) lands in
`SrCu2SnS4/results/` on the cluster; local machines are left with file
transfer, git, and the writeup.

**Process lesson.** The first submission died within 10 h of sbatch;
nobody looked for 18 days. Check `sacct` within a day of submitting — a
TIMEOUT surfaces immediately, and afterok chains die silently with it.

**Correction, same evening: the pinned-4.3.3 venv recipe above FAILED
twice before a different fix worked [all writeup-grade].**
- Attempt 1 — `PIP_CONFIG_FILE=/dev/null pip install 'phono3py==4.3.3'`:
  /dev/null does open the path to PyPI, but the Alliance python VETOES
  PyPI's prebuilt manylinux wheels, so pip fell back to the 4.3.3 source
  package — whose build config still uses the pre-0.10 scikit-build-core
  key `cmake.verbose`, which scikit-build-core >= 0.10 rejects outright.
  Confirmed by diffing the 4.3.3 vs 4.4.0 source packages from PyPI:
  4.4.0 renamed the key to `build.verbose`.
- Attempt 2 — same with `phono3py==4.4.0`: its own source now builds,
  but the dependency chain (phonopy -> symfc -> scipy) reached
  scipy-from-source, whose meson build requires OpenBLAS that pip's
  isolated build environment cannot see. Dead end: rebuilding the
  scientific Python stack from source on the cluster is the wrong fight.
- Working fix — shadow the wheel veto for the install command only:
  `~/pipshim/_manylinux.py` defining `manylinux_compatible(major, minor,
  arch) -> (major, minor) <= (2, 34)`, then
  `PYTHONPATH=$HOME/pipshim PIP_CONFIG_FILE=/dev/null pip install
  'phono3py==4.4.0'`. Everything arrived as prebuilt wheels, zero
  compilation: phono3py 4.4.0, phonopy 4.4.0, numpy 2.4.6, scipy 1.17.1,
  h5py 3.16.0, spglib 2.7.0, symfc 1.7.3, phonors 0.3.0, matplotlib.
  `phono3py-init --help` prints usage; `import phono3py` -> 4.4.0. That
  shadowing works is what confirms the veto mechanism (a `_manylinux`
  hook shipped with the Alliance python, overridden by PYTHONPATH
  precedence). Install-time only — the venv needs no PYTHONPATH at run
  time. Recipe now in DRAC_SETUP.md section 3.
- Version note [flagged]: the displacement dataset was generated by
  phono3py 4.3.3 (Mac); cluster postprocessing runs 4.4.0, since 4.3.3
  cannot be built there. Session 2's workstation smoke test already
  verified 4.4.0 reads this exact dataset identically (2x2x1 supercell,
  168 calculations, P3_121). The wheels bundle their own BLAS rather
  than the cluster-tuned one — acceptable for this postprocessing
  workload.
- **stage2 submitted: job 20215178**, afterok on the stage1 array (the
  sbatch NOTE about 64G = 65536M is informational). Full chain queued
  unattended: 20213855 (stage0) -> 20213856 (168-task array) ->
  20215178 (postprocess -> kappa_L into `SrCu2SnS4/results/` on the
  cluster).

**Next day (2026-08-21 afternoon): campaign outcome — 144/168, plus a
patterned batch of fast failures.**
- stage0 (20213855) COMPLETED in 02:56:28 — the OMP_NUM_THREADS=1 fix
  fully confirmed (2h56m vs stuck on iteration 7 at the 10 h cap before).
- stage1 (20213856): 144/168 COMPLETED at ~39-47 min per force
  calculation; **24 tasks FAILED in 19-27 s each**, all dying right after
  pw.x's dynamical-RAM printout, always MPI task 13/14 exiting code 1,
  across ~20 different nodes over ~2.6 h. The failed displacement IDs are
  strikingly regular: exactly one inside each ~6-displacement pair block
  (disp-00026, 00601, 01182, ..., 13709). That regularity argues for a
  deterministic per-configuration trigger rather than random node flakes,
  but the logs also carry node-level noise (pmix errors, task-epilog
  failures) — undecided pending the rerun. Full verbatim record:
  `SrCu2SnS4/phono3py/slurm_logs/evidence_2026-08-21_stage1_fastfails.md`
  (transcribed from the interactive session — the on-disk scf.err/CRASH
  get overwritten by reruns).
- stage2 (20215178) went DependencyNeverSatisfied as designed (afterok on
  an array with failures can never fire): scancel'ed, and the 24 failed
  indices were resubmitted with a fresh stage2 chained after them (job
  ids in the next entry once reported back).
- **Archival workflow added** (user request — raw outputs must reach
  GitHub, not just the WORKLOG narrative): (1)
  `scripts/slurm/collect_evidence.sh` snapshots sacct + every unhealthy
  displacement's scf.err/CRASH/scf.out + campaign CSVs into timestamped
  `slurm_logs/evidence_*/` dirs — runs automatically at stage2 start, and
  manually BEFORE any rerun; (2) `scripts/fetch_home.sh` (workstation
  side) rsyncs the whole campaign home (excluding tmp/ and scripts/) and
  commits+pushes in one command. DRAC_SETUP sections 6-7 updated.

**Root cause of the 24 fast-fails FOUND [writeup-grade]: QE
`sym_rho_init_shell` "lone vector".** Diagnostics (verbatim in the
evidence file): disp-00026's CRASH says `task # 14, from
sym_rho_init_shell, error # 2: lone vector`; stage0's decisions were
KMESH=3 3 3 with 60/480 Ry (low-cutoff check PASSED, k-mesh check kept
3x3x3); healthy disp-00025 has 14 irreducible k-points vs 10 for failed
disp-00026. Mechanism: the failing member of each pair block is the
displacement combination that PRESERVES a symmetry operation; for those
configurations QE's charge-symmetrization setup hits its known "lone
vector" failure when G-vector symmetry shells are split across the
32-rank distribution. Fully deterministic, which explains the perfect
one-per-block ID pattern, the constant task 13/14, and both nk=2 and
nk=1 failing — and means the plain rerun (20260344, stage2 20260345
chained) is expected to fail identically. Fix: patch
`nosym = .true., noinv = .true.` into the still-unhealthy scf.in only
(idempotent guard on both health and prior patch), then resubmit those
indices and re-chain stage2. Physics unchanged: symmetry there is only a
k-sum/symmetrization shortcut; the full 3x3x3 mesh is sampled explicitly
at the same cutoffs and conv_thr (~27 vs 10 k-points, ~2x cost for these
24 runs), safe to mix with the 144 symmetry-reduced runs since phono3py
symmetrizes fc3 downstream. Expect the same trap in the SrZrS3 /
Rb2Cu2SnS4 campaigns. Final rerun job ids: next entry, once reported.

**Executed (2026-08-21 ~20:47 UTC).** The plain rerun 20260344 did fail
identically — collect_evidence.sh (fetched onto the cluster clone via the
public raw URL) found the same 24 unhealthy displacements afterwards and
snapshotted them to `slurm_logs/evidence_20260821T204652Z/`. All 24
scf.in patched with nosym/noinv (exactly the predicted list). **nosym
rerun = job 20260532; fresh stage2 = job 20260533 (afterok).** Expected:
~1-1.5 h per nosym run (27 vs 10 k-points), then stage2 (~1-2 h) writes
kappa_L into `SrCu2SnS4/results/` on the cluster; archival via
`scripts/fetch_home.sh` from the workstation afterwards.

## 2026-08-26 — Session 5: campaign closed out from archived records; interim progress email drafted

**Campaign completion, reconstructed from the on-disk archive** (the previous
entry ended at "nosym rerun submitted"; the finishing session on the cluster
never wrote its WORKLOG entry, so this one records what the archived records
show, after tracing each number back to them).

- **nosym rerun 20260532: all 24 succeeded — all 168 force calculations
  healthy.** The health record spans TWO logs: `campaign_log_slurm.csv`
  (the stage-2 gate's assembled log) holds 167 data rows (166 `ok` plus
  disp-04705 `ok_retry` at nk=1); the 168th, disp-00001, doubled as the
  stage-0 reference benchmark at the 90/720 Ry settings and is logged as
  `benchmark_00001, ok` in `campaign_log.csv`. Consequence [flagged]:
  FORCES_FC3 mixes one 90/720 Ry force set (disp-00001) with 167 at
  60/480 Ry — harmless at our tolerance (max |dF| between the two settings
  is 5.2e-6 Ry/bohr per `checks/lowcut_report.txt`, ~1% of the 5e-5
  threshold), but it belongs in the writeup.
- **stage2 ran TWICE, and only the second is the final answer:**
  1. **Job 20260533**: built FORCES_FC3 *without* subtracting residual
     forces of the undisplaced supercell. Its q-mesh ladder
     (kappa_avg(300 K) = 0.341 / 0.328 / 0.376 / 0.364 / 0.381 W/m/K at
     7x7x3 / 9x9x4 / 11x11x5 / 13x13x6 / 15x15x7) never had a <3% step, so
     it fell back to the largest mesh with its own logged WARNING to flag
     this — final-m15157, kappa_avg(300 K) = 0.381 W/m/K.
  2. The undisplaced ("pristine") supercell was then run on Nibi (job
     20305341 failed — its CRASH shows a `seqopn ... ./tmp/sc.restart26`
     error; job 20305344 completed; the archived `checks/pristine/scf.in`
     carries the nosym/noinv patch, as expected for the maximally symmetric
     configuration). **Job 20311271** rebuilt FORCES_FC3 with
     `--cfz checks/pristine/scf.out` (residual-force subtraction). That
     small fc3 change nudged the ladder to 0.341 / 0.328 / 0.375 / 0.364,
     the 11x11x5 -> 13x13x6 step became ~2.96% < 3% (from the
     full-precision hdf5 values 0.37503 -> 0.36394; the log's rounded
     values give 2.93%), and the final full-T run
     at **13x13x6** wrote `results/kappa_L_first_pass.csv` +
     `kappa_L_summary.md` — the curated numbers (300 K: xx=yy 0.3960,
     zz 0.2999, avg 0.3639; 900 K avg 0.1213 W m^-1 K^-1; min phonon
     frequency -0.0000 THz, no imaginary modes).
- Everything was archived home by `fetch_home.sh` in three commits
  (32bf814, cd882c2, 9bfe607). Numbers in the summary/CSV verified against
  `log_kappa.txt` (final run at 13x13x6) and the stage2 slurm logs — they
  match line for line.
- **Honest spread [flagged]:** chosen 13x13x6 avg (0.364) vs the
  no-subtraction 15x15x7 pass (0.381) differ by ~5% at 300 K, and the
  ladder convergence at 13x13x6 is borderline (2.9% vs the 3% criterion).
  The interim email therefore quotes "roughly 0.35-0.40 W m^-1 K^-1", not
  three significant figures.
- **Reproducibility gap [action item]:** the `--cfz` / pristine-subtraction
  step exists only in the Nibi clone's locally edited `postprocess.py`
  (fetch_home.sh excludes `scripts/`; the repo copy has no `--cfz`). Port it
  into `scripts/postprocess.py` BEFORE the SrZrS3 / Rb2Cu2SnS4 campaigns.
  Also: the archived `pristine_20305341.out` / `pristine_20305344.out` slurm
  logs are 0 bytes, so the pristine jobs' stdout is not in the archive.

**Interim progress email to Roy drafted (user request).** New in this
package: `EMAIL_DRAFT.md` (subject + body, modest first-person voice,
no dates in the body), `ATTACHMENTS.md`, `READY_TO_ATTACH/` with one file
(`SrCu2SnS4_kappa_L_first_pass.csv`, copy of the authoritative results CSV),
and this package's `CLAUDE.md`. Content: it-runs-now trap list
(phono3py-init split, symmetry tolerance/P1, wheelhouse pin, OpenMP
oversubscription, QE lone-vector -> nosym), first-pass setup and kappa_L
table with the caveats (RTA, 4.0 A pair cutoff, 2x2x1 supercell, no NAC,
PBE no SOC, ~5% numerical spread), and next-step question (other two
materials vs tightening SrCu2SnS4 first). The personal Gmail was checked
and holds no Roy thread — the correspondence lives in the uwaterloo
mailbox, so no Gmail draft was created; the user copies the draft there.
NOT sent; READY_TO_ATTACH/ freezes on send. Also updated:
`thermo_candidates/Roy_task_status.md` (was still "not started") and
`HANDOFF.md` (kappa_L landed; what remains).

**Still open for the full fourth-step package:** port `--cfz` into the repo
postprocess.py; SrZrS3 + Rb2Cu2SnS4 campaigns (patch nosym into
symmetry-preserving displacements from the start); the complete writeup;
`learning/08_phonons_and_kappa_L.md` [pending] sections; reproducibility/
and results/ folders here; add phono3py to the CV skills list only now that
kappa_L has landed.

**Rigor review (required; ran three independent audits — number tracing,
rules/tone compliance, adversarial physics — before finalizing the draft).**
Every number in the email and this entry traced to a primary output
(CSV/hdf5/log/slurm/yaml agreement confirmed line for line; the staged
attachment is byte-identical to the authoritative CSV). Corrections applied
as a result: the campaign_log_slurm.csv row-count claim above (originally
misstated as 168 rows; disp-00001 lives in campaign_log.csv as the 90/720 Ry
benchmark), and in the email — softened the opening and install phrasing,
credited cluster access to Roy AND the professor (the repo attributes the
DRAC authorization to the professor), corrected the nosym explanation
(nosym also disables charge/force symmetrization, not just k-point
bookkeeping; forces agree within the force tolerance, which is the honest
claim), separated the quantifiable ~5% numerical spread from the unbounded
systematics (pair cutoff / supercell / RTA / no NAC), made the "quite low
for a sulfide" comparison conditional on the tightened follow-up and
explicitly memory-based, flagged the 13x13x6 convergence as borderline,
labeled the 1/T fall a consistency check (only ph-ph scattering is
included, so 1/T is near built-in), and mapped the email table columns to
the CSV headers. Notebook-grade audit notes for the future writeup:
log_kappa.txt prints "Non-analytical term correction (NAC): True" as a
default-settings echo — no BORN data exists anywhere, so no NAC was
actually applied; the "-0.0000 THz" minimum is -2.15e-6 THz in
kappa-m13136.hdf5 (numerical zero of the Gamma acoustic modes); the 83,088
(P1) and 600 (5.0 A) displacement counts survive only as Session-1
notebook records (the P1 inputs were deliberately deleted), unlike 13,848
and 168 which are confirmed by phono3py_disp.yaml. Remaining limitations
stated, none glossed over; no Scientific-rules violations found in the
final draft (PF/tau absent, zT_e called an upper bound, no-SOC stated,
kappa_L labeled calculated first-pass, per-material convergence promised
for the next two materials).

## 2026-08-27 — Session 6: kappa_L figure added to the interim email package

User request while preparing to send: the earlier packages all carried
figures, so the interim email gets one too. New script
`thermo_candidates/SrCu2SnS4/phono3py/scripts/plot_kappa_L.py` (same style
as the boltztrap2 plot scripts: read-only inputs, printed checks, Agg,
results/ output) plots in-plane, c-axis, and scalar-average kappa_L vs T
from the authoritative `results/kappa_L_first_pass.csv`. Checks before
plotting: (1) CSV columns == raw `kappa-m13136.hdf5` to the CSV's 4-decimal
rounding [passed]; (2) kappa_xx == kappa_yy and avg == trace/3 [passed
after widening the tolerance to 1.5e-4 — the CSV rounds each column
independently, so the recomputed average differs from the rounded avg
column by up to ~1e-4; first run failed at 5e-5, a tolerance bug in the
new script, not a data problem]. The two series hues were checked with a
colorblind-safety validator (the scalar average is a dashed neutral
reference line, not a third hue). Output
`results/kappa_L_first_pass.png` copied into this package's
`READY_TO_ATTACH/` as `SrCu2SnS4_kappa_L_first_pass.png`; ATTACHMENTS.md
now lists two files; EMAIL_DRAFT.md gained half a sentence pointing at the
figure. Both attachments were also zipped and handed to the user directly
(the user cannot reach the repo checkout from their device); sending to
Roy still happens from the uwaterloo mailbox. READY_TO_ATTACH/ freezes on
send, as before.

## 2026-08-27 — Session 6b: interim email SENT; READY_TO_ATTACH frozen

The user sent the interim progress email to Roy from the uwaterloo mailbox
(body per EMAIL_DRAFT.md with the figure sentence, plus a personal P.S.
added at send time — deliberately not recorded in this public repo), with
the two staged attachments (kappa_L CSV + PNG). Following the convention of
the earlier packages, `READY_TO_ATTACH/` is now FROZEN as the record of
exactly what was sent; the package CLAUDE.md was updated accordingly. The
package itself stays IN PROGRESS (SrZrS3 / Rb2Cu2SnS4 campaigns and the
full "how we got it working" writeup are still ahead).

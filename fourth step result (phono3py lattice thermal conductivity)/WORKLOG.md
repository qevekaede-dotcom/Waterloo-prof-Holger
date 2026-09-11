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

## 2026-08-22 — Session 5: campaign complete, kappa_L verified, package staged

**All green.** nosym rerun 20260532: 24/24 COMPLETED (1:04-1:34 each —
the expected ~2x from 27 vs 10 k-points). stage2 20260533: COMPLETED in
31 min. Two small workstation traps closed while archiving: git needed a
one-time identity on the WSL clone (`user.name`/`user.email`), and GitHub
no longer accepts password pushes — a dedicated SSH key
(`~/.ssh/id_ed25519_github`) was generated and registered, and the remote
switched to SSH. `fetch_home.sh` then archived everything (main commit
32bf814). FORCES_FC3 at 62.9 MB drew GitHub's >50 MB warning — under the
100 MB hard limit, no action needed.

**Results [calculated] and verification.**
- kappa_L(300 K): xx = yy 0.4036, zz 0.3367, avg 0.3813 W m^-1 K^-1;
  falls ~1/T to avg 0.1271 at 900 K (0.3813 x 300/900 = 0.1271 exactly).
- Independent re-read of `kappa-m15157.hdf5` reproduces the CSV to all
  four decimals; off-diagonal components ~1e-8; xx = yy exact — the
  trigonal symmetry check passes for free.
- Minimum phonon frequency -2e-6 THz (numerical zero): no imaginary
  modes. fc3 solver: traditional (no symfc fallback needed).
- Mesh ladder at 300 K: 0.341 / 0.328 / 0.376 / 0.364 / 0.381 W m^-1 K^-1
  for 7x7x3 / 9x9x4 / 11x11x5 / 13x13x6 / 15x15x7 — the 3% criterion was
  NOT reached (last step 4.7%); the largest mesh is reported and ~5% is
  carried as the uncertainty everywhere the number appears.
- Campaign stats (campaign_log_slurm.csv): 167 array timings, mean
  43.7 min (31.9-93.7) on 32 ranks; 166 ok + 1 ok_retry; ~3,900
  core-hours in stage 1, ~4,000 total.
- OPEN ITEM: `checks/pristine` (undisplaced-supercell residual forces)
  failed via the same lone-vector bug (task 7; 10 k-points, full
  symmetry). To close before the package is sent: patch nosym/noinv into
  `checks/pristine/scf.in` and rerun once (~1 h). freq_min ~ 0 already
  supports dynamical stability, but the explicit residual number belongs
  in the record.

**Package assembled** (`fourth step result (phono3py lattice thermal
conductivity)/`): README, CLAUDE, ATTACHMENTS, EMAIL_DRAFT (staged, NOT
sent), READY_TO_ATTACH (HOW_WE_GOT_PHONO3PY_WORKING.md + CSV + figure +
stage-2 summary), reproducibility (campaign scripts incl. the SLURM port
+ plot_kappa.py), results. learning/08 [pending] sections filled;
Roy_task_status, SrCu2SnS4/CLAUDE.md and HANDOFF updated. READY_TO_ATTACH
freezes on send, per package rules.

**Rigor review (required by CLAUDE.md) — outcome.** Every reported number
traces to `kappa-m15157.hdf5`, the stage-2 log, or
`campaign_log_slurm.csv`; units are in every column header; values are
tagged [calculated]; kappa_L is nowhere combined with tau-dependent
quantities (no "full zT" claimed); no-SOC and no-NAC are stated wherever
the number appears; convergence parameters were re-decided on the cluster
(nothing copied between machines). Open items stated rather than glossed:
the ~5% q-mesh convergence and the pending pristine check.

**Addendum, same day: pristine check CLOSED — and upgraded from flag to
correction.** The nosym pristine rerun (job 20305344, 1:13 on 32 ranks,
27 k-points) completed; **max residual force on the undisplaced supercell
= 5.451e-4 Ry/bohr** (user's extraction and an independent Python re-read
of all 96 atoms agree exactly; the four 2x2x1 images of each unit-cell
atom carry near-identical forces, confirming the residual is a unit-cell
relaxation residual, not supercell noise). That EXCEEDS the 1e-4
guideline (~18% of the 2.97e-3 typical displaced-cell force), so instead
of merely flagging it we correct it: phono3py supports
`--cfz checks/pristine/scf.out` (subtract residual forces) at the
FORCES_FC3 step — `scripts/postprocess.py` now passes it whenever the
pristine output exists. Plan: on the cluster delete the derived products
(FORCES_FC3, fc2/fc3.hdf5, kappa-m*.hdf5 — all already archived in git at
commit 32bf814, nothing is lost), apply the same one-line edit to the
cluster's postprocess.py, resubmit stage2 (~30 min), re-fetch, re-verify,
and refresh every number in the package before anything goes to Roy.
Tooling note for honesty: the first two residual-force extractions
printed a false 0.000e+00 — the awk range included the "Total force ...
Total SCF correction" line and the word "correction" won a string
comparison against every number, hijacking the maximum; reproduced and
fixed (match atom lines only, coerce numerics).

**Final addendum: corrected stage2 (job 20311271) done — FINAL first-pass
numbers.** The --cfz rerun completed; verification repeated and passed
(CSV == kappa-m13136.hdf5 to all four decimals; xx=yy exact; off-diag
~4e-8; freq_min -2e-6 THz; 0.3639 x 300/900 = 0.1213 exactly).
- **kappa_L(300 K) [calculated, residual-corrected]: xx=yy 0.3960,
  zz 0.2999, avg 0.3639 W m^-1 K^-1; 900 K avg 0.1213.**
- Mesh ladder with corrected forces: 0.341 / 0.328 / 0.375 / 0.364 —
  met the 3% criterion at 13x13x6 (2.9% vs the previous mesh; the
  pre-correction run had just missed at 3.19%), so the ladder stopped
  there and 15x15x7 was not rerun. ~5% stays as the quoted uncertainty
  (ladder spread ~0.33-0.38).
- Decomposing the change from the previously reported 0.3813: the
  residual-force correction itself moved the fixed-mesh average by
  < 0.1% (0.364 -> 0.3639 at 13x13x6) — the earlier result was robust —
  while the protocol's mesh selection (15x15x7 -> 13x13x6) accounts for
  the rest (~4%), within the stated uncertainty. Good worked example:
  the q-mesh, not the residual forces, is the real error bar here.
- Housekeeping: the local/archived kappa-m15157.hdf5 is the
  PRE-correction artifact (not regenerated on the cluster, rsync does
  not delete); kept deliberately as the record behind the earlier
  numbers. Package, learning/08, Roy_task_status, SrCu2SnS4/CLAUDE.md,
  HANDOFF and the figure all refreshed to the corrected numbers.
  Remaining: user approves EMAIL_DRAFT.md and sends; freeze
  READY_TO_ATTACH on send.

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

## 2026-08-27 — Reconciliation note: two parallel sessions merged

Two sessions worked this package in parallel without seeing each other:
this one (branch claude/canada-computing-center-task-d165w2; the 2026-08-22
"Session 5" above, plus the staged full package) and a second session
(branch claude/holger-repo-access-a8ikbc; the 2026-08-26 "Session 5" above
— the duplicate numbering is an artifact of the split and is left as
written, per append-only rules). Reconciliation decisions:

- The SENT record wins: EMAIL_DRAFT.md is the interim email actually sent
  (2026-08-26, uwaterloo mailbox, personal P.S. unrecorded);
  READY_TO_ATTACH/ is frozen with exactly the two sent files. Verified
  against the corrected results: every number in the sent email is
  correct.
- The fuller unsent draft is kept as EMAIL_DRAFT_full_package_unsent.md;
  the full writeup draft moved to the package root
  (HOW_WE_GOT_PHONO3PY_WORKING.md) as staging for the final
  three-material package, per the plan the interim email states.
- The 2026-08-26 session's action items, resolved: (1) the --cfz port
  into scripts/postprocess.py was already done on this branch (commit
  1389943) — no gap; (2) the 0-byte pristine_*.out slurm logs are
  expected — the wrapped sbatch redirected all output to
  checks/pristine/scf.out and scf.err, both archived; (3) its disp-00001
  observation (forces at 90/720 Ry among 167 at 60/480, dF 5.2e-6 —
  harmless) is a genuine catch, now added to the writeup draft's
  validation section.
- Both sessions' HANDOFF / Roy_task_status edits were merged into single
  reconciled versions (interim SENT; full package pending SrZrS3 +
  Rb2Cu2SnS4).

## 2026-09-10 — Session 7: two-material campaign audit and QE-unit correction

The user authorized an automated DRAC workflow for the pending SrZrS3 and
Rb2Cu2SnS4 phono3py calculations.  Before submitting new force campaigns, the
shared driver and old SrCu2SnS4 evidence were audited.  Heavy calculations and
phonon postprocessing remain restricted to DRAC compute nodes; no new science
was run locally.

The audit found that the phono3py QE interface records lengths in atomic units.
The authoritative SrCu2SnS4 `phono3py_disp.yaml` says `length: "au"`; its
`cutoff_pair_distance: 4.0` is therefore 4 bohr (about 2.1167 A), not 4 A as
previously documented.  All 24 included two-displacement pair groups have
zero pair distance, while the shortest nonzero pair is about 4.33833022 bohr
and was excluded.  The 168-supercell result is retained as a calculated,
residual-corrected historical first pass, but its interpretation is downgraded:
it does not establish a physically adequate 4-A fc3 range or pair-cutoff
convergence.  The frozen interim email attachments were not edited.  The old
"5 A / 600 supercells" notebook estimate is affected by the same unit issue
and must not be used as a true 5-A cost estimate.

A new strict QE force parser was started under
`thermo_candidates/scripts/phono3py_campaign/`.  It selects the main total
force block rather than the repeated high-verbosity force decompositions,
requires the last pw.x run to converge and finish, rejects later truncated
force blocks, and validates the expected atom count.  Five lightweight unit
tests pass.  Direct read-only checks of the original final relax outputs give
maximum force components of 5.0303e-4 Ry/bohr for SrZrS3 and 2.6738e-4
Ry/bohr for Rb2Cu2SnS4.  Both exceed the new phonon-grade gate and therefore
require fixed-cell tight ionic relaxation plus an independent pristine SCF
before displacement preflight.

The new configs and generator will store requested distances in Angstrom and
convert explicitly with 1 bohr = 0.529177210903 A before invoking phono3py;
generated YAML displacement norms, cutoff, atom count, supercell matrix, and
volume ratio must be checked.  Production selection remains blocked until
remote preflight reports the real displacement counts and resource estimates.

## 2026-09-10 — Session 8: residual-force provenance correction and gated workflow

A second read-only audit traced the exact SrCu2SnS4 residual-force source.
`slurm_logs/stage2_20311271.out` and `log_cf3.txt` show that the final stage-2
command passed `--cfz checks/pristine/scf.out`, and phono3py reported that the
file's forces were subtracted before creating `FORCES_FC3`.  That archived QE
output has one converged SCF and a complete 96-atom force block, followed by
`seqopn(90): error opening ./tmp/sc.restart`; its stderr records MPI aborts.
The repository contains no second PWSCF output supporting the older statement
that job 20305344 was a clean rerun.  A numerical reconstruction of phono3py's
per-file drift correction plus subtraction of this pristine force block agrees
with the first 96 `FORCES_FC3` components to a maximum of about
4.17e-11 Ry/bohr.  Therefore the correction's data lineage is established,
but the pristine QE run is not a healthy completed calculation.  This corrects
the earlier worklog claim without rewriting it or changing frozen attachments.

The pending-material workflow now has separate SrZrS3 and Rb2Cu2SnS4 campaign
configs, strict QE input/output parsers, immutable attempt and provenance
records, fixed-cell tight-relax plus independent-pristine gates, phono3py
count/geometry/unit preflight, evidence-only afterany collection, and a
fail-closed Nibi submission front-end.  Scientific-policy hashes are separated
by stage so a later recorded production choice cannot invalidate earlier
structure evidence.  The explicit Slurm account is `def-kleinke_cpu`; every
request records it and uncertain successful `sbatch` responses block retry.
Local lightweight validation passed 36 unit tests, Python compilation, both
material config validations, and shell syntax checks.  Final read-only review
released only relax and passing-gate preflight; force production, FC2/FC3,
transport postprocessing, and final audit remain intentionally blocked pending
real remote preflight and force/amplitude convergence evidence.

## 2026-09-10 — Session 9: Nibi clean deployment and tight-relax submissions

The tested workflow was committed and pushed on branch
`codex/two-material-phonons` (`06a1326`, followed by submission-host fixes
`fcdbc33` and `92d973a`). A new clean Nibi clone was created at
`/scratch/yuhansun/Waterloo-prof-Holger-phonons-20260910`; the historical dirty
cluster clone was not modified. Nibi reproduced all 36 initial unit tests,
both material config validations, and the installed phono3py/phonopy 4.4.0 and
spglib 2.7.0 environment. After the login-host regression test was added, the
suite contained 37 passing tests.

Two submission attempts were safely stopped before `sbatch` because Nibi
reported login hostnames `ic-l5.nibi.sharcnet` and, in another multiplexed
session, `l5`, while the initial guard accepted neither. No local submission
record or Slurm job resulted from those stops. The guard was narrowed to the
observed Nibi FQDN/short-name patterns, with tests that reject a suffixed fake
domain and any environment containing `SLURM_JOB_ID`.

The following immutable tight-relax chains were then submitted under explicit
account `def-kleinke_cpu`:

- Rb2Cu2SnS4: primary `21638193`, attempt
  `20260910T074723Z-relax-efb1dbed`; afterany collector `21638194`, attempt
  `20260910T074723Z-collect-a2405103`.
- SrZrS3: primary `21638199`, attempt
  `20260910T074839Z-relax-49cd2cc4`; afterany collector `21638200`, attempt
  `20260910T074840Z-collect-46e972d8`.

At the 2026-09-10 07:49 UTC check both primaries were PENDING for Priority and
both collectors were PENDING on their correct `afterany` dependencies. Each
primary requests one node, 32 tasks, 2000 MiB per CPU, and 12 hours. This is
not yet a completed structure, phonon, or thermal-conductivity result. The
next automatic action is evidence inspection; preflight is permitted only
after `finalize-relax` publishes a passing immutable gate.

## 2026-09-10 — Session 10: first live outcome and pilot safety integration

A read-only Nibi check at 08:38 UTC found Rb2Cu2SnS4 job `21638193` still
running normally on `c277`. Through BFGS step 4 its total force decreased from
8.92e-4 to 2.49e-4 Ry/bohr; the latest largest force component was 9.636e-5
Ry/bohr. The output was still growing, pw.x remained active, and no fatal QE,
MPI, OOM, or time-limit signature was present. Collector `21638194` remained
pending on the correct unfulfilled `afterany:21638193` dependency. These are
intermediate diagnostics, not an accepted structure.

SrZrS3 job `21638199` reached a terminal FAILED state and collector `21638200`
completed normally. All reported electronic SCFs converged and the pw.x step
itself ended with `JOB DONE`, but QE explicitly reported
`bfgs failed ... convergence not achieved` after 20 SCF / 19 BFGS steps. Its
last total force was 3.6e-5 Ry/bohr and largest force component approximately
1.097e-5 Ry/bohr. The workflow correctly treated the missing BFGS convergence
marker as a scientific failure even though the force was below the configured
5e-5 component ceiling: it published no pristine input/output, execution
manifest, or accepted structure gate. The failed attempt and its collection
record remain immutable. Any continuation must be a new attempt that starts
from explicitly hashed final coordinates and must still pass normal BFGS,
matched-pristine, atom-order, cell, symmetry, and force gates; the threshold
will not be loosened.

Local workflow development continued without running heavy science. The force
submission frontend now binds every task-map row to the matching manifest row,
real QE input path and SHA256, derives MPI ranks, walltime and material
concurrency from the immutable budget receipt, and distinguishes declared
pilot duplicates from unique production displacements. The campaign CLI now
has explicit preparation/audit entry points for signed pilot datasets and
budgeted force bundles, plus a compute-node-only one-task force runner. No
force array was submitted: production remains blocked on accepted structures,
real preflight counts, raw pilot evidence, recorded scientific selection and
an approved measured resource budget.

## 2026-09-10 — Session 11: both initial tight relaxations fail closed

At the 10:02 UTC read-only Nibi check, Rb2Cu2SnS4 primary job `21638193`
was terminal FAILED with exit `2:0`, and its afterany collector `21638194`
had completed. QE explicitly reported `bfgs failed ... convergence not
achieved` after 13 SCF / 12 BFGS steps. The last total force was
8.2e-5 Ry/bohr and the largest component reported by the strict parser was
2.331e-5 Ry/bohr. `relax.err` was empty; final coordinates preceded
`JOB DONE`; no separate QE, MPI, OOM, or time-limit fatal marker was found.
The output and run-manifest SHA256 anchors were
`e960376989bf0f11a7ca8c8b4e6cd3a4a328134d881e96752662b645780bd6a4`
and `e0fb981daee631ca2d8a3d4c07bc2e696d61bfad80672b7e7d3bab06e986d5d5`.
The collector recorded one finished upstream attempt with wrapper exit 2.
No pristine SCF, execution manifest, or accepted structure gate was created.

This leaves both new materials at the same strict boundary: their individual
SCFs and pw.x processes ended cleanly enough to expose complete final
coordinates, but neither ionic optimizer recorded normal BFGS convergence.
Low final forces alone are not accepted as convergence. Their original
attempts and collectors remain immutable. Any continuation must use a new
run directory, hash the source manifest/output, copy only small evidence and
coordinates, start from fresh QE scratch and atomic wavefunctions, and pass
the unchanged normal-BFGS, independent-pristine, cumulative-displacement,
cell, atom-order, force, and symmetry gates.

Local development did not run QE, phono3py force calculations, FC2/FC3, or
thermal-conductivity postprocessing. The signed initial-pilot path now requires
an exact six-SCF composition (two pristine, a single displacement plus an
independent duplicate, and a double displacement plus an independent
duplicate), replays raw selection evidence, binds task and scheduler identity,
and collects immutable Slurm accounting. The latest synthetic unit suite had
197 passing tests and one environment-only spglib skip. Automatic subset retry
and production calculations remain disabled; real Nibi spglib/phono3py and
Slurm-accounting smoke tests are still required before even the exploratory
pilot can be submitted.

## 2026-09-10 — Session 12: recovery path verified locally; Nibi MFA blocks live continuation

The next fail-closed step was implemented and tested without modifying either
original failed Nibi attempt. `relax_recovery.py` accepts only a separately
hashed, terminal BFGS-nonconvergence attempt whose QE process, force block,
final coordinates, atom order, fixed cell, pseudopotentials, Slurm identity,
wrapper failure, and source manifest all replay consistently. It creates one
new run directory, copies only immutable small evidence, starts QE from fresh
scratch with atomic potentials/wavefunctions, preserves the original accepted
geometry as the cumulative-displacement reference, and keeps the normal BFGS,
independent-pristine, force, symmetry, cell, atom-order, and displacement gates
unchanged. A second automatic reset is rejected and a failed recovery cannot
start the pristine calculation.

The full local suite passed **197/197 tests** in the project scientific Python
environment (Python 3.11.15, spglib 2.7.0, phonopy 4.3.1, phono3py 4.3.3),
including the real spglib synthetic-structure check. Both material configs
validated, Python compilation passed, every Slurm shell file passed `bash -n`,
and `git diff --check` found no whitespace errors. Two operator mistakes were
kept visible during validation: running unittest discovery from the repository
root omitted the campaign module from the import path, and the first config
check used the nonexistent subcommand `validate` plus then an incorrect
relative path. Re-running from the campaign directory with `validate-config`
and the correct paths passed; these were invocation errors, not workflow-code
failures.

A fresh read-only SSH query at approximately 14:18 UTC could not authenticate:
the local eight-hour ControlMaster socket was absent and Nibi required
interactive keyboard MFA. Consequently no current `squeue`, `sacct`, log, or
run-directory evidence was obtained, no recovery directory was prepared, and
no job was submitted. The last verified scheduler snapshot therefore remains
10:02 UTC: both original tight-relax primaries failed their BFGS gate and both
afterany collectors completed. The safe next action is to establish one
interactive authenticated Nibi session, deploy this reviewed code in a new
clean checkout, re-query Slurm and the source hashes, then prepare and submit
the two recovery runs separately.

**Scientific-rigor review.** No new calculated material property or stability
claim was made. The low forces in the failed relaxations are still not treated
as BFGS convergence; no pristine SCF, displacement, FC2/FC3, q-mesh, kappa_L,
NAC, SOC, PF/tau, or full-zT conclusion was produced. Frozen
`READY_TO_ATTACH/` records were untouched.

## 2026-09-10 — Session 13: authenticated Nibi recovery deployment and live launch

The user established an interactive Duo-authenticated Nibi SSH session; its
ControlMaster socket allowed subsequent noninteractive evidence checks. At
14:28 UTC `squeue` was empty. Explicit job-ID `sacct` queries reconfirmed the
original terminal states: relax jobs `21638193` and `21638199` FAILED with
exit `2:0`, while collectors `21638194` and `21638200` COMPLETED. The two
original `relax.out` hashes and run-manifest hashes matched the archived
handoff values for Rb2Cu2SnS4 and the collector evidence for SrZrS3. No old
job or run directory was reused.

A new clean checkout was created at
`/scratch/yuhansun/Waterloo-prof-Holger-phonons-recovery-20e079f`, fixed at
Git commit `20e079f`. Nibi's Python 3.11.5 environment with spglib 2.7.0,
phonopy 4.4.0, and phono3py 4.4.0 passed all **197/197** unit tests, both
material config validations, Python compilation, and Slurm shell syntax.

The recovery backend then replayed each raw failed attempt and created two new
immutable run directories below
`/scratch/yuhansun/phono3py-runs/20260910-recovery-20e079f/`. Rb2Cu2SnS4 was
bound to source job `21638193`, manifest SHA256
`e0fb981daee631ca2d8a3d4c07bc2e696d61bfad80672b7e7d3bab06e986d5d5`,
output SHA256
`e960376989bf0f11a7ca8c8b4e6cd3a4a328134d881e96752662b645780bd6a4`,
and recovery-receipt SHA256
`3f320714efd75a11b462e12da0c3af9f032df9d6f28e8e29d425ae26b753a074`.
SrZrS3 was bound to source job `21638199`, manifest SHA256
`0eb7c96aceb46c4232199afcebcabb708d21ee003c9e9bc954ac4f96688a1e4e`,
output SHA256
`babf637f09371ced6838dd41e13baaff1e7002614243a5de2ac60c615e69f6f7`,
and receipt SHA256
`34fbf5e8294e06f6776903b9fb355b5071f3ef0d4641d77f498a4351f45c20f1`.
Only small evidence and coordinates were copied; old QE scratch was not
copied or read as restart state.

Fresh plan/execute handshakes submitted two recovery chains under explicit
account `def-kleinke_cpu`:

- Rb2Cu2SnS4 primary `21656285`, attempt
  `20260910T143146Z-relax-1ecddf1b`; afterany collector `21656286`, attempt
  `20260910T143146Z-collect-d11e8ac9`.
- SrZrS3 primary `21656287`, attempt
  `20260910T143146Z-relax-519dab1c`; afterany collector `21656288`, attempt
  `20260910T143147Z-collect-be4bf4f7`.

At 14:34 UTC both primaries were RUNNING on compute node `c508`, each with 32
tasks, 62.5 GiB and a 12-hour limit; both collectors were PENDING on their
correct unfulfilled `afterany` dependencies. The inputs explicitly contain
`restart_mode='from_scratch'`, `startingpot='atomic'`, and
`startingwfc='atomic+random'`. QE reported 32 processor cores, both stderr
files were empty, Rb2Cu2SnS4 had reached SCF iteration 4, and SrZrS3 iteration
17 of the first ionic step. No fatal QE/MPI marker was present. These are only
launch-health observations; neither BFGS, pristine, nor the structure gate has
passed yet, and no preflight or force task was submitted.

**Scientific-rigor review.** The recovery retains the original cumulative
position-shift reference and all force, cell, atom-order, symmetry, and normal
BFGS requirements. No threshold or material-specific basis/k mesh was copied
between materials or relaxed. No new phonon, stability, kappa_L, NAC/SOC,
PF/tau, or zT claim was made, and every frozen `READY_TO_ATTACH/` record
remained untouched.

**14:38 UTC addendum.** SrZrS3 recovery `21656287` recorded normal BFGS
convergence in two SCF cycles / one BFGS step, followed by final coordinates
and `JOB DONE`; the wrapper then started its independent pristine SCF. The
pristine output was still growing, stderr remained empty, and neither the
execution manifest nor structure gate existed yet. Rb2Cu2SnS4 `21656285`
remained inside its first recovery SCF. Both Slurm primaries were still
RUNNING and both collectors remained correctly dependency-held, so no
preflight action was taken.

## 2026-09-10 — Session 14: SrZrS3 gate/preflight and Rb recovery boundary

Live Nibi evidence was re-queried rather than inferred from the previous job
snapshot. SrZrS3 recovery `21656287` and collector `21656288` both completed.
The recovery had normal BFGS convergence in 2 SCF cycles / 1 ionic step; the
setting-matched pristine SCF also converged and finished. The immutable
structure gate passed at 14:50 UTC: relax/pristine maximum force components
were `9.87e-6` and `1.046e-5 Ry/bohr`, respectively; maximum cumulative
position shift was `0.0018847721 A`; all 20 atoms and the fixed cell matched;
Pnma (#62) was retained at symmetry tolerances from `1e-6` to `1e-3 A`.
This accepts a structure for displacement preflight only, not for production
force or kappa claims.

The first SrZrS3 preflight, job `21657046`, failed closed in 34 seconds after
phono3py had generated the first candidate. The immediate error claimed a
violation of `A_super=M^T A`, but the matrix was correct. Direct reconstruction
found only one threshold exceedance: the generated 32.6590248211-bohr vector
differed from the configured-CODATA reconstruction by `2.147e-7 bohr`, just
above the old `2e-7` absolute tolerance. phono3py 4.4.0 uses approximately
`0.529177207424 A/bohr`, while the configuration explicitly uses
`0.529177210903 A/bohr`; their relative difference is about `6.6e-9`.

The preflight lattice gate now uses `1e-8` relative plus `2e-8 bohr` absolute
tolerance and records that tolerance in every result. A regression test uses
the actual failed SrZrS3 vectors and still rejects a `1e-5 bohr` wrong-matrix
perturbation. The preflight submission path was also corrected to consume the
accepted structure as immutable upstream evidence when downstream code changes;
new Slurm submissions and attempts still record their exact current script and
campaign-code hashes. A second submission attempt initially stopped before
`sbatch` because Nibi reports a just-finished job missing from `squeue` as
`Invalid job id specified`; the duplicate checker now treats only that exact
absence response as a reason to query `sacct`, while unrelated scheduler
errors remain blocking. Tests cover both cases.

The corrected code was pushed as `dd13471` and `0586c6b`, fast-forwarded into
the recovery checkout, and validated on both the Mac scientific environment
and Nibi: **201/201 tests passed**, both campaign configs validated, Python
compilation passed, all Slurm shell files passed `bash -n`, and `git diff
--check` passed. Two local invocation mistakes are retained here: the first
scientific-environment discovery command ran from the repo root without the
campaign module on `PYTHONPATH`, and the first config command used one `..`
too many. Correct reruns from the campaign directory passed; neither error was
a workflow or scientific failure.

Corrected SrZrS3 preflight `21657673` completed in 1m50s. Inventory SHA256 is
`3ff44af185f185f5d95648df5e53042f7d25f361d9b7577a8f7d3b7f8161f6ab`.
The exact generated displacement counts were:

- 3x2x1 (120 atoms), 4 A: 1379; 5 A: 2047; uncut: 11625.
- 4x2x1 (160 atoms), 4 A: 1379; 5 A: 2047; 6 A: 3747; uncut: 15225.

All five routine candidates contain nonzero pair groups and passed unit,
matrix, volume, atom-count, ID, amplitude, cutoff, and geometry checks, but
all exceed the configured 800-displacement hard cap. The inventory therefore
contains zero selection-eligible candidates and explicitly requires
scientific/resource review. No pilot or force task was submitted.

Rb2Cu2SnS4 recovery `21656285` failed with exit `2:0`; collector `21656286`
completed and archived the immutable evidence. QE completed four electronic
SCFs and pw.x returned zero with `JOB DONE`, but the optimizer printed
`history already reset at previous step: exiting` and explicit BFGS
nonconvergence after 4 SCF cycles / 3 BFGS steps. Total force decreased
`8.2e-5 -> 7.9e-5 -> 7.1e-5 -> 6.7e-5 Ry/bohr`; the final strict-parser
maximum component was `1.768e-5 Ry/bohr`. Stderr is empty and there is no
separate QE, MPI, OOM, or time-limit error. No pristine calculation or gate
was produced. The recovery output SHA256 is
`7203cb32b14c4c39aa450746993b240487ad7d6c65320eaf42c6ae120e85e118`.
Because the reviewed workflow permits only one automatic reset, a second
continuation is not authorized without scientific review.

**Scientific-rigor review.** No lattice thermal conductivity, FC2/FC3,
stability, NAC/SOC, PF/tau, or full-zT claim was produced. A successful pw.x
exit and low force were not substituted for normal BFGS convergence. SrZrS3
counts are preflight cost/geometry evidence only; they do not prove force,
cutoff, supercell, q-mesh, or kappa convergence. All `READY_TO_ATTACH/`
records remained unchanged.

## 2026-09-11 — Session 15: hourly check blocked by expired Nibi MFA session

The repository was resumed from `codex/two-material-phonons` at `c8dcb0b` only
after inspecting the local worktree and fetching GitHub.  The checkout was
clean and exactly matched `origin/codex/two-material-phonons` (ahead/behind
`0/0`).  Every `READY_TO_ATTACH/` directory remained unchanged.

A fresh read-only Nibi query at 04:18 UTC failed before any scheduler command
ran.  `ssh -O check drac` confirmed that
`/Users/kaede/.ssh/cm-yuhansun@nibi.alliancecan.ca-22` did not exist, and Nibi
rejected batch authentication because interactive MFA was required.  Therefore
this session obtained no current `squeue`, `sacct`, job-log, or run-directory
evidence and did not infer live state from the historical job IDs.  No remote
directory was prepared and no job was submitted or rerun.  The last verified
remote snapshot remains 2026-09-10 15:11 UTC: SrZrS3 had passed its structure
gate but every declared preflight candidate exceeded the 800-task cap, while
Rb2Cu2SnS4 had exhausted the reviewed one-reset BFGS recovery path without a
passing structure gate.

Local lightweight validation used the scientific Python 3.11.15 environment
with spglib 2.7.0, phonopy 4.3.1, and phono3py 4.3.3.  The campaign suite passed
**201/201 tests**.  Both material configs validated healthy while retaining
their null production selections; Python compilation, all Slurm `bash -n`
checks, and `git diff --check` passed.  One operator invocation error is kept
visible: the first config validation omitted the required `--config` option;
the correctly formed rerun passed for both materials.  This was not a workflow
or scientific failure.

**Scientific-rigor review.** No new force, force constant, phonon, stability,
q-mesh, kappa_L, NAC/SOC, PF/tau, or zT evidence was produced.  SrZrS3's
preflight counts remain cost/geometry evidence only, and Rb2Cu2SnS4's low final
force remains insufficient to replace normal BFGS convergence.  A new SrZrS3
cutoff/supercell choice cannot be justified from the repository summary alone
without the accepted remote geometry and shell inventory; a second Rb ionic
continuation requires an explicit reviewed strategy.  The immediate operator
action is to re-establish one interactive Nibi MFA session so the next hourly
run can obtain live evidence before any further decision or submission.

## 2026-09-11 — Session 15: hourly live check blocked by renewed Nibi MFA

Git was fetched before interpreting state. The local and remote
`codex/two-material-phonons` branches both resolved to `c8dcb0b`, the working
tree was initially clean, and every `READY_TO_ATTACH/` path was unchanged.
At 04:17 UTC the configured Nibi ControlMaster socket was absent; a batch-mode
SSH connection was rejected at the mandatory keyboard-interactive/Duo step.
No scheduler command ran, so this session obtained no current `squeue`,
`sacct`, job-log, or run-directory evidence and did not relabel the 2026-09-10
15:11 UTC terminal snapshot as live state. No relaxation, preflight, pilot,
force, FC2/FC3, or kappa job was submitted.

Local validation in the scientific environment passed **201/201 tests**, both
material configuration checks, Python compilation, Slurm shell syntax, and
`git diff --check`. The suite includes strict last-complete-force parsing,
setting-matched pristine subtraction, ordered residual-corrected force-product
reconstruction, and `--cfz` gates. One shell-validation invocation failed only
because zsh expanded an absent `slurm/*.sh` glob; the corrected null-glob loop
passed and this did not reflect a workflow-code failure.

SrZrS3 remains at a passed structure gate with all five declared routine
preflight candidates above the 800-displacement cap (1379--3747; 0/5 eligible).
Rb2Cu2SnS4 remains without an accepted structure after the permitted one-reset
recovery failed normal BFGS convergence. The next live evidence check requires
one user-authenticated Nibi login; a second Rb ionic continuation and a new Sr
cutoff/supercell/resource plan remain scientific decisions, not automatic
retries.

**Scientific-rigor review.** This was monitoring and software validation, not
a material calculation. No new force, phonon, stability, cutoff, supercell,
q-mesh, NAC/SOC, kappa_L, PF/tau, electronic-only zT, or full-zT conclusion was
produced. Low terminal forces still do not replace normal BFGS convergence,
and preflight counts remain cost/geometry evidence only. Frozen attachment
records were not modified.

## 2026-09-11 — Session 15: hourly live check blocked by renewed Nibi MFA

The repository was fetched first; local and remote
`codex/two-material-phonons` both resolved to `c8dcb0b`, with frozen
`READY_TO_ATTACH/` records unchanged. At 04:16 UTC the previous Nibi
ControlMaster socket was absent and batch-mode SSH was rejected at the
mandatory keyboard-interactive/Duo step. No scheduler command ran, so this
session obtained no current `squeue`, `sacct`, job-log, or run-directory
evidence and did not relabel the 2026-09-10 terminal snapshot as live state.
No job was submitted.

Local lightweight validation passed **201/201 tests**, both material config
checks, Python compilation, Slurm shell syntax, and targeted regressions for
the last complete QE force block, setting-matched pristine input, and the
ordered residual-corrected `--cfz` force product. Production remains blocked:
SrZrS3 has zero candidate below the 800-displacement cap, and Rb2Cu2SnS4 has
no accepted structure after its allowed one-reset recovery.

**Scientific-rigor review.** No new force, phonon, stability, cutoff,
supercell, q-mesh, NAC/SOC, kappa_L, PF/tau, electronic-only zT, or full-zT
claim was made. Low terminal force still does not replace normal BFGS
convergence; preflight counts remain cost/geometry evidence only. A fresh live
query requires a user-authenticated Nibi SSH session.

## 2026-09-11 — Session 15: hourly check blocked by renewed Nibi MFA

At 04:18 UTC, a fresh fetch confirmed that local branch
`codex/two-material-phonons` and its upstream both pointed to `c8dcb0b`.
All four frozen `READY_TO_ATTACH/` directories had no staged, unstaged, or
untracked changes. A noninteractive `ssh drac` query reached Nibi but was
rejected because keyboard-interactive multifactor authentication was required;
therefore this run obtained no current `squeue`, `sacct`, scheduler-log, or
remote-product evidence. The authentication failure is not evidence of an
empty queue or an unchanged remote state.

No relax, preflight, pilot, force array, FC2/FC3 construction, or kappa
postprocessing was submitted or rerun. The last verified scientific boundary
remains the 2026-09-10 evidence: SrZrS3 passed its structure gate, but all five
routine preflight candidates require 1379--3747 displacement supercells and
exceed the 800-task cap; Rb2Cu2SnS4 exhausted the one reviewed recovery reset
without normal BFGS convergence. An interactive `ssh drac` login is required
before live evidence can be refreshed. Neither a second Rb ionic continuation
nor a revised Sr cutoff/supercell/resource choice is authorized by this check.

Local read-only validation used the project scientific Python environment:
201/201 unit tests passed, both material configs validated as healthy while
retaining `production_blocked_pending_selection=true`, Python compilation and
all Slurm shell syntax checks passed, and `git diff --check` passed. This
validates the current residual-force parser and pristine/`--cfz` gates at the
test level only; it is not new force or thermal-conductivity evidence.

**Scientific-rigor review.** No new material property, convergence, stability,
NAC/SOC, PF/tau, electronic-only zT, or full-zT conclusion was made. Historical
job IDs and low residual forces were not promoted to current or successful
evidence, and all frozen attachments and raw research records remained
untouched.

## 2026-09-11 — Session 15: hourly live check blocked by expired Nibi MFA session

The hourly task fetched all Git remotes and confirmed that
`codex/two-material-phonons` and its upstream were both at `c8dcb0b`, with no
pre-existing worktree changes. No path under any `READY_TO_ATTACH/` directory
was modified.

A first SSH query used the nonexistent local alias `nibi` and failed during
hostname resolution; the configured alias was then verified as `drac` for
`yuhansun@nibi.alliancecan.ca`. At 04:16 UTC, a batch-mode query through that
correct alias reached Nibi but was rejected because the ControlMaster socket
had expired and interactive keyboard MFA was required. `ssh -O check drac`
independently confirmed that the socket did not exist. Therefore this session
obtained no new live `squeue`, `sacct`, job-log, or run-directory evidence and
did not assume that the previous empty-queue snapshot was still current.

No relaxation, preflight, pilot, force array, FC2/FC3 build, or kappa
postprocessing was prepared, submitted, or rerun. The last verified evidence
remains the 2026-09-10 15:11 UTC snapshot: SrZrS3 has a passing structure gate
but all five candidates exceed the 800-displacement cap; Rb2Cu2SnS4 exhausted
the single reviewed reset path without normal BFGS convergence. An interactive
`ssh drac` login is required before the next monitor can refresh Slurm and
immutable attempt evidence. Neither a second Rb continuation nor a changed Sr
cutoff/supercell/resource choice is automatically authorized.

**Scientific-rigor review.** No new property, convergence, stability, NAC/SOC,
PF/tau, electronic-only zT, or full-zT conclusion was made. Historical job IDs
and low forces were not promoted to current or successful evidence, and frozen
attachments remained untouched.

### Session 15 reconciliation note

Several hourly automation instances overlapped and appended separate Session 15
descriptions of the same 04:16--04:18 UTC authentication attempt. Treat those
entries as one monitoring event, not as independent scheduler checks: all reached
the same expired-ControlMaster/Duo blocker, obtained no live Slurm or remote-file
evidence, ran only local validation, and submitted no job. This note preserves
the append-only history while preventing the duplicate prose from being counted
as repeated scientific evidence.

## 2026-09-11 — Session 16: 09:12 UTC hourly check remains MFA-blocked

The repository was fetched before interpreting state. The clean local
`codex/two-material-phonons` branch and its upstream both resolved to
`48395a2`; no tracked or untracked path under any of the four
`READY_TO_ATTACH/` directories had changed.

A new read-only Nibi connection attempt at 09:12 UTC did not reach a remote
shell. `ssh -O check drac` reported that the configured ControlMaster socket
did not exist, and a batch-mode connection was rejected at the mandatory
keyboard-interactive multifactor-authentication step. Consequently no current
`squeue`, `sacct`, job-log, or remote-product evidence was obtained. This is
not evidence that the queue is empty or that the remote state is unchanged,
and no historical job ID was presented as live. No relaxation, preflight,
pilot, force, FC2/FC3, q-mesh, or kappa job was prepared, submitted, or rerun.

Local lightweight validation used Python 3.11.15 with spglib 2.7.0, phonopy
4.3.1, and phono3py 4.3.3. All **201/201 tests** passed, including the strict
last-complete-force parser, setting-matched pristine-force checks, ordered
residual-corrected force reconstruction, and `--cfz` gates. Both material
configs validated healthy while retaining
`production_blocked_pending_selection=true`; Python compilation, every Slurm
shell syntax check, and `git diff --check` passed. Two operator invocation
errors are retained: the first config-validation rerun used a path one level
too high and failed before reading the JSON, and the first shell loop let zsh
expand an absent `slurm/*.sh` glob. Corrected commands passed; neither was a
workflow-code or scientific failure.

The last verified remote boundary therefore remains 2026-09-10 15:11 UTC.
SrZrS3 has a passing structure gate and audited counts for all five routine
candidates, but **0/5** are selection-eligible under the 800-displacement cap
(1379, 2047, 1379, 2047, and 3747). Rb2Cu2SnS4 still has no accepted structure
after the original and permitted one-reset attempts both failed normal BFGS
convergence; its low last force component does not replace that missing
optimizer criterion. An interactive `ssh drac` login is required before the
next live refresh. A revised SrZrS3 cutoff/supercell/resource choice and any
second Rb ionic continuation remain separate scientific decisions and were not
authorized by this monitoring run.

**Scientific-rigor review.** This run produced no new calculated material
property, force, phonon, stability, cutoff, supercell, q-mesh, NAC/SOC,
kappa_L, PF/tau, electronic-only zT, or full-zT conclusion. Preflight counts
remain geometry/cost evidence only, low forces were not promoted to BFGS
convergence, raw records were preserved, and every frozen attachment remained
untouched.

## 2026-09-11 — Session 17: independent continuation worktree and audited local preparation

At the user's request, continuation work moved to the new worktree
`/Users/kaede/research/Waterloo-Holger-remaining-phonons` on branch
`codex/remaining-two-phonons`, based on verified active-branch commit
`5fdd4a16924f48df4cfe1c83303d47b0cc323240`. Local implementation commit
`e524d6e` prepares evidence-gated continuation for SrZrS3 and Rb2Cu2SnS4; it
does not launch QE, phono3py, or any scheduler job.

The completed SrCu2SnS4 work was audited as experience, not accepted as a
numerical template. Its retained calculation is a historical first pass: the
4.0 cutoff is in bohr (about 2.12 Angstrom), the pristine calculation did not
finish healthily, only 154 of 168 force outputs satisfy the strict completion
criteria, force settings are mixed, and the corrected q-mesh ladder does not
meet the current every-diagonal, every-temperature, two-step convergence
contract. Therefore no SrCu2SnS4 cutoff, supercell, force, residual, or mesh
threshold was silently transferred to the remaining materials.

SrZrS3's historical one-reset recovery remains the only accepted structure
source: it has normal BFGS completion, an independent healthy pristine SCF,
maximum terminal force components of 9.87e-6 and 1.046e-5 Ry/bohr, a
0.0018847721-Angstrom cumulative shift, and Pnma symmetry. Its five existing
preflight counts (1379, 2047, 1379, 2047, and 3747) all exceed the current 800
displacement cap, so none is production-eligible. The new 2x1x1/3.70-Angstrom
and 3x1x1/3.70-Angstrom candidates are explicitly count-only hypotheses. A
new accepted-structure importer now replays and archives the full recovery
lineage into a fresh self-contained run before any current-policy preflight;
the old run cannot be mutated or used directly.

Rb2Cu2SnS4 still has no accepted structure. Both the original job 21638193
and the permitted one-reset job 21656285 ended with explicit BFGS
nonconvergence; their low terminal forces are not optimizer convergence. The
prepared next step is a fixed-geometry three-SCF diagnostic with two identical
100/800-Ry inputs and one 100/1000-Ry input in separate scratch directories.
Only a passing, reviewed diagnostic can release at most one fresh
small-trust-radius BFGS polish, which must still be followed by normal BFGS,
pristine, and structure-gate evidence. No automatic reset or submission is
enabled.

The shared workflow now also has a force-finalization gate that replays the
exact production plan, task map, submissions, accounting, raw outputs,
backend hashes, and resource-budget ledger before publishing a force-dataset
receipt. It validates readiness to construct FC2/FC3 only; it does not claim a
phonon or kappa result. A distinct fresh review finished with verdict `ship`
after symlink, ledger-rewrite, task-map, imported-run, and final-coordinate
regressions were closed. The focused security suite passed 8/8 tests and the
full suite passed 259/259 tests with one optional-spglib skip. Both material
configs validate healthy while retaining null production selections, disabled
automatic submission, and null approved core-hour budgets; Python compilation,
Slurm shell syntax, and Git whitespace checks also pass.

Live Nibi state was not refreshed: the read-only SSH attempt reached the
mandatory MFA boundary and produced no scheduler or remote-artifact evidence.
The latest verified remote boundary remains 2026-09-10 15:11 UTC. No remote
import, diagnostic, relaxation, preflight, pilot, force, FC2/FC3, q-mesh, or
kappa work was run. The former hourly automation was removed, and future
continuation is manual and user-directed.

**Scientific-rigor review.** This session created local workflow controls and
an audited continuation plan, not a new calculated material result. Production
choices remain unapproved, public postprocessing and final audit remain
unreleased, no historical failure was reclassified as success, and every
`READY_TO_ATTACH/` directory and frozen raw record remained untouched.

## 2026-09-11 — Session 18: signed gate submissions and preserved Rb startup failure

The user explicitly authorized Nibi submission after the local continuation
plan. The former hourly automation was confirmed absent; this session used
only direct, manual checks. Before submission, the implementation was expanded
to bind exact preflight subsets, diagnostic resources, immutable
pseudopotentials, Slurm submission/collector records, runtime scripts,
terminal accounting, and symlink-safe paths. A fresh independent Sol review
returned `SHIP`. Local validation passed 290 tests with one optional-spglib
skip, both material configs, Python compilation, all Slurm shell syntax, and
`git diff --check`. The reviewed implementation was committed and pushed as
`4e9b64c`.

The Nibi ControlMaster session was live at 12:53 UTC and the user's queue was
empty. A clean detached clone was created at
`/scratch/yuhansun/Waterloo-prof-Holger-remaining-phonons-4e9b64c`, and the
exact commit passed the same 290-test suite plus both config and shell checks
on Nibi. The first preparation invocation used the system `python3` and
stopped before creating the run root because that interpreter lacked
`spglib`. The corrected invocation used the fixed
`/home/yuhansun/venvs/p3/bin/python` environment (spglib 2.7.0, phonopy 4.4.0,
phono3py 4.4.0) and prepared fresh, self-contained SrZrS3 and Rb2Cu2SnS4 run
directories from reverified source hashes.

SrZrS3 count-only preflight job `21730034` completed with exit `0:0` in 20
seconds. Its signed subset contained only
`sr_fc3_2x1x1__sr_cutoff_3p70A` and
`sr_fc3_3x1x1__sr_cutoff_3p70A`. Each candidate generated 1003 displacement
supercells; the corresponding uncontracted counts were 4025 and 5825. Both
exceed the 800-displacement hard cap and remain selection-ineligible. The
inventory intentionally records `requested_scope_complete=true` while
`preflight_complete=false` and `full_config_preflight_complete=false`, so it
cannot release pilot or production work. No force calculation ran.

The first Rb2Cu2SnS4 diagnostic job `21730035` failed with exit `1:0` after 3
seconds, before any SCF or `diagnostic_execution.json` existed. Its preserved
stderr is exactly the Alliance profile's nounset failure for
`SKIP_CC_CVMFS`. Afterany collector `21730036` completed, correctly recorded
an incomplete/no-gate result, and exposed a second technical defect: the
deliberately cleaned PATH did not contain Nibi's `sacct`, so accounting was
recorded with code 127. The one-shot dispatch claim consumed that run
directory as designed. It was not reused, deleted, or relabeled as a
scientific attempt.

The minimal hotfix temporarily disables nounset only while sourcing the
external Alliance profile, restores the caller's shell options on success and
failure, and calls trusted `/opt/software/slurm/bin/sacct` directly. Added
regressions reproduce both live faults. Local validation then passed 293 tests
with one optional-spglib skip, and fresh Sol review again returned `SHIP`.
The fix was committed and pushed as `f557d02`; a new clean detached Nibi clone
passed all 293 tests in the phono3py environment, with both runtime and config
checks clean.

A wholly new Rb lineage was prepared under
`/scratch/yuhansun/phono3py-runs/20260911-continuation-f557d02/Rb2Cu2SnS4`
from the same reverified failed-recovery source hashes. Diagnostic job
`21731206` and afterany collector `21731207` were submitted at 13:06 UTC. At
the final submission snapshot the diagnostic was `RUNNING` on one Nibi node
with 32 tasks, 2000 MB per task, and a two-hour ceiling; the collector was
dependency-pending. No diagnostic finalization, BFGS polish, structure gate,
preflight, force array, FC2/FC3 construction, q-mesh, or kappa calculation was
released from this Rb run.

**Scientific-rigor review.** Sr's new values are displacement counts and
resource-screening evidence only. Rb's first dispatch is a documented
technical startup failure, while the replacement diagnostic is still a
running fixed-geometry force-consistency test at this snapshot. Neither is a
new phonon, stability, force-constant, kappa_L, PF/tau, electronic-only zT, or
full-zT result. A successful Slurm state alone cannot authorize a report:
collector evidence and scientific gates must pass, followed by the full
material-specific force/FC2/FC3/q-mesh pipeline. The historical SrCu2SnS4
baseline also remains a first-pass, unconverged reference under the current
stricter contract. Frozen attachments and raw records were unchanged.

## 2026-09-11 — Session 19: Rb Slurm-step repair and live diagnostic launch

This entry supersedes Session 18's live Rb snapshot without rewriting its
historical evidence. Diagnostic job `21731206` from commit `f557d02` did not
run an SCF: it stopped after 6 seconds because Nibi did not provide a usable
`SLURM_TIMELIMIT` variable. Its collector `21731207` completed and bound the
terminal accounting (`FAILED`, exit `2:0`, 32 CPUs, 62.50G requested memory,
120-minute scheduler limit) into an incomplete/no-gate record. Commit
`2a58b59` added a signed 120-minute request fallback for the missing runtime
variable while retaining terminal `sacct TimelimitRaw` as authoritative.

The resulting fresh diagnostic job `21731419` also stopped before a scientific
SCF. The batch shell loaded Quantum ESPRESSO successfully, but all 32 tasks in
the nested `srun pw.x` step reported `execve(): pw.x: No such file or
directory`; the process receipt records return code 2 and empty stdout. Job
accounting is `FAILED/2:0` after 9 seconds, and collector `21731420` completed
with an immutable incomplete/no-gate report. The exact cause was Slurm's
inheritance of the submission-side finite `--export` policy into job steps:
the batch shell saw the module-added QE path, while the nested step did not.

Commit `cf0b1d1` fixes only that boundary. The login-to-batch submission remains
an explicit allow-list; inside the sanitized batch environment,
`SLURM_EXPORT_ENV=ALL` is forced and read-only so `srun` receives the fixed
module and virtualenv environment. New tests reproduce a restricted initial
export, module load, virtualenv activation and `srun pw.x`; they also preserve
failure when the module lacks QE and confirm that callers still cannot inject
an all-environment sbatch export. The full local suite passed 298 tests with
one optional-spglib skip; Python compilation, shell syntax and whitespace
checks passed. Fresh independent Sol review returned `SHIP`. A clean detached
Nibi clone at
`/scratch/yuhansun/Waterloo-prof-Holger-remaining-phonons-cf0b1d1` passed all
298 tests in `/home/yuhansun/venvs/p3`.

Two one-core, non-scientific Slurm smoke records were retained. Job `21732162`
failed a test-script assertion that required a literal `LD_LIBRARY_PATH`, even
though its `srun /usr/bin/env` step completed; that variable is not required
when the linked runtime is otherwise resolvable. The corrected smoke job
`21732191` completed `0:0` in 7 seconds. Its job step resolved
`/cvmfs/.../quantumespresso/7.3.1/bin/pw.x`, and `ldd` showed no missing linked
library. No QE material calculation was run by either smoke test.

The original failed-recovery source hashes were reverified unchanged before a
new lineage was prepared:

- source run manifest:
  `888994ffd904adafcf4bf2de816edab7adffe1722eda55ce4badf94b55202021`;
- source `relax.out`:
  `7203cb32b14c4c39aa450746993b240487ad7d6c65320eaf42c6ae120e85e118`;
- new lineage:
  `c28d1f118fbbb16b54c0d341e0796441e4b1414ad30a71ba6e46e1cf503ed34d`;
- new baseline and higher-ecutrho inputs:
  `aea7a2819a03b2ca3785229c40a715dbde8473bc1245cdfd25b206ac12f1f7ad`
  and
  `156338eaf4b13f43c476445b357ee0ccd5e789f3b970f5c01042bcc177be09bd`.

The run root is
`/scratch/yuhansun/phono3py-runs/20260911-continuation-cf0b1d1/Rb2Cu2SnS4`.
Diagnostic job `21732222` and afterany collector `21732223` were submitted at
13:31 UTC. At the 13:32 UTC snapshot, the diagnostic was `RUNNING` with 32
tasks, 2000 MB per task and a two-hour limit; the collector was
dependency-pending. `baseline-a/scf.out` was about 41 KB and showed QE had
initialized the grids, memory and electronic calculation, while `scf.err` was
empty. This is the first current diagnostic attempt verified to have entered
QE; it is not yet a completed or passing diagnostic.

**Scientific-rigor review.** None of the three failed Rb attempts is a material
result, and a running fourth attempt is not a result either. Even a passing
three-SCF diagnostic can only support a separate decision on one BFGS polish;
it cannot accept the structure. SrZrS3 remains blocked because both new
count-only candidates require 1003 displacements and exceed the 800 cap. No
new force dataset, FC2/FC3, phonon stability result, q-mesh convergence,
kappa_L, PF/tau, electronic-only zT or full zT was produced. No polish,
preflight, production or postprocessing stage was automatically released, no
hourly automation was created, and frozen attachments remained unchanged.

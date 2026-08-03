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

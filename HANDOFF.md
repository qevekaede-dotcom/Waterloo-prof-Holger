# Session handoff — current state and what's next

A snapshot so a fresh session can pick up without re-deriving anything. The
standing rules are in `CLAUDE.md` (auto-loaded); the beginner tutorial is
`WORKFLOW_EXPLAINED.md`; the hands-on curriculum is `learning/`. This file is
just "you are here + do this next".

## Where things stand (all verified on disk)

- The workspace is a git repo pushed to the **public** GitHub repo
  `qevekaede-dotcom/Waterloo-prof-Holger` (made public on request; private
  group material stays local-only). QE scratch (`**/tmp/`, `*.wfc*`,
  `*.save/`) and the unrelated law-coursework folder are gitignored. After
  finishing a task, commit and push.

- **All three first-pass workflows are COMPLETE**: SrCu2SnS4, SrZrS3,
  Rb2Cu2SnS4. Each has its own convergence tests, vc-relax, final SCF, dense
  NSCF, BoltzTraP2, and `results/workflow_summary.md`.
  - Sampled PBE gaps [calculated]: 0.3445 / 0.6096 / 0.7811 eV.
  - Favored carrier on the sampled grid: p (SrCu2SnS4), n by zT_e (SrZrS3),
    p (Rb2Cu2SnS4). Full comparison: `learning/05_comparing_materials.md`.
- **Reported to Roy and approved.** Two deliverable packages were sent as one
  combined email (Folder 1 + Folder 2) and are now **frozen**:
  - `second step result (DOS and Seebeck)/` — SrCu2SnS4 QE-vs-BoltzTraP2 DOS
    comparison + Seebeck(mu) figure.
  - `third step result (three-material first pass)/` — the three-material
    comparison. (`first step result (submission_to_roy)/` = the original
    SrCu2SnS4 submission.)
  - Do NOT edit any `READY_TO_ATTACH/`; they record exactly what was sent.
- No background compute is running. The temporary `folder1.zip`/`folder2.zip`
  were removed after sending.
- Roy approved a computational focus (no wet-lab obligation). A separate
  administrative email about wet-lab-in-4th-year + volunteer forms was drafted
  in chat (not a package).

## THE CURRENT TASK — phonons via phono3py (IN PROGRESS, 2026-07-13)

Roy's ask (see `thermo_candidates/Roy_task_status.md`): professor recommended
**phono3py**; Roy could not get it to run; deliverable includes a "how we got
it working" writeup packaged as `fourth step result (phono3py lattice thermal
conductivity)/` (folder + WORKLOG.md already exist — the WORKLOG has the full
story so far, including the failed attempts).

**State right now** (verify on disk before acting):
- phonopy 4.3.1 + phono3py 4.3.3 installed via pip wheels in `thermo-bt2` —
  install was trivially easy; the traps were elsewhere. phono3py 4.x moved
  setup commands to `phono3py-init`; QE cell needed `--tolerance 1e-3` or
  symmetry collapsed to P1 (83k displacements instead of 168).
- Displacement set generated: SrCu2SnS4, 2x2x1 supercell (96 atoms),
  cutoff-pair 4.0 A -> **168 force calculations**, P3_121 confirmed.
- Full automation in `thermo_candidates/SrCu2SnS4/phono3py/scripts/`
  (see that folder's README.md): `run_campaign.sh` = resumable driver
  (stage 0 k-mesh/cutoff force checks -> stage 1 all 168 SCFs -> stage 2
  FORCES_FC3 + q-mesh ladder + kappa_L 300-900 K into `../results/`).
- **Windows workstation: local env COMPLETE (2026-07-21).** WSL2 Ubuntu
  24.04 on the Ryzen 9800X3D box; conda env `thermo` (QE 7.5 + OpenMPI,
  phonopy/phono3py 4.4.0, h5py), SSSP 1.3.0 precision verified against the
  manifest, repo cloned at `~/Waterloo-prof-Holger`. Local QE runs need
  `QE_NP=6` (the conda OpenMPI counts the 6 physical cores WSL exposes).
  Smoke-tested end to end; WORKLOG Session 2 has the details. The campaign
  does NOT run here — and since 2026-08-21 the user's local compute is
  committed elsewhere, so stage-2 postprocessing moved onto the cluster
  too: local machines do prep, file transfer, git, and writeup only.
- **CAMPAIGN runs on DRAC — do not launch locally.** The disp-00001
  benchmark showed >= 2 h per force calculation on the laptop (1-2 weeks per
  material), and the professor has now authorized a Digital Research
  Alliance account under the group allocation, which supersedes the
  resources-email question. The SLURM port is DONE: `scripts/slurm/`
  (stage0 sbatch reusing run_campaign.sh via its new STOP_AFTER hook ->
  168-task array -> stage2 gate + postprocess, chained by `submit_all.sh`)
  plus a student-oriented walkthrough in `DRAC_SETUP.md`. SSH key pairs for
  the cluster exist in the workstation WSL and on the Mac (both named
  `~/.ssh/id_ed25519_drac`); the Mac public key was handed to the user to
  paste into CCDB. **Account details confirmed from CCDB (2026-08-03):**
  role active (sponsored by the professor, expires 2027-06-15), allocation
  `ACCOUNT=def-kleinke` now filled in `scripts/slurm/cluster.env` (RAP
  asw-382-aa, "8 active allocations - No RAC" = default share on any
  general-purpose cluster). The login username lives in the local
  `~/.ssh/config` (`Host drac`) on both machines, deliberately not in this
  public repo.
- **CAMPAIGN RESUBMITTED ON NIBI (2026-08-21): stage0 = job 20213855,
  stage1 168-task array = job 20213856 (afterok-chained), and stage2 now
  runs on the cluster as well** (chained after the array; the at-home
  stage2 plan is dead — local compute is committed elsewhere). The FIRST
  submission (2026-08-03, jobs 19030260/19030261) computed NOTHING in 18
  days: the Alliance QE module is an MPI+OpenMP hybrid and no thread cap
  was set, so 32 ranks x ~11 threads thrashed the 32-core allocation
  ("running on 352 processor cores"); stage0 hit its 10 h TIMEOUT still
  on SCF iteration 7 of the first benchmark, and stage1 sat at
  DependencyNeverSatisfied. Fix: `export OMP_NUM_THREADS=1` in
  cluster.env + 12 h caps (WORKLOG Session 4). The Session-3 wheelhouse
  trap (pip pins phono3py to 3.25, no phono3py-init) is bypassed with
  `PIP_CONFIG_FILE=/dev/null pip install 'phono3py==4.3.3' h5py` into
  `~/venvs/p3` (DRAC_SETUP.md section 3), so stage2 runs the SAME 4.3.3
  that generated the dataset. When kappa_L lands in the cluster's
  `SrCu2SnS4/results/`: rsync everything home with `--exclude 'scripts/'`
  (the Nibi clone carries local script edits; `git checkout -- ...scripts/`
  there before any future pull) and commit — transfer and git only, no
  local compute. Traps already burned: per-cluster activation at
  ccdb.alliancecan.ca/me/access_systems was the "connection closed"
  cause; Nibi needs an explicit partition (cpubase_bycore_b2) and the
  `_cpu` account variant. Monitor with `sacct -j 20213855` /
  `sacct -j 20213856` over `ssh drac` (ControlMaster gives 8 h of
  Duo-free reuse after one interactive login) — and check within a day
  of any submission, not 18 days later.
- After kappa_L lands: package the fourth step result, update
  `learning/08_phonons_and_kappa_L.md` [pending] sections, run the rigor
  review, THEN scale to SrZrS3 / Rb2Cu2SnS4 (each with its own convergence
  decisions).
- The CV (`~/Desktop/CV_Yuhan Sun_updated.docx/.pdf`) already lists this
  phonon work as "currently building"; phono3py is deliberately NOT yet in
  the Skills list — add it once kappa_L actually lands.

## Machine + tooling gotchas (learned this session — reuse them)

- Activate everything with: `source "$HOME/scientific-tools/env/thermo-bt2.sh"`
  (conda env `thermo-bt2`; QE binaries under `~/scientific-tools/apps/qe`).
- Hardware: Apple **M5 Pro, 18-core CPU, 24 GB unified memory**. Run QE with
  `QE_NP=12 QE_NK=2` (12 MPI ranks, 2 k-point pools) and leave headroom; more
  than ~2 pools risks the 24 GB limit. The 20-core GPU is useless for this QE
  (GPU accel is CUDA/NVIDIA-only).
- Wrap long runs in `caffeinate -i` so idle sleep doesn't throttle them; a
  **closed lid still sleeps** — tell the user to keep it open on mains power.
- Run heavy QE in the **background** and continue when the task-notification
  fires. Health-check every step: `JOB DONE`, electron-count vs pseudo-valence
  arithmetic, symmetry kept, volume drift <~1%, pressure plateau.
- The pre-made per-material `boltztrap2/run_bt2.sh` template ships with THREE
  bugs every time (qe_source path missing `/final`; bare `btp2` crashes under
  NumPy 2 -> use `btp2_compat.py`; half-open `300:900:100` and through-zero
  `-1e21:1e21:1e20` ranges). Fix before running; see any material's
  `boltztrap2/run_bt2.sh` for the corrected form.

## Rules that bite (from CLAUDE.md — do not relearn the hard way)

Never call PF/tau an absolute power factor; never call zT_e the final zT;
state no-SOC; "best" = best on the sampled grid; convergence params are
per-material (never copied). Keep raw outputs immutable; derived tables go in
`results/`. Tag values [calculated]/[database]/[experimental], units in every
header. Anything sent to Roy uses the modest first-person student voice.
Run the scientific-rigor self-review after every task.

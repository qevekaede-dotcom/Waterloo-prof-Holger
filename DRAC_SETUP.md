# Running the phono3py campaign on a Digital Research Alliance cluster

Goal: the 168 force calculations (and the checks around them) run on a
Digital Research Alliance of Canada (DRAC) cluster instead of a laptop or
workstation. The professor has authorized an account under the group's
allocation. Local machines (Mac / Windows-WSL) keep doing preparation,
small tests, and the writeup; the cluster does the heavy compute.

Plain-language picture: you `ssh` into a **login node** (a shared computer
for editing files and submitting work — never for running QE itself), hand
your jobs to the **SLURM scheduler** with `sbatch`, and SLURM runs them on
**compute nodes** when resources free up. Everything below is one-time setup
plus three commands.

## 1. One-time: account, MFA, SSH key

1. Confirm the CCDB account is active: log in at https://ccdb.alliancecan.ca
   with the credentials created during registration. The professor's approval
   of the role request is what activates it.
2. Enroll multi-factor authentication (Duo) in CCDB if not already done —
   logins require it.
3. Upload the SSH public key. On the Windows workstation the key pair was
   generated in WSL at `~/.ssh/id_ed25519_drac` / `~/.ssh/id_ed25519_drac.pub`
   (no passphrase — regenerate with one if preferred:
   `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_drac`). In CCDB:
   My Account -> Manage SSH Keys -> paste the contents of the `.pub` file.

## 2. One-time: pick a cluster and log in

General-purpose clusters (any of them can run this campaign; use the one the
professor's allocation points at — ask if unsure). Verify current hostnames
and status at https://status.alliancecan.ca:

| Cluster  | Login host              | Note                          |
| -------- | ----------------------- | ----------------------------- |
| Nibi     | nibi.alliancecan.ca     | SHARCNET (Ontario — closest to Waterloo) |
| Fir      | fir.alliancecan.ca      | Simon Fraser (BC)             |
| Rorqual  | rorqual.alliancecan.ca  | Calcul Québec                 |
| Narval   | narval.alliancecan.ca   | Calcul Québec                 |

A matching `Host drac` entry template is in the WSL `~/.ssh/config`; fill in
the DRAC username and chosen host, then:

```sh
ssh drac
```

First login asks for the CCDB password + Duo confirmation; afterwards the key
takes over.

## 3. One-time: set up the workspace on the cluster

All on the login node. The repo is public, so cloning needs no credentials.
Work under `~/scratch` (fast, but **purged after ~60 days of inactivity** —
results must be brought home promptly, see section 7).

```sh
# workspace
cd ~/scratch
git clone https://github.com/qevekaede-dotcom/Waterloo-prof-Holger.git
cd Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/phono3py

# pseudopotentials (same 4 files as everywhere else; ~60 MB)
mkdir -p ~/pseudos/SSSP-1.3.0-PBE-precision && cd ~/pseudos
curl -sL -o SSSP_1.3.0_PBE_precision.tar.gz 'https://archive.materialscloud.org/records/rcyfm-68h65/files/SSSP_1.3.0_PBE_precision.tar.gz?download=1'
tar -xf SSSP_1.3.0_PBE_precision.tar.gz -C SSSP-1.3.0-PBE-precision

# python venv for stage 2 (phono3py postprocessing)
module load python/3.11
python -m venv ~/venvs/p3
source ~/venvs/p3/bin/activate
pip install --upgrade pip
pip install phonopy phono3py h5py
deactivate
```

Then edit `scripts/slurm/cluster.env`:

- `ACCOUNT=def-CHANGEME` -> the group's allocation string (looks like
  `def-<professor's username>`; visible in CCDB or ask Roy).
- The `quantumespresso` module line -> a version that exists on this cluster
  (`module spider quantumespresso` lists them; any 7.x is fine).

## 4. Launch

```sh
cd ~/scratch/Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/phono3py
bash scripts/slurm/submit_all.sh
```

This submits three chained jobs:

- **stage0** — reference benchmark + k-mesh/cutoff force checks + pristine
  check, then writes `checks/DECISIONS.txt` and generates all 168 inputs at
  the decided settings (same logic as the laptop driver).
- **stage1** — a 168-task job array, one force SCF per task, at most 32
  running at once. Each task health-checks its output and retries once with
  `nk=1` on failure.
- **stage2** — waits until every stage1 task succeeded, then builds
  FORCES_FC3, walks the q-mesh ladder, and writes kappa_L(300-900 K) tables
  into `../results/`.

## 5. Monitor

```sh
squeue -u $USER                      # what is queued/running
tail -f slurm_logs/stage0_*.out      # live stage0 progress
sacct -j <stage1-jobid> --format=JobID,State,Elapsed | tail -20
cat checks/DECISIONS.txt             # after stage0: the decided k-mesh/cutoffs
```

Feasibility sanity check, same rule as always: after stage0, the benchmark
line in `campaign_log.csv` gives one force calculation's wall seconds on 32
cluster cores; the array runs up to 32 of them in parallel, so the whole
stage1 should be a small number of hours, not weeks.

## 6. If some stage1 tasks fail

`sacct -j <stage1-jobid>` shows FAILED indices; each failed run's
`fc_calcs/disp-*/scf.err` says why. After fixing (often just resubmitting is
enough for node-level flukes):

```sh
sbatch --account=$ACCOUNT --array=<failed indices, e.g. 17,42> scripts/slurm/stage1_array.sbatch
# the held stage2 will show DependencyNeverSatisfied — replace it:
scancel <old-stage2-jobid>
sbatch --account=$ACCOUNT scripts/slurm/stage2_post.sbatch
```

## 7. Bring the results home

Recommended: pull from the WSL side with rsync (keeps GitHub credentials off
the shared cluster):

```sh
# from WSL on the workstation
rsync -av --exclude 'tmp/' drac:scratch/Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/phono3py/ \
      ~/Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/phono3py/
rsync -av drac:scratch/Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/results/ \
      ~/Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/results/
```

then commit and push from WSL as usual. (Alternative: add an SSH key on the
cluster to GitHub and push directly from there.)

What comes home: `fc_calcs/*/scf.out` (the raw force records),
`campaign_log*.csv`, `checks/`, `kappa-*.hdf5`, `fc2.hdf5`/`fc3.hdf5`,
`FORCES_FC3`, and `results/kappa_L_first_pass.csv` + `kappa_L_summary.md`.
Raw outputs stay immutable once home, per the workspace rules.

## Approximations unchanged

The cluster port changes *where* the campaign runs, not *what* it computes:
same 2x2x1 supercell, cutoff-pair 4.0 A, displacement set, health checks,
q-mesh ladder, and RTA settings documented in the WORKLOG. kappa_L from this
campaign is still the first-pass value under those documented approximations.

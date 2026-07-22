# Running the phono3py campaign on a Windows workstation

Goal: clone this repo on a Windows machine and run the SrCu2SnS4
force-calculation campaign there. Quantum ESPRESSO needs a Unix environment
with MPI, so everything runs inside **WSL2** (Windows Subsystem for Linux);
Windows itself only hosts it.

## 1. Install WSL2 + Ubuntu (once)

PowerShell **as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Reboot when asked, open "Ubuntu" from the Start menu, create a Linux
username/password. Everything below happens in that Ubuntu terminal.

## 2. Install the toolchain (once)

```sh
# Miniforge (conda)
curl -LO https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b && ~/miniforge3/bin/conda init bash && exec bash

# One environment with QE (parallel, bundled OpenMPI) + phono3py
conda create -n thermo -c conda-forge python=3.11 qe -y
conda activate thermo
pip install phonopy phono3py h5py

# sanity checks
which pw.x && pw.x -h 2>&1 | head -1
phono3py-init -h | head -2
```

## 3. Pseudopotentials (once)

Download **SSSP 1.3.0 PBE precision** from Materials Cloud
(https://www.materialscloud.org/discover/sssp — "SSSP PBE precision v1.3.0"
archive), unpack, and point the pipeline at it:

```sh
mkdir -p ~/pseudos/SSSP-1.3.0-PBE-precision
tar -xf SSSP_1.3.0_PBE_precision.tar.gz -C ~/pseudos/SSSP-1.3.0-PBE-precision
echo 'export SSSP_PBE_PRECISION=$HOME/pseudos/SSSP-1.3.0-PBE-precision' >> ~/.bashrc
exec bash
```

Verify the four files this material needs are present (names must match
`thermo_candidates/SrCu2SnS4/qe/pseudo/manifest.md` exactly):
`Sr_pbe_v1.uspp.F.UPF`, `Cu.paw.z_11.ld1.psl.v1.0.0-low.upf`,
`Sn_pbe_v1.uspp.F.UPF`, `s_pbe_v1.4.uspp.F.UPF`.

## 4. Clone the repo (into the Linux filesystem, NOT /mnt/c)

```sh
cd ~ && git clone https://github.com/qevekaede-dotcom/Waterloo-prof-Holger.git
cd Waterloo-prof-Holger/thermo_candidates/SrCu2SnS4/phono3py
```

(/mnt/c works but file I/O there is several times slower — keep the working
copy in the WSL home directory.)

## 5. Launch the campaign

```sh
conda activate thermo
nproc                       # physical guidance below
QE_NP=<cores> QE_NK=2 nohup bash scripts/run_campaign.sh >> campaign.out 2>&1 &
```

- `QE_NP`: number of MPI ranks — use the number of **physical** cores
  (not hyperthreads), leaving 1-2 free. On the Mac benchmark 12 ranks used
  ~5-6 GB RAM total; scale expectations accordingly.
- The driver is **idempotent**: rerunning the same command resumes wherever
  it stopped. It will automatically (stage 0) run the reference benchmark
  disp-00001 and the k-mesh/cutoff force-convergence checks, then
  (stage 1) all 168 force calculations with health checks, then (stage 2)
  build force constants and compute kappa_L into `../results/`.
- Watch progress: `tail -f campaign.out` and `campaign_log.csv`.
- **Decide feasibility early**: after the benchmark line appears in
  `campaign_log.csv`, multiply its wall_seconds by ~168. If that is weeks
  on this workstation too, stop and wait for cluster access instead
  (see HANDOFF.md).

## 6. Windows-side settings (or the campaign dies overnight)

- Settings -> System -> Power: set "Put my device to sleep" to **Never**
  while plugged in. (WSL pauses when Windows sleeps.)
- Windows Update -> set **active hours** so it does not reboot mid-run;
  ideally pause updates for the campaign duration.
- If the machine has lots of RAM but WSL feels capped: WSL limits itself to
  ~50% of RAM by default; raise it in `C:\Users\<you>\.wslconfig`:

  ```ini
  [wsl2]
  memory=24GB
  ```

  then `wsl --shutdown` and reopen Ubuntu.

## 7. Getting results back

Commit and push from WSL (`git add -A && git commit && git push`), then pull
on the Mac. Raw QE scratch never enters git (`.gitignore`); the derived
tables land in `thermo_candidates/SrCu2SnS4/results/`.

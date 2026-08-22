# Reproducibility: the exact campaign machinery

Verbatim copies of the scripts that produced the fourth-step result, taken
from `thermo_candidates/SrCu2SnS4/phono3py/scripts/` at packaging time
(that location stays authoritative).

- `prepare_inputs.py` — wraps the 168 phono3py supercell fragments with
  the QE header at the decided settings.
- `run_campaign.sh` — resumable driver (stage 0 force-convergence checks
  -> stage 1 force SCFs -> stage 2 postprocess); on SLURM only stage 0
  runs through it (STOP_AFTER hook).
- `compare_forces.py` — the 5e-5 Ry/bohr force-convergence criterion.
- `postprocess.py` — FORCES_FC3, fc2/fc3, q-mesh ladder, kappa_L tables.
- `slurm/` — the Nibi port: `cluster.env` (account, partition, module,
  OMP_NUM_THREADS=1), three chained sbatch stages, `submit_all.sh`,
  `collect_evidence.sh` (forensic snapshots before any rerun).
- `fetch_home.sh` — one-command rsync home + git commit + push.
- `plot_kappa.py` — regenerates `SrCu2SnS4_kappa_L_vs_T.png` from the
  authoritative CSV.

How to rerun on a fresh Alliance cluster: `DRAC_SETUP.md` at the repo
root, sections 1-7 (including the stage-2 virtual-environment recipe and
its traps). The full narrative with every failure: `../WORKLOG.md`.

Material-specific inputs (not copied here; authoritative in the material
workspace): `unitcell.in`, `phono3py_disp.yaml`, the 168
`supercell-*.in` fragments, and `checks/DECISIONS.txt` (k = 3x3x3,
cutoffs 60/480 Ry, decided on-machine). The 24 symmetry-preserving
displacements and the pristine check cell additionally carry
`nosym = .true., noinv = .true.` (QE "lone vector" workaround — see the
write-up, trap 7).

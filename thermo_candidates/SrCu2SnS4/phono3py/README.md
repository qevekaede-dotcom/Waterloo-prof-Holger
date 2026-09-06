# SrCu2SnS4 — phono3py lattice thermal conductivity workspace

Status: the 168-displacement campaign and residual-corrected first-pass
kappa_L(T) are complete on DRAC/Nibi. Do not restart this campaign as part
of resuming a session. Full zT still needs an electronic relaxation-time
model. Task context:
`../../Roy_task_status.md`; running lab notebook:
`../../../fourth step result (phono3py lattice thermal conductivity)/WORKLOG.md`.

## Layout

- `unitcell.in` — copy of the relaxed final SCF input (`../qe/01_scf/`);
  the structural source of truth for displacement generation.
- `phono3py_disp.yaml`, `phono3py.yaml` — displacement dataset
  (2x2x1 supercell, cutoff-pair 4.0 A, tolerance 1e-3 -> P3_121).
- `supercell-XXXXX.in` — 168 phono3py structure fragments (sparse IDs out of
  13,848; only pairs within the 4.0 A cutoff are generated).
- `scripts/prepare_inputs.py` — wraps fragments with the QE header
  (fixed occupations, tprnfor, conv_thr 1e-9) -> `fc_calcs/`. Actual force
  settings selected by checks: 3x3x3, 60/480 Ry for 167 displacements;
  disp-00001 preserves its 90/720 Ry benchmark (force-difference check passed).
- `scripts/run_campaign.sh` — resumable campaign driver (stages 0-2).
- `scripts/compare_forces.py` — k-mesh force-convergence decision (stage 0).
- `scripts/postprocess.py` — FORCES_FC3, fc2/fc3, q-mesh ladder, kappa_L,
  derived tables into `../results/`.
- `fc_calcs/disp-XXXXX/` — one pw.x force SCF per displacement
  (`scf.in`/`scf.out`; `tmp/` is deleted after every run).
- `checks/` — force k-mesh/cutoff checks, `DECISIONS.txt`, and pristine
  force records. The 2x2x2 mesh failed; 60/480 Ry passed against 90/720 Ry.
- `campaign_log.csv` — per-run wall time and status; `FAILED.list` — IDs that
  failed twice (must be empty before stage 2 runs).

## Results and provenance

- `kappa-m13136.hdf5` is the residual-corrected 13x13x6 result behind
  `../results/kappa_L_first_pass.csv`: average 0.3639 W m^-1 K^-1 at
  300 K and 0.1213 at 900 K [calculated, PBE, no SOC, RTA, no NAC].
- `log_cf3.txt` and `slurm_logs/stage2_20311271.out` record `--cfz`
  processing. The pristine maximum force component was 5.4513e-4 Ry/bohr.
- `kappa-m15157.hdf5` is an intentionally retained pre-correction result;
  do not use it as the next point in the corrected q-mesh ladder.
- The last corrected mesh step changes the average by -2.9559%, but zz
  by -12.2745%. The historical ~5% estimate is not a demonstrated tensor
  or total physical uncertainty. Supercell/pair-cutoff convergence is not
  established; the result remains first pass.

## Future runs — cluster only

Use `scripts/slurm/` and [DRAC_SETUP.md](../../../DRAC_SETUP.md) after a new
calculation is requested and parameters are reviewed. Both force calculations
and heavy phonon postprocessing run on DRAC compute nodes. Local machines
perform preparation, transfer, Git, writeup, and lightweight read-only checks.
Consult [HANDOFF.md](../../../HANDOFF.md) before using any historical job IDs.

Before a future run, diagnose the residual-force `awk` in
`scripts/run_campaign.sh`: it reported zero on this Mac for the nonzero
pristine log during the repository audit. No scripts or results were changed.
Resume logic skips completed runs, but this does not make changing parameters
or regenerating existing inputs safe; review provenance and preserve records.
Raw QE outputs stay here (research records — do not rewrite); derived tables
land in `../results/`.

## Known gotchas (details in the WORKLOG)

- phono3py 4.x: setup commands live in `phono3py-init` (not `phono3py`);
  `--version` does not exist; QE cell mode needs `--qe -c unitcell.in`.
- Without `--tolerance 1e-3` the 6-decimal coordinates read as P1 and the
  displacement count explodes (83k instead of 168 within cutoff).
- Cluster traps (OpenMP thread oversubscription, wheel installation,
  symmetry-related fast failures) and their fixes are recorded in the
  fourth-step WORKLOG. Preserve failed logs as evidence.

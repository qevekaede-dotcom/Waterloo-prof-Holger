# SrCu2SnS4 — phono3py lattice thermal conductivity workspace

Goal: third-order force constants -> phonon-phonon scattering -> kappa_L(T),
the missing denominator of the zT_e values in `../results/`. Task context:
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
  (90/720 Ry, fixed occupations, tprnfor, conv_thr 1e-9) -> `fc_calcs/`.
- `scripts/run_campaign.sh` — resumable campaign driver (stages 0-2).
- `scripts/compare_forces.py` — k-mesh force-convergence decision (stage 0).
- `scripts/postprocess.py` — FORCES_FC3, fc2/fc3, q-mesh ladder, kappa_L,
  derived tables into `../results/`.
- `fc_calcs/disp-XXXXX/` — one pw.x force SCF per displacement
  (`scf.in`/`scf.out`; `tmp/` is deleted after every run).
- `kcheck/` — stage-0 k-mesh check (2x2x2 vs 3x3x3) and `DECISION.txt`.
- `campaign_log.csv` — per-run wall time and status; `FAILED.list` — IDs that
  failed twice (must be empty before stage 2 runs).

## How to run / resume

```sh
cd "$(dirname "$0")"  # this directory
nohup caffeinate -i bash scripts/run_campaign.sh >> campaign.out 2>&1 &
```

The driver skips completed runs, so rerunning after an interruption is safe.
Raw QE outputs stay here (research records — do not rewrite); derived tables
land in `../results/`.

## Known gotchas (details in the WORKLOG)

- phono3py 4.x: setup commands live in `phono3py-init` (not `phono3py`);
  `--version` does not exist; QE cell mode needs `--qe -c unitcell.in`.
- Without `--tolerance 1e-3` the 6-decimal coordinates read as P1 and the
  displacement count explodes (83k instead of 168 within cutoff).
- Keep the laptop lid open on mains power; closed lid sleeps even under
  caffeinate.

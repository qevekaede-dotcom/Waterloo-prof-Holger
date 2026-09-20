# Reproducibility: archival rejected campaign record

This directory is an archival record of the rejected historical SrCu2SnS4
campaign, not a runnable workflow. Its scripts are deliberately fail-closed
before any write, job submission, QE execution, force-constant construction,
or evidence snapshot. Do not use them to rerun, repair, or extend the result.
Any new calculation must start from a new empty RUN_DIR and use the v2
workflow with its own immutable run fingerprint and evidence gates.

- `prepare_inputs.py` — retired historical input generator; exits before writes.
- `run_campaign.sh` — retired historical driver; exits before execution.
- `compare_forces.py` — read-only historical force comparison helper.
- `postprocess.py` — retired historical postprocessor; exits before execution.
- `slurm/` — archived Nibi port. All submit, stage, and evidence-snapshot
  entrypoints now exit before any action; `cluster.env` is historical context.
- `fetch_home.sh` — retired archival fetch/commit helper; exits before action.
- `plot_kappa.py` — a visualization helper for the authoritative historical
  CSV; it does not validate or revive the rejected calculation.

The full historical narrative is in `../WORKLOG.md`; it is not a rerun guide.

Material-specific inputs (not copied here; authoritative in the material
workspace): `unitcell.in`, `phono3py_disp.yaml`, the 168
`supercell-*.in` fragments, and `checks/DECISIONS.txt` (k = 3x3x3,
cutoffs 60/480 Ry, decided on-machine). The 24 symmetry-preserving
displacements and the pristine check cell additionally carry
`nosym = .true., noinv = .true.` (QE "lone vector" workaround — see the
write-up, trap 7).

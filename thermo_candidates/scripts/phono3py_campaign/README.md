# Gated QE/phono3py campaign driver

This directory is the shared, fail-closed workflow used by the pending
SrZrS3 and Rb2Cu2SnS4 campaigns. Material-specific scientific settings live
in each material's `phono3py/campaign.json`; this directory provides strict QE
input/output handling, immutable provenance, compute-node guards, and safe
Slurm submission.

## Released boundary

The currently released path is:

1. `validate-config` and `prepare-relax` on a login/preparation node;
2. when a previously accepted structure has the same structure policy but an
   older preflight policy, `accepted_structure_import.py` may replay and archive
   the complete accepted relaxation into a fresh, self-contained run directory;
   imported runs cannot execute or finalize another relaxation;
3. after an explicitly audited terminal BFGS failure, `relax_recovery.py`
   may create one separate immutable continuation run from the failed output's
   hashed final coordinates; it copies no QE scratch, keeps the original
   geometry as the cumulative-displacement reference, and does not loosen any
   setting or acceptance gate;
4. for Rb2Cu2SnS4 only, after the single automatic reset is exhausted,
   `polish_recovery.py` may run the reviewed three-SCF force-consistency
   diagnostic and release at most one fresh BFGS polish; the diagnostic itself
   never accepts a structure or unlocks preflight;
5. fixed-cell tight `relax` plus a setting-matched independent pristine SCF
   inside a Nibi Slurm allocation;
6. `finalize-relax`, which publishes a structure only if completion, BFGS,
   force, cell, atom-order, position-shift, and symmetry checks all pass;
7. compute-node-only `preflight`, which enumerates configured phono3py
   displacement candidates and audits units, IDs, matrices, cells, counts,
   and hard caps without running displaced-force calculations;
8. explicit signed pilot-dataset, resource-receipt, force-task, raw-evidence,
   and pilot-analysis paths. These paths remain bounded by the six-SCF initial
   timing/noise composition and the configured concurrency and cumulative
   pilot limits; none may bypass the accepted-structure or selection gates;
9. evidence-only `collect`, normally submitted with `afterany` so a failed
   primary job still leaves a machine-readable record.

After an explicitly selected and fully collected production force campaign,
`plan-force-finalize` and `finalize-force` replay the task maps, settings,
pristine references, scheduler/submission records, raw task evidence, backend
hashes, and the cumulative budget ledger before publishing a force-dataset
gate. This gate says only that FC2/FC3 construction may begin; it is not a
phonon or thermal-conductivity result.

Production force submission, `postprocess`, and final `audit` remain
deliberately blocked while the material configs retain null scientific
selections and no approved per-material core-hour budget. The public
`postprocess` and final `audit` commands are not yet released implementations,
even after a future selection. Implemented diagnostic, pilot, finalization,
and Slurm machinery is not evidence that a calculation is authorized or has
run. Production is released only after real preflight and force/amplitude
evidence supports an explicit material-specific selection and measured
resource budget.

## Submission contract

`submit.py plan` is read-only. `submit.py execute` runs only on a Nibi login
node and requires the exact full configuration SHA printed by a fresh plan.
It derives the Slurm account from `scheduler.slurm_account`, exports absolute
config/run/workflow paths, uses a new attempt ID, writes immutable request and
response records, and blocks active or uncertain duplicate submissions.

Relax and force submissions receive a distinct `afterany` collector job.
An `sbatch` success response without a parseable job ID is treated as
potentially active and cannot be retried until manually reconciled with the
scheduler. Force array bounds, when that stage is later released, must equal
the exact `0..N-1` domain in an immutable task map.

## Provenance model

The run manifest stores independent structure and preflight scientific-policy
hashes. Later filling of the production selection therefore does not rewrite
or invalidate earlier evidence, while changes to any policy actually consumed
by a released stage are rejected. Full config hashes are still recorded at
preparation, launch, and submission time.

Every heavy command refuses to run without Slurm compute-node context. Runtime
outputs belong in a scratch run directory outside the Git repository and
outside every frozen `READY_TO_ATTACH` directory. No heavy QE or phono3py
postprocessing is intended for a local workstation.

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
   `submit.py` exposes a versioned `diagnostic` Slurm stage for the reviewed
   three-SCF force-consistency check; it is available only after
   `prepare-lineage`, consumes one immutable attempt, uses the explicit
   `scheduler.diagnostic_resources` allocation, receives a distinct
   evidence-only `afterany` collector, and never accepts a structure or
   releases the BFGS polish by itself. The first
   immutable submission request or started Slurm dispatch consumes that
   RUN_DIR's only diagnostic opportunity, including startup/node failures;
   retry requires a separately reviewed new run rather than reuse of the old
   lineage directory;
5. fixed-cell tight `relax` plus a setting-matched independent pristine SCF
   inside a Nibi Slurm allocation;
6. `finalize-relax`, which publishes a structure only if completion, BFGS,
   force, cell, atom-order, position-shift, and symmetry checks all pass;
7. compute-node-only `preflight`, which enumerates configured phono3py
   displacement candidates and audits units, IDs, matrices, cells, counts,
   and hard caps without running displaced-force calculations. An optional
   repeated `--candidate-id` list selects a nonempty, duplicate-free subset;
   its canonical SHA256 binds the exact config enumeration and preflight
   policy through plan, Slurm export, attempt context, CLI, and inventory.
   Omitting the option retains the full configured enumeration;
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
It derives the Slurm account from `scheduler.slurm_account`, passes an explicit
Slurm export allow-list (never `ALL`), exports absolute config/run/workflow
paths and their hashes, uses a new attempt ID, writes immutable request and
response records, and blocks active or uncertain duplicate submissions.
`cluster.env` clears shell/Python startup hooks and fixes the campaign CLI,
module versions, Python environment, pseudopotential location, QE launcher,
pool count, and OpenMP count from version-controlled values or the scheduler
account identity; caller-provided runner/module overrides are not accepted.

Diagnostic, relax, and force submissions receive a distinct `afterany`
collector job. Preflight does not. Diagnostic resources are all passed as
explicit `sbatch` overrides from the material configuration; the diagnostic
script contains no hidden allocation defaults. Its collector preserves the
extended raw `sacct` allocation fields and cannot publish a scientific gate.
Diagnostic finalization requires one unique same-ID submission, dispatch
claim, primary wrapper, execution record, collector submission/wrapper,
collection receipt, and raw scheduler allocation. It replays all hashes and
requires the primary allocation to be `COMPLETED` with exit `0:0`, the exact
account/partition/node/CPU/time policy, and an equivalent total memory request.
An `sbatch` success response without a parseable job ID is treated as
potentially active and cannot be retried until manually reconciled with the
scheduler. Force array bounds, when that stage is later released, must equal
the exact `0..N-1` domain in an immutable task map.

For a targeted preflight, repeat the same candidate arguments in `plan` and
`execute`; `execute` still requires the plan's exact full config SHA256:

```text
submit.py plan --stage preflight ... \
  --candidate-id sr_fc3_2x1x1__sr_cutoff_3p70A \
  --candidate-id sr_fc3_3x1x1__sr_cutoff_3p70A
submit.py execute --stage preflight ... --expect-config-sha <plan config SHA256> \
  --expect-candidate-subset-sha <plan candidate_subset_sha256> \
  --candidate-id sr_fc3_2x1x1__sr_cutoff_3p70A \
  --candidate-id sr_fc3_3x1x1__sr_cutoff_3p70A
```

No-cutoff rows are derived only when the same selected attempt actually ran a
cutoff-pair parent for that supercell. A subset that omits that parent records
the no-cutoff row as skipped instead of failing or borrowing an older count.
Subset inventories set `requested_scope_complete=true` but keep both
`preflight_complete` and `full_config_preflight_complete` false, so they cannot
be consumed as a full pilot/production preflight.

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

For the reviewed Rb diagnostic, `prepare-lineage` copies the exact launch-time
UPF bytes into `lineage_source/pseudopotentials/`; generated SCF inputs point
only at that archive. Submission, runtime, finalization, and release rehash
every archived UPF. Diagnostic, submission, Slurm-attempt, dispatch-claim, and
scientific-attempt paths are checked component by component and may not contain
symbolic links or resolve outside the run directory.

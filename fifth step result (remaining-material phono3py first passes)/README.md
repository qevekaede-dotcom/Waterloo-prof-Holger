# Remaining-material phono3py first passes

This is a small, read-only index for the two remaining material phonon first
passes.  It deliberately contains no raw QE output, force-constant HDF5,
thermal-conductivity HDF5, copied input trees, or `READY_TO_ATTACH/` directory.
Those records remain in the material workspaces (and, where noted, in immutable
DRAC run directories).

## Scientific disposition

| Material | What was completed | Honest current status | Lattice thermal conductivity |
| --- | --- | --- | --- |
| SrZrS3 | All 788 pristine-plus-displacement force tasks were accounted for; FC2 and FC3 passed shape/finite integrity checks. | `first_pass_unconverged` and rejected: the explicit non-NAC 12x5x3 mesh has imaginary modes. | No valid kappa_L. The finite tensor is a rejected diagnostic and must not be used for zT. |
| Rb2Cu2SnS4 | FIRE, pristine, preflight, and force-pilot gates passed. Of the original production array, the 361 recovery is valid; element 462 failed during QE module start-up. | Incomplete. Narrow recovery `22312416` and its dependent postprocess `22312417` have been submitted; at this record point only their queued state is confirmed. | No FC2, FC3, q-mesh result, or kappa_L is available. |

The statuses above are deliberately not interchangeable: a scheduler submission
or a finite HDF5 file is not scientific acceptance.  These are PBE/RTA
first-pass screens, without the convergence evidence needed for an intrinsic
material property; see the material evidence for their separate limits.

## Evidence map

- SrZrS3: [rejected first-pass evidence](../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/README.md), [machine-readable audit](../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json), and [rejected diagnostic CSV](../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/kappa_m1253_rejected_diagnostic.csv).
- Rb2Cu2SnS4: [campaign overview](../thermo_candidates/Rb2Cu2SnS4/phono3py/README.md), [curated first-pass evidence](../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/README.md), [task-462 recovery submission record](../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/recovery462_submission_20260920.json), and the [original production task map](../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/task_map.tsv).
- [Results index](results/README.md) distinguishes the rejected Sr diagnostic from an accepted result. [Reproducibility index](reproducibility/README.md) points to source inputs and scripts without copying them.

## Rb recovery boundary

The historical production job `21934047` is not being rerun wholesale. Its
original element 361 was recovered; element 462 (`disp03843`) failed before
scientific calculation because the QE module could not start. The old dependent
postprocess `21934081` remains untouched. The narrow replacement chain is
`22312416` followed by `22312417`; this package records only that the chain was
submitted and observed queued, not that either job ran, completed, audited,
or produced force constants.

See [SESSION_MEMORY.md](SESSION_MEMORY.md) for the continuation boundary and
[WORKLOG.md](WORKLOG.md) for this package-assembly entry.
